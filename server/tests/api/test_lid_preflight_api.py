from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer
import json
import threading
import unittest

from yap_server.lid.errors import (
    LidPreflightCancelled,
    LidPreflightConflict,
    LidPreflightUnavailable,
)
from yap_server.lid.preflight import LidPreflightBackpressure
from yap_server.lid.transport import LidTransportError, LidTransportStaleError

from .api_fixtures import HealthServerTestCase


MEDIA_TYPE = "application/vnd.yap.lid-preflight.v1+octet-stream"


class _LidService:
    def __init__(self) -> None:
        self.bodies: list[bytes] = []
        self.error: Exception | None = None
        self.cancelled: set[str] = set()

    def run_envelope(self, body: bytes) -> dict[str, object]:
        self.bodies.append(body)
        if self.error is not None:
            raise self.error
        return {
            "schemaVersion": 1,
            "requestId": "lid-request-01",
            "status": "manual",
            "suggestedLocale": None,
            "userConfirmationRequired": True,
        }

    def cancel(self, request_id: str) -> bool:
        if request_id not in self.cancelled:
            return False
        self.cancelled.remove(request_id)
        return True


class LidPreflightApiTests(HealthServerTestCase):
    def setUp(self) -> None:
        self.lid_service = _LidService()
        self.lid_preflight_service = self.lid_service
        super().setUp()

    def test_runs_bounded_binary_preflight_without_logging_probe_bytes(self) -> None:
        body = b"private-pcm-probes"

        status, headers, response = self._request(
            "/v1/lid/preflight",
            method="POST",
            headers={"Content-Type": MEDIA_TYPE},
            data=body,
        )

        self.assertIsInstance(self.server, ThreadingHTTPServer)
        self.assertEqual(status, 200)
        self.assert_json_headers(headers, response)
        self.assertEqual(self.lid_service.bodies, [body])
        self.assertEqual(json.loads(response)["status"], "manual")
        self.assertNotIn(body.decode("ascii"), "\n".join(self.logger.messages))

    def test_requires_the_versioned_binary_media_type(self) -> None:
        status, headers, response = self._request(
            "/v1/lid/preflight",
            method="POST",
            headers={"Content-Type": "application/octet-stream"},
            data=b"probe",
        )

        self.assert_error(
            status,
            headers,
            response,
            expected_status=415,
            code="UNSUPPORTED_MEDIA_TYPE",
            message="LID preflight requires its versioned binary media type.",
        )
        self.assertEqual(self.lid_service.bodies, [])

    def test_maps_invalid_and_stale_contracts_without_leaking_details(self) -> None:
        cases = (
            (
                LidTransportError("private source C:/secret/audio.wav"),
                400,
                "INVALID_LID_PREFLIGHT",
                "LID preflight request is invalid.",
            ),
            (
                LidTransportStaleError("private stale details"),
                409,
                "STALE_LID_PREFLIGHT_CONTRACT",
                "LID preflight contract identity is stale.",
            ),
        )
        for error, expected_status, code, message in cases:
            with self.subTest(code=code):
                self.lid_service.error = error
                status, headers, response = self._request(
                    "/v1/lid/preflight",
                    method="POST",
                    headers={"Content-Type": MEDIA_TYPE},
                    data=b"probe",
                )
                self.assert_error(
                    status,
                    headers,
                    response,
                    expected_status=expected_status,
                    code=code,
                    message=message,
                )
                self.assertNotIn("private", response.decode("utf-8"))

    def test_maps_capacity_conflict_cancellation_and_unavailability(self) -> None:
        cases = (
            (
                LidPreflightBackpressure("full"),
                429,
                "LID_PREFLIGHT_BUSY",
                "LID preflight capacity is temporarily full.",
                True,
            ),
            (
                LidPreflightConflict("duplicate"),
                409,
                "LID_PREFLIGHT_CONFLICT",
                "LID preflight request conflicts with active work.",
                False,
            ),
            (
                LidPreflightCancelled("cancelled"),
                409,
                "LID_PREFLIGHT_CANCELLED",
                "LID preflight request was cancelled.",
                False,
            ),
            (
                LidPreflightUnavailable("fenced"),
                503,
                "LID_PREFLIGHT_UNAVAILABLE",
                "LID preflight is temporarily unavailable.",
                True,
            ),
        )
        for error, expected_status, code, message, retryable in cases:
            with self.subTest(code=code):
                self.lid_service.error = error
                status, headers, response = self._request(
                    "/v1/lid/preflight",
                    method="POST",
                    headers={"Content-Type": MEDIA_TYPE},
                    data=b"probe",
                )
                self.assert_error(
                    status,
                    headers,
                    response,
                    expected_status=expected_status,
                    code=code,
                    message=message,
                    retryable=retryable,
                )
                if expected_status == 429:
                    self.assertEqual(headers["Retry-After"], "1")

    def test_cancel_is_explicit_and_unknown_requests_fail_closed(self) -> None:
        self.lid_service.cancelled.add("lid-request-01")

        status, headers, response = self._request(
            "/v1/lid/preflights/lid-request-01",
            method="DELETE",
        )

        self.assertEqual(status, 202)
        self.assert_json_headers(headers, response)
        self.assertEqual(
            json.loads(response),
            {
                "schemaVersion": 1,
                "requestId": "lid-request-01",
                "status": "cancellation_requested",
            },
        )

        status, headers, response = self._request(
            "/v1/lid/preflights/unknown",
            method="DELETE",
        )
        self.assert_error(
            status,
            headers,
            response,
            expected_status=404,
            code="LID_PREFLIGHT_NOT_FOUND",
            message="Active LID preflight request was not found.",
        )


class _BlockingLidService:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.cancelled = threading.Event()

    def run_envelope(self, body: bytes) -> dict[str, object]:
        if body != b"blocking-probe":
            raise AssertionError("unexpected test body")
        self.started.set()
        if not self.cancelled.wait(timeout=2):
            raise AssertionError("test preflight was not cancelled")
        raise LidPreflightCancelled("cancelled")

    def cancel(self, request_id: str) -> bool:
        if request_id != "lid-blocking-01" or not self.started.is_set():
            return False
        self.cancelled.set()
        return True


class LidPreflightCancellationApiTests(HealthServerTestCase):
    def setUp(self) -> None:
        self.blocking_service = _BlockingLidService()
        self.lid_preflight_service = self.blocking_service
        super().setUp()

    def test_delete_can_cancel_an_in_flight_post(self) -> None:
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(
                self._request,
                "/v1/lid/preflight",
                method="POST",
                headers={"Content-Type": MEDIA_TYPE},
                data=b"blocking-probe",
            )
            self.assertTrue(self.blocking_service.started.wait(timeout=1))
            cancel_status, _, _ = self._request(
                "/v1/lid/preflights/lid-blocking-01",
                method="DELETE",
            )
            status, headers, response = pending.result(timeout=2)

        self.assertEqual(cancel_status, 202)
        self.assert_error(
            status,
            headers,
            response,
            expected_status=409,
            code="LID_PREFLIGHT_CANCELLED",
            message="LID preflight request was cancelled.",
        )


if __name__ == "__main__":
    unittest.main()
