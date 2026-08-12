from __future__ import annotations

import threading
import time
from typing import Protocol

from psycopg import Error as PostgresError

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
)

from .archivist import (
    ArchivistContainmentError,
    ArchivistIngestion,
    ArchivistJobView,
    ArchivistRequest,
)


_ARCHIVIST_WORK = AgentWorkSpec(
    role=AgentRole.ARCHIVIST,
    purpose=AgentPurpose.KNOWLEDGE_INGEST,
    route=ExecutionRoute.SERVER_IO,
    scheduling_class=SchedulingClass.BACKGROUND_IO,
)
_INGESTION_DEADLINE_SECONDS = 60.0
_ADMISSION_POLL_SECONDS = 0.05


class ArchivistAdmission(Protocol):
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


class ArchivistProcessor(Protocol):
    def ingest(
        self,
        request: ArchivistRequest,
        *,
        principal: AuthenticatedPrincipal,
        cancellation: threading.Event,
    ) -> ArchivistIngestion: ...


class ArchivistServiceError(RuntimeError):
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


class ArchivistService:
    """Run one owner-bound background ingestion under an acknowledged lease."""

    def __init__(
        self,
        *,
        admission: ArchivistAdmission,
        processor: ArchivistProcessor,
    ) -> None:
        self._admission = admission
        self._processor = processor

    def ingest(
        self,
        request: ArchivistRequest,
        *,
        principal: AuthenticatedPrincipal,
        cancellation: threading.Event,
    ) -> ArchivistJobView:
        if not isinstance(request, ArchivistRequest):
            raise TypeError("archivist request type is invalid")
        if not isinstance(principal, AuthenticatedPrincipal):
            raise TypeError("archivist principal type is invalid")
        if not isinstance(cancellation, threading.Event):
            raise TypeError("archivist cancellation type is invalid")

        deadline = time.monotonic() + _INGESTION_DEADLINE_SECONDS
        ticket = self._admission.new_ticket()
        remaining_ms = _remaining_deadline_ms(deadline)
        try:
            initial = self._admission.submit(
                ticket,
                principal=principal,
                work=_ARCHIVIST_WORK,
                source_sha256=request.capture_sha256,
                remaining_deadline_ms=remaining_ms,
            )
        except BaseException:
            self._contain_ticket(ticket)
            raise
        if initial.outcome not in {"queued", "admitted"}:
            raise _submit_error(initial.outcome)

        worker_cancellation = threading.Event()
        forwarding_stopped = threading.Event()
        forwarder = threading.Thread(
            target=_forward_cancellation,
            args=(cancellation, worker_cancellation, forwarding_stopped),
            name=f"archivist-cancellation-{ticket.request_id}",
            daemon=False,
        )
        deadline_timer = threading.Timer(
            max(0.0, deadline - time.monotonic()),
            worker_cancellation.set,
        )
        deadline_timer.name = f"archivist-deadline-{ticket.request_id}"
        deadline_timer.daemon = False
        forwarder.start()
        deadline_timer.start()
        lease_active = False
        try:
            admission = initial
            while admission.outcome == "queued":
                if worker_cancellation.wait(_ADMISSION_POLL_SECONDS):
                    return self._cancelled_view(
                        ticket,
                        request,
                        _cancellation_reason(cancellation, deadline),
                    )
                admission = self._admission.status(ticket)
            if admission.outcome == "cancellation-requested":
                return self._acknowledge_requested_cancellation(
                    ticket,
                    request,
                    admission,
                )
            if admission.outcome != "admitted":
                return ArchivistJobView(
                    request_id=ticket.request_id,
                    status="failed",
                    capture_sha256=request.capture_sha256,
                    reason=_admission_reason(admission.outcome),
                )
            lease_active = True
            if (
                admission.route != ExecutionRoute.SERVER_IO
                or admission.provider_generation is not None
            ):
                raise ArchivistContainmentError(
                    "archivist admission lease identity is invalid"
                )
            if _cancellation_due(cancellation, deadline):
                worker_cancellation.set()
            if worker_cancellation.is_set():
                lease_active = False
                return self._cancelled_view(
                    ticket,
                    request,
                    _cancellation_reason(cancellation, deadline),
                )

            ingestion: ArchivistIngestion | None = None
            failure_reason: str | None = None
            try:
                ingestion = self._processor.ingest(
                    request,
                    principal=principal,
                    cancellation=worker_cancellation,
                )
            except KnowledgeToolCancelled:
                lease_active = False
                return self._cancelled_view(
                    ticket,
                    request,
                    _cancellation_reason(cancellation, deadline),
                )
            except KnowledgeToolCancellationFailed as error:
                raise ArchivistContainmentError(
                    "archivist database cancellation was not contained"
                ) from error
            except (LookupError, PermissionError, ValueError):
                failure_reason = "invalid-reviewed-source"
            except (OSError, PostgresError):
                failure_reason = "storage-unavailable"

            current = self._admission.status(ticket)
            if current.outcome == "cancellation-requested":
                lease_active = False
                return self._acknowledge_requested_cancellation(
                    ticket,
                    request,
                    current,
                )
            if (
                current.outcome != "admitted"
                or current.route != ExecutionRoute.SERVER_IO
                or current.provider_generation is not None
            ):
                raise ArchivistContainmentError(
                    "archivist admission changed before completion"
                )
            if _cancellation_due(cancellation, deadline):
                worker_cancellation.set()
            if worker_cancellation.is_set():
                lease_active = False
                return self._cancelled_view(
                    ticket,
                    request,
                    _cancellation_reason(cancellation, deadline),
                )

            completed = self._admission.complete(ticket)
            lease_active = False
            if completed.outcome != "completed":
                raise ArchivistContainmentError(
                    "archivist admission lease did not complete"
                )
            if failure_reason is not None:
                return ArchivistJobView(
                    request_id=ticket.request_id,
                    status="failed",
                    capture_sha256=request.capture_sha256,
                    reason=failure_reason,
                )
            if ingestion is None:
                raise ArchivistContainmentError(
                    "archivist processor did not return one outcome"
                )
            return ArchivistJobView(
                request_id=ticket.request_id,
                status="staged",
                capture_sha256=ingestion.capture_sha256,
                source_admission_sha256=ingestion.source_admission_sha256,
                generation_sha256=ingestion.generation.generation_sha256,
                concept_count=ingestion.generation.concept_count,
                permission_count=ingestion.generation.permission_count,
            )
        except BaseException:
            if lease_active:
                self._contain_ticket(ticket)
            raise
        finally:
            forwarding_stopped.set()
            forwarder.join()
            deadline_timer.cancel()
            deadline_timer.join()

    def _cancelled_view(
        self,
        ticket: AgentAdmissionTicket,
        request: ArchivistRequest,
        reason: str,
    ) -> ArchivistJobView:
        cancelled = self._admission.cancel(ticket)
        expected = _expected_cancellation_outcome(cancelled)
        if expected is None:
            raise ArchivistContainmentError(
                "archivist cancellation was not admitted"
            )
        terminal = self._admission.acknowledge_cancellation(ticket)
        if terminal.outcome != expected:
            raise ArchivistContainmentError(
                "archivist cancellation was not acknowledged"
            )
        return ArchivistJobView(
            request_id=ticket.request_id,
            status="cancelled",
            capture_sha256=request.capture_sha256,
            reason=reason,
        )

    def _acknowledge_requested_cancellation(
        self,
        ticket: AgentAdmissionTicket,
        request: ArchivistRequest,
        admission: AgentAdmission,
    ) -> ArchivistJobView:
        expected = _expected_cancellation_outcome(admission)
        if expected is None:
            raise ArchivistContainmentError(
                "archivist cancellation response is invalid"
            )
        terminal = self._admission.acknowledge_cancellation(ticket)
        if terminal.outcome != expected:
            raise ArchivistContainmentError(
                "archivist cancellation was not acknowledged"
            )
        return ArchivistJobView(
            request_id=ticket.request_id,
            status="cancelled",
            capture_sha256=request.capture_sha256,
            reason=_admission_reason(expected),
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
                    "not-found-or-unauthorized",
                }
        except BaseException:
            contained = False
        if not contained:
            raise ArchivistContainmentError(
                "archivist admission could not be contained"
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
        raise ArchivistServiceError(
            504,
            "ARCHIVIST_DEADLINE",
            "Knowledge ingestion could not start before its deadline.",
            retryable=True,
        )
    return remaining


def _submit_error(outcome: str) -> ArchivistServiceError:
    if outcome in {"owner-queue-full", "queue-full"}:
        return ArchivistServiceError(
            429,
            "ARCHIVIST_CAPACITY",
            "Knowledge ingestion capacity is temporarily unavailable.",
            retryable=True,
        )
    return ArchivistServiceError(
        503,
        "ARCHIVIST_UNAVAILABLE",
        "Knowledge ingestion admission is temporarily unavailable.",
        retryable=True,
    )


def _expected_cancellation_outcome(admission: AgentAdmission) -> str | None:
    if admission.outcome in {"cancelled", "deadline-exceeded", "provider-unavailable"}:
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
    }.get(outcome, "admission-failed")


def _cancellation_reason(cancellation: threading.Event, deadline: float) -> str:
    if cancellation.is_set():
        return "client-cancelled"
    if time.monotonic() >= deadline:
        return "deadline-exceeded"
    return "cancelled"


def _cancellation_due(cancellation: threading.Event, deadline: float) -> bool:
    return cancellation.is_set() or time.monotonic() >= deadline


__all__ = [
    "ArchivistService",
    "ArchivistServiceError",
]
