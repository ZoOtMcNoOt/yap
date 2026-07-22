from __future__ import annotations

from concurrent.futures import Future
import hashlib
from pathlib import Path
import tempfile
import threading
import time
import unittest
from typing import Callable

from yap_server.jobs import JobServiceError, RecordingJobService
from yap_server.pools.batch_contract import (
    BatchJobFactory,
    PoolBackpressure,
)

from tests.asr_route_fixtures import (
    TEST_ASR_CATALOG_REVISION,
    test_asr_route,
)

from .service_fixtures import _create_request


_WORKER_RESULT = {
    "model": {"id": "private-asr", "revision": "revision-1"},
    "transcript": {"text": "Restart-safe transcript."},
}


class _Reservation:
    def __init__(
        self,
        start: Callable[[BatchJobFactory], Future[dict[str, object]]],
        abort: Callable[[], None] = lambda: None,
    ) -> None:
        self._start = start
        self._abort = abort
        self._consumed = False

    def start(self, factory: BatchJobFactory) -> Future[dict[str, object]]:
        if self._consumed:
            raise RuntimeError("test reservation is already consumed")
        self._consumed = True
        return self._start(factory)

    def abort(self) -> None:
        if self._consumed:
            return
        self._consumed = True
        self._abort()


class _PendingProcessor:
    @property
    def asr_catalog_revision(self) -> str:
        return TEST_ASR_CATALOG_REVISION

    def resolve_route(self, catalog_language_bcp47: str):
        return test_asr_route(catalog_language_bcp47)

    def reserve(
        self,
        _job_id: str,
        *,
        pcm_byte_length: int,
    ) -> _Reservation:
        if pcm_byte_length < 1:
            raise ValueError("test PCM reservation must be positive")
        return _Reservation(lambda _factory: Future())

    def cancel(self, _job_id: str) -> bool:
        return False


class _ImmediateProcessor(_PendingProcessor):
    def __init__(self) -> None:
        self.started: list[str] = []

    def reserve(
        self,
        job_id: str,
        *,
        pcm_byte_length: int,
    ) -> _Reservation:
        if pcm_byte_length < 1:
            raise ValueError("test PCM reservation must be positive")
        def start(factory: BatchJobFactory) -> Future[dict[str, object]]:
            factory(threading.Event())
            self.started.append(job_id)
            future: Future[dict[str, object]] = Future()
            future.set_result(dict(_WORKER_RESULT))
            return future

        return _Reservation(start)


class _ObservedService(RecordingJobService):
    def __init__(self, *args: object, **kwargs: object) -> None:
        self.active_pump_passes = 0
        self.max_active_pump_passes = 0
        super().__init__(*args, **kwargs)

    def _pump_pending_processing_pass(self) -> None:
        self.active_pump_passes += 1
        self.max_active_pump_passes = max(
            self.max_active_pump_passes,
            self.active_pump_passes,
        )
        try:
            super()._pump_pending_processing_pass()
        finally:
            self.active_pump_passes -= 1


class _BarrierProcessor(_PendingProcessor):
    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._busy = False
        self.started: list[str] = []
        self.futures: dict[str, Future[dict[str, object]]] = {}
        self.first_slot_released = threading.Event()
        self.allow_first_service_callback = threading.Event()

    def reserve(
        self,
        job_id: str,
        *,
        pcm_byte_length: int,
    ) -> _Reservation:
        if pcm_byte_length < 1:
            raise ValueError("test PCM reservation must be positive")
        with self._condition:
            if self._busy:
                raise PoolBackpressure("test processor is at capacity")
            self._busy = True

        def abort() -> None:
            with self._condition:
                self._busy = False
                self._condition.notify_all()

        def start(factory: BatchJobFactory) -> Future[dict[str, object]]:
            try:
                factory(threading.Event())
            except BaseException:
                abort()
                raise
            future: Future[dict[str, object]] = Future()
            with self._condition:
                self.started.append(job_id)
                is_first = len(self.started) == 1
                self.futures[job_id] = future
                self._condition.notify_all()

            def release(_completed: Future[dict[str, object]]) -> None:
                with self._condition:
                    self._busy = False
                    self._condition.notify_all()
                if is_first:
                    self.first_slot_released.set()
                    if not self.allow_first_service_callback.wait(timeout=5):
                        raise TimeoutError("test did not release the service callback")

            # This callback is intentionally registered before the service's
            # callback. It opens the exact release-before-pump race window.
            future.add_done_callback(release)
            return future

        return _Reservation(start, abort)

    def wait_for_starts(self, count: int) -> None:
        with self._condition:
            if not self._condition.wait_for(
                lambda: len(self.started) >= count,
                timeout=5,
            ):
                raise AssertionError(f"only {len(self.started)} jobs started")

    def complete(self, job_id: str) -> None:
        self.futures[job_id].set_result(dict(_WORKER_RESULT))


def _create_and_upload(
    service: RecordingJobService,
) -> tuple[dict[str, object], dict[str, object]]:
    request = _create_request()
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
) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if service.get(job_id)["status"] == expected:
            return
        time.sleep(0.01)
    raise AssertionError(f"job did not reach {expected}: {service.get(job_id)}")


class RestartAdmissionTests(unittest.TestCase):
    def test_immediate_restart_futures_are_drained_without_recursive_pump_failure(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = RecordingJobService(
                root,
                processor=_PendingProcessor(),
                supported_languages=("en",),
                now=lambda: "2026-07-14T21:40:00Z",
            )
            job_ids: list[str] = []
            for _ in range(220):
                request, created = _create_and_upload(first)
                first.commit(created["jobId"], _commit_request(request))
                job_ids.append(created["jobId"])
            first.begin_runtime_shutdown()

            resumed_processor = _ImmediateProcessor()
            resumed = _ObservedService(
                root,
                processor=resumed_processor,
                supported_languages=("en",),
                now=lambda: "2026-07-14T21:41:00Z",
                startup_worker_cleanup_verified=True,
            )
            try:
                self.assertEqual(len(resumed_processor.started), len(job_ids))
                self.assertEqual(resumed.max_active_pump_passes, 1)
                statuses = [resumed.get(job_id)["status"] for job_id in job_ids]
                self.assertEqual(statuses.count("complete"), len(job_ids))
                self.assertNotIn("failed", statuses)
            finally:
                resumed.begin_runtime_shutdown()

    def test_recovered_work_is_admitted_before_a_new_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = RecordingJobService(
                root,
                processor=_PendingProcessor(),
                supported_languages=("en",),
                now=lambda: "2026-07-14T21:42:00Z",
            )
            old_jobs: list[str] = []
            for _ in range(2):
                request, created = _create_and_upload(first)
                first.commit(created["jobId"], _commit_request(request))
                old_jobs.append(created["jobId"])
            first.begin_runtime_shutdown()

            processor = _BarrierProcessor()
            resumed = RecordingJobService(
                root,
                processor=processor,
                supported_languages=("en",),
                now=lambda: "2026-07-14T21:43:00Z",
                startup_worker_cleanup_verified=True,
            )
            new_request, newcomer = _create_and_upload(resumed)
            processor.wait_for_starts(1)
            first_old = processor.started[0]
            completion = threading.Thread(
                target=processor.complete,
                args=(first_old,),
                daemon=True,
            )
            completion.start()
            self.assertTrue(processor.first_slot_released.wait(timeout=5))

            with self.assertRaises(JobServiceError) as busy:
                resumed.commit(newcomer["jobId"], _commit_request(new_request))
            self.assertEqual(busy.exception.code, "SERVER_BUSY")
            self.assertTrue(busy.exception.retryable)
            self.assertEqual(processor.started, [first_old])

            processor.allow_first_service_callback.set()
            completion.join(timeout=5)
            self.assertFalse(completion.is_alive())
            processor.wait_for_starts(2)
            second_old = next(job_id for job_id in old_jobs if job_id != first_old)
            self.assertEqual(processor.started[:2], [first_old, second_old])
            processor.complete(second_old)
            _wait_for_status(resumed, second_old, "complete")

            resumed.commit(newcomer["jobId"], _commit_request(new_request))
            processor.wait_for_starts(3)
            self.assertEqual(
                processor.started,
                [first_old, second_old, newcomer["jobId"]],
            )
            processor.complete(newcomer["jobId"])
            _wait_for_status(resumed, newcomer["jobId"], "complete")
            resumed.begin_runtime_shutdown()


if __name__ == "__main__":
    unittest.main()
