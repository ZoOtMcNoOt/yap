from __future__ import annotations

import threading
import time
import unittest

from yap_server.agents.curator import CuratorRequest
from yap_server.agents.curator_service import CuratorJobView
from yap_server.agents.curator_proposal_service import (
    CuratorProposalContainmentError,
    CuratorProposalService,
)
from yap_server.auth import AuthenticatedPrincipal
from yap_server.knowledge.knowledge_tool_contract import ProposalCitation


def _principal(subject: str = "alice") -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        tenant_id="tenant-a",
        subject_id=subject,
        client_id="desktop",
        scopes=frozenset(),
    )


def _request(*, submission_id: str = "submission-1") -> CuratorRequest:
    return CuratorRequest(
        submission_id=submission_id,
        trigger="explicit-proposal",
        expected_generation_sha256="a" * 64,
        reviewed_content="The reviewed release remains blocked.",
        source_citations=(
            ProposalCitation(
                concept_id="meetings/job-1",
                source_revision="b" * 64,
                content_sha256="c" * 64,
                char_start=0,
                char_end=28,
            ),
        ),
    )


class _ControlledCurator:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls: list[tuple[CuratorRequest, AuthenticatedPrincipal]] = []
        self.result = CuratorJobView(
            request_id="internal-curator-1",
            submission_id="submission-1",
            status="proposed",
            generation_sha256="a" * 64,
            evidence_sha256="d" * 64,
            proposal_id="e" * 64,
        )

    def propose(self, request, *, principal, cancellation):
        self.calls.append((request, principal))
        self.started.set()
        while not self.release.wait(0.01):
            if cancellation.is_set():
                return CuratorJobView(
                    request_id="internal-curator-1",
                    submission_id=request.submission_id,
                    status="cancelled",
                    generation_sha256=request.expected_generation_sha256,
                    reason="client-cancelled",
                )
        return self.result


def _wait_for_terminal(
    service: CuratorProposalService,
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
    raise AssertionError("curator product request did not finish")


class CuratorProposalServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.inner = _ControlledCurator()
        self.service = CuratorProposalService(curator=self.inner)

    def tearDown(self) -> None:
        self.inner.release.set()
        self.service.close()

    def test_submit_projects_safe_terminal_proposal_under_product_identity(
        self,
    ) -> None:
        initial = self.service.submit(_request(), principal=_principal())

        self.assertEqual(initial.status, "queued")
        self.assertRegex(initial.request_id, r"^curator-proposal-[0-9a-f]{32}$")
        self.assertEqual(
            initial.to_wire(),
            {
                "schemaVersion": 1,
                "requestId": initial.request_id,
                "submissionId": "submission-1",
                "status": "queued",
                "generationSha256": "a" * 64,
            },
        )
        self.assertTrue(self.inner.started.wait(1))
        self.inner.release.set()

        terminal = _wait_for_terminal(self.service, initial.request_id, _principal())
        self.assertEqual(terminal.status, "proposed")
        self.assertEqual(terminal.evidence_sha256, "d" * 64)
        self.assertEqual(terminal.proposal_id, "e" * 64)
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

    def test_rejected_result_retains_no_proposal_identity(self) -> None:
        self.inner.result = CuratorJobView(
            request_id="internal-curator-1",
            submission_id="submission-1",
            status="rejected",
            generation_sha256="a" * 64,
            evidence_sha256="d" * 64,
            reason="model-rejected",
        )
        initial = self.service.submit(_request(), principal=_principal())
        self.inner.release.set()

        terminal = _wait_for_terminal(self.service, initial.request_id, _principal())
        self.assertEqual(terminal.status, "rejected")
        self.assertIsNone(terminal.proposal_id)
        self.assertEqual(terminal.reason, "model-rejected")

    def test_mismatched_inner_identity_fences_the_product_service(self) -> None:
        self.inner.result = CuratorJobView(
            request_id="internal-curator-1",
            submission_id="other-submission",
            status="proposed",
            generation_sha256="a" * 64,
            evidence_sha256="d" * 64,
            proposal_id="e" * 64,
        )
        initial = self.service.submit(_request(), principal=_principal())
        self.inner.release.set()

        terminal = _wait_for_terminal(self.service, initial.request_id, _principal())
        self.assertEqual(terminal.status, "failed")
        self.assertEqual(terminal.reason, "service-unavailable")
        with self.assertRaises(CuratorProposalContainmentError):
            self.service.submit(
                _request(submission_id="submission-2"), principal=_principal()
            )
        with self.assertRaises(CuratorProposalContainmentError):
            self.service.close()

        self.service = CuratorProposalService(curator=_ControlledCurator())


if __name__ == "__main__":
    unittest.main()
