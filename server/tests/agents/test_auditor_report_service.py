from __future__ import annotations

import hashlib
import threading
import time
import unittest
from unittest import mock

from yap_server.agents.auditor import (
    AuditorEvidencePack,
    AuditorReport,
    AuditorRequest,
    build_auditor_report,
)
from yap_server.agents.auditor_model import AuditorDecision
from yap_server.agents.auditor_service import AuditorContainmentError, AuditorJobView
from yap_server.agents.auditor_report_service import (
    AuditorReportContainmentError,
    AuditorReportService,
    AuditorReportServiceError,
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


def _request() -> AuditorRequest:
    return AuditorRequest("Helios release limit", 1, "a" * 64)


def _evidence() -> AuditorEvidencePack:
    texts = (
        "Helios release limit is five items.",
        "Helios release limit is ten items.",
    )
    items = tuple(
        LibrarianEvidenceItem(
            concept_id=f"limits/helios-{index}",
            source_revision="revision-1",
            content_sha256=hashlib.sha256(text.encode()).hexdigest(),
            char_start=0,
            char_end=len(text),
            text=text,
        )
        for index, text in enumerate(texts, start=1)
    )
    return AuditorEvidencePack.create(
        generation_sha256="a" * 64,
        source_admission_sha256="b" * 64,
        permission_hash="c" * 64,
        authorization_hash="d" * 64,
        items=items,
        output_budget_exhausted=False,
    )


def _report() -> AuditorReport:
    report = build_auditor_report(
        _request(),
        _evidence(),
        AuditorDecision("report", ((0, 1),)),
    )
    assert report is not None
    return report


class _ControlledAuditor:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls: list[tuple[AuditorRequest, AuthenticatedPrincipal]] = []
        self.result = AuditorJobView("internal-auditor-1", "complete", _report())
        self.error: BaseException | None = None

    def audit(self, request, *, principal, cancellation):
        self.calls.append((request, principal))
        self.started.set()
        while not self.release.wait(0.01):
            if cancellation.is_set():
                return AuditorJobView(
                    "internal-auditor-1",
                    "cancelled",
                    reason="client-cancelled",
                )
        if self.error is not None:
            raise self.error
        if cancellation.is_set():
            return AuditorJobView(
                "internal-auditor-1",
                "cancelled",
                reason="client-cancelled",
            )
        return self.result


def _wait_for_terminal(
    service: AuditorReportService,
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
    raise AssertionError("auditor product report request did not finish")


class AuditorReportServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.inner = _ControlledAuditor()
        self.service = AuditorReportService(auditor=self.inner)

    def tearDown(self) -> None:
        self.inner.release.set()
        self.service.close()

    def test_submit_projects_safe_terminal_report_under_product_identity(self) -> None:
        initial = self.service.submit(_request(), principal=_principal())

        self.assertEqual(initial.status, "queued")
        self.assertRegex(initial.request_id, r"^auditor-report-[0-9a-f]{32}$")
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
        self.assertEqual(terminal.report, _report())
        self.assertEqual(terminal.to_wire()["report"], _report().to_wire())
        self.assertEqual(self.inner.calls, [(_request(), _principal())])

    def test_status_and_cancel_are_owner_scoped_and_terminal(self) -> None:
        initial = self.service.submit(_request(), principal=_principal())
        self.assertTrue(self.inner.started.wait(1))

        self.assertIsNone(self.service.get(initial.request_id, principal=_principal("bob")))
        self.assertFalse(self.service.cancel(initial.request_id, principal=_principal("bob")))
        self.assertTrue(self.service.cancel(initial.request_id, principal=_principal()))
        requested = self.service.get(initial.request_id, principal=_principal())
        assert requested is not None
        self.assertEqual(requested.status, "cancellation-requested")

        terminal = _wait_for_terminal(self.service, initial.request_id, _principal())
        self.assertEqual(terminal.status, "cancelled")
        self.assertEqual(terminal.reason, "client-cancelled")
        self.assertIsNone(terminal.report)

    def test_evidence_unavailable_has_no_report(self) -> None:
        self.inner.result = AuditorJobView(
            "internal-auditor-1",
            "evidence-unavailable",
            reason="evidence-unavailable",
        )
        initial = self.service.submit(_request(), principal=_principal())
        self.inner.release.set()

        terminal = _wait_for_terminal(self.service, initial.request_id, _principal())
        self.assertEqual(terminal.status, "evidence-unavailable")
        self.assertEqual(terminal.reason, "evidence-unavailable")
        self.assertIsNone(terminal.report)

    def test_capacity_failure_uses_only_the_auditor_product_vocabulary(self) -> None:
        with mock.patch(
            "yap_server.agents.auditor_report_service._MAXIMUM_INFLIGHT_REQUESTS",
            1,
        ):
            self.service.submit(_request(), principal=_principal())
            with self.assertRaises(AuditorReportServiceError) as raised:
                self.service.submit(_request(), principal=_principal("bob"))

        self.assertEqual(raised.exception.status, 429)
        self.assertEqual(raised.exception.code, "AUDITOR_REPORT_CAPACITY")
        self.assertTrue(raised.exception.retryable)

    def test_invalid_or_uncontained_inner_result_fences_product_service(self) -> None:
        self.inner.result = AuditorJobView("internal-auditor-1", "complete")
        initial = self.service.submit(_request(), principal=_principal())
        self.inner.release.set()

        terminal = _wait_for_terminal(self.service, initial.request_id, _principal())
        self.assertEqual(terminal.status, "failed")
        self.assertEqual(terminal.reason, "service-unavailable")
        with self.assertRaises(AuditorReportContainmentError):
            self.service.submit(_request(), principal=_principal())
        with self.assertRaises(AuditorReportContainmentError):
            self.service.close()

        self.service = AuditorReportService(auditor=_ControlledAuditor())

    def test_inner_containment_failure_fences_product_service(self) -> None:
        self.inner.error = AuditorContainmentError("worker escaped")
        initial = self.service.submit(_request(), principal=_principal())
        self.inner.release.set()

        terminal = _wait_for_terminal(self.service, initial.request_id, _principal())
        self.assertEqual(terminal.status, "failed")
        with self.assertRaises(AuditorReportContainmentError):
            self.service.submit(_request(), principal=_principal())
        with self.assertRaises(AuditorReportContainmentError):
            self.service.close()

        self.service = AuditorReportService(auditor=_ControlledAuditor())


if __name__ == "__main__":
    unittest.main()
