from __future__ import annotations

import os
import unittest
from uuid import uuid4

import psycopg

from yap_server.auth.principal import PrincipalKey
from yap_server.knowledge.terminology_ledger import (
    append_terminology_record,
    bind_job_terminology_snapshot,
    install_terminology_schema,
    read_job_terminology_snapshot,
)
from yap_server.knowledge.terminology_snapshot import TerminologyRecord


POSTGRES_DSN = os.environ.get("YAP_TEST_POSTGRES_DSN")


@unittest.skipUnless(POSTGRES_DSN, "YAP_TEST_POSTGRES_DSN is not configured")
class TerminologyLedgerTests(unittest.TestCase):
    def test_job_binding_remains_frozen_after_a_new_record_version(self) -> None:
        suffix = uuid4().hex
        tenant_id = f"tenant-{suffix}"
        principal = PrincipalKey(tenant_id, f"alice-{suffix}")
        job_id = f"job-{suffix}"
        first = _record(tenant_id, principal.subject_id, 1, "TAVI")
        second = _record(tenant_id, principal.subject_id, 2, "TAVR")

        with psycopg.connect(POSTGRES_DSN) as connection:
            install_terminology_schema(connection)
            append_terminology_record(connection, first, actor=principal)
            bound = bind_job_terminology_snapshot(
                connection,
                job_id=job_id,
                principal=principal,
                team_ids=(),
                locale="en-US",
            )
            append_terminology_record(connection, second, actor=principal)
            unchanged = read_job_terminology_snapshot(
                connection, tenant_id=tenant_id, job_id=job_id
            )
            next_job = bind_job_terminology_snapshot(
                connection,
                job_id=f"next-{job_id}",
                principal=principal,
                team_ids=(),
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

    def test_actor_cannot_append_another_users_personal_record(self) -> None:
        suffix = uuid4().hex
        tenant_id = f"tenant-{suffix}"
        actor = PrincipalKey(tenant_id, f"alice-{suffix}")
        record = _record(tenant_id, f"bob-{suffix}", 1, "Private")
        with psycopg.connect(POSTGRES_DSN) as connection:
            install_terminology_schema(connection)
            with self.assertRaisesRegex(PermissionError, "does not own"):
                append_terminology_record(connection, record, actor=actor)


def _record(
    tenant_id: str, owner_id: str, version: int, canonical_form: str
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
        deleted=False,
        audit_revision=f"audit-{version}",
        changed_at=f"2026-08-09T12:00:0{version}Z",
    )


if __name__ == "__main__":
    unittest.main()
