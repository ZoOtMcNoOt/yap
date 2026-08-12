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
    StudentQuestionSupport,
    student_question_text,
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
        topic="crash safety",
    )


def _item(
    text: str = "The reviewed meeting records crash safety.",
) -> StudentEvidenceItem:
    return StudentEvidenceItem(
        concept_id="meetings/job-1",
        source_revision="b" * 64,
        content_sha256="c" * 64,
        char_start=0,
        char_end=len(text),
        text=text,
    )


def _evidence(
    *,
    visible: bool = True,
    item: StudentEvidenceItem | None = None,
) -> StudentEvidence:
    return StudentEvidence.create(
        generation_sha256="a" * 64,
        permission_hash="d" * 64,
        authorization_hash="e" * 64,
        conversation_concept_id="meetings/job-1",
        items=((item or _item()),) if visible else (),
        output_budget_exhausted=False,
    )


def _question() -> StudentQuestion:
    subject = "crash safety"
    return StudentQuestion(
        subject,
        student_question_text(subject),
        (StudentQuestionSupport(_item(), "crash safety"),),
    )


def _model_response(
    subject: str = "crash safety",
    quote: str = "crash safety",
    *,
    evidence_index: object = 0,
) -> dict[str, object]:
    return {
        "questions": [
            {
                "sourceSubject": subject,
                "sourceEvidenceIndex": evidence_index,
                "supportQuote": quote,
            }
        ]
    }


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
    def test_result_auditor_requires_exactly_one_successful_question(self) -> None:
        auditor = PostgresStudentResultAuditor(
            lambda: (_ for _ in ()).throw(AssertionError("database opened")),
            _runtime_identity(),
        )
        for count in (0, 2):
            with self.subTest(count=count), self.assertRaisesRegex(
                ValueError,
                "result audit is invalid",
            ):
                auditor.record(
                    principal=_principal(),
                    request_id="student-1",
                    request=_request(),
                    provider_generation=7,
                    status="complete",
                    reason=None,
                    evidence=_evidence(),
                    question_count=count,
                    duration_milliseconds=1,
                )

    def test_request_requires_exact_meeting_generation_and_topic(self) -> None:
        self.assertEqual(
            StudentRequest.from_wire(
                {
                    "schemaVersion": 2,
                    "conversationConceptId": "meetings/job-1",
                    "expectedGenerationSha256": "a" * 64,
                    "topic": "crash safety",
                }
            ),
            _request(),
        )
        invalid = (
            {
                "schemaVersion": 1,
                "conversationConceptId": "meetings/job-1",
                "expectedGenerationSha256": "a" * 64,
                "topic": "crash safety",
            },
            {
                "schemaVersion": 2,
                "conversationConceptId": "projects/voiceos",
                "expectedGenerationSha256": "a" * 64,
                "topic": "crash safety",
            },
            {
                "schemaVersion": 2,
                "conversationConceptId": "meetings/job-1",
                "expectedGenerationSha256": "bad",
                "topic": "crash safety",
            },
            {
                "schemaVersion": 2,
                "conversationConceptId": "meetings/job-1",
                "expectedGenerationSha256": False,
                "topic": "crash safety",
            },
            {
                "schemaVersion": 2,
                "conversationConceptId": "meetings/job-1",
                "expectedGenerationSha256": "a" * 64,
                "topic": "crash safety",
                "transcript": "caller supplied",
            },
            {
                "schemaVersion": 2,
                "conversationConceptId": "meetings/job\\1",
                "expectedGenerationSha256": "a" * 64,
                "topic": "crash safety",
            },
            {
                "schemaVersion": 2,
                "conversationConceptId": "meetings/job-1",
                "expectedGenerationSha256": "a" * 64,
                "topic": "What should be invented?",
            },
        )
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                StudentRequest.from_wire(value)

    def test_model_returns_only_questions_with_exact_visible_citations(self) -> None:
        transport = _Transport(_model_response())
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
        self.assertEqual(
            questions[0].supports,
            (StudentQuestionSupport(_item(), "crash safety"),),
        )
        payload = transport.payloads[0]
        self.assertEqual(payload["max_tokens"], 256)
        prompt = payload["messages"][1]["content"]
        self.assertIn('"topic":"crash safety"', prompt)
        self.assertIn(
            '"evidenceSha256":"' + _evidence().evidence_sha256 + '"',
            prompt,
        )
        prompt_value = json.loads(prompt)
        self.assertEqual(
            prompt_value["visibleEvidence"],
            [
                {
                    "sourceEvidenceIndex": 0,
                    "text": _item().text,
                }
            ],
        )
        self.assertIn(
            "exactly one concise source subject copied byte-for-byte",
            payload["messages"][0]["content"],
        )
        self.assertIn(
            "Never copy topic text into sourceSubject unless those identical bytes",
            payload["messages"][0]["content"],
        )
        self.assertIn(
            "sourceSubject is an exact contiguous substring of supportQuote",
            payload["messages"][0]["content"],
        )
        schema = payload["response_format"]["json_schema"]["schema"]
        self.assertEqual(schema["properties"]["questions"]["maxItems"], 1)
        self.assertEqual(
            set(schema["properties"]["questions"]["items"]["properties"]),
            {"sourceSubject", "sourceEvidenceIndex", "supportQuote"},
        )

    def test_model_rejects_invalid_evidence_selection_or_multiple_questions(self) -> None:
        responses = (
            _model_response(evidence_index=-1),
            _model_response(evidence_index=1),
            _model_response(evidence_index=True),
            {
                "questions": [
                    _model_response()["questions"][0],
                    _model_response("reviewed meeting", "reviewed meeting")[
                        "questions"
                    ][0],
                ]
            },
            {
                "questions": [
                    {
                        **_model_response()["questions"][0],
                        "sourceCitation": _item().citation_wire(),
                    }
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

    def test_model_rejects_subject_not_exactly_supported(self) -> None:
        audit = _item("Alice approved TAVI. Bob approved CABG.")
        decimal = _item("The medication dose was 0,5 mg on 08/31/2026.")
        cases = (
            (audit, "Alice approved CABG", audit.text),
            (audit, "Was Bob approved by Alice", audit.text),
            (decimal, "5,0 mg", decimal.text),
            (decimal, "31/08/2026", decimal.text),
            (decimal, "medication dose?", decimal.text),
            (_item("A discontinued device."), "continued", "A discontinued device."),
            (_item("The drug was discontinued."), "continued", "continued"),
            (_item("The patient can't drive."), "can", "can"),
            (_item("Dose 0,5 mg."), "5 mg", "5 mg"),
            (_item("Date 08/31/2026 today."), "31/2026", "31/2026"),
            (_item("$100 was approved."), "100", "100"),
            (_item("Dose 5°C today."), "5", "5"),
            (_item("Dose 5 mg/day today."), "5 mg", "5 mg"),
            (_item("Failure was 5%."), "5", "5"),
            (_item("José approved."), "Jose", "Jose"),
            (_item("Jean‑Luc approved."), "Luc", "Luc"),
            (_item("anti‐inflammatory dose."), "inflammatory", "inflammatory"),
            (_item("Time 10:15 today."), "15", "15"),
            (_item("Ratio 1:2 today."), "2", "2"),
            (_item("Dose 5°C today."), "°C", "°C"),
            (_item("Failure 5% today."), "% today", "% today"),
            (_item("Dose +5 mg today."), "5 mg", "5 mg"),
            (_item("Dose −5 mg today."), "5 mg", "5 mg"),
            (_item("Dose ≤5 mg today."), "5 mg", "5 mg"),
            (_item("Dose 3–5 mg today."), "5 mg", "5 mg"),
        )
        for item, subject, quote in cases:
            response = _model_response(subject, quote)
            with self.subTest(subject=subject, quote=quote), self.assertRaises(
                ValueError
            ):
                StudentQuestionModel(
                    transport=_Transport(response),
                    model="rapid-model",
                    maximum_output_tokens=256,
                ).generate(
                    _request(),
                    _evidence(item=item),
                    cancellation=threading.Event(),
                )

        for text, subject in (
            ("Dose 0,5 mg.", "0,5 mg"),
            ("Date 08/31/2026 today.", "08/31/2026"),
            ("$100 was approved.", "$100"),
            ("Dose 5°C today.", "5°C"),
            ("Dose 5 mg/day today.", "5 mg/day"),
            ("Failure was 5%.", "5%"),
            ("Date 2026-08-31.", "2026-08-31"),
            ("Time 10:15 today.", "10:15"),
            ("Ratio 1:2 today.", "1:2"),
            ("José approved.", "José"),
            ("Jean‑Luc approved.", "Jean‑Luc"),
            ("anti‐inflammatory dose.", "anti‐inflammatory"),
            ("Decision: approved.", "approved"),
            ("Dose +5 mg today.", "+5 mg"),
            ("Dose −5 mg today.", "−5 mg"),
            ("Dose ≤5 mg today.", "≤5 mg"),
            ("Dose 3–5 mg today.", "3–5 mg"),
        ):
            item = _item(text)
            response = _model_response(subject, text)
            with self.subTest(valid_subject=subject):
                questions = StudentQuestionModel(
                    transport=_Transport(response),
                    model="rapid-model",
                    maximum_output_tokens=256,
                ).generate(
                    _request(),
                    _evidence(item=item),
                    cancellation=threading.Event(),
                )
                self.assertEqual(questions[0].source_subject, subject)

    def test_model_derives_support_span_and_rejects_repeated_quote(self) -> None:
        item = _item("Audit evidence. Audit evidence.")
        with self.assertRaisesRegex(ValueError, "support is invalid"):
            StudentQuestionSupport(item, "Audit evidence")

        with self.assertRaisesRegex(ValueError, "support is invalid"):
            StudentQuestionSupport(_item("Audit Audit Audit"), "Audit Audit")

        support = StudentQuestionSupport(_item(), "crash safety")
        self.assertEqual(
            support.to_wire(),
            {
                "sourceCitation": _item().citation_wire(),
                "supportQuote": "crash safety",
                "supportCharStart": 29,
                "supportCharEnd": 41,
            },
        )

    def test_service_rejects_same_identity_support_with_changed_text(self) -> None:
        admission = _Admission()
        canonical = _item()
        forged_text = (
            "X" * (len(canonical.text) - len("crash safety")) + "crash safety"
        )
        forged = replace(
            canonical,
            text=forged_text,
        )
        view = StudentService(
            admission=admission,
            evidence_reader=_Reader(_evidence(item=canonical)),
            question_generator=_Generator(
                questions=(
                    StudentQuestion(
                        "crash safety",
                        student_question_text("crash safety"),
                        (StudentQuestionSupport(forged, "crash safety"),),
                    ),
                )
            ),
            result_auditor=_Auditor(),
        ).create_questions(
            _request(),
            principal=_principal(),
            cancellation=threading.Event(),
        )

        self.assertEqual(view.status, "failed")
        self.assertEqual(view.reason, "invalid-output")

    def test_model_binds_only_the_selected_visible_evidence(self) -> None:
        primary = _item("Alice approved TAVI.")
        unrelated = replace(
            _item("Bob denied CABG."),
            source_revision="d" * 64,
            content_sha256="e" * 64,
        )
        evidence = StudentEvidence.create(
            generation_sha256="a" * 64,
            permission_hash="d" * 64,
            authorization_hash="e" * 64,
            conversation_concept_id="meetings/job-1",
            items=(primary, unrelated),
            output_budget_exhausted=False,
        )
        questions = StudentQuestionModel(
            transport=_Transport(
                _model_response("CABG", unrelated.text, evidence_index=1)
            ),
            model="rapid-model",
            maximum_output_tokens=256,
        ).generate(_request(), evidence, cancellation=threading.Event())

        self.assertEqual(
            questions[0].supports,
            (StudentQuestionSupport(unrelated, unrelated.text),),
        )

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
        self.assertEqual(view.to_wire()["schemaVersion"], 3)
        self.assertEqual(
            view.to_wire()["questions"][0]["sourceSubject"],
            "crash safety",
        )
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
                questions=(
                    StudentQuestion(
                        "crash safety",
                        student_question_text("crash safety"),
                        (StudentQuestionSupport(hidden, "crash safety"),),
                    ),
                )
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
