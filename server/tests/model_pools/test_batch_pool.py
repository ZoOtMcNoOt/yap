from __future__ import annotations

import unittest
from pathlib import Path
import threading
import time

from tests.asr_route_fixtures import TEST_ASR_CATALOG_REVISION, test_asr_route

from yap_server.jobs.contract_values import MAX_JOB_PCM_BYTES
from yap_server.pools.batch_asr import (
    BatchAsrJob,
    BatchAsrPool,
    BatchWorker,
    DuplicatePoolJob,
    PoolBackpressure,
    PoolFenced,
    WorkerContainmentError,
    WorkerExecutionError,
)

from .batch_asr_fixtures import (
    AUDIO_SHA256,
    BlockingWorker,
    CancellationAwareWorker,
    ClosableWorker,
    CloseContainmentFailureWorker,
    ContainmentFailureWorker,
)


def _test_pool(
    worker: BatchWorker,
    *,
    max_workers: int,
    max_queued: int,
) -> BatchAsrPool:
    return BatchAsrPool(
        worker,
        route_resolver=test_asr_route,
        asr_catalog_revision=TEST_ASR_CATALOG_REVISION,
        max_workers=max_workers,
        max_queued=max_queued,
    )


class BatchAsrPoolTests(unittest.TestCase):
    def test_eight_lane_plan_slot_and_pcm_capacity_edges_refund_exactly(self) -> None:
        pool = BatchAsrPool(
            BlockingWorker(),
            route_resolver=test_asr_route,
            asr_catalog_revision=TEST_ASR_CATALOG_REVISION,
            max_workers=8,
            max_queued=8,
            max_inflight_pcm_bytes=MAX_JOB_PCM_BYTES,
        )
        thirty_second_pcm_bytes = 16_000 * 2 * 30
        two_hour_pcm_bytes = 16_000 * 2 * 2 * 60 * 60
        try:
            slot_reservations = [
                pool.reserve(
                    f"slot-{index}",
                    pcm_byte_length=thirty_second_pcm_bytes,
                )
                for index in range(16)
            ]
            with self.assertRaises(PoolBackpressure):
                pool.reserve("slot-17", pcm_byte_length=thirty_second_pcm_bytes)
            for reservation in slot_reservations:
                reservation.abort()
            self.assertEqual(pool.outstanding_count, 0)

            first = pool.reserve("two-hour-1", pcm_byte_length=two_hour_pcm_bytes)
            second = pool.reserve("two-hour-2", pcm_byte_length=two_hour_pcm_bytes)
            with self.assertRaises(PoolBackpressure):
                pool.reserve("one-second", pcm_byte_length=16_000 * 2)
            first.abort()
            replacement = pool.reserve("one-second", pcm_byte_length=16_000 * 2)
            replacement.abort()
            second.abort()
            self.assertEqual(pool.outstanding_count, 0)
        finally:
            pool.shutdown()

    def test_pool_bounds_aggregate_pcm_before_preparation(self) -> None:
        pool = BatchAsrPool(
            BlockingWorker(),
            route_resolver=test_asr_route,
            asr_catalog_revision=TEST_ASR_CATALOG_REVISION,
            max_workers=2,
            max_queued=2,
            max_inflight_pcm_bytes=10,
        )
        try:
            first = pool.reserve("job-1", pcm_byte_length=6)
            with self.assertRaises(PoolBackpressure):
                pool.reserve("job-2", pcm_byte_length=5)
            first.abort()

            replacement = pool.reserve("job-2", pcm_byte_length=10)
            replacement.abort()
            with self.assertRaises(ValueError):
                pool.reserve("job-3", pcm_byte_length=11)
        finally:
            pool.shutdown()

    def test_batch_job_requires_an_explicit_iso_language(self) -> None:
        job = BatchAsrJob(
            "job-1",
            Path("one.wav"),
            Path("one.json"),
            language="en",
            input_sha256=AUDIO_SHA256,
            route=test_asr_route(),
        )

        self.assertEqual(job.language, "en")
        for invalid in ("", "auto", "EN", "eng", "../en"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    BatchAsrJob(
                        "job-1",
                        Path("one.wav"),
                        Path("one.json"),
                        language=invalid,
                        input_sha256=AUDIO_SHA256,
                        route=test_asr_route(),
                    )

    def test_pool_bounds_running_and_queued_work(self) -> None:
        worker = BlockingWorker()
        pool = _test_pool(worker, max_workers=1, max_queued=1)
        try:
            first = pool.submit(
                BatchAsrJob(
                    "job-1",
                    Path("one.wav"),
                    Path("one.json"),
                    language="en",
                    input_sha256=AUDIO_SHA256,
                    route=test_asr_route(),
                )
            )
            self.assertTrue(worker.started.wait(timeout=2))
            second = pool.submit(
                BatchAsrJob(
                    "job-2",
                    Path("two.wav"),
                    Path("two.json"),
                    language="en",
                    input_sha256=AUDIO_SHA256,
                    route=test_asr_route(),
                )
            )

            with self.assertRaises(PoolBackpressure):
                pool.submit(
                    BatchAsrJob(
                        "job-3",
                        Path("three.wav"),
                        Path("three.json"),
                        language="en",
                        input_sha256=AUDIO_SHA256,
                        route=test_asr_route(),
                    )
                )

            worker.release.set()
            self.assertEqual(first.result(timeout=2)["jobId"], "job-1")
            self.assertEqual(second.result(timeout=2)["jobId"], "job-2")
        finally:
            worker.release.set()
            pool.shutdown()

    def test_reservation_bounds_capacity_before_input_preparation_starts(self) -> None:
        worker = BlockingWorker()
        pool = _test_pool(worker, max_workers=1, max_queued=0)
        preparation_started = threading.Event()
        release_preparation = threading.Event()
        try:
            reservation = pool.reserve("job-1")
            self.assertEqual(pool.outstanding_count, 1)
            self.assertFalse(preparation_started.is_set())
            with self.assertRaises(PoolBackpressure):
                pool.reserve("job-2")

            def prepare(_cancellation: threading.Event) -> BatchAsrJob:
                preparation_started.set()
                if not release_preparation.wait(timeout=2):
                    raise TimeoutError("test preparation was not released")
                return BatchAsrJob(
                    "job-1",
                    Path("one.wav"),
                    Path("one.json"),
                    language="en",
                    input_sha256=AUDIO_SHA256,
                    route=test_asr_route(),
                )

            future = reservation.start(prepare)
            self.assertTrue(preparation_started.wait(timeout=2))
            release_preparation.set()
            self.assertTrue(worker.started.wait(timeout=2))
            worker.release.set()
            self.assertEqual(future.result(timeout=2)["jobId"], "job-1")
            self.assertEqual(pool.outstanding_count, 0)
        finally:
            release_preparation.set()
            worker.release.set()
            pool.shutdown()

    def test_aborted_reservation_releases_exactly_one_capacity_slot(self) -> None:
        pool = _test_pool(BlockingWorker(), max_workers=1, max_queued=0)
        try:
            reservation = pool.reserve("job-1")
            reservation.abort()
            reservation.abort()

            self.assertEqual(pool.outstanding_count, 0)
            replacement = pool.reserve("job-2")
            replacement.abort()
            self.assertEqual(pool.outstanding_count, 0)
        finally:
            pool.shutdown()

    def test_pool_rejects_duplicate_outstanding_job(self) -> None:
        worker = BlockingWorker()
        pool = _test_pool(worker, max_workers=1, max_queued=1)
        try:
            job = BatchAsrJob(
                "job-1",
                Path("one.wav"),
                Path("one.json"),
                language="en",
                input_sha256=AUDIO_SHA256,
                route=test_asr_route(),
            )
            future = pool.submit(job)
            self.assertTrue(worker.started.wait(timeout=2))
            with self.assertRaises(DuplicatePoolJob):
                pool.submit(job)
            worker.release.set()
            future.result(timeout=2)
        finally:
            worker.release.set()
            pool.shutdown()

    def test_pool_shutdown_stops_the_worker_before_waiting_for_threads(self) -> None:
        worker = ClosableWorker()
        pool = _test_pool(worker, max_workers=1, max_queued=0)
        pool.submit(
            BatchAsrJob(
                "job-1",
                Path("one.wav"),
                Path("one.json"),
                language="en",
                input_sha256=AUDIO_SHA256,
                route=test_asr_route(),
            )
        )
        self.assertTrue(worker.started.wait(timeout=2))

        pool.shutdown()

        self.assertTrue(worker.closed.is_set())

    def test_pool_shutdown_does_not_wait_forever_after_containment_failure(self) -> None:
        worker = CloseContainmentFailureWorker()
        pool = _test_pool(worker, max_workers=1, max_queued=0)
        future = pool.submit(
            BatchAsrJob(
                "job-1",
                Path("one.wav"),
                Path("one.json"),
                language="en",
                input_sha256=AUDIO_SHA256,
                route=test_asr_route(),
            )
        )
        self.assertTrue(worker.started.wait(timeout=2))

        started = time.monotonic()
        try:
            with self.assertRaisesRegex(WorkerContainmentError, "cleanup"):
                pool.shutdown()
            self.assertLess(time.monotonic() - started, 1)
            self.assertTrue(pool.fenced)
        finally:
            worker.release.set()
        self.assertEqual(future.result(timeout=2)["jobId"], "job-1")

    def test_pool_cancels_one_running_job_without_stopping_the_worker(self) -> None:
        worker = CancellationAwareWorker()
        pool = _test_pool(worker, max_workers=1, max_queued=0)
        try:
            future = pool.submit(
                BatchAsrJob(
                    "job-1",
                    Path("one.wav"),
                    Path("one.json"),
                    language="en",
                    input_sha256=AUDIO_SHA256,
                    route=test_asr_route(),
                )
            )
            self.assertTrue(worker.started.wait(timeout=2))

            self.assertTrue(pool.cancel("job-1"))

            with self.assertRaisesRegex(WorkerExecutionError, "cancelled"):
                future.result(timeout=2)
            self.assertTrue(worker.stopped.is_set())
            self.assertEqual(pool.outstanding_count, 0)
            self.assertFalse(pool.cancel("job-1"))
        finally:
            pool.shutdown()

    def test_pool_cancels_queued_work_without_deadlocking_its_completion_callback(
        self,
    ) -> None:
        worker = BlockingWorker()
        pool = _test_pool(worker, max_workers=1, max_queued=1)
        try:
            running = pool.submit(
                BatchAsrJob(
                    "job-1",
                    Path("one.wav"),
                    Path("one.json"),
                    language="en",
                    input_sha256=AUDIO_SHA256,
                    route=test_asr_route(),
                )
            )
            self.assertTrue(worker.started.wait(timeout=2))
            queued = pool.submit(
                BatchAsrJob(
                    "job-2",
                    Path("two.wav"),
                    Path("two.json"),
                    language="en",
                    input_sha256=AUDIO_SHA256,
                    route=test_asr_route(),
                )
            )

            self.assertTrue(pool.cancel("job-2"))

            self.assertTrue(queued.cancelled())
            self.assertEqual(pool.outstanding_count, 1)
            worker.release.set()
            running.result(timeout=2)
            self.assertEqual(pool.outstanding_count, 0)
        finally:
            worker.release.set()
            pool.shutdown()

    def test_pool_fences_new_work_after_unverified_container_cleanup(self) -> None:
        pool = _test_pool(
            ContainmentFailureWorker(),
            max_workers=1,
            max_queued=0,
        )
        job = BatchAsrJob(
            "job-1",
            Path("one.wav"),
            Path("one.json"),
            language="en",
            input_sha256=AUDIO_SHA256,
            route=test_asr_route(),
        )
        try:
            with self.assertRaises(WorkerContainmentError):
                pool.submit(job).result(timeout=2)

            with self.assertRaisesRegex(PoolFenced, "containment"):
                pool.submit(
                    BatchAsrJob(
                        "job-2",
                        Path("two.wav"),
                        Path("two.json"),
                        language="en",
                        input_sha256=AUDIO_SHA256,
                        route=test_asr_route(),
                    )
                )
            self.assertTrue(pool.fenced)
            self.assertEqual(pool.outstanding_count, 0)
        finally:
            pool.shutdown()
