from __future__ import annotations

import hashlib
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from yap_server.jobs import JobServiceError, RecordingJobService
from yap_server.pools.batch_asr import BatchAsrPool

from tests.asr_route_fixtures import TEST_ASR_CATALOG_REVISION, test_asr_route

from .service_fixtures import _DelayedCancellationWorker, _Processor, _create_request


class RecordingJobRetentionTests(unittest.TestCase):
    def test_expired_terminal_jobs_are_pruned_before_new_intake(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            clock = {"now": "2026-07-14T21:15:00Z"}
            service = RecordingJobService(
                root,
                processor=_Processor(),
                supported_languages=("en",),
                now=lambda: clock["now"],
            )
            expired = service.create(
                _create_request(retention_expires_at_utc="2026-07-15T00:00:00Z"),
                idempotency_key="expired-create",
            )
            service.cancel(expired["jobId"])
            expired_root = root / "jobs" / expired["jobId"]
            self.assertTrue(expired_root.is_dir())
            clock["now"] = "2026-07-16T00:00:00Z"

            fresh = service.create(
                _create_request(
                    session_id="s-batch-fresh",
                    retention_expires_at_utc="2026-08-13T21:00:00Z",
                ),
                idempotency_key="fresh-create",
            )

            self.assertEqual(fresh["status"], "accepted")
            self.assertFalse(expired_root.exists())
            with self.assertRaises(KeyError):
                service.get(expired["jobId"])

    def test_idle_maintenance_prunes_expired_terminal_jobs_without_new_intake(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            clock = {"now": "2026-07-14T21:15:00Z"}
            service = RecordingJobService(
                root,
                processor=_Processor(),
                supported_languages=("en",),
                now=lambda: clock["now"],
            )
            expired = service.create(
                _create_request(retention_expires_at_utc="2026-07-15T00:00:00Z")
            )
            service.cancel(expired["jobId"])
            expired_root = root / "jobs" / expired["jobId"]
            clock["now"] = "2026-07-16T00:00:00Z"

            self.assertEqual(service.prune_expired(), 1)
            self.assertFalse(expired_root.exists())
            with self.assertRaises(KeyError):
                service.get(expired["jobId"])

    def test_idle_maintenance_cancels_and_removes_expired_uncommitted_audio(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            clock = {"now": "2026-07-14T21:15:00Z"}
            service = RecordingJobService(
                root,
                processor=_Processor(),
                supported_languages=("en",),
                now=lambda: clock["now"],
            )
            expired = service.create(
                _create_request(retention_expires_at_utc="2026-07-15T00:00:00Z")
            )
            expired_root = root / "jobs" / expired["jobId"]
            clock["now"] = "2026-07-16T00:00:00Z"

            self.assertEqual(service.prune_expired(), 1)
            self.assertFalse(expired_root.exists())
            with self.assertRaises(KeyError):
                service.get(expired["jobId"])

    def test_restart_recovers_when_retention_delete_stops_after_state_removal(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            clock = {"now": "2026-07-14T21:15:00Z"}
            service = RecordingJobService(
                root,
                processor=_Processor(),
                supported_languages=("en",),
                now=lambda: clock["now"],
            )
            expired = service.create(
                _create_request(retention_expires_at_utc="2026-07-15T00:00:00Z")
            )
            service.cancel(expired["jobId"])
            healthy = service.create(
                _create_request(
                    session_id="s-batch-healthy",
                    retention_expires_at_utc="2026-08-13T21:00:00Z",
                )
            )
            clock["now"] = "2026-07-16T00:00:00Z"
            original_rmtree = shutil.rmtree
            interrupted = {"raised": False}

            def remove_state_then_fail(path: Path) -> None:
                candidate = Path(path)
                if not interrupted["raised"] and candidate.name.startswith(
                    ".deleting-"
                ):
                    (candidate / "state.json").unlink()
                    interrupted["raised"] = True
                    raise OSError("injected partial retention deletion")
                original_rmtree(candidate)

            with patch(
                "yap_server.jobs.job_store.shutil.rmtree",
                side_effect=remove_state_then_fail,
            ):
                self.assertEqual(service.prune_expired(), 1)

            tombstones = list((root / "jobs").glob(".deleting-*"))
            self.assertEqual(len(tombstones), 1)
            self.assertFalse((root / "jobs" / expired["jobId"]).exists())

            restarted = RecordingJobService(
                root,
                processor=_Processor(),
                supported_languages=("en",),
                now=lambda: clock["now"],
            )

            self.assertEqual(restarted.get(healthy["jobId"])["status"], "accepted")
            self.assertEqual(list((root / "jobs").glob(".deleting-*")), [])

    def test_expired_running_job_stays_nonterminal_until_worker_cleanup_finishes(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            clock = {"now": "2026-07-14T21:15:00Z"}
            worker = _DelayedCancellationWorker()
            pool = BatchAsrPool(
                worker,
                max_workers=1,
                max_queued=0,
                route_resolver=test_asr_route,
                asr_catalog_revision=TEST_ASR_CATALOG_REVISION,
            )
            try:
                service = RecordingJobService(
                    root,
                    processor=pool,
                    supported_languages=("en",),
                    now=lambda: clock["now"],
                )
                request = _create_request(
                    retention_expires_at_utc="2026-07-15T00:00:00Z"
                )
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
                service.commit(
                    created["jobId"],
                    {
                        "captureManifest": request["captureManifest"],
                        "chunkCount": 1,
                    },
                )
                self.assertTrue(worker.started.wait(timeout=2))
                job_root = root / "jobs" / created["jobId"]
                clock["now"] = "2026-07-16T00:00:00Z"

                self.assertEqual(service.prune_expired(), 0)
                self.assertTrue(worker.cancellation_received.wait(timeout=2))
                self.assertEqual(
                    service.get(created["jobId"])["status"],
                    "server_processing",
                )
                self.assertTrue(job_root.is_dir())

                worker.release_cleanup.set()
                deadline = time.monotonic() + 2
                while pool.outstanding_count and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertEqual(pool.outstanding_count, 0)
                self.assertEqual(service.prune_expired(), 1)
                self.assertFalse(job_root.exists())
            finally:
                worker.release_cleanup.set()
                pool.shutdown()

    def test_active_job_count_cap_fails_closed_without_mutating_storage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            service = RecordingJobService(
                root,
                processor=_Processor(),
                supported_languages=("en",),
                now=lambda: "2026-07-14T21:16:00Z",
            )

            with patch("yap_server.jobs.service._MAX_STORED_JOBS", 1):
                first = service.create(_create_request())
                with self.assertRaises(JobServiceError) as full:
                    service.create(_create_request(session_id="s-batch-second"))

            self.assertEqual(full.exception.status, 429)
            self.assertEqual(full.exception.code, "SERVER_STORAGE_LIMIT")
            self.assertFalse(full.exception.retryable)
            self.assertEqual(
                [path.name for path in (root / "jobs").iterdir()],
                [first["jobId"]],
            )

    def test_pending_deletion_debt_still_counts_against_job_capacity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            clock = {"now": "2026-07-14T21:15:00Z"}
            service = RecordingJobService(
                root,
                processor=_Processor(),
                supported_languages=("en",),
                now=lambda: clock["now"],
            )
            expired = service.create(
                _create_request(retention_expires_at_utc="2026-07-15T00:00:00Z")
            )
            service.cancel(expired["jobId"])
            clock["now"] = "2026-07-16T00:00:00Z"

            with (
                patch("yap_server.jobs.service._MAX_STORED_JOBS", 2),
                patch(
                    "yap_server.jobs.job_store.shutil.rmtree",
                    side_effect=OSError("persistent deletion failure"),
                ),
            ):
                self.assertEqual(service.prune_expired(), 1)
                accepted = service.create(
                    _create_request(
                        session_id="s-batch-after-deletion-debt",
                        retention_expires_at_utc="2026-08-13T21:00:00Z",
                    )
                )
                with self.assertRaises(JobServiceError) as full:
                    service.create(
                        _create_request(
                            session_id="s-batch-over-deletion-debt",
                            retention_expires_at_utc="2026-08-13T21:00:00Z",
                        )
                    )

            self.assertEqual(accepted["status"], "accepted")
            self.assertEqual(full.exception.status, 429)
            self.assertEqual(full.exception.code, "SERVER_STORAGE_LIMIT")
            self.assertEqual(
                len(list((root / "jobs").glob(".deleting-*"))),
                1,
            )

    def test_create_retries_only_a_bounded_deletion_debt_batch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            jobs_root = root / "jobs"
            jobs_root.mkdir(parents=True)
            for index in range(10):
                (jobs_root / f".deleting-job-{index:032x}").mkdir()

            with (
                patch(
                    "yap_server.jobs.job_store._MAX_PENDING_DELETION_RECONCILIATIONS",
                    3,
                    create=True,
                ),
                patch(
                    "yap_server.jobs.job_store.shutil.rmtree",
                    side_effect=OSError("persistent deletion failure"),
                ) as remove,
            ):
                service = RecordingJobService(
                    root,
                    processor=_Processor(),
                    supported_languages=("en",),
                    now=lambda: "2026-07-14T21:15:00Z",
                )
                remove.reset_mock()

                created = service.create(_create_request())

            self.assertEqual(created["status"], "accepted")
            self.assertEqual(remove.call_count, 3)
            self.assertEqual(
                len(list(jobs_root.glob(".deleting-*"))),
                10,
            )
