from __future__ import annotations

from concurrent.futures import Future
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from yap_server.jobs import JobServiceError, RecordingJobService
from yap_server.jobs.stage_attempts import finish_stage, start_stage
from yap_server.pools.batch_contract import WorkerContainmentError

from .service_fixtures import _ControlledProcessor, _create_request


class _CountingProcessor(_ControlledProcessor):
    def __init__(self) -> None:
        super().__init__()
        self.reservation_count = 0

    def reserve(self, job_id: str, *, pcm_byte_length: int):
        self.reservation_count += 1
        return super().reserve(job_id, pcm_byte_length=pcm_byte_length)


class _UnfencedContainmentProcessor(_CountingProcessor):
    def cancel(self, _job_id: str) -> bool:
        self.future.set_exception(
            WorkerContainmentError("owned worker cleanup could not be verified")
        )
        return False


class RecordingJobStageRetryEdgeTests(unittest.TestCase):
    def test_restart_closes_interrupted_publication_before_restarting_asr(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            processor = _ControlledProcessor()
            service, request, job_id = _uploaded_service(root, processor)
            service.commit(
                job_id,
                {"captureManifest": request["captureManifest"], "chunkCount": 1},
            )
            attempts = service._state.stage_attempts[job_id]
            finish_stage(
                attempts,
                stage="asr",
                attempt=1,
                state="succeeded",
                completed_at_utc="2026-07-14T21:31:00Z",
                retryable=False,
                output_fingerprint_sha256="c" * 64,
            )
            alignment_attempt = start_stage(
                attempts,
                stage="alignment",
                input_fingerprint_sha256="c" * 64,
                component_id="alignment-gate",
                component_revision="alignment-unavailable-test-v1",
                started_at_utc="2026-07-14T21:31:00Z",
            )
            finish_stage(
                attempts,
                stage="alignment",
                attempt=alignment_attempt,
                state="unavailable",
                completed_at_utc="2026-07-14T21:31:00Z",
                retryable=False,
                reason="ALIGNMENT_UNAVAILABLE",
            )
            start_stage(
                attempts,
                stage="result_publication",
                input_fingerprint_sha256="d" * 64,
                component_id="yap-result-contract",
                component_revision="result-schema-1",
                started_at_utc="2026-07-14T21:31:00Z",
            )
            service._persist_job_locked(job_id)
            service.begin_runtime_shutdown()

            restart_processor = _ControlledProcessor()
            restarted = RecordingJobService(
                root,
                processor=restart_processor,
                supported_languages=("en",),
                now=lambda: "2026-07-14T21:32:00Z",
                startup_worker_cleanup_verified=True,
            )
            restarted_stages = restarted.get_stages(job_id)["stages"]
            self.assertEqual(
                [
                    (stage["stage"], stage["attempt"], stage["state"])
                    for stage in restarted_stages
                ],
                [
                    ("asr", 2, "running"),
                    ("alignment", 1, "unavailable"),
                    ("result_publication", 1, "failed"),
                ],
            )
            restart_processor.future.set_result(_worker_payload("Restarted ASR completed."))
            self.assertEqual(restarted.get(job_id)["status"], "complete")
            completed_stages = restarted.get_stages(job_id)["stages"]
            self.assertEqual(
                [
                    (stage["stage"], stage["attempt"], stage["state"])
                    for stage in completed_stages
                ],
                [
                    ("asr", 2, "succeeded"),
                    ("alignment", 2, "unavailable"),
                    ("result_publication", 2, "succeeded"),
                ],
            )

    def test_publication_intent_persist_failure_rolls_back_to_retryable_asr(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            processor = _ControlledProcessor()
            service, request, job_id = _uploaded_service(root, processor)
            service.commit(
                job_id,
                {"captureManifest": request["captureManifest"], "chunkCount": 1},
            )
            from yap_server.jobs import job_store as store_module

            original_publish_json = store_module.publish_json
            failed_once = False

            def fail_publication_intent_once(path: Path, value: object) -> None:
                nonlocal failed_once
                attempts = value.get("stageAttempts", []) if isinstance(value, dict) else []
                publication_running = any(
                    attempt.get("stage") == "result_publication"
                    and attempt.get("state") == "running"
                    for attempt in attempts
                    if isinstance(attempt, dict)
                )
                if path.name == "state.json" and publication_running and not failed_once:
                    failed_once = True
                    raise OSError("injected publication-intent failure")
                original_publish_json(path, value)

            with patch.object(
                store_module,
                "publish_json",
                fail_publication_intent_once,
            ):
                processor.future.set_result(_worker_payload("First result was not durable."))

            self.assertTrue(failed_once)
            failed = service.get(job_id)
            self.assertEqual(failed["status"], "failed")
            self.assertEqual(failed["error"]["code"], "SERVER_STORAGE_ERROR")
            failed_stages = service.get_stages(job_id)
            self.assertEqual(
                [
                    (stage["stage"], stage["state"], stage["retryable"])
                    for stage in failed_stages["stages"]
                ],
                [("asr", "failed", True)],
            )

            processor.future = Future()
            retried = service.retry_stage(
                job_id,
                "asr",
                {
                    "stage": "asr",
                    "attempt": 1,
                    "projectionRevision": failed_stages["projectionRevision"],
                    "captureManifestSha256": request["captureManifest"]["sha256"],
                },
            )
            self.assertEqual(retried["stages"][0]["attempt"], 2)
            processor.future.set_result(_worker_payload("Retry completed safely."))
            self.assertEqual(service.get(job_id)["status"], "complete")

    def test_migrated_incomplete_history_retains_new_retryable_attempt_input(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            initial_processor = _ControlledProcessor()
            service, request, job_id = _uploaded_service(root, initial_processor)
            state_path = root / "jobs" / job_id / "state.json"
            legacy = json.loads(state_path.read_text(encoding="utf-8"))
            legacy["schemaVersion"] = 4
            del legacy["stageHistoryComplete"]
            del legacy["stageAttempts"]
            del legacy["projectionRevision"]
            state_path.write_text(
                json.dumps(legacy, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )

            migrated_processor = _ControlledProcessor()
            migrated = RecordingJobService(
                root,
                processor=migrated_processor,
                supported_languages=("en",),
                now=lambda: "2026-07-14T21:32:00Z",
            )
            self.assertFalse(migrated.get_stages(job_id)["historyComplete"])
            migrated.commit(
                job_id,
                {"captureManifest": request["captureManifest"], "chunkCount": 1},
            )
            migrated_processor.future.set_exception(RuntimeError("retryable failure"))
            self.assertEqual(migrated.get(job_id)["status"], "failed")

            retry_processor = _ControlledProcessor()
            restarted = RecordingJobService(
                root,
                processor=retry_processor,
                supported_languages=("en",),
                now=lambda: "2026-07-14T21:33:00Z",
            )
            failed_stages = restarted.get_stages(job_id)
            self.assertFalse(failed_stages["historyComplete"])
            chunks = list((root / "jobs" / job_id / "chunks").iterdir())
            self.assertEqual(len(chunks), 1)
            retried = restarted.retry_stage(
                job_id,
                "asr",
                {
                    "stage": "asr",
                    "attempt": 1,
                    "projectionRevision": failed_stages["projectionRevision"],
                    "captureManifestSha256": request["captureManifest"]["sha256"],
                },
            )
            self.assertEqual(
                (retried["stages"][0]["attempt"], retried["stages"][0]["state"]),
                (2, "running"),
            )
            retry_processor.future.set_result(_worker_payload("Migrated retry succeeded."))
            self.assertEqual(restarted.get(job_id)["status"], "complete")

    def test_attempt_65_is_rejected_before_reserving_or_mutating_history(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            processor = _CountingProcessor()
            service, request, job_id = _uploaded_service(root, processor)
            service.commit(
                job_id,
                {"captureManifest": request["captureManifest"], "chunkCount": 1},
            )
            processor.future.set_exception(RuntimeError("attempt one failed"))
            attempts = service._state.stage_attempts[job_id]
            for attempt_number in range(2, 65):
                started_at = "2026-07-14T21:34:00Z"
                observed = start_stage(
                    attempts,
                    stage="asr",
                    input_fingerprint_sha256=request["captureManifest"]["sha256"],
                    component_id="cohere-batch",
                    component_revision="b" * 40,
                    started_at_utc=started_at,
                )
                self.assertEqual(observed, attempt_number)
                finish_stage(
                    attempts,
                    stage="asr",
                    attempt=observed,
                    state="failed",
                    completed_at_utc=started_at,
                    retryable=True,
                    reason="ASR_WORKER_FAILED",
                )
            service._persist_job_locked(job_id)
            before = service.get_stages(job_id)
            self.assertEqual(before["stages"][0]["attempt"], 64)
            self.assertEqual(processor.reservation_count, 1)

            with self.assertRaises(JobServiceError) as exhausted:
                service.retry_stage(
                    job_id,
                    "asr",
                    {
                        "stage": "asr",
                        "attempt": 64,
                        "projectionRevision": before["projectionRevision"],
                        "captureManifestSha256": request["captureManifest"]["sha256"],
                    },
                )
            self.assertEqual(exhausted.exception.code, "STAGE_ATTEMPT_LIMIT")
            self.assertFalse(exhausted.exception.retryable)
            self.assertEqual(processor.reservation_count, 1)
            after = service.get_stages(job_id)
            self.assertEqual(after["stages"], before["stages"])
            failed = service.get(job_id)
            self.assertEqual(failed["status"], "failed")
            self.assertEqual(failed["error"]["code"], "ASR_STAGE_ATTEMPT_LIMIT")
            self.assertFalse(failed["error"]["retryable"])
            self.assertEqual(list((root / "jobs" / job_id / "chunks").iterdir()), [])

    def test_cleanup_uncertainty_blocks_retry_without_trusting_processor_fencing(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            processor = _UnfencedContainmentProcessor()
            service, request, job_id = _uploaded_service(root, processor)
            service.commit(
                job_id,
                {"captureManifest": request["captureManifest"], "chunkCount": 1},
            )
            self.assertEqual(processor.reservation_count, 1)

            with self.assertRaises(JobServiceError) as cancellation:
                service.cancel(job_id)
            self.assertEqual(
                cancellation.exception.code,
                "CANCELLATION_CLEANUP_UNVERIFIED",
            )
            failed = service.get(job_id)
            self.assertEqual(failed["status"], "failed")
            self.assertEqual(failed["error"]["code"], "ASR_CLEANUP_UNVERIFIED")
            stages = service.get_stages(job_id)

            with self.assertRaises(JobServiceError) as retry:
                service.retry_stage(
                    job_id,
                    "asr",
                    {
                        "stage": "asr",
                        "attempt": 1,
                        "projectionRevision": stages["projectionRevision"],
                        "captureManifestSha256": request["captureManifest"]["sha256"],
                    },
                )
            self.assertEqual(retry.exception.code, "STAGE_NOT_RETRYABLE")
            self.assertEqual(processor.reservation_count, 1)


def _uploaded_service(
    root: Path,
    processor: _ControlledProcessor,
) -> tuple[RecordingJobService, dict[str, object], str]:
    service = RecordingJobService(
        root,
        processor=processor,
        supported_languages=("en",),
        now=lambda: "2026-07-14T21:31:00Z",
    )
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
    return service, request, str(created["jobId"])


def _worker_payload(transcript: str) -> dict[str, object]:
    return {
        "model": {
            "id": "CohereLabs/cohere-transcribe-03-2026",
            "revision": "b1eacc2686a3d08ceaae5f24a88b1d519620bc09",
        },
        "transcript": {"text": transcript},
    }


if __name__ == "__main__":
    unittest.main()
