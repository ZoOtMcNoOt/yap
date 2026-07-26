from __future__ import annotations

from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
import sqlite3
import tempfile
import unittest

from yap_server.auth import AuthenticatedPrincipal, PrincipalKey
from yap_server.auth.identity_repository import (
    AuditChainInvalid,
    PurposeGrantMetadata,
    SqliteIdentityRepository,
)


TENANT_ID = "11111111-1111-4111-8111-111111111111"
SUBJECT_ID = "22222222-2222-4222-8222-222222222222"
ADMIN_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
CLIENT_ID = "33333333-3333-4333-8333-333333333333"


class _Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, seconds: int = 1) -> None:
        self.value += timedelta(seconds=seconds)


def _principal(
    subject_id: str = SUBJECT_ID,
    *,
    issued_at_unix: int = 1_774_699_199,
) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        tenant_id=TENANT_ID,
        subject_id=subject_id,
        client_id=CLIENT_ID,
        scopes=frozenset({"access_as_user"}),
        issued_at_unix=issued_at_unix,
    )


class IdentityRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "identity.sqlite3"
        self.clock = _Clock()
        self.repository = SqliteIdentityRepository(
            self.path,
            clock=self.clock,
        )
        self.user = _principal()
        self.admin = _principal(ADMIN_ID)

    def tearDown(self) -> None:
        self.repository.close()
        self.temporary.cleanup()

    def test_principal_upsert_is_minimal_and_persists_across_restart(self) -> None:
        record = self.repository.upsert_principal(
            self.user,
            display_name_snapshot="Yap Test User",
        )
        self.assertEqual(record.key, self.user.key)
        self.assertEqual(record.display_name_snapshot, "Yap Test User")
        self.assertTrue(self.repository.access_is_allowed(self.user))

        self.repository.close()
        self.repository = SqliteIdentityRepository(
            self.path,
            clock=self.clock,
        )
        persisted = self.repository.principal(self.user.key)
        self.assertIsNotNone(persisted)
        self.assertEqual(persisted.display_name_snapshot, "Yap Test User")
        self.repository.verify_audit_chain()

        with closing(sqlite3.connect(self.path)) as connection:
            columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(principal_identity)")
            }
        self.assertEqual(
            columns,
            {
                "tenant_id",
                "subject_id",
                "display_name_snapshot",
                "created_at_utc",
                "last_seen_at_utc",
                "access_revoked_after_unix",
            },
        )

    def test_access_revocation_rejects_old_tokens_and_allows_newer_tokens(self) -> None:
        issued_at = int(self.clock().timestamp()) - 1
        user = _principal(issued_at_unix=issued_at)
        self.repository.upsert_principal(user)
        self.repository.upsert_principal(self.admin)

        epoch = self.repository.revoke_access(self.admin.key, user.key)

        self.assertEqual(epoch, int(self.clock().timestamp()))
        self.assertFalse(self.repository.access_is_allowed(user))
        self.clock.advance()
        self.assertTrue(
            self.repository.access_is_allowed(
                _principal(issued_at_unix=int(self.clock().timestamp()))
            )
        )

    def test_purpose_grant_and_revocation_are_separate_revisioned_controls(
        self,
    ) -> None:
        self.repository.upsert_principal(self.user)
        self.repository.upsert_principal(self.admin)
        metadata = PurposeGrantMetadata(
            grant_id="55555555-5555-4555-8555-555555555555",
            legal_basis_code="deployment-approved-basis",
            privacy_assessment_ref="pia-2026-07",
            notice_version="notice-v1",
        )

        granted_epoch = self.repository.grant_purpose(
            self.admin.key,
            self.user.key,
            purpose="matching",
            metadata=metadata,
        )
        self.assertEqual(granted_epoch, 1)
        self.assertTrue(self.repository.purpose_is_active(self.user.key, "matching"))
        self.assertFalse(self.repository.purpose_is_active(self.user.key, "adaptation"))

        revoked_epoch = self.repository.revoke_purpose(
            self.admin.key,
            self.user.key,
            purpose="matching",
        )
        self.assertEqual(revoked_epoch, 2)
        self.assertFalse(self.repository.purpose_is_active(self.user.key, "matching"))

        with closing(sqlite3.connect(self.path)) as connection:
            revisions = connection.execute(
                """
                SELECT epoch, state, grant_id
                FROM purpose_grant_revision
                ORDER BY epoch
                """
            ).fetchall()
        self.assertEqual(
            revisions,
            [
                (1, "granted", metadata.grant_id),
                (2, "revoked", metadata.grant_id),
            ],
        )

    def test_audit_chain_is_redacted_and_tampering_is_detected_on_restart(self) -> None:
        self.repository.upsert_principal(self.user)
        events = self.repository.audit_events()
        self.assertEqual(len(events), 1)
        serialized = str(events[0])
        self.assertNotIn("access_as_user", serialized)
        self.assertNotIn("Bearer", serialized)
        self.assertNotIn("token", serialized.casefold())

        self.repository.close()
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute(
                "UPDATE authorization_audit SET event_json = '{}' WHERE sequence = 1"
            )
            connection.commit()

        with self.assertRaises(AuditChainInvalid):
            self.repository = SqliteIdentityRepository(
                self.path,
                clock=self.clock,
            )

    def test_cross_tenant_or_unknown_targets_are_not_created_by_mutation(self) -> None:
        self.repository.upsert_principal(self.admin)
        unknown = PrincipalKey(
            tenant_id="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            subject_id=SUBJECT_ID,
        )

        with self.assertRaises(KeyError):
            self.repository.revoke_access(self.admin.key, unknown)
        self.assertIsNone(self.repository.principal(unknown))
