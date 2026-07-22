from __future__ import annotations

from collections import deque
from dataclasses import replace
import json
import socket
import threading
import unittest

from yap_server.pools.batch_contract import (
    ProviderCapacityUnavailable,
    ProviderServiceUnavailable,
    WorkerCancellationAcknowledged,
    WorkerExecutionError,
)
from yap_server.pools.vllm_transcription_client import (
    VllmTranscriptionClient,
    _LoopbackHttpConnection,
    _parse_loopback_http_endpoint,
)

from .batch_asr_fixtures import test_lock as _test_lock


class _Response:
    def __init__(self, status: int, payload: object) -> None:
        self.status = status
        self._encoded = json.dumps(payload).encode("utf-8")

    def getheader(self, name: str) -> str | None:
        if name.lower() == "content-length":
            return str(len(self._encoded))
        if name.lower() == "content-type":
            return "application/json"
        return None

    def read(self, amount: int = -1) -> bytes:
        if amount < 0:
            amount = len(self._encoded)
        returned, self._encoded = self._encoded[:amount], self._encoded[amount:]
        return returned


class _Connection:
    def __init__(
        self,
        response: _Response | None,
        *,
        block_until_closed: bool = False,
    ) -> None:
        self.response = response
        self.block_until_closed = block_until_closed
        self.entered_response = threading.Event()
        self.closed = threading.Event()
        self.cancelled = threading.Event()
        self.request_line: tuple[str, str] | None = None
        self.headers: dict[str, str] = {}
        self.sent: list[bytes] = []

    def putrequest(self, method: str, path: str) -> None:
        self.request_line = (method, path)

    def putheader(self, name: str, value: str) -> None:
        self.headers[name] = value

    def endheaders(self) -> None:
        return

    def send(self, value: object) -> None:
        self.sent.append(bytes(value))

    def getresponse(self) -> _Response:
        self.entered_response.set()
        if self.block_until_closed:
            self.closed.wait(timeout=2)
            raise OSError("closed")
        assert self.response is not None
        return self.response

    def close(self) -> None:
        self.closed.set()

    def cancel(self) -> None:
        self.cancelled.set()
        self.close()


class _ConnectionFactory:
    def __init__(self, *connections: _Connection) -> None:
        self.connections = deque(connections)
        self.arguments: list[tuple[str, int, float]] = []

    def __call__(self, host: str, port: int, timeout: float) -> _Connection:
        self.arguments.append((host, port, timeout))
        return self.connections.popleft()


class _Socket:
    def __init__(self) -> None:
        self.shutdown_calls: list[int] = []
        self.closed = False

    def shutdown(self, how: int) -> None:
        self.shutdown_calls.append(how)

    def close(self) -> None:
        self.closed = True


class VllmTranscriptionClientTests(unittest.TestCase):
    def test_concrete_cancellation_shuts_down_socket_before_close(self) -> None:
        connection = _LoopbackHttpConnection("127.0.0.1", 8000, timeout=2)
        active_socket = _Socket()
        connection.sock = active_socket  # type: ignore[assignment]

        connection.cancel()

        self.assertEqual(active_socket.shutdown_calls, [socket.SHUT_RDWR])
        self.assertTrue(active_socket.closed)
        self.assertIsNone(connection.sock)

    def test_readiness_requires_the_exact_vllm_version_and_served_model(self) -> None:
        lock = _test_lock()
        lock = replace(
            lock,
            runtime_overlay_packages=(("vllm", "0.22.1+test"),),
            runtime_reported_serving_version="0.22.1+test.dev",
        )
        version = _Connection(_Response(200, {"version": "0.22.1+test.dev"}))
        models = _Connection(
            _Response(
                200,
                {
                    "object": "list",
                    "data": [
                        {
                            "id": lock.model_id,
                            "object": "model",
                            "root": "/models/asr",
                        }
                    ],
                },
            )
        )
        client = VllmTranscriptionClient(
            endpoint="http://127.0.0.1:8000",
            api_key="private-test-key",
            timeout_seconds=2,
            connection_factory=_ConnectionFactory(version, models),
        )

        client.verify_ready(lock)

        self.assertEqual(version.request_line, ("GET", "/version"))
        self.assertEqual(models.request_line, ("GET", "/v1/models"))
        self.assertEqual(
            models.headers["Authorization"],
            "Bearer private-test-key",
        )

    def test_readiness_rejects_a_reported_version_that_differs_from_the_lock(
        self,
    ) -> None:
        lock = replace(
            _test_lock(),
            runtime_overlay_packages=(("vllm", "0.22.1+test"),),
            runtime_reported_serving_version="0.22.1+expected.dev",
        )
        version = _Connection(_Response(200, {"version": "0.22.1+other.dev"}))
        client = VllmTranscriptionClient(
            endpoint="http://127.0.0.1:8000",
            api_key="private-test-key",
            timeout_seconds=2,
            connection_factory=_ConnectionFactory(version),
        )

        with self.assertRaisesRegex(WorkerExecutionError, "differs from the lock") as caught:
            client.verify_ready(lock)

        self.assertNotIsInstance(caught.exception, ProviderServiceUnavailable)

    def test_readiness_preserves_a_transient_service_unavailable_status(self) -> None:
        lock = replace(
            _test_lock(),
            runtime_overlay_packages=(("vllm", "0.22.1+test"),),
            runtime_reported_serving_version="0.22.1+test.dev",
        )
        client = VllmTranscriptionClient(
            endpoint="http://127.0.0.1:8000",
            api_key="private-test-key",
            timeout_seconds=2,
            connection_factory=_ConnectionFactory(
                _Connection(_Response(503, {"error": "loading"}))
            ),
        )

        with self.assertRaisesRegex(ProviderServiceUnavailable, "not ready"):
            client.verify_ready(lock)

    def test_readiness_does_not_retry_authentication_failure(self) -> None:
        lock = replace(
            _test_lock(),
            runtime_overlay_packages=(("vllm", "0.22.1+test"),),
            runtime_reported_serving_version="0.22.1+test.dev",
        )
        client = VllmTranscriptionClient(
            endpoint="http://127.0.0.1:8000",
            api_key="wrong-key",
            timeout_seconds=2,
            connection_factory=_ConnectionFactory(
                _Connection(_Response(401, {"error": "unauthorized"}))
            ),
        )

        with self.assertRaises(WorkerExecutionError) as caught:
            client.verify_ready(lock)

        self.assertNotIsInstance(caught.exception, ProviderServiceUnavailable)

    def test_readiness_retries_transport_failure_but_not_client_defects(self) -> None:
        lock = replace(
            _test_lock(),
            runtime_overlay_packages=(("vllm", "0.22.1+test"),),
            runtime_reported_serving_version="0.22.1+test.dev",
        )

        def unavailable(_host: str, _port: int, _timeout: float) -> _Connection:
            raise ConnectionRefusedError("not listening")

        unavailable_client = VllmTranscriptionClient(
            endpoint="http://127.0.0.1:8000",
            api_key="private-test-key",
            timeout_seconds=2,
            connection_factory=unavailable,
        )
        with self.assertRaises(ProviderServiceUnavailable):
            unavailable_client.verify_ready(lock)

        def broken(_host: str, _port: int, _timeout: float) -> _Connection:
            raise RuntimeError("broken factory")

        broken_client = VllmTranscriptionClient(
            endpoint="http://127.0.0.1:8000",
            api_key="private-test-key",
            timeout_seconds=2,
            connection_factory=broken,
        )
        with self.assertRaisesRegex(WorkerExecutionError, "probe failed") as caught:
            broken_client.verify_ready(lock)

        self.assertNotIsInstance(caught.exception, ProviderServiceUnavailable)

    def test_transcription_sends_one_bounded_multipart_request(self) -> None:
        connection = _Connection(
            _Response(
                200,
                {
                    "text": " \nhello\tworld \r\n",
                    "usage": {"type": "duration", "seconds": 1},
                },
            )
        )
        client = VllmTranscriptionClient(
            endpoint="http://[::1]:8000",
            api_key="private-test-key",
            timeout_seconds=2,
            connection_factory=_ConnectionFactory(connection),
        )

        transcript = client.transcribe(
            job_id="job-1",
            encoded_wav=b"RIFF-test-wav",
            model="CohereLabs/cohere-transcribe-03-2026",
            language="en",
            cancellation=threading.Event(),
            shutdown=threading.Event(),
        )

        self.assertEqual(transcript, "hello world")
        self.assertEqual(
            connection.request_line,
            ("POST", "/v1/audio/transcriptions"),
        )
        body = b"".join(connection.sent)
        self.assertIn(b'name="model"', body)
        self.assertIn(b"CohereLabs/cohere-transcribe-03-2026", body)
        self.assertIn(b'name="language"', body)
        self.assertIn(b"\r\n\r\nen\r\n", body)
        self.assertIn(b'name="response_format"', body)
        self.assertIn(b"\r\n\r\njson\r\n", body)
        self.assertIn(b'filename="audio.wav"', body)
        self.assertIn(b"RIFF-test-wav", body)
        self.assertEqual(
            int(connection.headers["Content-Length"]),
            len(body),
        )

    def test_transcription_preserves_retryable_provider_backpressure(self) -> None:
        connection = _Connection(_Response(429, {"error": "busy"}))
        client = VllmTranscriptionClient(
            endpoint="http://127.0.0.1:8000",
            api_key="private-test-key",
            timeout_seconds=2,
            connection_factory=_ConnectionFactory(connection),
        )

        with self.assertRaisesRegex(ProviderCapacityUnavailable, "admission is full"):
            client.transcribe(
                job_id="job-busy",
                encoded_wav=b"RIFF-test-wav",
                model="CohereLabs/cohere-transcribe-03-2026",
                language="en",
                cancellation=threading.Event(),
                shutdown=threading.Event(),
            )

    def test_cancellation_closes_and_joins_the_active_http_request(self) -> None:
        connection = _Connection(None, block_until_closed=True)
        cancellation = threading.Event()
        client = VllmTranscriptionClient(
            endpoint="http://127.0.0.1:8000",
            api_key="private-test-key",
            timeout_seconds=2,
            connection_factory=_ConnectionFactory(connection),
        )
        dispatch_observed: list[bool] = []

        def cancel_after_dispatch() -> None:
            dispatch_observed.append(
                client.wait_until_dispatched("job-1", timeout_seconds=1)
            )
            cancellation.set()

        timer = threading.Thread(target=cancel_after_dispatch)
        timer.start()
        with self.assertRaisesRegex(WorkerCancellationAcknowledged, "cancelled"):
            client.transcribe(
                job_id="job-1",
                encoded_wav=b"RIFF-test-wav",
                model="CohereLabs/cohere-transcribe-03-2026",
                language="en",
                cancellation=cancellation,
                shutdown=threading.Event(),
            )
        timer.join(timeout=1)

        self.assertFalse(timer.is_alive())
        self.assertEqual(dispatch_observed, [True])
        self.assertTrue(connection.cancelled.is_set())
        self.assertTrue(connection.closed.is_set())

    def test_dispatch_wait_times_out_for_an_unknown_request(self) -> None:
        client = VllmTranscriptionClient(
            endpoint="http://127.0.0.1:8000",
            api_key="private-test-key",
            timeout_seconds=2,
            connection_factory=_ConnectionFactory(),
        )

        self.assertFalse(
            client.wait_until_dispatched("missing", timeout_seconds=0.02)
        )

    def test_cancel_before_connection_creation_does_not_send_request(self) -> None:
        connection = _Connection(
            _Response(
                200,
                {
                    "text": "unexpected",
                    "usage": {"type": "duration", "seconds": 1},
                },
            )
        )
        factory_entered = threading.Event()
        release_factory = threading.Event()

        def delayed_connection(
            _host: str,
            _port: int,
            _timeout: float,
        ) -> _Connection:
            factory_entered.set()
            if not release_factory.wait(timeout=1):
                raise AssertionError("test connection factory was not released")
            return connection

        cancellation = threading.Event()
        client = VllmTranscriptionClient(
            endpoint="http://127.0.0.1:8000",
            api_key="private-test-key",
            timeout_seconds=2,
            connection_factory=delayed_connection,
        )
        outcome: list[BaseException] = []

        def run() -> None:
            try:
                client.transcribe(
                    job_id="job-1",
                    encoded_wav=b"RIFF-test-wav",
                    model="CohereLabs/cohere-transcribe-03-2026",
                    language="en",
                    cancellation=cancellation,
                    shutdown=threading.Event(),
                )
            except BaseException as error:
                outcome.append(error)

        request_thread = threading.Thread(target=run)
        try:
            request_thread.start()
            self.assertTrue(factory_entered.wait(timeout=1))
            cancellation.set()
            release_factory.set()
            request_thread.join(timeout=2)

            self.assertFalse(request_thread.is_alive())
            self.assertEqual(len(outcome), 1)
            self.assertIsInstance(outcome[0], WorkerCancellationAcknowledged)
            self.assertIsNone(connection.request_line)
        finally:
            release_factory.set()
            client.close()

    def test_connection_creation_failure_is_accounted_without_a_thread_leak(
        self,
    ) -> None:
        def fail_connection(_host: str, _port: int, _timeout: float) -> _Connection:
            raise OSError("connection unavailable")

        client = VllmTranscriptionClient(
            endpoint="http://127.0.0.1:8000",
            api_key="private-test-key",
            timeout_seconds=2,
            connection_factory=fail_connection,
        )

        with self.assertRaisesRegex(WorkerExecutionError, "request failed"):
            client.transcribe(
                job_id="job-1",
                encoded_wav=b"RIFF-test-wav",
                model="CohereLabs/cohere-transcribe-03-2026",
                language="en",
                cancellation=threading.Event(),
                shutdown=threading.Event(),
            )

    def test_rejects_non_loopback_or_ambiguous_endpoints_and_api_keys(self) -> None:
        self.assertEqual(
            _parse_loopback_http_endpoint("http://127.0.0.1:8000"),
            ("127.0.0.1", 8000),
        )
        self.assertEqual(
            _parse_loopback_http_endpoint("http://[::1]:8000"),
            ("::1", 8000),
        )
        for endpoint in (
            "https://127.0.0.1:8000",
            "http://localhost:8000",
            "http://192.168.1.2:8000",
            "http://user@127.0.0.1:8000",
            "http://127.0.0.1:8000/path",
            "http://127.0.0.1",
            "http://127.0.0.1:0",
        ):
            with self.subTest(endpoint=endpoint):
                with self.assertRaises(ValueError):
                    _parse_loopback_http_endpoint(endpoint)

        with self.assertRaisesRegex(ValueError, "API key"):
            VllmTranscriptionClient(
                endpoint="http://127.0.0.1:8000",
                api_key="line-one\nline-two",
                timeout_seconds=2,
            )
        with self.assertRaisesRegex(ValueError, "API key"):
            VllmTranscriptionClient(
                endpoint="http://127.0.0.1:8000",
                api_key="x" * 513,
                timeout_seconds=2,
            )


if __name__ == "__main__":
    unittest.main()
