from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time
import unittest

from yap_server.knowledge.governed_rag_agent import ReasoningRetryableError
from yap_server.knowledge.knowledge_tool_contract import KnowledgeToolCancelled
from yap_server.knowledge.vllm_reasoning_client import VllmReasoningClient


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request: object, client_address: object) -> None:
        pass


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    status = 200
    observed: dict[str, object] | None = None
    delay_seconds = 0.0
    trickle_seconds = 0.0

    def do_POST(self) -> None:
        length = int(self.headers["Content-Length"])
        type(self).observed = json.loads(self.rfile.read(length))
        time.sleep(type(self).delay_seconds)
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
    def setUp(self) -> None:
        _Handler.status = 200
        _Handler.observed = None
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

    def test_fails_closed_when_transport_does_not_acknowledge_cancellation(
        self,
    ) -> None:
        _Handler.delay_seconds = 2.0
        cancellation = threading.Event()
        outcome: list[BaseException] = []

        def call() -> None:
            try:
                self.client("governed prompt", cancellation)
            except BaseException as error:
                outcome.append(error)

        request = threading.Thread(target=call)
        request.start()
        time.sleep(0.1)
        cancellation.set()
        request.join(timeout=2.0)

        self.assertFalse(request.is_alive())
        self.assertIsInstance(outcome[0], RuntimeError)
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
