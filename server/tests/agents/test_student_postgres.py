from __future__ import annotations

import os
import threading
import unittest
from uuid import uuid4

import psycopg

from yap_server.agents.archivist import (
    ArchivistRequest,
    PostgresArchivistProcessor,
    compile_reviewed_capture_generation,
)
from yap_server.agents.student import (
    PostgresStudentEvidenceReader,
    StudentRequest,
    student_request_sha256,
    student_work_sha256,
)
from yap_server.agents.student_result_audit import (
    PostgresStudentResultAuditor,
    StudentRuntimeAuditIdentity,
    install_student_result_audit_schema,
)
from yap_server.auth import AuthenticatedPrincipal, PrincipalKey
from yap_server.jobs.ownership import PrincipalRecordingJobs
from yap_server.knowledge.generation_ledger import (
    activate_complete_generation,
    install_knowledge_schema,
    store_generation_embeddings,
)
from yap_server.knowledge.knowledge_tool_audit import (
    install_knowledge_tool_audit_schema,
)
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
class StudentPostgresTests(unittest.TestCase):
    def test_reads_only_exact_visible_conversation_and_generation(self) -> None:
        suffix = uuid4().hex
        owner = PrincipalKey(f"tenant-{suffix}", f"alice-{suffix}")
        principal = _authenticated(owner)
        job_id = f"job-{suffix}"
        capture = _capture(owner, job_id)
        compiled = compile_reviewed_capture_generation(capture, principal=principal)
        PostgresArchivistProcessor(_connect).ingest(
            ArchivistRequest(capture.capture_sha256),
            principal=principal,
            cancellation=threading.Event(),
        )
        with psycopg.connect(POSTGRES_DSN) as connection:
            store_generation_embeddings(
                connection,
                tenant_id=owner.tenant_id,
                generation_sha256=compiled.generation_sha256,
                embedding_model_id="student-test",
                embedding_model_revision="revision-1",
                embeddings={
                    chunk.chunk_id: (1.0,) + (0.0,) * 767
                    for chunk in compiled.chunks
                },
            )
            activate_complete_generation(
                connection,
                tenant_id=owner.tenant_id,
                generation_sha256=compiled.generation_sha256,
            )

        request = StudentRequest(
            conversation_concept_id=f"meetings/{job_id}",
            expected_generation_sha256=compiled.generation_sha256,
            topic="crash safety",
        )
        reader = PostgresStudentEvidenceReader(_connect)
        visible = reader.read(
            request,
            principal=principal,
            cancellation=threading.Event(),
        )
        hidden = reader.read(
            request,
            principal=_authenticated(
                PrincipalKey(owner.tenant_id, f"bob-{suffix}")
            ),
            cancellation=threading.Event(),
        )
        stale = StudentRequest(
            conversation_concept_id=request.conversation_concept_id,
            expected_generation_sha256="0" * 64,
            topic=request.topic,
        )
        with self.assertRaisesRegex(ValueError, "stale"):
            reader.read(
                stale,
                principal=principal,
                cancellation=threading.Event(),
            )
        result_auditor = PostgresStudentResultAuditor(
            _connect,
            _runtime_identity(),
        )
        result_auditor.record(
            principal=principal,
            request_id=f"student-{suffix}",
            request=request,
            provider_generation=7,
            status="complete",
            reason=None,
            evidence=visible,
            question_count=1,
            duration_milliseconds=12,
        )
        result_auditor.record(
            principal=principal,
            request_id=f"student-{suffix}",
            request=request,
            provider_generation=7,
            status="complete",
            reason=None,
            evidence=visible,
            question_count=1,
            duration_milliseconds=12,
        )
        with self.assertRaisesRegex(ValueError, "identity conflicts"):
            result_auditor.record(
                principal=principal,
                request_id=f"student-{suffix}",
                request=request,
                provider_generation=7,
                status="failed",
                reason="invalid-output",
                evidence=visible,
                question_count=0,
                duration_milliseconds=12,
            )
        result_auditor.record(
            principal=_authenticated(
                PrincipalKey(owner.tenant_id, f"bob-{suffix}")
            ),
            request_id=f"student-hidden-{suffix}",
            request=request,
            provider_generation=None,
            status="evidence-unavailable",
            reason="evidence-unavailable",
            evidence=hidden,
            question_count=0,
            duration_milliseconds=3,
        )
        with psycopg.connect(POSTGRES_DSN) as verification:
            audits = verification.execute(
                """SELECT subject_id, operation, outcome, result_count
                   FROM yap_knowledge_tool_audit
                   WHERE tenant_id = %s AND agent_id = 'student'
                   ORDER BY audit_id""",
                (owner.tenant_id,),
            ).fetchall()
            result_audits = verification.execute(
                """SELECT subject_id, request_id, request_sha256,
                          conversation_concept_id, work_sha256,
                          purpose, route, scheduling_class, provider_generation,
                          candidate_id, model, model_revision, runtime_id,
                          profile_sha256, candidate_lock_sha256,
                          generation_sha256, evidence_sha256,
                          permission_hash, authorization_hash,
                          outcome, reason, result_count
                   FROM yap_student_result_audit
                   WHERE tenant_id = %s ORDER BY audit_id""",
                (owner.tenant_id,),
            ).fetchall()
            _cleanup(verification, owner.tenant_id)

        self.assertEqual(visible.generation_sha256, compiled.generation_sha256)
        self.assertEqual(visible.conversation_concept_id, f"meetings/{job_id}")
        self.assertEqual(len(visible.items), 1)
        self.assertEqual(visible.items[0].concept_id, f"meetings/{job_id}")
        self.assertIn("Crash-safe private transcript", visible.items[0].text)
        self.assertEqual(hidden.items, ())
        self.assertEqual(
            audits,
            [
                (owner.subject_id, "conversation-evidence", "succeeded", 1),
                (f"bob-{suffix}", "conversation-evidence", "succeeded", 0),
                (owner.subject_id, "conversation-evidence", "failed", 0),
            ],
        )
        identity = _runtime_identity()
        self.assertEqual(
            result_audits,
            [
                (
                    owner.subject_id,
                    f"student-{suffix}",
                    student_request_sha256(request),
                    request.conversation_concept_id,
                    student_work_sha256(request, visible),
                    "learning-questions",
                    "rapid-automation",
                    "background-llm",
                    7,
                    identity.candidate_id,
                    identity.model,
                    identity.model_revision,
                    identity.runtime_id,
                    identity.profile_sha256,
                    identity.candidate_lock_sha256,
                    compiled.generation_sha256,
                    visible.evidence_sha256,
                    visible.permission_hash,
                    visible.authorization_hash,
                    "succeeded",
                    None,
                    1,
                ),
                (
                    f"bob-{suffix}",
                    f"student-hidden-{suffix}",
                    student_request_sha256(request),
                    request.conversation_concept_id,
                    student_work_sha256(request, hidden),
                    "learning-questions",
                    "rapid-automation",
                    "background-llm",
                    None,
                    identity.candidate_id,
                    identity.model,
                    identity.model_revision,
                    identity.runtime_id,
                    identity.profile_sha256,
                    identity.candidate_lock_sha256,
                    compiled.generation_sha256,
                    hidden.evidence_sha256,
                    hidden.permission_hash,
                    hidden.authorization_hash,
                    "unavailable",
                    "evidence-unavailable",
                    0,
                ),
            ],
        )

    def test_pre_cancelled_read_records_no_success(self) -> None:
        suffix = uuid4().hex
        owner = PrincipalKey(f"tenant-{suffix}", f"alice-{suffix}")
        with psycopg.connect(POSTGRES_DSN) as setup:
            install_reviewed_capture_schema(setup)
            install_knowledge_schema(setup)
            install_knowledge_tool_audit_schema(setup)
            install_student_result_audit_schema(setup)
        cancellation = threading.Event()
        cancellation.set()
        with self.assertRaises(KnowledgeToolCancelled):
            PostgresStudentEvidenceReader(_connect).read(
                StudentRequest(
                    conversation_concept_id=f"meetings/job-{suffix}",
                    expected_generation_sha256="a" * 64,
                    topic="crash safety",
                ),
                principal=_authenticated(owner),
                cancellation=cancellation,
            )
        with psycopg.connect(POSTGRES_DSN) as verification:
            outcomes = verification.execute(
                """SELECT outcome FROM yap_knowledge_tool_audit
                   WHERE tenant_id = %s AND agent_id = 'student'""",
                (owner.tenant_id,),
            ).fetchall()
            _cleanup(verification, owner.tenant_id)
        self.assertEqual(outcomes, [("cancelled",)])


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
        reviewed_at_utc="2026-08-12T16:00:00Z",
        result_revision_sha256=result_revision_sha256(result),
        decision="accepted",
    )
    with psycopg.connect(POSTGRES_DSN) as connection:
        install_reviewed_capture_schema(connection)
        install_knowledge_schema(connection)
        install_knowledge_tool_audit_schema(connection)
        install_student_result_audit_schema(connection)
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
        client_id="student-tests",
        scopes=frozenset(),
    )


def _connect():
    return psycopg.connect(POSTGRES_DSN)


def _runtime_identity() -> StudentRuntimeAuditIdentity:
    return StudentRuntimeAuditIdentity(
        candidate_id="qwen3.6-35b-a3b-nvfp4",
        model="nvidia/Qwen3.6-35B-A3B-NVFP4",
        model_revision="f" * 40,
        runtime_id="qwen-vllm-26.07-xgrammar-0.2.1",
        profile_sha256="1" * 64,
        candidate_lock_sha256="2" * 64,
    )


def _cleanup(connection, tenant_id: str) -> None:
    connection.execute(
        "DELETE FROM yap_student_result_audit WHERE tenant_id = %s",
        (tenant_id,),
    )
    connection.execute(
        "DELETE FROM yap_knowledge_tool_audit WHERE tenant_id = %s",
        (tenant_id,),
    )
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
