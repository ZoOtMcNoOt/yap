from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from uuid import uuid4

import psycopg

from yap_server.agents import AgentAdmission, AgentAdmissionTicket, ExecutionRoute
from yap_server.agents.auditor import (
    AuditorRequest,
    PostgresAuditorEvidenceReader,
    PostgresAuditorEvidenceVerifier,
    auditor_request_sha256,
    auditor_work_sha256,
    read_auditor_evidence_in_transaction,
)
from yap_server.agents.auditor_model import AuditorDecision
from yap_server.agents.auditor_result_audit import (
    AuditorRuntimeAuditIdentity,
    PostgresAuditorResultAuditor,
    install_auditor_result_audit_schema,
)
from yap_server.agents.auditor_service import AuditorService
from yap_server.auth import AuthenticatedPrincipal
from yap_server.knowledge.generation_ledger import (
    activate_complete_generation,
    install_knowledge_schema,
    store_generation_embeddings,
)
from yap_server.knowledge.knowledge_tool_audit import (
    install_knowledge_tool_audit_schema,
)

from tests.knowledge.test_postgres_permission_safe_retrieval import (
    _generation,
    _stage_reviewed_generation,
)


POSTGRES_DSN = os.environ.get("YAP_TEST_POSTGRES_DSN")


class _Admission:
    def __init__(self) -> None:
        self._next = 0
        self._open: set[str] = set()

    def new_ticket(self) -> AgentAdmissionTicket:
        self._next += 1
        return AgentAdmissionTicket(f"auditor-pg-{self._next}-{uuid4().hex}", "1" * 64)

    def submit(self, ticket, **kwargs):
        self._open.add(ticket.request_id)
        self.work = kwargs["work"]
        return self._view(ticket)

    def status(self, ticket):
        return self._view(ticket)

    def complete(self, ticket):
        self._open.discard(ticket.request_id)
        return AgentAdmission(ticket, "completed")

    def cancel(self, ticket):
        return AgentAdmission(
            ticket,
            "cancellation-requested",
            cancellation_reason="client-requested",
        )

    def acknowledge_cancellation(self, ticket):
        self._open.discard(ticket.request_id)
        return AgentAdmission(ticket, "cancelled")

    def _view(self, ticket):
        return AgentAdmission(
            ticket,
            "admitted",
            route=ExecutionRoute.COMPLEX_ORCHESTRATION,
            provider_generation=7,
            queue_duration_ms=0,
        )


class _Model:
    def review(self, request, evidence, *, cancellation):
        del request, cancellation
        if len(evidence.items) < 2:
            return AuditorDecision("evidence-unavailable", ())
        return AuditorDecision("report", ((1, 0),))


def _identity() -> AuditorRuntimeAuditIdentity:
    return AuditorRuntimeAuditIdentity(
        candidate_id="gemma-4-31b-it-nvfp4",
        model="nvidia/Gemma-4-31B-IT-NVFP4",
        model_revision="4135a98a9b728a548947683219633b25682223ac",
        runtime_id="gemma-vllm-26.06",
        profile_sha256="c" * 64,
        candidate_lock_sha256="d" * 64,
    )


def _principal(tenant_id: str, subject_id: str) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        tenant_id=tenant_id,
        subject_id=subject_id,
        client_id="auditor-postgres-tests",
        scopes=frozenset({"knowledge.read"}),
    )


def _connect():
    return psycopg.connect(POSTGRES_DSN)


@unittest.skipUnless(POSTGRES_DSN, "YAP_TEST_POSTGRES_DSN is not configured")
class AuditorPostgresTests(unittest.TestCase):
    def test_permission_safe_report_and_content_free_audit_survive_reconnect(
        self,
    ) -> None:
        tenant_id = f"tenant-{uuid4().hex}"
        with TemporaryDirectory() as directory:
            generation = _generation(Path(directory), tenant_id, subject="alice")
        with psycopg.connect(POSTGRES_DSN) as setup:
            install_knowledge_schema(setup)
            install_knowledge_tool_audit_schema(setup)
            install_auditor_result_audit_schema(setup)
            _stage_reviewed_generation(setup, generation)
            store_generation_embeddings(
                setup,
                tenant_id=tenant_id,
                generation_sha256=generation.generation_sha256,
                embedding_model_id="auditor-test",
                embedding_model_revision="revision-1",
                embeddings={
                    chunk.chunk_id: (0.0,) * 768 for chunk in generation.chunks
                },
            )
            activate_complete_generation(
                setup,
                tenant_id=tenant_id,
                generation_sha256=generation.generation_sha256,
            )
        admission = _Admission()
        service = AuditorService(
            admission=admission,
            evidence_reader=PostgresAuditorEvidenceReader(_connect),
            model=_Model(),
            result_auditor=PostgresAuditorResultAuditor(_connect, _identity()),
        )
        principal = _principal(tenant_id, "alice")
        request = AuditorRequest("approved release", 2, generation.generation_sha256)

        visible = service.audit(
            request,
            principal=principal,
            cancellation=threading.Event(),
        )
        hidden = service.audit(
            request,
            principal=_principal(tenant_id, "bob"),
            cancellation=threading.Event(),
        )
        absent = service.audit(
            AuditorRequest("termthatdoesnotexist", 2, generation.generation_sha256),
            principal=principal,
            cancellation=threading.Event(),
        )

        self.assertEqual(visible.status, "complete")
        self.assertIsNotNone(visible.report)
        assert visible.report is not None
        self.assertEqual(len(visible.report.findings), 1)
        self.assertFalse(visible.report.canonical)
        self.assertTrue(visible.report.requires_review)
        self.assertNotIn("sourcePath", repr(visible.to_wire()))
        self.assertNotIn("score", repr(visible.to_wire()).lower())
        hidden_wire = hidden.to_wire()
        absent_wire = absent.to_wire()
        hidden_wire.pop("requestId")
        absent_wire.pop("requestId")
        self.assertEqual(hidden_wire, absent_wire)

        with psycopg.connect(POSTGRES_DSN) as reconnected:
            result_rows = reconnected.execute(
                """SELECT subject_id, request_sha256, work_sha256,
                          evidence_sha256, report_sha256, citation_sha256,
                          generation_sha256, source_admission_sha256,
                          permission_hash, authorization_hash, agent_role,
                          purpose, route, scheduling_class, provider_generation,
                          outcome, reason, result_count
                   FROM yap_auditor_result_audit
                   WHERE tenant_id = %s ORDER BY audit_id""",
                (tenant_id,),
            ).fetchall()
            tool_rows = reconnected.execute(
                """SELECT subject_id, operation, outcome, result_count
                   FROM yap_knowledge_tool_audit
                   WHERE tenant_id = %s AND agent_id = 'auditor'
                   ORDER BY audit_id""",
                (tenant_id,),
            ).fetchall()
            source_admission = reconnected.execute(
                """SELECT source_admission_sha256 FROM yap_knowledge_builds
                   WHERE tenant_id = %s AND generation_sha256 = %s""",
                (tenant_id, generation.generation_sha256),
            ).fetchone()[0]
            content_hits = reconnected.execute(
                """SELECT count(*) FROM yap_auditor_result_audit audit
                   WHERE tenant_id = %s AND row_to_json(audit)::text LIKE %s""",
                (tenant_id, f"%{visible.report.findings[0].citations[0].text}%"),
            ).fetchone()[0]
            with reconnected.transaction():
                exact_evidence = read_auditor_evidence_in_transaction(
                    reconnected,
                    request,
                    principal=principal,
                )
            _cleanup(reconnected, tenant_id)

        self.assertEqual(len(result_rows), 3)
        first = result_rows[0]
        self.assertEqual(first[0], "alice")
        self.assertEqual(first[1], auditor_request_sha256(request))
        self.assertEqual(first[2], auditor_work_sha256(request, exact_evidence))
        self.assertEqual(first[4], visible.report.report_sha256)
        self.assertEqual(first[5], visible.report.citation_sha256)
        self.assertEqual(first[7], source_admission)
        self.assertEqual(
            first[10:18],
            (
                "auditor",
                "knowledge-audit",
                "complex-orchestration",
                "idle-only",
                7,
                "succeeded",
                None,
                1,
            ),
        )
        self.assertEqual(
            [(row[0], row[15], row[16], row[17]) for row in result_rows[1:]],
            [
                ("bob", "unavailable", "empty-result", 0),
                ("alice", "unavailable", "empty-result", 0),
            ],
        )
        self.assertEqual(
            [(row[0], row[1], row[2], row[3]) for row in tool_rows[:3]],
            [
                ("alice", "search", "succeeded", 2),
                ("bob", "search", "succeeded", 0),
                ("alice", "search", "succeeded", 0),
            ],
        )
        self.assertEqual(content_hits, 0)

    def test_current_verifier_rejects_source_admission_or_generation_drift(
        self,
    ) -> None:
        tenant_id = f"tenant-{uuid4().hex}"
        with TemporaryDirectory() as directory:
            generation = _generation(Path(directory), tenant_id, subject="alice")
        with psycopg.connect(POSTGRES_DSN) as setup:
            install_knowledge_schema(setup)
            install_knowledge_tool_audit_schema(setup)
            install_auditor_result_audit_schema(setup)
            _stage_reviewed_generation(setup, generation)
            store_generation_embeddings(
                setup,
                tenant_id=tenant_id,
                generation_sha256=generation.generation_sha256,
                embedding_model_id="auditor-test",
                embedding_model_revision="revision-1",
                embeddings={
                    chunk.chunk_id: (0.0,) * 768 for chunk in generation.chunks
                },
            )
            activate_complete_generation(
                setup,
                tenant_id=tenant_id,
                generation_sha256=generation.generation_sha256,
            )
        principal = _principal(tenant_id, "alice")
        request = AuditorRequest("approved release", 2, generation.generation_sha256)
        evidence = PostgresAuditorEvidenceReader(_connect).read(
            request,
            principal=principal,
            cancellation=threading.Event(),
        )
        verifier = PostgresAuditorEvidenceVerifier(_connect)
        verifier.verify(
            request,
            evidence,
            principal=principal,
            cancellation=threading.Event(),
        )
        with psycopg.connect(POSTGRES_DSN) as mutation:
            mutation.execute(
                """UPDATE yap_knowledge_source_admissions
                   SET source_revision = 'forged-revision'
                   WHERE tenant_id = %s""",
                (tenant_id,),
            )
        with self.assertRaises(ValueError):
            verifier.verify(
                request,
                evidence,
                principal=principal,
                cancellation=threading.Event(),
            )
        with psycopg.connect(POSTGRES_DSN) as cleanup:
            _cleanup(cleanup, tenant_id)


def _cleanup(connection, tenant_id: str) -> None:
    connection.execute(
        "DELETE FROM yap_auditor_result_audit WHERE tenant_id = %s",
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


if __name__ == "__main__":
    unittest.main()
