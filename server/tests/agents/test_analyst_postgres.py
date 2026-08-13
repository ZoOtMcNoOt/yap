from __future__ import annotations

import os
import threading
import unittest
from uuid import uuid4

import psycopg

from yap_server.agents import AgentAdmission, AgentAdmissionTicket, ExecutionRoute
from yap_server.agents.analyst import (
    AnalystRequest,
    PostgresAnalystEvidenceVerifier,
    analyst_librarian_request,
    analyst_request_sha256,
    analyst_work_sha256,
)
from yap_server.agents.analyst_model import AnalystDecision
from yap_server.agents.analyst_result_audit import (
    AnalystRuntimeAuditIdentity,
    PostgresAnalystResultAuditor,
    install_analyst_result_audit_schema,
)
from yap_server.agents.analyst_service import AnalystService
from yap_server.agents.librarian import PostgresLibrarianEvidenceReader
from yap_server.agents.librarian_result_audit import PostgresLibrarianResultAuditor
from yap_server.agents.librarian_service import LibrarianService
from yap_server.knowledge.knowledge_tool_contract import KnowledgeGenerationStale

from tests.agents.test_librarian_postgres import (
    _active_generation,
    _cleanup,
    _connect,
)


POSTGRES_DSN = os.environ.get("YAP_TEST_POSTGRES_DSN")


class _Admission:
    def __init__(self) -> None:
        self._next = 0
        self._route_by_request: dict[str, ExecutionRoute] = {}
        self._completed: set[str] = set()

    def new_ticket(self):
        self._next += 1
        return AgentAdmissionTicket(f"analyst-pg-{self._next}-{uuid4().hex}", "1" * 64)

    def submit(self, ticket, **kwargs):
        route = kwargs["work"].route
        self._route_by_request[ticket.request_id] = route
        return self._view(ticket)

    def status(self, ticket):
        return self._view(ticket)

    def complete(self, ticket):
        self._completed.add(ticket.request_id)
        return AgentAdmission(ticket, "completed")

    def cancel(self, ticket):
        return AgentAdmission(
            ticket,
            "cancellation-requested",
            cancellation_reason="client-requested",
        )

    def acknowledge_cancellation(self, ticket):
        return AgentAdmission(ticket, "cancelled")

    def _view(self, ticket):
        if ticket.request_id in self._completed:
            return AgentAdmission(ticket, "completed")
        route = self._route_by_request.get(ticket.request_id)
        return AgentAdmission(
            ticket,
            "admitted",
            route=route,
            provider_generation=(
                7 if route is ExecutionRoute.COMPLEX_ORCHESTRATION else None
            ),
            queue_duration_ms=0,
        )


class _Model:
    def answer(self, request, evidence, *, cancellation):
        del request, cancellation
        return AnalystDecision("answer", tuple(range(len(evidence.items))))


class _RecordingLibrarian:
    def __init__(self, service: LibrarianService) -> None:
        self._service = service
        self.view = None

    def query(self, request, *, principal, cancellation):
        self.view = self._service.query(
            request,
            principal=principal,
            cancellation=cancellation,
        )
        return self.view


def _identity() -> AnalystRuntimeAuditIdentity:
    return AnalystRuntimeAuditIdentity(
        candidate_id="gemma-4-31b-it-nvfp4",
        model="nvidia/Gemma-4-31B-IT-NVFP4",
        model_revision="4135a98a9b728a548947683219633b25682223ac",
        runtime_id="gemma-vllm-26.06",
        profile_sha256="c" * 64,
        candidate_lock_sha256="d" * 64,
    )


@unittest.skipUnless(POSTGRES_DSN, "YAP_TEST_POSTGRES_DSN is not configured")
class AnalystPostgresTests(unittest.TestCase):
    def test_exact_librarian_lineage_answer_and_content_free_audit_survive_reconnect(
        self,
    ) -> None:
        owner, principal, compiled = _active_generation()
        with psycopg.connect(POSTGRES_DSN) as setup:
            install_analyst_result_audit_schema(setup)
        admission = _Admission()
        librarian = _RecordingLibrarian(
            LibrarianService(
                admission=admission,
                evidence_reader=PostgresLibrarianEvidenceReader(_connect),
                result_auditor=PostgresLibrarianResultAuditor(_connect),
            )
        )
        auditor = PostgresAnalystResultAuditor(_connect, _identity())
        service = AnalystService(
            admission=admission,
            librarian=librarian,
            evidence_verifier=PostgresAnalystEvidenceVerifier(_connect),
            model=_Model(),
            result_auditor=auditor,
        )
        request = AnalystRequest(
            question="crash safe transcript",
            maximum_results=1,
            expected_generation_sha256=compiled.generation_sha256,
        )

        view = service.answer(
            request,
            principal=principal,
            cancellation=threading.Event(),
        )

        self.assertEqual(view.status, "complete")
        self.assertIsNotNone(view.answer)
        assert view.answer is not None
        self.assertEqual(len(view.answer.citations), 1)
        self.assertEqual(view.answer.answer, view.answer.citations[0].text)
        with psycopg.connect(POSTGRES_DSN) as reconnected:
            row = reconnected.execute(
                """SELECT a.subject_id, a.request_sha256, a.work_sha256,
                          a.evidence_sha256, a.answer_sha256, a.citation_sha256,
                          a.generation_sha256, a.permission_hash,
                          a.authorization_hash, a.agent_role, a.purpose, a.route,
                          a.scheduling_class, a.provider_generation, a.outcome,
                          a.reason, a.result_count, l.outcome, l.result_count
                   FROM yap_analyst_result_audit a
                   JOIN yap_librarian_result_audit l
                     ON l.tenant_id = a.tenant_id
                    AND l.request_id = a.librarian_request_id
                   WHERE a.tenant_id = %s""",
                (owner.tenant_id,),
            ).fetchone()
            self.assertIsNotNone(row)
            assert row is not None
            self.assertEqual(row[0], owner.subject_id)
            self.assertEqual(row[1], analyst_request_sha256(request))
            self.assertIsNotNone(librarian.view)
            assert librarian.view is not None
            self.assertEqual(
                row[2], analyst_work_sha256(request, librarian.view.evidence)
            )
            self.assertEqual(row[3], view.answer.evidence_sha256)
            self.assertEqual(row[4], view.answer.answer_sha256)
            self.assertEqual(row[5], view.answer.citation_sha256)
            self.assertEqual(
                row[9:17],
                (
                    "analyst",
                    "knowledge-answer",
                    "complex-orchestration",
                    "interactive",
                    7,
                    "succeeded",
                    None,
                    1,
                ),
            )
            self.assertEqual(row[17:19], ("succeeded", 1))
            answer_text_hits = reconnected.execute(
                """SELECT count(*) FROM yap_analyst_result_audit AS audit
                   WHERE tenant_id = %s AND row_to_json(audit)::text LIKE %s""",
                (owner.tenant_id, f"%{view.answer.answer}%"),
            ).fetchone()[0]
            self.assertEqual(answer_text_hits, 0)
            reconnected.execute(
                "DELETE FROM yap_analyst_result_audit WHERE tenant_id = %s",
                (owner.tenant_id,),
            )
            _cleanup(reconnected, owner.tenant_id)

    def test_current_evidence_verifier_rejects_changed_generation(self) -> None:
        owner, principal, compiled = _active_generation()
        with psycopg.connect(POSTGRES_DSN) as setup:
            install_analyst_result_audit_schema(setup)
        request = AnalystRequest("crash safe transcript", 1, compiled.generation_sha256)
        evidence = PostgresLibrarianEvidenceReader(_connect).read(
            analyst_librarian_request(request),
            principal=principal,
            cancellation=threading.Event(),
        )
        verifier = PostgresAnalystEvidenceVerifier(_connect)
        verifier.verify(
            request,
            evidence,
            principal=principal,
            cancellation=threading.Event(),
        )
        stale_request = AnalystRequest("crash safe transcript", 1, "0" * 64)
        with self.assertRaises(KnowledgeGenerationStale):
            verifier.verify(
                stale_request,
                evidence,
                principal=principal,
                cancellation=threading.Event(),
            )
        with psycopg.connect(POSTGRES_DSN) as cleanup:
            cleanup.execute(
                "DELETE FROM yap_analyst_result_audit WHERE tenant_id = %s",
                (owner.tenant_id,),
            )
            _cleanup(cleanup, owner.tenant_id)


if __name__ == "__main__":
    unittest.main()
