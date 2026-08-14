from __future__ import annotations

from dataclasses import dataclass
import re
import threading
import time
from typing import Protocol
from uuid import uuid4

from yap_server.auth import AuthenticatedPrincipal, PrincipalKey

from .coordinator import CoordinatorProposalBundle, CoordinatorRequest
from .coordinator_service import CoordinatorJobView


_MAXIMUM_INFLIGHT_REQUESTS = 64
_MAXIMUM_RETAINED_TERMINAL_REQUESTS = 256
_TERMINAL_RETENTION_SECONDS = 15 * 60.0
_CLOSE_TIMEOUT_SECONDS = 68.0
_REQUEST_ID = re.compile(r"^coordinator-bundle-[0-9a-f]{32}$")
_ACTIVE_STATUSES = frozenset({"queued", "running", "cancellation-requested"})
_TERMINAL_STATUSES = frozenset(
    {"complete", "evidence-unavailable", "cancelled", "failed"}
)


class CoordinatorBundleRunner(Protocol):
    def coordinate(
        self,
        request: CoordinatorRequest,
        *,
        principal: AuthenticatedPrincipal,
        cancellation: threading.Event,
    ) -> CoordinatorJobView: ...


class CoordinatorBundleContainmentError(RuntimeError):
    pass


class CoordinatorBundleServiceError(RuntimeError):
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
class CoordinatorBundleJobView:
    request_id: str
    status: str
    bundle: CoordinatorProposalBundle | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.request_id, str)
            or _REQUEST_ID.fullmatch(self.request_id) is None
        ):
            raise ValueError("coordinator product request identity is invalid")
        if self.status not in _ACTIVE_STATUSES | _TERMINAL_STATUSES:
            raise ValueError("coordinator product status is invalid")
        if self.status == "complete":
            if (
                not isinstance(self.bundle, CoordinatorProposalBundle)
                or self.reason is not None
            ):
                raise ValueError("complete coordinator product view is invalid")
        elif self.status in _ACTIVE_STATUSES:
            if self.bundle is not None or self.reason is not None:
                raise ValueError("active coordinator product view is invalid")
        elif (
            self.bundle is not None
            or not isinstance(self.reason, str)
            or not self.reason
        ):
            raise ValueError("terminal coordinator product view is invalid")

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


@dataclass(slots=True)
class _BundleJob:
    request_id: str
    owner: PrincipalKey
    principal: AuthenticatedPrincipal
    request: CoordinatorRequest
    cancellation: threading.Event
    status: str = "queued"
    bundle: CoordinatorProposalBundle | None = None
    reason: str | None = None
    terminal_at: float | None = None

    def view(self) -> CoordinatorBundleJobView:
        return CoordinatorBundleJobView(
            request_id=self.request_id,
            status=self.status,
            bundle=self.bundle,
            reason=self.reason,
        )


class CoordinatorBundleService:
    """Own asynchronous, principal-scoped product access to Coordinator."""

    def __init__(self, *, coordinator: CoordinatorBundleRunner) -> None:
        self._coordinator = coordinator
        self._lock = threading.RLock()
        self._jobs: dict[str, _BundleJob] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._closed = False
        self._fenced_reason: str | None = None

    def submit(
        self,
        request: CoordinatorRequest,
        *,
        principal: AuthenticatedPrincipal,
    ) -> CoordinatorBundleJobView:
        if not isinstance(request, CoordinatorRequest):
            raise TypeError("coordinator product request type is invalid")
        if not isinstance(principal, AuthenticatedPrincipal):
            raise TypeError("coordinator product principal type is invalid")
        with self._lock:
            self._require_open_locked()
            self._prune_locked()
            if sum(job.terminal_at is None for job in self._jobs.values()) >= (
                _MAXIMUM_INFLIGHT_REQUESTS
            ):
                raise CoordinatorBundleServiceError(
                    429,
                    "COORDINATOR_BUNDLE_CAPACITY",
                    "Coordination-bundle capacity is temporarily unavailable.",
                    retryable=True,
                )
            request_id = f"coordinator-bundle-{uuid4().hex}"
            if request_id in self._jobs:
                raise CoordinatorBundleContainmentError(
                    "coordinator product request identity collided"
                )
            job = _BundleJob(
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
    ) -> CoordinatorBundleJobView | None:
        if not isinstance(principal, AuthenticatedPrincipal):
            raise TypeError("coordinator product principal type is invalid")
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
            raise TypeError("coordinator product principal type is invalid")
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
                self._fenced_reason = "coordinator product workers did not stop"
            if self._fenced_reason is not None:
                raise CoordinatorBundleContainmentError(self._fenced_reason)

    def _run(self, job: _BundleJob) -> None:
        with self._lock:
            if job.status == "queued":
                job.status = "running"
        try:
            result = self._coordinator.coordinate(
                job.request,
                principal=job.principal,
                cancellation=job.cancellation,
            )
            if not isinstance(result, CoordinatorJobView):
                raise CoordinatorBundleContainmentError(
                    "coordinator product result type is invalid"
                )
            if (
                not isinstance(result.request_id, str)
                or not result.request_id
                or result.status not in _TERMINAL_STATUSES
            ):
                raise CoordinatorBundleContainmentError(
                    "coordinator product result identity is invalid"
                )
            projected = CoordinatorBundleJobView(
                request_id=job.request_id,
                status=result.status,
                bundle=result.bundle,
                reason=result.reason,
            )
            with self._lock:
                job.status = projected.status
                job.bundle = projected.bundle
                job.reason = projected.reason
                job.terminal_at = time.monotonic()
        except BaseException:
            with self._lock:
                job.status = "failed"
                job.bundle = None
                job.reason = "service-unavailable"
                job.terminal_at = time.monotonic()
                self._fenced_reason = "coordinator product worker containment failed"
        finally:
            with self._lock:
                self._threads.pop(job.request_id, None)

    def _require_open_locked(self) -> None:
        if self._closed:
            raise CoordinatorBundleContainmentError(
                "coordinator product service is closed"
            )
        if self._fenced_reason is not None:
            raise CoordinatorBundleContainmentError(self._fenced_reason)

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
    "CoordinatorBundleContainmentError",
    "CoordinatorBundleJobView",
    "CoordinatorBundleRunner",
    "CoordinatorBundleService",
    "CoordinatorBundleServiceError",
]
