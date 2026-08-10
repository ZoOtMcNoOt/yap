from __future__ import annotations

import http.client
import json
import queue
import socket
import threading
from urllib.parse import urlsplit

from .governed_rag_agent import ReasoningRetryableError
from .knowledge_tool_contract import KnowledgeToolCancelled


class SglangReasoningClient:
    """Call one server-selected SGLang model over a bounded loopback connection."""

    def __init__(
        self,
        *,
        endpoint: str,
        model: str,
        timeout_seconds: int,
        maximum_response_bytes: int,
        maximum_output_tokens: int,
    ) -> None:
        parsed = urlsplit(endpoint)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "localhost"}
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or parsed.port is None
        ):
            raise ValueError("SGLang endpoint must be explicit loopback HTTP")
        if not model or len(model) > 256 or model.strip() != model:
            raise ValueError("SGLang model identity is invalid")
        if not 1 <= timeout_seconds <= 300:
            raise ValueError("SGLang timeout is invalid")
        if not 1 <= maximum_response_bytes <= 4_000_000:
            raise ValueError("SGLang response bound is invalid")
        if not 1 <= maximum_output_tokens <= 4_096:
            raise ValueError("SGLang output token bound is invalid")
        self._host = parsed.hostname
        self._port = parsed.port
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._maximum_response_bytes = maximum_response_bytes
        self._maximum_output_tokens = maximum_output_tokens

    def __call__(self, prompt: str, cancellation: threading.Event) -> str:
        if not isinstance(prompt, str) or not prompt:
            raise ValueError("SGLang prompt is invalid")
        if cancellation.is_set():
            raise KnowledgeToolCancelled("SGLang reasoning was cancelled")
        connection = http.client.HTTPConnection(
            self._host, self._port, timeout=self._timeout_seconds
        )
        outcome: queue.Queue[str | BaseException] = queue.Queue(maxsize=1)
        try:
            body = json.dumps(
                {
                    "model": self._model,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "Use only supplied governed context. Return the exact "
                                "requested JSON structure without extra text."
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0,
                    "max_tokens": self._maximum_output_tokens,
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {
                            "name": "governed_answer",
                            "strict": True,
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "answer": {"type": "string"},
                                    "citationConceptIds": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                },
                                "required": ["answer", "citationConceptIds"],
                                "additionalProperties": False,
                            },
                        },
                    },
                },
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
                ),
                daemon=True,
            )
            worker.start()
            while worker.is_alive():
                if cancellation.wait(0.01):
                    _close_connection(connection)
                    raise KnowledgeToolCancelled("SGLang reasoning was cancelled")
            result = outcome.get_nowait()
            if isinstance(result, BaseException):
                if isinstance(result, (OSError, http.client.HTTPException)):
                    raise ReasoningRetryableError(
                        "SGLang reasoning transport failed"
                    ) from result
                raise result
            return result
        finally:
            _close_connection(connection)


def _request(
    connection: http.client.HTTPConnection,
    body: bytes,
    maximum_response_bytes: int,
    outcome: queue.Queue[str | BaseException],
) -> None:
    try:
        connection.request(
            "POST",
            "/v1/chat/completions",
            body=body,
            headers={"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        response_body = response.read(maximum_response_bytes + 1)
        if response.status in {429, 502, 503, 504}:
            raise ReasoningRetryableError("SGLang reasoning is temporarily unavailable")
        if response.status != 200:
            raise RuntimeError("SGLang reasoning request was rejected")
        if len(response_body) > maximum_response_bytes:
            raise ValueError("SGLang response exceeds its byte bound")
        outcome.put_nowait(_response_content(response_body))
    except BaseException as error:
        outcome.put_nowait(error)


def _close_connection(connection: http.client.HTTPConnection) -> None:
    if connection.sock is not None:
        try:
            connection.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
    connection.close()


def _response_content(body: bytes) -> str:
    try:
        value = json.loads(body)
        choices = value["choices"]
        content = choices[0]["message"]["content"]
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError, TypeError) as error:
        raise ValueError("SGLang response differs from the contract") from error
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(content, str):
        raise ValueError("SGLang response differs from the contract")
    return content


__all__ = ["SglangReasoningClient"]
