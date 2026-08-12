from __future__ import annotations

from dataclasses import dataclass
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
from yap_server.knowledge.agent_reasoning_routes import ReasoningRetryableError
from yap_server.knowledge.knowledge_tool_contract import (
    KnowledgeToolCancellationFailed,
    KnowledgeToolCancelled,
    KnowledgeToolTimedOut,
)

from .student import (
    StudentEvidence,
    StudentRequest,
    student_work_sha256,
    validate_student_evidence,
)
from .student_model import StudentQuestion, validate_student_questions


_STUDENT_WORK = AgentWorkSpec(
    role=AgentRole.STUDENT,
    purpose=AgentPurpose.LEARNING_QUESTIONS,
    route=ExecutionRoute.RAPID_AUTOMATION,
    scheduling_class=SchedulingClass.BACKGROUND_LLM,
)
_DEADLINE_SECONDS = 60.0
_ADMISSION_POLL_SECONDS = 0.05


class StudentAdmission(Protocol):
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


class StudentEvidenceReader(Protocol):
    def read(
        self,
        request: StudentRequest,
        *,
        principal: AuthenticatedPrincipal,
        cancellation: threading.Event,
    ) -> StudentEvidence: ...


class StudentQuestionGenerator(Protocol):
    def generate(
        self,
        request: StudentRequest,
        evidence: StudentEvidence,
        *,
        cancellation: threading.Event,
    ) -> tuple[StudentQuestion, ...]: ...


class StudentResultAuditor(Protocol):
    def record(
        self,
        *,
        principal: AuthenticatedPrincipal,
        request_id: str,
        request: StudentRequest,
        provider_generation: int | None,
        status: str,
        reason: str | None,
        evidence: StudentEvidence | None,
        question_count: int,
        duration_milliseconds: int,
    ) -> None: ...


class StudentServiceError(RuntimeError):
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


class StudentContainmentError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class StudentJobView:
    request_id: str
    status: str
    conversation_concept_id: str
    generation_sha256: str
    evidence_sha256: str | None = None
    questions: tuple[StudentQuestion, ...] = ()
    output_budget_exhausted: bool = False
    reason: str | None = None

    def to_wire(self) -> dict[str, object]:
        value: dict[str, object] = {
            "schemaVersion": 3,
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


class StudentService:
    """Create source-cited questions under one exact rapid-route lease."""

    def __init__(
        self,
        *,
        admission: StudentAdmission,
        evidence_reader: StudentEvidenceReader,
        question_generator: StudentQuestionGenerator,
        result_auditor: StudentResultAuditor,
    ) -> None:
        self._admission = admission
        self._evidence_reader = evidence_reader
        self._question_generator = question_generator
        self._result_auditor = result_auditor

    def create_questions(
        self,
        request: StudentRequest,
        *,
        principal: AuthenticatedPrincipal,
        cancellation: threading.Event,
    ) -> StudentJobView:
        if not isinstance(request, StudentRequest):
            raise TypeError("student request type is invalid")
        if not isinstance(principal, AuthenticatedPrincipal):
            raise TypeError("student principal type is invalid")
        if not isinstance(cancellation, threading.Event):
            raise TypeError("student cancellation type is invalid")

        started = time.monotonic()
        deadline = started + _DEADLINE_SECONDS
        ticket = self._admission.new_ticket()
        worker_cancellation = threading.Event()
        forwarding_stopped = threading.Event()
        forwarder = threading.Thread(
            target=_forward_cancellation,
            args=(cancellation, worker_cancellation, forwarding_stopped),
            name=f"student-cancellation-{ticket.request_id}",
            daemon=False,
        )
        deadline_timer = threading.Timer(
            max(0.0, deadline - time.monotonic()),
            worker_cancellation.set,
        )
        deadline_timer.name = f"student-deadline-{ticket.request_id}"
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
                validate_student_evidence(request, evidence)
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
                raise StudentContainmentError(
                    "student evidence cancellation was not contained"
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
                    status="evidence-unavailable",
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
                    evidence=evidence,
                    reason=_cancellation_reason(cancellation, deadline),
                )
            if not evidence.items:
                return self._result(
                    ticket,
                    request,
                    principal=principal,
                    started=started,
                    status="evidence-unavailable",
                    evidence=evidence,
                    reason="evidence-unavailable",
                )

            try:
                admission = self._admission.submit(
                    ticket,
                    principal=principal,
                    work=_STUDENT_WORK,
                    source_sha256=student_work_sha256(request, evidence),
                    remaining_deadline_ms=_remaining_deadline_ms(deadline),
                )
                ticket_open = admission.outcome in {"queued", "admitted"}
            except BaseException:
                self._contain_ticket(ticket)
                raise
            if admission.outcome not in {"queued", "admitted"}:
                self._result(
                    ticket,
                    request,
                    principal=principal,
                    started=started,
                    status="failed",
                    evidence=evidence,
                    reason=_admission_reason(admission.outcome),
                )
                raise _submit_error(admission.outcome)

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
            if admission.outcome == "cancellation-requested":
                view = self._acknowledge_requested_cancellation(
                    ticket,
                    request,
                    evidence,
                    principal,
                    started,
                    admission,
                    provider_generation,
                )
                ticket_open = False
                return view
            if admission.outcome != "admitted":
                ticket_open = False
                return self._result(
                    ticket,
                    request,
                    principal=principal,
                    started=started,
                    status="failed",
                    evidence=evidence,
                    reason=_admission_reason(admission.outcome),
                    provider_generation=provider_generation,
                )
            if (
                admission.route != ExecutionRoute.RAPID_AUTOMATION
                or isinstance(admission.provider_generation, bool)
                or not isinstance(admission.provider_generation, int)
                or admission.provider_generation < 1
            ):
                raise StudentContainmentError(
                    "student admission lease identity is invalid"
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

            questions: tuple[StudentQuestion, ...] = ()
            failure_reason: str | None = None
            try:
                questions = self._question_generator.generate(
                    request,
                    evidence,
                    cancellation=worker_cancellation,
                )
                questions = validate_student_questions(questions, evidence)
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
                raise StudentContainmentError(
                    "student model transport was not contained"
                ) from error

            current = self._admission.status(ticket)
            if current.outcome == "cancellation-requested":
                view = self._acknowledge_requested_cancellation(
                    ticket,
                    request,
                    evidence,
                    principal,
                    started,
                    current,
                    provider_generation,
                )
                ticket_open = False
                return view
            if (
                current.outcome != "admitted"
                or current.route != ExecutionRoute.RAPID_AUTOMATION
                or current.provider_generation != provider_generation
            ):
                raise StudentContainmentError(
                    "student admission changed before completion"
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
            ticket_open = False
            if completed.outcome != "completed":
                raise StudentContainmentError(
                    "student admission lease did not complete"
                )
            if failure_reason is not None:
                return self._result(
                    ticket,
                    request,
                    principal=principal,
                    started=started,
                    status="failed",
                    evidence=evidence,
                    reason=failure_reason,
                    provider_generation=provider_generation,
                )
            if not questions:
                raise StudentContainmentError(
                    "student generator returned no validated questions"
                )
            return self._result(
                ticket,
                request,
                principal=principal,
                started=started,
                status="complete",
                evidence=evidence,
                questions=questions,
                provider_generation=provider_generation,
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
        request: StudentRequest,
        *,
        principal: AuthenticatedPrincipal,
        started: float,
        status: str,
        evidence: StudentEvidence | None = None,
        questions: tuple[StudentQuestion, ...] = (),
        reason: str | None = None,
        provider_generation: int | None = None,
    ) -> StudentJobView:
        view = StudentJobView(
            request_id=ticket.request_id,
            status=status,
            conversation_concept_id=request.conversation_concept_id,
            generation_sha256=(
                evidence.generation_sha256
                if evidence is not None
                else request.expected_generation_sha256
            ),
            evidence_sha256=(
                evidence.evidence_sha256 if evidence is not None else None
            ),
            questions=questions,
            output_budget_exhausted=(
                evidence.output_budget_exhausted
                if evidence is not None
                else False
            ),
            reason=reason,
        )
        self._result_auditor.record(
            principal=principal,
            request_id=ticket.request_id,
            request=request,
            provider_generation=provider_generation,
            status=status,
            reason=reason,
            evidence=evidence,
            question_count=len(questions),
            duration_milliseconds=max(
                0, round((time.monotonic() - started) * 1_000)
            ),
        )
        return view

    def _cancelled_view(
        self,
        ticket: AgentAdmissionTicket,
        request: StudentRequest,
        evidence: StudentEvidence,
        principal: AuthenticatedPrincipal,
        started: float,
        reason: str,
        provider_generation: int | None,
    ) -> StudentJobView:
        cancelled = self._admission.cancel(ticket)
        expected = _expected_cancellation_outcome(cancelled)
        if expected is None:
            raise StudentContainmentError("student cancellation was not admitted")
        terminal = self._admission.acknowledge_cancellation(ticket)
        if terminal.outcome != expected:
            raise StudentContainmentError(
                "student cancellation was not acknowledged"
            )
        return self._result(
            ticket,
            request,
            principal=principal,
            started=started,
            status="cancelled",
            evidence=evidence,
            reason=reason,
            provider_generation=provider_generation,
        )

    def _acknowledge_requested_cancellation(
        self,
        ticket: AgentAdmissionTicket,
        request: StudentRequest,
        evidence: StudentEvidence,
        principal: AuthenticatedPrincipal,
        started: float,
        admission: AgentAdmission,
        provider_generation: int | None,
    ) -> StudentJobView:
        expected = _expected_cancellation_outcome(admission)
        if expected is None:
            raise StudentContainmentError(
                "student cancellation response is invalid"
            )
        terminal = self._admission.acknowledge_cancellation(ticket)
        if terminal.outcome != expected:
            raise StudentContainmentError(
                "student cancellation was not acknowledged"
            )
        return self._result(
            ticket,
            request,
            principal=principal,
            started=started,
            status="cancelled",
            evidence=evidence,
            reason=_admission_reason(expected),
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
                    "not-found-or-unauthorized",
                }
        except BaseException:
            contained = False
        if not contained:
            raise StudentContainmentError("student admission could not be contained")


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
        raise StudentServiceError(
            504,
            "STUDENT_DEADLINE",
            "Learning questions could not start before their deadline.",
            retryable=True,
        )
    return remaining


def _submit_error(outcome: str) -> StudentServiceError:
    if outcome in {"owner-queue-full", "queue-full"}:
        return StudentServiceError(
            429,
            "STUDENT_CAPACITY",
            "Learning-question capacity is temporarily unavailable.",
            retryable=True,
        )
    return StudentServiceError(
        503,
        "STUDENT_UNAVAILABLE",
        "Learning-question admission is temporarily unavailable.",
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
        "owner-queue-full": "capacity-unavailable",
        "queue-full": "capacity-unavailable",
    }.get(outcome, "admission-failed")


def _cancellation_reason(cancellation: threading.Event, deadline: float) -> str:
    if cancellation.is_set():
        return "client-cancelled"
    if time.monotonic() >= deadline:
        return "deadline-exceeded"
    return "cancelled"


__all__ = [
    "StudentContainmentError",
    "StudentJobView",
    "StudentService",
    "StudentServiceError",
]
