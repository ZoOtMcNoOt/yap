from __future__ import annotations

from contextlib import nullcontext
import threading
import unittest
from unittest.mock import patch

from yap_server.agents.archivist import ArchivistJobView
from yap_server.agents.archivist_ingestion_runner import (
    PostgresArchivistIngestionRunner,
)
from yap_server.agents.archivist_ingestion_service import (
    ArchivistIngestionRequest,
    ArchivistIngestionServiceError,
)
from yap_server.auth import AuthenticatedPrincipal
from yap_server.knowledge.reviewed_capture_ledger import ReviewedCaptureDescriptor
from yap_server.knowledge.reviewed_meeting_knowledge import result_revision_sha256


def _principal(subject: str = "alice") -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        tenant_id="tenant-a",
        subject_id=subject,
        client_id="desktop",
        scopes=frozenset(),
    )


def _result() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "jobId": "job-1",
        "transcript": "Reviewed launch decision.",
    }


def _request() -> ArchivistIngestionRequest:
    return ArchivistIngestionRequest(
        job_id="job-1",
        expected_result_sha256=result_revision_sha256(_result()),
    )


def _capture() -> ReviewedCaptureDescriptor:
    return ReviewedCaptureDescriptor(
        tenant_id="tenant-a",
        owner_id="alice",
        job_id="job-1",
        capture_sha256="a" * 64,
        result_sha256=_request().expected_result_sha256,
        review_sha256="b" * 64,
        normalized_okf_sha256="c" * 64,
        normalized_okf="reviewed",
    )


class _Jobs:
    owner = _principal().key

    def __init__(self) -> None:
        self.projection = {"displayName": "Architecture review"}
        self.result = _result()

    def get(self, job_id):
        if job_id != "job-1":
            raise AssertionError("unexpected job")
        return self.projection

    def get_result(self, job_id):
        if job_id != "job-1":
            raise AssertionError("unexpected job")
        return self.result


class _JobService:
    def __init__(self) -> None:
        self.jobs = _Jobs()
        self.principals = []

    def for_principal(self, principal):
        self.principals.append(principal)
        return self.jobs


class _Core:
    def __init__(self) -> None:
        self.calls = []

    def ingest(self, request, *, principal, cancellation):
        self.calls.append((request, principal, cancellation))
        return ArchivistJobView(
            request_id="archivist-core-1",
            status="staged",
            capture_sha256=request.capture_sha256,
            source_admission_sha256="d" * 64,
            generation_sha256="e" * 64,
            concept_count=1,
            permission_count=1,
        )


class ArchivistIngestionRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.jobs = _JobService()
        self.core = _Core()
        self.connection = object()
        self.runner = PostgresArchivistIngestionRunner(
            jobs=self.jobs,
            connection_factory=lambda: nullcontext(self.connection),
            archivist=self.core,
            now=lambda: "2026-08-13T22:30:00Z",
        )

    def test_preflight_binds_the_authenticated_owner_and_exact_result(self) -> None:
        self.runner.validate_source(_request(), principal=_principal())

        self.assertEqual(self.jobs.principals, [_principal()])
        changed = ArchivistIngestionRequest(
            job_id="job-1",
            expected_result_sha256="f" * 64,
        )
        with self.assertRaises(ArchivistIngestionServiceError) as raised:
            self.runner.validate_source(changed, principal=_principal())
        self.assertEqual(raised.exception.status, 409)
        self.assertEqual(raised.exception.code, "ARCHIVIST_SOURCE_CHANGED")

    def test_existing_review_capture_is_reused_before_one_core_lease(self) -> None:
        cancellation = threading.Event()
        with (
            patch(
                "yap_server.agents.archivist_ingestion_runner.read_reviewed_capture_for_result",
                return_value=_capture(),
            ) as read_capture,
            patch(
                "yap_server.agents.archivist_ingestion_runner.append_reviewed_meeting_capture"
            ) as append_capture,
        ):
            view = self.runner.stage(
                _request(),
                principal=_principal(),
                cancellation=cancellation,
            )

        self.assertEqual(view.status, "staged")
        self.assertEqual(view.capture_sha256, "a" * 64)
        append_capture.assert_not_called()
        read_capture.assert_called_once_with(
            self.connection,
            principal=_principal().key,
            job_id="job-1",
            result_sha256=_request().expected_result_sha256,
        )
        self.assertEqual(len(self.core.calls), 1)
        self.assertEqual(self.core.calls[0][0].capture_sha256, "a" * 64)

    def test_new_review_uses_only_server_owned_source_fields(self) -> None:
        with (
            patch(
                "yap_server.agents.archivist_ingestion_runner.read_reviewed_capture_for_result",
                return_value=None,
            ),
            patch(
                "yap_server.agents.archivist_ingestion_runner.append_reviewed_meeting_capture",
                return_value=_capture(),
            ) as append_capture,
        ):
            self.runner.stage(
                _request(),
                principal=_principal(),
                cancellation=threading.Event(),
            )

        review = append_capture.call_args.kwargs["review"]
        self.assertEqual(review.reviewer, _principal().key)
        self.assertEqual(review.job_id, "job-1")
        self.assertEqual(review.title, "Architecture review")
        self.assertEqual(review.reviewed_at_utc, "2026-08-13T22:30:00Z")
        self.assertEqual(
            review.result_revision_sha256,
            _request().expected_result_sha256,
        )
        self.assertEqual(review.decision, "accepted")

    def test_pre_cancel_writes_no_capture_and_takes_no_core_lease(self) -> None:
        cancellation = threading.Event()
        cancellation.set()
        with patch(
            "yap_server.agents.archivist_ingestion_runner.read_reviewed_capture_for_result"
        ) as read_capture:
            view = self.runner.stage(
                _request(),
                principal=_principal(),
                cancellation=cancellation,
            )

        self.assertEqual(view.status, "cancelled")
        read_capture.assert_not_called()
        self.assertEqual(self.core.calls, [])


if __name__ == "__main__":
    unittest.main()
