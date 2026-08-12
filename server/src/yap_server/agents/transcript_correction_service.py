from __future__ import annotations

from dataclasses import dataclass
import threading
import time
from typing import Protocol

from yap_server.agents.admission_protocol import (
    AgentAdmission,
    AgentAdmissionTicket,
    AgentPurpose,
    AgentRole,
    AgentWorkSpec,
    ExecutionRoute,
    SchedulingClass,
)
from yap_server.auth import AuthenticatedPrincipal, PrincipalKey
from yap_server.knowledge.agent_reasoning_routes import ReasoningRetryableError
from yap_server.knowledge.knowledge_tool_contract import KnowledgeToolCancelled

from .transcript_correction import (
    BoundTranscriptCorrectionRequest,
    TranscriptCorrectionRequest,
    TranscriptCorrectionTerminology,
    ValidatedTranscriptCorrection,
    bind_transcript_correction_request,
)
from .transcript_correction_model import TranscriptCorrectionCancelled


_MAXIMUM_INFLIGHT_JOBS = 64
_MAXIMUM_RETAINED_TERMINAL_JOBS = 256
_JOB_DEADLINE_SECONDS = 60.0
_TERMINAL_RETENTION_SECONDS = 15 * 60.0
_ADMISSION_POLL_SECONDS = 0.1
_CLOSE_TIMEOUT_SECONDS = 5.0
_SCRIBE_WORK = AgentWorkSpec(
    role=AgentRole.SCRIBE,
    purpose=AgentPurpose.TRANSCRIPT_CORRECT,
    route=ExecutionRoute.RAPID_AUTOMATION,
    scheduling_class=SchedulingClass.HOT,
)


class TranscriptCorrectionAdmission(Protocol):
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


class TranscriptCorrectionModelProtocol(Protocol):
    def correct(
        self,
        request: BoundTranscriptCorrectionRequest,
        *,
        cancellation: threading.Event,
    ) -> ValidatedTranscriptCorrection: ...


class TranscriptCorrectionTerminologyResolver(Protocol):
    def resolve(
        self,
        *,
        principal: AuthenticatedPrincipal,
        locale: str,
    ) -> TranscriptCorrectionTerminology: ...


class TranscriptCorrectionTerminologyUnavailable(RuntimeError):
    pass


class TranscriptCorrectionContainmentError(RuntimeError):
    pass


class TranscriptCorrectionServiceError(RuntimeError):
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
class TranscriptCorrectionJobView:
    request_id: str
    status: str
    source_revision_sha256: str
    source_sha256: str
    terminology_snapshot_sha256: str
    applied: bool
    corrected_text: str | None = None
    reason: str | None = None

    def to_wire(self) -> dict[str, object]:
        value: dict[str, object] = {
            "schemaVersion": 1,
            "requestId": self.request_id,
            "status": self.status,
            "sourceRevisionSha256": self.source_revision_sha256,
            "sourceSha256": self.source_sha256,
            "terminologySnapshotSha256": self.terminology_snapshot_sha256,
            "applied": self.applied,
        }
        if self.corrected_text is not None:
            value["correctedText"] = self.corrected_text
        if self.reason is not None:
            value["reason"] = self.reason
        return value


@dataclass(slots=True)
class _CorrectionJob:
    principal: AuthenticatedPrincipal
    owner: PrincipalKey
    request: BoundTranscriptCorrectionRequest
    ticket: AgentAdmissionTicket
    initial_admission: AgentAdmission
    cancellation: threading.Event
    deadline: float
    status: str = "queued"
    cancel_reason: str | None = None
    applied: bool = False
    corrected_text: str | None = None
    reason: str | None = None
    terminal_at: float | None = None
    completion_started: bool = False

    def view(self) -> TranscriptCorrectionJobView:
        return TranscriptCorrectionJobView(
            request_id=self.ticket.request_id,
            status=self.status,
            source_revision_sha256=self.request.source_revision_sha256,
            source_sha256=self.request.source_sha256,
            terminology_snapshot_sha256=(
                self.request.terminology.snapshot_sha256
            ),
            applied=self.applied,
            corrected_text=self.corrected_text,
            reason=self.reason,
        )


class TranscriptCorrectionService:
    """Own owner-bound correction work from broker queue through containment."""

    def __init__(
        self,
        *,
        admission: TranscriptCorrectionAdmission,
        model: TranscriptCorrectionModelProtocol,
        terminology: TranscriptCorrectionTerminologyResolver,
    ) -> None:
        self._admission = admission
        self._model = model
        self._terminology = terminology
        self._lock = threading.RLock()
        self._idle = threading.Condition(self._lock)
        self._jobs: dict[str, _CorrectionJob] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._submissions = 0
        self._closed = False
        self._fenced_reason: str | None = None

    def submit(
        self,
        request: TranscriptCorrectionRequest,
        *,
        principal: AuthenticatedPrincipal,
    ) -> TranscriptCorrectionJobView:
        submission_started = time.monotonic()
        if not isinstance(request, TranscriptCorrectionRequest):
            raise TypeError("transcript correction request type is invalid")
        if not isinstance(principal, AuthenticatedPrincipal):
            raise TypeError("transcript correction principal type is invalid")
        with self._lock:
            self._require_open_locked()
            self._prune_locked()
            inflight_jobs = sum(
                job.terminal_at is None for job in self._jobs.values()
            )
            if (
                inflight_jobs + self._submissions
                >= _MAXIMUM_INFLIGHT_JOBS
            ):
                raise TranscriptCorrectionServiceError(
                    429,
                    "TRANSCRIPT_CORRECTION_CAPACITY",
                    "Transcript correction capacity is temporarily unavailable.",
                    retryable=True,
                )
            self._submissions += 1
        try:
            try:
                terminology = self._terminology.resolve(
                    principal=principal,
                    locale=request.language_bcp47,
                )
            except TranscriptCorrectionTerminologyUnavailable as error:
                raise TranscriptCorrectionServiceError(
                    503,
                    "TRANSCRIPT_CORRECTION_TERMINOLOGY_UNAVAILABLE",
                    "Approved terminology is temporarily unavailable.",
                    retryable=True,
                ) from error
            if not isinstance(terminology, TranscriptCorrectionTerminology):
                raise TranscriptCorrectionContainmentError(
                    "transcript correction terminology identity is invalid"
                )
            bound_request = bind_transcript_correction_request(request, terminology)
            deadline = submission_started + _JOB_DEADLINE_SECONDS
            remaining_deadline_ms = int(
                max(0.0, deadline - time.monotonic()) * 1_000
            )
            if remaining_deadline_ms <= 0:
                raise TranscriptCorrectionServiceError(
                    504,
                    "TRANSCRIPT_CORRECTION_DEADLINE",
                    "Transcript correction could not start before its deadline.",
                    retryable=True,
                )
            ticket = self._admission.new_ticket()
            try:
                initial = self._admission.submit(
                    ticket,
                    principal=principal,
                    work=_SCRIBE_WORK,
                    source_sha256=bound_request.source_sha256,
                    remaining_deadline_ms=remaining_deadline_ms,
                )
            except BaseException:
                self._contain_unstarted_ticket(ticket)
                raise
            if initial.outcome not in {"queued", "admitted"}:
                raise _submit_error(initial.outcome)
            job = _CorrectionJob(
                principal=principal,
                owner=principal.key,
                request=bound_request,
                ticket=ticket,
                initial_admission=initial,
                cancellation=threading.Event(),
                deadline=deadline,
            )
            thread = threading.Thread(
                target=self._run_job,
                args=(job,),
                name=f"scribe-{ticket.request_id}",
                daemon=False,
            )
            with self._lock:
                if self._closed or self._fenced_reason is not None:
                    contain_instead = True
                    identity_collision = False
                elif ticket.request_id in self._jobs:
                    contain_instead = True
                    identity_collision = True
                else:
                    contain_instead = False
                    identity_collision = False
                    self._jobs[ticket.request_id] = job
                    self._threads[ticket.request_id] = thread
            if contain_instead:
                self._contain_unstarted_ticket(ticket)
                if identity_collision:
                    raise RuntimeError(
                        "transcript correction request identity collided"
                    )
                raise TranscriptCorrectionServiceError(
                    503,
                    "TRANSCRIPT_CORRECTION_UNAVAILABLE",
                    "Transcript correction service is closed.",
                    retryable=True,
                )
            try:
                thread.start()
            except BaseException:
                with self._lock:
                    self._jobs.pop(ticket.request_id, None)
                    self._threads.pop(ticket.request_id, None)
                self._contain_unstarted_ticket(ticket)
                raise
            with self._lock:
                return job.view()
        finally:
            with self._lock:
                self._submissions -= 1
                self._idle.notify_all()

    def get(
        self,
        request_id: str,
        *,
        principal: AuthenticatedPrincipal,
    ) -> TranscriptCorrectionJobView | None:
        if not isinstance(principal, AuthenticatedPrincipal):
            raise TypeError("transcript correction principal type is invalid")
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
            raise TypeError("transcript correction principal type is invalid")
        with self._lock:
            job = self._jobs.get(request_id)
            if (
                job is None
                or job.owner != principal.key
                or job.terminal_at is not None
                or job.completion_started
            ):
                return False
            self._request_cancellation_locked(job, "client-cancelled")
            return True

    def close(self) -> None:
        deadline = time.monotonic() + _CLOSE_TIMEOUT_SECONDS
        with self._lock:
            self._closed = True
            while self._submissions:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._fenced_reason = (
                        "transcript correction admission did not drain during shutdown"
                    )
                    break
                self._idle.wait(timeout=remaining)
            for job in self._jobs.values():
                if job.terminal_at is None:
                    self._request_cancellation_locked(job, "service-closed")
            threads = tuple(self._threads.values())
        for thread in threads:
            thread.join(timeout=max(0.0, deadline - time.monotonic()))
        with self._lock:
            alive = any(thread.is_alive() for thread in threads)
            if alive or self._fenced_reason is not None:
                raise TranscriptCorrectionContainmentError(
                    self._fenced_reason
                    or "transcript correction workers did not stop"
                )

    def _contain_unstarted_ticket(self, ticket: AgentAdmissionTicket) -> None:
        try:
            cancelled = self._admission.cancel(ticket)
            if cancelled.outcome == "cancellation-requested":
                terminal = self._admission.acknowledge_cancellation(ticket)
                contained = terminal.outcome == "cancelled"
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
            with self._lock:
                self._fenced_reason = (
                    "transcript correction admission could not be contained"
                )
            raise TranscriptCorrectionContainmentError(
                "transcript correction admission could not be contained"
            )

    def _run_job(self, job: _CorrectionJob) -> None:
        deadline_timer: threading.Timer | None = None
        try:
            admission = job.initial_admission
            while admission.outcome == "queued":
                if self._wait_for_cancellation_or_deadline(job):
                    self._cancel_and_acknowledge(job)
                    return
                admission = self._admission.status(job.ticket)
            if admission.outcome == "cancellation-requested":
                reason = _cancellation_reason(admission.cancellation_reason)
                expected_outcome = _expected_cancellation_outcome(admission)
                if expected_outcome is None:
                    self._fence(job, "transcript correction cancellation was invalid")
                    return
                self._acknowledge_cancellation(
                    job,
                    expected_outcome=expected_outcome,
                    terminal_status=_terminal_status_for_reason(reason),
                    reason=reason,
                )
                return
            if admission.outcome != "admitted":
                self._finish_unchanged(job, _admission_reason(admission.outcome))
                return
            generation = admission.provider_generation
            if generation is None:
                self._fence(job, "admitted correction omitted provider identity")
                return
            deadline_timer = self._start_deadline_timer(job)
            with self._lock:
                if job.cancellation.is_set():
                    pass
                else:
                    job.status = "running"
            if job.cancellation.is_set():
                self._cancel_and_acknowledge(job)
                return

            correction: ValidatedTranscriptCorrection | None = None
            unchanged_reason: str | None = None
            try:
                correction = self._model.correct(
                    job.request,
                    cancellation=job.cancellation,
                )
            except (TranscriptCorrectionCancelled, KnowledgeToolCancelled):
                self._cancel_and_acknowledge(job)
                return
            except ReasoningRetryableError:
                unchanged_reason = "runtime-unavailable"
            except ValueError:
                unchanged_reason = "invalid-output"
            except RuntimeError:
                self._fence(job, "transcript correction worker containment failed")
                return

            if job.cancellation.is_set():
                self._cancel_and_acknowledge(job)
                return
            current = self._admission.status(job.ticket)
            if (
                current.outcome != "admitted"
                or current.provider_generation != generation
            ):
                if current.outcome == "cancellation-requested":
                    reason = _cancellation_reason(current.cancellation_reason)
                elif current.outcome == "admitted":
                    reason = "provider-changed"
                else:
                    reason = _admission_reason(current.outcome)
                self._cancel_and_acknowledge(
                    job,
                    reason=reason,
                )
                return
            with self._lock:
                if job.cancellation.is_set():
                    cancel_before_completion = True
                else:
                    cancel_before_completion = False
                    job.completion_started = True
            if cancel_before_completion:
                self._cancel_and_acknowledge(job)
                return
            completed = self._admission.complete(job.ticket)
            self._stop_deadline_timer(deadline_timer)
            deadline_timer = None
            if completed.outcome != "completed":
                reason = _cancellation_result_reason(completed)
                expected_outcome = _expected_cancellation_outcome(completed)
                if reason is not None and expected_outcome is not None:
                    self._acknowledge_cancellation(
                        job,
                        expected_outcome=expected_outcome,
                        terminal_status=_terminal_status_for_reason(reason),
                        reason=reason,
                    )
                    return
                self._fence(job, "transcript correction lease did not complete")
                return
            if job.cancellation.is_set():
                self._finish_unchanged(
                    job,
                    job.cancel_reason or "deadline-exceeded",
                )
                return
            if correction is None:
                self._finish_unchanged(job, unchanged_reason or "invalid-output")
                return
            self._finish_correction(job, correction)
        except BaseException:
            self._fence(job, "transcript correction lifecycle failed")
        finally:
            self._stop_deadline_timer(deadline_timer)
            with self._lock:
                self._threads.pop(job.ticket.request_id, None)
                self._idle.notify_all()

    def _wait_for_cancellation_or_deadline(self, job: _CorrectionJob) -> bool:
        remaining = job.deadline - time.monotonic()
        if remaining <= 0:
            with self._lock:
                self._request_cancellation_locked(job, "deadline-exceeded")
            return True
        return job.cancellation.wait(min(_ADMISSION_POLL_SECONDS, remaining))

    def _start_deadline_timer(self, job: _CorrectionJob) -> threading.Timer | None:
        remaining = job.deadline - time.monotonic()
        if remaining <= 0:
            with self._lock:
                self._request_cancellation_locked(job, "deadline-exceeded")
            return None
        timer = threading.Timer(remaining, self._expire_job, args=(job,))
        timer.name = f"scribe-deadline-{job.ticket.request_id}"
        timer.daemon = False
        timer.start()
        return timer

    @staticmethod
    def _stop_deadline_timer(timer: threading.Timer | None) -> None:
        if timer is None:
            return
        timer.cancel()
        timer.join()

    def _expire_job(self, job: _CorrectionJob) -> None:
        with self._lock:
            self._request_cancellation_locked(job, "deadline-exceeded")

    @staticmethod
    def _request_cancellation_locked(job: _CorrectionJob, reason: str) -> bool:
        if job.terminal_at is not None or job.cancellation.is_set():
            return False
        job.cancel_reason = reason
        job.status = "cancellation-requested"
        job.cancellation.set()
        return True

    def _cancel_and_acknowledge(
        self,
        job: _CorrectionJob,
        *,
        reason: str | None = None,
    ) -> None:
        final_reason = reason or job.cancel_reason or "client-cancelled"
        cancelled = self._admission.cancel(job.ticket)
        expected_outcome = _expected_cancellation_outcome(cancelled)
        if expected_outcome is None:
            self._fence(job, "transcript correction cancellation was not admitted")
            return
        self._acknowledge_cancellation(
            job,
            expected_outcome=expected_outcome,
            terminal_status=_terminal_status_for_reason(final_reason),
            reason=final_reason,
        )

    def _acknowledge_cancellation(
        self,
        job: _CorrectionJob,
        *,
        expected_outcome: str,
        terminal_status: str,
        reason: str | None = None,
    ) -> None:
        terminal = self._admission.acknowledge_cancellation(job.ticket)
        if terminal.outcome != expected_outcome:
            self._fence(job, "transcript correction cancellation was not acknowledged")
            return
        if terminal_status == "complete":
            self._finish_unchanged(job, reason or "provider-changed")
        else:
            with self._lock:
                job.status = "cancelled"
                job.applied = False
                job.corrected_text = None
                job.reason = reason or job.cancel_reason or "client-cancelled"
                job.terminal_at = time.monotonic()

    def _finish_correction(
        self,
        job: _CorrectionJob,
        correction: ValidatedTranscriptCorrection,
    ) -> None:
        corrected_text = (
            job.request.source_text if correction.uncertain else correction.corrected_text
        )
        applied = not correction.uncertain and corrected_text != job.request.source_text
        reason = (
            "uncertain"
            if correction.uncertain
            else (None if applied else "unchanged")
        )
        with self._lock:
            job.status = "complete"
            job.applied = applied
            job.corrected_text = corrected_text
            job.reason = reason
            job.terminal_at = time.monotonic()

    def _finish_unchanged(self, job: _CorrectionJob, reason: str) -> None:
        with self._lock:
            job.status = "complete"
            job.applied = False
            job.corrected_text = job.request.source_text
            job.reason = reason
            job.terminal_at = time.monotonic()

    def _fence(self, job: _CorrectionJob, reason: str) -> None:
        with self._lock:
            self._fenced_reason = reason
            job.status = "failed"
            job.applied = False
            job.corrected_text = None
            job.reason = "containment-failed"
            job.terminal_at = time.monotonic()

    def _require_open_locked(self) -> None:
        if self._closed:
            raise TranscriptCorrectionServiceError(
                503,
                "TRANSCRIPT_CORRECTION_UNAVAILABLE",
                "Transcript correction service is closed.",
                retryable=True,
            )
        if self._fenced_reason is not None:
            raise TranscriptCorrectionContainmentError(self._fenced_reason)

    def _prune_locked(self) -> None:
        cutoff = time.monotonic() - _TERMINAL_RETENTION_SECONDS
        terminal_jobs = sorted(
            (
                (job.terminal_at, request_id)
                for request_id, job in self._jobs.items()
                if job.terminal_at is not None
            ),
            key=lambda item: (item[0], item[1]),
        )
        expired = {
            request_id
            for terminal_at, request_id in terminal_jobs
            if terminal_at is not None and terminal_at < cutoff
        }
        retained = [
            request_id
            for _, request_id in terminal_jobs
            if request_id not in expired
        ]
        excess = max(0, len(retained) - _MAXIMUM_RETAINED_TERMINAL_JOBS)
        expired.update(retained[:excess])
        for request_id in expired:
            self._jobs.pop(request_id, None)


def _submit_error(outcome: str) -> TranscriptCorrectionServiceError:
    if outcome in {"owner-queue-full", "queue-full"}:
        return TranscriptCorrectionServiceError(
            429,
            "TRANSCRIPT_CORRECTION_CAPACITY",
            "Transcript correction capacity is temporarily unavailable.",
            retryable=True,
        )
    if outcome == "broker-busy":
        return TranscriptCorrectionServiceError(
            503,
            "TRANSCRIPT_CORRECTION_UNAVAILABLE",
            "Transcript correction admission is temporarily unavailable.",
            retryable=True,
        )
    if outcome == "provider-unavailable":
        return TranscriptCorrectionServiceError(
            503,
            "TRANSCRIPT_CORRECTION_PROVIDER_UNAVAILABLE",
            "Transcript correction provider is unavailable.",
            retryable=True,
        )
    return TranscriptCorrectionServiceError(
        503,
        "TRANSCRIPT_CORRECTION_UNAVAILABLE",
        "Transcript correction admission failed.",
        retryable=True,
    )


def _admission_reason(outcome: str) -> str:
    return {
        "deadline-exceeded": "deadline-exceeded",
        "provider-unavailable": "provider-unavailable",
        "cancelled": "client-cancelled",
    }.get(outcome, "admission-failed")


def _cancellation_reason(reason: str | None) -> str:
    return {
        "client-requested": "client-cancelled",
        "deadline-exceeded": "deadline-exceeded",
        "provider-unavailable": "provider-unavailable",
    }.get(reason, "admission-failed")


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


def _cancellation_result_reason(admission: AgentAdmission) -> str | None:
    if admission.outcome == "cancellation-requested":
        return _cancellation_reason(admission.cancellation_reason)
    if admission.outcome in {"cancelled", "deadline-exceeded", "provider-unavailable"}:
        return _admission_reason(admission.outcome)
    return None


def _terminal_status_for_reason(reason: str) -> str:
    return "cancelled" if reason in {"client-cancelled", "service-closed"} else "complete"


__all__ = [
    "TranscriptCorrectionContainmentError",
    "TranscriptCorrectionJobView",
    "TranscriptCorrectionService",
    "TranscriptCorrectionServiceError",
    "TranscriptCorrectionTerminologyResolver",
    "TranscriptCorrectionTerminologyUnavailable",
]
