from __future__ import annotations

from dataclasses import dataclass
import threading
import time
from typing import Protocol
from uuid import uuid4

from yap_server.auth import AuthenticatedPrincipal, PrincipalKey

from .librarian import LibrarianEvidencePack, LibrarianRequest
from .librarian_service import LibrarianJobView


_MAXIMUM_INFLIGHT_QUERIES = 64
_MAXIMUM_RETAINED_TERMINAL_QUERIES = 256
_TERMINAL_RETENTION_SECONDS = 15 * 60.0
_CLOSE_TIMEOUT_SECONDS = 22.0
_ACTIVE_STATUSES = frozenset({"queued", "running", "cancellation-requested"})
_TERMINAL_STATUSES = frozenset(
    {"complete", "evidence-unavailable", "cancelled", "failed"}
)


class LibrarianQueryRunner(Protocol):
    def query(
        self,
        request: LibrarianRequest,
        *,
        principal: AuthenticatedPrincipal,
        cancellation: threading.Event,
    ) -> LibrarianJobView: ...


class LibrarianQueryContainmentError(RuntimeError):
    pass


class LibrarianQueryServiceError(RuntimeError):
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
class LibrarianQueryJobView:
    request_id: str
    status: str
    evidence: LibrarianEvidencePack | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.request_id, str)
            or not self.request_id.startswith("librarian-query-")
            or len(self.request_id) != len("librarian-query-") + 32
            or any(
                byte not in b"0123456789abcdef"
                for byte in self.request_id[len("librarian-query-") :].encode()
            )
        ):
            raise ValueError("librarian product request identity is invalid")
        if self.status not in _ACTIVE_STATUSES | _TERMINAL_STATUSES:
            raise ValueError("librarian product status is invalid")
        if self.status == "complete":
            if (
                self.evidence is None
                or not self.evidence.items
                or self.reason is not None
            ):
                raise ValueError("complete librarian query view is invalid")
        elif self.status in _ACTIVE_STATUSES:
            if self.evidence is not None or self.reason is not None:
                raise ValueError("active librarian query view is invalid")
        elif self.evidence is not None or not self.reason:
            raise ValueError("terminal librarian query view is invalid")

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


@dataclass(slots=True)
class _QueryJob:
    request_id: str
    owner: PrincipalKey
    principal: AuthenticatedPrincipal
    request: LibrarianRequest
    cancellation: threading.Event
    status: str = "queued"
    evidence: LibrarianEvidencePack | None = None
    reason: str | None = None
    terminal_at: float | None = None

    def view(self) -> LibrarianQueryJobView:
        return LibrarianQueryJobView(
            request_id=self.request_id,
            status=self.status,
            evidence=self.evidence,
            reason=self.reason,
        )


class LibrarianQueryService:
    """Own asynchronous, owner-scoped product access to Librarian."""

    def __init__(self, *, librarian: LibrarianQueryRunner) -> None:
        self._librarian = librarian
        self._lock = threading.RLock()
        self._jobs: dict[str, _QueryJob] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._closed = False
        self._fenced_reason: str | None = None

    def submit(
        self,
        request: LibrarianRequest,
        *,
        principal: AuthenticatedPrincipal,
    ) -> LibrarianQueryJobView:
        if not isinstance(request, LibrarianRequest):
            raise TypeError("librarian product request type is invalid")
        if not isinstance(principal, AuthenticatedPrincipal):
            raise TypeError("librarian product principal type is invalid")
        with self._lock:
            self._require_open_locked()
            self._prune_locked()
            if sum(job.terminal_at is None for job in self._jobs.values()) >= (
                _MAXIMUM_INFLIGHT_QUERIES
            ):
                raise LibrarianQueryServiceError(
                    429,
                    "LIBRARIAN_QUERY_CAPACITY",
                    "Knowledge query capacity is temporarily unavailable.",
                    retryable=True,
                )
            request_id = f"librarian-query-{uuid4().hex}"
            if request_id in self._jobs:
                raise LibrarianQueryContainmentError(
                    "librarian product request identity collided"
                )
            job = _QueryJob(
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
    ) -> LibrarianQueryJobView | None:
        if not isinstance(principal, AuthenticatedPrincipal):
            raise TypeError("librarian product principal type is invalid")
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
            raise TypeError("librarian product principal type is invalid")
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
                self._fenced_reason = "librarian product workers did not stop"
            if self._fenced_reason is not None:
                raise LibrarianQueryContainmentError(self._fenced_reason)

    def _run(self, job: _QueryJob) -> None:
        with self._lock:
            if job.status == "queued":
                job.status = "running"
        try:
            result = self._librarian.query(
                job.request,
                principal=job.principal,
                cancellation=job.cancellation,
            )
            if not isinstance(result, LibrarianJobView):
                raise LibrarianQueryContainmentError(
                    "librarian product result type is invalid"
                )
            if result.status not in _TERMINAL_STATUSES:
                raise LibrarianQueryContainmentError(
                    "librarian product result is not terminal"
                )
            projected = LibrarianQueryJobView(
                request_id=job.request_id,
                status=result.status,
                evidence=result.evidence,
                reason=result.reason,
            )
            with self._lock:
                job.status = projected.status
                job.evidence = projected.evidence
                job.reason = projected.reason
                job.terminal_at = time.monotonic()
        except BaseException:
            with self._lock:
                job.status = "failed"
                job.evidence = None
                job.reason = "service-unavailable"
                job.terminal_at = time.monotonic()
                self._fenced_reason = "librarian product worker containment failed"
        finally:
            with self._lock:
                self._threads.pop(job.request_id, None)

    def _require_open_locked(self) -> None:
        if self._closed:
            raise LibrarianQueryContainmentError("librarian product service is closed")
        if self._fenced_reason is not None:
            raise LibrarianQueryContainmentError(self._fenced_reason)

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
            len(retained) - _MAXIMUM_RETAINED_TERMINAL_QUERIES,
        )
        expired.update(retained[:excess])
        for request_id in expired:
            self._jobs.pop(request_id, None)


__all__ = [
    "LibrarianQueryContainmentError",
    "LibrarianQueryJobView",
    "LibrarianQueryRunner",
    "LibrarianQueryService",
    "LibrarianQueryServiceError",
]
