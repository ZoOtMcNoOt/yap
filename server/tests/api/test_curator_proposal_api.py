from __future__ import annotations

import json

from yap_server.agents.curator_proposal_service import (
    CuratorProposalJobView,
    CuratorProposalServiceError,
)

from .api_fixtures import HealthServerTestCase


def _request() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "submissionId": "submission-1",
        "trigger": "explicit-proposal",
        "expectedGenerationSha256": "a" * 64,
        "reviewedContent": "The reviewed release remains blocked.",
        "sourceCitations": [
            {
                "conceptId": "meetings/job-1",
                "sourceRevision": "b" * 64,
                "contentSha256": "c" * 64,
                "charStart": 0,
                "charEnd": 28,
            }
        ],
    }


class _Service:
    def __init__(self) -> None:
        self.submitted = []
        self.cancelled = []
        self.view = CuratorProposalJobView(
            request_id="curator-proposal-" + "1" * 32,
            submission_id="submission-1",
            status="queued",
            generation_sha256="a" * 64,
        )
        self.submit_error: CuratorProposalServiceError | None = None

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
        self.view = CuratorProposalJobView(
            request_id=request_id,
            submission_id="submission-1",
            status="cancellation-requested",
            generation_sha256="a" * 64,
        )
        return True


class CuratorProposalApiTests(HealthServerTestCase):
    def setUp(self) -> None:
        self.service = _Service()
        self.curator_proposal_service = self.service
        super().setUp()

    def test_submit_status_cancel_and_health_capability(self) -> None:
        status, _, response = self._request("/v1/health")
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(response)["capabilities"]["curatorProposals"])

        status, headers, response = self._request(
            "/v1/curator-proposals",
            method="POST",
            headers={"Content-Type": "application/json"},
            data=json.dumps(_request(), separators=(",", ":")).encode(),
        )
        self.assertEqual(status, 202)
        self.assert_json_headers(headers, response)
        self.assertEqual(json.loads(response), self.service.view.to_wire())
        request, principal = self.service.submitted[0]
        self.assertEqual(request.submission_id, "submission-1")
        self.assertEqual(request.trigger, "explicit-proposal")
        self.assertTrue(principal.tenant_id)
        self.assertTrue(principal.subject_id)

        path = f"/v1/curator-proposals/{self.service.view.request_id}"
        status, _, response = self._request(path)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(response)["status"], "queued")

        status, _, response = self._request(path, method="DELETE")
        self.assertEqual(status, 202)
        self.assertEqual(json.loads(response)["status"], "cancellation-requested")

    def test_invalid_request_unknown_identity_and_capacity_fail_closed(self) -> None:
        value = _request()
        value["unexpected"] = True
        status, headers, body = self._request(
            "/v1/curator-proposals",
            method="POST",
            headers={"Content-Type": "application/json"},
            data=json.dumps(value).encode(),
        )
        self.assert_error(
            status,
            headers,
            body,
            expected_status=400,
            code="INVALID_CURATOR_PROPOSAL",
            message="Knowledge-proposal request is invalid.",
        )

        status, headers, body = self._request(
            "/v1/curator-proposals/curator-proposal-" + "9" * 32
        )
        self.assert_error(
            status,
            headers,
            body,
            expected_status=404,
            code="CURATOR_PROPOSAL_NOT_FOUND",
            message="The knowledge-proposal request does not exist.",
        )

        self.service.submit_error = CuratorProposalServiceError(
            429,
            "CURATOR_PROPOSAL_CAPACITY",
            "Knowledge-proposal capacity is temporarily unavailable.",
            retryable=True,
        )
        status, headers, body = self._request(
            "/v1/curator-proposals",
            method="POST",
            headers={"Content-Type": "application/json"},
            data=json.dumps(_request()).encode(),
        )
        self.assert_error(
            status,
            headers,
            body,
            expected_status=429,
            code="CURATOR_PROPOSAL_CAPACITY",
            message="Knowledge-proposal capacity is temporarily unavailable.",
            retryable=True,
        )


if __name__ == "__main__":
    import unittest

    unittest.main()
