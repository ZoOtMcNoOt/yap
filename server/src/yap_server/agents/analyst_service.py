from __future__ import annotations

from dataclasses import dataclass
import threading
import time
from typing import Protocol

from psycopg import Error as PostgresError
from psycopg.errors import LockNotAvailable, QueryCanceled

from yap_server.auth import AuthenticatedPrincipal
from yap_server.knowledge.agent_reasoning_routes import ReasoningRetryableError
from yap_server.knowledge.knowledge_tool_contract import (
    KnowledgeGenerationStale,
    KnowledgeToolCancellationFailed,
    KnowledgeToolCancelled,
    KnowledgeToolTimedOut,
)

from .admission_protocol import (
    AgentAdmission,
    AgentAdmissionTicket,
    AgentPurpose,
    AgentRole,
    AgentWorkSpec,
    ExecutionRoute,
    SchedulingClass,
)
from .analyst import (
    AnalystAnswer,
    AnalystEvidenceChanged,
    AnalystRequest,
    analyst_work_sha256,
    build_analyst_answer,
)
from .analyst_model import AnalystDecision
from .librarian import LibrarianEvidencePack, LibrarianRequest
from .librarian_service import LibrarianJobView


ANALYST_OPERATION_DEADLINE_SECONDS = 80.0
ANALYST_TERMINAL_AUDIT_DEADLINE_SECONDS = 84.0
ANALYST_WORKFLOW_DEADLINE_SECONDS = 86.0

_ANALYST_WORK = AgentWorkSpec(
    role=AgentRole.ANALYST,
    purpose=AgentPurpose.KNOWLEDGE_ANSWER,
    route=ExecutionRoute.COMPLEX_ORCHESTRATION,
    scheduling_class=SchedulingClass.INTERACTIVE,
)
_ADMISSION_POLL_SECONDS = 0.05


class AnalystAdmission(Protocol):
    def new_ticket(self) -> AgentAdmissionTicket: ...

    def submit(
        self,
        ticket: AgentAdmissionTicket,
        *,
        principal: AuthenticatedPrincipal,
        work: AgentWorkSpec,
        source_sha256: str,
        remaining_deadline_ms: int,
    ) -> AgentAdmission: ...

    def status(self, ticket: AgentAdmissionTicket) -> AgentAdmission: ...

    def cancel(self, ticket: AgentAdmissionTicket) -> AgentAdmission: ...

    def complete(self, ticket: AgentAdmissionTicket) -> AgentAdmission: ...

    def acknowledge_cancellation(
        self,
        ticket: AgentAdmissionTicket,
    ) -> AgentAdmission: ...


class AnalystLibrarian(Protocol):
    def query(
        self,
        request: LibrarianRequest,
        *,
        principal: AuthenticatedPrincipal,
        cancellation: threading.Event,
    ) -> LibrarianJobView: ...


class AnalystModel(Protocol):
    def answer(
        self,
        request: AnalystRequest,
        evidence: LibrarianEvidencePack,
        *,
        cancellation: threading.Event,
    ) -> AnalystDecision: ...


class AnalystEvidenceVerifier(Protocol):
    def verify(
        self,
        request: AnalystRequest,
        evidence: LibrarianEvidencePack,
        *,
        principal: AuthenticatedPrincipal,
        cancellation: threading.Event,
    ) -> None: ...


class AnalystResultAuditor(Protocol):
    def record(
        self,
        *,
        principal: AuthenticatedPrincipal,
        request_id: str,
        librarian_request_id: str | None,
        request: AnalystRequest,
        provider_generation: int | None,
        status: str,
        reason: str | None,
        evidence: LibrarianEvidencePack | None,
        answer: AnalystAnswer | None,
        duration_milliseconds: int,
        cancellation: threading.Event,
        deadline: float,
    ) -> None: ...


class AnalystContainmentError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AnalystJobView:
    request_id: str
    status: str
    answer: AnalystAnswer | None = None
    reason: str | None = None

    def to_wire(self) -> dict[str, object]:
        value: dict[str, object] = {
            "schemaVersion": 1,
            "requestId": self.request_id,
            "status": self.status,
        }
        if self.answer is not None:
            value["citedAnswer"] = self.answer.to_wire()
        if self.reason is not None:
            value["reason"] = self.reason
        return value


class AnalystService:
    """Retrieve first, then run one extractive answer selection under Gemma."""

    def __init__(
        self,
        *,
        admission: AnalystAdmission,
        librarian: AnalystLibrarian,
        evidence_verifier: AnalystEvidenceVerifier,
        model: AnalystModel,
        result_auditor: AnalystResultAuditor,
    ) -> None:
        self._admission = admission
        self._librarian = librarian
        self._evidence_verifier = evidence_verifier
        self._model = model
        self._result_auditor = result_auditor

    def answer(
        self,
        request: AnalystRequest,
        *,
        principal: AuthenticatedPrincipal,
        cancellation: threading.Event,
    ) -> AnalystJobView:
        if not isinstance(request, AnalystRequest):
            raise TypeError("analyst request type is invalid")
        if not isinstance(principal, AuthenticatedPrincipal):
            raise TypeError("analyst principal type is invalid")
        if not isinstance(cancellation, threading.Event):
            raise TypeError("analyst cancellation type is invalid")

        started = time.monotonic()
        operation_deadline = started + ANALYST_OPERATION_DEADLINE_SECONDS
        audit_deadline = started + ANALYST_TERMINAL_AUDIT_DEADLINE_SECONDS
        containment_deadline = started + ANALYST_WORKFLOW_DEADLINE_SECONDS
        ticket = self._admission.new_ticket()
        worker_cancellation = threading.Event()
        if cancellation.is_set():
            worker_cancellation.set()
        forwarding_stopped = threading.Event()
        forwarder = threading.Thread(
            target=_forward_cancellation,
            args=(cancellation, worker_cancellation, forwarding_stopped),
            name=f"analyst-cancellation-{ticket.request_id}",
            daemon=False,
        )
        deadline_timer = threading.Timer(
            max(0.0, operation_deadline - time.monotonic()),
            worker_cancellation.set,
        )
        deadline_timer.name = f"analyst-deadline-{ticket.request_id}"
        deadline_timer.daemon = False
        forwarder.start()
        deadline_timer.start()
        ticket_open = False
        librarian_request_id: str | None = None
        evidence: LibrarianEvidencePack | None = None
        provider_generation: int | None = None
        try:
            if worker_cancellation.is_set():
                return self._result(
                    ticket,
                    request,
                    principal=principal,
                    started=started,
                    status="cancelled",
                    reason=_cancellation_reason(cancellation, operation_deadline),
                    audit_deadline=audit_deadline,
                )

            librarian = self._librarian.query(
                LibrarianRequest(
                    search_text=request.question,
                    maximum_results=request.maximum_results,
                    expected_generation_sha256=request.expected_generation_sha256,
                ),
                principal=principal,
                cancellation=worker_cancellation,
            )
            if not isinstance(librarian, LibrarianJobView):
                raise AnalystContainmentError("analyst librarian result is invalid")
            librarian_request_id = librarian.request_id
            if librarian.status != "complete":
                status, reason = _librarian_failure(librarian)
                return self._result(
                    ticket,
                    request,
                    principal=principal,
                    started=started,
                    status=status,
                    reason=reason,
                    librarian_request_id=librarian_request_id,
                    audit_deadline=audit_deadline,
                )
            evidence = librarian.evidence
            if evidence is None or not evidence.items:
                raise AnalystContainmentError(
                    "analyst librarian success omitted evidence"
                )
            if evidence.output_budget_exhausted:
                return self._result(
                    ticket,
                    request,
                    principal=principal,
                    started=started,
                    status="evidence-unavailable",
                    reason="incomplete-evidence",
                    librarian_request_id=librarian_request_id,
                    evidence=evidence,
                    audit_deadline=audit_deadline,
                )
            if worker_cancellation.is_set():
                return self._result(
                    ticket,
                    request,
                    principal=principal,
                    started=started,
                    status="cancelled",
                    reason=_cancellation_reason(cancellation, operation_deadline),
                    librarian_request_id=librarian_request_id,
                    evidence=evidence,
                    audit_deadline=audit_deadline,
                )

            source_sha256 = analyst_work_sha256(request, evidence)
            remaining_deadline_ms = _remaining_deadline_ms(operation_deadline)
            if remaining_deadline_ms is None:
                return self._result(
                    ticket,
                    request,
                    principal=principal,
                    started=started,
                    status="cancelled",
                    reason="deadline-exceeded",
                    librarian_request_id=librarian_request_id,
                    evidence=evidence,
                    audit_deadline=audit_deadline,
                )
            try:
                admission = self._admission.submit(
                    ticket,
                    principal=principal,
                    work=_ANALYST_WORK,
                    source_sha256=source_sha256,
                    remaining_deadline_ms=remaining_deadline_ms,
                )
                ticket_open = admission.outcome in {"queued", "admitted"}
            except BaseException:
                self._contain_ticket(ticket)
                raise
            if admission.outcome not in {"queued", "admitted"}:
                return self._result(
                    ticket,
                    request,
                    principal=principal,
                    started=started,
                    status="failed",
                    reason=_admission_reason(admission.outcome),
                    librarian_request_id=librarian_request_id,
                    evidence=evidence,
                    audit_deadline=audit_deadline,
                )

            while admission.outcome == "queued":
                if worker_cancellation.wait(_ADMISSION_POLL_SECONDS):
                    view = self._cancelled_view(
                        ticket,
                        request,
                        principal,
                        started,
                        librarian_request_id,
                        evidence,
                        _cancellation_reason(cancellation, operation_deadline),
                        provider_generation,
                        audit_deadline,
                    )
                    ticket_open = False
                    return view
                admission = self._admission.status(ticket)
            terminal = self._terminal_admission_view(
                ticket,
                request,
                principal,
                started,
                librarian_request_id,
                evidence,
                admission,
                provider_generation,
                audit_deadline,
            )
            if terminal is not None:
                ticket_open = False
                return terminal
            if (
                admission.outcome != "admitted"
                or admission.route is not ExecutionRoute.COMPLEX_ORCHESTRATION
                or isinstance(admission.provider_generation, bool)
                or not isinstance(admission.provider_generation, int)
                or admission.provider_generation < 1
            ):
                raise AnalystContainmentError(
                    "analyst admission lease identity is invalid"
                )
            provider_generation = admission.provider_generation
            if worker_cancellation.is_set():
                view = self._cancelled_view(
                    ticket,
                    request,
                    principal,
                    started,
                    librarian_request_id,
                    evidence,
                    _cancellation_reason(cancellation, operation_deadline),
                    provider_generation,
                    audit_deadline,
                )
                ticket_open = False
                return view

            try:
                self._evidence_verifier.verify(
                    request,
                    evidence,
                    principal=principal,
                    cancellation=worker_cancellation,
                )
            except KnowledgeToolCancelled:
                view = self._cancelled_view(
                    ticket,
                    request,
                    principal,
                    started,
                    librarian_request_id,
                    evidence,
                    _cancellation_reason(cancellation, operation_deadline),
                    provider_generation,
                    audit_deadline,
                )
                ticket_open = False
                return view
            except KnowledgeToolCancellationFailed as error:
                raise AnalystContainmentError(
                    "analyst evidence reauthorization was not contained"
                ) from error
            except (KnowledgeGenerationStale, LookupError, AnalystEvidenceChanged):
                failure_reason = "stale-generation"
            except KnowledgeToolTimedOut:
                failure_reason = "storage-timeout"
            except (QueryCanceled, LockNotAvailable):
                failure_reason = "storage-timeout"
            except (OSError, PostgresError):
                failure_reason = "storage-unavailable"
            else:
                failure_reason = None

            if failure_reason is not None:
                current = self._admission.status(ticket)
                terminal = self._terminal_admission_view(
                    ticket,
                    request,
                    principal,
                    started,
                    librarian_request_id,
                    evidence,
                    current,
                    provider_generation,
                    audit_deadline,
                )
                if terminal is not None:
                    ticket_open = False
                    return terminal
                completed = self._admission.complete(ticket)
                terminal = self._terminal_admission_view(
                    ticket,
                    request,
                    principal,
                    started,
                    librarian_request_id,
                    evidence,
                    completed,
                    provider_generation,
                    audit_deadline,
                )
                if terminal is not None:
                    ticket_open = False
                    return terminal
                if completed.outcome != "completed":
                    raise AnalystContainmentError(
                        "analyst admission lease did not complete"
                    )
                ticket_open = False
                return self._result(
                    ticket,
                    request,
                    principal=principal,
                    started=started,
                    status=(
                        "evidence-unavailable"
                        if failure_reason == "stale-generation"
                        else "failed"
                    ),
                    reason=failure_reason,
                    librarian_request_id=librarian_request_id,
                    evidence=evidence,
                    provider_generation=provider_generation,
                    audit_deadline=audit_deadline,
                )

            decision: AnalystDecision | None = None
            failure_reason: str | None = None
            try:
                decision = self._model.answer(
                    request,
                    evidence,
                    cancellation=worker_cancellation,
                )
                if not isinstance(decision, AnalystDecision):
                    raise ValueError("analyst model decision type is invalid")
            except KnowledgeToolCancelled:
                view = self._cancelled_view(
                    ticket,
                    request,
                    principal,
                    started,
                    librarian_request_id,
                    evidence,
                    _cancellation_reason(cancellation, operation_deadline),
                    provider_generation,
                    audit_deadline,
                )
                ticket_open = False
                return view
            except ReasoningRetryableError:
                failure_reason = "runtime-unavailable"
            except ValueError:
                failure_reason = "invalid-output"
            except RuntimeError as error:
                raise AnalystContainmentError(
                    "analyst model transport was not contained"
                ) from error

            current = self._admission.status(ticket)
            terminal = self._terminal_admission_view(
                ticket,
                request,
                principal,
                started,
                librarian_request_id,
                evidence,
                current,
                provider_generation,
                audit_deadline,
            )
            if terminal is not None:
                ticket_open = False
                return terminal
            if (
                current.outcome != "admitted"
                or current.route is not ExecutionRoute.COMPLEX_ORCHESTRATION
                or current.provider_generation != provider_generation
            ):
                raise AnalystContainmentError(
                    "analyst admission changed before completion"
                )
            if worker_cancellation.is_set():
                view = self._cancelled_view(
                    ticket,
                    request,
                    principal,
                    started,
                    librarian_request_id,
                    evidence,
                    _cancellation_reason(cancellation, operation_deadline),
                    provider_generation,
                    audit_deadline,
                )
                ticket_open = False
                return view

            completed = self._admission.complete(ticket)
            terminal = self._terminal_admission_view(
                ticket,
                request,
                principal,
                started,
                librarian_request_id,
                evidence,
                completed,
                provider_generation,
                audit_deadline,
            )
            if terminal is not None:
                ticket_open = False
                return terminal
            if completed.outcome != "completed":
                raise AnalystContainmentError(
                    "analyst admission lease did not complete"
                )
            ticket_open = False

            if worker_cancellation.is_set() or cancellation.is_set():
                return self._result(
                    ticket,
                    request,
                    principal=principal,
                    started=started,
                    status="cancelled",
                    reason=_cancellation_reason(cancellation, operation_deadline),
                    librarian_request_id=librarian_request_id,
                    evidence=evidence,
                    provider_generation=provider_generation,
                    audit_deadline=audit_deadline,
                )
            if failure_reason is not None:
                return self._result(
                    ticket,
                    request,
                    principal=principal,
                    started=started,
                    status="failed",
                    reason=failure_reason,
                    librarian_request_id=librarian_request_id,
                    evidence=evidence,
                    provider_generation=provider_generation,
                    audit_deadline=audit_deadline,
                )
            if decision is None:
                raise AnalystContainmentError("analyst returned no decision")
            if decision.outcome == "evidence-unavailable":
                return self._result(
                    ticket,
                    request,
                    principal=principal,
                    started=started,
                    status="evidence-unavailable",
                    reason="model-evidence-unavailable",
                    librarian_request_id=librarian_request_id,
                    evidence=evidence,
                    provider_generation=provider_generation,
                    audit_deadline=audit_deadline,
                )

            answer = build_analyst_answer(request, evidence, decision)
            if answer is None:
                raise AnalystContainmentError(
                    "analyst answer decision produced no answer"
                )
            try:
                return self._result(
                    ticket,
                    request,
                    principal=principal,
                    started=started,
                    status="complete",
                    reason=None,
                    librarian_request_id=librarian_request_id,
                    evidence=evidence,
                    answer=answer,
                    provider_generation=provider_generation,
                    response_answer=answer,
                    audit_cancellation=worker_cancellation,
                    audit_deadline=audit_deadline,
                )
            except (KnowledgeToolCancelled, KnowledgeToolTimedOut):
                return self._result(
                    ticket,
                    request,
                    principal=principal,
                    started=started,
                    status="cancelled",
                    reason=_cancellation_reason(cancellation, operation_deadline),
                    librarian_request_id=librarian_request_id,
                    evidence=evidence,
                    provider_generation=provider_generation,
                    audit_deadline=audit_deadline,
                )
            except (KnowledgeGenerationStale, LookupError, AnalystEvidenceChanged):
                return self._result(
                    ticket,
                    request,
                    principal=principal,
                    started=started,
                    status="evidence-unavailable",
                    reason="stale-generation",
                    librarian_request_id=librarian_request_id,
                    evidence=evidence,
                    provider_generation=provider_generation,
                    audit_deadline=audit_deadline,
                )
            except (QueryCanceled, LockNotAvailable):
                return self._result(
                    ticket,
                    request,
                    principal=principal,
                    started=started,
                    status="failed",
                    reason="storage-timeout",
                    librarian_request_id=librarian_request_id,
                    evidence=evidence,
                    provider_generation=provider_generation,
                    audit_deadline=audit_deadline,
                )
            except (OSError, PostgresError):
                return self._result(
                    ticket,
                    request,
                    principal=principal,
                    started=started,
                    status="failed",
                    reason="storage-unavailable",
                    librarian_request_id=librarian_request_id,
                    evidence=evidence,
                    provider_generation=provider_generation,
                    audit_deadline=audit_deadline,
                )
        except BaseException:
            if ticket_open:
                self._contain_ticket(ticket)
            raise
        finally:
            forwarding_stopped.set()
            forwarder.join()
            deadline_timer.cancel()
            deadline_timer.join()
            if time.monotonic() > containment_deadline:
                worker_cancellation.set()

    def _result(
        self,
        ticket: AgentAdmissionTicket,
        request: AnalystRequest,
        *,
        principal: AuthenticatedPrincipal,
        started: float,
        status: str,
        reason: str | None,
        librarian_request_id: str | None = None,
        evidence: LibrarianEvidencePack | None = None,
        answer: AnalystAnswer | None = None,
        provider_generation: int | None = None,
        response_answer: AnalystAnswer | None = None,
        audit_cancellation: threading.Event | None = None,
        audit_deadline: float,
    ) -> AnalystJobView:
        if audit_cancellation is None:
            audit_cancellation = threading.Event()
        self._result_auditor.record(
            principal=principal,
            request_id=ticket.request_id,
            librarian_request_id=librarian_request_id,
            request=request,
            provider_generation=provider_generation,
            status=status,
            reason=reason,
            evidence=evidence,
            answer=answer,
            duration_milliseconds=max(
                0,
                round((time.monotonic() - started) * 1_000),
            ),
            cancellation=audit_cancellation,
            deadline=audit_deadline,
        )
        return AnalystJobView(ticket.request_id, status, response_answer, reason)

    def _cancelled_view(
        self,
        ticket: AgentAdmissionTicket,
        request: AnalystRequest,
        principal: AuthenticatedPrincipal,
        started: float,
        librarian_request_id: str,
        evidence: LibrarianEvidencePack,
        reason: str,
        provider_generation: int | None,
        audit_deadline: float,
    ) -> AnalystJobView:
        cancelled = self._admission.cancel(ticket)
        expected = _expected_cancellation_outcome(cancelled)
        if expected is None:
            raise AnalystContainmentError("analyst cancellation was not admitted")
        terminal = self._admission.acknowledge_cancellation(ticket)
        if terminal.outcome != expected:
            raise AnalystContainmentError("analyst cancellation was not acknowledged")
        return self._result(
            ticket,
            request,
            principal=principal,
            started=started,
            status=("failed" if expected == "provider-unavailable" else "cancelled"),
            reason=(
                "provider-unavailable" if expected == "provider-unavailable" else reason
            ),
            librarian_request_id=librarian_request_id,
            evidence=evidence,
            provider_generation=provider_generation,
            audit_deadline=audit_deadline,
        )

    def _terminal_admission_view(
        self,
        ticket: AgentAdmissionTicket,
        request: AnalystRequest,
        principal: AuthenticatedPrincipal,
        started: float,
        librarian_request_id: str,
        evidence: LibrarianEvidencePack,
        admission: AgentAdmission,
        provider_generation: int | None,
        audit_deadline: float,
    ) -> AnalystJobView | None:
        if admission.outcome == "cancellation-requested":
            expected = _expected_cancellation_outcome(admission)
            if expected is None:
                raise AnalystContainmentError(
                    "analyst cancellation response is invalid"
                )
            terminal = self._admission.acknowledge_cancellation(ticket)
            if terminal.outcome != expected:
                raise AnalystContainmentError(
                    "analyst cancellation was not acknowledged"
                )
            return self._result(
                ticket,
                request,
                principal=principal,
                started=started,
                status=(
                    "failed" if expected == "provider-unavailable" else "cancelled"
                ),
                reason=_admission_reason(expected),
                librarian_request_id=librarian_request_id,
                evidence=evidence,
                provider_generation=provider_generation,
                audit_deadline=audit_deadline,
            )
        if admission.outcome not in {
            "cancelled",
            "deadline-exceeded",
            "provider-unavailable",
        }:
            return None
        return self._result(
            ticket,
            request,
            principal=principal,
            started=started,
            status=(
                "failed" if admission.outcome == "provider-unavailable" else "cancelled"
            ),
            reason=_admission_reason(admission.outcome),
            librarian_request_id=librarian_request_id,
            evidence=evidence,
            provider_generation=provider_generation,
            audit_deadline=audit_deadline,
        )

    def _contain_ticket(self, ticket: AgentAdmissionTicket) -> None:
        try:
            cancelled = self._admission.cancel(ticket)
            if cancelled.outcome == "cancellation-requested":
                terminal = self._admission.acknowledge_cancellation(ticket)
                contained = terminal.outcome in {
                    "cancelled",
                    "deadline-exceeded",
                    "provider-unavailable",
                }
            else:
                contained = cancelled.outcome in {
                    "cancelled",
                    "completed",
                    "deadline-exceeded",
                    "provider-unavailable",
                }
        except BaseException:
            contained = False
        if not contained:
            raise AnalystContainmentError("analyst admission could not be contained")


def _librarian_failure(view: LibrarianJobView) -> tuple[str, str]:
    if view.status == "evidence-unavailable":
        return "evidence-unavailable", view.reason or "evidence-unavailable"
    if view.status == "failed" and view.reason == "stale-generation":
        return "evidence-unavailable", "stale-generation"
    if view.status == "cancelled":
        return "cancelled", view.reason or "client-cancelled"
    if view.status == "failed":
        return "failed", view.reason or "storage-unavailable"
    raise AnalystContainmentError("analyst librarian entered an unknown state")


def _remaining_deadline_ms(deadline: float) -> int | None:
    remaining = int(max(0.0, deadline - time.monotonic()) * 1_000)
    if remaining <= 0:
        return None
    return remaining


def _expected_cancellation_outcome(admission: AgentAdmission) -> str | None:
    if admission.outcome in {
        "cancelled",
        "deadline-exceeded",
        "provider-unavailable",
    }:
        return admission.outcome
    if admission.outcome != "cancellation-requested":
        return None
    return {
        "client-requested": "cancelled",
        "deadline-exceeded": "deadline-exceeded",
        "provider-unavailable": "provider-unavailable",
    }.get(admission.cancellation_reason)


def _admission_reason(outcome: str) -> str:
    return {
        "cancelled": "client-cancelled",
        "deadline-exceeded": "deadline-exceeded",
        "provider-unavailable": "provider-unavailable",
        "owner-queue-full": "capacity-unavailable",
        "queue-full": "capacity-unavailable",
    }.get(outcome, "admission-failed")


def _cancellation_reason(cancellation: threading.Event, deadline: float) -> str:
    if cancellation.is_set():
        return "client-cancelled"
    if time.monotonic() >= deadline:
        return "deadline-exceeded"
    return "client-cancelled"


def _forward_cancellation(
    source: threading.Event,
    target: threading.Event,
    stopped: threading.Event,
) -> None:
    while not stopped.wait(0.01):
        if source.is_set():
            target.set()
            return


__all__ = [
    "ANALYST_OPERATION_DEADLINE_SECONDS",
    "ANALYST_TERMINAL_AUDIT_DEADLINE_SECONDS",
    "ANALYST_WORKFLOW_DEADLINE_SECONDS",
    "AnalystContainmentError",
    "AnalystJobView",
    "AnalystService",
]
