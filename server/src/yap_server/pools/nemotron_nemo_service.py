from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import secrets
import signal
import stat
import sys
import threading
from typing import Mapping

from yap_server.bounded_file import read_regular_file
from yap_server.limits import MAX_WORKER_RESULT_BYTES
from yap_server.pools.authenticated_loopback_http import validate_private_api_key
from yap_server.pools.pcm_audio import (
    MAX_ENCODED_AUDIO_BYTES,
    decode_pcm16_wav,
)
from yap_server.pools.model_lock import (
    ModelPoolLock,
    load_model_pool_lock,
    verify_model_artifacts,
)
from yap_server.pools.nemo_stream_scheduler import (
    NemoStreamCapacityExceeded,
    NemoStreamRuntimeFenced,
)
from yap_server.pools.nemotron_engine import (
    NemotronAsrInput,
    NemotronInferenceCancelled,
)
from yap_server.pools.nemotron_nemo_protocol import (
    NEMOTRON_NEMO_MAX_ACTIVE_REQUESTS,
    NEMOTRON_NEMO_MAX_REQUEST_BYTES,
    NEMOTRON_NEMO_READY_PATH,
    NEMOTRON_NEMO_TRANSCRIPTION_PATH,
    NemotronNemoServiceRequest,
    cancellation_path,
)
from yap_server.pools.nemotron_nemo_cleanup import (
    NATIVE_RUNTIME_CLEANUP_TIMEOUT_SECONDS,
    close_native_runtime_or_fail_stop as _close_native_runtime_or_fail_stop,
    fail_stop_native_runtime as _fail_stop_shutdown,
)
from yap_server.pools.nemotron_nemo_streaming import NemotronNemoStreamingEngine
from yap_server.pools.utterance_plan import read_utterance_plan


_API_KEY_ENV = "YAP_NEMOTRON_NEMO_API_KEY"
_REQUEST_TIMEOUT_SECONDS = 10.0
_MAX_HTTP_REQUEST_WORKERS = NEMOTRON_NEMO_MAX_ACTIVE_REQUESTS * 2 + 2
_SHUTDOWN_CLEANUP_TIMEOUT_SECONDS = NATIVE_RUNTIME_CLEANUP_TIMEOUT_SECONDS


class NemotronNemoRequestCancelled(RuntimeError):
    pass


class NemotronNemoServiceBusy(RuntimeError):
    pass


class NemotronNemoServiceFenced(RuntimeError):
    pass


class NemotronNemoApplication:
    """Authenticated transport adapter around one resident native engine."""

    def __init__(
        self,
        *,
        engine: NemotronNemoStreamingEngine,
        lock: ModelPoolLock,
        storage_root: Path,
    ) -> None:
        self._engine = engine
        model_identity = engine.serving_identity().get("model")
        if model_identity != {
            "poolId": lock.pool_id,
            "id": lock.model_id,
            "revision": lock.model_revision,
        }:
            raise ValueError("resident NeMo engine identity differs from the model lock")
        self._storage_root = _validated_storage_root(storage_root)
        self._active_lock = threading.Lock()
        self._active: dict[str, threading.Event] = {}
        self._shutdown = threading.Event()
        self._fenced = threading.Event()

    def readiness(self) -> tuple[int, dict[str, object]]:
        status = 503 if self._shutdown.is_set() or self._fenced.is_set() else 200
        payload = self._engine.serving_identity()
        with self._active_lock:
            active_requests = len(self._active)
        capacity = payload.get("capacity")
        if not isinstance(capacity, dict):
            raise RuntimeError("resident NeMo serving identity omitted capacity")
        payload["capacity"] = {
            **capacity,
            "activeRequests": active_requests,
        }
        payload["status"] = "unavailable" if status != 200 else "ready"
        return status, payload

    def transcribe(self, request: NemotronNemoServiceRequest) -> dict[str, object]:
        cancellation = threading.Event()
        with self._active_lock:
            if self._shutdown.is_set() or self._fenced.is_set():
                raise NemotronNemoServiceFenced("resident NeMo runtime is unavailable")
            if request.job_id in self._active:
                raise NemotronNemoServiceBusy("request identity is already active")
            if len(self._active) >= NEMOTRON_NEMO_MAX_ACTIVE_REQUESTS:
                raise NemotronNemoServiceBusy("resident NeMo admission is full")
            self._active[request.job_id] = cancellation
        try:
            input_path = _resolve_storage_file(
                request.input_path,
                storage_root=self._storage_root,
            )
            encoded_wav = read_regular_file(input_path, MAX_ENCODED_AUDIO_BYTES)
            if cancellation.is_set() or self._shutdown.is_set():
                raise NemotronNemoRequestCancelled(
                    "resident NeMo request was cancelled"
                )
            audio = decode_pcm16_wav(encoded_wav)
            if audio.sha256 != request.input_sha256:
                raise ValueError("Nemotron NeMo input identity changed before dispatch")
            plan_path = _resolve_storage_file(
                request.utterance_plan_path,
                storage_root=self._storage_root,
            )
            plan = read_utterance_plan(
                plan_path,
                expected_sha256=request.utterance_plan_sha256,
                expected_input_wav_sha256=audio.sha256,
                expected_input_sample_count=audio.frame_count,
            )
            if cancellation.is_set() or self._shutdown.is_set():
                raise NemotronNemoRequestCancelled(
                    "resident NeMo request was cancelled"
                )
            return self._engine.transcribe_recording(
                NemotronAsrInput(
                    job_id=request.job_id,
                    audio=audio,
                    language=request.language,
                    punctuation=request.punctuation,
                ),
                plan,
                cancelled=lambda: cancellation.is_set() or self._shutdown.is_set(),
            )
        except NemoStreamCapacityExceeded as error:
            raise NemotronNemoServiceBusy("resident NeMo admission is full") from error
        except NemoStreamRuntimeFenced as error:
            self._fenced.set()
            raise NemotronNemoServiceFenced(
                "resident NeMo runtime fenced after inference failure"
            ) from error
        except NemotronInferenceCancelled as error:
            raise NemotronNemoRequestCancelled(
                "resident NeMo request was cancelled"
            ) from error
        finally:
            with self._active_lock:
                if self._active.get(request.job_id) is cancellation:
                    self._active.pop(request.job_id, None)

    def cancel(self, job_id: str) -> bool:
        with self._active_lock:
            cancellation = self._active.get(job_id)
            if cancellation is None:
                return False
            cancellation.set()
            return True

    def request_shutdown(self) -> None:
        self._shutdown.set()
        with self._active_lock:
            cancellations = tuple(self._active.values())
        for cancellation in cancellations:
            cancellation.set()

    def close(self) -> None:
        self.request_shutdown()
        self._engine.close()


class _NemotronNemoHttpServer(HTTPServer):
    allow_reuse_address = False
    request_queue_size = _MAX_HTTP_REQUEST_WORKERS

    def __init__(
        self,
        address: tuple[str, int],
        *,
        application: NemotronNemoApplication,
        api_key: str,
    ) -> None:
        self.application = application
        self.api_key = api_key
        self._request_slots = threading.BoundedSemaphore(_MAX_HTTP_REQUEST_WORKERS)
        super().__init__(address, _NemotronNemoRequestHandler)
        self._request_executor = ThreadPoolExecutor(
            max_workers=_MAX_HTTP_REQUEST_WORKERS,
            thread_name_prefix="yap-nemotron-http-request",
        )

    def process_request(self, request, client_address) -> None:
        if not self._request_slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            self._request_executor.submit(
                self._process_request_in_worker,
                request,
                client_address,
            )
        except Exception:
            self._request_slots.release()
            self.shutdown_request(request)
            raise

    def _process_request_in_worker(self, request, client_address) -> None:
        try:
            try:
                self.finish_request(request, client_address)
            except Exception:
                self.handle_error(request, client_address)
            finally:
                self.shutdown_request(request)
        finally:
            self._request_slots.release()

    def server_close(self) -> None:
        self.application.request_shutdown()
        try:
            super().server_close()
        finally:
            # Active inference is owned by the bounded scheduler shutdown below.
            # Waiting here would keep the listener and container alive forever if
            # a native inference call stopped returning.
            self._request_executor.shutdown(wait=False, cancel_futures=True)

    def handle_error(self, request, client_address) -> None:
        del request, client_address


class _NemotronNemoRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "Yap-Nemotron"
    sys_version = ""

    @property
    def _server(self) -> _NemotronNemoHttpServer:
        return self.server  # type: ignore[return-value]

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(_REQUEST_TIMEOUT_SECONDS)

    def log_message(self, _format: str, *args: object) -> None:
        del args

    def do_GET(self) -> None:
        if not self._authenticated() or self.path != NEMOTRON_NEMO_READY_PATH:
            self._write_json(404, {"error": "not-found"})
            return
        status, payload = self._server.application.readiness()
        self._write_json(status, payload)

    def do_POST(self) -> None:
        if not self._authenticated() or self.path != NEMOTRON_NEMO_TRANSCRIPTION_PATH:
            self._write_json(404, {"error": "not-found"})
            return
        try:
            request = NemotronNemoServiceRequest.from_payload(self._read_json())
            result = self._server.application.transcribe(request)
        except NemotronNemoRequestCancelled:
            self._write_json(409, {"error": "cancelled"})
        except NemotronNemoServiceBusy:
            self._write_json(429, {"error": "busy"})
        except NemotronNemoServiceFenced:
            self._write_json(503, {"error": "runtime-unavailable"})
        except (OSError, ValueError):
            self._write_json(422, {"error": "invalid-request"})
        except BaseException:
            self._write_json(500, {"error": "inference-failed"})
        else:
            self._write_json(200, result)

    def do_DELETE(self) -> None:
        if not self._authenticated():
            self._write_json(404, {"error": "not-found"})
            return
        prefix = f"{NEMOTRON_NEMO_TRANSCRIPTION_PATH}/"
        job_id = self.path[len(prefix) :] if self.path.startswith(prefix) else ""
        try:
            expected_path = cancellation_path(job_id)
        except ValueError:
            self._write_json(404, {"error": "not-found"})
            return
        if self.path != expected_path:
            self._write_json(404, {"error": "not-found"})
            return
        cancelled = self._server.application.cancel(job_id)
        self._write_json(
            202 if cancelled else 404,
            {"status": "cancellation-requested" if cancelled else "not-active"},
        )

    def _authenticated(self) -> bool:
        authorization = self.headers.get("Authorization")
        expected = f"Bearer {self._server.api_key}"
        return isinstance(authorization, str) and secrets.compare_digest(
            authorization,
            expected,
        )

    def _read_json(self) -> object:
        content_type = self.headers.get("Content-Type", "")
        content_length = self.headers.get("Content-Length")
        if not content_type.lower().startswith("application/json"):
            raise ValueError("request content type is invalid")
        try:
            length = int(content_length) if content_length is not None else -1
        except ValueError as error:
            raise ValueError("request content length is invalid") from error
        if not 1 <= length <= NEMOTRON_NEMO_MAX_REQUEST_BYTES:
            raise ValueError("request content length is invalid")
        encoded = self.rfile.read(length)
        if len(encoded) != length:
            raise ValueError("request body ended before its declared length")
        try:
            return json.loads(encoded, object_pairs_hook=_unique_json_object)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            raise ValueError("request body is not valid JSON") from error

    def _write_json(self, status: int, payload: Mapping[str, object]) -> None:
        encoded = json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        if len(encoded) > MAX_WORKER_RESULT_BYTES:
            status = 500
            encoded = b'{"error":"response-too-large"}'
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(encoded)


def _validated_storage_root(path: Path) -> Path:
    if not isinstance(path, Path) or not path.is_absolute():
        raise ValueError("Nemotron NeMo storage root path is invalid")
    try:
        metadata = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise ValueError("Nemotron NeMo storage root is missing") from error
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or resolved != path
    ):
        raise ValueError("Nemotron NeMo storage root must be a real directory")
    return resolved


def _resolve_storage_file(value: str, *, storage_root: Path) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        raise ValueError("Nemotron NeMo input path must be absolute")
    try:
        metadata = candidate.lstat()
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(storage_root)
    except (OSError, ValueError) as error:
        raise ValueError("Nemotron NeMo input path escapes private storage") from error
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or resolved != candidate
    ):
        raise ValueError("Nemotron NeMo input path must be a canonical regular file")
    return candidate


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serve one resident Nemotron NeMo model")
    parser.add_argument("--lock", required=True)
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--storage-dir", required=True)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    api_key = os.environ.get(_API_KEY_ENV, "")
    validate_private_api_key(api_key, component="Nemotron NeMo")
    if arguments.host != "0.0.0.0" or not 1 <= arguments.port <= 65_535:
        raise ValueError("resident Nemotron NeMo bind address is invalid")
    lock = load_model_pool_lock(Path(arguments.lock))
    model_dir = Path(arguments.model_dir).resolve(strict=True)
    verify_model_artifacts(lock, model_dir)
    with redirect_stdout(sys.stderr):
        engine = NemotronNemoStreamingEngine(model_dir=model_dir, lock=lock)
    application: NemotronNemoApplication | None = None
    server: _NemotronNemoHttpServer | None = None
    server_thread: threading.Thread | None = None
    try:
        application = NemotronNemoApplication(
            engine=engine,
            lock=lock,
            storage_root=Path(arguments.storage_dir),
        )
        active_application = application
        server = _NemotronNemoHttpServer(
            (arguments.host, arguments.port),
            application=active_application,
            api_key=api_key,
        )
        stopped = threading.Event()

        def request_stop(_signum: int, _frame: object) -> None:
            active_application.request_shutdown()
            stopped.set()

        signal.signal(signal.SIGTERM, request_stop)
        signal.signal(signal.SIGINT, request_stop)
        server_thread = threading.Thread(
            target=server.serve_forever,
            name="yap-nemotron-nemo-http",
        )
        server_thread.start()
        while server_thread.is_alive() and not stopped.wait(0.5):
            pass
        if not server_thread.is_alive() and not stopped.is_set():
            raise RuntimeError("resident Nemotron NeMo HTTP server stopped unexpectedly")
    finally:
        try:
            if application is not None:
                application.request_shutdown()
            if server is not None and server_thread is not None:
                if server_thread.ident is not None:
                    server.shutdown()
                    server_thread.join()
                server.server_close()
        except BaseException:
            _fail_stop_shutdown()
        close_runtime = application.close if application is not None else engine.close
        _close_native_runtime_or_fail_stop(
            close_runtime,
            timeout_seconds=_SHUTDOWN_CLEANUP_TIMEOUT_SECONDS,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
