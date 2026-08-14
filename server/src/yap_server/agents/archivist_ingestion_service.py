from __future__ import annotations

from dataclasses import dataclass
import re
import threading
import time
from typing import Protocol
from uuid import uuid4

from yap_server.auth import AuthenticatedPrincipal, PrincipalKey
from yap_server.jobs.contract_values import identifier, valid_sha256

from .archivist import ArchivistJobView


_MAXIMUM_INFLIGHT_INGESTIONS = 64
_MAXIMUM_RETAINED_TERMINAL_INGESTIONS = 256
_TERMINAL_RETENTION_SECONDS = 15 * 60.0
_CLOSE_TIMEOUT_SECONDS = 65.0
_ACTIVE_STATUSES = frozenset({"queued", "running", "cancellation-requested"})
_TERMINAL_STATUSES = frozenset({"staged", "cancelled", "failed"})
_TERMINAL_REASONS = {
    "cancelled": frozenset({"client-cancelled", "deadline-exceeded"}),
    "failed": frozenset(
        {
            "invalid-reviewed-source",
            "source-changed",
            "storage-unavailable",
            "service-unavailable",
        }
    ),
}
_PRODUCT_REQUEST_ID = re.compile(r"^archivist-ingestion-[0-9a-f]{32}$")


@dataclass(frozen=True, slots=True)
class ArchivistIngestionRequest:
    job_id: str
    expected_result_sha256: str

    def __post_init__(self) -> None:
        identifier(self.job_id, 128, "archivist product job ID")
        if not valid_sha256(self.expected_result_sha256):
            raise ValueError("archivist product result identity is invalid")

    @classmethod
    def from_wire(cls, value: object) -> ArchivistIngestionRequest:
        if not isinstance(value, dict) or set(value) != {
            "schemaVersion",
            "jobId",
            "expectedResultSha256",
        }:
            raise ValueError("archivist product request fields differ")
        if isinstance(value["schemaVersion"], bool) or value["schemaVersion"] != 1:
            raise ValueError("archivist product request schema is unsupported")
        return cls(
            job_id=value["jobId"],
            expected_result_sha256=value["expectedResultSha256"],
        )

    def to_wire(self) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "jobId": self.job_id,
            "expectedResultSha256": self.expected_result_sha256,
        }


@dataclass(frozen=True, slots=True)
class ArchivistIngestionJobView:
    request_id: str
    status: str
    job_id: str
    result_sha256: str
    capture_sha256: str | None = None
    source_admission_sha256: str | None = None
    generation_sha256: str | None = None
    concept_count: int | None = None
    permission_count: int | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if _PRODUCT_REQUEST_ID.fullmatch(self.request_id) is None:
            raise ValueError("archivist product request identity is invalid")
        identifier(self.job_id, 128, "archivist product job ID")
        if not valid_sha256(self.result_sha256):
            raise ValueError("archivist product result identity is invalid")
        outputs = (
            self.capture_sha256,
            self.source_admission_sha256,
            self.generation_sha256,
            self.concept_count,
            self.permission_count,
        )
        if self.status in _ACTIVE_STATUSES:
            if any(value is not None for value in outputs) or self.reason is not None:
                raise ValueError("active archivist product view is invalid")
            return
        if self.status == "staged":
            if (
                not all(valid_sha256(value) for value in outputs[:3])
                or any(
                    not isinstance(value, int) or isinstance(value, bool) or value < 1
                    for value in outputs[3:]
                )
                or self.reason is not None
            ):
                raise ValueError("staged archivist product view is invalid")
            return
        if self.status not in _TERMINAL_STATUSES:
            raise ValueError("archivist product status is invalid")
        if any(value is not None for value in outputs):
            raise ValueError("terminal archivist product output is invalid")
        if self.reason not in _TERMINAL_REASONS[self.status]:
            raise ValueError("archivist product terminal reason is invalid")

    def to_wire(self) -> dict[str, object]:
        value: dict[str, object] = {
            "schemaVersion": 1,
            "requestId": self.request_id,
            "status": self.status,
            "jobId": self.job_id,
            "resultSha256": self.result_sha256,
        }
        for key, item in (
            ("captureSha256", self.capture_sha256),
            ("sourceAdmissionSha256", self.source_admission_sha256),
            ("generationSha256", self.generation_sha256),
            ("conceptCount", self.concept_count),
            ("permissionCount", self.permission_count),
            ("reason", self.reason),
        ):
            if item is not None:
                value[key] = item
        return value


class ArchivistIngestionRunner(Protocol):
    def validate_source(
        self,
        request: ArchivistIngestionRequest,
        *,
        principal: AuthenticatedPrincipal,
    ) -> None: ...

    def stage(
        self,
        request: ArchivistIngestionRequest,
        *,
        principal: AuthenticatedPrincipal,
        cancellation: threading.Event,
    ) -> ArchivistJobView: ...


class ArchivistIngestionContainmentError(RuntimeError):
    pass


class ArchivistIngestionServiceError(RuntimeError):
    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        *,
        retryable: bool,
        reason: str,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.retryable = retryable
        self.reason = reason


@dataclass(slots=True)
class _IngestionJob:
    request_id: str
    owner: PrincipalKey
    principal: AuthenticatedPrincipal
    request: ArchivistIngestionRequest
    cancellation: threading.Event
    status: str = "queued"
    capture_sha256: str | None = None
    source_admission_sha256: str | None = None
    generation_sha256: str | None = None
    concept_count: int | None = None
    permission_count: int | None = None
    reason: str | None = None
    terminal_at: float | None = None

    def view(self) -> ArchivistIngestionJobView:
        return ArchivistIngestionJobView(
            request_id=self.request_id,
            status=self.status,
            job_id=self.request.job_id,
            result_sha256=self.request.expected_result_sha256,
            capture_sha256=self.capture_sha256,
            source_admission_sha256=self.source_admission_sha256,
            generation_sha256=self.generation_sha256,
            concept_count=self.concept_count,
            permission_count=self.permission_count,
            reason=self.reason,
        )


class ArchivistIngestionService:
    """Own asynchronous, authenticated review-and-stage product requests."""

    def __init__(self, *, runner: ArchivistIngestionRunner) -> None:
        self._runner = runner
        self._lock = threading.RLock()
        self._jobs: dict[str, _IngestionJob] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._closed = False
        self._fenced_reason: str | None = None

    def submit(
        self,
        request: ArchivistIngestionRequest,
        *,
        principal: AuthenticatedPrincipal,
    ) -> ArchivistIngestionJobView:
        if not isinstance(request, ArchivistIngestionRequest):
            raise TypeError("archivist product request type is invalid")
        if not isinstance(principal, AuthenticatedPrincipal):
            raise TypeError("archivist product principal type is invalid")
        self._runner.validate_source(request, principal=principal)
        with self._lock:
            self._require_open_locked()
            self._prune_locked()
            if sum(job.terminal_at is None for job in self._jobs.values()) >= (
                _MAXIMUM_INFLIGHT_INGESTIONS
            ):
                raise ArchivistIngestionServiceError(
                    429,
                    "ARCHIVIST_INGESTION_CAPACITY",
                    "Knowledge staging capacity is temporarily unavailable.",
                    retryable=True,
                    reason="storage-unavailable",
                )
            request_id = f"archivist-ingestion-{uuid4().hex}"
            if request_id in self._jobs:
                raise ArchivistIngestionContainmentError(
                    "archivist product request identity collided"
                )
            job = _IngestionJob(
                request_id=request_id,
                owner=principal.key,
                principal=principal,
                request=request,
                cancellation=threading.Event(),
            )
            thread = threading.Thread(
                target=self._run,
                args=(job,),
                name=request_id,
                daemon=False,
            )
            self._jobs[request_id] = job
            self._threads[request_id] = thread
            initial = job.view()
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
    ) -> ArchivistIngestionJobView | None:
        if not isinstance(principal, AuthenticatedPrincipal):
            raise TypeError("archivist product principal type is invalid")
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
            raise TypeError("archivist product principal type is invalid")
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
                self._fenced_reason = "archivist product workers did not stop"
            if self._fenced_reason is not None:
                raise ArchivistIngestionContainmentError(self._fenced_reason)

    def _run(self, job: _IngestionJob) -> None:
        with self._lock:
            if job.status == "queued":
                job.status = "running"
        try:
            result = self._runner.stage(
                job.request,
                principal=job.principal,
                cancellation=job.cancellation,
            )
            if not isinstance(result, ArchivistJobView):
                raise ArchivistIngestionContainmentError(
                    "archivist product result type is invalid"
                )
            projected = _project_result(job, result)
            with self._lock:
                _apply_view(job, projected)
        except ArchivistIngestionServiceError as error:
            with self._lock:
                _apply_failure(job, error.reason)
        except BaseException:
            with self._lock:
                _apply_failure(job, "service-unavailable")
                self._fenced_reason = "archivist product worker containment failed"
        finally:
            with self._lock:
                self._threads.pop(job.request_id, None)

    def _require_open_locked(self) -> None:
        if self._closed:
            raise ArchivistIngestionContainmentError(
                "archivist product service is closed"
            )
        if self._fenced_reason is not None:
            raise ArchivistIngestionContainmentError(self._fenced_reason)

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
        excess = max(
            0,
            len(retained) - _MAXIMUM_RETAINED_TERMINAL_INGESTIONS,
        )
        expired.update(retained[:excess])
        for request_id in expired:
            self._jobs.pop(request_id, None)


def _project_result(
    job: _IngestionJob,
    result: ArchivistJobView,
) -> ArchivistIngestionJobView:
    if result.status == "staged":
        if result.capture_sha256 is None:
            raise ArchivistIngestionContainmentError(
                "archivist staged result omitted its capture identity"
            )
        return ArchivistIngestionJobView(
            request_id=job.request_id,
            status="staged",
            job_id=job.request.job_id,
            result_sha256=job.request.expected_result_sha256,
            capture_sha256=result.capture_sha256,
            source_admission_sha256=result.source_admission_sha256,
            generation_sha256=result.generation_sha256,
            concept_count=result.concept_count,
            permission_count=result.permission_count,
        )
    if result.status == "cancelled":
        return ArchivistIngestionJobView(
            request_id=job.request_id,
            status="cancelled",
            job_id=job.request.job_id,
            result_sha256=job.request.expected_result_sha256,
            reason=(
                result.reason
                if result.reason in _TERMINAL_REASONS["cancelled"]
                else "client-cancelled"
            ),
        )
    if result.status == "failed":
        return ArchivistIngestionJobView(
            request_id=job.request_id,
            status="failed",
            job_id=job.request.job_id,
            result_sha256=job.request.expected_result_sha256,
            reason=(
                result.reason
                if result.reason in _TERMINAL_REASONS["failed"]
                else "storage-unavailable"
            ),
        )
    raise ArchivistIngestionContainmentError("archivist product result is not terminal")


def _apply_view(job: _IngestionJob, view: ArchivistIngestionJobView) -> None:
    job.status = view.status
    job.capture_sha256 = view.capture_sha256
    job.source_admission_sha256 = view.source_admission_sha256
    job.generation_sha256 = view.generation_sha256
    job.concept_count = view.concept_count
    job.permission_count = view.permission_count
    job.reason = view.reason
    job.terminal_at = time.monotonic()


def _apply_failure(job: _IngestionJob, reason: str) -> None:
    _apply_view(
        job,
        ArchivistIngestionJobView(
            request_id=job.request_id,
            status="failed",
            job_id=job.request.job_id,
            result_sha256=job.request.expected_result_sha256,
            reason=reason,
        ),
    )


__all__ = [
    "ArchivistIngestionContainmentError",
    "ArchivistIngestionJobView",
    "ArchivistIngestionRequest",
    "ArchivistIngestionRunner",
    "ArchivistIngestionService",
    "ArchivistIngestionServiceError",
]
