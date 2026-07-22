from __future__ import annotations

from dataclasses import dataclass
import http.client
import json
import threading
import time
from typing import Callable

from yap_server.limits import MAX_WORKER_RESULT_BYTES
from yap_server.pools.authenticated_loopback_http import (
    HttpConnection,
    LoopbackHttpResponseStatusError,
    decode_bounded_json_response,
    parse_numeric_loopback_http_endpoint,
    validate_private_api_key,
)
from yap_server.pools.batch_contract import (
    ProviderCapacityUnavailable,
    ProviderServiceUnavailable,
    WorkerCancellationAcknowledged,
    WorkerContainmentError,
    WorkerExecutionError,
)
from yap_server.pools.model_lock import ModelPoolLock
from yap_server.pools.nemotron_nemo_pipeline import (
    NEMOTRON_STREAMING_ATTENTION_CONTEXT,
    NEMOTRON_STREAMING_CHUNK_SECONDS,
    NEMOTRON_STREAMING_MAX_STREAMS,
)
from yap_server.pools.nemotron_nemo_protocol import (
    NEMOTRON_NEMO_MAX_REQUEST_BYTES,
    NEMOTRON_NEMO_READY_PATH,
    NEMOTRON_NEMO_TRANSCRIPTION_PATH,
    NemotronNemoServiceRequest,
    cancellation_path,
)


_READINESS_TIMEOUT_SECONDS = 5.0
_CANCELLATION_ACK_SECONDS = 5.0
_POLL_SECONDS = 0.02
_TRANSCRIPTION_STATUSES = frozenset({200, 409, 422, 429, 500, 503})
_CANCELLATION_STATUSES = frozenset({202, 404})


ConnectionFactory = Callable[[str, int, float], HttpConnection]


@dataclass(slots=True)
class _ActiveRequest:
    completed: threading.Event
    cancel_requested: threading.Event
    dispatched: threading.Event
    connection: HttpConnection | None = None


class NemotronNemoClient:
    """Cancellable client for Yap's authenticated resident NeMo adapter."""

    def __init__(
        self,
        *,
        endpoint: str,
        api_key: str,
        timeout_seconds: float,
        connection_factory: ConnectionFactory | None = None,
    ) -> None:
        host, port = parse_numeric_loopback_http_endpoint(
            endpoint,
            component="Nemotron NeMo",
        )
        validate_private_api_key(api_key, component="Nemotron NeMo")
        if timeout_seconds <= 0:
            raise ValueError("Nemotron NeMo request timeout must be positive")
        self._host = host
        self._port = port
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._connection_factory = connection_factory or _open_http_connection
        self._shutdown = threading.Event()
        self._active_lock = threading.Lock()
        self._active: dict[str, _ActiveRequest] = {}

    def verify_ready(self, lock: ModelPoolLock) -> None:
        self.readiness_capacity(lock)

    def readiness_capacity(self, lock: ModelPoolLock) -> dict[str, int]:
        """Return the authenticated bounded admission snapshot."""

        try:
            status, payload = self._request_json(
                method="GET",
                path=NEMOTRON_NEMO_READY_PATH,
                body=None,
                timeout_seconds=_READINESS_TIMEOUT_SECONDS,
                accepted_statuses=frozenset({200}),
            )
        except LoopbackHttpResponseStatusError as error:
            if error.status == 503:
                raise ProviderServiceUnavailable(
                    "resident Nemotron NeMo is not ready"
                ) from error
            raise
        if status != 200 or not _matches_readiness(payload, lock):
            raise WorkerExecutionError(
                "resident Nemotron NeMo identity differs from the model lock"
            )
        capacity = payload["capacity"]
        if not isinstance(capacity, dict):
            raise RuntimeError("validated resident NeMo capacity changed shape")
        return {
            "activeRequests": int(capacity["activeRequests"]),
            "maxActiveRequests": int(capacity["maxActiveRequests"]),
        }

    def transcribe(
        self,
        request: NemotronNemoServiceRequest,
        *,
        cancellation: threading.Event,
        shutdown: threading.Event,
    ) -> dict[str, object]:
        if self._shutdown.is_set() or shutdown.is_set() or cancellation.is_set():
            raise WorkerCancellationAcknowledged(
                "resident Nemotron NeMo request was cancelled"
            )
        body = json.dumps(
            request.to_payload(),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        if len(body) > NEMOTRON_NEMO_MAX_REQUEST_BYTES:
            raise WorkerExecutionError("resident Nemotron NeMo request is oversized")
        completed = threading.Event()
        active = _ActiveRequest(
            completed=completed,
            cancel_requested=threading.Event(),
            dispatched=threading.Event(),
        )
        outcome: dict[str, object | None] = {"result": None, "error": None}

        with self._active_lock:
            if request.job_id in self._active:
                raise WorkerExecutionError(
                    "resident Nemotron NeMo request identity is already active"
                )
            self._active[request.job_id] = active

        def execute() -> None:
            connection: HttpConnection | None = None
            try:
                connection = self._connection_factory(
                    self._host,
                    self._port,
                    self._timeout_seconds,
                )
                with self._active_lock:
                    if self._active.get(request.job_id) is not active:
                        raise WorkerContainmentError(
                            "resident Nemotron NeMo request ownership was lost"
                        )
                    active.connection = connection
                if (
                    active.cancel_requested.is_set()
                    or self._shutdown.is_set()
                    or shutdown.is_set()
                    or cancellation.is_set()
                ):
                    raise WorkerCancellationAcknowledged(
                        "resident Nemotron NeMo request was cancelled"
                    )
                status, payload = self._send_json(
                    connection,
                    method="POST",
                    path=NEMOTRON_NEMO_TRANSCRIPTION_PATH,
                    body=body,
                    accepted_statuses=_TRANSCRIPTION_STATUSES,
                    dispatched=active.dispatched,
                )
                if status == 429:
                    raise ProviderCapacityUnavailable(
                        "resident Nemotron NeMo admission is full"
                    )
                if status != 200 or not isinstance(payload, dict):
                    raise WorkerExecutionError(
                        "resident Nemotron NeMo transcription failed"
                    )
                outcome["result"] = payload
            except BaseException as error:
                outcome["error"] = error
            finally:
                with self._active_lock:
                    if self._active.get(request.job_id) is active:
                        self._active.pop(request.job_id, None)
                try:
                    if connection is not None:
                        connection.close()
                finally:
                    completed.set()

        request_thread = threading.Thread(
            target=execute,
            name=f"yap-nemotron-nemo-http-{request.job_id}",
            daemon=True,
        )
        try:
            request_thread.start()
        except BaseException as error:
            with self._active_lock:
                if self._active.get(request.job_id) is active:
                    self._active.pop(request.job_id, None)
            completed.set()
            raise WorkerExecutionError(
                "resident Nemotron NeMo request thread did not start"
            ) from error
        deadline = time.monotonic() + self._timeout_seconds
        termination = "completed"
        containment_deadline: float | None = None
        while not completed.wait(_POLL_SECONDS):
            if self._shutdown.is_set() or shutdown.is_set() or cancellation.is_set():
                termination = "cancelled"
                containment_deadline = time.monotonic() + _CANCELLATION_ACK_SECONDS
                try:
                    self._cancel_remote(
                        request.job_id,
                        active=active,
                        deadline=containment_deadline,
                    )
                except WorkerExecutionError:
                    self._close_active(request.job_id)
                break
            if time.monotonic() >= deadline:
                termination = "timed_out"
                containment_deadline = time.monotonic() + _CANCELLATION_ACK_SECONDS
                try:
                    self._cancel_remote(
                        request.job_id,
                        active=active,
                        deadline=containment_deadline,
                    )
                except WorkerExecutionError:
                    self._close_active(request.job_id)
                break

        if (
            termination != "completed"
            and containment_deadline is not None
            and not completed.wait(
                max(0.0, containment_deadline - time.monotonic())
            )
        ):
            self._close_active(request.job_id)
            raise WorkerContainmentError(
                "resident Nemotron NeMo cancellation acknowledgement timed out"
            )
        request_thread.join(timeout=0)
        if termination == "cancelled":
            raise WorkerCancellationAcknowledged(
                "resident Nemotron NeMo request was cancelled"
            )
        if termination == "timed_out":
            raise WorkerExecutionError("resident Nemotron NeMo request timed out")
        error = outcome["error"]
        if error is not None:
            if isinstance(
                error,
                (
                    ProviderCapacityUnavailable,
                    WorkerCancellationAcknowledged,
                    WorkerContainmentError,
                ),
            ):
                raise error
            raise WorkerExecutionError(
                "resident Nemotron NeMo request failed"
            ) from error
        result = outcome["result"]
        if not isinstance(result, dict):
            raise WorkerExecutionError("resident Nemotron NeMo result is invalid")
        return result

    def wait_until_dispatched(self, job_id: str, *, timeout_seconds: float) -> bool:
        """Wait until one request body has crossed the loopback socket."""

        if timeout_seconds <= 0:
            raise ValueError("Nemotron NeMo dispatch wait must be positive")
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
            active = tuple(self._active.items())
        deadline = time.monotonic() + _CANCELLATION_ACK_SECONDS
        for job_id, request in active:
            try:
                self._cancel_remote(job_id, active=request, deadline=deadline)
            except WorkerExecutionError:
                if request.connection is not None:
                    request.connection.close()
        if any(
            not request.completed.wait(max(0.0, deadline - time.monotonic()))
            for _job_id, request in active
        ):
            for _job_id, request in active:
                connection = request.connection
                if connection is not None:
                    connection.close()
            raise WorkerContainmentError(
                "resident Nemotron NeMo shutdown acknowledgement timed out"
            )

    def _cancel_remote(
        self,
        job_id: str,
        *,
        active: _ActiveRequest,
        deadline: float,
    ) -> None:
        active.cancel_requested.set()
        while True:
            if active.completed.is_set():
                return
            with self._active_lock:
                current = self._active.get(job_id)
                connection = active.connection if current is active else None
            if connection is None:
                if active.completed.is_set():
                    return
                if time.monotonic() >= deadline:
                    raise WorkerExecutionError(
                        "resident Nemotron NeMo cancellation was not admitted"
                    )
                time.sleep(_POLL_SECONDS)
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._close_active(job_id)
                raise WorkerExecutionError(
                    "resident Nemotron NeMo cancellation was not admitted"
                )
            status, _payload = self._request_json(
                method="DELETE",
                path=cancellation_path(job_id),
                body=None,
                timeout_seconds=remaining,
                accepted_statuses=_CANCELLATION_STATUSES,
            )
            if status == 202 or active.completed.is_set():
                return
            if time.monotonic() >= deadline:
                self._close_active(job_id)
                raise WorkerExecutionError(
                    "resident Nemotron NeMo cancellation was not admitted"
                )
            time.sleep(_POLL_SECONDS)

    def _close_active(self, job_id: str) -> None:
        with self._active_lock:
            active = self._active.get(job_id)
        if active is not None and active.connection is not None:
            active.connection.close()

    def _request_json(
        self,
        *,
        method: str,
        path: str,
        body: bytes | None,
        timeout_seconds: float,
        accepted_statuses: frozenset[int],
    ) -> tuple[int, object]:
        connection: HttpConnection | None = None
        try:
            connection = self._connection_factory(
                self._host,
                self._port,
                timeout_seconds,
            )
            return self._send_json(
                connection,
                method=method,
                path=path,
                body=body,
                accepted_statuses=accepted_statuses,
            )
        except WorkerExecutionError:
            raise
        except (OSError, http.client.HTTPException) as error:
            raise ProviderServiceUnavailable(
                "resident Nemotron NeMo HTTP request failed"
            ) from error
        except Exception as error:
            raise WorkerExecutionError(
                "resident Nemotron NeMo HTTP request failed"
            ) from error
        finally:
            if connection is not None:
                connection.close()

    def _send_json(
        self,
        connection: HttpConnection,
        *,
        method: str,
        path: str,
        body: bytes | None,
        accepted_statuses: frozenset[int],
        dispatched: threading.Event | None = None,
    ) -> tuple[int, object]:
        connection.putrequest(method, path)
        connection.putheader("Authorization", f"Bearer {self._api_key}")
        connection.putheader("Accept", "application/json")
        if body is not None:
            connection.putheader("Content-Type", "application/json")
            connection.putheader("Content-Length", str(len(body)))
        connection.endheaders()
        if body is not None:
            connection.send(body)
        if dispatched is not None:
            dispatched.set()
        return decode_bounded_json_response(
            connection.getresponse(),
            component="Nemotron NeMo",
            maximum_bytes=MAX_WORKER_RESULT_BYTES,
            accepted_statuses=accepted_statuses,
        )


def _matches_readiness(value: object, lock: ModelPoolLock) -> bool:
    if not isinstance(value, dict) or set(value) != {
        "schemaVersion",
        "status",
        "model",
        "runtime",
        "capacity",
    }:
        return False
    model = value.get("model")
    runtime = value.get("runtime")
    capacity = value.get("capacity")
    if (
        value.get("schemaVersion") != 1
        or value.get("status") != "ready"
        or model
        != {
            "poolId": lock.pool_id,
            "id": lock.model_id,
            "revision": lock.model_revision,
        }
        or not isinstance(capacity, dict)
        or set(capacity) != {"activeRequests", "maxActiveRequests"}
        or capacity.get("maxActiveRequests") != NEMOTRON_STREAMING_MAX_STREAMS
        or isinstance(capacity.get("activeRequests"), bool)
        or not isinstance(capacity.get("activeRequests"), int)
        or not 0
        <= capacity["activeRequests"]
        <= NEMOTRON_STREAMING_MAX_STREAMS
        or not isinstance(runtime, dict)
        or set(runtime)
        != {
            "device",
            "deviceName",
            "computeCapability",
            "pythonVersion",
            "torchVersion",
            "torchCudaVersion",
            "overlayPackages",
            "dtype",
            "servingEngine",
            "servingEngineVersion",
            "streamingChunkMs",
            "attentionContext",
        }
    ):
        return False
    python_version = runtime.get("pythonVersion")
    device_name = runtime.get("deviceName")
    compute_capability = runtime.get("computeCapability")
    versions = dict(lock.runtime_overlay_packages)
    return (
        runtime.get("device") == "cuda"
        and isinstance(device_name, str)
        and bool(device_name)
        and isinstance(compute_capability, list)
        and len(compute_capability) == 2
        and all(isinstance(item, int) for item in compute_capability)
        and isinstance(python_version, str)
        and (
            python_version == lock.runtime_python_version
            or python_version.startswith(lock.runtime_python_version + ".")
        )
        and runtime.get("torchVersion") == lock.runtime_torch_version
        and runtime.get("torchCudaVersion") == lock.runtime_torch_cuda_version
        and runtime.get("overlayPackages") == versions
        and runtime.get("dtype") == "bfloat16"
        and runtime.get("servingEngine") == "nemo-cache-aware"
        and runtime.get("servingEngineVersion") == versions.get("nemo_toolkit")
        and runtime.get("streamingChunkMs")
        == round(NEMOTRON_STREAMING_CHUNK_SECONDS * 1_000)
        and runtime.get("attentionContext")
        == list(NEMOTRON_STREAMING_ATTENTION_CONTEXT)
    )


def _open_http_connection(host: str, port: int, timeout: float) -> HttpConnection:
    return http.client.HTTPConnection(host, port, timeout=timeout)
