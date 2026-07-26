from __future__ import annotations

import hashlib
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from yap_server.jobs import JobServiceError, RecordingJobService
from yap_server.jobs.job_store import DurableJobState, RecordingJobStore
from yap_server.pools.batch_asr import BatchAsrPool

from tests.asr_route_fixtures import TEST_ASR_CATALOG_REVISION, test_asr_route

from .service_fixtures import (
    _ControlledProcessor,
    _DelayedCancellationWorker,
    _Processor,
    _create_request,
)


class RecordingJobRetentionTests(unittest.TestCase):
    def test_legacy_tombstone_cleanup_has_a_global_entry_budget_and_finishes(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            jobs_root = root / "jobs"
            tombstone = jobs_root / f".deleting-job-{1:032x}"
            chunks = tombstone / "chunks"
            chunks.mkdir(parents=True)
            for index in range(17):
                (chunks / f"legacy-{index:04d}.pcm").write_bytes(b"x")
            (tombstone / "state.json").write_text("{}", encoding="utf-8")
            state = DurableJobState(
                pending_deletions={tombstone.name: None},
            )
            store = _job_store(root)
            passes = 0

            with (
                patch("os.unlink", wraps=os.unlink) as unlink,
                patch("os.rmdir", wraps=os.rmdir) as rmdir,
            ):
                while state.pending_deletions and passes < 20:
                    unlink.reset_mock()
                    rmdir.reset_mock()
                    store.reconcile_pending_deletions(
                        state,
                        max_tombstones=1,
                        max_entries=5,
                    )
                    self.assertLessEqual(unlink.call_count + rmdir.call_count, 5)
                    passes += 1

            self.assertGreater(passes, 1)
            self.assertEqual(state.pending_deletions, {})
            self.assertFalse(tombstone.exists())

    def test_incremental_tombstone_cleanup_does_not_follow_directory_links(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            outside = root / "outside"
            outside.mkdir()
            protected = outside / "protected.txt"
            protected.write_text("keep", encoding="utf-8")
            tombstone = root / "jobs" / f".deleting-job-{4:032x}"
            tombstone.mkdir(parents=True)
            link = tombstone / "redirect"
            try:
                link.symlink_to(outside, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"directory links are unavailable: {error}")
            state = DurableJobState(
                pending_deletions={tombstone.name: None},
            )

            _job_store(root).reconcile_pending_deletions(
                state,
                max_tombstones=1,
                max_entries=4,
            )

            self.assertTrue(protected.is_file())
            self.assertEqual(protected.read_text(encoding="utf-8"), "keep")
            self.assertEqual(state.pending_deletions, {})

    def test_max_chunk_shaped_tombstone_cleanup_is_bounded_and_eventual(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            jobs_root = root / "jobs"
            tombstone = jobs_root / f".deleting-job-{2:032x}"
            chunks = tombstone / "chunks"
            chunks.mkdir(parents=True)
            for index in range(4096):
                (chunks / f"{index:08d}.pcm").touch()
            state = DurableJobState(
                pending_deletions={tombstone.name: None},
            )
            store = _job_store(root)
            passes = 0

            with (
                patch("os.unlink", wraps=os.unlink) as unlink,
                patch("os.rmdir", wraps=os.rmdir) as rmdir,
            ):
                while state.pending_deletions and passes < 40:
                    unlink.reset_mock()
                    rmdir.reset_mock()
                    store.reconcile_pending_deletions(
                        state,
                        max_tombstones=1,
                        max_entries=257,
                    )
                    self.assertLessEqual(
                        unlink.call_count + rmdir.call_count,
                        257,
                    )
                    passes += 1

            self.assertGreater(passes, 1)
            self.assertLess(passes, 40)
            self.assertEqual(state.pending_deletions, {})
            self.assertFalse(tombstone.exists())

    def test_expired_job_transition_only_renames_a_max_chunk_shaped_tree(
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
            created = service.create(
                _create_request(retention_expires_at_utc="2026-07-15T00:00:00Z")
            )
            job_root = root / "jobs" / created["jobId"]
            chunks = job_root / "chunks"
            for index in range(4096):
                (chunks / f"legacy-{index:08d}.pcm").touch()
            clock["now"] = "2026-07-16T00:00:00Z"

            with (
                patch("os.unlink", wraps=os.unlink) as unlink,
                patch("os.rmdir", wraps=os.rmdir) as rmdir,
            ):
                self.assertEqual(service.prune_expired(), 1)

            self.assertEqual(unlink.call_count + rmdir.call_count, 0)
            self.assertFalse(job_root.exists())
            tombstones = list((root / "jobs").glob(".deleting-*"))
            self.assertEqual(len(tombstones), 1)
            self.assertEqual(len(list((tombstones[0] / "chunks").iterdir())), 4096)

            for _ in range(40):
                service.prune_expired()
                if not list((root / "jobs").glob(".deleting-*")):
                    break
            self.assertEqual(list((root / "jobs").glob(".deleting-*")), [])

    def test_startup_does_not_eagerly_purge_expired_cancelled_legacy_chunks(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            clock = {"now": "2026-07-14T21:15:00Z"}
            original = RecordingJobService(
                root,
                processor=_Processor(),
                supported_languages=("en",),
                now=lambda: clock["now"],
            )
            created = original.create(
                _create_request(retention_expires_at_utc="2026-07-15T00:00:00Z")
            )
            original.cancel(created["jobId"])
            chunks = root / "jobs" / created["jobId"] / "chunks"
            for index in range(257):
                (chunks / f"legacy-{index:08d}.pcm").touch()
            clock["now"] = "2026-07-16T00:00:00Z"

            with (
                patch("os.unlink", wraps=os.unlink) as unlink,
                patch("os.rmdir", wraps=os.rmdir) as rmdir,
            ):
                RecordingJobService(
                    root,
                    processor=_Processor(),
                    supported_languages=("en",),
                    now=lambda: clock["now"],
                    startup_worker_cleanup_verified=True,
                )

            self.assertEqual(unlink.call_count + rmdir.call_count, 0)
            tombstones = list((root / "jobs").glob(".deleting-*"))
            self.assertEqual(len(tombstones), 1)
            self.assertEqual(len(list((tombstones[0] / "chunks").iterdir())), 257)

    def test_startup_and_create_bound_expired_job_transitions_per_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            clock = {"now": "2026-07-14T21:15:00Z"}
            original = RecordingJobService(
                root,
                processor=_Processor(),
                supported_languages=("en",),
                now=lambda: clock["now"],
            )
            expired_ids = []
            for index in range(5):
                created = original.create(
                    _create_request(
                        session_id=f"s-batch-expired-{index}",
                        retention_expires_at_utc="2026-07-15T00:00:00Z",
                    )
                )
                original.cancel(created["jobId"])
                expired_ids.append(created["jobId"])
            clock["now"] = "2026-07-16T00:00:00Z"

            with patch(
                "yap_server.jobs.service._MAX_EXPIRED_JOB_TRANSITIONS_PER_PASS",
                2,
                create=True,
            ):
                restarted = RecordingJobService(
                    root,
                    processor=_Processor(),
                    supported_languages=("en",),
                    now=lambda: clock["now"],
                    startup_worker_cleanup_verified=True,
                )
                jobs_root = root / "jobs"
                self.assertEqual(len(list(jobs_root.glob(".deleting-*"))), 2)
                self.assertEqual(
                    sum((jobs_root / job_id).exists() for job_id in expired_ids),
                    3,
                )

                fresh = restarted.create(
                    _create_request(
                        session_id="s-batch-after-bounded-expiry",
                        retention_expires_at_utc="2026-08-13T21:00:00Z",
                    )
                )

                self.assertEqual(fresh["status"], "accepted")
                self.assertLessEqual(
                    len(list(jobs_root.glob(".deleting-*"))),
                    2,
                )
                self.assertEqual(
                    sum((jobs_root / job_id).exists() for job_id in expired_ids),
                    1,
                )
                for _ in range(10):
                    restarted.prune_expired()
                    if not any(
                        (jobs_root / job_id).exists() for job_id in expired_ids
                    ) and not list(jobs_root.glob(".deleting-*")):
                        break

            self.assertFalse(
                any((root / "jobs" / job_id).exists() for job_id in expired_ids)
            )
            self.assertEqual(list((root / "jobs").glob(".deleting-*")), [])

    def test_startup_does_not_recover_expired_processing_beyond_transition_budget(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            clock = {"now": "2026-07-14T21:15:00Z"}
            original_processor = _ControlledProcessor()
            original = RecordingJobService(
                root,
                processor=original_processor,
                supported_languages=("en",),
                now=lambda: clock["now"],
            )
            expired_ids: list[str] = []
            chunk = bytes(320)
            for index in range(10):
                session_id = f"s-expired-processing-{index}"
                request = _create_request(
                    session_id=session_id,
                    retention_expires_at_utc="2026-07-15T00:00:00Z",
                )
                created = original.create(request)
                original.accept_chunk(
                    original.prepare_chunk_upload(
                        created["jobId"],
                        track_id="track-1",
                        sequence_start=0,
                        sequence_end=159,
                        idempotency_key=f"1/{session_id}/track-1/0/159",
                        content_sha256=hashlib.sha256(chunk).hexdigest(),
                        audio_codec="pcm_s16le",
                        sample_rate_hz=16000,
                        channels=1,
                        content_length=len(chunk),
                    ),
                    chunk,
                )
                committed = original.commit(
                    created["jobId"],
                    {
                        "captureManifest": request["captureManifest"],
                        "chunkCount": 1,
                    },
                )
                self.assertEqual(committed["status"], "server_processing")
                expired_ids.append(created["jobId"])
            self.assertEqual(len(original_processor.jobs), 10)
            original.begin_runtime_shutdown()
            clock["now"] = "2026-07-16T00:00:00Z"
            restarted_processor = _ControlledProcessor()

            restarted = RecordingJobService(
                root,
                processor=restarted_processor,
                supported_languages=("en",),
                now=lambda: clock["now"],
                startup_worker_cleanup_verified=True,
            )

            jobs_root = root / "jobs"
            remaining = [
                job_id for job_id in expired_ids if (jobs_root / job_id).is_dir()
            ]
            self.assertEqual(len(list(jobs_root.glob(".deleting-*"))), 8)
            self.assertEqual(len(remaining), 2)
            self.assertEqual(restarted_processor.jobs, [])
            for job_id in remaining:
                self.assertEqual(restarted.get(job_id)["status"], "server_processing")
                state = (jobs_root / job_id / "state.json").read_text(
                    encoding="utf-8"
                )
                self.assertEqual(state.count('"state":"running"'), 1)
                self.assertNotIn("SERVER_RESTARTED", state)

    def test_startup_uses_one_bounded_legacy_debt_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tombstone = root / "jobs" / f".deleting-job-{3:032x}"
            tombstone.mkdir(parents=True)
            for index in range(20):
                (tombstone / f"legacy-{index:04d}.bin").touch()

            with (
                patch(
                    "yap_server.jobs.job_store._MAX_PENDING_DELETION_ENTRIES_PER_PASS",
                    4,
                    create=True,
                ),
                patch(
                    "yap_server.jobs.job_store._MAX_PENDING_DELETION_TOMBSTONES_PER_PASS",
                    1,
                    create=True,
                ),
                patch("os.unlink", wraps=os.unlink) as unlink,
                patch("os.rmdir", wraps=os.rmdir) as rmdir,
            ):
                RecordingJobService(
                    root,
                    processor=_Processor(),
                    supported_languages=("en",),
                    now=lambda: "2026-07-14T21:15:00Z",
                )

            self.assertLessEqual(unlink.call_count + rmdir.call_count, 4)
            self.assertTrue(tombstone.exists())

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
            interrupted = {"raised": False}

            def remove_state_then_fail(
                _directory: Path,
                **details: object,
            ) -> bool:
                tombstone = Path(details["tombstone_root"])
                if not interrupted["raised"]:
                    (tombstone / "state.json").unlink()
                    interrupted["raised"] = True
                    raise OSError("injected partial retention deletion")
                return False

            self.assertEqual(service.prune_expired(), 1)
            with patch.object(
                service._store,
                "_delete_directory_incrementally",
                side_effect=remove_state_then_fail,
            ):
                self.assertEqual(service.prune_expired(), 0)

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
                patch.object(
                    service._store,
                    "_delete_directory_incrementally",
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
                    "yap_server.jobs.job_store._MAX_PENDING_DELETION_TOMBSTONES_PER_PASS",
                    3,
                    create=True,
                ),
                patch.object(
                    RecordingJobStore,
                    "_delete_directory_incrementally",
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


def _job_store(root: Path) -> RecordingJobStore:
    return RecordingJobStore(
        root,
        supported_languages=("en",),
        now=lambda: "2026-07-14T21:15:00Z",
        startup_worker_cleanup_verified=True,
        route_resolver=test_asr_route,
        asr_catalog_revision=TEST_ASR_CATALOG_REVISION,
    )
