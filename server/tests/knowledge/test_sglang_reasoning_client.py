from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time
import unittest

from yap_server.knowledge.governed_rag_agent import ReasoningRetryableError
from yap_server.knowledge.knowledge_tool_contract import KnowledgeToolCancelled
from yap_server.knowledge.sglang_reasoning_client import SglangReasoningClient


class _Handler(BaseHTTPRequestHandler):
    status = 200
    observed: dict[str, object] | None = None
    delay_seconds = 0.0

    def do_POST(self) -> None:
        length = int(self.headers["Content-Length"])
        type(self).observed = json.loads(self.rfile.read(length))
        time.sleep(type(self).delay_seconds)
        body = json.dumps(
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "answer": "Bound answer.",
                                    "citationConceptIds": ["concept-1"],
                                }
                            )
                        }
                    }
                ]
            }
        ).encode()
        self.send_response(type(self).status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            pass

    def log_message(self, format: str, *args: object) -> None:
        pass


class SglangReasoningClientTests(unittest.TestCase):
    def setUp(self) -> None:
        _Handler.status = 200
        _Handler.observed = None
        _Handler.delay_seconds = 0.0
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.client = SglangReasoningClient(
            endpoint=f"http://127.0.0.1:{self.server.server_port}",
            model="selected/model",
            timeout_seconds=2,
            maximum_response_bytes=10_000,
            maximum_output_tokens=100,
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

    def test_rejects_cancelled_and_retryable_requests(self) -> None:
        cancelled = threading.Event()
        cancelled.set()
        with self.assertRaises(KnowledgeToolCancelled):
            self.client("governed prompt", cancelled)

        _Handler.status = 503
        with self.assertRaises(ReasoningRetryableError):
            self.client("governed prompt", threading.Event())

    def test_cancels_in_flight_request(self) -> None:
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
        request.join(timeout=1.0)

        self.assertFalse(request.is_alive())
        self.assertIsInstance(outcome[0], KnowledgeToolCancelled)


if __name__ == "__main__":
    unittest.main()
