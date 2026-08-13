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
from yap_server.knowledge.knowledge_tool_contract import (
    KnowledgeToolCancellationFailed,
    KnowledgeToolCancelled,
    KnowledgeToolTimedOut,
)

from .librarian import (
    LibrarianEvidenceItem,
    LibrarianEvidencePack,
    LibrarianRequest,
    librarian_request_sha256,
    librarian_work_sha256,
    validate_librarian_evidence,
)


LIBRARIAN_WORKFLOW_DEADLINE_SECONDS = 15.0

_LIBRARIAN_WORK = AgentWorkSpec(
    role=AgentRole.LIBRARIAN,
    purpose=AgentPurpose.KNOWLEDGE_READ,
    route=ExecutionRoute.SERVER_IO,
    scheduling_class=SchedulingClass.INTERACTIVE,
)
_ADMISSION_POLL_SECONDS = 0.05


class LibrarianAdmission(Protocol):
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


class LibrarianEvidenceReader(Protocol):
    def read(
        self,
        request: LibrarianRequest,
        *,
        principal: AuthenticatedPrincipal,
        cancellation: threading.Event,
    ) -> LibrarianEvidencePack: ...


class LibrarianResultAuditor(Protocol):
    def record(
        self,
        *,
        principal: AuthenticatedPrincipal,
        request_id: str,
        request_sha256: str,
        work_sha256: str | None,
        evidence_sha256: str | None,
        generation_sha256: str | None,
        permission_hash: str | None,
        authorization_hash: str | None,
        outcome: str,
        reason: str | None,
        result_count: int,
        duration_milliseconds: int,
    ) -> None: ...


class LibrarianContainmentError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class LibrarianJobView:
    request_id: str
    status: str
    evidence: LibrarianEvidencePack | None = None
    reason: str | None = None

    @property
    def generation_sha256(self) -> str | None:
        return self.evidence.generation_sha256 if self.evidence is not None else None

    @property
    def permission_hash(self) -> str | None:
        return self.evidence.permission_hash if self.evidence is not None else None

    @property
    def authorization_hash(self) -> str | None:
        return self.evidence.authorization_hash if self.evidence is not None else None

    @property
    def evidence_sha256(self) -> str | None:
        return self.evidence.evidence_sha256 if self.evidence is not None else None

    @property
    def items(self) -> tuple[LibrarianEvidenceItem, ...]:
        return self.evidence.items if self.evidence is not None else ()

    @property
    def output_budget_exhausted(self) -> bool:
        return (
            self.evidence.output_budget_exhausted
            if self.evidence is not None
            else False
        )

    def to_wire(self) -> dict[str, object]:
        value: dict[str, object] = {
            "schemaVersion": 1,
            "requestId": self.request_id,
            "status": self.status,
        }
        if self.evidence is not None:
            value["evidencePack"] = self.evidence.to_wire()
        if self.reason is not None:
            value["reason"] = self.reason
        return value


class LibrarianService:
    """Run one bounded permission-safe read under a Server-IO lease."""

    def __init__(
        self,
        *,
        admission: LibrarianAdmission,
        evidence_reader: LibrarianEvidenceReader,
        result_auditor: LibrarianResultAuditor,
    ) -> None:
        self._admission = admission
        self._evidence_reader = evidence_reader
        self._result_auditor = result_auditor

    def query(
        self,
        request: LibrarianRequest,
        *,
        principal: AuthenticatedPrincipal,
        cancellation: threading.Event,
    ) -> LibrarianJobView:
        if not isinstance(request, LibrarianRequest):
            raise TypeError("librarian request type is invalid")
        if not isinstance(principal, AuthenticatedPrincipal):
            raise TypeError("librarian principal type is invalid")
        if not isinstance(cancellation, threading.Event):
            raise TypeError("librarian cancellation type is invalid")

        started = time.monotonic()
        deadline = started + LIBRARIAN_WORKFLOW_DEADLINE_SECONDS
        ticket = self._admission.new_ticket()
        if cancellation.is_set():
            return self._result(
                ticket,
                request,
                principal=principal,
                started=started,
                status="cancelled",
                outcome="cancelled",
                reason="client-cancelled",
            )

        worker_cancellation = threading.Event()
        forwarding_stopped = threading.Event()
        forwarder = threading.Thread(
            target=_forward_cancellation,
            args=(cancellation, worker_cancellation, forwarding_stopped),
            name=f"librarian-cancellation-{ticket.request_id}",
            daemon=False,
        )
        deadline_timer = threading.Timer(
            max(0.0, deadline - time.monotonic()),
            worker_cancellation.set,
        )
        deadline_timer.name = f"librarian-deadline-{ticket.request_id}"
        deadline_timer.daemon = False
        forwarder.start()
        deadline_timer.start()
        ticket_open = False
        evidence: LibrarianEvidencePack | None = None
        try:
            remaining_deadline_ms = _remaining_deadline_ms(deadline)
            if remaining_deadline_ms is None:
                return self._result(
                    ticket,
                    request,
                    principal=principal,
                    started=started,
                    status="cancelled",
                    outcome="cancelled",
                    reason="deadline-exceeded",
                )
            try:
                admission = self._admission.submit(
                    ticket,
                    principal=principal,
                    work=_LIBRARIAN_WORK,
                    source_sha256=librarian_request_sha256(request),
                    remaining_deadline_ms=remaining_deadline_ms,
                )
                ticket_open = admission.outcome in {"queued", "admitted"}
            except Exception:
                self._contain_ticket(ticket)
                return self._result(
                    ticket,
                    request,
                    principal=principal,
                    started=started,
                    status="failed",
                    outcome="failed",
                    reason="admission-failed",
                )

            if admission.outcome not in {"queued", "admitted"}:
                return self._result(
                    ticket,
                    request,
                    principal=principal,
                    started=started,
                    status="failed",
                    outcome="failed",
                    reason=_admission_reason(admission.outcome),
                )

            while admission.outcome == "queued":
                if worker_cancellation.wait(_ADMISSION_POLL_SECONDS):
                    view = self._cancelled_view(
                        ticket,
                        request,
                        principal,
                        started,
                        _cancellation_reason(cancellation, deadline),
                        evidence,
                    )
                    ticket_open = False
                    return view
                admission = self._admission.status(ticket)

            terminal = self._terminal_admission_view(
                ticket,
                request,
                principal,
                started,
                admission,
                evidence,
            )
            if terminal is not None:
                ticket_open = False
                return terminal
            if admission.outcome != "admitted":
                raise LibrarianContainmentError(
                    "librarian queued admission entered an unknown state"
                )
            if (
                admission.route != ExecutionRoute.SERVER_IO
                or admission.provider_generation is not None
            ):
                raise LibrarianContainmentError(
                    "librarian admission lease identity is invalid"
                )
            if worker_cancellation.is_set():
                view = self._cancelled_view(
                    ticket,
                    request,
                    principal,
                    started,
                    _cancellation_reason(cancellation, deadline),
                    evidence,
                )
                ticket_open = False
                return view

            failure: tuple[str, str, str] | None = None
            try:
                evidence = self._evidence_reader.read(
                    request,
                    principal=principal,
                    cancellation=worker_cancellation,
                )
            except KnowledgeToolCancelled:
                view = self._cancelled_view(
                    ticket,
                    request,
                    principal,
                    started,
                    _cancellation_reason(cancellation, deadline),
                    evidence,
                )
                ticket_open = False
                return view
            except KnowledgeToolCancellationFailed as error:
                raise LibrarianContainmentError(
                    "librarian database cancellation was not contained"
                ) from error
            except (KnowledgeToolTimedOut, QueryCanceled, LockNotAvailable):
                failure = ("failed", "failed", "storage-timeout")
            except PermissionError:
                failure = ("failed", "unauthorized", "unauthorized")
            except LookupError:
                failure = (
                    "evidence-unavailable",
                    "unavailable",
                    "evidence-unavailable",
                )
            except ValueError:
                failure = ("failed", "unavailable", "stale-generation")
            except (OSError, PostgresError):
                failure = ("failed", "failed", "storage-unavailable")

            if evidence is not None:
                try:
                    validate_librarian_evidence(request, evidence)
                except ValueError as error:
                    raise LibrarianContainmentError(
                        "librarian evidence validation was not contained"
                    ) from error

            current = self._admission.status(ticket)
            terminal = self._terminal_admission_view(
                ticket,
                request,
                principal,
                started,
                current,
                evidence,
            )
            if terminal is not None:
                ticket_open = False
                return terminal
            if (
                current.outcome != "admitted"
                or current.route != ExecutionRoute.SERVER_IO
                or current.provider_generation is not None
            ):
                raise LibrarianContainmentError(
                    "librarian admission changed before completion"
                )
            if worker_cancellation.is_set():
                view = self._cancelled_view(
                    ticket,
                    request,
                    principal,
                    started,
                    _cancellation_reason(cancellation, deadline),
                    evidence,
                )
                ticket_open = False
                return view

            completed = self._admission.complete(ticket)
            terminal = self._terminal_admission_view(
                ticket,
                request,
                principal,
                started,
                completed,
                evidence,
            )
            if terminal is not None:
                ticket_open = False
                return terminal
            if completed.outcome != "completed":
                raise LibrarianContainmentError(
                    "librarian admission lease did not complete"
                )
            ticket_open = False

            if worker_cancellation.is_set() or cancellation.is_set():
                return self._result(
                    ticket,
                    request,
                    principal=principal,
                    started=started,
                    status="cancelled",
                    outcome="cancelled",
                    reason=_cancellation_reason(cancellation, deadline),
                    audit_evidence=evidence,
                )
            if failure is not None:
                status, outcome, reason = failure
                return self._result(
                    ticket,
                    request,
                    principal=principal,
                    started=started,
                    status=status,
                    outcome=outcome,
                    reason=reason,
                    audit_evidence=evidence,
                )
            if evidence is None:
                raise LibrarianContainmentError(
                    "librarian evidence reader returned no outcome"
                )
            if not evidence.items:
                return self._result(
                    ticket,
                    request,
                    principal=principal,
                    started=started,
                    status="evidence-unavailable",
                    outcome="unavailable",
                    reason="empty-result",
                    audit_evidence=evidence,
                )
            return self._result(
                ticket,
                request,
                principal=principal,
                started=started,
                status="complete",
                outcome="succeeded",
                reason=None,
                audit_evidence=evidence,
                response_evidence=evidence,
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

    def _result(
        self,
        ticket: AgentAdmissionTicket,
        request: LibrarianRequest,
        *,
        principal: AuthenticatedPrincipal,
        started: float,
        status: str,
        outcome: str,
        reason: str | None,
        audit_evidence: LibrarianEvidencePack | None = None,
        response_evidence: LibrarianEvidencePack | None = None,
    ) -> LibrarianJobView:
        work_sha256 = (
            librarian_work_sha256(request, audit_evidence)
            if audit_evidence is not None
            else None
        )
        self._result_auditor.record(
            principal=principal,
            request_id=ticket.request_id,
            request_sha256=librarian_request_sha256(request),
            work_sha256=work_sha256,
            evidence_sha256=(
                audit_evidence.evidence_sha256
                if audit_evidence is not None
                else None
            ),
            generation_sha256=(
                audit_evidence.generation_sha256
                if audit_evidence is not None
                else request.expected_generation_sha256
            ),
            permission_hash=(
                audit_evidence.permission_hash
                if audit_evidence is not None
                else None
            ),
            authorization_hash=(
                audit_evidence.authorization_hash
                if audit_evidence is not None
                else None
            ),
            outcome=outcome,
            reason=reason,
            result_count=(len(response_evidence.items) if response_evidence else 0),
            duration_milliseconds=max(
                0,
                round((time.monotonic() - started) * 1_000),
            ),
        )
        return LibrarianJobView(
            request_id=ticket.request_id,
            status=status,
            evidence=response_evidence,
            reason=reason,
        )

    def _cancelled_view(
        self,
        ticket: AgentAdmissionTicket,
        request: LibrarianRequest,
        principal: AuthenticatedPrincipal,
        started: float,
        reason: str,
        evidence: LibrarianEvidencePack | None,
    ) -> LibrarianJobView:
        cancelled = self._admission.cancel(ticket)
        expected = _expected_cancellation_outcome(cancelled)
        if expected is None:
            raise LibrarianContainmentError(
                "librarian cancellation was not admitted"
            )
        terminal = self._admission.acknowledge_cancellation(ticket)
        if terminal.outcome != expected:
            raise LibrarianContainmentError(
                "librarian cancellation was not acknowledged"
            )
        return self._result(
            ticket,
            request,
            principal=principal,
            started=started,
            status="cancelled",
            outcome="cancelled",
            reason=reason,
            audit_evidence=evidence,
        )

    def _terminal_admission_view(
        self,
        ticket: AgentAdmissionTicket,
        request: LibrarianRequest,
        principal: AuthenticatedPrincipal,
        started: float,
        admission: AgentAdmission,
        evidence: LibrarianEvidencePack | None,
    ) -> LibrarianJobView | None:
        if admission.outcome == "cancellation-requested":
            expected = _expected_cancellation_outcome(admission)
            if expected is None:
                raise LibrarianContainmentError(
                    "librarian cancellation response is invalid"
                )
            terminal = self._admission.acknowledge_cancellation(ticket)
            if terminal.outcome != expected:
                raise LibrarianContainmentError(
                    "librarian cancellation was not acknowledged"
                )
            reason = _terminal_reason(expected)
            return self._result(
                ticket,
                request,
                principal=principal,
                started=started,
                status=("cancelled" if expected != "provider-unavailable" else "failed"),
                outcome=("cancelled" if expected != "provider-unavailable" else "failed"),
                reason=reason,
                audit_evidence=evidence,
            )
        if admission.outcome not in {
            "cancelled",
            "deadline-exceeded",
            "provider-unavailable",
        }:
            return None
        reason = _terminal_reason(admission.outcome)
        return self._result(
            ticket,
            request,
            principal=principal,
            started=started,
            status=(
                "cancelled"
                if admission.outcome in {"cancelled", "deadline-exceeded"}
                else "failed"
            ),
            outcome=(
                "cancelled"
                if admission.outcome in {"cancelled", "deadline-exceeded"}
                else "failed"
            ),
            reason=reason,
            audit_evidence=evidence,
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
            raise LibrarianContainmentError(
                "librarian admission could not be contained"
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


def _remaining_deadline_ms(deadline: float) -> int | None:
    remaining = int(max(0.0, deadline - time.monotonic()) * 1_000)
    return remaining if remaining > 0 else None


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
    if outcome in {"owner-queue-full", "queue-full"}:
        return "capacity-unavailable"
    return "admission-failed"


def _terminal_reason(outcome: str) -> str:
    return {
        "cancelled": "client-cancelled",
        "deadline-exceeded": "deadline-exceeded",
        "provider-unavailable": "admission-failed",
    }[outcome]


def _cancellation_reason(cancellation: threading.Event, deadline: float) -> str:
    if cancellation.is_set():
        return "client-cancelled"
    if time.monotonic() >= deadline:
        return "deadline-exceeded"
    return "client-cancelled"


__all__ = [
    "LIBRARIAN_WORKFLOW_DEADLINE_SECONDS",
    "LibrarianContainmentError",
    "LibrarianJobView",
    "LibrarianService",
]
