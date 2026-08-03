from __future__ import annotations

from concurrent.futures import Future
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import wave

from yap_server.jobs import JobServiceError, RecordingJobService
from yap_server.language_span_contract import (
    ServerUtteranceLanguageObservation,
    build_server_language_span_evidence,
)
from yap_server.pools.batch_contract import (
    AsrRouteDecision,
    ProviderCapacityUnavailable,
)

from .service_fixtures import (
    _BusyProcessor,
    _ControlledProcessor,
    _Processor,
    _create_request,
)


class RecordingJobProcessingTests(unittest.TestCase):
    def test_commit_builds_worker_wav_and_publishes_an_immutable_result(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            processor = _ControlledProcessor()
            service = RecordingJobService(
                Path(temporary),
                processor=processor,
                supported_languages=("en",),
                now=lambda: "2026-07-14T21:03:00Z",
            )
            request = _create_request()
            created = service.create(request)
            chunk = bytes(320)
            plan = service.prepare_chunk_upload(
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
            )
            service.accept_chunk(plan, chunk)

            committed = service.commit(
                created["jobId"],
                {
                    "captureManifest": request["captureManifest"],
                    "chunkCount": 1,
                },
            )

            self.assertEqual(committed["status"], "server_processing")
            self.assertEqual(processor.reserved_pcm_bytes, [len(chunk)])
            self.assertEqual(len(processor.jobs), 1)
            worker_job = processor.jobs[0]
            self.assertEqual(worker_job.job_id, created["jobId"])
            self.assertEqual(worker_job.language, "en-US")
            with wave.open(str(worker_job.input_path), "rb") as audio:
                self.assertEqual(audio.getnchannels(), 1)
                self.assertEqual(audio.getframerate(), 16000)
                self.assertEqual(audio.getsampwidth(), 2)
                self.assertEqual(audio.readframes(audio.getnframes()), chunk)

            aligned_words = [
                {
                    "wordIndex": index,
                    "text": text,
                    "startMs": start_ms,
                    "endMs": end_ms,
                    "turnId": None,
                    "attribution": {"kind": "unknown"},
                    "confidence": None,
                }
                for index, (text, start_ms, end_ms) in enumerate(
                    (
                        ("Phase", 0, 2),
                        ("five", 2, 4),
                        ("is", 4, 6),
                        ("connected.", 6, 10),
                    )
                )
            ]
            processor.future.set_result(
                {
                    "schemaVersion": 1,
                    "jobId": created["jobId"],
                    "model": {
                        "poolId": "cohere-batch",
                        "id": "CohereLabs/cohere-transcribe-03-2026",
                        "revision": "b1eacc2686a3d08ceaae5f24a88b1d519620bc09",
                    },
                    "audio": {
                        "sha256": worker_job.input_sha256,
                        "sampleRateHz": 16000,
                        "durationMs": 10,
                    },
                    "transcript": {
                        "text": "Phase five is connected.",
                        "language": "en",
                        "punctuation": True,
                    },
                    "alignment": {
                        "status": "available",
                        "reason": None,
                        "componentRevision": "cohere-attention-en-v1",
                        "alignedWords": aligned_words,
                    },
                }
            )

            self.assertEqual(service.get(created["jobId"])["status"], "complete")
            self.assertEqual(
                service.get_result(created["jobId"]),
                {
                    "sessionId": "s-batch-create",
                    "revision": 1,
                    "authority": "server_authoritative",
                    "createdAtUtc": "2026-07-14T21:03:00Z",
                    "captureManifestSha256": "a" * 64,
                    "previousResultSha256": None,
                    "status": "complete",
                    "language": {
                        "languageBcp47": "en-US",
                        "confidence": None,
                    },
                    "transcript": "Phase five is connected.",
                    "alignment": {
                        "status": "available",
                        "reason": None,
                        "componentRevision": "cohere-attention-en-v1",
                    },
                    "alignedWords": aligned_words,
                    "modelProvenance": [
                        {
                            "modelId": "CohereLabs/cohere-transcribe-03-2026",
                            "revision": "b1eacc2686a3d08ceaae5f24a88b1d519620bc09",
                            "calibrationRevision": "asr-not-applicable",
                        }
                    ],
                },
            )
            self.assertEqual(
                [
                    (stage["stage"], stage["attempt"], stage["state"])
                    for stage in service.get_stages(created["jobId"])["stages"]
                ],
                [
                    ("asr", 1, "succeeded"),
                    ("alignment", 1, "succeeded"),
                    ("result_publication", 1, "succeeded"),
                ],
            )

    def test_dynamic_worker_evidence_survives_authoritative_result_publication(self) -> None:
        class DynamicProcessor(_ControlledProcessor):
            def resolve_route(self, language_bcp47: str) -> AsrRouteDecision:
                if language_bcp47 != "und":
                    raise AssertionError("dynamic job lost the und catalog language")
                return AsrRouteDecision(
                    provider_id="nemotron",
                    pool_id="nemotron-batch",
                    execution_mode="dynamicBatch",
                    model_revision="d" * 40,
                    provider_language="auto",
                )

        with tempfile.TemporaryDirectory() as temporary:
            processor = DynamicProcessor()
            service = RecordingJobService(
                Path(temporary),
                processor=processor,
                supported_languages=("und",),
                now=lambda: "2026-07-17T21:03:00Z",
            )
            request = _create_request()
            request["languageDecision"] = {
                "mode": "dynamic",
                "languageBcp47": None,
                "disposition": "explicitDynamic",
            }
            request["metadata"]["localeHintBcp47"] = "und"
            request["metadata"]["preferredLanguagesBcp47"] = ["und"]
            created = service.create(request)
            chunk = bytes(320)
            plan = service.prepare_chunk_upload(
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
            )
            service.accept_chunk(plan, chunk)
            service.commit(
                created["jobId"],
                {
                    "captureManifest": request["captureManifest"],
                    "chunkCount": 1,
                },
            )
            worker_job = processor.jobs[0]
            self.assertEqual(worker_job.language, "und")
            self.assertEqual(worker_job.route.provider_language, "auto")
            self.assertIsNotNone(worker_job.utterance_plan_path)
            self.assertIsNotNone(worker_job.utterance_plan_sha256)
            assert worker_job.utterance_plan_path is not None
            self.assertTrue(worker_job.utterance_plan_path.is_file())
            asr_attempt = service._state.stage_attempts[created["jobId"]][0]
            self.assertNotEqual(
                asr_attempt["inputFingerprintSha256"],
                request["preprocessingEvidence"]["normalization"][
                    "outputPcmSha256"
                ],
            )
            segments = [
                {
                    "index": 0,
                    "sourceSpanIndex": 0,
                    "text": "hello",
                    "status": "detected",
                    "languageBcp47": "en-US",
                    "rawLanguageTag": "en-US",
                    "reason": None,
                },
                {
                    "index": 1,
                    "sourceSpanIndex": 0,
                    "text": "bonjour",
                    "status": "unknown",
                    "languageBcp47": None,
                    "rawLanguageTag": "el-GR",
                    "reason": "DISABLED_LANGUAGE_TAG",
                },
            ]
            processor.future.set_result(
                {
                    "schemaVersion": 1,
                    "jobId": created["jobId"],
                    "model": {
                        "poolId": "nemotron-batch",
                        "id": "nvidia/nemotron-3.5-asr-streaming-0.6b",
                        "revision": "d" * 40,
                    },
                    "audio": {
                        "sha256": worker_job.input_sha256,
                        "sampleRateHz": 16000,
                        "durationMs": 10,
                    },
                    "transcript": {
                        "text": "hello bonjour",
                        "language": "auto",
                        "punctuation": True,
                        "languageSegments": segments,
                        "languageSpanEvidence": build_server_language_span_evidence(
                            source_end_sample=160,
                            provider_id="nemotron",
                            pool_id="nemotron-batch",
                            model_id="nvidia/nemotron-3.5-asr-streaming-0.6b",
                            model_revision="d" * 40,
                            utterance_plan_sha256=worker_job.utterance_plan_sha256,
                            utterances=(
                                ServerUtteranceLanguageObservation(
                                    start_sample=0,
                                    end_sample=160,
                                    language_segments=segments,
                                ),
                            ),
                        ),
                    },
                }
            )

            result = service.get_result(created["jobId"])

        self.assertEqual(result["language"], {"languageBcp47": "und", "confidence": None})
        self.assertEqual(result["languageSegments"], segments)
        self.assertEqual(
            result["languageSpanEvidence"]["utterancePlanSha256"],
            worker_job.utterance_plan_sha256,
        )

    def test_silence_can_complete_with_an_empty_transcript(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            processor = _ControlledProcessor()
            service = RecordingJobService(
                Path(temporary),
                processor=processor,
                supported_languages=("en",),
                now=lambda: "2026-07-14T21:03:01Z",
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
            service.commit(
                created["jobId"],
                {"captureManifest": request["captureManifest"], "chunkCount": 1},
            )

            processor.future.set_result(
                {
                    "model": {
                        "id": "CohereLabs/cohere-transcribe-03-2026",
                        "revision": "b1eacc2686a3d08ceaae5f24a88b1d519620bc09",
                    },
                    "transcript": {"text": ""},
                }
            )

            self.assertEqual(service.get(created["jobId"])["status"], "complete")
            self.assertEqual(service.get_result(created["jobId"])["transcript"], "")

    def test_processing_intent_failure_prevents_worker_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            processor = _ControlledProcessor()
            service = RecordingJobService(
                Path(temporary),
                processor=processor,
                supported_languages=("en",),
                now=lambda: "2026-07-14T21:03:15Z",
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

            from yap_server.jobs import job_store as store_module

            original_publish_json = store_module.publish_json

            def fail_processing_state(path: Path, value: object) -> None:
                if (
                    path.name == "state.json"
                    and value["projection"]["status"] == "server_processing"
                ):
                    raise OSError("private processing state unavailable")
                original_publish_json(path, value)

            with patch.object(store_module, "publish_json", fail_processing_state):
                with self.assertRaises(OSError):
                    service.commit(
                        created["jobId"],
                        {
                            "captureManifest": request["captureManifest"],
                            "chunkCount": 1,
                        },
                    )

            self.assertEqual(processor.jobs, [])
            self.assertEqual(service.get(created["jobId"])["status"], "uploading")
            with self.assertRaises(JobServiceError) as unavailable:
                service.get_result(created["jobId"])
            self.assertEqual(unavailable.exception.code, "RESULT_NOT_READY")

    def test_worker_failure_becomes_retryable_job_failure_without_a_result(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            processor = _ControlledProcessor()
            service = RecordingJobService(
                Path(temporary),
                processor=processor,
                supported_languages=("en",),
                now=lambda: "2026-07-14T21:06:00Z",
            )
            request = _create_request()
            created = service.create(request)
            chunk = bytes(320)
            plan = service.prepare_chunk_upload(
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
            )
            service.accept_chunk(plan, chunk)
            service.commit(
                created["jobId"],
                {"captureManifest": request["captureManifest"], "chunkCount": 1},
            )

            processor.future.set_exception(RuntimeError("private worker details"))

            failed = service.get(created["jobId"])
            self.assertEqual(failed["status"], "failed")
            self.assertEqual(
                failed["error"],
                {
                    "code": "ASR_WORKER_FAILED",
                    "message": "The private ASR worker did not complete the job.",
                    "retryable": True,
                    "requestId": f"job-{created['jobId']}",
                },
            )
            with self.assertRaises(JobServiceError) as missing:
                service.get_result(created["jobId"])
            self.assertEqual(missing.exception.status, 409)
            self.assertEqual(missing.exception.code, "RESULT_NOT_READY")
            job_root = Path(temporary) / "jobs" / created["jobId"]
            retained_chunks = list((job_root / "chunks").iterdir())
            self.assertEqual(len(retained_chunks), 1)
            self.assertEqual(retained_chunks[0].read_bytes(), chunk)
            self.assertTrue((job_root / "input.wav").exists())
            stages = service.get_stages(created["jobId"])
            self.assertTrue(stages["historyComplete"])
            self.assertEqual(
                stages["stages"],
                [
                    {
                        "stage": "asr",
                        "attempt": 1,
                        "state": "failed",
                        "updatedAtUtc": "2026-07-14T21:06:00Z",
                        "retryable": True,
                        "reason": "ASR_WORKER_FAILED",
                    }
                ],
            )
            restarted = RecordingJobService(
                Path(temporary),
                processor=_Processor(),
                supported_languages=("en",),
                now=lambda: "2026-07-14T21:06:01Z",
            )
            self.assertEqual(restarted.get(created["jobId"]), failed)
            self.assertEqual(restarted.get_stages(created["jobId"]), stages)
            self.assertEqual(len(list((job_root / "chunks").iterdir())), 1)

    def test_provider_backpressure_remains_a_retryable_capacity_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            processor = _ControlledProcessor()
            service = RecordingJobService(
                Path(temporary),
                processor=processor,
                supported_languages=("en",),
                now=lambda: "2026-07-14T21:06:00Z",
            )
            request = _create_request()
            created = service.create(request)
            chunk = bytes(320)
            plan = service.prepare_chunk_upload(
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
            )
            service.accept_chunk(plan, chunk)
            service.commit(
                created["jobId"],
                {"captureManifest": request["captureManifest"], "chunkCount": 1},
            )

            processor.future.set_exception(
                ProviderCapacityUnavailable("private provider details")
            )

            failed = service.get(created["jobId"])
            self.assertEqual(failed["status"], "failed")
            self.assertEqual(
                failed["error"],
                {
                    "code": "SERVER_BUSY",
                    "message": "Server capacity is temporarily unavailable.",
                    "retryable": True,
                    "requestId": f"job-{created['jobId']}",
                },
            )
            self.assertEqual(
                service.get_stages(created["jobId"])["stages"][0]["reason"],
                "SERVER_BUSY",
            )

    def test_commit_backpressure_is_retryable_without_losing_uploaded_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = RecordingJobService(
                Path(temporary),
                processor=_BusyProcessor(),
                supported_languages=("en",),
                now=lambda: "2026-07-14T21:11:00Z",
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

            with self.assertRaises(JobServiceError) as busy:
                service.commit(
                    created["jobId"],
                    {
                        "captureManifest": request["captureManifest"],
                        "chunkCount": 1,
                    },
                )

            self.assertEqual(busy.exception.status, 429)
            self.assertEqual(busy.exception.code, "SERVER_BUSY")
            self.assertTrue(busy.exception.retryable)
            self.assertEqual(service.get(created["jobId"])["status"], "uploading")

    def test_failed_asr_stage_retries_exact_capture_with_optimistic_revision(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            processor = _ControlledProcessor()
            service = RecordingJobService(
                Path(temporary),
                processor=processor,
                supported_languages=("en",),
                now=lambda: "2026-07-14T21:12:00Z",
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
            service.commit(
                created["jobId"],
                {"captureManifest": request["captureManifest"], "chunkCount": 1},
            )
            processor.future.set_exception(RuntimeError("first attempt failed"))
            failed_stages = service.get_stages(created["jobId"])
            retry_request = {
                "stage": "asr",
                "attempt": 1,
                "projectionRevision": failed_stages["projectionRevision"],
                "captureManifestSha256": request["captureManifest"]["sha256"],
            }

            stale_request = dict(retry_request)
            stale_request["projectionRevision"] -= 1
            with self.assertRaises(JobServiceError) as stale:
                service.retry_stage(created["jobId"], "asr", stale_request)
            self.assertEqual(stale.exception.code, "STAGE_PROJECTION_STALE")

            processor.future = Future()
            retried = service.retry_stage(created["jobId"], "asr", retry_request)
            self.assertEqual(
                (retried["stages"][0]["attempt"], retried["stages"][0]["state"]),
                (2, "running"),
            )
            self.assertEqual(len(processor.jobs), 2)
            retry_job = processor.jobs[-1]
            processor.future.set_result(
                {
                    "model": {
                        "id": "CohereLabs/cohere-transcribe-03-2026",
                        "revision": "b1eacc2686a3d08ceaae5f24a88b1d519620bc09",
                    },
                    "transcript": {"text": "Retry used the retained capture."},
                }
            )

            self.assertEqual(service.get(created["jobId"])["status"], "complete")
            self.assertEqual(retry_job.input_path.read_bytes(), processor.jobs[0].input_path.read_bytes())
            self.assertEqual(
                [
                    (stage["stage"], stage["attempt"], stage["state"])
                    for stage in service.get_stages(created["jobId"])["stages"]
                ],
                [
                    ("asr", 2, "succeeded"),
                    ("alignment", 1, "unavailable"),
                    ("result_publication", 1, "succeeded"),
                ],
            )

    def test_invalid_worker_result_becomes_a_safe_retryable_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            processor = _ControlledProcessor()
            service = RecordingJobService(
                Path(temporary),
                processor=processor,
                supported_languages=("en",),
                now=lambda: "2026-07-14T21:14:00Z",
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
            service.commit(
                created["jobId"],
                {"captureManifest": request["captureManifest"], "chunkCount": 1},
            )
            processor.future.set_result({"transcript": {"text": "missing model"}})

            failed = service.get(created["jobId"])
            self.assertEqual(failed["status"], "failed")
            self.assertEqual(failed["error"]["code"], "ASR_RESULT_INVALID")
            self.assertTrue(failed["error"]["retryable"])
