from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import tempfile
import unittest

from yap_server.auth import AuthenticatedPrincipal
from yap_server.auth.identity_repository import (
    PurposeGrantMetadata,
    SqliteIdentityRepository,
)
from yap_server.auth.purpose_authorization import (
    AuthorizationDenied,
    IdentityAuthorizationPolicy,
    IdentityAuthorizationService,
)


TENANT_ID = "11111111-1111-4111-8111-111111111111"
OTHER_TENANT_ID = "99999999-9999-4999-8999-999999999999"
USER_ID = "22222222-2222-4222-8222-222222222222"
ADMIN_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
CLIENT_ID = "33333333-3333-4333-8333-333333333333"
ADMIN_ROLE = "Yap.IdentityAdministrator"


def _principal(
    subject_id: str,
    *,
    tenant_id: str = TENANT_ID,
    roles: frozenset[str] = frozenset(),
) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        tenant_id=tenant_id,
        subject_id=subject_id,
        client_id=CLIENT_ID,
        scopes=frozenset({"access_as_user"}),
        issued_at_unix=1_774_699_199,
        roles=roles,
    )


def _metadata(seed: int) -> PurposeGrantMetadata:
    return PurposeGrantMetadata(
        grant_id=f"{seed:08x}-5555-4555-8555-555555555555",
        legal_basis_code="deployment-approved-basis",
        privacy_assessment_ref="pia-2026-07",
        notice_version="notice-v1",
    )


class PurposeAuthorizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.repository = SqliteIdentityRepository(
            Path(self.temporary.name) / "identity.sqlite3",
            clock=lambda: datetime(2026, 7, 25, 12, 0, tzinfo=UTC),
        )
        self.user = _principal(USER_ID)
        self.admin = _principal(ADMIN_ID, roles=frozenset({ADMIN_ROLE}))
        self.repository.upsert_principal(self.user)
        self.repository.upsert_principal(self.admin)
        self.service = IdentityAuthorizationService(
            self.repository,
            policy=IdentityAuthorizationPolicy(
                administrator_roles=frozenset({ADMIN_ROLE})
            ),
        )

    def tearDown(self) -> None:
        self.repository.close()
        self.temporary.cleanup()

    def test_ordinary_principal_cannot_self_grant_or_mutate_access(self) -> None:
        with self.assertRaisesRegex(AuthorizationDenied, "not authorized"):
            self.service.grant_purpose(
                self.user,
                self.user.key,
                purpose="enrollment",
                metadata=_metadata(1),
            )
        with self.assertRaisesRegex(AuthorizationDenied, "not authorized"):
            self.service.revoke_access(self.user, self.user.key)

        self.assertFalse(self.repository.purpose_is_active(self.user.key, "enrollment"))
        self.assertTrue(self.repository.access_is_allowed(self.user))
        denied = [
            event
            for event in self.repository.audit_events()
            if event["action"].startswith("authorization.control.")
        ]
        self.assertEqual(
            [(event["action"], event["outcome"]) for event in denied],
            [
                ("authorization.control.grant_purpose", "denied"),
                ("authorization.control.revoke_access", "denied"),
            ],
        )

    def test_voice_operations_fail_closed_until_every_required_grant_is_active(
        self,
    ) -> None:
        with self.assertRaises(AuthorizationDenied):
            self.service.authorize_enrollment(self.user)

        self.service.grant_purpose(
            self.admin,
            self.user.key,
            purpose="enrollment",
            metadata=_metadata(1),
        )
        enrollment = self.service.authorize_enrollment(self.user)
        self.assertEqual(enrollment.purpose_epochs, (("enrollment", 1),))

        with self.assertRaises(AuthorizationDenied):
            self.service.authorize_matching(self.user)
        self.service.grant_purpose(
            self.admin,
            self.user.key,
            purpose="matching",
            metadata=_metadata(2),
        )
        matching = self.service.authorize_matching(self.user)
        self.assertEqual(
            matching.purpose_epochs,
            (("enrollment", 1), ("matching", 1)),
        )

        with self.assertRaises(AuthorizationDenied):
            self.service.authorize_adaptation(self.user)
        self.service.grant_purpose(
            self.admin,
            self.user.key,
            purpose="adaptation",
            metadata=_metadata(3),
        )
        self.assertEqual(
            self.service.authorize_adaptation(self.user).purpose_epochs,
            (("adaptation", 1), ("enrollment", 1), ("matching", 1)),
        )

        self.service.revoke_purpose(
            self.admin,
            self.user.key,
            purpose="matching",
        )
        with self.assertRaises(AuthorizationDenied):
            self.service.authorize_matching(self.user)
        with self.assertRaises(AuthorizationDenied):
            self.service.authorize_adaptation(self.user)

    def test_control_authorization_and_mutation_share_one_transaction(self) -> None:
        statements: list[str] = []
        connection = self.repository._active_connection()
        connection.set_trace_callback(statements.append)
        try:
            self.service.grant_purpose(
                self.admin,
                self.user.key,
                purpose="enrollment",
                metadata=_metadata(1),
            )
        finally:
            connection.set_trace_callback(None)

        transaction_statements = [
            statement
            for statement in statements
            if statement in {"BEGIN IMMEDIATE", "COMMIT", "ROLLBACK"}
        ]
        self.assertEqual(transaction_statements, ["BEGIN IMMEDIATE", "COMMIT"])
        self.assertEqual(
            [
                (event["action"], event["outcome"])
                for event in self.repository.audit_events()[-2:]
            ],
            [
                ("authorization.control.grant_purpose", "allowed"),
                ("purpose.granted", "succeeded"),
            ],
        )

    def test_revoked_principal_is_denied_even_with_active_grants(self) -> None:
        self.service.grant_purpose(
            self.admin,
            self.user.key,
            purpose="enrollment",
            metadata=_metadata(1),
        )
        self.service.revoke_access(self.admin, self.user.key)

        with self.assertRaises(AuthorizationDenied):
            self.service.authorize_enrollment(self.user)
        event = self.repository.audit_events()[-1]
        self.assertEqual(event["action"], "authorization.voice.enrollment")
        self.assertEqual(event["outcome"], "denied")
        self.assertEqual(event["reason"], "principal_access_denied")

    def test_self_deletion_intent_and_admin_completion_are_redacted_audits(
        self,
    ) -> None:
        intent = self.service.record_deletion_intent(self.user, self.user.key)
        with self.assertRaises(AuthorizationDenied):
            self.service.record_deletion_completion(self.user, intent)
        self.service.record_deletion_completion(self.admin, intent)

        events = self.repository.audit_events()
        deletion = [
            event for event in events if event["action"].startswith("deletion.")
        ]
        self.assertEqual(
            [(event["action"], event["outcome"]) for event in deletion],
            [
                ("deletion.intent", "recorded"),
                ("deletion.completion", "recorded"),
            ],
        )
        self.assertEqual(
            {event["operationId"] for event in deletion},
            {intent.operation_id},
        )
        serialized = str(deletion)
        self.assertNotIn("access_as_user", serialized)
        self.assertNotIn("Bearer", serialized)
        self.assertNotIn("token", serialized.casefold())
        self.repository.verify_audit_chain()

    def test_cross_tenant_admin_role_is_not_cross_tenant_authority(self) -> None:
        other = _principal(
            "88888888-8888-4888-8888-888888888888",
            tenant_id=OTHER_TENANT_ID,
            roles=frozenset({ADMIN_ROLE}),
        )
        self.repository.upsert_principal(other)

        with self.assertRaises(AuthorizationDenied):
            self.service.grant_purpose(
                other,
                self.user.key,
                purpose="enrollment",
                metadata=_metadata(1),
            )
        self.assertFalse(self.repository.purpose_is_active(self.user.key, "enrollment"))
        denied = self.repository.audit_events()[-1]
        self.assertEqual(
            denied["action"],
            "authorization.control.grant_purpose",
        )
        self.assertEqual(
            denied["target"],
            {
                "tenantId": other.tenant_id,
                "subjectId": other.subject_id,
            },
        )


if __name__ == "__main__":
    unittest.main()
