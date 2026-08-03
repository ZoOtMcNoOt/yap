from __future__ import annotations

from concurrent.futures import CancelledError
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from yap_server.jobs import JobServiceError, RecordingJobService
from yap_server.jobs import processing_input as processing_input_module
from yap_server.jobs.runtime import BatchRuntime, StorageRuntimeLease
from yap_server.pools.batch_asr import (
    BatchAsrJob,
    BatchAsrPool,
    WorkerContainmentError,
    WorkerExecutionError,
)

from tests.asr_route_fixtures import TEST_ASR_CATALOG_REVISION, test_asr_route

from .service_fixtures import (
    _ControlledProcessor,
    _create_request,
)


class _ControlledWorker:
    def __init__(self) -> None:
        self.jobs: list[BatchAsrJob] = []
        self.started = threading.Event()
        self.release = threading.Event()

    def run(
        self,
        job: BatchAsrJob,
        cancellation: threading.Event,
    ) -> dict[str, object]:
        self.jobs.append(job)
        self.started.set()
        while not self.release.wait(timeout=0.01):
            if cancellation.is_set():
                raise WorkerExecutionError("test worker was cancelled")
        if cancellation.is_set():
            raise WorkerExecutionError("test worker was cancelled")
        return {
            "model": {"id": "private-asr", "revision": "revision-1"},
            "transcript": {"text": "Durably admitted transcript."},
        }

    def close(self) -> None:
        self.release.set()


class _LateResultAfterContainmentFailureWorker:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    def run(
        self,
        _job: BatchAsrJob,
        _cancellation: threading.Event,
    ) -> dict[str, object]:
        self.started.set()
        if not self.release.wait(timeout=2):
            raise AssertionError("late-result worker was not released")
        return {
            "model": {"id": "private-asr", "revision": "revision-1"},
            "transcript": {"text": "Must not be published after shutdown."},
        }

    def close(self) -> None:
        raise WorkerContainmentError("synthetic containment failure")


class _InProcessStorageLease:
    _owned: set[Path] = set()

    def __init__(self, root: Path) -> None:
        self._root = root
        self._retained_for_fail_stop = False
        if root in self._owned:
            raise ValueError(
                "private server storage is already owned by another runtime"
            )
        self._owned.add(root)

    def retain_until_process_exit(self) -> None:
        self._retained_for_fail_stop = True

    def close(self) -> None:
        if self._retained_for_fail_stop:
            return
        self._owned.discard(self._root)


def _create_and_upload(
    service: RecordingJobService,
    request: dict[str, object] | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    request = _create_request() if request is None else request
    created = service.create(request)
    chunk = bytes(320)
    service.accept_chunk(
        service.prepare_chunk_upload(
            created["jobId"],
            track_id="track-1",
            sequence_start=0,
            sequence_end=159,
            idempotency_key="1/s-batch-create/track-1/0/159",
            content_sha256=hashlib.sha256(chunk).hexdigest(),
            audio_codec="pcm_s16le",
            sample_rate_hz=16000,
            channels=1,
            content_length=len(chunk),
        ),
        chunk,
    )
    return request, created


def _commit_request(request: dict[str, object]) -> dict[str, object]:
    return {
        "captureManifest": request["captureManifest"],
        "chunkCount": len(request["chunks"]),
    }


def _wait_for_status(
    service: RecordingJobService,
    job_id: str,
    expected: str,
) -> dict[str, object]:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        projection = service.get(job_id)
        if projection["status"] == expected:
            return projection
        time.sleep(0.01)
    raise AssertionError(f"job did not reach {expected}: {service.get(job_id)}")


class RecordingJobCommitAdmissionTests(unittest.TestCase):
    def test_runtime_shutdown_fences_every_mutating_service_entry_point(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            processor = _ControlledProcessor()
            service = RecordingJobService(
                root,
                processor=processor,
                supported_languages=("en",),
                now=lambda: "2026-07-14T21:29:00Z",
            )
            request, created = _create_and_upload(service)
            body = bytes(320)
            replay_plan = service.prepare_chunk_upload(
                created["jobId"],
                track_id="track-1",
                sequence_start=0,
                sequence_end=159,
                idempotency_key="1/s-batch-create/track-1/0/159",
                content_sha256=hashlib.sha256(body).hexdigest(),
                audio_codec="pcm_s16le",
                sample_rate_hz=16000,
                channels=1,
                content_length=len(body),
            )
            state_before_shutdown = (
                root / "jobs" / created["jobId"] / "state.json"
            ).read_bytes()

            service.begin_runtime_shutdown()

            operations = (
                lambda: service.create(_create_request(session_id="s-after-shutdown")),
                lambda: service.prepare_chunk_upload(
                    created["jobId"],
                    track_id="track-1",
                    sequence_start=0,
                    sequence_end=159,
                    idempotency_key="1/s-batch-create/track-1/0/159",
                    content_sha256=hashlib.sha256(body).hexdigest(),
                    audio_codec="pcm_s16le",
                    sample_rate_hz=16000,
                    channels=1,
                    content_length=len(body),
                ),
                lambda: service.accept_chunk(replay_plan, body),
                lambda: service.commit(
                    created["jobId"],
                    _commit_request(request),
                ),
                lambda: service.retry_stage(
                    created["jobId"],
                    "asr",
                    {
                        "stage": "asr",
                        "attempt": 1,
                        "projectionRevision": 1,
                        "captureManifestSha256": "a" * 64,
                    },
                ),
                lambda: service.cancel(created["jobId"]),
                service.prune_expired,
            )
            for operation in operations:
                with self.subTest(operation=operation):
                    with self.assertRaises(JobServiceError) as stopped:
                        operation()
                    self.assertEqual(stopped.exception.status, 503)
                    self.assertEqual(
                        stopped.exception.code,
                        "SERVER_SHUTTING_DOWN",
                    )
                    self.assertTrue(stopped.exception.retryable)

            self.assertEqual(processor.jobs, [])
            self.assertNotIn(created["jobId"], service._state.cancelled)
            self.assertEqual(
                (root / "jobs" / created["jobId"] / "state.json").read_bytes(),
                state_before_shutdown,
            )

    def test_containment_failure_blocks_reownership_and_late_callback_mutation(
        self,
    ) -> None:
        self._assert_containment_failure_retains_lease(_InProcessStorageLease)

    @unittest.skipUnless(os.name == "posix", "POSIX storage lease")
    def test_containment_failure_retains_lease_and_blocks_late_publication(
        self,
    ) -> None:
        self._assert_containment_failure_retains_lease(StorageRuntimeLease)

    def _assert_containment_failure_retains_lease(self, lease_type: type) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            worker = _LateResultAfterContainmentFailureWorker()
            pool = BatchAsrPool(
                worker,
                max_workers=1,
                max_queued=0,
                route_resolver=test_asr_route,
                asr_catalog_revision=TEST_ASR_CATALOG_REVISION,
            )
            service = RecordingJobService(
                root,
                processor=pool,
                supported_languages=("en",),
                now=lambda: "2026-07-14T21:29:00Z",
            )
            runtime = BatchRuntime(
                service=service,
                pool=pool,
                storage_lease=lease_type(root),
                asr_capabilities={},
                language_detection_runtime=None,
            )
            request, created = _create_and_upload(service)
            service.commit(created["jobId"], _commit_request(request))
            self.assertTrue(worker.started.wait(timeout=1))
            completion_event = service._completion_events[created["jobId"]]
            state_path = root / "jobs" / created["jobId"] / "state.json"
            state_before_close = state_path.read_bytes()

            with self.assertRaisesRegex(
                WorkerContainmentError,
                "synthetic containment failure",
            ):
                runtime.close()
            with self.assertRaisesRegex(
                WorkerContainmentError,
                "process restart is required",
            ):
                runtime.close()
            runtime.storage_lease.close()
            with self.assertRaisesRegex(ValueError, "already owned"):
                lease_type(root)

            worker.release.set()
            self.assertTrue(completion_event.wait(timeout=2))
            deadline = time.monotonic() + 2
            while pool.outstanding_count and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertEqual(pool.outstanding_count, 0)
            self.assertEqual(state_path.read_bytes(), state_before_close)
            self.assertFalse(
                (root / "jobs" / created["jobId"] / "result-revision.json").exists()
            )

    def test_slow_preparation_does_not_block_exact_commit_replay(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            worker = _ControlledWorker()
            pool = BatchAsrPool(
                worker,
                max_workers=1,
                max_queued=0,
                route_resolver=test_asr_route,
                asr_catalog_revision=TEST_ASR_CATALOG_REVISION,
            )
            service = RecordingJobService(
                Path(temporary),
                processor=pool,
                supported_languages=("en",),
                now=lambda: "2026-07-14T21:30:00Z",
            )
            request, created = _create_and_upload(service)
            entered_preparation = threading.Event()
            release_preparation = threading.Event()
            publication_count = 0
            original_publish_wav = processing_input_module.publish_wav

            def blocked_publish_wav(*args: object, **kwargs: object) -> str:
                nonlocal publication_count
                publication_count += 1
                entered_preparation.set()
                if not release_preparation.wait(timeout=2):
                    raise TimeoutError("test preparation was not released")
                return original_publish_wav(*args, **kwargs)

            try:
                with patch.object(
                    processing_input_module,
                    "publish_wav",
                    blocked_publish_wav,
                ):
                    committed = service.commit(
                        created["jobId"], _commit_request(request)
                    )
                    self.assertEqual(committed["status"], "server_processing")
                    self.assertTrue(entered_preparation.wait(timeout=2))

                    replayed = service.commit(
                        created["jobId"], _commit_request(request)
                    )
                    self.assertEqual(replayed, committed)
                    self.assertEqual(publication_count, 1)
                    self.assertEqual(pool.outstanding_count, 1)

                    conflicting = _commit_request(request)
                    conflicting["chunkCount"] = 2
                    with self.assertRaises(ValueError):
                        service.commit(created["jobId"], conflicting)

                    release_preparation.set()
                    self.assertTrue(worker.started.wait(timeout=2))
                    self.assertEqual(worker.jobs[0].route, test_asr_route())
                    worker.release.set()
                    completed = _wait_for_status(service, created["jobId"], "complete")
                    self.assertEqual(
                        service.commit(created["jobId"], _commit_request(request)),
                        completed,
                    )
                    self.assertEqual(publication_count, 1)
            finally:
                release_preparation.set()
                worker.release.set()
                service.begin_runtime_shutdown()
                pool.shutdown()

    def test_saturated_capacity_rejects_before_derived_wav_work(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            worker = _ControlledWorker()
            pool = BatchAsrPool(
                worker,
                max_workers=1,
                max_queued=0,
                route_resolver=test_asr_route,
                asr_catalog_revision=TEST_ASR_CATALOG_REVISION,
            )
            service = RecordingJobService(
                Path(temporary),
                processor=pool,
                supported_languages=("en",),
                now=lambda: "2026-07-14T21:31:00Z",
            )
            first_request, first = _create_and_upload(service)
            second_request, second = _create_and_upload(service)
            entered_preparation = threading.Event()
            release_preparation = threading.Event()
            publication_count = 0
            original_publish_wav = processing_input_module.publish_wav

            def blocked_publish_wav(*args: object, **kwargs: object) -> str:
                nonlocal publication_count
                publication_count += 1
                entered_preparation.set()
                if not release_preparation.wait(timeout=2):
                    raise TimeoutError("test preparation was not released")
                return original_publish_wav(*args, **kwargs)

            try:
                with patch.object(
                    processing_input_module,
                    "publish_wav",
                    blocked_publish_wav,
                ):
                    service.commit(first["jobId"], _commit_request(first_request))
                    self.assertTrue(entered_preparation.wait(timeout=2))
                    with self.assertRaises(JobServiceError) as busy:
                        service.commit(second["jobId"], _commit_request(second_request))
                    self.assertEqual(busy.exception.code, "SERVER_BUSY")
                    self.assertTrue(busy.exception.retryable)
                    self.assertEqual(publication_count, 1)
                    self.assertFalse(
                        (
                            Path(temporary) / "jobs" / second["jobId"] / "input.wav"
                        ).exists()
                    )
            finally:
                release_preparation.set()
                worker.release.set()
                service.begin_runtime_shutdown()
                pool.shutdown()

    def test_cancellation_during_preparation_never_starts_the_gpu_worker(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            worker = _ControlledWorker()
            pool = BatchAsrPool(
                worker,
                max_workers=1,
                max_queued=0,
                route_resolver=test_asr_route,
                asr_catalog_revision=TEST_ASR_CATALOG_REVISION,
            )
            service = RecordingJobService(
                root,
                processor=pool,
                supported_languages=("en",),
                now=lambda: "2026-07-14T21:31:30Z",
            )
            request, created = _create_and_upload(service)
            entered_preparation = threading.Event()

            def cancellable_publish_wav(*_args: object, **kwargs: object) -> str:
                cancellation = kwargs.get("cancellation")
                if not isinstance(cancellation, threading.Event):
                    raise AssertionError("preparation cancellation token is missing")
                entered_preparation.set()
                if not cancellation.wait(timeout=2):
                    raise TimeoutError("test preparation was not cancelled")
                raise CancelledError()

            try:
                with patch.object(
                    processing_input_module,
                    "publish_wav",
                    cancellable_publish_wav,
                ):
                    committed = service.commit(
                        created["jobId"], _commit_request(request)
                    )
                    self.assertEqual(committed["status"], "server_processing")
                    self.assertTrue(entered_preparation.wait(timeout=2))
                    cancelled = service.cancel(created["jobId"])
                self.assertEqual(cancelled["status"], "cancelled")
                self.assertFalse(worker.started.is_set())
                self.assertEqual(pool.outstanding_count, 0)
                self.assertFalse(
                    (root / "jobs" / created["jobId"] / "input.wav").exists()
                )
                self.assertEqual(
                    list((root / "jobs" / created["jobId"] / "chunks").iterdir()),
                    [],
                )
            finally:
                worker.release.set()
                service.begin_runtime_shutdown()
                pool.shutdown()

    def test_processing_state_failure_aborts_the_reserved_slot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            worker = _ControlledWorker()
            pool = BatchAsrPool(
                worker,
                max_workers=1,
                max_queued=0,
                route_resolver=test_asr_route,
                asr_catalog_revision=TEST_ASR_CATALOG_REVISION,
            )
            service = RecordingJobService(
                root,
                processor=pool,
                supported_languages=("en",),
                now=lambda: "2026-07-14T21:32:00Z",
            )
            request, created = _create_and_upload(service)
            from yap_server.jobs import job_store as store_module

            original_publish_json = store_module.publish_json

            def fail_processing_state(path: Path, value: object) -> None:
                if (
                    path.name == "state.json"
                    and value["projection"]["status"] == "server_processing"
                ):
                    raise OSError("injected processing-state failure")
                original_publish_json(path, value)

            try:
                with patch.object(store_module, "publish_json", fail_processing_state):
                    with self.assertRaises(OSError):
                        service.commit(created["jobId"], _commit_request(request))
                self.assertEqual(pool.outstanding_count, 0)
                self.assertEqual(service.get(created["jobId"])["status"], "uploading")
                self.assertFalse(
                    (root / "jobs" / created["jobId"] / "input.wav").exists()
                )
                self.assertFalse(worker.started.is_set())
            finally:
                worker.release.set()
                service.begin_runtime_shutdown()
                pool.shutdown()

    def test_preprocessed_pcm_digest_mismatch_never_reaches_the_gpu_worker(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            worker = _ControlledWorker()
            pool = BatchAsrPool(
                worker,
                max_workers=1,
                max_queued=0,
                route_resolver=test_asr_route,
                asr_catalog_revision=TEST_ASR_CATALOG_REVISION,
            )
            service = RecordingJobService(
                root,
                processor=pool,
                supported_languages=("en",),
                now=lambda: "2026-07-14T21:32:30Z",
            )
            request = _create_request()
            request["preprocessingEvidence"]["normalization"]["outputPcmSha256"] = (
                "c" * 64
            )
            request, created = _create_and_upload(service, request)
            try:
                committed = service.commit(created["jobId"], _commit_request(request))
                self.assertEqual(committed["status"], "server_processing")
                failed = _wait_for_status(service, created["jobId"], "failed")
                self.assertEqual(
                    failed["error"]["code"],
                    "ASR_INPUT_INTEGRITY_FAILED",
                )
                self.assertFalse(worker.started.is_set())
                self.assertEqual(pool.outstanding_count, 0)
                self.assertFalse(
                    (root / "jobs" / created["jobId"] / "input.wav").exists()
                )
                self.assertEqual(
                    list((root / "jobs" / created["jobId"] / "chunks").iterdir()),
                    [],
                )
            finally:
                worker.release.set()
                service.begin_runtime_shutdown()
                pool.shutdown()

    def test_verified_restart_resumes_durable_processing_intent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first_worker = _ControlledWorker()
            first_pool = BatchAsrPool(
                first_worker,
                max_workers=1,
                max_queued=0,
                route_resolver=test_asr_route,
                asr_catalog_revision=TEST_ASR_CATALOG_REVISION,
            )
            first_service = RecordingJobService(
                root,
                processor=first_pool,
                supported_languages=("en",),
                now=lambda: "2026-07-14T21:33:00Z",
            )
            request, created = _create_and_upload(first_service)
            first_service.commit(created["jobId"], _commit_request(request))
            self.assertTrue(first_worker.started.wait(timeout=2))

            first_service.begin_runtime_shutdown()
            first_pool.shutdown()
            self.assertEqual(
                first_service.get(created["jobId"])["status"],
                "server_processing",
            )
            persisted = json.loads(
                (root / "jobs" / created["jobId"] / "state.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(persisted["projection"]["status"], "server_processing")
            self.assertEqual(persisted["schemaVersion"], 6)
            self.assertEqual(
                persisted["asrRouting"],
                {
                    "asrCatalogRevision": TEST_ASR_CATALOG_REVISION,
                    "route": test_asr_route().to_persisted(),
                },
            )

            def must_not_reresolve(_provider_language: str):
                raise AssertionError("durable processing route was re-resolved")

            resumed_worker = _ControlledWorker()
            resumed_pool = BatchAsrPool(
                resumed_worker,
                max_workers=1,
                max_queued=0,
                route_resolver=must_not_reresolve,
                asr_catalog_revision="d" * 64,
            )
            resumed_service = RecordingJobService(
                root,
                processor=resumed_pool,
                supported_languages=("en",),
                now=lambda: "2026-07-14T21:34:00Z",
                startup_worker_cleanup_verified=True,
            )
            try:
                self.assertTrue(resumed_worker.started.wait(timeout=2))
                self.assertEqual(len(resumed_worker.jobs), 1)
                self.assertEqual(resumed_worker.jobs[0].route, test_asr_route())
                resumed_worker.release.set()
                self.assertEqual(
                    _wait_for_status(
                        resumed_service,
                        created["jobId"],
                        "complete",
                    )["status"],
                    "complete",
                )
            finally:
                resumed_worker.release.set()
                resumed_service.begin_runtime_shutdown()
                resumed_pool.shutdown()
