from __future__ import annotations

import os
import threading
import unittest
from uuid import uuid4

import psycopg

from yap_server.agents import AgentAdmission, AgentAdmissionTicket, ExecutionRoute
from yap_server.agents.archivist import (
    ArchivistRequest,
    PostgresArchivistProcessor,
    compile_reviewed_capture_generation,
)
from yap_server.agents.librarian import (
    LibrarianRequest,
    PostgresLibrarianEvidenceReader,
    librarian_request_sha256,
    librarian_work_sha256,
)
from yap_server.agents.librarian_result_audit import (
    PostgresLibrarianResultAuditor,
    install_librarian_result_audit_schema,
)
from yap_server.agents.librarian_service import LibrarianService
from yap_server.auth import AuthenticatedPrincipal, PrincipalKey
from yap_server.knowledge.generation_ledger import (
    activate_complete_generation,
    store_generation_embeddings,
)
from yap_server.knowledge.knowledge_tool_contract import KnowledgeToolCancelled

from tests.agents.test_student_postgres import _capture


POSTGRES_DSN = os.environ.get("YAP_TEST_POSTGRES_DSN")


@unittest.skipUnless(POSTGRES_DSN, "YAP_TEST_POSTGRES_DSN is not configured")
class LibrarianPostgresTests(unittest.TestCase):
    def test_visible_pack_hidden_equivalence_and_terminal_audit_survive_reconnect(
        self,
    ) -> None:
        owner, principal, compiled = _active_generation()
        request = LibrarianRequest(
            search_text="crash safe transcript",
            maximum_results=1,
            expected_generation_sha256=compiled.generation_sha256,
        )
        auditor = PostgresLibrarianResultAuditor(_connect)
        visible = LibrarianService(
            admission=_Admission(f"librarian-visible-{uuid4().hex}"),
            evidence_reader=PostgresLibrarianEvidenceReader(_connect),
            result_auditor=auditor,
        ).query(
            request,
            principal=principal,
            cancellation=threading.Event(),
        )
        other = _authenticated(
            PrincipalKey(owner.tenant_id, f"bob-{uuid4().hex}")
        )
        hidden = LibrarianService(
            admission=_Admission(f"librarian-hidden-{uuid4().hex}"),
            evidence_reader=PostgresLibrarianEvidenceReader(_connect),
            result_auditor=auditor,
        ).query(
            request,
            principal=other,
            cancellation=threading.Event(),
        )
        absent = LibrarianService(
            admission=_Admission(f"librarian-absent-{uuid4().hex}"),
            evidence_reader=PostgresLibrarianEvidenceReader(_connect),
            result_auditor=auditor,
        ).query(
            LibrarianRequest(
                search_text="termthatdoesnotexist",
                maximum_results=1,
                expected_generation_sha256=compiled.generation_sha256,
            ),
            principal=principal,
            cancellation=threading.Event(),
        )

        with psycopg.connect(POSTGRES_DSN) as restarted:
            result_rows = restarted.execute(
                """SELECT subject_id, request_sha256, work_sha256,
                          evidence_sha256, generation_sha256, permission_hash,
                          authorization_hash, agent_role, purpose, route,
                          scheduling_class, outcome, reason, result_count
                   FROM yap_librarian_result_audit
                   WHERE tenant_id = %s ORDER BY audit_id""",
                (owner.tenant_id,),
            ).fetchall()
            tool_rows = restarted.execute(
                """SELECT subject_id, operation, outcome, result_count,
                          generation_sha256, permission_hash, authorization_hash
                   FROM yap_knowledge_tool_audit
                   WHERE tenant_id = %s AND agent_id = 'librarian'
                   ORDER BY audit_id""",
                (owner.tenant_id,),
            ).fetchall()
            _cleanup(restarted, owner.tenant_id)

        self.assertEqual(visible.status, "complete")
        self.assertEqual(len(visible.items), 1)
        self.assertIn("Crash-safe private transcript", visible.items[0].text)
        self.assertNotIn("sourcePath", repr(visible.to_wire()))
        self.assertNotIn("score", repr(visible.to_wire()).lower())
        self.assertEqual(hidden.status, "evidence-unavailable")
        self.assertEqual(absent.status, "evidence-unavailable")
        hidden_wire = hidden.to_wire()
        absent_wire = absent.to_wire()
        hidden_wire.pop("requestId")
        absent_wire.pop("requestId")
        self.assertEqual(hidden_wire, absent_wire)
        self.assertEqual(len(result_rows), 3)
        self.assertEqual(
            result_rows[0],
            (
                owner.subject_id,
                librarian_request_sha256(request),
                librarian_work_sha256(request, visible.evidence),
                visible.evidence_sha256,
                visible.generation_sha256,
                visible.permission_hash,
                visible.authorization_hash,
                "librarian",
                "knowledge-read",
                "server-io",
                "interactive",
                "succeeded",
                None,
                1,
            ),
        )
        self.assertEqual(
            [(row[0], row[11], row[12], row[13]) for row in result_rows[1:]],
            [
                (other.subject_id, "unavailable", "empty-result", 0),
                (owner.subject_id, "unavailable", "empty-result", 0),
            ],
        )
        self.assertEqual(
            [(row[0], row[1], row[2], row[3]) for row in tool_rows],
            [
                (owner.subject_id, "search", "succeeded", 1),
                (other.subject_id, "search", "succeeded", 0),
                (owner.subject_id, "search", "succeeded", 0),
            ],
        )

    def test_stale_generation_and_pre_cancelled_read_fail_closed(self) -> None:
        owner, principal, compiled = _active_generation()
        reader = PostgresLibrarianEvidenceReader(_connect)
        stale = LibrarianRequest(
            search_text="crash safe transcript",
            maximum_results=1,
            expected_generation_sha256="0" * 64,
        )
        with self.assertRaisesRegex(ValueError, "stale"):
            reader.read(
                stale,
                principal=principal,
                cancellation=threading.Event(),
            )
        cancellation = threading.Event()
        cancellation.set()
        with self.assertRaises(KnowledgeToolCancelled):
            reader.read(
                LibrarianRequest(
                    search_text="crash safe transcript",
                    maximum_results=1,
                    expected_generation_sha256=compiled.generation_sha256,
                ),
                principal=principal,
                cancellation=cancellation,
            )

        with psycopg.connect(POSTGRES_DSN) as verification:
            outcomes = verification.execute(
                """SELECT outcome FROM yap_knowledge_tool_audit
                   WHERE tenant_id = %s AND agent_id = 'librarian'
                   ORDER BY audit_id""",
                (owner.tenant_id,),
            ).fetchall()
            _cleanup(verification, owner.tenant_id)
        self.assertEqual(outcomes, [("failed",), ("cancelled",)])


class _Admission:
    def __init__(self, request_id: str) -> None:
        self._ticket = AgentAdmissionTicket(request_id, "1" * 64)
        self.outcome = "admitted"

    def new_ticket(self):
        return self._ticket

    def submit(self, ticket, **kwargs):
        del kwargs
        return self._view(ticket)

    def status(self, ticket):
        return self._view(ticket)

    def cancel(self, ticket):
        self.outcome = "cancellation-requested"
        return AgentAdmission(
            ticket,
            self.outcome,
            cancellation_reason="client-requested",
        )

    def acknowledge_cancellation(self, ticket):
        self.outcome = "cancelled"
        return AgentAdmission(ticket, self.outcome)

    def complete(self, ticket):
        self.outcome = "completed"
        return AgentAdmission(ticket, self.outcome)

    def _view(self, ticket):
        if self.outcome == "admitted":
            return AgentAdmission(
                ticket,
                "admitted",
                route=ExecutionRoute.SERVER_IO,
                provider_generation=None,
                queue_duration_ms=0,
            )
        return AgentAdmission(ticket, self.outcome)


def _active_generation():
    suffix = uuid4().hex
    owner = PrincipalKey(f"tenant-{suffix}", f"alice-{suffix}")
    principal = _authenticated(owner)
    capture = _capture(owner, f"job-{suffix}")
    compiled = compile_reviewed_capture_generation(capture, principal=principal)
    PostgresArchivistProcessor(_connect).ingest(
        ArchivistRequest(capture.capture_sha256),
        principal=principal,
        cancellation=threading.Event(),
    )
    with psycopg.connect(POSTGRES_DSN) as connection:
        install_librarian_result_audit_schema(connection)
        store_generation_embeddings(
            connection,
            tenant_id=owner.tenant_id,
            generation_sha256=compiled.generation_sha256,
            embedding_model_id="librarian-test",
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
    return owner, principal, compiled


def _authenticated(owner: PrincipalKey) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        tenant_id=owner.tenant_id,
        subject_id=owner.subject_id,
        client_id="librarian-tests",
        scopes=frozenset(),
    )


def _connect():
    return psycopg.connect(POSTGRES_DSN)


def _cleanup(connection, tenant_id: str) -> None:
    connection.execute(
        "DELETE FROM yap_librarian_result_audit WHERE tenant_id = %s",
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
