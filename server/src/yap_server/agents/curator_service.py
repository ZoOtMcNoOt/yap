from __future__ import annotations

from dataclasses import dataclass
import threading
import time
from typing import Protocol

from psycopg import Error as PostgresError
from psycopg.errors import LockNotAvailable, QueryCanceled

from yap_server.agents.admission_protocol import (
    AgentAdmission,
    AgentAdmissionTicket,
    AgentPurpose,
    AgentRole,
    AgentWorkSpec,
    ExecutionRoute,
    SchedulingClass,
)
from yap_server.auth import AuthenticatedPrincipal
from yap_server.knowledge.agent_reasoning_routes import ReasoningRetryableError
from yap_server.knowledge.knowledge_proposals import (
    KnowledgeProposal,
    KnowledgeProposalCapacityExceeded,
)
from yap_server.knowledge.knowledge_tool_contract import (
    KnowledgeToolCancellationFailed,
    KnowledgeToolCancelled,
    KnowledgeToolTimedOut,
)

from .curator import (
    CuratorEvidence,
    CuratorRequest,
    curator_request_sha256,
    curator_work_sha256,
    validate_curator_evidence,
)
from .curator_model import CuratorDecision
from .curator_result_audit import CuratorStoredResult


_CURATOR_WORK = AgentWorkSpec(
    role=AgentRole.CURATOR,
    purpose=AgentPurpose.KNOWLEDGE_PROPOSE,
    route=ExecutionRoute.COMPLEX_ORCHESTRATION,
    scheduling_class=SchedulingClass.BACKGROUND_LLM,
)
_DEADLINE_SECONDS = 60.0
_ADMISSION_POLL_SECONDS = 0.05


class CuratorAdmission(Protocol):
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


class CuratorEvidenceReader(Protocol):
    def read(
        self,
        request: CuratorRequest,
        *,
        principal: AuthenticatedPrincipal,
        cancellation: threading.Event,
    ) -> CuratorEvidence: ...


class CuratorReviewer(Protocol):
    def review(
        self,
        request: CuratorRequest,
        evidence: CuratorEvidence,
        *,
        cancellation: threading.Event,
    ) -> CuratorDecision: ...


class CuratorResultAuditor(Protocol):
    def read(
        self,
        *,
        principal: AuthenticatedPrincipal,
        submission_id: str,
    ) -> CuratorStoredResult | None: ...

    def record(
        self,
        *,
        principal: AuthenticatedPrincipal,
        request_id: str,
        request: CuratorRequest,
        provider_generation: int | None,
        status: str,
        reason: str | None,
        evidence: CuratorEvidence | None,
        proposal_id: str | None,
        proposal_permission_hash: str | None = None,
        proposal_authorization_hash: str | None = None,
        duration_milliseconds: int,
    ) -> None: ...


class CuratorPublisher(Protocol):
    def publish(
        self,
        *,
        principal: AuthenticatedPrincipal,
        request_id: str,
        request: CuratorRequest,
        evidence: CuratorEvidence,
        provider_generation: int,
        started: float,
        deadline: float,
        cancellation: threading.Event,
    ) -> KnowledgeProposal: ...


class CuratorServiceError(RuntimeError):
    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        *,
        retryable: bool,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.retryable = retryable


class CuratorContainmentError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CuratorJobView:
    request_id: str
    submission_id: str
    status: str
    generation_sha256: str
    evidence_sha256: str | None = None
    proposal_id: str | None = None
    reason: str | None = None

    def to_wire(self) -> dict[str, object]:
        value: dict[str, object] = {
            "schemaVersion": 1,
            "requestId": self.request_id,
            "submissionId": self.submission_id,
            "status": self.status,
            "generationSha256": self.generation_sha256,
        }
        if self.evidence_sha256 is not None:
            value["evidenceSha256"] = self.evidence_sha256
        if self.proposal_id is not None:
            value["proposalId"] = self.proposal_id
        if self.reason is not None:
            value["reason"] = self.reason
        return value


class CuratorService:
    """Review and atomically publish one cited noncanonical proposal."""

    def __init__(
        self,
        *,
        admission: CuratorAdmission,
        evidence_reader: CuratorEvidenceReader,
        reviewer: CuratorReviewer,
        publisher: CuratorPublisher,
        result_auditor: CuratorResultAuditor,
    ) -> None:
        self._admission = admission
        self._evidence_reader = evidence_reader
        self._reviewer = reviewer
        self._publisher = publisher
        self._result_auditor = result_auditor

    def propose(
        self,
        request: CuratorRequest,
        *,
        principal: AuthenticatedPrincipal,
        cancellation: threading.Event,
    ) -> CuratorJobView:
        if not isinstance(request, CuratorRequest):
            raise TypeError("curator request type is invalid")
        if not isinstance(principal, AuthenticatedPrincipal):
            raise TypeError("curator principal type is invalid")
        if not isinstance(cancellation, threading.Event):
            raise TypeError("curator cancellation type is invalid")

        stored = self._read_stored(request, principal)
        if stored is not None:
            return _stored_view(stored)

        started = time.monotonic()
        deadline = started + _DEADLINE_SECONDS
        ticket = self._admission.new_ticket()
        worker_cancellation = threading.Event()
        if cancellation.is_set():
            worker_cancellation.set()
        forwarding_stopped = threading.Event()
        forwarder = threading.Thread(
            target=_forward_cancellation,
            args=(cancellation, worker_cancellation, forwarding_stopped),
            name=f"curator-cancellation-{ticket.request_id}",
            daemon=False,
        )
        deadline_timer = threading.Timer(
            max(0.0, deadline - time.monotonic()),
            worker_cancellation.set,
        )
        deadline_timer.name = f"curator-deadline-{ticket.request_id}"
        deadline_timer.daemon = False
        forwarder.start()
        deadline_timer.start()
        ticket_open = False
        provider_generation: int | None = None
        try:
            try:
                evidence = self._evidence_reader.read(
                    request,
                    principal=principal,
                    cancellation=worker_cancellation,
                )
                validate_curator_evidence(request, evidence)
            except KnowledgeToolCancelled:
                return self._result(
                    ticket,
                    request,
                    principal=principal,
                    started=started,
                    status="cancelled",
                    reason=_cancellation_reason(cancellation, deadline),
                )
            except KnowledgeToolCancellationFailed as error:
                raise CuratorContainmentError(
                    "curator evidence cancellation was not contained"
                ) from error
            except KnowledgeToolTimedOut:
                return self._result(
                    ticket,
                    request,
                    principal=principal,
                    started=started,
                    status="failed",
                    reason="storage-timeout",
                )
            except LookupError:
                return self._result(
                    ticket,
                    request,
                    principal=principal,
                    started=started,
                    status="failed",
                    reason="evidence-unavailable",
                )
            except ValueError:
                return self._result(
                    ticket,
                    request,
                    principal=principal,
                    started=started,
                    status="failed",
                    reason="stale-or-invalid-generation",
                )
            except (OSError, PostgresError):
                return self._result(
                    ticket,
                    request,
                    principal=principal,
                    started=started,
                    status="failed",
                    reason="storage-unavailable",
                )

            if worker_cancellation.is_set():
                return self._result(
                    ticket,
                    request,
                    principal=principal,
                    started=started,
                    status="cancelled",
                    reason=_cancellation_reason(cancellation, deadline),
                    evidence=evidence,
                )

            try:
                try:
                    remaining_deadline_ms = _remaining_deadline_ms(deadline)
                except CuratorServiceError:
                    return self._result(
                        ticket,
                        request,
                        principal=principal,
                        started=started,
                        status="failed",
                        reason="deadline-exceeded",
                        evidence=evidence,
                    )
                admission = self._admission.submit(
                    ticket,
                    principal=principal,
                    work=_CURATOR_WORK,
                    source_sha256=curator_work_sha256(request, evidence),
                    remaining_deadline_ms=remaining_deadline_ms,
                )
                ticket_open = admission.outcome in {"queued", "admitted"}
            except BaseException:
                self._contain_ticket(ticket)
                raise
            if admission.outcome not in {"queued", "admitted"}:
                view = self._result(
                    ticket,
                    request,
                    principal=principal,
                    started=started,
                    status="failed",
                    reason=_admission_reason(admission.outcome),
                    evidence=evidence,
                )
                return view

            while admission.outcome == "queued":
                if worker_cancellation.wait(_ADMISSION_POLL_SECONDS):
                    view = self._cancelled_view(
                        ticket,
                        request,
                        evidence,
                        principal,
                        started,
                        _cancellation_reason(cancellation, deadline),
                        provider_generation,
                    )
                    ticket_open = False
                    return view
                admission = self._admission.status(ticket)
            terminal_view = self._terminal_admission_view(
                ticket,
                request,
                evidence,
                principal,
                started,
                admission,
                provider_generation,
            )
            if terminal_view is not None:
                ticket_open = False
                return terminal_view
            if admission.outcome != "admitted":
                raise CuratorContainmentError(
                    "curator queued admission entered an unknown state"
                )
            if (
                admission.route != ExecutionRoute.COMPLEX_ORCHESTRATION
                or isinstance(admission.provider_generation, bool)
                or not isinstance(admission.provider_generation, int)
                or admission.provider_generation < 1
            ):
                raise CuratorContainmentError(
                    "curator admission lease identity is invalid"
                )
            provider_generation = admission.provider_generation
            if worker_cancellation.is_set():
                view = self._cancelled_view(
                    ticket,
                    request,
                    evidence,
                    principal,
                    started,
                    _cancellation_reason(cancellation, deadline),
                    provider_generation,
                )
                ticket_open = False
                return view

            decision: CuratorDecision | None = None
            failure_reason: str | None = None
            try:
                decision = self._reviewer.review(
                    request,
                    evidence,
                    cancellation=worker_cancellation,
                )
                if not isinstance(decision, CuratorDecision):
                    raise ValueError("curator model decision type is invalid")
            except KnowledgeToolCancelled:
                view = self._cancelled_view(
                    ticket,
                    request,
                    evidence,
                    principal,
                    started,
                    _cancellation_reason(cancellation, deadline),
                    provider_generation,
                )
                ticket_open = False
                return view
            except ReasoningRetryableError:
                failure_reason = "runtime-unavailable"
            except ValueError:
                failure_reason = "invalid-output"
            except RuntimeError as error:
                raise CuratorContainmentError(
                    "curator model transport was not contained"
                ) from error

            current = self._admission.status(ticket)
            terminal_view = self._terminal_admission_view(
                ticket,
                request,
                evidence,
                principal,
                started,
                current,
                provider_generation,
            )
            if terminal_view is not None:
                ticket_open = False
                return terminal_view
            if (
                current.outcome != "admitted"
                or current.route != ExecutionRoute.COMPLEX_ORCHESTRATION
                or current.provider_generation != provider_generation
            ):
                raise CuratorContainmentError(
                    "curator admission changed before completion"
                )
            if worker_cancellation.is_set():
                view = self._cancelled_view(
                    ticket,
                    request,
                    evidence,
                    principal,
                    started,
                    _cancellation_reason(cancellation, deadline),
                    provider_generation,
                )
                ticket_open = False
                return view
            completed = self._admission.complete(ticket)
            terminal_view = self._terminal_admission_view(
                ticket,
                request,
                evidence,
                principal,
                started,
                completed,
                provider_generation,
            )
            if terminal_view is not None:
                ticket_open = False
                return terminal_view
            if completed.outcome != "completed":
                raise CuratorContainmentError(
                    "curator admission lease did not complete"
                )
            ticket_open = False

            if worker_cancellation.is_set() or cancellation.is_set():
                return self._result(
                    ticket,
                    request,
                    principal=principal,
                    started=started,
                    status="cancelled",
                    reason=_cancellation_reason(cancellation, deadline),
                    evidence=evidence,
                    provider_generation=provider_generation,
                )

            if failure_reason is not None:
                return self._result(
                    ticket,
                    request,
                    principal=principal,
                    started=started,
                    status="failed",
                    reason=failure_reason,
                    evidence=evidence,
                    provider_generation=provider_generation,
                )
            if decision is None:
                raise CuratorContainmentError("curator returned no decision")
            if decision.decision == "reject":
                return self._result(
                    ticket,
                    request,
                    principal=principal,
                    started=started,
                    status="rejected",
                    reason="model-rejected",
                    evidence=evidence,
                    provider_generation=provider_generation,
                )

            try:
                if deadline <= time.monotonic():
                    return self._result(
                        ticket,
                        request,
                        principal=principal,
                        started=started,
                        status="failed",
                        reason="deadline-exceeded",
                        evidence=evidence,
                        provider_generation=provider_generation,
                    )
                proposal = self._publisher.publish(
                    principal=principal,
                    request_id=ticket.request_id,
                    request=request,
                    evidence=evidence,
                    provider_generation=provider_generation,
                    started=started,
                    deadline=deadline,
                    cancellation=worker_cancellation,
                )
            except BaseException as error:
                recovered = self._read_stored(request, principal)
                if recovered is not None:
                    return _stored_view(recovered)
                if isinstance(error, KnowledgeProposalCapacityExceeded):
                    view = self._result(
                        ticket,
                        request,
                        principal=principal,
                        started=started,
                        status="failed",
                        reason="capacity-unavailable",
                        evidence=evidence,
                        provider_generation=provider_generation,
                    )
                    return view
                if isinstance(error, KnowledgeToolCancelled):
                    return self._result(
                        ticket,
                        request,
                        principal=principal,
                        started=started,
                        status="cancelled",
                        reason=_cancellation_reason(cancellation, deadline),
                        evidence=evidence,
                        provider_generation=provider_generation,
                    )
                if isinstance(error, KnowledgeToolCancellationFailed):
                    raise CuratorContainmentError(
                        "curator publication cancellation was not contained"
                    ) from error
                if isinstance(error, ValueError):
                    return self._result(
                        ticket,
                        request,
                        principal=principal,
                        started=started,
                        status="failed",
                        reason="stale-or-invalid-generation",
                        evidence=evidence,
                        provider_generation=provider_generation,
                    )
                if isinstance(error, KnowledgeToolTimedOut):
                    return self._result(
                        ticket,
                        request,
                        principal=principal,
                        started=started,
                        status="failed",
                        reason="deadline-exceeded",
                        evidence=evidence,
                        provider_generation=provider_generation,
                    )
                if isinstance(error, (QueryCanceled, LockNotAvailable)):
                    return self._result(
                        ticket,
                        request,
                        principal=principal,
                        started=started,
                        status="failed",
                        reason="storage-timeout",
                        evidence=evidence,
                        provider_generation=provider_generation,
                    )
                if isinstance(error, (OSError, PostgresError)):
                    return self._result(
                        ticket,
                        request,
                        principal=principal,
                        started=started,
                        status="failed",
                        reason="storage-unavailable",
                        evidence=evidence,
                        provider_generation=provider_generation,
                    )
                raise
            return CuratorJobView(
                ticket.request_id,
                request.submission_id,
                "proposed",
                proposal.generation_sha256,
                evidence.evidence_sha256,
                proposal.proposal_id,
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

    def _read_stored(
        self,
        request: CuratorRequest,
        principal: AuthenticatedPrincipal,
    ) -> CuratorStoredResult | None:
        stored = self._result_auditor.read(
            principal=principal,
            submission_id=request.submission_id,
        )
        if stored is not None and stored.request_sha256 != curator_request_sha256(
            request
        ):
            raise CuratorServiceError(
                409,
                "CURATOR_SUBMISSION_CONFLICT",
                "The Curator submission identity already belongs to other content.",
                retryable=False,
            )
        return stored

    def _result(
        self,
        ticket: AgentAdmissionTicket,
        request: CuratorRequest,
        *,
        principal: AuthenticatedPrincipal,
        started: float,
        status: str,
        reason: str,
        evidence: CuratorEvidence | None = None,
        provider_generation: int | None = None,
    ) -> CuratorJobView:
        duration = max(0, round((time.monotonic() - started) * 1_000))
        try:
            self._result_auditor.record(
                principal=principal,
                request_id=ticket.request_id,
                request=request,
                provider_generation=provider_generation,
                status=status,
                reason=reason,
                evidence=evidence,
                proposal_id=None,
                duration_milliseconds=duration,
            )
        except ValueError:
            stored = self._read_stored(request, principal)
            if stored is None:
                raise
            return _stored_view(stored)
        return CuratorJobView(
            ticket.request_id,
            request.submission_id,
            status,
            (
                evidence.generation_sha256
                if evidence is not None
                else request.expected_generation_sha256
            ),
            evidence.evidence_sha256 if evidence is not None else None,
            reason=reason,
        )

    def _cancelled_view(
        self,
        ticket: AgentAdmissionTicket,
        request: CuratorRequest,
        evidence: CuratorEvidence,
        principal: AuthenticatedPrincipal,
        started: float,
        reason: str,
        provider_generation: int | None,
    ) -> CuratorJobView:
        cancelled = self._admission.cancel(ticket)
        expected = _expected_cancellation_outcome(cancelled)
        if expected is None:
            raise CuratorContainmentError("curator cancellation was not admitted")
        terminal = self._admission.acknowledge_cancellation(ticket)
        if terminal.outcome != expected:
            raise CuratorContainmentError(
                "curator cancellation was not acknowledged"
            )
        return self._result(
            ticket,
            request,
            principal=principal,
            started=started,
            status="cancelled",
            reason=reason,
            evidence=evidence,
            provider_generation=provider_generation,
        )

    def _acknowledge_requested_cancellation(
        self,
        ticket: AgentAdmissionTicket,
        request: CuratorRequest,
        evidence: CuratorEvidence,
        principal: AuthenticatedPrincipal,
        started: float,
        admission: AgentAdmission,
        provider_generation: int | None,
    ) -> CuratorJobView:
        expected = _expected_cancellation_outcome(admission)
        if expected is None:
            raise CuratorContainmentError(
                "curator cancellation response is invalid"
            )
        terminal = self._admission.acknowledge_cancellation(ticket)
        if terminal.outcome != expected:
            raise CuratorContainmentError(
                "curator cancellation was not acknowledged"
            )
        return self._result(
            ticket,
            request,
            principal=principal,
            started=started,
            status="cancelled",
            reason=_admission_reason(expected),
            evidence=evidence,
            provider_generation=provider_generation,
        )

    def _terminal_admission_view(
        self,
        ticket: AgentAdmissionTicket,
        request: CuratorRequest,
        evidence: CuratorEvidence,
        principal: AuthenticatedPrincipal,
        started: float,
        admission: AgentAdmission,
        provider_generation: int | None,
    ) -> CuratorJobView | None:
        if admission.outcome == "cancellation-requested":
            return self._acknowledge_requested_cancellation(
                ticket,
                request,
                evidence,
                principal,
                started,
                admission,
                provider_generation,
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
            status="cancelled",
            reason=_admission_reason(admission.outcome),
            evidence=evidence,
            provider_generation=provider_generation,
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
                    "not-found-or-unauthorized",
                }
        except BaseException:
            contained = False
        if not contained:
            raise CuratorContainmentError(
                "curator admission could not be contained"
            )


def _stored_view(stored: CuratorStoredResult) -> CuratorJobView:
    return CuratorJobView(
        stored.request_id,
        stored.submission_id,
        stored.status,
        stored.generation_sha256,
        stored.evidence_sha256,
        stored.proposal_id,
        stored.reason,
    )


def _forward_cancellation(
    source: threading.Event,
    target: threading.Event,
    stopped: threading.Event,
) -> None:
    while not stopped.wait(0.01):
        if source.is_set():
            target.set()
            return


def _remaining_deadline_ms(deadline: float) -> int:
    remaining = int(max(0.0, deadline - time.monotonic()) * 1_000)
    if remaining <= 0:
        raise CuratorServiceError(
            504,
            "CURATOR_DEADLINE",
            "Knowledge proposal could not start before its deadline.",
            retryable=True,
        )
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


__all__ = [
    "CuratorContainmentError",
    "CuratorJobView",
    "CuratorService",
    "CuratorServiceError",
]
