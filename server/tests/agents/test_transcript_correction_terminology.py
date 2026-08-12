from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import os
import tempfile
import unittest
from unittest import mock

from yap_server.agents.transcript_correction_terminology import (
    PersonalOrganizationTerminologyMemberships,
    PostgresTranscriptCorrectionTerminologyResolver,
    read_private_postgres_dsn,
)
from yap_server.agents.transcript_correction_service import (
    TranscriptCorrectionTerminologyUnavailable,
)
from yap_server.auth import AuthenticatedPrincipal, PrincipalKey
from yap_server.knowledge.terminology_snapshot import (
    TerminologyRecord,
    freeze_terminology_snapshot,
)


def _principal(subject: str = "alice") -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        tenant_id="tenant-a",
        subject_id=subject,
        client_id="desktop",
        scopes=frozenset(),
    )


class TranscriptCorrectionTerminologyTests(unittest.TestCase):
    def test_resolver_freezes_server_owned_snapshot_and_exact_forms(self) -> None:
        principal = _principal()
        snapshot = freeze_terminology_snapshot(
            (
                TerminologyRecord(
                    record_id="dose",
                    tenant_id="tenant-a",
                    scope="personal",
                    owner_id="alice",
                    locale="en-US",
                    canonical_form="Dosage",
                    variants=("dosage",),
                    sensitivity="internal",
                    version=1,
                    deleted=False,
                    audit_revision="audit-1",
                    changed_at="2026-08-11T12:00:00Z",
                ),
            ),
            principal=principal.key,
            team_ids=(),
            locale="en-US",
            source_revision="ledger-1",
        )
        seen: list[object] = []

        @contextmanager
        def connection_factory():
            connection = object()
            seen.append(connection)
            yield connection

        resolver = PostgresTranscriptCorrectionTerminologyResolver(
            connection_factory=connection_factory,
            memberships=PersonalOrganizationTerminologyMemberships(),
        )
        with mock.patch(
            "yap_server.agents.transcript_correction_terminology."
            "store_current_terminology_snapshot",
            return_value=snapshot,
        ) as store:
            resolved = resolver.resolve(
                principal=principal,
                locale="en-US",
            )

        self.assertEqual(resolved.snapshot_sha256, snapshot.snapshot_sha256)
        self.assertEqual(resolved.exact_forms, ("Dosage",))
        store.assert_called_once()
        self.assertIs(store.call_args.args[0], seen[0])
        self.assertEqual(store.call_args.kwargs["locale"], "en-US")
        self.assertEqual(
            store.call_args.kwargs["authorization"].principal,
            principal.key,
        )
        self.assertEqual(store.call_args.kwargs["authorization"].team_ids, ())

    def test_database_failure_is_publicly_classified_as_unavailable(self) -> None:
        @contextmanager
        def connection_factory():
            raise OSError("private database detail")
            yield  # pragma: no cover

        resolver = PostgresTranscriptCorrectionTerminologyResolver(
            connection_factory=connection_factory,
            memberships=PersonalOrganizationTerminologyMemberships(),
        )
        with self.assertRaises(TranscriptCorrectionTerminologyUnavailable) as raised:
            resolver.resolve(
                principal=_principal(),
                locale="en-US",
            )
        self.assertNotIn("private", str(raised.exception))

    def test_private_dsn_file_is_bounded_and_owner_private(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "knowledge.dsn"
            path.write_text("dbname=yap\n", encoding="utf-8")
            path.chmod(0o600)
            self.assertEqual(read_private_postgres_dsn(path), "dbname=yap")

            path.write_text("dbname=yap\nsslmode=require\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "invalid"):
                read_private_postgres_dsn(path)

            if os.name == "posix":
                path.write_text("dbname=yap", encoding="utf-8")
                path.chmod(0o644)
                with self.assertRaisesRegex(ValueError, "owner-private"):
                    read_private_postgres_dsn(path)

    def test_membership_boundary_never_invents_team_authority(self) -> None:
        resolver = PersonalOrganizationTerminologyMemberships()
        self.assertEqual(resolver.team_ids_for(PrincipalKey("tenant-a", "alice")), ())


if __name__ == "__main__":
    unittest.main()
