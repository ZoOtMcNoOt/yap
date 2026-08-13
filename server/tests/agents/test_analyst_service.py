from __future__ import annotations

import hashlib
import threading
import unittest
from unittest.mock import patch

from yap_server.agents import (
    AgentAdmission,
    AgentAdmissionTicket,
    AgentPurpose,
    AgentRole,
    ExecutionRoute,
    SchedulingClass,
)
from yap_server.agents.analyst import AnalystRequest
from yap_server.agents.analyst_model import AnalystDecision
from yap_server.agents.analyst_service import (
    AnalystContainmentError,
    AnalystService,
)
from yap_server.agents.librarian import (
    LibrarianEvidenceItem,
    LibrarianEvidencePack,
)
from yap_server.agents.librarian_service import LibrarianJobView
from yap_server.auth import AuthenticatedPrincipal
from yap_server.knowledge.knowledge_tool_contract import KnowledgeGenerationStale
from yap_server.knowledge.knowledge_tool_contract import KnowledgeToolCancelled


def _principal() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        tenant_id="tenant-a",
        subject_id="alice",
        client_id="desktop",
        scopes=frozenset(),
    )


def _request() -> AnalystRequest:
    return AnalystRequest("What was approved?", 3, "a" * 64)


def _item(index: int = 0) -> LibrarianEvidenceItem:
    text = (
        "The reviewed release was approved."
        if index == 0
        else "The approval remains source-bound."
    )
    return LibrarianEvidenceItem(
        concept_id=f"records/release-{index}",
        source_revision="revision-1",
        content_sha256=hashlib.sha256(text.encode()).hexdigest(),
        char_start=index * 100,
        char_end=index * 100 + len(text),
        text=text,
    )


def _evidence(*, exhausted: bool = False) -> LibrarianEvidencePack:
    return LibrarianEvidencePack.create(
        generation_sha256="a" * 64,
        permission_hash="b" * 64,
        authorization_hash="c" * 64,
        items=(_item(0), _item(1)),
        output_budget_exhausted=exhausted,
    )


class _Admission:
    def __init__(self, events: list[str], *, outcome: str = "admitted") -> None:
        self.events = events
        self.outcome = outcome
        self.route = ExecutionRoute.COMPLEX_ORCHESTRATION
        self.provider_generation = 7
        self.submission: dict[str, object] | None = None
        self.complete_hook = None

    def new_ticket(self) -> AgentAdmissionTicket:
        self.events.append("new-ticket")
        return AgentAdmissionTicket("analyst-1", "1" * 64)

    def submit(self, ticket, **kwargs):
        self.events.append("submit")
        self.submission = kwargs
        return self._view(ticket)

    def status(self, ticket):
        self.events.append("status")
        return self._view(ticket)

    def cancel(self, ticket):
        self.events.append("cancel")
        if self.outcome in {"completed", "cancelled", "deadline-exceeded"}:
            return AgentAdmission(ticket, self.outcome)
        self.outcome = "cancellation-requested"
        return AgentAdmission(
            ticket,
            "cancellation-requested",
            cancellation_reason="client-requested",
        )

    def acknowledge_cancellation(self, ticket):
        self.events.append("acknowledge-cancellation")
        self.outcome = "cancelled"
        return AgentAdmission(ticket, "cancelled")

    def complete(self, ticket):
        self.events.append("complete")
        self.outcome = "completed"
        if self.complete_hook is not None:
            self.complete_hook()
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


class _Librarian:
    def __init__(
        self,
        events: list[str],
        view: LibrarianJobView | None = None,
    ) -> None:
        self.events = events
        self.view = view or LibrarianJobView("librarian-1", "complete", _evidence())
        self.calls = 0

    def query(self, request, *, principal, cancellation):
        del request, principal
        self.events.append("librarian")
        self.calls += 1
        if cancellation.is_set():
            return LibrarianJobView(
                "librarian-1", "cancelled", reason="client-cancelled"
            )
        return self.view


class _Verifier:
    def __init__(self, events: list[str], error: BaseException | None = None) -> None:
        self.events = events
        self.error = error
        self.calls = 0

    def verify(self, request, evidence, *, principal, cancellation):
        del request, evidence, principal, cancellation
        self.events.append("verify")
        self.calls += 1
        if self.error is not None:
            raise self.error


class _Model:
    def __init__(
        self,
        events: list[str],
        decision: AnalystDecision | None = None,
        error: BaseException | None = None,
    ) -> None:
        self.events = events
        self.decision = decision or AnalystDecision("answer", (0, 1))
        self.error = error
        self.calls = 0

    def answer(self, request, evidence, *, cancellation):
        del request, evidence, cancellation
        self.events.append("model")
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.decision


class _Auditor:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.records: list[dict[str, object]] = []

    def record(self, **value):
        self.events.append("audit")
        self.records.append(value)

    def read(self, **value):
        del value
        return None


class _CancelSuccessOnceAuditor(_Auditor):
    def record(self, **value):
        if value["status"] == "complete":
            self.events.append("audit-cancelled")
            raise KnowledgeToolCancelled("cancelled during success audit")
        super().record(**value)


class _StaleSuccessOnceAuditor(_Auditor):
    def record(self, **value):
        if value["status"] == "complete":
            self.events.append("audit-stale")
            raise KnowledgeGenerationStale("changed during success audit")
        super().record(**value)


class AnalystServiceTests(unittest.TestCase):
    def _service(
        self,
        *,
        events: list[str] | None = None,
        admission: _Admission | None = None,
        librarian: _Librarian | None = None,
        verifier: _Verifier | None = None,
        model: _Model | None = None,
        auditor: _Auditor | None = None,
    ):
        events = events if events is not None else []
        admission = admission or _Admission(events)
        librarian = librarian or _Librarian(events)
        verifier = verifier or _Verifier(events)
        model = model or _Model(events)
        auditor = auditor or _Auditor(events)
        return (
            AnalystService(
                admission=admission,
                librarian=librarian,
                evidence_verifier=verifier,
                model=model,
                result_auditor=auditor,
            ),
            admission,
            librarian,
            verifier,
            model,
            auditor,
            events,
        )

    def test_success_retrieves_before_complex_admission_and_returns_exact_items(self):
        service, admission, _, _, model, auditor, events = self._service()

        view = service.answer(
            _request(), principal=_principal(), cancellation=threading.Event()
        )

        self.assertEqual(view.status, "complete")
        self.assertIsNotNone(view.answer)
        assert view.answer is not None
        self.assertEqual(
            view.answer.answer,
            "The reviewed release was approved.\n\nThe approval remains source-bound.",
        )
        self.assertEqual(view.answer.citations, _evidence().items)
        self.assertLess(events.index("librarian"), events.index("submit"))
        self.assertLess(events.index("verify"), events.index("model"))
        self.assertLess(events.index("complete"), events.index("audit"))
        self.assertEqual(model.calls, 1)
        assert admission.submission is not None
        work = admission.submission["work"]
        self.assertEqual(work.role, AgentRole.ANALYST)
        self.assertEqual(work.purpose, AgentPurpose.KNOWLEDGE_ANSWER)
        self.assertEqual(work.route, ExecutionRoute.COMPLEX_ORCHESTRATION)
        self.assertEqual(work.scheduling_class, SchedulingClass.INTERACTIVE)
        self.assertEqual(auditor.records[-1]["status"], "complete")
        self.assertEqual(auditor.records[-1]["librarian_request_id"], "librarian-1")

    def test_empty_or_truncated_librarian_result_never_admits_model(self):
        for view, expected_reason in (
            (
                LibrarianJobView(
                    "librarian-1",
                    "evidence-unavailable",
                    reason="empty-result",
                ),
                "empty-result",
            ),
            (
                LibrarianJobView("librarian-1", "complete", _evidence(exhausted=True)),
                "incomplete-evidence",
            ),
        ):
            with self.subTest(reason=expected_reason):
                events: list[str] = []
                librarian = _Librarian(events, view)
                service, admission, _, verifier, model, auditor, _ = self._service(
                    events=events,
                    admission=_Admission(events),
                    librarian=librarian,
                    verifier=_Verifier(events),
                    model=_Model(events),
                    auditor=_Auditor(events),
                )
                result = service.answer(
                    _request(),
                    principal=_principal(),
                    cancellation=threading.Event(),
                )
                self.assertEqual(result.status, "evidence-unavailable")
                self.assertEqual(result.reason, expected_reason)
                self.assertNotIn("submit", events)
                self.assertEqual(verifier.calls, 0)
                self.assertEqual(model.calls, 0)
                self.assertEqual(auditor.records[-1]["status"], "evidence-unavailable")
                self.assertIsNone(admission.submission)

    def test_librarian_stale_generation_is_unavailable_without_model_admission(self):
        events: list[str] = []
        librarian = _Librarian(
            events,
            LibrarianJobView("librarian-1", "failed", reason="stale-generation"),
        )
        service, admission, _, verifier, model, auditor, _ = self._service(
            events=events,
            admission=_Admission(events),
            librarian=librarian,
            verifier=_Verifier(events),
            model=_Model(events),
            auditor=_Auditor(events),
        )

        view = service.answer(
            _request(), principal=_principal(), cancellation=threading.Event()
        )

        self.assertEqual(view.status, "evidence-unavailable")
        self.assertEqual(view.reason, "stale-generation")
        self.assertIsNone(admission.submission)
        self.assertEqual(verifier.calls, 0)
        self.assertEqual(model.calls, 0)
        self.assertEqual(auditor.records[-1]["status"], "evidence-unavailable")

    def test_current_authority_failure_completes_lease_without_model(self):
        events: list[str] = []
        verifier = _Verifier(events, KnowledgeGenerationStale("stale"))
        service, _, _, _, model, auditor, _ = self._service(
            events=events,
            verifier=verifier,
        )

        view = service.answer(
            _request(), principal=_principal(), cancellation=threading.Event()
        )

        self.assertEqual(view.status, "evidence-unavailable")
        self.assertEqual(view.reason, "stale-generation")
        self.assertEqual(model.calls, 0)
        self.assertLess(events.index("verify"), events.index("complete"))
        self.assertEqual(auditor.records[-1]["status"], "evidence-unavailable")

    def test_invalid_model_output_is_terminal_and_returns_no_answer(self):
        events: list[str] = []
        model = _Model(events, error=ValueError("invalid"))
        service, _, _, _, _, auditor, _ = self._service(
            events=events,
            model=model,
        )

        view = service.answer(
            _request(), principal=_principal(), cancellation=threading.Event()
        )

        self.assertEqual(view.status, "failed")
        self.assertEqual(view.reason, "invalid-output")
        self.assertIsNone(view.answer)
        self.assertLess(events.index("complete"), events.index("audit"))
        self.assertEqual(auditor.records[-1]["reason"], "invalid-output")

    def test_model_can_return_evidence_unavailable_without_answer(self):
        events: list[str] = []
        model = _Model(
            events,
            decision=AnalystDecision("evidence-unavailable", ()),
        )
        service, _, _, _, _, auditor, _ = self._service(
            events=events,
            model=model,
        )

        view = service.answer(
            _request(), principal=_principal(), cancellation=threading.Event()
        )

        self.assertEqual(view.status, "evidence-unavailable")
        self.assertEqual(view.reason, "model-evidence-unavailable")
        self.assertIsNone(view.answer)
        self.assertEqual(auditor.records[-1]["status"], "evidence-unavailable")

    def test_pre_cancelled_request_never_reads_or_submits(self):
        cancellation = threading.Event()
        cancellation.set()
        service, admission, librarian, verifier, model, auditor, events = (
            self._service()
        )

        view = service.answer(
            _request(), principal=_principal(), cancellation=cancellation
        )

        self.assertEqual(view.status, "cancelled")
        self.assertEqual(view.reason, "client-cancelled")
        self.assertEqual(librarian.calls, 0)
        self.assertEqual(verifier.calls, 0)
        self.assertEqual(model.calls, 0)
        self.assertIsNone(admission.submission)
        self.assertNotIn("submit", events)
        self.assertEqual(auditor.records[-1]["status"], "cancelled")

    def test_cancellation_after_model_completion_wins_before_audit(self):
        events: list[str] = []
        cancellation = threading.Event()
        admission = _Admission(events)
        admission.complete_hook = cancellation.set
        service, _, _, _, _, auditor, _ = self._service(
            events=events,
            admission=admission,
        )

        view = service.answer(
            _request(), principal=_principal(), cancellation=cancellation
        )

        self.assertEqual(view.status, "cancelled")
        self.assertIsNone(view.answer)
        self.assertEqual(auditor.records[-1]["status"], "cancelled")

    def test_cancellation_during_success_audit_rolls_back_answer_and_audits_cancel(
        self,
    ):
        events: list[str] = []
        auditor = _CancelSuccessOnceAuditor(events)
        service, _, _, _, _, _, _ = self._service(
            events=events,
            auditor=auditor,
        )

        view = service.answer(
            _request(), principal=_principal(), cancellation=threading.Event()
        )

        self.assertEqual(view.status, "cancelled")
        self.assertEqual(view.reason, "client-cancelled")
        self.assertIsNone(view.answer)
        self.assertEqual(events.count("audit-cancelled"), 1)
        self.assertEqual(len(auditor.records), 1)
        self.assertEqual(auditor.records[0]["status"], "cancelled")
        self.assertIsNone(auditor.records[0]["answer"])

    def test_generation_change_during_success_audit_returns_no_answer(self):
        events: list[str] = []
        auditor = _StaleSuccessOnceAuditor(events)
        service, _, _, _, _, _, _ = self._service(
            events=events,
            auditor=auditor,
        )

        view = service.answer(
            _request(), principal=_principal(), cancellation=threading.Event()
        )

        self.assertEqual(view.status, "evidence-unavailable")
        self.assertEqual(view.reason, "stale-generation")
        self.assertIsNone(view.answer)
        self.assertEqual(events.count("audit-stale"), 1)
        self.assertEqual(len(auditor.records), 1)
        self.assertEqual(auditor.records[0]["status"], "evidence-unavailable")
        self.assertIsNone(auditor.records[0]["answer"])

    def test_submit_response_loss_requires_proven_containment(self):
        events: list[str] = []

        class _LostAdmission(_Admission):
            def submit(self, ticket, **kwargs):
                del ticket, kwargs
                self.events.append("submit")
                raise OSError("lost")

            def cancel(self, ticket):
                self.events.append("cancel")
                return AgentAdmission(ticket, "not-found-or-unauthorized")

        service, *_ = self._service(
            events=events,
            admission=_LostAdmission(events),
        )
        with self.assertRaisesRegex(AnalystContainmentError, "could not be contained"):
            service.answer(
                _request(), principal=_principal(), cancellation=threading.Event()
            )

    def test_deadline_exhausted_before_submit_is_audited_without_containment(self):
        service, admission, _, verifier, model, auditor, events = self._service()

        with patch(
            "yap_server.agents.analyst_service._remaining_deadline_ms",
            return_value=None,
        ):
            view = service.answer(
                _request(), principal=_principal(), cancellation=threading.Event()
            )

        self.assertEqual(view.status, "cancelled")
        self.assertEqual(view.reason, "deadline-exceeded")
        self.assertIsNone(admission.submission)
        self.assertEqual(verifier.calls, 0)
        self.assertEqual(model.calls, 0)
        self.assertNotIn("submit", events)
        self.assertNotIn("cancel", events)
        self.assertEqual(len(auditor.records), 1)
        self.assertEqual(auditor.records[0]["status"], "cancelled")


if __name__ == "__main__":
    unittest.main()
