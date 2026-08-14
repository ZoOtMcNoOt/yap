
from __future__ import annotations

from dataclasses import dataclass
import re
import threading
import time
from typing import Protocol
from uuid import uuid4

from yap_server.auth import AuthenticatedPrincipal, PrincipalKey

from .auditor import AuditorReport, AuditorRequest
from .auditor_service import AuditorJobView


_MAXIMUM_INFLIGHT_REQUESTS = 64
_MAXIMUM_RETAINED_TERMINAL_REQUESTS = 256
_TERMINAL_RETENTION_SECONDS = 15 * 60.0
_CLOSE_TIMEOUT_SECONDS = 68.0
_REQUEST_ID = re.compile(r"^auditor-report-[0-9a-f]{32}$")
_ACTIVE_STATUSES = frozenset({"queued", "running", "cancellation-requested"})
_TERMINAL_STATUSES = frozenset(
    {"complete", "evidence-unavailable", "cancelled", "failed"}
)


class AuditorReportRunner(Protocol):
    def audit(
        self,
        request: AuditorRequest,
        *,
        principal: AuthenticatedPrincipal,
        cancellation: threading.Event,
    ) -> AuditorJobView: ...


class AuditorReportContainmentError(RuntimeError):
    pass


class AuditorReportServiceError(RuntimeError):
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


@dataclass(frozen=True, slots=True)
class AuditorReportJobView:
    request_id: str
    status: str
    report: AuditorReport | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.request_id, str)
            or _REQUEST_ID.fullmatch(self.request_id) is None
        ):
            raise ValueError("auditor product request identity is invalid")
        if self.status not in _ACTIVE_STATUSES | _TERMINAL_STATUSES:
            raise ValueError("auditor product status is invalid")
        if self.status == "complete":
            if (
                not isinstance(self.report, AuditorReport)
                or self.reason is not None
            ):
                raise ValueError("complete auditor product view is invalid")
        elif self.status in _ACTIVE_STATUSES:
            if self.report is not None or self.reason is not None:
                raise ValueError("active auditor product view is invalid")
        elif (
            self.report is not None
            or not isinstance(self.reason, str)
            or not self.reason
        ):
            raise ValueError("terminal auditor product view is invalid")

    def to_wire(self) -> dict[str, object]:
        value: dict[str, object] = {
            "schemaVersion": 1,
            "requestId": self.request_id,
            "status": self.status,
        }
        if self.report is not None:
            value["report"] = self.report.to_wire()
        if self.reason is not None:
            value["reason"] = self.reason
        return value


@dataclass(slots=True)
class _ReportJob:
    request_id: str
    owner: PrincipalKey
    principal: AuthenticatedPrincipal
    request: AuditorRequest
    cancellation: threading.Event
    status: str = "queued"
    report: AuditorReport | None = None
    reason: str | None = None
    terminal_at: float | None = None

    def view(self) -> AuditorReportJobView:
        return AuditorReportJobView(
            request_id=self.request_id,
            status=self.status,
            report=self.report,
            reason=self.reason,
        )


class AuditorReportService:
    """Own asynchronous, principal-scoped product access to Auditor."""

    def __init__(self, *, auditor: AuditorReportRunner) -> None:
        self._auditor = auditor
        self._lock = threading.RLock()
        self._jobs: dict[str, _ReportJob] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._closed = False
        self._fenced_reason: str | None = None

    def submit(
        self,
        request: AuditorRequest,
        *,
        principal: AuthenticatedPrincipal,
    ) -> AuditorReportJobView:
        if not isinstance(request, AuditorRequest):
            raise TypeError("auditor product request type is invalid")
        if not isinstance(principal, AuthenticatedPrincipal):
            raise TypeError("auditor product principal type is invalid")
        with self._lock:
            self._require_open_locked()
            self._prune_locked()
            if sum(job.terminal_at is None for job in self._jobs.values()) >= (
                _MAXIMUM_INFLIGHT_REQUESTS
            ):
                raise AuditorReportServiceError(
                    429,
                    "AUDITOR_REPORT_CAPACITY",
                    "Audit-report capacity is temporarily unavailable.",
                    retryable=True,
                )
            request_id = f"auditor-report-{uuid4().hex}"
            if request_id in self._jobs:
                raise AuditorReportContainmentError(
                    "auditor product request identity collided"
                )
            job = _ReportJob(
                request_id=request_id,
                owner=principal.key,
                principal=principal,
                request=request,
                cancellation=threading.Event(),
            )
            initial = job.view()
            thread = threading.Thread(
                target=self._run,
                args=(job,),
                name=request_id,
                daemon=False,
            )
            self._jobs[request_id] = job
            self._threads[request_id] = thread
            try:
                thread.start()
            except BaseException:
                self._jobs.pop(request_id, None)
                self._threads.pop(request_id, None)
                raise
            return initial

    def get(
        self,
        request_id: str,
        *,
        principal: AuthenticatedPrincipal,
    ) -> AuditorReportJobView | None:
        if not isinstance(principal, AuthenticatedPrincipal):
            raise TypeError("auditor product principal type is invalid")
        with self._lock:
            job = self._jobs.get(request_id)
            if job is None or job.owner != principal.key:
                return None
            return job.view()

    def cancel(
        self,
        request_id: str,
        *,
        principal: AuthenticatedPrincipal,
    ) -> bool:
        if not isinstance(principal, AuthenticatedPrincipal):
            raise TypeError("auditor product principal type is invalid")
        with self._lock:
            job = self._jobs.get(request_id)
            if (
                job is None
                or job.owner != principal.key
                or job.status not in _ACTIVE_STATUSES
            ):
                return False
            job.cancellation.set()
            job.status = "cancellation-requested"
            return True

    def close(self) -> None:
        deadline = time.monotonic() + _CLOSE_TIMEOUT_SECONDS
        with self._lock:
            self._closed = True
            for job in self._jobs.values():
                if job.terminal_at is None:
                    job.cancellation.set()
                    job.status = "cancellation-requested"
            threads = tuple(self._threads.values())
        for thread in threads:
            thread.join(timeout=max(0.0, deadline - time.monotonic()))
        with self._lock:
            if any(thread.is_alive() for thread in threads):
                self._fenced_reason = "auditor product workers did not stop"
            if self._fenced_reason is not None:
                raise AuditorReportContainmentError(self._fenced_reason)

    def _run(self, job: _ReportJob) -> None:
        with self._lock:
            if job.status == "queued":
                job.status = "running"
        try:
            result = self._auditor.audit(
                job.request,
                principal=job.principal,
                cancellation=job.cancellation,
            )
            if not isinstance(result, AuditorJobView):
                raise AuditorReportContainmentError(
                    "auditor product result type is invalid"
                )
            if (
                not isinstance(result.request_id, str)
                or not result.request_id
                or result.status not in _TERMINAL_STATUSES
            ):
                raise AuditorReportContainmentError(
                    "auditor product result identity is invalid"
                )
            projected = AuditorReportJobView(
                request_id=job.request_id,
                status=result.status,
                report=result.report,
                reason=result.reason,
            )
            with self._lock:
                job.status = projected.status
                job.report = projected.report
                job.reason = projected.reason
                job.terminal_at = time.monotonic()
        except BaseException:
            with self._lock:
                job.status = "failed"
                job.report = None
                job.reason = "service-unavailable"
                job.terminal_at = time.monotonic()
                self._fenced_reason = "auditor product worker containment failed"
        finally:
            with self._lock:
                self._threads.pop(job.request_id, None)

    def _require_open_locked(self) -> None:
        if self._closed:
            raise AuditorReportContainmentError(
                "auditor product service is closed"
            )
        if self._fenced_reason is not None:
            raise AuditorReportContainmentError(self._fenced_reason)

    def _prune_locked(self) -> None:
        cutoff = time.monotonic() - _TERMINAL_RETENTION_SECONDS
        terminal = sorted(
            (
                (job.terminal_at, request_id)
                for request_id, job in self._jobs.items()
                if job.terminal_at is not None
            ),
            key=lambda item: (item[0], item[1]),
        )
        expired = {
            request_id
            for terminal_at, request_id in terminal
            if terminal_at is not None and terminal_at < cutoff
        }
        retained = [
            request_id for _, request_id in terminal if request_id not in expired
        ]
        excess = max(0, len(retained) - _MAXIMUM_RETAINED_TERMINAL_REQUESTS)
        expired.update(retained[:excess])
        for request_id in expired:
            self._jobs.pop(request_id, None)


__all__ = [
    "AuditorReportContainmentError",
    "AuditorReportJobView",
    "AuditorReportRunner",
    "AuditorReportService",
    "AuditorReportServiceError",
]
