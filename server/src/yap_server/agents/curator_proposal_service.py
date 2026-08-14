from __future__ import annotations

from dataclasses import dataclass
import re
import threading
import time
from typing import Protocol
from uuid import uuid4

from yap_server.auth import AuthenticatedPrincipal, PrincipalKey

from .curator import CuratorRequest
from .curator_service import (
    CuratorJobView,
    CuratorServiceError,
)


_MAXIMUM_INFLIGHT_REQUESTS = 64
_MAXIMUM_RETAINED_TERMINAL_REQUESTS = 256
_TERMINAL_RETENTION_SECONDS = 15 * 60.0
_CLOSE_TIMEOUT_SECONDS = 62.0
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REQUEST_ID = re.compile(r"^curator-proposal-[0-9a-f]{32}$")
_ACTIVE_STATUSES = frozenset({"queued", "running", "cancellation-requested"})
_TERMINAL_STATUSES = frozenset({"proposed", "rejected", "cancelled", "failed"})


class CuratorProposalRunner(Protocol):
    def propose(
        self,
        request: CuratorRequest,
        *,
        principal: AuthenticatedPrincipal,
        cancellation: threading.Event,
    ) -> CuratorJobView: ...


class CuratorProposalContainmentError(RuntimeError):
    pass


class CuratorProposalServiceError(RuntimeError):
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
class CuratorProposalJobView:
    request_id: str
    submission_id: str
    status: str
    generation_sha256: str
    evidence_sha256: str | None = None
    proposal_id: str | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.request_id, str)
            or _REQUEST_ID.fullmatch(self.request_id) is None
            or not isinstance(self.submission_id, str)
            or not self.submission_id
            or len(self.submission_id) > 128
            or not isinstance(self.generation_sha256, str)
            or _SHA256.fullmatch(self.generation_sha256) is None
        ):
            raise ValueError("curator product identity is invalid")
        if self.evidence_sha256 is not None and (
            not isinstance(self.evidence_sha256, str)
            or _SHA256.fullmatch(self.evidence_sha256) is None
        ):
            raise ValueError("curator product evidence identity is invalid")
        if self.status not in _ACTIVE_STATUSES | _TERMINAL_STATUSES:
            raise ValueError("curator product status is invalid")
        if self.status in _ACTIVE_STATUSES:
            if (
                self.evidence_sha256 is not None
                or self.proposal_id is not None
                or self.reason is not None
            ):
                raise ValueError("active curator product view is invalid")
        elif self.status == "proposed":
            if (
                self.evidence_sha256 is None
                or not isinstance(self.proposal_id, str)
                or _SHA256.fullmatch(self.proposal_id) is None
                or self.reason is not None
            ):
                raise ValueError("proposed curator product view is invalid")
        elif self.status == "rejected":
            if (
                self.evidence_sha256 is None
                or self.proposal_id is not None
                or self.reason != "model-rejected"
            ):
                raise ValueError("rejected curator product view is invalid")
        elif (
            self.proposal_id is not None
            or not isinstance(self.reason, str)
            or not self.reason
        ):
            raise ValueError("terminal curator product view is invalid")

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


@dataclass(slots=True)
class _ProposalJob:
    request_id: str
    owner: PrincipalKey
    principal: AuthenticatedPrincipal
    request: CuratorRequest
    cancellation: threading.Event
    status: str = "queued"
    evidence_sha256: str | None = None
    proposal_id: str | None = None
    reason: str | None = None
    terminal_at: float | None = None

    def view(self) -> CuratorProposalJobView:
        return CuratorProposalJobView(
            request_id=self.request_id,
            submission_id=self.request.submission_id,
            status=self.status,
            generation_sha256=self.request.expected_generation_sha256,
            evidence_sha256=self.evidence_sha256,
            proposal_id=self.proposal_id,
            reason=self.reason,
        )


class CuratorProposalService:
    """Own asynchronous, principal-scoped product access to Curator."""

    def __init__(self, *, curator: CuratorProposalRunner) -> None:
        self._curator = curator
        self._lock = threading.RLock()
        self._jobs: dict[str, _ProposalJob] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._closed = False
        self._fenced_reason: str | None = None

    def submit(
        self,
        request: CuratorRequest,
        *,
        principal: AuthenticatedPrincipal,
    ) -> CuratorProposalJobView:
        if not isinstance(request, CuratorRequest):
            raise TypeError("curator product request type is invalid")
        if not isinstance(principal, AuthenticatedPrincipal):
            raise TypeError("curator product principal type is invalid")
        with self._lock:
            self._require_open_locked()
            self._prune_locked()
            if sum(job.terminal_at is None for job in self._jobs.values()) >= (
                _MAXIMUM_INFLIGHT_REQUESTS
            ):
                raise CuratorProposalServiceError(
                    429,
                    "CURATOR_PROPOSAL_CAPACITY",
                    "Knowledge-proposal capacity is temporarily unavailable.",
                    retryable=True,
                )
            request_id = f"curator-proposal-{uuid4().hex}"
            if request_id in self._jobs:
                raise CuratorProposalContainmentError(
                    "curator product request identity collided"
                )
            job = _ProposalJob(
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
    ) -> CuratorProposalJobView | None:
        if not isinstance(principal, AuthenticatedPrincipal):
            raise TypeError("curator product principal type is invalid")
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
            raise TypeError("curator product principal type is invalid")
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
                self._fenced_reason = "curator product workers did not stop"
            if self._fenced_reason is not None:
                raise CuratorProposalContainmentError(self._fenced_reason)

    def _run(self, job: _ProposalJob) -> None:
        with self._lock:
            if job.status == "queued":
                job.status = "running"
        try:
            result = self._curator.propose(
                job.request,
                principal=job.principal,
                cancellation=job.cancellation,
            )
            if not isinstance(result, CuratorJobView):
                raise CuratorProposalContainmentError(
                    "curator product result type is invalid"
                )
            if (
                result.status not in _TERMINAL_STATUSES
                or result.submission_id != job.request.submission_id
                or result.generation_sha256 != job.request.expected_generation_sha256
            ):
                raise CuratorProposalContainmentError(
                    "curator product result identity is invalid"
                )
            projected = CuratorProposalJobView(
                request_id=job.request_id,
                submission_id=result.submission_id,
                status=result.status,
                generation_sha256=result.generation_sha256,
                evidence_sha256=result.evidence_sha256,
                proposal_id=result.proposal_id,
                reason=result.reason,
            )
            with self._lock:
                job.status = projected.status
                job.evidence_sha256 = projected.evidence_sha256
                job.proposal_id = projected.proposal_id
                job.reason = projected.reason
                job.terminal_at = time.monotonic()
        except CuratorServiceError as error:
            with self._lock:
                job.status = "failed"
                job.evidence_sha256 = None
                job.proposal_id = None
                job.reason = _curator_service_reason(error)
                job.terminal_at = time.monotonic()
        except BaseException:
            with self._lock:
                job.status = "failed"
                job.evidence_sha256 = None
                job.proposal_id = None
                job.reason = "service-unavailable"
                job.terminal_at = time.monotonic()
                self._fenced_reason = "curator product worker containment failed"
        finally:
            with self._lock:
                self._threads.pop(job.request_id, None)

    def _require_open_locked(self) -> None:
        if self._closed:
            raise CuratorProposalContainmentError("curator product service is closed")
        if self._fenced_reason is not None:
            raise CuratorProposalContainmentError(self._fenced_reason)

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


def _curator_service_reason(error: CuratorServiceError) -> str:
    return {
        "CURATOR_DEADLINE": "deadline-exceeded",
        "CURATOR_SUBMISSION_CONFLICT": "submission-conflict",
    }.get(error.code, "service-unavailable")


__all__ = [
    "CuratorProposalContainmentError",
    "CuratorProposalJobView",
    "CuratorProposalRunner",
    "CuratorProposalService",
    "CuratorProposalServiceError",
]
