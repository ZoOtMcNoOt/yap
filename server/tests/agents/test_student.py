from __future__ import annotations

from dataclasses import replace
import json
import threading
import time
import unittest

from yap_server.agents import (
    AgentAdmission,
    AgentAdmissionTicket,
    AgentPurpose,
    AgentRole,
    ExecutionRoute,
    SchedulingClass,
)
from yap_server.agents.student import (
    StudentEvidence,
    StudentEvidenceItem,
    StudentRequest,
    student_work_sha256,
)
from yap_server.agents.student_result_audit import (
    PostgresStudentResultAuditor,
    StudentRuntimeAuditIdentity,
)
from yap_server.agents.student_model import (
    StudentQuestion,
    StudentQuestionModel,
)
from yap_server.agents.student_service import StudentService
from yap_server.auth import AuthenticatedPrincipal
from yap_server.knowledge.knowledge_tool_contract import KnowledgeToolCancelled


def _principal(subject: str = "alice") -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        tenant_id="tenant-a",
        subject_id=subject,
        client_id="desktop",
        scopes=frozenset(),
    )


def _request() -> StudentRequest:
    return StudentRequest(
        conversation_concept_id="meetings/job-1",
        expected_generation_sha256="a" * 64,
        focus="crash safety",
    )


def _item() -> StudentEvidenceItem:
    text = "The reviewed meeting records crash safety."
    return StudentEvidenceItem(
        concept_id="meetings/job-1",
        source_revision="b" * 64,
        content_sha256="c" * 64,
        char_start=0,
        char_end=len(text),
        text=text,
    )


def _evidence(*, visible: bool = True) -> StudentEvidence:
    return StudentEvidence.create(
        generation_sha256="a" * 64,
        permission_hash="d" * 64,
        authorization_hash="e" * 64,
        conversation_concept_id="meetings/job-1",
        items=(_item(),) if visible else (),
        output_budget_exhausted=False,
    )


def _question() -> StudentQuestion:
    return StudentQuestion(
        "What crash-safety property does the reviewed meeting record?",
        (_item(),),
    )


def _runtime_identity() -> StudentRuntimeAuditIdentity:
    return StudentRuntimeAuditIdentity(
        candidate_id="qwen-rapid",
        model="nvidia/Qwen3.6-35B-A3B-NVFP4",
        model_revision="f" * 40,
        runtime_id="qwen-vllm",
        profile_sha256="1" * 64,
        candidate_lock_sha256="2" * 64,
    )


class _Transport:
    def __init__(self, content: object) -> None:
        self.content = content
        self.payloads: list[dict[str, object]] = []

    def request(self, payload, cancellation, dispatched=None):
        del dispatched
        if cancellation.is_set():
            raise AssertionError("student model was called after cancellation")
        self.payloads.append(payload)
        content = self.content
        if not isinstance(content, str):
            content = json.dumps(content, separators=(",", ":"))
        return {"choices": [{"message": {"content": content}}]}


class _Reader:
    def __init__(
        self,
        evidence: StudentEvidence,
        *,
        error: BaseException | None = None,
    ) -> None:
        self.evidence = evidence
        self.error = error
        self.calls: list[tuple[StudentRequest, str]] = []

    def read(self, request, *, principal, cancellation):
        self.calls.append((request, principal.subject_id))
        if cancellation.is_set():
            raise KnowledgeToolCancelled("cancelled")
        if self.error is not None:
            raise self.error
        return self.evidence


class _Generator:
    def __init__(
        self,
        *,
        questions: tuple[StudentQuestion, ...] = (_question(),),
        error: BaseException | None = None,
    ) -> None:
        self.questions = questions
        self.error = error
        self.calls: list[tuple[StudentRequest, StudentEvidence]] = []

    def generate(self, request, evidence, *, cancellation):
        self.calls.append((request, evidence))
        if cancellation.is_set():
            raise KnowledgeToolCancelled("cancelled")
        if self.error is not None:
            raise self.error
        return self.questions


class _BlockingGenerator:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.stopped = threading.Event()

    def generate(self, request, evidence, *, cancellation):
        del request, evidence
        self.started.set()
        cancellation.wait(2)
        self.stopped.set()
        raise KnowledgeToolCancelled("cancelled")


class _Auditor:
    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    def record(self, **value) -> None:
        self.records.append(value)


class _Admission:
    def __init__(self, *, queued: bool = False) -> None:
        self.outcome = "queued" if queued else "admitted"
        self.calls: list[tuple[str, str]] = []
        self.submission: dict[str, object] | None = None
        self.route = ExecutionRoute.RAPID_AUTOMATION
        self.generation = 7

    def new_ticket(self):
        self.calls.append(("new-ticket", "student-1"))
        return AgentAdmissionTicket("student-1", "1" * 64)

    def submit(self, ticket, **kwargs):
        self.calls.append(("submit", ticket.request_id))
        self.submission = kwargs
        return self._response(ticket)

    def status(self, ticket):
        self.calls.append(("status", ticket.request_id))
        return self._response(ticket)

    def admit(self) -> None:
        self.outcome = "admitted"

    def cancel(self, ticket):
        self.calls.append(("cancel", ticket.request_id))
        if self.outcome in {"completed", "cancelled"}:
            return AgentAdmission(ticket, self.outcome)
        self.outcome = "cancellation-requested"
        return AgentAdmission(
            ticket,
            self.outcome,
            cancellation_reason="client-requested",
        )

    def acknowledge_cancellation(self, ticket):
        self.calls.append(("acknowledge-cancellation", ticket.request_id))
        self.outcome = "cancelled"
        return AgentAdmission(ticket, self.outcome)

    def complete(self, ticket):
        self.calls.append(("complete", ticket.request_id))
        self.outcome = "completed"
        return AgentAdmission(ticket, self.outcome)

    def _response(self, ticket):
        if self.outcome == "admitted":
            return AgentAdmission(
                ticket,
                "admitted",
                route=self.route,
                provider_generation=self.generation,
                queue_duration_ms=0,
            )
        return AgentAdmission(ticket, self.outcome)


class StudentTests(unittest.TestCase):
    def test_result_auditor_rejects_success_without_questions(self) -> None:
        auditor = PostgresStudentResultAuditor(
            lambda: (_ for _ in ()).throw(AssertionError("database opened")),
            _runtime_identity(),
        )
        with self.assertRaisesRegex(ValueError, "result audit is invalid"):
            auditor.record(
                principal=_principal(),
                request_id="student-1",
                request=_request(),
                provider_generation=7,
                status="complete",
                reason=None,
                evidence=_evidence(),
                question_count=0,
                duration_milliseconds=1,
            )

    def test_request_requires_exact_meeting_generation_and_focus(self) -> None:
        self.assertEqual(
            StudentRequest.from_wire(
                {
                    "schemaVersion": 1,
                    "conversationConceptId": "meetings/job-1",
                    "expectedGenerationSha256": "a" * 64,
                    "focus": "crash safety",
                }
            ),
            _request(),
        )
        invalid = (
            {
                "schemaVersion": 1,
                "conversationConceptId": "projects/voiceos",
                "expectedGenerationSha256": "a" * 64,
                "focus": "crash safety",
            },
            {
                "schemaVersion": 1,
                "conversationConceptId": "meetings/job-1",
                "expectedGenerationSha256": "bad",
                "focus": "crash safety",
            },
            {
                "schemaVersion": 1,
                "conversationConceptId": "meetings/job-1",
                "expectedGenerationSha256": False,
                "focus": "crash safety",
            },
            {
                "schemaVersion": 1,
                "conversationConceptId": "meetings/job-1",
                "expectedGenerationSha256": "a" * 64,
                "focus": "crash safety",
                "transcript": "caller supplied",
            },
            {
                "schemaVersion": 1,
                "conversationConceptId": "meetings/job\\1",
                "expectedGenerationSha256": "a" * 64,
                "focus": "crash safety",
            },
        )
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                StudentRequest.from_wire(value)

    def test_model_returns_only_questions_with_exact_visible_citations(self) -> None:
        content = {
            "questions": [
                {
                    "question": "What crash-safety property was reviewed?",
                    "sourceCitations": [_item().citation_wire()],
                }
            ]
        }
        transport = _Transport(content)
        questions = StudentQuestionModel(
            transport=transport,
            model="rapid-model",
            maximum_output_tokens=256,
        ).generate(
            _request(),
            _evidence(),
            cancellation=threading.Event(),
        )

        self.assertEqual(len(questions), 1)
        self.assertEqual(questions[0].citations, (_item(),))
        payload = transport.payloads[0]
        self.assertEqual(payload["max_tokens"], 256)
        prompt = payload["messages"][1]["content"]
        self.assertIn('"focus":"crash safety"', prompt)
        self.assertIn(
            '"evidenceSha256":"' + _evidence().evidence_sha256 + '"',
            prompt,
        )

    def test_model_rejects_hidden_or_duplicate_evidence_claims(self) -> None:
        hidden = _item().citation_wire()
        hidden["conceptId"] = "meetings/hidden"
        responses = (
            {
                "questions": [
                    {
                        "question": "What hidden fact exists?",
                        "sourceCitations": [hidden],
                    }
                ]
            },
            {
                "questions": [
                    {
                        "question": "Summarize the reviewed fact.",
                        "sourceCitations": [_item().citation_wire()],
                    }
                ]
            },
            {
                "questions": [
                    {
                        "question": "What was reviewed?",
                        "sourceCitations": [_item().citation_wire()],
                    },
                    {
                        "question": "What was reviewed?",
                        "sourceCitations": [_item().citation_wire()],
                    },
                ]
            },
        )
        for response in responses:
            with self.subTest(response=response), self.assertRaises(ValueError):
                StudentQuestionModel(
                    transport=_Transport(response),
                    model="rapid-model",
                    maximum_output_tokens=256,
                ).generate(
                    _request(),
                    _evidence(),
                    cancellation=threading.Event(),
                )

        with self.assertRaisesRegex(ValueError, "source identity"):
            replace(_item(), source_revision="not-a-source-sha")

    def test_empty_or_hidden_evidence_never_submits_or_calls_the_model(self) -> None:
        admission = _Admission()
        generator = _Generator()
        auditor = _Auditor()
        view = StudentService(
            admission=admission,
            evidence_reader=_Reader(_evidence(visible=False)),
            question_generator=generator,
            result_auditor=auditor,
        ).create_questions(
            _request(),
            principal=_principal(),
            cancellation=threading.Event(),
        )

        self.assertEqual(view.status, "evidence-unavailable")
        self.assertEqual(view.questions, ())
        self.assertEqual(generator.calls, [])
        self.assertNotIn("submit", [operation for operation, _ in admission.calls])
        self.assertEqual(auditor.records[0]["request_id"], "student-1")
        self.assertIsNone(auditor.records[0]["provider_generation"])
        self.assertEqual(auditor.records[0]["status"], "evidence-unavailable")
        self.assertEqual(auditor.records[0]["reason"], "evidence-unavailable")

    def test_queued_work_uses_exact_student_route_and_completes_once(self) -> None:
        admission = _Admission(queued=True)
        generator = _Generator()
        service = StudentService(
            admission=admission,
            evidence_reader=_Reader(_evidence()),
            question_generator=generator,
            result_auditor=_Auditor(),
        )
        outcomes: list[object] = []
        worker = threading.Thread(
            target=lambda: outcomes.append(
                service.create_questions(
                    _request(),
                    principal=_principal(),
                    cancellation=threading.Event(),
                )
            )
        )
        worker.start()
        _wait_for(lambda: admission.submission is not None)
        self.assertEqual(generator.calls, [])
        admission.admit()
        worker.join(2)

        self.assertFalse(worker.is_alive())
        view = outcomes[0]
        self.assertEqual(view.status, "complete")
        self.assertEqual(view.questions, (_question(),))
        assert admission.submission is not None
        work = admission.submission["work"]
        self.assertEqual(work.role, AgentRole.STUDENT)
        self.assertEqual(work.purpose, AgentPurpose.LEARNING_QUESTIONS)
        self.assertEqual(work.route, ExecutionRoute.RAPID_AUTOMATION)
        self.assertEqual(work.scheduling_class, SchedulingClass.BACKGROUND_LLM)
        self.assertEqual(
            admission.submission["source_sha256"],
            student_work_sha256(_request(), _evidence()),
        )
        self.assertEqual(
            [operation for operation, _ in admission.calls].count("complete"),
            1,
        )

    def test_capacity_rejection_is_audited_without_a_provider_lease(self) -> None:
        admission = _Admission()
        admission.outcome = "owner-queue-full"
        auditor = _Auditor()
        service = StudentService(
            admission=admission,
            evidence_reader=_Reader(_evidence()),
            question_generator=_Generator(),
            result_auditor=auditor,
        )

        with self.assertRaisesRegex(RuntimeError, "capacity"):
            service.create_questions(
                _request(),
                principal=_principal(),
                cancellation=threading.Event(),
            )

        self.assertEqual(len(auditor.records), 1)
        self.assertEqual(auditor.records[0]["status"], "failed")
        self.assertEqual(auditor.records[0]["reason"], "capacity-unavailable")
        self.assertIsNone(auditor.records[0]["provider_generation"])
        self.assertEqual(admission.calls[-1][0], "submit")

    def test_invalid_output_completes_lease_without_publishing_questions(self) -> None:
        admission = _Admission()
        auditor = _Auditor()
        view = StudentService(
            admission=admission,
            evidence_reader=_Reader(_evidence()),
            question_generator=_Generator(error=ValueError("private output")),
            result_auditor=auditor,
        ).create_questions(
            _request(),
            principal=_principal(),
            cancellation=threading.Event(),
        )

        self.assertEqual(view.status, "failed")
        self.assertEqual(view.reason, "invalid-output")
        self.assertEqual(view.questions, ())
        self.assertNotIn("private output", repr(view.to_wire()))
        self.assertEqual(admission.calls[-1][0], "complete")
        self.assertEqual(auditor.records[0]["status"], "failed")
        self.assertEqual(auditor.records[0]["question_count"], 0)

    def test_service_rejects_reader_evidence_that_differs_from_request(self) -> None:
        admission = _Admission()
        generator = _Generator()
        invalid = replace(_evidence(), generation_sha256="9" * 64)

        view = StudentService(
            admission=admission,
            evidence_reader=_Reader(invalid),
            question_generator=generator,
            result_auditor=_Auditor(),
        ).create_questions(
            _request(),
            principal=_principal(),
            cancellation=threading.Event(),
        )

        self.assertEqual(view.status, "failed")
        self.assertEqual(view.reason, "stale-or-invalid-generation")
        self.assertEqual(generator.calls, [])
        self.assertNotIn("submit", [operation for operation, _ in admission.calls])

    def test_service_rejects_generator_citation_outside_frozen_evidence(self) -> None:
        admission = _Admission()
        hidden = replace(_item(), concept_id="meetings/hidden")

        view = StudentService(
            admission=admission,
            evidence_reader=_Reader(_evidence()),
            question_generator=_Generator(
                questions=(StudentQuestion("What hidden fact exists?", (hidden,)),)
            ),
            result_auditor=_Auditor(),
        ).create_questions(
            _request(),
            principal=_principal(),
            cancellation=threading.Event(),
        )

        self.assertEqual(view.status, "failed")
        self.assertEqual(view.reason, "invalid-output")
        self.assertEqual(view.questions, ())
        self.assertEqual(admission.calls[-1][0], "complete")

    def test_active_cancellation_stops_model_and_acknowledges_lease(self) -> None:
        admission = _Admission()
        generator = _BlockingGenerator()
        cancellation = threading.Event()
        outcomes: list[object] = []
        auditor = _Auditor()
        service = StudentService(
            admission=admission,
            evidence_reader=_Reader(_evidence()),
            question_generator=generator,
            result_auditor=auditor,
        )
        worker = threading.Thread(
            target=lambda: outcomes.append(
                service.create_questions(
                    _request(),
                    principal=_principal(),
                    cancellation=cancellation,
                )
            )
        )
        worker.start()
        self.assertTrue(generator.started.wait(1))
        cancellation.set()
        worker.join(2)

        self.assertFalse(worker.is_alive())
        self.assertTrue(generator.stopped.is_set())
        self.assertEqual(outcomes[0].status, "cancelled")
        self.assertEqual(outcomes[0].questions, ())
        self.assertEqual(admission.outcome, "cancelled")
        self.assertEqual(auditor.records[0]["status"], "cancelled")
        self.assertEqual(auditor.records[0]["provider_generation"], 7)

    def test_wrong_route_is_contained_before_failure(self) -> None:
        admission = _Admission()
        admission.route = ExecutionRoute.COMPLEX_ORCHESTRATION
        with self.assertRaisesRegex(RuntimeError, "lease identity"):
            StudentService(
                admission=admission,
                evidence_reader=_Reader(_evidence()),
                question_generator=_Generator(),
                result_auditor=_Auditor(),
            ).create_questions(
                _request(),
                principal=_principal(),
                cancellation=threading.Event(),
            )
        self.assertEqual(
            [operation for operation, _ in admission.calls[-2:]],
            ["cancel", "acknowledge-cancellation"],
        )

    def test_uncontained_model_transport_contains_the_lease_and_fails_closed(
        self,
    ) -> None:
        admission = _Admission()
        with self.assertRaisesRegex(
            RuntimeError,
            "model transport was not contained",
        ):
            StudentService(
                admission=admission,
                evidence_reader=_Reader(_evidence()),
                question_generator=_Generator(error=RuntimeError("socket survived")),
                result_auditor=_Auditor(),
            ).create_questions(
                _request(),
                principal=_principal(),
                cancellation=threading.Event(),
            )
        self.assertEqual(
            [operation for operation, _ in admission.calls[-2:]],
            ["cancel", "acknowledge-cancellation"],
        )


def _wait_for(predicate) -> None:
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition was not reached")


if __name__ == "__main__":
    unittest.main()
