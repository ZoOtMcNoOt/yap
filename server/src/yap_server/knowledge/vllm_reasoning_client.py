from __future__ import annotations

import http.client
import json
import queue
import socket
import threading
import time

from yap_server.pools.authenticated_loopback_http import (
    parse_numeric_loopback_http_endpoint,
)

from .agent_reasoning_routes import ReasoningRetryableError
from .governed_answer_protocol import (
    FINAL_RESPONSE_PROTOCOLS,
    governed_answer_json,
    governed_answer_request_fields,
)
from .knowledge_tool_contract import KnowledgeToolCancelled


class BoundedVllmJsonClient:
    """Exchange bounded JSON with one loopback vLLM endpoint."""

    def __init__(
        self,
        *,
        endpoint: str,
        timeout_seconds: int,
        maximum_response_bytes: int,
    ) -> None:
        host, port = parse_numeric_loopback_http_endpoint(
            endpoint,
            component="vLLM reasoning",
        )
        if not 1 <= timeout_seconds <= 300:
            raise ValueError("vLLM timeout is invalid")
        if not 1 <= maximum_response_bytes <= 4_000_000:
            raise ValueError("vLLM response bound is invalid")
        self._host = host
        self._port = port
        self._timeout_seconds = timeout_seconds
        self._maximum_response_bytes = maximum_response_bytes

    def request(
        self,
        payload: dict[str, object],
        cancellation: threading.Event,
        dispatched: threading.Event | None = None,
    ) -> dict[str, object]:
        if not isinstance(payload, dict) or not payload:
            raise ValueError("vLLM request payload is invalid")
        if cancellation.is_set():
            raise KnowledgeToolCancelled("vLLM reasoning was cancelled")
        connection = http.client.HTTPConnection(
            self._host, self._port, timeout=self._timeout_seconds
        )
        outcome: queue.Queue[dict[str, object] | BaseException] = queue.Queue(
            maxsize=1
        )
        try:
            body = json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            worker = threading.Thread(
                target=_request,
                args=(
                    connection,
                    body,
                    self._maximum_response_bytes,
                    outcome,
                    dispatched,
                ),
                daemon=True,
            )
            worker.start()
            deadline = time.monotonic() + self._timeout_seconds
            while worker.is_alive():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    _close_connection(connection)
                    worker.join(timeout=1.0)
                    if worker.is_alive():
                        raise RuntimeError("vLLM reasoning transport did not stop")
                    raise ReasoningRetryableError("vLLM reasoning timed out")
                if cancellation.wait(min(0.01, remaining)):
                    _close_connection(connection)
                    worker.join(timeout=1.0)
                    if worker.is_alive():
                        raise RuntimeError("vLLM reasoning transport did not stop")
                    raise KnowledgeToolCancelled("vLLM reasoning was cancelled")
            result = outcome.get_nowait()
            if isinstance(result, BaseException):
                if isinstance(result, (OSError, http.client.HTTPException)):
                    raise ReasoningRetryableError(
                        "vLLM reasoning transport failed"
                    ) from result
                raise result
            return result
        finally:
            _close_connection(connection)


class VllmReasoningClient:
    """Call one server-selected vLLM model over a bounded loopback connection."""

    def __init__(
        self,
        *,
        endpoint: str,
        model: str,
        timeout_seconds: int,
        maximum_response_bytes: int,
        maximum_output_tokens: int,
        final_response_protocol: str,
    ) -> None:
        if not model or len(model) > 256 or model.strip() != model:
            raise ValueError("vLLM model identity is invalid")
        if not 1 <= maximum_output_tokens <= 4_096:
            raise ValueError("vLLM output token bound is invalid")
        if final_response_protocol not in FINAL_RESPONSE_PROTOCOLS:
            raise ValueError("vLLM final response protocol is invalid")
        self._transport = BoundedVllmJsonClient(
            endpoint=endpoint,
            timeout_seconds=timeout_seconds,
            maximum_response_bytes=maximum_response_bytes,
        )
        self._model = model
        self._maximum_output_tokens = maximum_output_tokens
        self._final_response_protocol = final_response_protocol

    def __call__(self, prompt: str, cancellation: threading.Event) -> str:
        return self.request(prompt, cancellation, dispatched=None)

    def request(
        self,
        prompt: str,
        cancellation: threading.Event,
        dispatched: threading.Event | None,
    ) -> str:
        if not isinstance(prompt, str) or not prompt:
            raise ValueError("vLLM prompt is invalid")
        payload: dict[str, object] = {
            "model": self._model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Use only supplied governed context. Return the exact "
                        "requested answer structure without extra text."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
            "max_tokens": self._maximum_output_tokens,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        payload.update(
            governed_answer_request_fields(self._final_response_protocol)
        )
        response = self._transport.request(
            payload,
            cancellation,
            dispatched,
        )
        return governed_answer_json(response, self._final_response_protocol)


def _request(
    connection: http.client.HTTPConnection,
    body: bytes,
    maximum_response_bytes: int,
    outcome: queue.Queue[dict[str, object] | BaseException],
    dispatched: threading.Event | None,
) -> None:
    try:
        connection.request(
            "POST",
            "/v1/chat/completions",
            body=body,
            headers={"Content-Type": "application/json"},
        )
        if dispatched is not None:
            dispatched.set()
        response = connection.getresponse()
        response_body = response.read(maximum_response_bytes + 1)
        if response.status in {429, 502, 503, 504}:
            raise ReasoningRetryableError("vLLM reasoning is temporarily unavailable")
        if response.status != 200:
            raise RuntimeError("vLLM reasoning request was rejected")
        if len(response_body) > maximum_response_bytes:
            raise ValueError("vLLM response exceeds its byte bound")
        outcome.put_nowait(_response_json(response_body))
    except BaseException as error:
        outcome.put_nowait(error)


def _close_connection(connection: http.client.HTTPConnection) -> None:
    if connection.sock is not None:
        try:
            connection.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
    connection.close()


def _response_json(body: bytes) -> dict[str, object]:
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("vLLM response differs from the contract") from error
    if not isinstance(value, dict):
        raise ValueError("vLLM response differs from the contract")
    return value


__all__ = ["BoundedVllmJsonClient", "VllmReasoningClient"]
