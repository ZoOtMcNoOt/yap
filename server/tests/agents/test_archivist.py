from __future__ import annotations

import hashlib
import threading
import time
import unittest

from yap_server.agents import (
    AgentAdmission,
    AgentAdmissionTicket,
    AgentPurpose,
    AgentRole,
    ExecutionRoute,
    SchedulingClass,
)
from yap_server.agents.archivist import (
    ArchivistIngestion,
    ArchivistRequest,
    compile_reviewed_capture_generation,
)
from yap_server.agents.archivist_service import (
    ArchivistContainmentError,
    ArchivistService,
)
from yap_server.auth import AuthenticatedPrincipal
from yap_server.knowledge.generation_ledger import KnowledgeGenerationDescriptor
from yap_server.knowledge.knowledge_tool_contract import KnowledgeToolCancelled
from yap_server.knowledge.reviewed_capture_ledger import ReviewedCaptureDescriptor


def _principal(subject: str = "alice") -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        tenant_id="tenant-a",
        subject_id=subject,
        client_id="desktop",
        scopes=frozenset(),
    )


def _request() -> ArchivistRequest:
    return ArchivistRequest("a" * 64)


def _ingestion() -> ArchivistIngestion:
    return ArchivistIngestion(
        capture_sha256="a" * 64,
        source_admission_sha256="b" * 64,
        generation=KnowledgeGenerationDescriptor(
            "tenant-a",
            "c" * 64,
            "a" * 64,
            "0.1",
            1,
            1,
        ),
    )


class _Admission:
    def __init__(self, *, queued: bool = False) -> None:
        self.queued = queued
        self.outcome = "queued" if queued else "admitted"
        self.calls: list[tuple[str, str]] = []
        self.submission: dict[str, object] | None = None
        self.route = ExecutionRoute.SERVER_IO

    def new_ticket(self) -> AgentAdmissionTicket:
        return AgentAdmissionTicket("archivist-1", "1" * 64)

    def submit(self, ticket, **kwargs):
        self.calls.append(("submit", ticket.request_id))
        self.submission = kwargs
        return self._response(ticket)

    def status(self, ticket):
        self.calls.append(("status", ticket.request_id))
        return self._response(ticket)

    def admit(self) -> None:
        self.outcome = "admitted"

    def cancel(self, ticket):
        self.calls.append(("cancel", ticket.request_id))
        if self.outcome in {"completed", "cancelled"}:
            return AgentAdmission(ticket, self.outcome)
        self.outcome = "cancellation-requested"
        return AgentAdmission(
            ticket,
            self.outcome,
            cancellation_reason="client-requested",
        )

    def acknowledge_cancellation(self, ticket):
        self.calls.append(("acknowledge-cancellation", ticket.request_id))
        self.outcome = "cancelled"
        return AgentAdmission(ticket, self.outcome)

    def complete(self, ticket):
        self.calls.append(("complete", ticket.request_id))
        self.outcome = "completed"
        return AgentAdmission(ticket, self.outcome)

    def _response(self, ticket):
        if self.outcome == "admitted":
            return AgentAdmission(
                ticket,
                "admitted",
                route=self.route,
                provider_generation=None,
                queue_duration_ms=0,
            )
        return AgentAdmission(ticket, self.outcome)


class _LostSubmitAdmission(_Admission):
    def submit(self, ticket, **kwargs):
        self.calls.append(("submit", ticket.request_id))
        self.submission = kwargs
        self.outcome = "not-found-or-unauthorized"
        raise RuntimeError("admission response was lost")

    def cancel(self, ticket):
        self.calls.append(("cancel", ticket.request_id))
        return AgentAdmission(ticket, "not-found-or-unauthorized")


class _Processor:
    def __init__(self, *, error: BaseException | None = None) -> None:
        self.error = error
        self.calls: list[tuple[ArchivistRequest, str]] = []

    def ingest(self, request, *, principal, cancellation):
        self.calls.append((request, principal.subject_id))
        if cancellation.is_set():
            raise AssertionError("processor was dispatched after cancellation")
        if self.error is not None:
            raise self.error
        return _ingestion()


class _BlockingProcessor:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.stopped = threading.Event()

    def ingest(self, request, *, principal, cancellation):
        del request, principal
        self.started.set()
        cancellation.wait(2)
        self.stopped.set()
        raise KnowledgeToolCancelled("cancelled")


class ArchivistTests(unittest.TestCase):
    def test_request_accepts_only_one_durable_capture_identity(self) -> None:
        self.assertEqual(
            ArchivistRequest.from_wire({"schemaVersion": 1, "captureSha256": "a" * 64}),
            _request(),
        )
        for value in (
            {"schemaVersion": 1, "captureSha256": "not-a-hash"},
            {
                "schemaVersion": 1,
                "captureSha256": "a" * 64,
                "transcript": "caller supplied",
            },
        ):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    ArchivistRequest.from_wire(value)

    def test_compiles_one_owner_only_generation_without_mutating_source(self) -> None:
        normalized = _normalized_capture()
        capture = ReviewedCaptureDescriptor(
            tenant_id="tenant-a",
            owner_id="alice",
            job_id="job-1",
            capture_sha256="a" * 64,
            result_sha256="b" * 64,
            review_sha256="c" * 64,
            normalized_okf_sha256=hashlib.sha256(normalized.encode()).hexdigest(),
            normalized_okf=normalized,
        )
        generation = compile_reviewed_capture_generation(
            capture,
            principal=_principal(),
        )

        self.assertEqual(generation.source_revision, capture.capture_sha256)
        self.assertEqual(generation.concepts[0].concept_id, "meetings/job-1")
        self.assertEqual(generation.permissions[0].audience, (_principal().key,))
        self.assertEqual(generation.permissions[0].purposes, ("knowledge.read",))
        self.assertEqual(generation.permissions[0].classification, "confidential")
        self.assertEqual(capture.normalized_okf, normalized)
        with self.assertRaises(PermissionError):
            compile_reviewed_capture_generation(
                capture,
                principal=_principal("bob"),
            )

    def test_queued_ingestion_uses_exact_server_io_lease_and_stages_once(self) -> None:
        admission = _Admission(queued=True)
        processor = _Processor()
        service = ArchivistService(admission=admission, processor=processor)
        outcome: list[object] = []

        worker = threading.Thread(
            target=lambda: outcome.append(
                service.ingest(
                    _request(),
                    principal=_principal(),
                    cancellation=threading.Event(),
                )
            )
        )
        worker.start()
        _wait_for(lambda: admission.calls)
        self.assertEqual(processor.calls, [])
        admission.admit()
        worker.join(2)

        self.assertFalse(worker.is_alive())
        self.assertEqual(len(outcome), 1)
        view = outcome[0]
        self.assertEqual(view.status, "staged")
        self.assertEqual(view.generation_sha256, "c" * 64)
        self.assertEqual(len(processor.calls), 1)
        self.assertEqual(
            [operation for operation, _ in admission.calls if operation == "complete"],
            ["complete"],
        )
        assert admission.submission is not None
        work = admission.submission["work"]
        self.assertEqual(work.role, AgentRole.ARCHIVIST)
        self.assertEqual(work.purpose, AgentPurpose.KNOWLEDGE_INGEST)
        self.assertEqual(work.route, ExecutionRoute.SERVER_IO)
        self.assertEqual(work.scheduling_class, SchedulingClass.BACKGROUND_IO)
        self.assertEqual(admission.submission["source_sha256"], "a" * 64)

    def test_cancelled_queued_work_never_reaches_the_processor(self) -> None:
        admission = _Admission(queued=True)
        processor = _Processor()
        service = ArchivistService(admission=admission, processor=processor)
        cancellation = threading.Event()
        outcome: list[object] = []
        worker = threading.Thread(
            target=lambda: outcome.append(
                service.ingest(
                    _request(),
                    principal=_principal(),
                    cancellation=cancellation,
                )
            )
        )
        worker.start()
        _wait_for(lambda: admission.calls)
        cancellation.set()
        worker.join(2)

        self.assertFalse(worker.is_alive())
        self.assertEqual(outcome[0].status, "cancelled")
        self.assertEqual(outcome[0].reason, "client-cancelled")
        self.assertEqual(processor.calls, [])
        self.assertEqual(
            [operation for operation, _ in admission.calls[-2:]],
            ["cancel", "acknowledge-cancellation"],
        )

    def test_invalid_source_is_failed_without_a_success_payload(self) -> None:
        admission = _Admission()
        service = ArchivistService(
            admission=admission,
            processor=_Processor(error=ValueError("private detail")),
        )
        view = service.ingest(
            _request(),
            principal=_principal(),
            cancellation=threading.Event(),
        )

        self.assertEqual(view.status, "failed")
        self.assertEqual(view.reason, "invalid-reviewed-source")
        self.assertIsNone(view.generation_sha256)
        self.assertNotIn("private detail", repr(view.to_wire()))
        self.assertEqual(admission.calls[-1][0], "complete")

    def test_active_cancellation_is_acknowledged_before_return(self) -> None:
        admission = _Admission()
        processor = _BlockingProcessor()
        service = ArchivistService(admission=admission, processor=processor)
        cancellation = threading.Event()
        outcome: list[object] = []
        worker = threading.Thread(
            target=lambda: outcome.append(
                service.ingest(
                    _request(),
                    principal=_principal(),
                    cancellation=cancellation,
                )
            )
        )
        worker.start()
        self.assertTrue(processor.started.wait(1))
        cancellation.set()
        worker.join(2)

        self.assertFalse(worker.is_alive())
        self.assertTrue(processor.stopped.is_set())
        self.assertEqual(outcome[0].status, "cancelled")
        self.assertEqual(admission.outcome, "cancelled")
        self.assertNotIn("complete", [operation for operation, _ in admission.calls])

    def test_wrong_route_lease_is_contained_before_failure(self) -> None:
        admission = _Admission()
        admission.route = ExecutionRoute.RAPID_AUTOMATION
        service = ArchivistService(admission=admission, processor=_Processor())
        with self.assertRaisesRegex(RuntimeError, "lease identity"):
            service.ingest(
                _request(),
                principal=_principal(),
                cancellation=threading.Event(),
            )

        self.assertEqual(
            [operation for operation, _ in admission.calls[-2:]],
            ["cancel", "acknowledge-cancellation"],
        )

    def test_lost_submit_response_requires_proven_ticket_containment(self) -> None:
        admission = _LostSubmitAdmission()
        service = ArchivistService(admission=admission, processor=_Processor())

        with self.assertRaisesRegex(
            ArchivistContainmentError,
            "admission could not be contained",
        ):
            service.ingest(
                _request(),
                principal=_principal(),
                cancellation=threading.Event(),
            )

        self.assertEqual(
            [operation for operation, _ in admission.calls],
            ["submit", "cancel"],
        )


def _normalized_capture() -> str:
    return """---
type: Meeting
title: Architecture review
resource: yap://tenant/tenant-a/meeting/job-1
timestamp: '2026-08-12T10:00:00Z'
yap_schema: 1
provenance:
  source: server-authoritative-meeting-result
  source_revision: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
  result_sha256: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
  review_sha256: cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
  job_id: job-1
  owner: {tenant_id: tenant-a, subject_id: alice}
---
# Transcript

The reviewed meeting records crash safety.
"""


def _wait_for(predicate) -> None:
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition was not reached")


if __name__ == "__main__":
    unittest.main()
