from __future__ import annotations

import threading
import time
import unittest

from yap_server.agents.archivist import ArchivistJobView
from yap_server.agents.archivist_ingestion_service import (
    ArchivistIngestionContainmentError,
    ArchivistIngestionJobView,
    ArchivistIngestionRequest,
    ArchivistIngestionService,
    ArchivistIngestionServiceError,
)
from yap_server.agents.archivist_service import ArchivistContainmentError
from yap_server.auth import AuthenticatedPrincipal


def _principal(subject: str = "alice") -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        tenant_id="tenant-a",
        subject_id=subject,
        client_id="desktop",
        scopes=frozenset(),
    )


def _request() -> ArchivistIngestionRequest:
    return ArchivistIngestionRequest(
        job_id="job-1",
        expected_result_sha256="a" * 64,
    )


class _ControlledRunner:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.validated: list[tuple[ArchivistIngestionRequest, str]] = []
        self.calls: list[tuple[ArchivistIngestionRequest, str]] = []
        self.validation_error: BaseException | None = None
        self.error: BaseException | None = None
        self.result = ArchivistJobView(
            request_id="internal-archivist-1",
            status="staged",
            capture_sha256="b" * 64,
            source_admission_sha256="c" * 64,
            generation_sha256="d" * 64,
            concept_count=1,
            permission_count=1,
        )

    def validate_source(self, request, *, principal):
        self.validated.append((request, principal.subject_id))
        if self.validation_error is not None:
            raise self.validation_error

    def stage(self, request, *, principal, cancellation):
        self.calls.append((request, principal.subject_id))
        self.started.set()
        while not self.release.wait(0.01):
            if cancellation.is_set():
                return ArchivistJobView(
                    request_id="internal-archivist-1",
                    status="cancelled",
                    capture_sha256="b" * 64,
                    reason="client-cancelled",
                )
        if self.error is not None:
            raise self.error
        if cancellation.is_set():
            return ArchivistJobView(
                request_id="internal-archivist-1",
                status="cancelled",
                capture_sha256="b" * 64,
                reason="client-cancelled",
            )
        return self.result


def _wait_for_terminal(
    service: ArchivistIngestionService,
    request_id: str,
    principal: AuthenticatedPrincipal,
) -> ArchivistIngestionJobView:
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
    raise AssertionError("archivist product ingestion did not finish")


class ArchivistIngestionServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = _ControlledRunner()
        self.service = ArchivistIngestionService(runner=self.runner)

    def tearDown(self) -> None:
        self.runner.release.set()
        try:
            self.service.close()
        except ArchivistIngestionContainmentError:
            pass

    def test_request_accepts_only_server_job_and_reviewed_result_identity(self) -> None:
        self.assertEqual(
            ArchivistIngestionRequest.from_wire(
                {
                    "schemaVersion": 1,
                    "jobId": "job-1",
                    "expectedResultSha256": "a" * 64,
                }
            ),
            _request(),
        )
        for value in (
            {
                "schemaVersion": 1,
                "jobId": "job-1",
                "expectedResultSha256": "invalid",
            },
            {
                "schemaVersion": 1,
                "jobId": "job-1",
                "expectedResultSha256": "a" * 64,
                "transcript": "caller-controlled",
            },
        ):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    ArchivistIngestionRequest.from_wire(value)

    def test_submit_projects_one_owner_bound_staged_generation(self) -> None:
        initial = self.service.submit(_request(), principal=_principal())

        self.assertEqual(initial.status, "queued")
        self.assertRegex(
            initial.request_id,
            r"^archivist-ingestion-[0-9a-f]{32}$",
        )
        self.assertEqual(
            initial.to_wire(),
            {
                "schemaVersion": 1,
                "requestId": initial.request_id,
                "status": "queued",
                "jobId": "job-1",
                "resultSha256": "a" * 64,
            },
        )
        self.assertTrue(self.runner.started.wait(1))
        self.runner.release.set()

        terminal = _wait_for_terminal(
            self.service,
            initial.request_id,
            _principal(),
        )
        self.assertEqual(terminal.status, "staged")
        self.assertEqual(terminal.capture_sha256, "b" * 64)
        self.assertEqual(terminal.source_admission_sha256, "c" * 64)
        self.assertEqual(terminal.generation_sha256, "d" * 64)
        self.assertEqual(terminal.concept_count, 1)
        self.assertEqual(terminal.permission_count, 1)
        self.assertNotEqual(terminal.request_id, "internal-archivist-1")
        self.assertEqual(self.runner.validated, [(_request(), "alice")])
        self.assertEqual(self.runner.calls, [(_request(), "alice")])

    def test_status_and_cancel_are_owner_scoped(self) -> None:
        initial = self.service.submit(_request(), principal=_principal())
        self.assertTrue(self.runner.started.wait(1))

        self.assertIsNone(
            self.service.get(initial.request_id, principal=_principal("bob"))
        )
        self.assertFalse(
            self.service.cancel(initial.request_id, principal=_principal("bob"))
        )
        self.assertTrue(self.service.cancel(initial.request_id, principal=_principal()))
        terminal = _wait_for_terminal(
            self.service,
            initial.request_id,
            _principal(),
        )
        self.assertEqual(terminal.status, "cancelled")
        self.assertEqual(terminal.reason, "client-cancelled")
        self.assertIsNone(terminal.generation_sha256)

    def test_source_preflight_rejection_creates_no_product_request(self) -> None:
        self.runner.validation_error = ArchivistIngestionServiceError(
            404,
            "ARCHIVIST_SOURCE_NOT_FOUND",
            "The server transcript does not exist.",
            retryable=False,
            reason="invalid-reviewed-source",
        )

        with self.assertRaises(ArchivistIngestionServiceError) as raised:
            self.service.submit(_request(), principal=_principal())

        self.assertEqual(raised.exception.status, 404)
        self.assertEqual(self.runner.calls, [])

    def test_inner_containment_failure_fences_future_submissions(self) -> None:
        self.runner.error = ArchivistContainmentError("worker escaped")
        initial = self.service.submit(_request(), principal=_principal())
        self.runner.release.set()

        terminal = _wait_for_terminal(
            self.service,
            initial.request_id,
            _principal(),
        )
        self.assertEqual(terminal.status, "failed")
        self.assertEqual(terminal.reason, "service-unavailable")
        with self.assertRaises(ArchivistIngestionContainmentError):
            self.service.submit(_request(), principal=_principal())


if __name__ == "__main__":
    unittest.main()
