from __future__ import annotations

import hashlib
import threading
import time
import unittest

from yap_server.agents.analyst import (
    AnalystAnswer,
    AnalystRequest,
    build_analyst_answer,
)
from yap_server.agents.analyst_answer_service import (
    AnalystAnswerContainmentError,
    AnalystAnswerService,
)
from yap_server.agents.analyst_model import AnalystDecision
from yap_server.agents.analyst_service import AnalystContainmentError, AnalystJobView
from yap_server.agents.librarian import LibrarianEvidenceItem, LibrarianEvidencePack
from yap_server.auth import AuthenticatedPrincipal


def _principal(subject: str = "alice") -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        tenant_id="tenant-a",
        subject_id=subject,
        client_id="desktop",
        scopes=frozenset(),
    )


def _request() -> AnalystRequest:
    return AnalystRequest("What was approved?", 3, "a" * 64)


def _evidence() -> LibrarianEvidencePack:
    text = "The reviewed release was approved."
    item = LibrarianEvidenceItem(
        concept_id="records/release",
        source_revision="revision-1",
        content_sha256=hashlib.sha256(text.encode()).hexdigest(),
        char_start=0,
        char_end=len(text),
        text=text,
    )
    return LibrarianEvidencePack.create(
        generation_sha256="a" * 64,
        permission_hash="b" * 64,
        authorization_hash="c" * 64,
        items=(item,),
        output_budget_exhausted=False,
    )


def _answer() -> AnalystAnswer:
    answer = build_analyst_answer(
        _request(),
        _evidence(),
        AnalystDecision("answer", (0,)),
    )
    assert answer is not None
    return answer


class _ControlledAnalyst:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls: list[tuple[AnalystRequest, AuthenticatedPrincipal]] = []
        self.result = AnalystJobView("internal-analyst-1", "complete", _answer())
        self.error: BaseException | None = None

    def answer(self, request, *, principal, cancellation):
        self.calls.append((request, principal))
        self.started.set()
        while not self.release.wait(0.01):
            if cancellation.is_set():
                return AnalystJobView(
                    "internal-analyst-1",
                    "cancelled",
                    reason="client-cancelled",
                )
        if self.error is not None:
            raise self.error
        if cancellation.is_set():
            return AnalystJobView(
                "internal-analyst-1",
                "cancelled",
                reason="client-cancelled",
            )
        return self.result


def _wait_for_terminal(
    service: AnalystAnswerService,
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
    raise AssertionError("analyst product answer request did not finish")


class AnalystAnswerServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.inner = _ControlledAnalyst()
        self.service = AnalystAnswerService(analyst=self.inner)

    def tearDown(self) -> None:
        self.inner.release.set()
        self.service.close()

    def test_submit_projects_safe_terminal_answer_under_product_identity(self) -> None:
        initial = self.service.submit(_request(), principal=_principal())

        self.assertEqual(initial.status, "queued")
        self.assertRegex(initial.request_id, r"^analyst-answer-[0-9a-f]{32}$")
        self.assertEqual(
            initial.to_wire(),
            {
                "schemaVersion": 1,
                "requestId": initial.request_id,
                "status": "queued",
            },
        )
        self.assertTrue(self.inner.started.wait(1))
        self.inner.release.set()

        terminal = _wait_for_terminal(self.service, initial.request_id, _principal())
        self.assertEqual(terminal.status, "complete")
        self.assertEqual(terminal.answer, _answer())
        self.assertEqual(terminal.to_wire()["citedAnswer"], _answer().to_wire())
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

    def test_evidence_unavailable_has_no_answer(self) -> None:
        self.inner.result = AnalystJobView(
            "internal-analyst-1",
            "evidence-unavailable",
            reason="evidence-unavailable",
        )
        initial = self.service.submit(_request(), principal=_principal())
        self.inner.release.set()

        terminal = _wait_for_terminal(self.service, initial.request_id, _principal())
        self.assertEqual(terminal.status, "evidence-unavailable")
        self.assertEqual(terminal.reason, "evidence-unavailable")
        self.assertIsNone(terminal.answer)

    def test_invalid_or_uncontained_inner_result_fences_product_service(self) -> None:
        self.inner.result = AnalystJobView("internal-analyst-1", "complete")
        initial = self.service.submit(_request(), principal=_principal())
        self.inner.release.set()

        terminal = _wait_for_terminal(self.service, initial.request_id, _principal())
        self.assertEqual(terminal.status, "failed")
        self.assertEqual(terminal.reason, "service-unavailable")
        with self.assertRaises(AnalystAnswerContainmentError):
            self.service.submit(_request(), principal=_principal())
        with self.assertRaises(AnalystAnswerContainmentError):
            self.service.close()

        self.service = AnalystAnswerService(analyst=_ControlledAnalyst())

    def test_inner_containment_failure_fences_product_service(self) -> None:
        self.inner.error = AnalystContainmentError("worker escaped")
        initial = self.service.submit(_request(), principal=_principal())
        self.inner.release.set()

        terminal = _wait_for_terminal(self.service, initial.request_id, _principal())
        self.assertEqual(terminal.status, "failed")
        with self.assertRaises(AnalystAnswerContainmentError):
            self.service.submit(_request(), principal=_principal())
        with self.assertRaises(AnalystAnswerContainmentError):
            self.service.close()

        self.service = AnalystAnswerService(analyst=_ControlledAnalyst())


if __name__ == "__main__":
    unittest.main()
