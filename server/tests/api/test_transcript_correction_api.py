from __future__ import annotations

import hashlib
import json

from yap_server.agents.transcript_correction_service import (
    TranscriptCorrectionJobView,
    TranscriptCorrectionServiceError,
)

from .api_fixtures import HealthServerTestCase


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _request() -> dict[str, object]:
    text = "Um, the dosage is 25 mg."
    return {
        "schemaVersion": 1,
        "sourceRevisionSha256": "a" * 64,
        "sourceSha256": _sha256(text),
        "segments": [
            {
                "segmentId": "segment-0001",
                "startCharacter": 0,
                "endCharacter": len(text),
                "startMilliseconds": 0,
                "endMilliseconds": 1_500,
                "languageBcp47": "en-US",
                "text": text,
                "textSha256": _sha256(text),
            }
        ],
    }


class _Service:
    def __init__(self) -> None:
        self.submitted = []
        self.cancelled = []
        self.view = TranscriptCorrectionJobView(
            request_id="scribe-1",
            status="queued",
            source_revision_sha256="a" * 64,
            source_sha256=_request()["sourceSha256"],
            terminology_snapshot_sha256="c" * 64,
            applied=False,
        )
        self.submit_error: TranscriptCorrectionServiceError | None = None

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
        self.view = TranscriptCorrectionJobView(
            request_id=request_id,
            status="cancellation-requested",
            source_revision_sha256=self.view.source_revision_sha256,
            source_sha256=self.view.source_sha256,
            terminology_snapshot_sha256=self.view.terminology_snapshot_sha256,
            applied=False,
        )
        return True


class TranscriptCorrectionApiTests(HealthServerTestCase):
    def setUp(self) -> None:
        self.service = _Service()
        self.transcript_correction_service = self.service
        super().setUp()

    def test_submit_status_and_cancel_are_bounded_authenticated_routes(self) -> None:
        status, _, response = self._request("/v1/health")
        self.assertEqual(status, 200)
        self.assertTrue(
            json.loads(response)["capabilities"]["transcriptCorrection"]
        )

        body = json.dumps(_request(), separators=(",", ":")).encode()
        status, headers, response = self._request(
            "/v1/transcript-corrections",
            method="POST",
            headers={"Content-Type": "application/json"},
            data=body,
        )
        self.assertEqual(status, 202)
        self.assert_json_headers(headers, response)
        self.assertEqual(json.loads(response), self.service.view.to_wire())
        self.assertEqual(len(self.service.submitted), 1)
        request, principal = self.service.submitted[0]
        self.assertEqual(request.source_sha256, _request()["sourceSha256"])
        self.assertTrue(principal.tenant_id)
        self.assertTrue(principal.subject_id)

        status, _, response = self._request("/v1/transcript-corrections/scribe-1")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(response)["status"], "queued")

        status, _, response = self._request(
            "/v1/transcript-corrections/scribe-1",
            method="DELETE",
        )
        self.assertEqual(status, 202)
        self.assertEqual(json.loads(response)["status"], "cancellation-requested")
        self.assertEqual(self.service.cancelled, ["scribe-1"])

    def test_invalid_source_and_unknown_request_fail_closed(self) -> None:
        value = _request()
        value["sourceSha256"] = "b" * 64
        status, headers, body = self._request(
            "/v1/transcript-corrections",
            method="POST",
            headers={"Content-Type": "application/json"},
            data=json.dumps(value).encode(),
        )
        self.assert_error(
            status,
            headers,
            body,
            expected_status=400,
            code="INVALID_TRANSCRIPT_CORRECTION",
            message="Transcript correction request is invalid.",
        )

        status, headers, body = self._request(
            "/v1/transcript-corrections/missing"
        )
        self.assert_error(
            status,
            headers,
            body,
            expected_status=404,
            code="TRANSCRIPT_CORRECTION_NOT_FOUND",
            message="The transcript correction request does not exist.",
        )

    def test_capacity_error_is_public_safe_and_retryable(self) -> None:
        self.service.submit_error = TranscriptCorrectionServiceError(
            429,
            "TRANSCRIPT_CORRECTION_CAPACITY",
            "Transcript correction capacity is temporarily unavailable.",
            retryable=True,
        )
        status, headers, body = self._request(
            "/v1/transcript-corrections",
            method="POST",
            headers={"Content-Type": "application/json"},
            data=json.dumps(_request()).encode(),
        )
        self.assert_error(
            status,
            headers,
            body,
            expected_status=429,
            code="TRANSCRIPT_CORRECTION_CAPACITY",
            message="Transcript correction capacity is temporarily unavailable.",
            retryable=True,
        )

    def test_route_method_contract_rejects_unlisted_operations(self) -> None:
        status, headers, body = self._request(
            "/v1/transcript-corrections",
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
