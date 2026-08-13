from __future__ import annotations

from dataclasses import dataclass
import threading
import time
from typing import Protocol

from psycopg import Error as PostgresError
from psycopg.errors import LockNotAvailable, QueryCanceled

from yap_server.auth import AuthenticatedPrincipal
from yap_server.knowledge.agent_reasoning_routes import ReasoningRetryableError
from yap_server.knowledge.knowledge_proposals import CoordinatorEvidenceChanged
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
from .coordinator import (
    CoordinatorEvidencePack,
    CoordinatorProposalBundle,
    CoordinatorRequest,
    build_coordinator_proposal_bundle,
    coordinator_request_sha256,
    validate_coordinator_evidence,
)
from .coordinator_model import CoordinatorDecision


COORDINATOR_OPERATION_DEADLINE_SECONDS = 60.0
COORDINATOR_TERMINAL_AUDIT_DEADLINE_SECONDS = 64.0
COORDINATOR_WORKFLOW_DEADLINE_SECONDS = 66.0

_COORDINATOR_WORK = AgentWorkSpec(
    role=AgentRole.COORDINATOR,
    purpose=AgentPurpose.CONVERSATION_COORDINATE,
    route=ExecutionRoute.COMPLEX_ORCHESTRATION,
    scheduling_class=SchedulingClass.BACKGROUND_LLM,
)
_ADMISSION_POLL_SECONDS = 0.05


class CoordinatorAdmission(Protocol):
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


class CoordinatorEvidenceReader(Protocol):
    def read(
        self,
        request: CoordinatorRequest,
        *,
        principal: AuthenticatedPrincipal,
        cancellation: threading.Event,
    ) -> CoordinatorEvidencePack: ...


class CoordinatorModel(Protocol):
    def select(
        self,
        request: CoordinatorRequest,
        evidence: CoordinatorEvidencePack,
        *,
        cancellation: threading.Event,
    ) -> CoordinatorDecision: ...


class CoordinatorResultAuditor(Protocol):
    def record(
        self,
        *,
        principal: AuthenticatedPrincipal,
        request_id: str,
        request: CoordinatorRequest,
        provider_generation: int | None,
        status: str,
        reason: str | None,
        evidence: CoordinatorEvidencePack | None,
        bundle: CoordinatorProposalBundle | None,
        duration_milliseconds: int,
        cancellation: threading.Event,
        deadline: float,
    ) -> None: ...


class CoordinatorContainmentError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CoordinatorJobView:
    request_id: str
    status: str
    bundle: CoordinatorProposalBundle | None = None
    reason: str | None = None

    def to_wire(self) -> dict[str, object]:
        value: dict[str, object] = {
            "schemaVersion": 1,
            "requestId": self.request_id,
            "status": self.status,
        }
        if self.bundle is not None:
            value["proposalBundle"] = self.bundle.to_wire()
        if self.reason is not None:
            value["reason"] = self.reason
        return value


class CoordinatorService:
    """Select a source-cited proposal bundle under exactly one complex lease."""

    def __init__(
        self,
        *,
        admission: CoordinatorAdmission,
        evidence_reader: CoordinatorEvidenceReader,
        model: CoordinatorModel,
        result_auditor: CoordinatorResultAuditor,
    ) -> None:
        self._admission = admission
        self._evidence_reader = evidence_reader
        self._model = model
        self._result_auditor = result_auditor

    def coordinate(
        self,
        request: CoordinatorRequest,
        *,
        principal: AuthenticatedPrincipal,
        cancellation: threading.Event,
    ) -> CoordinatorJobView:
        if not isinstance(request, CoordinatorRequest):
            raise TypeError("coordinator request type is invalid")
        if not isinstance(principal, AuthenticatedPrincipal):
            raise TypeError("coordinator principal type is invalid")
        if not isinstance(cancellation, threading.Event):
            raise TypeError("coordinator cancellation type is invalid")

        started = time.monotonic()
        operation_deadline = started + COORDINATOR_OPERATION_DEADLINE_SECONDS
        audit_deadline = started + COORDINATOR_TERMINAL_AUDIT_DEADLINE_SECONDS
        containment_deadline = started + COORDINATOR_WORKFLOW_DEADLINE_SECONDS
        ticket = self._admission.new_ticket()
        worker_cancellation = threading.Event()
        if cancellation.is_set():
            worker_cancellation.set()
        forwarding_stopped = threading.Event()
        forwarder = threading.Thread(
            target=_forward_cancellation,
            args=(cancellation, worker_cancellation, forwarding_stopped),
            name=f"coordinator-cancellation-{ticket.request_id}",
            daemon=False,
        )
        deadline_timer = threading.Timer(
            max(0.0, operation_deadline - time.monotonic()),
            worker_cancellation.set,
        )
        deadline_timer.name = f"coordinator-deadline-{ticket.request_id}"
        deadline_timer.daemon = False
        forwarder.start()
        deadline_timer.start()
        ticket_open = False
        evidence: CoordinatorEvidencePack | None = None
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

            remaining_deadline_ms = _remaining_deadline_ms(operation_deadline)
            if remaining_deadline_ms is None:
                return self._result(
                    ticket,
                    request,
                    principal=principal,
                    started=started,
                    status="cancelled",
                    reason="deadline-exceeded",
                    audit_deadline=audit_deadline,
                )
            try:
                admission = self._admission.submit(
                    ticket,
                    principal=principal,
                    work=_COORDINATOR_WORK,
                    source_sha256=coordinator_request_sha256(request),
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
                    audit_deadline=audit_deadline,
                )

            while admission.outcome == "queued":
                if worker_cancellation.wait(_ADMISSION_POLL_SECONDS):
                    view = self._cancelled_view(
                        ticket,
                        request,
                        principal,
                        started,
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
                evidence,
                admission,
                provider_generation,
                audit_deadline,
            )
            if terminal is not None:
                ticket_open = False
                return terminal
            _validate_admitted(admission)
            provider_generation = admission.provider_generation
            assert isinstance(provider_generation, int)
            if worker_cancellation.is_set():
                view = self._cancelled_view(
                    ticket,
                    request,
                    principal,
                    started,
                    evidence,
                    _cancellation_reason(cancellation, operation_deadline),
                    provider_generation,
                    audit_deadline,
                )
                ticket_open = False
                return view

            read_status: str | None = None
            read_reason: str | None = None
            try:
                evidence = self._evidence_reader.read(
                    request,
                    principal=principal,
                    cancellation=worker_cancellation,
                )
                if not isinstance(evidence, CoordinatorEvidencePack):
                    raise CoordinatorContainmentError(
                        "coordinator evidence result is invalid"
                    )
                validate_coordinator_evidence(request, evidence)
            except KnowledgeToolCancelled:
                view = self._cancelled_view(
                    ticket,
                    request,
                    principal,
                    started,
                    evidence,
                    _cancellation_reason(cancellation, operation_deadline),
                    provider_generation,
                    audit_deadline,
                )
                ticket_open = False
                return view
            except KnowledgeToolCancellationFailed as error:
                raise CoordinatorContainmentError(
                    "coordinator evidence read was not contained"
                ) from error
            except (KnowledgeGenerationStale, CoordinatorEvidenceChanged):
                read_status, read_reason = "evidence-unavailable", "stale-generation"
            except LookupError:
                read_status, read_reason = "evidence-unavailable", "empty-result"
            except PermissionError:
                read_status, read_reason = "failed", "unauthorized"
            except (KnowledgeToolTimedOut, QueryCanceled, LockNotAvailable):
                read_status, read_reason = "failed", "storage-timeout"
            except (OSError, PostgresError):
                read_status, read_reason = "failed", "storage-unavailable"

            if read_status is not None:
                view = self._complete_and_result(
                    ticket,
                    request,
                    principal,
                    started,
                    evidence,
                    provider_generation,
                    read_status,
                    read_reason,
                    audit_deadline,
                )
                ticket_open = False
                return view
            if evidence is None:
                raise CoordinatorContainmentError("coordinator returned no evidence")
            if not evidence.candidates or evidence.output_budget_exhausted:
                view = self._complete_and_result(
                    ticket,
                    request,
                    principal,
                    started,
                    evidence,
                    provider_generation,
                    "evidence-unavailable",
                    (
                        "incomplete-evidence"
                        if evidence.output_budget_exhausted
                        else "empty-result"
                    ),
                    audit_deadline,
                )
                ticket_open = False
                return view
            if worker_cancellation.is_set():
                view = self._cancelled_view(
                    ticket,
                    request,
                    principal,
                    started,
                    evidence,
                    _cancellation_reason(cancellation, operation_deadline),
                    provider_generation,
                    audit_deadline,
                )
                ticket_open = False
                return view

            decision: CoordinatorDecision | None = None
            model_reason: str | None = None
            try:
                decision = self._model.select(
                    request,
                    evidence,
                    cancellation=worker_cancellation,
                )
                if not isinstance(decision, CoordinatorDecision):
                    raise ValueError("coordinator model decision type is invalid")
            except KnowledgeToolCancelled:
                view = self._cancelled_view(
                    ticket,
                    request,
                    principal,
                    started,
                    evidence,
                    _cancellation_reason(cancellation, operation_deadline),
                    provider_generation,
                    audit_deadline,
                )
                ticket_open = False
                return view
            except ReasoningRetryableError:
                model_reason = "runtime-unavailable"
            except ValueError:
                model_reason = "invalid-output"
            except RuntimeError as error:
                raise CoordinatorContainmentError(
                    "coordinator model transport was not contained"
                ) from error

            current = self._admission.status(ticket)
            terminal = self._terminal_admission_view(
                ticket,
                request,
                principal,
                started,
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
                raise CoordinatorContainmentError(
                    "coordinator admission changed before completion"
                )
            if worker_cancellation.is_set():
                view = self._cancelled_view(
                    ticket,
                    request,
                    principal,
                    started,
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
                evidence,
                completed,
                provider_generation,
                audit_deadline,
            )
            if terminal is not None:
                ticket_open = False
                return terminal
            if completed.outcome != "completed":
                raise CoordinatorContainmentError(
                    "coordinator admission lease did not complete"
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
                    evidence=evidence,
                    provider_generation=provider_generation,
                    audit_deadline=audit_deadline,
                )
            if model_reason is not None:
                return self._result(
                    ticket,
                    request,
                    principal=principal,
                    started=started,
                    status="failed",
                    reason=model_reason,
                    evidence=evidence,
                    provider_generation=provider_generation,
                    audit_deadline=audit_deadline,
                )
            if decision is None:
                raise CoordinatorContainmentError("coordinator returned no decision")
            if decision.outcome == "evidence-unavailable":
                return self._result(
                    ticket,
                    request,
                    principal=principal,
                    started=started,
                    status="evidence-unavailable",
                    reason="model-evidence-unavailable",
                    evidence=evidence,
                    provider_generation=provider_generation,
                    audit_deadline=audit_deadline,
                )

            bundle = build_coordinator_proposal_bundle(request, evidence, decision)
            if bundle is None:
                raise CoordinatorContainmentError(
                    "coordinator bundle decision produced no bundle"
                )
            try:
                return self._result(
                    ticket,
                    request,
                    principal=principal,
                    started=started,
                    status="complete",
                    reason=None,
                    evidence=evidence,
                    bundle=bundle,
                    provider_generation=provider_generation,
                    response_bundle=bundle,
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
                    evidence=evidence,
                    provider_generation=provider_generation,
                    audit_deadline=audit_deadline,
                )
            except (
                KnowledgeGenerationStale,
                LookupError,
                CoordinatorEvidenceChanged,
            ):
                return self._result(
                    ticket,
                    request,
                    principal=principal,
                    started=started,
                    status="evidence-unavailable",
                    reason="stale-generation",
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

    def _complete_and_result(
        self,
        ticket: AgentAdmissionTicket,
        request: CoordinatorRequest,
        principal: AuthenticatedPrincipal,
        started: float,
        evidence: CoordinatorEvidencePack | None,
        provider_generation: int,
        status: str,
        reason: str,
        audit_deadline: float,
    ) -> CoordinatorJobView:
        current = self._admission.status(ticket)
        terminal = self._terminal_admission_view(
            ticket,
            request,
            principal,
            started,
            evidence,
            current,
            provider_generation,
            audit_deadline,
        )
        if terminal is not None:
            return terminal
        if (
            current.outcome != "admitted"
            or current.route is not ExecutionRoute.COMPLEX_ORCHESTRATION
            or current.provider_generation != provider_generation
        ):
            raise CoordinatorContainmentError(
                "coordinator admission changed before completion"
            )
        completed = self._admission.complete(ticket)
        terminal = self._terminal_admission_view(
            ticket,
            request,
            principal,
            started,
            evidence,
            completed,
            provider_generation,
            audit_deadline,
        )
        if terminal is not None:
            return terminal
        if completed.outcome != "completed":
            raise CoordinatorContainmentError(
                "coordinator admission lease did not complete"
            )
        return self._result(
            ticket,
            request,
            principal=principal,
            started=started,
            status=status,
            reason=reason,
            evidence=evidence,
            provider_generation=provider_generation,
            audit_deadline=audit_deadline,
        )

    def _result(
        self,
        ticket: AgentAdmissionTicket,
        request: CoordinatorRequest,
        *,
        principal: AuthenticatedPrincipal,
        started: float,
        status: str,
        reason: str | None,
        evidence: CoordinatorEvidencePack | None = None,
        bundle: CoordinatorProposalBundle | None = None,
        provider_generation: int | None = None,
        response_bundle: CoordinatorProposalBundle | None = None,
        audit_cancellation: threading.Event | None = None,
        audit_deadline: float,
    ) -> CoordinatorJobView:
        if audit_cancellation is None:
            audit_cancellation = threading.Event()
        self._result_auditor.record(
            principal=principal,
            request_id=ticket.request_id,
            request=request,
            provider_generation=provider_generation,
            status=status,
            reason=reason,
            evidence=evidence,
            bundle=bundle,
            duration_milliseconds=max(
                0,
                round((time.monotonic() - started) * 1_000),
            ),
            cancellation=audit_cancellation,
            deadline=audit_deadline,
        )
        return CoordinatorJobView(ticket.request_id, status, response_bundle, reason)

    def _cancelled_view(
        self,
        ticket: AgentAdmissionTicket,
        request: CoordinatorRequest,
        principal: AuthenticatedPrincipal,
        started: float,
        evidence: CoordinatorEvidencePack | None,
        reason: str,
        provider_generation: int | None,
        audit_deadline: float,
    ) -> CoordinatorJobView:
        cancelled = self._admission.cancel(ticket)
        expected = _expected_cancellation_outcome(cancelled)
        if expected is None:
            raise CoordinatorContainmentError(
                "coordinator cancellation was not admitted"
            )
        terminal = self._admission.acknowledge_cancellation(ticket)
        if terminal.outcome != expected:
            raise CoordinatorContainmentError(
                "coordinator cancellation was not acknowledged"
            )
        return self._result(
            ticket,
            request,
            principal=principal,
            started=started,
            status=("failed" if expected == "provider-unavailable" else "cancelled"),
            reason=(
                "provider-unavailable" if expected == "provider-unavailable" else reason
            ),
            evidence=evidence,
            provider_generation=provider_generation,
            audit_deadline=audit_deadline,
        )

    def _terminal_admission_view(
        self,
        ticket: AgentAdmissionTicket,
        request: CoordinatorRequest,
        principal: AuthenticatedPrincipal,
        started: float,
        evidence: CoordinatorEvidencePack | None,
        admission: AgentAdmission,
        provider_generation: int | None,
        audit_deadline: float,
    ) -> CoordinatorJobView | None:
        if admission.outcome == "cancellation-requested":
            expected = _expected_cancellation_outcome(admission)
            if expected is None:
                raise CoordinatorContainmentError(
                    "coordinator cancellation response is invalid"
                )
            terminal = self._admission.acknowledge_cancellation(ticket)
            if terminal.outcome != expected:
                raise CoordinatorContainmentError(
                    "coordinator cancellation was not acknowledged"
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
            raise CoordinatorContainmentError(
                "coordinator admission could not be contained"
            )


def _validate_admitted(admission: AgentAdmission) -> None:
    if (
        admission.outcome != "admitted"
        or admission.route is not ExecutionRoute.COMPLEX_ORCHESTRATION
        or isinstance(admission.provider_generation, bool)
        or not isinstance(admission.provider_generation, int)
        or admission.provider_generation < 1
    ):
        raise CoordinatorContainmentError(
            "coordinator admission lease identity is invalid"
        )


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
    "COORDINATOR_OPERATION_DEADLINE_SECONDS",
    "COORDINATOR_TERMINAL_AUDIT_DEADLINE_SECONDS",
    "COORDINATOR_WORKFLOW_DEADLINE_SECONDS",
    "CoordinatorContainmentError",
    "CoordinatorJobView",
    "CoordinatorService",
]
