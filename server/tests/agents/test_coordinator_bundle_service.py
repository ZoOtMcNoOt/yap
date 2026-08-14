from __future__ import annotations

import hashlib
import threading
import time
import unittest

from yap_server.agents.coordinator import (
    CoordinatorEvidencePack,
    CoordinatorProposalBundle,
    CoordinatorProposalCandidate,
    CoordinatorRequest,
    build_coordinator_proposal_bundle,
)
from yap_server.agents.coordinator_bundle_service import (
    CoordinatorBundleContainmentError,
    CoordinatorBundleService,
)
from yap_server.agents.coordinator_model import CoordinatorDecision
from yap_server.agents.coordinator_service import (
    CoordinatorContainmentError,
    CoordinatorJobView,
)
from yap_server.agents.librarian import LibrarianEvidenceItem
from yap_server.auth import AuthenticatedPrincipal


def _principal(subject: str = "alice") -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        tenant_id="tenant-a",
        subject_id=subject,
        client_id="desktop",
        scopes=frozenset(),
    )


def _request() -> CoordinatorRequest:
    return CoordinatorRequest(
        "Coordinate the reviewed release proposals.",
        3,
        "a" * 64,
    )


def _candidate() -> CoordinatorProposalCandidate:
    text = "The reviewed release requires security approval."
    citation = LibrarianEvidenceItem(
        concept_id="records/release",
        source_revision="revision-1",
        content_sha256=hashlib.sha256(text.encode()).hexdigest(),
        char_start=0,
        char_end=len(text),
        text=text,
    )
    return CoordinatorProposalCandidate.create(
        proposal_id=hashlib.sha256(b"proposal-1").hexdigest(),
        curator_request_id="curator-request-1",
        curator_submission_id="curator-submission-1",
        curator_request_sha256=hashlib.sha256(b"curator-request").hexdigest(),
        curator_work_sha256=hashlib.sha256(b"curator-work").hexdigest(),
        curator_evidence_sha256=hashlib.sha256(b"curator-evidence").hexdigest(),
        generation_sha256="a" * 64,
        proposal_type="summary",
        proposed_content="Coordinate security approval before release.",
        inherited_permission_sha256=hashlib.sha256(b"inherited").hexdigest(),
        proposal_permission_hash=hashlib.sha256(b"permission").hexdigest(),
        proposal_authorization_hash=hashlib.sha256(b"authorization").hexdigest(),
        citations=(citation,),
    )


def _evidence() -> CoordinatorEvidencePack:
    return CoordinatorEvidencePack.create(
        generation_sha256="a" * 64,
        permission_hash="b" * 64,
        authorization_hash="c" * 64,
        candidates=(_candidate(),),
        output_budget_exhausted=False,
    )


def _bundle() -> CoordinatorProposalBundle:
    bundle = build_coordinator_proposal_bundle(
        _request(),
        _evidence(),
        CoordinatorDecision("bundle", (0,)),
    )
    assert bundle is not None
    return bundle


class _ControlledCoordinator:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls: list[tuple[CoordinatorRequest, AuthenticatedPrincipal]] = []
        self.result = CoordinatorJobView(
            "internal-coordinator-1",
            "complete",
            _bundle(),
        )
        self.error: BaseException | None = None

    def coordinate(self, request, *, principal, cancellation):
        self.calls.append((request, principal))
        self.started.set()
        while not self.release.wait(0.01):
            if cancellation.is_set():
                return CoordinatorJobView(
                    "internal-coordinator-1",
                    "cancelled",
                    reason="client-cancelled",
                )
        if self.error is not None:
            raise self.error
        if cancellation.is_set():
            return CoordinatorJobView(
                "internal-coordinator-1",
                "cancelled",
                reason="client-cancelled",
            )
        return self.result


def _wait_for_terminal(
    service: CoordinatorBundleService,
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
    raise AssertionError("coordinator product bundle request did not finish")


class CoordinatorBundleServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.inner = _ControlledCoordinator()
        self.service = CoordinatorBundleService(coordinator=self.inner)

    def tearDown(self) -> None:
        self.inner.release.set()
        self.service.close()

    def test_submit_projects_safe_terminal_bundle_under_product_identity(self) -> None:
        initial = self.service.submit(_request(), principal=_principal())

        self.assertEqual(initial.status, "queued")
        self.assertRegex(initial.request_id, r"^coordinator-bundle-[0-9a-f]{32}$")
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
        self.assertEqual(terminal.bundle, _bundle())
        self.assertEqual(
            terminal.to_wire()["proposalBundle"],
            _bundle().to_wire(),
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

    def test_evidence_unavailable_has_no_bundle(self) -> None:
        self.inner.result = CoordinatorJobView(
            "internal-coordinator-1",
            "evidence-unavailable",
            reason="evidence-unavailable",
        )
        initial = self.service.submit(_request(), principal=_principal())
        self.inner.release.set()

        terminal = _wait_for_terminal(self.service, initial.request_id, _principal())
        self.assertEqual(terminal.status, "evidence-unavailable")
        self.assertEqual(terminal.reason, "evidence-unavailable")
        self.assertIsNone(terminal.bundle)

    def test_invalid_or_uncontained_inner_result_fences_product_service(self) -> None:
        self.inner.result = CoordinatorJobView("internal-coordinator-1", "complete")
        initial = self.service.submit(_request(), principal=_principal())
        self.inner.release.set()

        terminal = _wait_for_terminal(self.service, initial.request_id, _principal())
        self.assertEqual(terminal.status, "failed")
        self.assertEqual(terminal.reason, "service-unavailable")
        with self.assertRaises(CoordinatorBundleContainmentError):
            self.service.submit(_request(), principal=_principal())
        with self.assertRaises(CoordinatorBundleContainmentError):
            self.service.close()

        self.service = CoordinatorBundleService(coordinator=_ControlledCoordinator())

    def test_inner_containment_failure_fences_product_service(self) -> None:
        self.inner.error = CoordinatorContainmentError("worker escaped")
        initial = self.service.submit(_request(), principal=_principal())
        self.inner.release.set()

        terminal = _wait_for_terminal(self.service, initial.request_id, _principal())
        self.assertEqual(terminal.status, "failed")
        with self.assertRaises(CoordinatorBundleContainmentError):
            self.service.submit(_request(), principal=_principal())
        with self.assertRaises(CoordinatorBundleContainmentError):
            self.service.close()

        self.service = CoordinatorBundleService(coordinator=_ControlledCoordinator())


if __name__ == "__main__":
    unittest.main()
