from __future__ import annotations

from dataclasses import dataclass
import http.client
import math
import re
import secrets
import socket
import threading
import time
from typing import Callable, Protocol

from yap_server.limits import MAX_WORKER_RESULT_BYTES
from yap_server.pools.authenticated_loopback_http import (
    HttpConnection as _HttpConnection,
    HttpResponse as _HttpResponse,
    LoopbackHttpResponseStatusError,
    decode_bounded_json_response,
    parse_numeric_loopback_http_endpoint,
    validate_private_api_key,
)
from yap_server.pools.batch_asr_worker import (
    MAX_AUDIO_SECONDS,
    MAX_ENCODED_AUDIO_BYTES,
)
from yap_server.pools.batch_contract import (
    ProviderCapacityUnavailable,
    ProviderServiceUnavailable,
    WorkerCancellationAcknowledged,
    WorkerContainmentError,
    WorkerExecutionError,
)
from yap_server.pools.model_lock import ModelPoolLock
from yap_server.transcript_text import canonical_transcript


_READINESS_TIMEOUT_SECONDS = 5.0
_CANCELLATION_ACK_SECONDS = 5.0
_POLL_SECONDS = 0.02
_MAX_JSON_RESPONSE_BYTES = MAX_WORKER_RESULT_BYTES
_MAX_METRICS_RESPONSE_BYTES = 2 * 1024 * 1024
_SEND_CHUNK_BYTES = 1024 * 1024
_REQUEST_ACTIVITY_LINE = re.compile(
    r"^(?P<name>vllm:num_requests_(?:running|waiting))"
    r"(?:\{[^{}]*\})?\s+"
    r"(?P<value>[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)"
    r"(?:\s+\d+)?$"
)


class _CancellableHttpConnection(_HttpConnection, Protocol):
    def cancel(self) -> None: ...


ConnectionFactory = Callable[[str, int, float], _CancellableHttpConnection]


@dataclass(slots=True)
class _ActiveRequest:
    completed: threading.Event
    cancel_requested: threading.Event
    dispatched: threading.Event
    connection: _CancellableHttpConnection | None = None


class _RequestCancelled(RuntimeError):
    pass


class VllmTranscriptionClient:
    """Cancellable, loopback-only client for vLLM's transcription endpoint."""

    def __init__(
        self,
        *,
        endpoint: str,
        api_key: str,
        timeout_seconds: float,
        connection_factory: ConnectionFactory | None = None,
    ) -> None:
        host, port = _parse_loopback_http_endpoint(endpoint)
        _validate_api_key(api_key)
        if timeout_seconds <= 0:
            raise ValueError("vLLM request timeout must be positive")
        self._host = host
        self._port = port
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._connection_factory = connection_factory or _open_http_connection
        self._shutdown = threading.Event()
        self._active_lock = threading.Lock()
        self._active: dict[str, _ActiveRequest] = {}

    def verify_ready(self, lock: ModelPoolLock) -> None:
        """Fail closed unless one exact locked model is served by pinned vLLM."""

        if "vllm" not in dict(lock.runtime_overlay_packages):
            raise WorkerExecutionError("vLLM runtime lock omitted its package version")
        expected_version = lock.runtime_reported_serving_version
        if expected_version is None:
            raise WorkerExecutionError("vLLM runtime lock omitted its reported version")
        version = self._get_json("/version", authenticated=False)
        if version != {"version": expected_version}:
            raise WorkerExecutionError("vLLM runtime version differs from the lock")
        models = self._get_json("/v1/models", authenticated=True)
        data = models.get("data") if isinstance(models, dict) else None
        if (
            not isinstance(models, dict)
            or models.get("object") != "list"
            or not isinstance(data, list)
            or len(data) != 1
            or not isinstance(data[0], dict)
            or data[0].get("id") != lock.model_id
            or data[0].get("object") != "model"
        ):
            raise WorkerExecutionError("vLLM served model differs from the lock")

    def verify_startup_idle(self) -> None:
        """Prove no request from a previous Yap owner remains in vLLM."""

        with self._active_lock:
            if self._active:
                raise WorkerContainmentError(
                    "vLLM startup reconciliation found local active requests"
                )
        running, waiting = self._request_activity()
        if running != 0 or waiting != 0:
            raise WorkerContainmentError(
                "vLLM still owns active requests from a previous runtime"
            )

    def transcribe(
        self,
        *,
        job_id: str,
        encoded_wav: bytes,
        model: str,
        language: str,
        cancellation: threading.Event,
        shutdown: threading.Event,
    ) -> str:
        if self._shutdown.is_set() or shutdown.is_set() or cancellation.is_set():
            raise WorkerCancellationAcknowledged(
                "vLLM transcription request was cancelled"
            )
        if not isinstance(encoded_wav, bytes) or not (
            1 <= len(encoded_wav) <= MAX_ENCODED_AUDIO_BYTES
        ):
            raise WorkerExecutionError("vLLM transcription audio is invalid")

        completed = threading.Event()
        active = _ActiveRequest(
            completed=completed,
            cancel_requested=threading.Event(),
            dispatched=threading.Event(),
        )
        outcome: dict[str, object | None] = {"result": None, "error": None}

        with self._active_lock:
            if job_id in self._active:
                raise WorkerExecutionError("vLLM request identity is already active")
            self._active[job_id] = active

        def execute() -> None:
            connection: _CancellableHttpConnection | None = None
            try:
                connection = self._connection_factory(
                    self._host,
                    self._port,
                    self._timeout_seconds,
                )
                with self._active_lock:
                    if self._active.get(job_id) is not active:
                        raise WorkerContainmentError(
                            "vLLM request ownership was lost"
                        )
                    active.connection = connection
                if (
                    active.cancel_requested.is_set()
                    or self._shutdown.is_set()
                    or shutdown.is_set()
                    or cancellation.is_set()
                ):
                    raise _RequestCancelled()
                outcome["result"] = self._post_transcription(
                    connection,
                    encoded_wav=encoded_wav,
                    model=model,
                    language=language,
                    cancellation=cancellation,
                    shutdown=shutdown,
                    cancel_requested=active.cancel_requested,
                    dispatched=active.dispatched,
                )
            except BaseException as error:
                outcome["error"] = error
            finally:
                with self._active_lock:
                    if self._active.get(job_id) is active:
                        self._active.pop(job_id, None)
                try:
                    if connection is not None:
                        connection.close()
                finally:
                    completed.set()

        request_thread = threading.Thread(
            target=execute,
            name=f"yap-vllm-http-{job_id}",
            daemon=True,
        )
        try:
            request_thread.start()
        except BaseException as error:
            with self._active_lock:
                if self._active.get(job_id) is active:
                    self._active.pop(job_id, None)
            completed.set()
            raise WorkerExecutionError("vLLM request thread did not start") from error
        deadline = time.monotonic() + self._timeout_seconds
        termination = "completed"
        containment_deadline: float | None = None
        while not completed.wait(_POLL_SECONDS):
            if self._shutdown.is_set() or shutdown.is_set() or cancellation.is_set():
                termination = "cancelled"
                containment_deadline = time.monotonic() + _CANCELLATION_ACK_SECONDS
                active.cancel_requested.set()
                self._close_active(job_id)
                break
            if time.monotonic() >= deadline:
                termination = "timed_out"
                containment_deadline = time.monotonic() + _CANCELLATION_ACK_SECONDS
                active.cancel_requested.set()
                self._close_active(job_id)
                break

        if (
            termination != "completed"
            and containment_deadline is not None
            and not completed.wait(
                max(0.0, containment_deadline - time.monotonic())
            )
        ):
            raise WorkerContainmentError(
                "vLLM HTTP request shutdown acknowledgement timed out"
            )
        request_thread.join(timeout=0)
        if termination == "cancelled":
            raise WorkerCancellationAcknowledged(
                "vLLM transcription request was cancelled"
            )
        if termination == "timed_out":
            raise WorkerExecutionError("vLLM transcription request timed out")
        error = outcome["error"]
        if error is not None:
            if isinstance(error, _RequestCancelled) and (
                self._shutdown.is_set() or shutdown.is_set() or cancellation.is_set()
            ):
                raise WorkerCancellationAcknowledged(
                    "vLLM transcription request was cancelled"
                )
            if isinstance(
                error,
                (ProviderCapacityUnavailable, WorkerContainmentError),
            ):
                raise error
            raise WorkerExecutionError("vLLM transcription request failed") from error
        result = outcome["result"]
        if not isinstance(result, str):
            raise WorkerExecutionError("vLLM transcription response is invalid")
        return result

    def wait_until_dispatched(self, job_id: str, *, timeout_seconds: float) -> bool:
        """Wait until one request body has crossed the loopback socket."""

        if timeout_seconds <= 0:
            raise ValueError("vLLM dispatch wait must be positive")
        deadline = time.monotonic() + timeout_seconds
        while not self._shutdown.is_set():
            with self._active_lock:
                active = self._active.get(job_id)
            if active is not None:
                return active.dispatched.wait(
                    max(0.0, deadline - time.monotonic())
                )
            if time.monotonic() >= deadline:
                return False
            time.sleep(_POLL_SECONDS)
        return False

    def close(self) -> None:
        self._shutdown.set()
        with self._active_lock:
            active = tuple(self._active.values())
        for request in active:
            request.cancel_requested.set()
            if request.connection is not None:
                request.connection.cancel()
        deadline = time.monotonic() + _CANCELLATION_ACK_SECONDS
        if any(
            not request.completed.wait(max(0.0, deadline - time.monotonic()))
            for request in active
        ):
            raise WorkerContainmentError("vLLM HTTP shutdown acknowledgement timed out")

    def _get_json(self, path: str, *, authenticated: bool) -> object:
        if self._shutdown.is_set():
            raise WorkerExecutionError("vLLM client is closed")
        connection: _CancellableHttpConnection | None = None
        try:
            connection = self._connection_factory(
                self._host,
                self._port,
                _READINESS_TIMEOUT_SECONDS,
            )
            connection.putrequest("GET", path)
            connection.putheader("Accept", "application/json")
            if authenticated:
                connection.putheader("Authorization", f"Bearer {self._api_key}")
            connection.endheaders()
            return _decode_json_response(connection.getresponse())
        except LoopbackHttpResponseStatusError as error:
            if error.status == 503:
                raise ProviderServiceUnavailable(
                    "vLLM is not ready"
                ) from error
            raise
        except WorkerExecutionError:
            raise
        except (OSError, http.client.HTTPException) as error:
            raise ProviderServiceUnavailable(
                "vLLM readiness endpoint is unavailable"
            ) from error
        except Exception as error:
            raise WorkerExecutionError("vLLM readiness probe failed") from error
        finally:
            if connection is not None:
                connection.close()

    def _request_activity(self) -> tuple[int, int]:
        if self._shutdown.is_set():
            raise WorkerExecutionError("vLLM client is closed")
        connection: _CancellableHttpConnection | None = None
        try:
            connection = self._connection_factory(
                self._host,
                self._port,
                _READINESS_TIMEOUT_SECONDS,
            )
            connection.putrequest("GET", "/metrics")
            connection.putheader("Accept", "text/plain")
            connection.endheaders()
            response = connection.getresponse()
            content_type = response.getheader("Content-Type")
            if (
                response.status != 200
                or not isinstance(content_type, str)
                or not content_type.lower().startswith("text/plain")
            ):
                raise WorkerExecutionError("vLLM request-activity probe is invalid")
            body = response.read(_MAX_METRICS_RESPONSE_BYTES + 1)
            if len(body) > _MAX_METRICS_RESPONSE_BYTES:
                raise WorkerExecutionError(
                    "vLLM request-activity response exceeds its bound"
                )
            try:
                text = body.decode("utf-8")
            except UnicodeDecodeError as error:
                raise WorkerExecutionError(
                    "vLLM request-activity response is not UTF-8"
                ) from error
            return _parse_request_activity(text)
        except WorkerExecutionError:
            raise
        except (OSError, http.client.HTTPException) as error:
            raise ProviderServiceUnavailable(
                "vLLM request-activity endpoint is unavailable"
            ) from error
        except Exception as error:
            raise WorkerExecutionError(
                "vLLM request-activity probe failed"
            ) from error
        finally:
            if connection is not None:
                connection.close()

    def _post_transcription(
        self,
        connection: _CancellableHttpConnection,
        *,
        encoded_wav: bytes,
        model: str,
        language: str,
        cancellation: threading.Event,
        shutdown: threading.Event,
        cancel_requested: threading.Event,
        dispatched: threading.Event,
    ) -> str:
        if (
            self._shutdown.is_set()
            or shutdown.is_set()
            or cancellation.is_set()
            or cancel_requested.is_set()
        ):
            raise _RequestCancelled()
        boundary = "yap-" + secrets.token_hex(24)
        prefix, suffix = _multipart_segments(
            boundary=boundary,
            model=model,
            language=language,
        )
        content_length = len(prefix) + len(encoded_wav) + len(suffix)
        connection.putrequest("POST", "/v1/audio/transcriptions")
        connection.putheader("Authorization", f"Bearer {self._api_key}")
        connection.putheader("Accept", "application/json")
        connection.putheader(
            "Content-Type",
            f"multipart/form-data; boundary={boundary}",
        )
        connection.putheader("Content-Length", str(content_length))
        connection.endheaders()
        connection.send(prefix)
        view = memoryview(encoded_wav)
        for offset in range(0, len(view), _SEND_CHUNK_BYTES):
            if (
                self._shutdown.is_set()
                or shutdown.is_set()
                or cancellation.is_set()
                or cancel_requested.is_set()
            ):
                raise _RequestCancelled()
            connection.send(view[offset : offset + _SEND_CHUNK_BYTES])
        connection.send(suffix)
        dispatched.set()
        status, payload = decode_bounded_json_response(
            connection.getresponse(),
            component="vLLM",
            maximum_bytes=_MAX_JSON_RESPONSE_BYTES,
            accepted_statuses=frozenset({200, 429}),
        )
        if status == 429:
            raise ProviderCapacityUnavailable("vLLM admission is full")
        if not isinstance(payload, dict) or set(payload) != {"text", "usage"}:
            raise WorkerExecutionError("vLLM transcription response shape is invalid")
        usage = payload["usage"]
        seconds = usage.get("seconds") if isinstance(usage, dict) else None
        if (
            not isinstance(usage, dict)
            or set(usage) != {"type", "seconds"}
            or usage.get("type") != "duration"
            or isinstance(seconds, bool)
            or not isinstance(seconds, int)
            or not 1 <= seconds <= MAX_AUDIO_SECONDS
        ):
            raise WorkerExecutionError("vLLM transcription usage is invalid")
        try:
            provider_text = payload["text"]
            return canonical_transcript(
                " ".join(provider_text.split()),
                "vLLM transcript",
            )
        except (AttributeError, ValueError) as error:
            raise WorkerExecutionError("vLLM transcription text is invalid") from error

    def _close_active(self, job_id: str) -> None:
        with self._active_lock:
            active = self._active.get(job_id)
        if active is not None and active.connection is not None:
            active.connection.cancel()


class _LoopbackHttpConnection(http.client.HTTPConnection):
    """HTTP connection whose cancellation wakes a blocked response read."""

    def cancel(self) -> None:
        active_socket = self.sock
        if active_socket is not None:
            try:
                active_socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        self.close()


def _open_http_connection(
    host: str,
    port: int,
    timeout: float,
) -> _CancellableHttpConnection:
    return _LoopbackHttpConnection(host, port, timeout=timeout)


def _parse_loopback_http_endpoint(endpoint: str) -> tuple[str, int]:
    return parse_numeric_loopback_http_endpoint(endpoint, component="vLLM")


def _parse_request_activity(text: str) -> tuple[int, int]:
    values = {
        "vllm:num_requests_running": 0,
        "vllm:num_requests_waiting": 0,
    }
    observed: set[str] = set()
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _REQUEST_ACTIVITY_LINE.fullmatch(stripped)
        if match is None:
            metric_name = stripped.split("{", 1)[0].split(None, 1)[0]
            if metric_name in values:
                raise ValueError("vLLM request-activity metric is malformed")
            continue
        name = match.group("name")
        value = float(match.group("value"))
        if not math.isfinite(value) or value < 0 or not value.is_integer():
            raise ValueError("vLLM request-activity metric is invalid")
        observed.add(name)
        values[name] += int(value)
    if observed != set(values):
        raise ValueError("vLLM request-activity metrics are incomplete")
    return (
        values["vllm:num_requests_running"],
        values["vllm:num_requests_waiting"],
    )


def _validate_api_key(api_key: str) -> None:
    validate_private_api_key(api_key, component="vLLM")


def _multipart_segments(
    *,
    boundary: str,
    model: str,
    language: str,
) -> tuple[bytes, bytes]:
    if (
        not boundary
        or not boundary.isascii()
        or not boundary.replace("-", "").isalnum()
    ):
        raise ValueError("multipart boundary is invalid")

    def field(name: str, value: str) -> bytes:
        if any(character in value for character in ("\0", "\r", "\n")):
            raise WorkerExecutionError("vLLM transcription field is invalid")
        return (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{value}\r\n"
        ).encode("utf-8")

    prefix = b"".join(
        (
            field("model", model),
            field("language", language),
            field("response_format", "json"),
            (
                f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="file"; '
                'filename="audio.wav"\r\n'
                "Content-Type: audio/wav\r\n\r\n"
            ).encode("ascii"),
        )
    )
    return prefix, f"\r\n--{boundary}--\r\n".encode("ascii")


def _decode_json_response(response: _HttpResponse) -> object:
    _status, payload = decode_bounded_json_response(
        response,
        component="vLLM",
        maximum_bytes=_MAX_JSON_RESPONSE_BYTES,
    )
    return payload
