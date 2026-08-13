from __future__ import annotations

import json

from yap_server.agents.archivist_ingestion_service import (
    ArchivistIngestionJobView,
    ArchivistIngestionServiceError,
)

from .api_fixtures import HealthServerTestCase


def _request() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "jobId": "job-1",
        "expectedResultSha256": "a" * 64,
    }


class _Service:
    def __init__(self) -> None:
        self.submitted = []
        self.cancelled = []
        self.view = ArchivistIngestionJobView(
            request_id="archivist-ingestion-" + "1" * 32,
            status="queued",
            job_id="job-1",
            result_sha256="a" * 64,
        )
        self.submit_error: ArchivistIngestionServiceError | None = None

    def submit(self, request, *, principal):
        if self.submit_error is not None:
            raise self.submit_error
        self.submitted.append((request, principal))
        return self.view

    def get(self, request_id, *, principal):
        del principal
        return self.view if request_id == self.view.request_id else None

    def cancel(self, request_id, *, principal):
        del principal
        if request_id != self.view.request_id:
            return False
        self.cancelled.append(request_id)
        self.view = ArchivistIngestionJobView(
            request_id=request_id,
            status="cancellation-requested",
            job_id="job-1",
            result_sha256="a" * 64,
        )
        return True


class ArchivistIngestionApiTests(HealthServerTestCase):
    def setUp(self) -> None:
        self.service = _Service()
        self.archivist_ingestion_service = self.service
        super().setUp()

    def test_submit_status_and_cancel_are_authenticated_and_owner_bound(self) -> None:
        status, _, response = self._request("/v1/health")
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(response)["capabilities"]["archivistIngestions"])

        status, headers, response = self._request(
            "/v1/archivist-ingestions",
            method="POST",
            headers={"Content-Type": "application/json"},
            data=json.dumps(_request(), separators=(",", ":")).encode(),
        )
        self.assertEqual(status, 202)
        self.assert_json_headers(headers, response)
        self.assertEqual(json.loads(response), self.service.view.to_wire())
        request, principal = self.service.submitted[0]
        self.assertEqual(request.job_id, "job-1")
        self.assertEqual(request.expected_result_sha256, "a" * 64)
        self.assertTrue(principal.tenant_id)
        self.assertTrue(principal.subject_id)

        path = f"/v1/archivist-ingestions/{self.service.view.request_id}"
        status, _, response = self._request(path)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(response)["status"], "queued")

        status, _, response = self._request(path, method="DELETE")
        self.assertEqual(status, 202)
        self.assertEqual(
            json.loads(response)["status"],
            "cancellation-requested",
        )

    def test_invalid_source_and_unknown_request_fail_closed(self) -> None:
        value = _request()
        value["transcript"] = "caller-controlled"
        status, headers, body = self._request(
            "/v1/archivist-ingestions",
            method="POST",
            headers={"Content-Type": "application/json"},
            data=json.dumps(value).encode(),
        )
        self.assert_error(
            status,
            headers,
            body,
            expected_status=400,
            code="INVALID_ARCHIVIST_INGESTION",
            message="Knowledge staging request is invalid.",
        )

        status, headers, body = self._request(
            "/v1/archivist-ingestions/archivist-ingestion-" + "9" * 32
        )
        self.assert_error(
            status,
            headers,
            body,
            expected_status=404,
            code="ARCHIVIST_INGESTION_NOT_FOUND",
            message="The knowledge staging request does not exist.",
        )

    def test_source_preflight_error_remains_public_safe(self) -> None:
        self.service.submit_error = ArchivistIngestionServiceError(
            404,
            "ARCHIVIST_SOURCE_NOT_FOUND",
            "The server transcript does not exist.",
            retryable=False,
            reason="invalid-reviewed-source",
        )
        status, headers, body = self._request(
            "/v1/archivist-ingestions",
            method="POST",
            headers={"Content-Type": "application/json"},
            data=json.dumps(_request()).encode(),
        )
        self.assert_error(
            status,
            headers,
            body,
            expected_status=404,
            code="ARCHIVIST_SOURCE_NOT_FOUND",
            message="The server transcript does not exist.",
        )

    def test_route_method_contract_is_exact(self) -> None:
        status, headers, body = self._request(
            "/v1/archivist-ingestions",
            method="GET",
        )
        self.assert_error(
            status,
            headers,
            body,
            expected_status=405,
            code="METHOD_NOT_ALLOWED",
            message="Method not allowed for this route.",
        )
        self.assertEqual(headers["Allow"], "POST")


if __name__ == "__main__":
    import unittest

    unittest.main()
