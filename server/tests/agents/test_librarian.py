from __future__ import annotations

from dataclasses import replace
import hashlib
import threading
import time
import unittest

from psycopg.errors import QueryCanceled

from yap_server.agents import (
    AgentAdmission,
    AgentAdmissionTicket,
    AgentPurpose,
    AgentRole,
    ExecutionRoute,
    SchedulingClass,
)
from yap_server.agents.librarian import (
    LibrarianEvidenceItem,
    LibrarianEvidencePack,
    LibrarianRequest,
    librarian_request_sha256,
    librarian_work_sha256,
    validate_librarian_evidence,
)
from yap_server.agents.librarian_service import (
    LibrarianContainmentError,
    LibrarianService,
)
from yap_server.auth import AuthenticatedPrincipal
from yap_server.knowledge.knowledge_tool_contract import (
    KnowledgeToolCancelled,
    KnowledgeToolCitation,
    KnowledgeToolItem,
    KnowledgeToolResponse,
    KnowledgeToolTimedOut,
)


def _principal(subject: str = "alice") -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        tenant_id="tenant-a",
        subject_id=subject,
        client_id="desktop",
        scopes=frozenset(),
    )


def _request(*, expected_generation: str | None = "a" * 64) -> LibrarianRequest:
    return LibrarianRequest(
        search_text="crash safe transcript",
        maximum_results=3,
        expected_generation_sha256=expected_generation,
    )


def _item(index: int = 0) -> LibrarianEvidenceItem:
    text = "The reviewed transcript is crash safe."
    return LibrarianEvidenceItem(
        concept_id=f"meetings/review-{index}",
        source_revision="revision-1",
        content_sha256=hashlib.sha256(text.encode()).hexdigest(),
        char_start=10,
        char_end=10 + len(text),
        text=text,
    )


def _evidence(
    *, items: tuple[LibrarianEvidenceItem, ...] | None = None
) -> LibrarianEvidencePack:
    return LibrarianEvidencePack.create(
        generation_sha256="a" * 64,
        permission_hash="b" * 64,
        authorization_hash="c" * 64,
        items=(_item(),) if items is None else items,
        output_budget_exhausted=False,
    )


class _Admission:
    def __init__(self, *, outcome: str = "admitted") -> None:
        self.outcome = outcome
        self.route = ExecutionRoute.SERVER_IO
        self.provider_generation: int | None = None
        self.calls: list[str] = []
        self.submission: dict[str, object] | None = None

    def new_ticket(self) -> AgentAdmissionTicket:
        self.calls.append("new-ticket")
        return AgentAdmissionTicket("librarian-1", "1" * 64)

    def submit(self, ticket, **kwargs):
        self.calls.append("submit")
        self.submission = kwargs
        return self._view(ticket)

    def status(self, ticket):
        self.calls.append("status")
        return self._view(ticket)

    def admit(self) -> None:
        self.outcome = "admitted"

    def cancel(self, ticket):
        self.calls.append("cancel")
        if self.outcome in {"completed", "cancelled", "deadline-exceeded"}:
            return AgentAdmission(ticket, self.outcome)
        self.outcome = "cancellation-requested"
        return AgentAdmission(
            ticket,
            self.outcome,
            cancellation_reason="client-requested",
        )

    def acknowledge_cancellation(self, ticket):
        self.calls.append("acknowledge-cancellation")
        self.outcome = "cancelled"
        return AgentAdmission(ticket, "cancelled")

    def complete(self, ticket):
        self.calls.append("complete")
        self.outcome = "completed"
        return AgentAdmission(ticket, "completed")

    def _view(self, ticket):
        if self.outcome == "admitted":
            return AgentAdmission(
                ticket,
                "admitted",
                route=self.route,
                provider_generation=self.provider_generation,
                queue_duration_ms=0,
            )
        return AgentAdmission(ticket, self.outcome)


class _Reader:
    def __init__(
        self,
        evidence: LibrarianEvidencePack | None = None,
        *,
        error: BaseException | None = None,
    ) -> None:
        self.evidence = evidence or _evidence()
        self.error = error
        self.calls: list[tuple[LibrarianRequest, str]] = []

    def read(self, request, *, principal, cancellation):
        self.calls.append((request, principal.subject_id))
        if cancellation.is_set():
            raise KnowledgeToolCancelled("cancelled")
        if self.error is not None:
            raise self.error
        return self.evidence


class _BlockingReader:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.stopped = threading.Event()

    def read(self, request, *, principal, cancellation):
        del request, principal
        self.started.set()
        cancellation.wait(2)
        self.stopped.set()
        raise KnowledgeToolCancelled("cancelled")


class _Auditor:
    def __init__(self, *, error: BaseException | None = None) -> None:
        self.error = error
        self.records: list[dict[str, object]] = []

    def record(self, **kwargs) -> None:
        if self.error is not None:
            raise self.error
        self.records.append(kwargs)


class LibrarianContractTests(unittest.TestCase):
    def test_request_wire_is_exact_and_server_authority_is_not_caller_owned(self) -> None:
        value = {
            "schemaVersion": 1,
            "searchText": "crash safe transcript",
            "maximumResults": 3,
            "expectedGenerationSha256": "a" * 64,
        }
        self.assertEqual(LibrarianRequest.from_wire(value), _request())

        invalid = (
            {**value, "schemaVersion": True},
            {**value, "schemaVersion": 1.0},
            {**value, "maximumResults": True},
            {**value, "maximumResults": 6},
            {**value, "searchText": "..."},
            {**value, "searchText": "\ud800"},
            {**value, "purpose": "knowledge.read"},
            {**value, "tenantId": "tenant-b"},
        )
        for candidate in invalid:
            with self.subTest(candidate=candidate):
                with self.assertRaises(ValueError):
                    LibrarianRequest.from_wire(candidate)

    def test_evidence_hash_and_safe_wire_are_exact(self) -> None:
        request = _request()
        evidence = _evidence(items=(_item(0), _item(1)))

        validate_librarian_evidence(request, evidence)
        wire = evidence.to_wire()

        self.assertEqual(wire["operation"], "search")
        self.assertEqual(len(wire["items"]), 2)
        self.assertNotIn("sourcePath", repr(wire))
        self.assertNotIn("retrievalScore", repr(wire))
        self.assertEqual(
            librarian_work_sha256(request, evidence),
            librarian_work_sha256(request, evidence),
        )
        self.assertNotEqual(
            librarian_request_sha256(request),
            librarian_work_sha256(request, evidence),
        )

        with self.assertRaises(ValueError):
            replace(evidence, items=(evidence.items[0], evidence.items[0]))
        for forged in (
            replace(evidence, evidence_sha256="0" * 64),
            replace(evidence, generation_sha256="9" * 64),
        ):
            with self.subTest(forged=forged):
                with self.assertRaises(ValueError):
                    validate_librarian_evidence(request, forged)

    def test_tool_response_conversion_excludes_storage_metadata(self) -> None:
        response = KnowledgeToolResponse(
            operation="search",
            generation_sha256="a" * 64,
            permission_hash="b" * 64,
            authorization_hash="c" * 64,
            items=(
                KnowledgeToolItem(
                    citation=KnowledgeToolCitation(
                        "meetings/review-0",
                        "revision-1",
                        _item().content_sha256,
                        10,
                        10 + len(_item().text),
                    ),
                    text=_item().text,
                    relationship_type=None,
                    target_concept_id=None,
                ),
            ),
            output_budget_exhausted=False,
        )
        pack = LibrarianEvidencePack.from_tool_response(response)

        self.assertEqual(pack.items, (_item(),))
        self.assertNotIn("sourcePath", repr(pack.to_wire()))
        self.assertNotIn("score", repr(pack.to_wire()).lower())


class LibrarianServiceTests(unittest.TestCase):
    def _service(self, admission=None, reader=None, auditor=None):
        return LibrarianService(
            admission=admission or _Admission(),
            evidence_reader=reader or _Reader(),
            result_auditor=auditor or _Auditor(),
        )

    def test_queued_query_uses_one_exact_server_io_lease_and_returns_pack(self) -> None:
        admission = _Admission(outcome="queued")
        reader = _Reader()
        auditor = _Auditor()
        service = self._service(admission, reader, auditor)
        results: list[object] = []
        worker = threading.Thread(
            target=lambda: results.append(
                service.query(
                    _request(),
                    principal=_principal(),
                    cancellation=threading.Event(),
                )
            )
        )
        worker.start()
        _wait_for(lambda: "status" in admission.calls)
        self.assertEqual(reader.calls, [])
        admission.admit()
        worker.join(2)

        self.assertFalse(worker.is_alive())
        view = results[0]
        self.assertEqual(view.status, "complete")
        self.assertEqual(view.evidence, _evidence())
        self.assertEqual(len(reader.calls), 1)
        self.assertEqual(admission.calls[-2:], ["status", "complete"])
        assert admission.submission is not None
        work = admission.submission["work"]
        self.assertEqual(work.role, AgentRole.LIBRARIAN)
        self.assertEqual(work.purpose, AgentPurpose.KNOWLEDGE_READ)
        self.assertEqual(work.route, ExecutionRoute.SERVER_IO)
        self.assertEqual(work.scheduling_class, SchedulingClass.INTERACTIVE)
        self.assertEqual(
            admission.submission["source_sha256"],
            librarian_request_sha256(_request()),
        )
        self.assertEqual(auditor.records[0]["outcome"], "succeeded")
        self.assertEqual(auditor.records[0]["result_count"], 1)

    def test_no_match_is_indistinguishable_and_never_returns_evidence_bytes(self) -> None:
        auditor = _Auditor()
        empty = _evidence(items=())
        view = self._service(reader=_Reader(empty), auditor=auditor).query(
            _request(),
            principal=_principal(),
            cancellation=threading.Event(),
        )

        self.assertEqual(view.status, "evidence-unavailable")
        self.assertIsNone(view.evidence)
        wire = view.to_wire()
        self.assertNotIn("evidencePack", wire)
        self.assertNotIn("items", wire)
        self.assertEqual(auditor.records[0]["outcome"], "unavailable")
        self.assertEqual(auditor.records[0]["result_count"], 0)

    def test_pre_cancelled_request_never_enters_admission_or_storage(self) -> None:
        admission = _Admission()
        reader = _Reader()
        auditor = _Auditor()
        cancellation = threading.Event()
        cancellation.set()

        view = self._service(admission, reader, auditor).query(
            _request(), principal=_principal(), cancellation=cancellation
        )

        self.assertEqual(view.status, "cancelled")
        self.assertEqual(admission.calls, ["new-ticket"])
        self.assertEqual(reader.calls, [])
        self.assertEqual(auditor.records[0]["outcome"], "cancelled")

    def test_queued_cancellation_is_acknowledged_before_return(self) -> None:
        admission = _Admission(outcome="queued")
        reader = _Reader()
        cancellation = threading.Event()
        results: list[object] = []
        worker = threading.Thread(
            target=lambda: results.append(
                self._service(admission, reader).query(
                    _request(),
                    principal=_principal(),
                    cancellation=cancellation,
                )
            )
        )
        worker.start()
        _wait_for(lambda: "status" in admission.calls)
        cancellation.set()
        worker.join(2)

        self.assertFalse(worker.is_alive())
        self.assertEqual(results[0].status, "cancelled")
        self.assertEqual(reader.calls, [])
        self.assertEqual(
            admission.calls[-2:], ["cancel", "acknowledge-cancellation"]
        )

    def test_active_database_cancellation_is_contained_before_return(self) -> None:
        admission = _Admission()
        reader = _BlockingReader()
        cancellation = threading.Event()
        results: list[object] = []
        worker = threading.Thread(
            target=lambda: results.append(
                self._service(admission, reader).query(
                    _request(),
                    principal=_principal(),
                    cancellation=cancellation,
                )
            )
        )
        worker.start()
        self.assertTrue(reader.started.wait(1))
        cancellation.set()
        worker.join(2)

        self.assertFalse(worker.is_alive())
        self.assertTrue(reader.stopped.is_set())
        self.assertEqual(results[0].status, "cancelled")
        self.assertEqual(admission.outcome, "cancelled")
        self.assertNotIn("complete", admission.calls)

    def test_storage_and_authorization_failures_are_typed_without_a_pack(self) -> None:
        cases = (
            (KnowledgeToolTimedOut("timeout"), "storage-timeout", "failed"),
            (QueryCanceled("timeout"), "storage-timeout", "failed"),
            (PermissionError("private"), "unauthorized", "failed"),
            (LookupError("hidden"), "evidence-unavailable", "evidence-unavailable"),
            (ValueError("stale"), "stale-generation", "failed"),
            (OSError("private"), "storage-unavailable", "failed"),
        )
        for error, reason, status in cases:
            with self.subTest(error=type(error).__name__):
                auditor = _Auditor()
                view = self._service(
                    reader=_Reader(error=error), auditor=auditor
                ).query(
                    _request(),
                    principal=_principal(),
                    cancellation=threading.Event(),
                )
                self.assertEqual(view.status, status)
                self.assertEqual(view.reason, reason)
                self.assertIsNone(view.evidence)
                self.assertNotIn("private", repr(view.to_wire()))

    def test_capacity_rejection_is_audited_and_never_reaches_storage(self) -> None:
        admission = _Admission(outcome="queue-full")
        reader = _Reader()
        auditor = _Auditor()
        view = self._service(admission, reader, auditor).query(
            _request(),
            principal=_principal(),
            cancellation=threading.Event(),
        )

        self.assertEqual(view.status, "failed")
        self.assertEqual(view.reason, "capacity-unavailable")
        self.assertEqual(reader.calls, [])
        self.assertEqual(auditor.records[0]["reason"], "capacity-unavailable")

    def test_wrong_lease_identity_is_contained(self) -> None:
        for route, generation in (
            (ExecutionRoute.RAPID_AUTOMATION, None),
            (ExecutionRoute.SERVER_IO, 1),
        ):
            with self.subTest(route=route, generation=generation):
                admission = _Admission()
                admission.route = route
                admission.provider_generation = generation
                with self.assertRaisesRegex(
                    LibrarianContainmentError, "lease identity"
                ):
                    self._service(admission=admission).query(
                        _request(),
                        principal=_principal(),
                        cancellation=threading.Event(),
                    )
                self.assertEqual(
                    admission.calls[-2:], ["cancel", "acknowledge-cancellation"]
                )

    def test_audit_failure_never_returns_the_evidence_pack(self) -> None:
        admission = _Admission()
        with self.assertRaisesRegex(RuntimeError, "audit unavailable"):
            self._service(
                admission=admission,
                auditor=_Auditor(error=RuntimeError("audit unavailable")),
            ).query(
                _request(),
                principal=_principal(),
                cancellation=threading.Event(),
            )
        self.assertEqual(admission.outcome, "completed")


def _wait_for(predicate) -> None:
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition was not reached")


if __name__ == "__main__":
    unittest.main()
