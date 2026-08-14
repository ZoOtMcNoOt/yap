from __future__ import annotations

import json
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from http.server import HTTPServer, ThreadingHTTPServer
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from yap_server.api.app import create_server
from yap_server.api.request_io import MAX_REQUEST_BODY_BYTES
from yap_server.config import ServerAuthenticationSettings, ServerSettings
from yap_server.jobs import RecordingJobService

from tests.recording_job_fixtures import (
    ControlledJobProcessor,
    batch_api_recording_job_request,
)

__all__ = [
    "BatchJobApiTestCase",
    "ControlledJobProcessor",
    "HealthServerTestCase",
    "MAX_REQUEST_BODY_BYTES",
    "meeting_import_job_request",
]


class _CapturingLogger:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def info(self, message: str) -> None:
        self.messages.append(message)


class _BlockingStatusService:
    def __init__(self, saturation: int) -> None:
        self._saturation = saturation
        self._lock = threading.Lock()
        self.release = threading.Event()
        self.saturated = threading.Event()
        self.active = 0
        self.maximum_active = 0

    def for_principal(self, _principal: object) -> _BlockingStatusService:
        return self

    def get(self, job_id: str) -> dict[str, object]:
        with self._lock:
            self.active += 1
            self.maximum_active = max(self.maximum_active, self.active)
            if self.active >= self._saturation:
                self.saturated.set()
        try:
            if not self.release.wait(timeout=5):
                raise TimeoutError("test request was not released")
            return {"jobId": job_id, "status": "accepted"}
        finally:
            with self._lock:
                self.active -= 1


def meeting_import_job_request() -> dict[str, object]:
    return batch_api_recording_job_request()


class HealthServerTestCase(unittest.TestCase):
    asr_capabilities: dict[str, object] | None = None
    librarian_query_service: object | None = None
    student_question_service: object | None = None
    archivist_ingestion_service: object | None = None
    curator_proposal_service: object | None = None
    lid_preflight_service: object | None = None
    transcript_correction_service: object | None = None
    request_authenticator: object | None = None
    server_settings = ServerSettings(
        host="127.0.0.1",
        port=0,
        authentication=ServerAuthenticationSettings(mode="development_loopback"),
    )

    def setUp(self) -> None:
        self.logger = _CapturingLogger()
        self.server = create_server(
            self.server_settings,
            logger=self.logger,
            asr_capabilities=self.asr_capabilities,
            librarian_query_service=self.librarian_query_service,
            student_question_service=self.student_question_service,
            archivist_ingestion_service=self.archivist_ingestion_service,
            curator_proposal_service=self.curator_proposal_service,
            lid_preflight_service=self.lid_preflight_service,
            transcript_correction_service=self.transcript_correction_service,
            request_authenticator=self.request_authenticator,
        )
        self.assertIsInstance(self.server, HTTPServer)
        if (
            self.lid_preflight_service is None
            and self.librarian_query_service is None
            and self.student_question_service is None
            and self.archivist_ingestion_service is None
            and self.curator_proposal_service is None
            and self.transcript_correction_service is None
        ):
            self.assertNotIsInstance(self.server, ThreadingHTTPServer)
        else:
            self.assertIsInstance(self.server, ThreadingHTTPServer)
        host, port = self.server.server_address[:2]
        self.base_url = f"http://{host}:{port}"
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            kwargs={"poll_interval": 0.01},
            daemon=True,
        )
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.assertFalse(self.thread.is_alive(), "health server did not stop cleanly")

    def _request(
        self,
        path: str,
        *,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        data: bytes | None = None,
        timeout: float = 2,
    ) -> tuple[int, Any, bytes]:
        request = Request(
            f"{self.base_url}{path}",
            data=data,
            headers=headers or {},
            method=method,
        )
        try:
            response = urlopen(request, timeout=timeout)
        except HTTPError as error:
            response = error
        with response:
            body = response.read()
            return response.status, response.headers, body

    def _raw_request(self, request: bytes) -> bytes:
        host, port = self.server.server_address[:2]
        with socket.create_connection((host, port), timeout=2) as client:
            client.sendall(request)
            client.shutdown(socket.SHUT_WR)
            response = bytearray()
            while chunk := client.recv(4096):
                response.extend(chunk)
        return bytes(response)

    def _parse_raw_json_response(
        self, response: bytes
    ) -> tuple[int, dict[str, object]]:
        head, body = response.split(b"\r\n\r\n", 1)
        status = int(head.split(b"\r\n", 1)[0].split()[1])
        return status, json.loads(body)

    def assert_json_headers(self, headers: Any, body: bytes) -> None:
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(int(headers["Content-Length"]), len(body))

    def assert_error(
        self,
        status: int,
        headers: Any,
        body: bytes,
        *,
        expected_status: int,
        code: str,
        message: str,
        retryable: bool = False,
    ) -> dict[str, object]:
        self.assertEqual(status, expected_status)
        self.assert_json_headers(headers, body)
        payload = json.loads(body)
        request_id = payload.get("requestId")
        self.assertIsInstance(request_id, str)
        self.assertRegex(request_id, r"^req-[0-9a-f]{32}$")
        self.assertEqual(
            payload,
            {
                "code": code,
                "message": message,
                "retryable": retryable,
                "requestId": request_id,
            },
        )
        return payload


class BatchJobApiTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.processor = ControlledJobProcessor()
        self.logger = _CapturingLogger()
        self.jobs = RecordingJobService(
            Path(self.temporary.name),
            processor=self.processor,
            supported_languages=("en",),
            now=lambda: "2026-07-14T21:10:00Z",
        )
        self.server = create_server(
            ServerSettings(
                host="127.0.0.1",
                port=0,
                authentication=ServerAuthenticationSettings(
                    mode="development_loopback"
                ),
            ),
            logger=self.logger,
            job_service=self.jobs,
        )
        self.assertIsInstance(self.server, ThreadingHTTPServer)
        host, port = self.server.server_address[:2]
        self.base_url = f"http://{host}:{port}"
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            kwargs={"poll_interval": 0.01},
            daemon=True,
        )
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.assertFalse(self.thread.is_alive())
        self.temporary.cleanup()

    def _request(
        self,
        path: str,
        *,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        data: bytes | None = None,
    ) -> tuple[int, Any, dict[str, object]]:
        request = Request(
            f"{self.base_url}{path}",
            data=data,
            headers=headers or {},
            method=method,
        )
        try:
            response = urlopen(request, timeout=2)
        except HTTPError as error:
            response = error
        with response:
            body = response.read()
            return response.status, response.headers, json.loads(body)
