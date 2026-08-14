from __future__ import annotations

from dataclasses import dataclass
import re
import threading
import time
from typing import Protocol
from uuid import uuid4

from yap_server.auth import AuthenticatedPrincipal, PrincipalKey

from .student import StudentRequest
from .student_model import StudentQuestion
from .student_service import StudentJobView, StudentServiceError


_MAXIMUM_INFLIGHT_REQUESTS = 64
_MAXIMUM_RETAINED_TERMINAL_REQUESTS = 256
_TERMINAL_RETENTION_SECONDS = 15 * 60.0
_CLOSE_TIMEOUT_SECONDS = 62.0
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REQUEST_ID = re.compile(r"^student-question-[0-9a-f]{32}$")
_ACTIVE_STATUSES = frozenset({"queued", "running", "cancellation-requested"})
_TERMINAL_STATUSES = frozenset(
    {"complete", "evidence-unavailable", "cancelled", "failed"}
)


class StudentQuestionRunner(Protocol):
    def create_questions(
        self,
        request: StudentRequest,
        *,
        principal: AuthenticatedPrincipal,
        cancellation: threading.Event,
    ) -> StudentJobView: ...


class StudentQuestionContainmentError(RuntimeError):
    pass


class StudentQuestionServiceError(RuntimeError):
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
class StudentQuestionJobView:
    request_id: str
    status: str
    conversation_concept_id: str
    generation_sha256: str
    evidence_sha256: str | None = None
    questions: tuple[StudentQuestion, ...] = ()
    output_budget_exhausted: bool = False
    reason: str | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.request_id, str)
            or _REQUEST_ID.fullmatch(self.request_id) is None
        ):
            raise ValueError("student product request identity is invalid")
        if (
            not isinstance(self.conversation_concept_id, str)
            or not self.conversation_concept_id.startswith("meetings/")
            or not isinstance(self.generation_sha256, str)
            or _SHA256.fullmatch(self.generation_sha256) is None
            or not isinstance(self.questions, tuple)
            or any(not isinstance(item, StudentQuestion) for item in self.questions)
            or not isinstance(self.output_budget_exhausted, bool)
        ):
            raise ValueError("student product source identity is invalid")
        if self.evidence_sha256 is not None and (
            not isinstance(self.evidence_sha256, str)
            or _SHA256.fullmatch(self.evidence_sha256) is None
        ):
            raise ValueError("student product evidence identity is invalid")
        if self.status not in _ACTIVE_STATUSES | _TERMINAL_STATUSES:
            raise ValueError("student product status is invalid")
        if self.status == "complete":
            if (
                len(self.questions) != 1
                or self.evidence_sha256 is None
                or self.reason is not None
                or any(
                    support.evidence.concept_id != self.conversation_concept_id
                    for question in self.questions
                    for support in question.supports
                )
            ):
                raise ValueError("complete student product view is invalid")
        elif self.status in _ACTIVE_STATUSES:
            if (
                self.evidence_sha256 is not None
                or self.questions
                or self.output_budget_exhausted
                or self.reason is not None
            ):
                raise ValueError("active student product view is invalid")
        elif self.questions or not isinstance(self.reason, str) or not self.reason:
            raise ValueError("terminal student product view is invalid")

    def to_wire(self) -> dict[str, object]:
        value: dict[str, object] = {
            "schemaVersion": 1,
            "requestId": self.request_id,
            "status": self.status,
            "conversationConceptId": self.conversation_concept_id,
            "generationSha256": self.generation_sha256,
            "questions": [question.to_wire() for question in self.questions],
            "outputBudgetExhausted": self.output_budget_exhausted,
        }
        if self.evidence_sha256 is not None:
            value["evidenceSha256"] = self.evidence_sha256
        if self.reason is not None:
            value["reason"] = self.reason
        return value


@dataclass(slots=True)
class _QuestionJob:
    request_id: str
    owner: PrincipalKey
    principal: AuthenticatedPrincipal
    request: StudentRequest
    cancellation: threading.Event
    status: str = "queued"
    evidence_sha256: str | None = None
    questions: tuple[StudentQuestion, ...] = ()
    output_budget_exhausted: bool = False
    reason: str | None = None
    terminal_at: float | None = None

    def view(self) -> StudentQuestionJobView:
        return StudentQuestionJobView(
            request_id=self.request_id,
            status=self.status,
            conversation_concept_id=self.request.conversation_concept_id,
            generation_sha256=self.request.expected_generation_sha256,
            evidence_sha256=self.evidence_sha256,
            questions=self.questions,
            output_budget_exhausted=self.output_budget_exhausted,
            reason=self.reason,
        )


class StudentQuestionService:
    """Own asynchronous, principal-scoped product access to Student."""

    def __init__(self, *, student: StudentQuestionRunner) -> None:
        self._student = student
        self._lock = threading.RLock()
        self._jobs: dict[str, _QuestionJob] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._closed = False
        self._fenced_reason: str | None = None

    def submit(
        self,
        request: StudentRequest,
        *,
        principal: AuthenticatedPrincipal,
    ) -> StudentQuestionJobView:
        if not isinstance(request, StudentRequest):
            raise TypeError("student product request type is invalid")
        if not isinstance(principal, AuthenticatedPrincipal):
            raise TypeError("student product principal type is invalid")
        with self._lock:
            self._require_open_locked()
            self._prune_locked()
            if sum(job.terminal_at is None for job in self._jobs.values()) >= (
                _MAXIMUM_INFLIGHT_REQUESTS
            ):
                raise StudentQuestionServiceError(
                    429,
                    "STUDENT_QUESTION_CAPACITY",
                    "Learning-question capacity is temporarily unavailable.",
                    retryable=True,
                )
            request_id = f"student-question-{uuid4().hex}"
            if request_id in self._jobs:
                raise StudentQuestionContainmentError(
                    "student product request identity collided"
                )
            job = _QuestionJob(
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
    ) -> StudentQuestionJobView | None:
        if not isinstance(principal, AuthenticatedPrincipal):
            raise TypeError("student product principal type is invalid")
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
            raise TypeError("student product principal type is invalid")
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
                self._fenced_reason = "student product workers did not stop"
            if self._fenced_reason is not None:
                raise StudentQuestionContainmentError(self._fenced_reason)

    def _run(self, job: _QuestionJob) -> None:
        with self._lock:
            if job.status == "queued":
                job.status = "running"
        try:
            result = self._student.create_questions(
                job.request,
                principal=job.principal,
                cancellation=job.cancellation,
            )
            if not isinstance(result, StudentJobView):
                raise StudentQuestionContainmentError(
                    "student product result type is invalid"
                )
            if (
                result.status not in _TERMINAL_STATUSES
                or result.conversation_concept_id != job.request.conversation_concept_id
                or result.generation_sha256 != job.request.expected_generation_sha256
            ):
                raise StudentQuestionContainmentError(
                    "student product result identity is invalid"
                )
            projected = StudentQuestionJobView(
                request_id=job.request_id,
                status=result.status,
                conversation_concept_id=result.conversation_concept_id,
                generation_sha256=result.generation_sha256,
                evidence_sha256=result.evidence_sha256,
                questions=result.questions,
                output_budget_exhausted=result.output_budget_exhausted,
                reason=result.reason,
            )
            with self._lock:
                job.status = projected.status
                job.evidence_sha256 = projected.evidence_sha256
                job.questions = projected.questions
                job.output_budget_exhausted = projected.output_budget_exhausted
                job.reason = projected.reason
                job.terminal_at = time.monotonic()
        except StudentServiceError as error:
            with self._lock:
                job.status = "failed"
                job.evidence_sha256 = None
                job.questions = ()
                job.output_budget_exhausted = False
                job.reason = _student_service_reason(error)
                job.terminal_at = time.monotonic()
        except BaseException:
            with self._lock:
                job.status = "failed"
                job.evidence_sha256 = None
                job.questions = ()
                job.output_budget_exhausted = False
                job.reason = "service-unavailable"
                job.terminal_at = time.monotonic()
                self._fenced_reason = "student product worker containment failed"
        finally:
            with self._lock:
                self._threads.pop(job.request_id, None)

    def _require_open_locked(self) -> None:
        if self._closed:
            raise StudentQuestionContainmentError("student product service is closed")
        if self._fenced_reason is not None:
            raise StudentQuestionContainmentError(self._fenced_reason)

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


def _student_service_reason(error: StudentServiceError) -> str:
    return {
        "STUDENT_CAPACITY": "capacity-unavailable",
        "STUDENT_DEADLINE": "deadline-exceeded",
    }.get(error.code, "service-unavailable")


__all__ = [
    "StudentQuestionContainmentError",
    "StudentQuestionJobView",
    "StudentQuestionRunner",
    "StudentQuestionService",
    "StudentQuestionServiceError",
]
