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
from yap_server.agents.coordinator import (
    CoordinatorEvidencePack,
    CoordinatorProposalCandidate,
    CoordinatorRequest,
    coordinator_request_sha256,
)
from yap_server.agents.coordinator_model import CoordinatorDecision
from yap_server.agents.coordinator_service import (
    CoordinatorContainmentError,
    CoordinatorService,
)
from yap_server.knowledge.vllm_reasoning_client import (
    VllmRequestRejected,
    VllmTransportNotContained,
)
from yap_server.agents.librarian import LibrarianEvidenceItem
from yap_server.auth import AuthenticatedPrincipal
from yap_server.knowledge.knowledge_proposals import CoordinatorEvidenceChanged
from yap_server.knowledge.knowledge_tool_contract import (
    KnowledgeGenerationStale,
    KnowledgeToolCancelled,
)


def _principal() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        tenant_id="tenant-a",
        subject_id="alice",
        client_id="desktop",
        scopes=frozenset(),
    )


def _request() -> CoordinatorRequest:
    return CoordinatorRequest("Coordinate the reviewed release.", 2, "a" * 64)


def _citation(index: int) -> LibrarianEvidenceItem:
    text = f"Reviewed source {index} supports this proposal."
    return LibrarianEvidenceItem(
        concept_id=f"conversations/{index}",
        source_revision="revision-1",
        content_sha256=hashlib.sha256(text.encode()).hexdigest(),
        char_start=index * 100,
        char_end=index * 100 + len(text),
        text=text,
    )


def _candidate(index: int) -> CoordinatorProposalCandidate:
    return CoordinatorProposalCandidate.create(
        proposal_id=hashlib.sha256(f"proposal-{index}".encode()).hexdigest(),
        curator_request_id=f"curator-request-{index}",
        curator_submission_id=f"curator-submission-{index}",
        curator_request_sha256=hashlib.sha256(
            f"curator-request-hash-{index}".encode()
        ).hexdigest(),
        curator_work_sha256=hashlib.sha256(
            f"curator-work-hash-{index}".encode()
        ).hexdigest(),
        curator_evidence_sha256=hashlib.sha256(
            f"curator-evidence-hash-{index}".encode()
        ).hexdigest(),
        generation_sha256="a" * 64,
        proposal_type="summary",
        proposed_content=f"Reviewed proposal {index}.",
        inherited_permission_sha256=hashlib.sha256(
            f"inherited-{index}".encode()
        ).hexdigest(),
        proposal_permission_hash=hashlib.sha256(
            f"permission-{index}".encode()
        ).hexdigest(),
        proposal_authorization_hash=hashlib.sha256(
            f"authorization-{index}".encode()
        ).hexdigest(),
        citations=(_citation(index),),
    )


def _evidence(*, exhausted: bool = False) -> CoordinatorEvidencePack:
    return CoordinatorEvidencePack.create(
        generation_sha256="a" * 64,
        permission_hash="b" * 64,
        authorization_hash="c" * 64,
        candidates=(_candidate(0), _candidate(1)),
        output_budget_exhausted=exhausted,
    )


class _Admission:
    def __init__(self, events: list[str], *, outcome: str = "admitted") -> None:
        self.events = events
        self.outcome = outcome
        self.provider_generation = 7
        self.submission: dict[str, object] | None = None
        self.complete_hook = None

    def new_ticket(self) -> AgentAdmissionTicket:
        self.events.append("new-ticket")
        return AgentAdmissionTicket("coordinator-1", "1" * 64)

    def submit(self, ticket, **kwargs):
        self.events.append("submit")
        self.submission = kwargs
        return self._view(ticket)

    def status(self, ticket):
        self.events.append("status")
        return self._view(ticket)

    def cancel(self, ticket):
        self.events.append("cancel")
        if self.outcome in {
            "completed",
            "cancelled",
            "deadline-exceeded",
            "provider-unavailable",
        }:
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
                route=ExecutionRoute.COMPLEX_ORCHESTRATION,
                provider_generation=self.provider_generation,
                queue_duration_ms=0,
            )
        return AgentAdmission(ticket, self.outcome)


class _Reader:
    def __init__(
        self,
        events: list[str],
        *,
        evidence: CoordinatorEvidencePack | None = None,
        error: BaseException | None = None,
    ) -> None:
        self.events = events
        self.evidence = evidence if evidence is not None else _evidence()
        self.error = error
        self.calls = 0

    def read(self, request, *, principal, cancellation):
        del request, principal, cancellation
        self.events.append("read")
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.evidence


class _Model:
    def __init__(
        self,
        events: list[str],
        *,
        decision: CoordinatorDecision | None = None,
        error: BaseException | None = None,
    ) -> None:
        self.events = events
        self.decision = decision or CoordinatorDecision("bundle", (1, 0))
        self.error = error
        self.calls = 0

    def select(self, request, evidence, *, cancellation):
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
            raise CoordinatorEvidenceChanged("changed during success audit")
        super().record(**value)


class CoordinatorServiceTests(unittest.TestCase):
    def _service(
        self,
        *,
        events: list[str] | None = None,
        admission: _Admission | None = None,
        reader: _Reader | None = None,
        model: _Model | None = None,
        auditor: _Auditor | None = None,
    ):
        events = events if events is not None else []
        admission = admission or _Admission(events)
        reader = reader or _Reader(events)
        model = model or _Model(events)
        auditor = auditor or _Auditor(events)
        return (
            CoordinatorService(
                admission=admission,
                evidence_reader=reader,
                model=model,
                result_auditor=auditor,
            ),
            admission,
            reader,
            model,
            auditor,
            events,
        )

    def test_success_uses_one_complex_background_lease_and_returns_exact_bundle(
        self,
    ) -> None:
        service, admission, reader, model, auditor, events = self._service()

        view = service.coordinate(
            _request(), principal=_principal(), cancellation=threading.Event()
        )

        self.assertEqual(view.status, "complete")
        self.assertIsNotNone(view.bundle)
        assert view.bundle is not None
        self.assertEqual(view.bundle.items, (_candidate(1), _candidate(0)))
        self.assertLess(events.index("submit"), events.index("read"))
        self.assertLess(events.index("read"), events.index("model"))
        self.assertLess(events.index("complete"), events.index("audit"))
        self.assertEqual(reader.calls, 1)
        self.assertEqual(model.calls, 1)
        self.assertEqual(events.count("submit"), 1)
        assert admission.submission is not None
        work = admission.submission["work"]
        self.assertEqual(work.role, AgentRole.COORDINATOR)
        self.assertEqual(work.purpose, AgentPurpose.CONVERSATION_COORDINATE)
        self.assertEqual(work.route, ExecutionRoute.COMPLEX_ORCHESTRATION)
        self.assertEqual(work.scheduling_class, SchedulingClass.BACKGROUND_LLM)
        self.assertEqual(
            admission.submission["source_sha256"],
            coordinator_request_sha256(_request()),
        )
        self.assertEqual(auditor.records[-1]["status"], "complete")
        self.assertIs(auditor.records[-1]["bundle"], view.bundle)
        self.assertIn("proposalBundle", view.to_wire())

    def test_empty_or_exhausted_evidence_completes_without_model(self) -> None:
        empty = CoordinatorEvidencePack.create(
            generation_sha256="a" * 64,
            permission_hash="b" * 64,
            authorization_hash="c" * 64,
            candidates=(),
            output_budget_exhausted=False,
        )
        for evidence, reason in (
            (empty, "empty-result"),
            (_evidence(exhausted=True), "incomplete-evidence"),
        ):
            with self.subTest(reason=reason):
                events: list[str] = []
                reader = _Reader(events, evidence=evidence)
                service, _, _, model, auditor, events = self._service(
                    events=events,
                    reader=reader,
                )
                view = service.coordinate(
                    _request(),
                    principal=_principal(),
                    cancellation=threading.Event(),
                )
                self.assertEqual(view.status, "evidence-unavailable")
                self.assertEqual(view.reason, reason)
                self.assertIsNone(view.bundle)
                self.assertEqual(model.calls, 0)
                self.assertLess(events.index("read"), events.index("complete"))
                self.assertEqual(auditor.records[-1]["status"], "evidence-unavailable")

    def test_stale_read_completes_lease_and_returns_unavailable(self) -> None:
        events: list[str] = []
        reader = _Reader(events, error=KnowledgeGenerationStale("stale"))
        service, _, _, model, auditor, events = self._service(
            events=events,
            reader=reader,
        )

        view = service.coordinate(
            _request(), principal=_principal(), cancellation=threading.Event()
        )

        self.assertEqual(view.status, "evidence-unavailable")
        self.assertEqual(view.reason, "stale-generation")
        self.assertEqual(model.calls, 0)
        self.assertLess(events.index("read"), events.index("complete"))
        self.assertEqual(auditor.records[-1]["status"], "evidence-unavailable")

    def test_invalid_model_output_is_audited_without_a_bundle(self) -> None:
        events: list[str] = []
        model = _Model(events, error=ValueError("invalid"))
        service, _, _, _, auditor, events = self._service(
            events=events,
            model=model,
        )

        view = service.coordinate(
            _request(), principal=_principal(), cancellation=threading.Event()
        )

        self.assertEqual(view.status, "failed")
        self.assertEqual(view.reason, "invalid-output")
        self.assertIsNone(view.bundle)
        self.assertLess(events.index("complete"), events.index("audit"))
        self.assertIsNone(auditor.records[-1]["bundle"])

    def test_out_of_range_decision_is_audited_before_lease_completion(self) -> None:
        events: list[str] = []
        model = _Model(events, decision=CoordinatorDecision("bundle", (7,)))
        service, admission, _, _, auditor, events = self._service(
            events=events,
            model=model,
        )

        view = service.coordinate(
            _request(), principal=_principal(), cancellation=threading.Event()
        )

        self.assertEqual(view.status, "failed")
        self.assertEqual(view.reason, "invalid-output")
        self.assertEqual(admission.outcome, "completed")
        self.assertLess(events.index("model"), events.index("complete"))
        self.assertEqual(auditor.records[-1]["status"], "failed")
        self.assertIsNone(auditor.records[-1]["bundle"])

    def test_contained_model_rejection_is_audited_as_runtime_unavailable(self) -> None:
        events: list[str] = []
        model = _Model(events, error=VllmRequestRejected("rejected"))
        service, admission, _, _, auditor, events = self._service(
            events=events,
            model=model,
        )

        view = service.coordinate(
            _request(), principal=_principal(), cancellation=threading.Event()
        )

        self.assertEqual(view.status, "failed")
        self.assertEqual(view.reason, "runtime-unavailable")
        self.assertEqual(admission.outcome, "completed")
        self.assertLess(events.index("complete"), events.index("audit"))
        self.assertEqual(auditor.records[-1]["status"], "failed")

    def test_uncontained_model_transport_fences_without_terminal_audit(self) -> None:
        events: list[str] = []
        model = _Model(events, error=VllmTransportNotContained("worker alive"))
        service, admission, _, _, auditor, _ = self._service(
            events=events,
            model=model,
        )

        with self.assertRaisesRegex(
            CoordinatorContainmentError,
            "model transport was not contained",
        ):
            service.coordinate(
                _request(), principal=_principal(), cancellation=threading.Event()
            )

        self.assertNotEqual(admission.outcome, "completed")
        self.assertEqual(auditor.records, [])

    def test_model_can_abstain_without_a_bundle(self) -> None:
        events: list[str] = []
        model = _Model(
            events,
            decision=CoordinatorDecision("evidence-unavailable", ()),
        )
        service, _, _, _, auditor, _ = self._service(
            events=events,
            model=model,
        )

        view = service.coordinate(
            _request(), principal=_principal(), cancellation=threading.Event()
        )

        self.assertEqual(view.status, "evidence-unavailable")
        self.assertEqual(view.reason, "model-evidence-unavailable")
        self.assertIsNone(view.bundle)
        self.assertEqual(auditor.records[-1]["status"], "evidence-unavailable")

    def test_pre_cancelled_request_never_submits_or_reads(self) -> None:
        cancellation = threading.Event()
        cancellation.set()
        service, admission, reader, model, auditor, events = self._service()

        view = service.coordinate(
            _request(), principal=_principal(), cancellation=cancellation
        )

        self.assertEqual(view.status, "cancelled")
        self.assertEqual(view.reason, "client-cancelled")
        self.assertIsNone(admission.submission)
        self.assertEqual(reader.calls, 0)
        self.assertEqual(model.calls, 0)
        self.assertNotIn("submit", events)
        self.assertEqual(auditor.records[-1]["status"], "cancelled")

    def test_cancellation_after_completion_wins_before_success_audit(self) -> None:
        events: list[str] = []
        cancellation = threading.Event()
        admission = _Admission(events)
        admission.complete_hook = cancellation.set
        service, _, _, _, auditor, _ = self._service(
            events=events,
            admission=admission,
        )

        view = service.coordinate(
            _request(), principal=_principal(), cancellation=cancellation
        )

        self.assertEqual(view.status, "cancelled")
        self.assertIsNone(view.bundle)
        self.assertEqual(auditor.records[-1]["status"], "cancelled")

    def test_success_audit_cancellation_returns_one_terminal_cancel(self) -> None:
        events: list[str] = []
        auditor = _CancelSuccessOnceAuditor(events)
        service, _, _, _, _, _ = self._service(events=events, auditor=auditor)

        view = service.coordinate(
            _request(), principal=_principal(), cancellation=threading.Event()
        )

        self.assertEqual(view.status, "cancelled")
        self.assertIsNone(view.bundle)
        self.assertEqual(events.count("audit-cancelled"), 1)
        self.assertEqual(len(auditor.records), 1)
        self.assertEqual(auditor.records[0]["status"], "cancelled")

    def test_success_audit_authority_change_returns_unavailable(self) -> None:
        events: list[str] = []
        auditor = _StaleSuccessOnceAuditor(events)
        service, _, _, _, _, _ = self._service(events=events, auditor=auditor)

        view = service.coordinate(
            _request(), principal=_principal(), cancellation=threading.Event()
        )

        self.assertEqual(view.status, "evidence-unavailable")
        self.assertEqual(view.reason, "stale-generation")
        self.assertIsNone(view.bundle)
        self.assertEqual(events.count("audit-stale"), 1)
        self.assertEqual(len(auditor.records), 1)
        self.assertEqual(auditor.records[0]["status"], "evidence-unavailable")

    def test_submit_response_loss_requires_proven_containment(self) -> None:
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
        with self.assertRaisesRegex(
            CoordinatorContainmentError,
            "could not be contained",
        ):
            service.coordinate(
                _request(), principal=_principal(), cancellation=threading.Event()
            )

    def test_deadline_exhausted_before_submit_is_audited_without_cancel(self) -> None:
        service, admission, reader, model, auditor, events = self._service()

        with patch(
            "yap_server.agents.coordinator_service._remaining_deadline_ms",
            return_value=None,
        ):
            view = service.coordinate(
                _request(), principal=_principal(), cancellation=threading.Event()
            )

        self.assertEqual(view.status, "cancelled")
        self.assertEqual(view.reason, "deadline-exceeded")
        self.assertIsNone(admission.submission)
        self.assertEqual(reader.calls, 0)
        self.assertEqual(model.calls, 0)
        self.assertNotIn("cancel", events)
        self.assertEqual(auditor.records[-1]["status"], "cancelled")


if __name__ == "__main__":
    unittest.main()
