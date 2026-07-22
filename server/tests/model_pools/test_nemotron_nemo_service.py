from __future__ import annotations

from dataclasses import replace
import hashlib
import http.client
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import wave

from yap_server.pools.batch_contract import (
    ProviderCapacityUnavailable,
    ProviderServiceUnavailable,
    WorkerCancellationAcknowledged,
    WorkerContainmentError,
    WorkerExecutionError,
)
from yap_server.pools.nemotron_engine import NemotronInferenceCancelled
from yap_server.pools.nemotron_nemo_client import NemotronNemoClient
from yap_server.pools.nemotron_nemo_protocol import NemotronNemoServiceRequest
from yap_server.pools.nemotron_nemo_service import (
    NemotronNemoApplication,
    NemotronNemoServiceBusy,
    _NemotronNemoHttpServer,
)
from yap_server.pools.utterance_plan import (
    build_utterance_plan,
    publish_utterance_plan,
)

from .batch_asr_fixtures import test_lock as _test_lock


class _FakeEngine:
    def __init__(
        self,
        lock,
        *,
        block_until_cancelled: bool = False,
        block_until_released: bool = False,
        expected_starts: int = 1,
    ) -> None:
        self.lock = lock
        self.block_until_cancelled = block_until_cancelled
        self.block_until_released = block_until_released
        self.expected_starts = expected_starts
        self.started = threading.Event()
        self.release = threading.Event()
        self.closed = False
        self.requests: list[object] = []
        self.request_thread_ids: set[int] = set()
        self.request_thread_names: set[str] = set()
        self._requests_lock = threading.Lock()

    def serving_identity(self) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "model": {
                "poolId": self.lock.pool_id,
                "id": self.lock.model_id,
                "revision": self.lock.model_revision,
            },
            "runtime": {
                "device": "cuda",
                "deviceName": "Synthetic GB10",
                "computeCapability": [12, 1],
                "pythonVersion": "3.12.3",
                "torchVersion": self.lock.runtime_torch_version,
                "torchCudaVersion": self.lock.runtime_torch_cuda_version,
                "overlayPackages": dict(self.lock.runtime_overlay_packages),
                "dtype": "bfloat16",
                "servingEngine": "nemo-cache-aware",
                "servingEngineVersion": "3.1.0+test",
                "streamingChunkMs": 1_120,
                "attentionContext": [56, 13],
            },
            "capacity": {"maxActiveRequests": 8},
        }

    def transcribe_recording(self, request, plan, *, cancelled):
        with self._requests_lock:
            self.requests.append((request, plan))
            self.request_thread_ids.add(threading.get_ident())
            self.request_thread_names.add(threading.current_thread().name)
            if len(self.requests) >= self.expected_starts:
                self.started.set()
        if self.block_until_cancelled:
            deadline = time.monotonic() + 2
            while not cancelled() and time.monotonic() < deadline:
                time.sleep(0.005)
            if cancelled():
                raise NemotronInferenceCancelled("cancelled")
            raise AssertionError("test request was not cancelled")
        if self.block_until_released:
            deadline = time.monotonic() + 2
            while (
                not self.release.is_set()
                and not cancelled()
                and time.monotonic() < deadline
            ):
                time.sleep(0.005)
            if cancelled():
                raise NemotronInferenceCancelled("cancelled")
            if not self.release.is_set():
                raise AssertionError("test request was not released")
        return {"schemaVersion": 1, "jobId": request.job_id}

    def close(self) -> None:
        self.closed = True


class NemotronNemoServiceTests(unittest.TestCase):
    def test_authenticated_client_verifies_identity_and_transcribes(self) -> None:
        lock = _native_lock()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            request = _request(root)
            engine = _FakeEngine(lock)
            application = NemotronNemoApplication(
                engine=engine,  # type: ignore[arg-type]
                lock=lock,
                storage_root=root,
            )
            server, server_thread = _serve(application, api_key="private-test-key")
            client = NemotronNemoClient(
                endpoint=f"http://127.0.0.1:{server.server_port}",
                api_key="private-test-key",
                timeout_seconds=2,
            )
            try:
                self.assertEqual(
                    client.readiness_capacity(lock),
                    {"activeRequests": 0, "maxActiveRequests": 8},
                )
                result = client.transcribe(
                    request,
                    cancellation=threading.Event(),
                    shutdown=threading.Event(),
                )
                self.assertEqual(result, {"schemaVersion": 1, "jobId": "job-1"})
                self.assertEqual(len(engine.requests), 1)
            finally:
                client.close()
                _stop(server, server_thread, application)

    def test_readiness_preserves_a_transient_service_unavailable_status(self) -> None:
        lock = _native_lock()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            application = NemotronNemoApplication(
                engine=_FakeEngine(lock),  # type: ignore[arg-type]
                lock=lock,
                storage_root=root,
            )
            server, server_thread = _serve(application, api_key="private-test-key")
            client = NemotronNemoClient(
                endpoint=f"http://127.0.0.1:{server.server_port}",
                api_key="private-test-key",
                timeout_seconds=2,
            )
            try:
                application.request_shutdown()
                with self.assertRaisesRegex(
                    ProviderServiceUnavailable,
                    "not ready",
                ):
                    client.verify_ready(lock)
            finally:
                client.close()
                _stop(server, server_thread, application)

    def test_readiness_retries_transport_failure_but_not_client_defects(self) -> None:
        lock = _native_lock()

        def unavailable(_host: str, _port: int, _timeout: float):
            raise ConnectionRefusedError("not listening")

        unavailable_client = NemotronNemoClient(
            endpoint="http://127.0.0.1:18001",
            api_key="private-test-key",
            timeout_seconds=2,
            connection_factory=unavailable,
        )
        with self.assertRaises(ProviderServiceUnavailable):
            unavailable_client.verify_ready(lock)

        def broken(_host: str, _port: int, _timeout: float):
            raise RuntimeError("broken factory")

        broken_client = NemotronNemoClient(
            endpoint="http://127.0.0.1:18001",
            api_key="private-test-key",
            timeout_seconds=2,
            connection_factory=broken,
        )
        with self.assertRaisesRegex(WorkerExecutionError, "request failed") as caught:
            broken_client.verify_ready(lock)

        self.assertNotIsInstance(caught.exception, ProviderServiceUnavailable)

    def test_http_requests_reuse_bounded_worker_threads(self) -> None:
        lock = _native_lock()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            request = _request(root)
            engine = _FakeEngine(lock)
            application = NemotronNemoApplication(
                engine=engine,  # type: ignore[arg-type]
                lock=lock,
                storage_root=root,
            )
            server, server_thread = _serve(application, api_key="private-test-key")
            client = NemotronNemoClient(
                endpoint=f"http://127.0.0.1:{server.server_port}",
                api_key="private-test-key",
                timeout_seconds=2,
            )
            try:
                for _index in range(20):
                    self.assertEqual(
                        client.transcribe(
                            request,
                            cancellation=threading.Event(),
                            shutdown=threading.Event(),
                        ),
                        {"schemaVersion": 1, "jobId": "job-1"},
                    )
                self.assertEqual(len(engine.request_thread_ids), 1)
                self.assertTrue(
                    all(
                        name.startswith("yap-nemotron-http-request")
                        for name in engine.request_thread_names
                    )
                )
            finally:
                client.close()
                _stop(server, server_thread, application)

    def test_separate_cancel_request_stops_only_the_target(self) -> None:
        lock = _native_lock()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            request = _request(root)
            engine = _FakeEngine(lock, block_until_cancelled=True)
            application = NemotronNemoApplication(
                engine=engine,  # type: ignore[arg-type]
                lock=lock,
                storage_root=root,
            )
            server, server_thread = _serve(application, api_key="private-test-key")
            client = NemotronNemoClient(
                endpoint=f"http://127.0.0.1:{server.server_port}",
                api_key="private-test-key",
                timeout_seconds=2,
            )
            cancellation = threading.Event()
            outcome: list[BaseException] = []

            def run() -> None:
                try:
                    client.transcribe(
                        request,
                        cancellation=cancellation,
                        shutdown=threading.Event(),
                    )
                except BaseException as error:
                    outcome.append(error)

            request_thread = threading.Thread(target=run)
            try:
                request_thread.start()
                self.assertTrue(
                    client.wait_until_dispatched("job-1", timeout_seconds=1)
                )
                self.assertTrue(engine.started.wait(timeout=1))
                cancellation.set()
                request_thread.join(timeout=2)

                self.assertFalse(request_thread.is_alive())
                self.assertEqual(len(outcome), 1)
                self.assertIsInstance(
                    outcome[0],
                    WorkerCancellationAcknowledged,
                )
            finally:
                client.close()
                _stop(server, server_thread, application)

    def test_dispatch_wait_times_out_for_an_unknown_request(self) -> None:
        client = NemotronNemoClient(
            endpoint="http://127.0.0.1:8000",
            api_key="private-test-key",
            timeout_seconds=2,
        )

        self.assertFalse(
            client.wait_until_dispatched("missing", timeout_seconds=0.02)
        )

    def test_cancel_before_connection_creation_does_not_dispatch(self) -> None:
        lock = _native_lock()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            request = _request(root)
            engine = _FakeEngine(lock)
            application = NemotronNemoApplication(
                engine=engine,  # type: ignore[arg-type]
                lock=lock,
                storage_root=root,
            )
            server, server_thread = _serve(application, api_key="private-test-key")
            factory_entered = threading.Event()
            release_factory = threading.Event()

            def delayed_connection(host: str, port: int, timeout: float):
                factory_entered.set()
                if not release_factory.wait(timeout=1):
                    raise AssertionError("test connection factory was not released")
                return http.client.HTTPConnection(host, port, timeout=timeout)

            client = NemotronNemoClient(
                endpoint=f"http://127.0.0.1:{server.server_port}",
                api_key="private-test-key",
                timeout_seconds=2,
                connection_factory=delayed_connection,
            )
            cancellation = threading.Event()
            outcome: list[BaseException] = []

            def run() -> None:
                try:
                    client.transcribe(
                        request,
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
                self.assertIsInstance(
                    outcome[0],
                    WorkerCancellationAcknowledged,
                )
                self.assertFalse(engine.started.is_set())
                self.assertEqual(engine.requests, [])
            finally:
                release_factory.set()
                client.close()
                _stop(server, server_thread, application)

    def test_shutdown_reports_containment_when_connection_creation_never_finishes(
        self,
    ) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        request = _request(Path(temporary.name).resolve())
        factory_entered = threading.Event()
        release_factory = threading.Event()

        def blocked_connection(_host: str, _port: int, _timeout: float):
            factory_entered.set()
            release_factory.wait()
            raise OSError("synthetic connection creation stopped")

        client = NemotronNemoClient(
            endpoint="http://127.0.0.1:8000",
            api_key="private-test-key",
            timeout_seconds=2,
            connection_factory=blocked_connection,
        )
        outcome: list[BaseException] = []

        def run() -> None:
            try:
                client.transcribe(
                    request,
                    cancellation=threading.Event(),
                    shutdown=threading.Event(),
                )
            except BaseException as error:
                outcome.append(error)

        request_thread = threading.Thread(target=run)
        request_thread.start()
        try:
            self.assertTrue(factory_entered.wait(timeout=1))
            with (
                patch(
                    "yap_server.pools.nemotron_nemo_client._CANCELLATION_ACK_SECONDS",
                    0.05,
                ),
                self.assertRaisesRegex(
                    WorkerContainmentError,
                    "shutdown acknowledgement timed out",
                ),
            ):
                client.close()
        finally:
            release_factory.set()
            request_thread.join(timeout=2)

        self.assertFalse(request_thread.is_alive())
        self.assertEqual(len(outcome), 1)
        self.assertIsInstance(outcome[0], WorkerExecutionError)

    def test_wrong_api_key_cannot_probe_runtime_identity(self) -> None:
        lock = _native_lock()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            application = NemotronNemoApplication(
                engine=_FakeEngine(lock),  # type: ignore[arg-type]
                lock=lock,
                storage_root=root,
            )
            server, server_thread = _serve(application, api_key="correct-key")
            client = NemotronNemoClient(
                endpoint=f"http://127.0.0.1:{server.server_port}",
                api_key="wrong-key",
                timeout_seconds=1,
            )
            try:
                with self.assertRaises(WorkerExecutionError) as caught:
                    client.verify_ready(lock)
                self.assertNotIsInstance(
                    caught.exception,
                    ProviderServiceUnavailable,
                )
            finally:
                client.close()
                _stop(server, server_thread, application)

    def test_eight_active_jobs_keep_identity_and_bound_admission(self) -> None:
        lock = _native_lock()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            base_request = _request(root)
            engine = _FakeEngine(
                lock,
                block_until_released=True,
                expected_starts=8,
            )
            application = NemotronNemoApplication(
                engine=engine,  # type: ignore[arg-type]
                lock=lock,
                storage_root=root,
            )
            server, server_thread = _serve(application, api_key="private-test-key")
            client = NemotronNemoClient(
                endpoint=f"http://127.0.0.1:{server.server_port}",
                api_key="private-test-key",
                timeout_seconds=2,
            )
            outcomes: dict[str, object] = {}

            def run(job_id: str) -> None:
                try:
                    outcomes[job_id] = application.transcribe(
                        replace(base_request, job_id=job_id)
                    )
                except BaseException as error:
                    outcomes[job_id] = error

            job_ids = tuple(f"capacity-{index}" for index in range(8))
            threads = [threading.Thread(target=run, args=(job_id,)) for job_id in job_ids]
            try:
                for thread in threads:
                    thread.start()
                self.assertTrue(engine.started.wait(timeout=1))
                self.assertEqual(
                    client.readiness_capacity(lock),
                    {"activeRequests": 8, "maxActiveRequests": 8},
                )
                with self.assertRaisesRegex(
                    NemotronNemoServiceBusy,
                    "admission is full",
                ):
                    application.transcribe(
                        replace(base_request, job_id="capacity-overflow")
                    )
                with self.assertRaisesRegex(
                    ProviderCapacityUnavailable,
                    "admission is full",
                ):
                    client.transcribe(
                        replace(base_request, job_id="capacity-overflow-http"),
                        cancellation=threading.Event(),
                        shutdown=threading.Event(),
                    )
                engine.release.set()
                for thread in threads:
                    thread.join(timeout=2)

                self.assertTrue(all(not thread.is_alive() for thread in threads))
                self.assertEqual(set(outcomes), set(job_ids))
                for job_id in job_ids:
                    self.assertEqual(
                        outcomes[job_id],
                        {"schemaVersion": 1, "jobId": job_id},
                    )
            finally:
                engine.release.set()
                client.close()
                _stop(server, server_thread, application)

    def test_request_path_must_remain_in_private_storage(self) -> None:
        lock = _native_lock()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            request = _request(root)
            escaped = replace(request, input_path=str(Path(__file__).resolve()))
            application = NemotronNemoApplication(
                engine=_FakeEngine(lock),  # type: ignore[arg-type]
                lock=lock,
                storage_root=root,
            )

            with self.assertRaisesRegex(ValueError, "escapes private storage"):
                application.transcribe(escaped)
            application.close()


def _native_lock():
    return replace(
        _test_lock(),
        pool_id="nemotron-batch",
        engine="nemo",
        model_id="nvidia/nemotron-3.5-asr-streaming-0.6b",
        supported_languages=("auto", "en-US"),
        runtime_overlay_packages=(
            ("nemo_toolkit", "3.1.0+test"),
            ("transformers", "5.14.1"),
        ),
    )


def _request(root: Path) -> NemotronNemoServiceRequest:
    audio_path = root / "input.wav"
    with wave.open(str(audio_path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16_000)
        output.writeframes(b"\0\0" * 1_600)
    audio_sha256 = hashlib.sha256(audio_path.read_bytes()).hexdigest()
    plan = build_utterance_plan(
        input_wav_sha256=audio_sha256,
        input_sample_count=1_600,
        source_sample_count=1_600,
        vad_status="error",
        vad_evidence_sha256="a" * 64,
        vad_intervals=(),
    )
    plan_path = root / "utterance-plan.json"
    plan_sha256 = publish_utterance_plan(plan_path, plan)
    return NemotronNemoServiceRequest(
        job_id="job-1",
        input_path=str(audio_path),
        input_sha256=audio_sha256,
        utterance_plan_path=str(plan_path),
        utterance_plan_sha256=plan_sha256,
        language="en-US",
        punctuation=True,
    )


def _serve(application, *, api_key: str):
    server = _NemotronNemoHttpServer(
        ("127.0.0.1", 0),
        application=application,
        api_key=api_key,
    )
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    return server, thread


def _stop(server, thread: threading.Thread, application) -> None:
    application.request_shutdown()
    server.shutdown()
    thread.join(timeout=2)
    server.server_close()
    application.close()


if __name__ == "__main__":
    unittest.main()
