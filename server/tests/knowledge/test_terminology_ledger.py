from __future__ import annotations

import os
import unittest
from uuid import uuid4

import psycopg

from yap_server.agents.transcript_correction_terminology import (
    PersonalOrganizationTerminologyMemberships,
    PostgresTranscriptCorrectionTerminologyResolver,
)
from yap_server.auth.principal import AuthenticatedPrincipal, PrincipalKey
from yap_server.knowledge.terminology_authorization import (
    resolve_terminology_authorization,
)
from yap_server.knowledge.terminology_ledger import (
    append_terminology_record,
    bind_job_terminology_snapshot,
    install_terminology_schema,
    read_job_terminology_snapshot,
    store_current_terminology_snapshot,
)
from yap_server.knowledge.terminology_snapshot import TerminologyRecord


POSTGRES_DSN = os.environ.get("YAP_TEST_POSTGRES_DSN")


@unittest.skipUnless(POSTGRES_DSN, "YAP_TEST_POSTGRES_DSN is not configured")
class TerminologyLedgerTests(unittest.TestCase):
    def test_scribe_freezes_owner_specific_terms_before_shared_admission(self) -> None:
        suffix = uuid4().hex
        tenant_id = f"tenant-{suffix}"
        alice = PrincipalKey(tenant_id, f"alice-{suffix}")
        bob = PrincipalKey(tenant_id, f"bob-{suffix}")
        with psycopg.connect(POSTGRES_DSN) as connection:
            install_terminology_schema(connection)
            append_terminology_record(
                connection,
                _record(tenant_id, alice.subject_id, 1, "AliceTerm"),
                authorization=_authorization(alice),
            )
        resolver = PostgresTranscriptCorrectionTerminologyResolver(
            connection_factory=lambda: psycopg.connect(POSTGRES_DSN),
            memberships=PersonalOrganizationTerminologyMemberships(),
        )

        alice_terms = resolver.resolve(
            principal=_authenticated(alice),
            locale="en-US",
        )
        bob_terms = resolver.resolve(
            principal=_authenticated(bob),
            locale="en-US",
        )
        repeated_alice_terms = resolver.resolve(
            principal=_authenticated(alice),
            locale="en-US",
        )

        self.assertEqual(alice_terms.exact_forms, ("AliceTerm",))
        self.assertEqual(bob_terms.exact_forms, ())
        self.assertNotEqual(
            alice_terms.snapshot_sha256,
            bob_terms.snapshot_sha256,
        )
        self.assertEqual(repeated_alice_terms, alice_terms)
        with psycopg.connect(POSTGRES_DSN) as connection:
            binding_count = connection.execute(
                """SELECT count(*) FROM yap_terminology_job_bindings
                   WHERE tenant_id = %s""",
                (tenant_id,),
            ).fetchone()
            snapshot_count = connection.execute(
                """SELECT count(*) FROM yap_terminology_snapshots
                   WHERE tenant_id = %s""",
                (tenant_id,),
            ).fetchone()
            self.assertEqual(binding_count, (0,))
            self.assertEqual(snapshot_count, (2,))
            connection.execute(
                "DELETE FROM yap_terminology_job_bindings WHERE tenant_id = %s",
                (tenant_id,),
            )
            connection.execute(
                "DELETE FROM yap_terminology_snapshots WHERE tenant_id = %s",
                (tenant_id,),
            )
            connection.execute(
                "DELETE FROM yap_terminology_records WHERE tenant_id = %s",
                (tenant_id,),
            )

    def test_job_binding_remains_frozen_after_a_new_record_version(self) -> None:
        suffix = uuid4().hex
        tenant_id = f"tenant-{suffix}"
        principal = PrincipalKey(tenant_id, f"alice-{suffix}")
        job_id = f"job-{suffix}"
        first = _record(tenant_id, principal.subject_id, 1, "TAVI")
        second = _record(tenant_id, principal.subject_id, 2, "TAVR")

        with psycopg.connect(POSTGRES_DSN) as connection:
            install_terminology_schema(connection)
            authorization = _authorization(principal)
            append_terminology_record(
                connection, first, authorization=authorization
            )
            bound = bind_job_terminology_snapshot(
                connection,
                job_id=job_id,
                authorization=authorization,
                locale="en-US",
            )
            append_terminology_record(
                connection, second, authorization=authorization
            )
            unchanged = read_job_terminology_snapshot(
                connection, principal=principal, job_id=job_id
            )
            next_job = bind_job_terminology_snapshot(
                connection,
                job_id=f"next-{job_id}",
                authorization=authorization,
                locale="en-US",
            )

            self.assertEqual(unchanged, bound)
            self.assertEqual(bound.variant_map["tavi"], "TAVI")
            self.assertEqual(next_job.variant_map["tavi"], "TAVR")
            self.assertNotEqual(bound.snapshot_sha256, next_job.snapshot_sha256)
            connection.execute(
                "DELETE FROM yap_terminology_job_bindings WHERE tenant_id = %s",
                (tenant_id,),
            )
            connection.execute(
                "DELETE FROM yap_terminology_snapshots WHERE tenant_id = %s",
                (tenant_id,),
            )
            connection.execute(
                "DELETE FROM yap_terminology_records WHERE tenant_id = %s",
                (tenant_id,),
            )
            connection.commit()

    def test_current_snapshot_rejects_conflicting_persisted_identity(self) -> None:
        suffix = uuid4().hex
        tenant_id = f"tenant-{suffix}"
        principal = PrincipalKey(tenant_id, f"alice-{suffix}")
        with psycopg.connect(POSTGRES_DSN) as connection:
            install_terminology_schema(connection)
            snapshot = store_current_terminology_snapshot(
                connection,
                authorization=_authorization(principal),
                locale="en-US",
            )
            connection.execute(
                """UPDATE yap_terminology_snapshots SET subject_id = %s
                   WHERE tenant_id = %s AND snapshot_sha256 = %s""",
                (f"mallory-{suffix}", tenant_id, snapshot.snapshot_sha256),
            )
            connection.commit()
            with self.assertRaisesRegex(RuntimeError, "identity differs"):
                store_current_terminology_snapshot(
                    connection,
                    authorization=_authorization(principal),
                    locale="en-US",
                )
            connection.rollback()
            connection.execute(
                "DELETE FROM yap_terminology_snapshots WHERE tenant_id = %s",
                (tenant_id,),
            )
            connection.commit()

    def test_actor_cannot_append_another_users_personal_record(self) -> None:
        suffix = uuid4().hex
        tenant_id = f"tenant-{suffix}"
        actor = PrincipalKey(tenant_id, f"alice-{suffix}")
        record = _record(tenant_id, f"bob-{suffix}", 1, "Private")
        with psycopg.connect(POSTGRES_DSN) as connection:
            install_terminology_schema(connection)
            with self.assertRaisesRegex(PermissionError, "does not own"):
                append_terminology_record(
                    connection, record, authorization=_authorization(actor)
                )

    def test_record_lineage_cannot_change_owner_or_resume_after_deletion(self) -> None:
        suffix = uuid4().hex
        tenant_id = f"tenant-{suffix}"
        alice = PrincipalKey(tenant_id, f"alice-{suffix}")
        bob = PrincipalKey(tenant_id, f"bob-{suffix}")
        with psycopg.connect(POSTGRES_DSN) as connection:
            install_terminology_schema(connection)
            append_terminology_record(
                connection,
                _record(tenant_id, alice.subject_id, 1, "TAVI"),
                authorization=_authorization(alice),
            )
            with self.assertRaisesRegex(ValueError, "authority is immutable"):
                append_terminology_record(
                    connection,
                    _record(tenant_id, bob.subject_id, 2, "TAVI"),
                    authorization=_authorization(bob),
                )
            deleted = _record(tenant_id, alice.subject_id, 2, "TAVI", deleted=True)
            append_terminology_record(
                connection, deleted, authorization=_authorization(alice)
            )
            with self.assertRaisesRegex(ValueError, "cannot be restored"):
                append_terminology_record(
                    connection,
                    _record(tenant_id, alice.subject_id, 3, "TAVI"),
                    authorization=_authorization(alice),
                )
            connection.execute(
                "DELETE FROM yap_terminology_records WHERE tenant_id = %s",
                (tenant_id,),
            )
            connection.commit()

    def test_same_tenant_job_identity_does_not_cross_owners(self) -> None:
        suffix = uuid4().hex
        tenant_id = f"tenant-{suffix}"
        alice = PrincipalKey(tenant_id, f"alice-{suffix}")
        bob = PrincipalKey(tenant_id, f"bob-{suffix}")
        job_id = f"job-{suffix}"
        with psycopg.connect(POSTGRES_DSN) as connection:
            install_terminology_schema(connection)
            append_terminology_record(
                connection,
                _record(tenant_id, alice.subject_id, 1, "AliceTerm"),
                authorization=_authorization(alice),
            )
            alice_snapshot = bind_job_terminology_snapshot(
                connection,
                job_id=job_id,
                authorization=_authorization(alice),
                locale="en-US",
            )
            bob_snapshot = bind_job_terminology_snapshot(
                connection,
                job_id=job_id,
                authorization=_authorization(bob),
                locale="en-US",
            )
            self.assertEqual(alice_snapshot.subject_id, alice.subject_id)
            self.assertEqual(bob_snapshot.subject_id, bob.subject_id)
            self.assertNotEqual(alice_snapshot.snapshot_sha256, bob_snapshot.snapshot_sha256)
            with self.assertRaisesRegex(LookupError, "no terminology snapshot"):
                read_job_terminology_snapshot(
                    connection,
                    principal=PrincipalKey(f"other-{suffix}", alice.subject_id),
                    job_id=job_id,
                )
            connection.execute(
                "DELETE FROM yap_terminology_job_bindings WHERE tenant_id = %s",
                (tenant_id,),
            )
            connection.execute(
                "DELETE FROM yap_terminology_snapshots WHERE tenant_id = %s",
                (tenant_id,),
            )
            connection.execute(
                "DELETE FROM yap_terminology_records WHERE tenant_id = %s",
                (tenant_id,),
            )
            connection.commit()


class _Memberships:
    def team_ids_for(self, principal: PrincipalKey) -> tuple[str, ...]:
        del principal
        return ()


def _authorization(principal: PrincipalKey):
    authenticated = _authenticated(principal)
    return resolve_terminology_authorization(
        authenticated,
        memberships=_Memberships(),
        administrator_roles=frozenset({"knowledge.admin"}),
    )


def _authenticated(principal: PrincipalKey) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        principal.tenant_id,
        principal.subject_id,
        "test-client",
        frozenset({"knowledge.read"}),
    )


def _record(
    tenant_id: str,
    owner_id: str,
    version: int,
    canonical_form: str,
    *,
    deleted: bool = False,
) -> TerminologyRecord:
    return TerminologyRecord(
        record_id="tavi",
        tenant_id=tenant_id,
        scope="personal",
        owner_id=owner_id,
        locale="en-US",
        canonical_form=canonical_form,
        variants=("tavi",),
        sensitivity="internal",
        version=version,
        deleted=deleted,
        audit_revision=f"audit-{version}",
        changed_at=f"2026-08-09T12:00:0{version}Z",
    )


if __name__ == "__main__":
    unittest.main()
