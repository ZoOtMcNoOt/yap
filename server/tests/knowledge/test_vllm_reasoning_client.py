from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time
import unittest
from unittest.mock import patch

from yap_server.knowledge import vllm_reasoning_client
from yap_server.knowledge.agent_reasoning_routes import ReasoningRetryableError
from yap_server.knowledge.knowledge_tool_contract import KnowledgeToolCancelled
from yap_server.knowledge.vllm_reasoning_client import (
    BoundedVllmJsonClient,
    VllmReasoningClient,
    VllmRequestRejected,
    VllmTransportNotContained,
)


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request: object, client_address: object) -> None:
        pass


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    status = 200
    observed: dict[str, object] | None = None
    observed_paths: list[str] = []
    rendered_token_ids: object = [1, 2, 3]
    delay_seconds = 0.0
    trickle_seconds = 0.0

    def do_POST(self) -> None:
        length = int(self.headers["Content-Length"])
        type(self).observed = json.loads(self.rfile.read(length))
        type(self).observed_paths.append(self.path)
        time.sleep(type(self).delay_seconds)
        if self.path == "/v1/chat/completions/render":
            body = json.dumps({"token_ids": type(self).rendered_token_ids}).encode()
            self.send_response(type(self).status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if "tools" in type(self).observed:
            message = {
                "content": None,
                "tool_calls": [
                    {
                        "id": "answer-1",
                        "type": "function",
                        "function": {
                            "name": "return_governed_answer",
                            "arguments": json.dumps(
                                {
                                    "answer": "Bound answer.",
                                    "citationConceptIds": ["concept-1"],
                                }
                            ),
                        },
                    }
                ],
            }
        else:
            message = {
                "content": json.dumps(
                    {
                        "answer": "Bound answer.",
                        "citationConceptIds": ["concept-1"],
                    }
                )
            }
        body = json.dumps(
            {
                "choices": [
                    {
                        "message": message,
                    }
                ]
            }
        ).encode()
        self.send_response(type(self).status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            if type(self).trickle_seconds:
                for byte in body:
                    self.wfile.write(bytes((byte,)))
                    self.wfile.flush()
                    time.sleep(type(self).trickle_seconds)
            else:
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            pass

    def log_message(self, format: str, *args: object) -> None:
        pass


class VllmReasoningClientTests(unittest.TestCase):
    def test_transport_requires_numeric_loopback_authority(self) -> None:
        for endpoint in (
            "http://localhost:8000",
            "http://user@127.0.0.1:8000",
            "http://127.0.0.1:8000/",
            "http://127.0.0.1:8000?query=1",
            "http://127.0.0.1:8000#fragment",
            "http://192.0.2.1:8000",
            "http://127.0.0.1:0",
        ):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                BoundedVllmJsonClient(
                    endpoint=endpoint,
                    timeout_seconds=1,
                    maximum_response_bytes=1,
                )
        for endpoint in ("http://127.0.0.1:8000", "http://[::1]:8000"):
            with self.subTest(endpoint=endpoint):
                BoundedVllmJsonClient(
                    endpoint=endpoint,
                    timeout_seconds=1,
                    maximum_response_bytes=1,
                )

    def setUp(self) -> None:
        _Handler.status = 200
        _Handler.observed = None
        _Handler.observed_paths = []
        _Handler.rendered_token_ids = [1, 2, 3]
        _Handler.delay_seconds = 0.0
        _Handler.trickle_seconds = 0.0
        self.server = _Server(("127.0.0.1", 0), _Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.client = VllmReasoningClient(
            endpoint=f"http://127.0.0.1:{self.server.server_port}",
            model="selected/model",
            timeout_seconds=2,
            maximum_response_bytes=10_000,
            maximum_output_tokens=100,
            final_response_protocol="json-schema",
        )

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_returns_only_structured_content_from_loopback_response(self) -> None:
        content = self.client("governed prompt", threading.Event())

        self.assertEqual(
            json.loads(content),
            {"answer": "Bound answer.", "citationConceptIds": ["concept-1"]},
        )
        self.assertEqual(_Handler.observed["model"], "selected/model")
        self.assertEqual(_Handler.observed["max_tokens"], 100)
        self.assertEqual(_Handler.observed["seed"], 0)
        self.assertEqual(_Handler.observed["n"], 1)
        self.assertEqual(
            _Handler.observed["chat_template_kwargs"], {"enable_thinking": False}
        )
        self.assertIn("response_format", _Handler.observed)

    def test_uses_forced_answer_tool_for_native_gemma_structure(self) -> None:
        client = VllmReasoningClient(
            endpoint=f"http://127.0.0.1:{self.server.server_port}",
            model="selected/model",
            timeout_seconds=2,
            maximum_response_bytes=10_000,
            maximum_output_tokens=100,
            final_response_protocol="forced-answer-tool",
        )

        content = client("governed prompt", threading.Event())

        self.assertEqual(
            json.loads(content),
            {"answer": "Bound answer.", "citationConceptIds": ["concept-1"]},
        )
        self.assertNotIn("response_format", _Handler.observed)
        self.assertEqual(
            _Handler.observed["tool_choice"],
            {
                "type": "function",
                "function": {"name": "return_governed_answer"},
            },
        )

    def test_rejects_cancelled_and_retryable_requests(self) -> None:
        cancelled = threading.Event()
        cancelled.set()
        with self.assertRaises(KnowledgeToolCancelled):
            self.client("governed prompt", cancelled)

        _Handler.status = 503
        with self.assertRaises(ReasoningRetryableError):
            self.client("governed prompt", threading.Event())

        _Handler.status = 401
        with self.assertRaises(VllmRequestRejected):
            self.client("governed prompt", threading.Event())

    def test_render_chat_counts_exact_tokens_and_fails_closed(self) -> None:
        transport = BoundedVllmJsonClient(
            endpoint=f"http://127.0.0.1:{self.server.server_port}",
            timeout_seconds=2,
            maximum_response_bytes=10_000,
        )
        payload = {"model": "selected/model", "messages": [{"role": "user"}]}

        self.assertEqual(
            transport.render_chat_token_count(payload, threading.Event()),
            3,
        )
        self.assertEqual(_Handler.observed_paths, ["/v1/chat/completions/render"])

        for invalid in ([], [1, True], [1, -1], "tokens"):
            with self.subTest(invalid=invalid):
                _Handler.rendered_token_ids = invalid
                with self.assertRaisesRegex(ValueError, "rendered token response"):
                    transport.render_chat_token_count(payload, threading.Event())

        _Handler.status = 400
        with self.assertRaisesRegex(ValueError, "exceeds or differs"):
            transport.render_chat_token_count(payload, threading.Event())

    def test_deep_json_is_a_bounded_contract_failure(self) -> None:
        with self.assertRaisesRegex(ValueError, "differs from the contract"):
            vllm_reasoning_client._response_json(
                ("[" * 5_000 + "]" * 5_000).encode("utf-8")
            )

    def test_fails_closed_when_transport_does_not_acknowledge_cancellation(
        self,
    ) -> None:
        _Handler.delay_seconds = 2.0
        cancellation = threading.Event()
        dispatched = threading.Event()
        outcome: list[BaseException] = []
        close_attempts = 0
        close_connection = vllm_reasoning_client._close_connection

        def close_after_failed_acknowledgement(connection) -> None:
            nonlocal close_attempts
            close_attempts += 1
            if close_attempts > 1:
                close_connection(connection)

        def call() -> None:
            try:
                self.client.request(
                    "governed prompt",
                    cancellation,
                    dispatched,
                )
            except BaseException as error:
                outcome.append(error)

        request = threading.Thread(target=call)
        with patch.object(
            vllm_reasoning_client,
            "_close_connection",
            side_effect=close_after_failed_acknowledgement,
        ):
            request.start()
            self.assertTrue(dispatched.wait(timeout=1.0))
            cancellation.set()
            request.join(timeout=2.0)

        self.assertFalse(request.is_alive())
        self.assertIsInstance(outcome[0], VllmTransportNotContained)
        self.assertIn("transport did not stop", str(outcome[0]))

    def test_request_timeout_is_a_total_wall_clock_deadline(self) -> None:
        _Handler.trickle_seconds = 0.02
        client = VllmReasoningClient(
            endpoint=f"http://127.0.0.1:{self.server.server_port}",
            model="selected/model",
            timeout_seconds=1,
            maximum_response_bytes=10_000,
            maximum_output_tokens=100,
            final_response_protocol="json-schema",
        )
        started = time.monotonic()

        with self.assertRaises(ReasoningRetryableError):
            client("governed prompt", threading.Event())

        self.assertLess(time.monotonic() - started, 1.75)


if __name__ == "__main__":
    unittest.main()
