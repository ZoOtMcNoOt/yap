from __future__ import annotations

import json

from yap_server.agents.coordinator_bundle_service import (
    CoordinatorBundleJobView,
    CoordinatorBundleServiceError,
)

from .api_fixtures import HealthServerTestCase


def _request() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "objective": "Coordinate the reviewed release proposals.",
        "maximumItems": 3,
        "expectedGenerationSha256": None,
    }


class _Service:
    def __init__(self) -> None:
        self.submitted = []
        self.cancelled = []
        self.view = CoordinatorBundleJobView(
            request_id="coordinator-bundle-" + "1" * 32,
            status="queued",
        )
        self.submit_error: CoordinatorBundleServiceError | None = None

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
        self.view = CoordinatorBundleJobView(
            request_id=request_id,
            status="cancellation-requested",
        )
        return True


class CoordinatorBundleApiTests(HealthServerTestCase):
    def setUp(self) -> None:
        self.service = _Service()
        self.coordinator_bundle_service = self.service
        super().setUp()

    def test_submit_status_cancel_and_health_capability(self) -> None:
        status, _, response = self._request("/v1/health")
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(response)["capabilities"]["coordinatorBundles"])

        status, headers, response = self._request(
            "/v1/coordinator-bundles",
            method="POST",
            headers={"Content-Type": "application/json"},
            data=json.dumps(_request(), separators=(",", ":")).encode(),
        )
        self.assertEqual(status, 202)
        self.assert_json_headers(headers, response)
        self.assertEqual(json.loads(response), self.service.view.to_wire())
        request, principal = self.service.submitted[0]
        self.assertEqual(
            request.objective,
            "Coordinate the reviewed release proposals.",
        )
        self.assertEqual(request.maximum_items, 3)
        self.assertIsNone(request.expected_generation_sha256)
        self.assertTrue(principal.tenant_id)
        self.assertTrue(principal.subject_id)

        path = f"/v1/coordinator-bundles/{self.service.view.request_id}"
        status, _, response = self._request(path)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(response)["status"], "queued")

        status, _, response = self._request(path, method="DELETE")
        self.assertEqual(status, 202)
        self.assertEqual(json.loads(response)["status"], "cancellation-requested")
        self.assertEqual(
            self.service.cancelled,
            ["coordinator-bundle-" + "1" * 32],
        )

    def test_invalid_request_and_unknown_identity_fail_closed(self) -> None:
        value = _request()
        value["unexpected"] = True
        status, headers, body = self._request(
            "/v1/coordinator-bundles",
            method="POST",
            headers={"Content-Type": "application/json"},
            data=json.dumps(value).encode(),
        )
        self.assert_error(
            status,
            headers,
            body,
            expected_status=400,
            code="INVALID_COORDINATOR_BUNDLE",
            message="Coordination-bundle request is invalid.",
        )

        status, headers, body = self._request(
            "/v1/coordinator-bundles/coordinator-bundle-" + "9" * 32
        )
        self.assert_error(
            status,
            headers,
            body,
            expected_status=404,
            code="COORDINATOR_BUNDLE_NOT_FOUND",
            message="The coordination-bundle request does not exist.",
        )

    def test_capacity_error_is_safe_retryable_and_methods_are_exact(self) -> None:
        self.service.submit_error = CoordinatorBundleServiceError(
            429,
            "COORDINATOR_BUNDLE_CAPACITY",
            "Coordination-bundle capacity is temporarily unavailable.",
            retryable=True,
        )
        status, headers, body = self._request(
            "/v1/coordinator-bundles",
            method="POST",
            headers={"Content-Type": "application/json"},
            data=json.dumps(_request()).encode(),
        )
        self.assert_error(
            status,
            headers,
            body,
            expected_status=429,
            code="COORDINATOR_BUNDLE_CAPACITY",
            message="Coordination-bundle capacity is temporarily unavailable.",
            retryable=True,
        )

        status, headers, body = self._request(
            "/v1/coordinator-bundles",
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
