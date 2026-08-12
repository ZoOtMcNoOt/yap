from __future__ import annotations

import os
import threading
import unittest
from uuid import uuid4

import psycopg

from yap_server.agents.archivist import (
    ArchivistRequest,
    PostgresArchivistProcessor,
)
from yap_server.auth import AuthenticatedPrincipal, PrincipalKey
from yap_server.jobs.ownership import PrincipalRecordingJobs
from yap_server.knowledge.generation_ledger import install_knowledge_schema
from yap_server.knowledge.knowledge_tool_contract import KnowledgeToolCancelled
from yap_server.knowledge.reviewed_capture_ledger import (
    append_reviewed_meeting_capture,
    install_reviewed_capture_schema,
)
from yap_server.knowledge.reviewed_meeting_knowledge import (
    KnowledgeSourceReview,
    result_revision_sha256,
)

from tests.jobs.service_fixtures import _published_result


POSTGRES_DSN = os.environ.get("YAP_TEST_POSTGRES_DSN")


@unittest.skipUnless(POSTGRES_DSN, "YAP_TEST_POSTGRES_DSN is not configured")
class ArchivistPostgresTests(unittest.TestCase):
    def test_exact_retry_and_restart_readback_stage_one_owner_generation(self) -> None:
        suffix = uuid4().hex
        owner = PrincipalKey(f"tenant-{suffix}", f"alice-{suffix}")
        principal = _authenticated(owner)
        capture = _capture(owner, f"job-{suffix}")
        processor = PostgresArchivistProcessor(_connect)
        request = ArchivistRequest(capture.capture_sha256)

        first = processor.ingest(
            request,
            principal=principal,
            cancellation=threading.Event(),
        )
        retry = processor.ingest(
            request,
            principal=principal,
            cancellation=threading.Event(),
        )
        with psycopg.connect(POSTGRES_DSN) as restarted:
            counts = restarted.execute(
                """SELECT
                    (SELECT count(*) FROM yap_knowledge_source_admissions
                     WHERE tenant_id = %s),
                    (SELECT count(*) FROM yap_knowledge_builds
                     WHERE tenant_id = %s),
                    (SELECT count(*) FROM yap_knowledge_active_builds
                     WHERE tenant_id = %s)""",
                (owner.tenant_id, owner.tenant_id, owner.tenant_id),
            ).fetchone()
            with self.assertRaises(LookupError):
                processor.ingest(
                    request,
                    principal=_authenticated(
                        PrincipalKey(owner.tenant_id, f"bob-{suffix}")
                    ),
                    cancellation=threading.Event(),
                )
            _cleanup(restarted, owner.tenant_id)

        self.assertEqual(retry, first)
        self.assertEqual(counts, (1, 1, 0))
        self.assertEqual(first.generation.concept_count, 1)
        self.assertEqual(first.generation.permission_count, 1)

    def test_pre_cancelled_ingestion_writes_no_generation(self) -> None:
        suffix = uuid4().hex
        owner = PrincipalKey(f"tenant-{suffix}", f"alice-{suffix}")
        capture = _capture(owner, f"job-{suffix}")
        cancellation = threading.Event()
        cancellation.set()
        with self.assertRaises(KnowledgeToolCancelled):
            PostgresArchivistProcessor(_connect).ingest(
                ArchivistRequest(capture.capture_sha256),
                principal=_authenticated(owner),
                cancellation=cancellation,
            )
        with psycopg.connect(POSTGRES_DSN) as connection:
            count = connection.execute(
                """SELECT count(*) FROM yap_knowledge_builds
                   WHERE tenant_id = %s""",
                (owner.tenant_id,),
            ).fetchone()[0]
            _cleanup(connection, owner.tenant_id)
        self.assertEqual(count, 0)


def _capture(owner: PrincipalKey, job_id: str):
    job = {
        "sessionId": f"session-{uuid4().hex}",
        "captureManifest": {"sha256": "a" * 64},
    }
    result = _published_result(job)
    review = KnowledgeSourceReview(
        reviewer=owner,
        job_id=job_id,
        title="Architecture review",
        reviewed_at_utc="2026-08-12T15:00:00Z",
        result_revision_sha256=result_revision_sha256(result),
        decision="accepted",
    )
    with psycopg.connect(POSTGRES_DSN) as connection:
        install_reviewed_capture_schema(connection)
        install_knowledge_schema(connection)
        return append_reviewed_meeting_capture(
            connection,
            PrincipalRecordingJobs(_ResultService(job, result), owner),
            review=review,
        )


class _ResultService:
    def __init__(self, job, result) -> None:
        self._job = job
        self._result = result

    def get(self, job_id: str, *, owner: PrincipalKey):
        if not job_id or not owner.subject_id:
            raise AssertionError("owned job read was not bound")
        return dict(self._job)

    def get_result(self, job_id: str, *, owner: PrincipalKey):
        if not job_id or not owner.subject_id:
            raise AssertionError("owned result read was not bound")
        return dict(self._result)


def _authenticated(owner: PrincipalKey) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        tenant_id=owner.tenant_id,
        subject_id=owner.subject_id,
        client_id="archivist-tests",
        scopes=frozenset(),
    )


def _connect():
    return psycopg.connect(POSTGRES_DSN)


def _cleanup(connection, tenant_id: str) -> None:
    connection.execute(
        "DELETE FROM yap_knowledge_active_builds WHERE tenant_id = %s",
        (tenant_id,),
    )
    connection.execute(
        "DELETE FROM yap_knowledge_builds WHERE tenant_id = %s",
        (tenant_id,),
    )
    connection.execute(
        "DELETE FROM yap_knowledge_source_admissions WHERE tenant_id = %s",
        (tenant_id,),
    )
    connection.execute(
        "DELETE FROM yap_knowledge_reviewed_captures WHERE tenant_id = %s",
        (tenant_id,),
    )


if __name__ == "__main__":
    unittest.main()
