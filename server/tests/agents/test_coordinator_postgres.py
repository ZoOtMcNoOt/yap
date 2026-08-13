from __future__ import annotations

import os
import threading
import time
import unittest
from uuid import uuid4

import psycopg

from yap_server.agents import AgentAdmission, AgentAdmissionTicket, ExecutionRoute
from yap_server.agents.coordinator import (
    CoordinatorEvidencePack,
    CoordinatorProposalBundle,
    CoordinatorRequest,
    coordinator_request_sha256,
)
from yap_server.agents.coordinator_model import CoordinatorDecision
from yap_server.agents.coordinator_result_audit import (
    CoordinatorRuntimeAuditIdentity,
    PostgresCoordinatorResultAuditor,
    install_coordinator_result_audit_schema,
)
from yap_server.agents.coordinator_service import CoordinatorService
from yap_server.agents.curator import CuratorRequest, PostgresCuratorEvidenceReader
from yap_server.agents.curator_publisher import PostgresCuratorPublisher
from yap_server.agents.curator_result_audit import PostgresCuratorResultAuditor
from yap_server.knowledge.knowledge_proposals import (
    CoordinatorEvidenceChanged,
    PostgresCoordinatorEvidenceReader,
    discard_knowledge_proposal,
    read_coordinator_evidence_in_transaction,
)

from tests.agents.test_curator_postgres import (
    _active_generation,
    _citation,
    _cleanup,
    _connect,
    _runtime_identity as curator_runtime_identity,
)


POSTGRES_DSN = os.environ.get("YAP_TEST_POSTGRES_DSN")


class _Admission:
    def __init__(self) -> None:
        self.ticket = AgentAdmissionTicket(
            f"coordinator-pg-{uuid4().hex}",
            "1" * 64,
        )
        self.completed = False
        self.submission: dict[str, object] | None = None

    def new_ticket(self) -> AgentAdmissionTicket:
        return self.ticket

    def submit(self, ticket, **kwargs):
        self.submission = kwargs
        return self._view(ticket)

    def status(self, ticket):
        return self._view(ticket)

    def complete(self, ticket):
        self.completed = True
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
        if self.completed:
            return AgentAdmission(ticket, "completed")
        return AgentAdmission(
            ticket,
            "admitted",
            route=ExecutionRoute.COMPLEX_ORCHESTRATION,
            provider_generation=17,
            queue_duration_ms=0,
        )


class _Model:
    def select(self, request, evidence, *, cancellation):
        del cancellation
        return CoordinatorDecision(
            "bundle",
            tuple(range(min(request.maximum_items, len(evidence.candidates)))),
        )


def _identity() -> CoordinatorRuntimeAuditIdentity:
    return CoordinatorRuntimeAuditIdentity(
        candidate_id="gemma-4-31b-it-nvfp4",
        model="nvidia/Gemma-4-31B-IT-NVFP4",
        model_revision="4135a98a9b728a548947683219633b25682223ac",
        runtime_id="gemma-vllm-26.06",
        profile_sha256="2" * 64,
        candidate_lock_sha256="3" * 64,
    )


def _publish_curator_proposal(principal, compiled, index: int):
    citation = _citation(compiled, "Crash-safe private transcript")
    request = CuratorRequest(
        submission_id=f"coordinator-source-{index}-{uuid4().hex}",
        trigger="explicit-proposal",
        expected_generation_sha256=compiled.generation_sha256,
        reviewed_content=f"Coordinate the reviewed release proposal {index}.",
        source_citations=(citation,),
    )
    evidence = PostgresCuratorEvidenceReader(_connect).read(
        request,
        principal=principal,
        cancellation=threading.Event(),
    )
    return PostgresCuratorPublisher(
        _connect,
        PostgresCuratorResultAuditor(_connect, curator_runtime_identity()),
    ).publish(
        principal=principal,
        request_id=f"curator-for-coordinator-{index}-{uuid4().hex}",
        request=request,
        evidence=evidence,
        provider_generation=11,
        started=time.monotonic(),
        deadline=time.monotonic() + 10,
        cancellation=threading.Event(),
    )


@unittest.skipUnless(POSTGRES_DSN, "YAP_TEST_POSTGRES_DSN is not configured")
class CoordinatorPostgresTests(unittest.TestCase):
    def test_service_rebinds_curator_lineage_and_audits_hashes_without_content(
        self,
    ) -> None:
        owner, principal, compiled = _active_generation()
        proposals = [
            _publish_curator_proposal(principal, compiled, index) for index in range(2)
        ]
        with psycopg.connect(POSTGRES_DSN) as setup:
            install_coordinator_result_audit_schema(setup)
        admission = _Admission()
        auditor = PostgresCoordinatorResultAuditor(_connect, _identity())
        service = CoordinatorService(
            admission=admission,
            evidence_reader=PostgresCoordinatorEvidenceReader(_connect),
            model=_Model(),
            result_auditor=auditor,
        )
        request = CoordinatorRequest(
            objective="Coordinate the reviewed release proposals.",
            maximum_items=2,
            expected_generation_sha256=compiled.generation_sha256,
        )

        view = service.coordinate(
            request,
            principal=principal,
            cancellation=threading.Event(),
        )

        self.assertEqual(view.status, "complete")
        self.assertIsNotNone(view.bundle)
        assert view.bundle is not None
        self.assertEqual(
            {item.proposal_id for item in view.bundle.items},
            {item.proposal_id for item in proposals},
        )
        assert admission.submission is not None
        self.assertEqual(
            admission.submission["source_sha256"],
            coordinator_request_sha256(request),
        )
        stored = auditor.read(
            principal=principal,
            request_id=admission.ticket.request_id,
        )
        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(stored.status, "complete")
        self.assertEqual(stored.bundle_sha256, view.bundle.bundle_sha256)
        self.assertEqual(stored.result_count, 2)

        with psycopg.connect(POSTGRES_DSN) as verification:
            row = verification.execute(
                """SELECT agent_role, purpose, route, scheduling_class,
                          provider_generation, outcome, reason, result_count
                   FROM yap_coordinator_result_audit
                   WHERE tenant_id = %s AND request_id = %s""",
                (owner.tenant_id, admission.ticket.request_id),
            ).fetchone()
            tool_row = verification.execute(
                """SELECT agent_id, operation, outcome, result_count,
                          generation_sha256, permission_hash, authorization_hash
                   FROM yap_knowledge_tool_audit
                   WHERE tenant_id = %s AND agent_id = 'coordinator'""",
                (owner.tenant_id,),
            ).fetchone()
            content_hits = verification.execute(
                """SELECT count(*) FROM yap_coordinator_result_audit AS audit
                   WHERE tenant_id = %s AND row_to_json(audit)::text LIKE %s""",
                (owner.tenant_id, f"%{request.objective}%"),
            ).fetchone()[0]
            proposal_hits = verification.execute(
                """SELECT count(*) FROM yap_coordinator_result_audit AS audit
                   WHERE tenant_id = %s AND row_to_json(audit)::text LIKE %s""",
                (owner.tenant_id, f"%{proposals[0].proposed_content}%"),
            ).fetchone()[0]
            self.assertEqual(
                row,
                (
                    "coordinator",
                    "conversation-coordinate",
                    "complex-orchestration",
                    "background-llm",
                    17,
                    "succeeded",
                    None,
                    2,
                ),
            )
            self.assertEqual(
                tool_row,
                (
                    "coordinator",
                    "open-proposal-evidence",
                    "succeeded",
                    2,
                    view.bundle.generation_sha256,
                    stored.permission_hash,
                    stored.authorization_hash,
                ),
            )
            self.assertEqual((content_hits, proposal_hits), (0, 0))
            verification.execute(
                "DELETE FROM yap_coordinator_result_audit WHERE tenant_id = %s",
                (owner.tenant_id,),
            )
            _cleanup(verification, owner.tenant_id)

    def test_exact_replay_conflict_and_discarded_source_reauthorization(
        self,
    ) -> None:
        owner, principal, compiled = _active_generation()
        proposal = _publish_curator_proposal(principal, compiled, 1)
        with psycopg.connect(POSTGRES_DSN) as setup:
            install_coordinator_result_audit_schema(setup)
        reader = PostgresCoordinatorEvidenceReader(_connect)
        request = CoordinatorRequest(
            objective="Coordinate the reviewed release proposal.",
            maximum_items=1,
            expected_generation_sha256=compiled.generation_sha256,
        )
        evidence = reader.read(
            request,
            principal=principal,
            cancellation=threading.Event(),
        )
        bundle = CoordinatorProposalBundle.create(
            generation_sha256=evidence.generation_sha256,
            evidence_sha256=evidence.evidence_sha256,
            items=(evidence.candidates[0],),
        )
        auditor = PostgresCoordinatorResultAuditor(_connect, _identity())
        values = {
            "principal": principal,
            "request_id": f"coordinator-audit-{uuid4().hex}",
            "request": request,
            "provider_generation": 17,
            "status": "complete",
            "reason": None,
            "evidence": evidence,
            "bundle": bundle,
            "duration_milliseconds": 12,
            "cancellation": threading.Event(),
            "deadline": time.monotonic() + 10,
        }
        auditor.record(**values)
        auditor.record(**values)
        with self.assertRaisesRegex(ValueError, "identity conflicts"):
            auditor.record(**{**values, "duration_milliseconds": 13})

        with psycopg.connect(POSTGRES_DSN) as connection:
            discard_knowledge_proposal(
                connection,
                principal=owner,
                proposal_id=proposal.proposal_id,
            )
        with self.assertRaises(CoordinatorEvidenceChanged):
            auditor.record(
                **{
                    **values,
                    "request_id": f"coordinator-stale-{uuid4().hex}",
                }
            )
        with psycopg.connect(POSTGRES_DSN) as verification:
            stale_count = verification.execute(
                """SELECT count(*) FROM yap_coordinator_result_audit
                   WHERE tenant_id = %s AND request_id LIKE 'coordinator-stale-%%'""",
                (owner.tenant_id,),
            ).fetchone()[0]
            self.assertEqual(stale_count, 0)
            verification.execute(
                "DELETE FROM yap_coordinator_result_audit WHERE tenant_id = %s",
                (owner.tenant_id,),
            )
            _cleanup(verification, owner.tenant_id)

    def test_terminal_reauthorization_serializes_concurrent_owner_publication(
        self,
    ) -> None:
        owner, principal, compiled = _active_generation()
        _publish_curator_proposal(principal, compiled, 1)
        citation = _citation(compiled, "Crash-safe private transcript")
        second_request = CuratorRequest(
            submission_id=f"coordinator-source-lock-{uuid4().hex}",
            trigger="explicit-proposal",
            expected_generation_sha256=compiled.generation_sha256,
            reviewed_content="Coordinate the second reviewed release proposal.",
            source_citations=(citation,),
        )
        second_evidence = PostgresCuratorEvidenceReader(_connect).read(
            second_request,
            principal=principal,
            cancellation=threading.Event(),
        )
        request = CoordinatorRequest(
            objective="Coordinate the reviewed release proposals.",
            maximum_items=2,
            expected_generation_sha256=compiled.generation_sha256,
        )
        reader_locked = threading.Event()
        release_reader = threading.Event()
        held_evidence: list[CoordinatorEvidencePack] = []

        def hold_terminal_read() -> None:
            with psycopg.connect(POSTGRES_DSN) as connection:
                with connection.transaction():
                    held_evidence.append(
                        read_coordinator_evidence_in_transaction(
                            connection,
                            request,
                            principal=principal,
                        )
                    )
                    reader_locked.set()
                    if not release_reader.wait(timeout=10):
                        raise RuntimeError("coordinator lock test timed out")

        publisher_connection = psycopg.connect(POSTGRES_DSN)
        publisher_pid = publisher_connection.info.backend_pid

        def publisher_factory():
            return publisher_connection

        publication: list[object] = []
        publication_errors: list[BaseException] = []

        def publish() -> None:
            try:
                publication.append(
                    PostgresCuratorPublisher(
                        publisher_factory,
                        PostgresCuratorResultAuditor(
                            publisher_factory,
                            curator_runtime_identity(),
                        ),
                    ).publish(
                        principal=principal,
                        request_id=f"curator-for-coordinator-lock-{uuid4().hex}",
                        request=second_request,
                        evidence=second_evidence,
                        provider_generation=11,
                        started=time.monotonic(),
                        deadline=time.monotonic() + 10,
                        cancellation=threading.Event(),
                    )
                )
            except BaseException as error:
                publication_errors.append(error)

        reader_thread = threading.Thread(target=hold_terminal_read)
        publisher_thread = threading.Thread(target=publish)
        try:
            reader_thread.start()
            self.assertTrue(reader_locked.wait(timeout=10))
            publisher_thread.start()
            waiting = False
            deadline = time.monotonic() + 5
            with psycopg.connect(POSTGRES_DSN) as observer:
                while time.monotonic() < deadline:
                    waiting = bool(
                        observer.execute(
                            """SELECT EXISTS (
                                   SELECT 1 FROM pg_locks
                                   WHERE pid = %s AND locktype = 'advisory'
                                     AND NOT granted
                               )""",
                            (publisher_pid,),
                        ).fetchone()[0]
                    )
                    if waiting:
                        break
                    time.sleep(0.02)
            self.assertTrue(waiting)
        finally:
            release_reader.set()
            reader_thread.join(timeout=10)
            publisher_thread.join(timeout=10)
        self.assertFalse(reader_thread.is_alive())
        self.assertFalse(publisher_thread.is_alive())
        self.assertEqual(publication_errors, [])
        self.assertEqual(len(publication), 1)
        self.assertEqual(len(held_evidence[0].candidates), 1)
        current = PostgresCoordinatorEvidenceReader(_connect).read(
            request,
            principal=principal,
            cancellation=threading.Event(),
        )
        self.assertEqual(len(current.candidates), 2)
        self.assertNotEqual(held_evidence[0], current)

        with psycopg.connect(POSTGRES_DSN) as verification:
            _cleanup(verification, owner.tenant_id)


if __name__ == "__main__":
    unittest.main()
