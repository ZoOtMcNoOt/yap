from __future__ import annotations

import json

from yap_server.agents.librarian_query_service import (
    LibrarianQueryJobView,
    LibrarianQueryServiceError,
)

from .api_fixtures import HealthServerTestCase


def _request() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "searchText": "reviewed launch decision",
        "maximumResults": 3,
        "expectedGenerationSha256": None,
    }


class _Service:
    def __init__(self) -> None:
        self.submitted = []
        self.cancelled = []
        self.view = LibrarianQueryJobView(
            request_id="librarian-query-" + "1" * 32,
            status="queued",
        )
        self.submit_error: LibrarianQueryServiceError | None = None

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
        self.view = LibrarianQueryJobView(
            request_id=request_id,
            status="cancellation-requested",
        )
        return True


class LibrarianQueryApiTests(HealthServerTestCase):
    def setUp(self) -> None:
        self.service = _Service()
        self.librarian_query_service = self.service
        super().setUp()

    def test_submit_status_and_cancel_are_bounded_authenticated_routes(self) -> None:
        status, _, response = self._request("/v1/health")
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(response)["capabilities"]["librarianQueries"])

        status, headers, response = self._request(
            "/v1/librarian-queries",
            method="POST",
            headers={"Content-Type": "application/json"},
            data=json.dumps(_request(), separators=(",", ":")).encode(),
        )
        self.assertEqual(status, 202)
        self.assert_json_headers(headers, response)
        self.assertEqual(json.loads(response), self.service.view.to_wire())
        request, principal = self.service.submitted[0]
        self.assertEqual(request.search_text, "reviewed launch decision")
        self.assertEqual(request.maximum_results, 3)
        self.assertTrue(principal.tenant_id)
        self.assertTrue(principal.subject_id)

        path = f"/v1/librarian-queries/{self.service.view.request_id}"
        status, _, response = self._request(path)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(response)["status"], "queued")

        status, _, response = self._request(path, method="DELETE")
        self.assertEqual(status, 202)
        self.assertEqual(
            json.loads(response)["status"],
            "cancellation-requested",
        )
        self.assertEqual(
            self.service.cancelled,
            ["librarian-query-" + "1" * 32],
        )

    def test_invalid_request_and_unknown_query_fail_closed(self) -> None:
        value = _request()
        value["unexpected"] = True
        status, headers, body = self._request(
            "/v1/librarian-queries",
            method="POST",
            headers={"Content-Type": "application/json"},
            data=json.dumps(value).encode(),
        )
        self.assert_error(
            status,
            headers,
            body,
            expected_status=400,
            code="INVALID_LIBRARIAN_QUERY",
            message="Knowledge query request is invalid.",
        )

        status, headers, body = self._request(
            "/v1/librarian-queries/librarian-query-" + "9" * 32
        )
        self.assert_error(
            status,
            headers,
            body,
            expected_status=404,
            code="LIBRARIAN_QUERY_NOT_FOUND",
            message="The knowledge query does not exist.",
        )

    def test_capacity_error_is_public_safe_and_retryable(self) -> None:
        self.service.submit_error = LibrarianQueryServiceError(
            429,
            "LIBRARIAN_QUERY_CAPACITY",
            "Knowledge query capacity is temporarily unavailable.",
            retryable=True,
        )
        status, headers, body = self._request(
            "/v1/librarian-queries",
            method="POST",
            headers={"Content-Type": "application/json"},
            data=json.dumps(_request()).encode(),
        )
        self.assert_error(
            status,
            headers,
            body,
            expected_status=429,
            code="LIBRARIAN_QUERY_CAPACITY",
            message="Knowledge query capacity is temporarily unavailable.",
            retryable=True,
        )

    def test_route_method_contract_rejects_unlisted_operations(self) -> None:
        status, headers, body = self._request(
            "/v1/librarian-queries",
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

        status, headers, body = self._request(
            "/v1/librarian-queries/not-a-librarian-query"
        )
        self.assert_error(
            status,
            headers,
            body,
            expected_status=404,
            code="NOT_FOUND",
            message="Route not found.",
        )


if __name__ == "__main__":
    import unittest

    unittest.main()
