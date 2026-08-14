from __future__ import annotations

import threading
import time
import unittest

from yap_server.agents.student import StudentEvidenceItem, StudentRequest
from yap_server.agents.student_model import (
    StudentQuestion,
    StudentQuestionSupport,
    student_question_text,
)
from yap_server.agents.student_question_service import (
    StudentQuestionContainmentError,
    StudentQuestionService,
)
from yap_server.agents.student_service import (
    StudentContainmentError,
    StudentJobView,
)
from yap_server.auth import AuthenticatedPrincipal


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


def _question() -> StudentQuestion:
    text = "The reviewed meeting records crash safety."
    evidence = StudentEvidenceItem(
        concept_id="meetings/job-1",
        source_revision="b" * 64,
        content_sha256="c" * 64,
        char_start=0,
        char_end=len(text),
        text=text,
    )
    subject = "crash safety"
    return StudentQuestion(
        source_subject=subject,
        question=student_question_text(subject),
        supports=(StudentQuestionSupport(evidence, subject),),
    )


class _ControlledStudent:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls: list[tuple[StudentRequest, AuthenticatedPrincipal]] = []
        self.result = StudentJobView(
            request_id="internal-student-1",
            status="complete",
            conversation_concept_id="meetings/job-1",
            generation_sha256="a" * 64,
            evidence_sha256="d" * 64,
            questions=(_question(),),
        )
        self.error: BaseException | None = None

    def create_questions(self, request, *, principal, cancellation):
        self.calls.append((request, principal))
        self.started.set()
        while not self.release.wait(0.01):
            if cancellation.is_set():
                return StudentJobView(
                    request_id="internal-student-1",
                    status="cancelled",
                    conversation_concept_id=request.conversation_concept_id,
                    generation_sha256=request.expected_generation_sha256,
                    reason="client-cancelled",
                )
        if self.error is not None:
            raise self.error
        if cancellation.is_set():
            return StudentJobView(
                request_id="internal-student-1",
                status="cancelled",
                conversation_concept_id=request.conversation_concept_id,
                generation_sha256=request.expected_generation_sha256,
                reason="client-cancelled",
            )
        return self.result


def _wait_for_terminal(
    service: StudentQuestionService,
    request_id: str,
    principal: AuthenticatedPrincipal,
):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        view = service.get(request_id, principal=principal)
        if view is not None and view.status not in {
            "queued",
            "running",
            "cancellation-requested",
        }:
            return view
        time.sleep(0.01)
    raise AssertionError("student product question request did not finish")


class StudentQuestionServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.inner = _ControlledStudent()
        self.service = StudentQuestionService(student=self.inner)

    def tearDown(self) -> None:
        self.inner.release.set()
        self.service.close()

    def test_submit_projects_safe_terminal_questions_under_product_identity(
        self,
    ) -> None:
        initial = self.service.submit(_request(), principal=_principal())

        self.assertEqual(initial.status, "queued")
        self.assertRegex(initial.request_id, r"^student-question-[0-9a-f]{32}$")
        self.assertEqual(
            initial.to_wire(),
            {
                "schemaVersion": 1,
                "requestId": initial.request_id,
                "status": "queued",
                "conversationConceptId": "meetings/job-1",
                "generationSha256": "a" * 64,
                "questions": [],
                "outputBudgetExhausted": False,
            },
        )
        self.assertTrue(self.inner.started.wait(1))
        self.inner.release.set()

        terminal = _wait_for_terminal(self.service, initial.request_id, _principal())
        self.assertEqual(terminal.status, "complete")
        self.assertEqual(terminal.questions, (_question(),))
        self.assertEqual(terminal.evidence_sha256, "d" * 64)
        self.assertEqual(
            terminal.to_wire()["questions"],
            [_question().to_wire()],
        )
        self.assertEqual(self.inner.calls, [(_request(), _principal())])

    def test_status_and_cancel_are_owner_scoped_and_terminal(self) -> None:
        initial = self.service.submit(_request(), principal=_principal())
        self.assertTrue(self.inner.started.wait(1))

        self.assertIsNone(
            self.service.get(initial.request_id, principal=_principal("bob"))
        )
        self.assertFalse(
            self.service.cancel(initial.request_id, principal=_principal("bob"))
        )
        self.assertTrue(self.service.cancel(initial.request_id, principal=_principal()))
        requested = self.service.get(initial.request_id, principal=_principal())
        self.assertIsNotNone(requested)
        assert requested is not None
        self.assertEqual(requested.status, "cancellation-requested")

        terminal = _wait_for_terminal(self.service, initial.request_id, _principal())
        self.assertEqual(terminal.status, "cancelled")
        self.assertEqual(terminal.reason, "client-cancelled")
        self.assertFalse(
            self.service.cancel(initial.request_id, principal=_principal())
        )

    def test_evidence_unavailable_has_no_questions(self) -> None:
        self.inner.result = StudentJobView(
            request_id="internal-student-1",
            status="evidence-unavailable",
            conversation_concept_id="meetings/job-1",
            generation_sha256="a" * 64,
            reason="evidence-unavailable",
        )
        initial = self.service.submit(_request(), principal=_principal())
        self.inner.release.set()

        terminal = _wait_for_terminal(self.service, initial.request_id, _principal())
        self.assertEqual(terminal.status, "evidence-unavailable")
        self.assertEqual(terminal.reason, "evidence-unavailable")
        self.assertEqual(terminal.questions, ())

    def test_mismatched_or_uncontained_inner_result_fences_product_service(
        self,
    ) -> None:
        self.inner.result = StudentJobView(
            request_id="internal-student-1",
            status="complete",
            conversation_concept_id="meetings/other",
            generation_sha256="a" * 64,
            evidence_sha256="d" * 64,
            questions=(_question(),),
        )
        initial = self.service.submit(_request(), principal=_principal())
        self.inner.release.set()

        terminal = _wait_for_terminal(self.service, initial.request_id, _principal())
        self.assertEqual(terminal.status, "failed")
        self.assertEqual(terminal.reason, "service-unavailable")
        with self.assertRaises(StudentQuestionContainmentError):
            self.service.submit(_request(), principal=_principal())
        with self.assertRaises(StudentQuestionContainmentError):
            self.service.close()

        self.service = StudentQuestionService(student=_ControlledStudent())

    def test_inner_containment_failure_fences_product_service(self) -> None:
        self.inner.error = StudentContainmentError("worker escaped")
        initial = self.service.submit(_request(), principal=_principal())
        self.inner.release.set()

        terminal = _wait_for_terminal(self.service, initial.request_id, _principal())
        self.assertEqual(terminal.status, "failed")
        with self.assertRaises(StudentQuestionContainmentError):
            self.service.submit(_request(), principal=_principal())
        with self.assertRaises(StudentQuestionContainmentError):
            self.service.close()

        self.service = StudentQuestionService(student=_ControlledStudent())


if __name__ == "__main__":
    unittest.main()
