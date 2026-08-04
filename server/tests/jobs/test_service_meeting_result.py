from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from yap_server.auth import PrincipalKey
from yap_server.jobs import JobServiceError, RecordingJobService
from yap_server.jobs.result_bundle import ResultBundleAdapterRegistry
from yap_server.meeting_transcription.contract import (
    MAX_MEETING_PCM_BYTES,
    MEETING_TRANSCRIPTION_POOL_ID,
)
from yap_server.meeting_transcription.result_revisions import (
    load_meeting_result_authority,
)
from yap_server.meeting_transcription.result_bundle_adapter import (
    MeetingResultBundleAdapter,
)
from yap_server.pools.batch_contract import AsrRouteDecision

from .service_fixtures import _ControlledProcessor, _create_request


SERVER_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_LOCK = SERVER_ROOT / "meeting-transcription-runtime.lock.json"
AUTHORITY = load_meeting_result_authority(RUNTIME_LOCK)
RESULT_BUNDLE_ADAPTERS = ResultBundleAdapterRegistry(
    {MEETING_TRANSCRIPTION_POOL_ID: MeetingResultBundleAdapter(AUTHORITY)}
)
ROUTE_PCM_BYTE_LIMITS = {
    MEETING_TRANSCRIPTION_POOL_ID: MAX_MEETING_PCM_BYTES,
}
ALICE = PrincipalKey(
    tenant_id="11111111-1111-4111-8111-111111111111",
    subject_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
)
BOB = PrincipalKey(
    tenant_id=ALICE.tenant_id,
    subject_id="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
)


class _MeetingProcessor(_ControlledProcessor):
    def resolve_route(self, language_bcp47: str) -> AsrRouteDecision:
        if language_bcp47 != "en-US":
            raise AssertionError("meeting route received the wrong catalog language")
        return AsrRouteDecision(
            provider_id="tiron",
            pool_id=MEETING_TRANSCRIPTION_POOL_ID,
            execution_mode="fixedBatch",
            model_revision=AUTHORITY.provenance.model.revision,
            provider_language="en",
        )


def _request_with_pcm_bytes(total_bytes: int, *, session_id: str) -> dict[str, object]:
    if total_bytes % 32 != 0:
        raise ValueError("test PCM length must resolve to whole milliseconds")
    request = _create_request(session_id=session_id)
    chunks: list[dict[str, object]] = []
    remaining = total_bytes
    sequence_start = 0
    start_ms = 0
    index = 0
    while remaining:
        byte_length = min(1024 * 1024, remaining)
        frame_count = byte_length // 2
        duration_ms = byte_length * 1000 // (16_000 * 2)
        chunks.append(
            {
                "replayKey": {
                    "schemaVersion": 1,
                    "sessionId": session_id,
                    "trackId": "track-1",
                    "sequenceStart": sequence_start,
                    "sequenceEnd": sequence_start + frame_count - 1,
                },
                "contentIdentity": {
                    "sha256": hashlib.sha256(f"chunk-{index}".encode()).hexdigest(),
                    "byteLength": byte_length,
                },
                "audioCodec": "pcm_s16le",
                "sampleRateHz": 16_000,
                "channels": 1,
                "startMs": start_ms,
                "durationMs": duration_ms,
            }
        )
        sequence_start += frame_count
        start_ms += duration_ms
        remaining -= byte_length
        index += 1
    request["chunks"] = chunks
    sample_count = total_bytes // 2
    normalization = request["preprocessingEvidence"]["normalization"]
    normalization["sourceSampleCount"] = sample_count
    normalization["outputSampleCount"] = sample_count
    request["preprocessingEvidence"]["vad"]["sourceSampleCount"] = sample_count
    return request


class RecordingJobMeetingResultTests(unittest.TestCase):
    def test_joint_worker_publishes_restart_safe_partial_revisions_and_cancel_purges_them(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            processor = _MeetingProcessor()
            service = RecordingJobService(
                root,
                processor=processor,
                supported_languages=("en-US",),
                now=lambda: "2026-08-03T03:00:00Z",
                result_bundle_adapters=RESULT_BUNDLE_ADAPTERS,
                route_pcm_byte_limits=ROUTE_PCM_BYTE_LIMITS,
                development_principal=None,
            )
            alice = service.for_principal(ALICE)
            request = _create_request()
            created = alice.create(request)
            chunk = bytes(320)
            alice.accept_chunk(
                alice.prepare_chunk_upload(
                    created["jobId"],
                    track_id="track-1",
                    sequence_start=0,
                    sequence_end=159,
                    idempotency_key="1/s-batch-create/track-1/0/159",
                    content_sha256=hashlib.sha256(chunk).hexdigest(),
                    audio_codec="pcm_s16le",
                    sample_rate_hz=16_000,
                    channels=1,
                    content_length=len(chunk),
                ),
                chunk,
            )
            alice.commit(
                created["jobId"],
                {
                    "captureManifest": request["captureManifest"],
                    "chunkCount": 1,
                },
            )
            worker_job = processor.jobs[0]
            speakers = [f"speaker-{index}" for index in range(1, 9)]
            processor.future.set_result(
                {
                    "schemaVersion": 1,
                    "jobId": created["jobId"],
                    "captureManifestSha256": "a" * 64,
                    "model": {
                        "id": AUTHORITY.provenance.model.identifier,
                        "revision": AUTHORITY.provenance.model.revision,
                        "runtimeHarnessRevision": AUTHORITY.provenance.harness.revision,
                        "speakerEncoderRevision": (
                            AUTHORITY.provenance.speaker_encoder.revision
                        ),
                        "applicationRevision": "e" * 40,
                        "runtimeLockSha256": AUTHORITY.runtime_lock_sha256,
                    },
                    "audio": {
                        "sha256": worker_job.input_sha256,
                        "durationMs": 10,
                        "sampleRateHz": 16_000,
                        "frameCount": 160,
                    },
                    "meeting": {
                        "language": "en",
                        "sessionSpeakerIds": speakers,
                        "turns": [
                            {
                                "index": index,
                                "sessionSpeakerId": speaker,
                                "startSample": index * 20,
                                "endSample": (index + 1) * 20,
                                "text": f"speaker {index + 1}",
                            }
                            for index, speaker in enumerate(speakers)
                        ],
                        "numDecodeWindows": 1,
                        "sourceTimeUnit": "samples",
                        "speakerCapacityDegradation": {
                            "code": "SPEAKER_CAPACITY_REACHED",
                            "scope": "decode_window",
                            "startSample": 0,
                            "endSample": 160,
                            "observedSpeakerCount": 8,
                            "speakerLimit": 8,
                        },
                    },
                    "runtime": {
                        "device": "cuda:0",
                        "dtype": "bfloat16",
                        "constrainedDecoding": True,
                        "twoPass": True,
                    },
                }
            )

            transcript = alice.get_result(created["jobId"])
            speaker = alice.get_speaker_result(created["jobId"])
            job_root = root / "jobs" / created["jobId"]
            self.assertEqual(
                transcript["transcript"],
                "speaker 1 speaker 2 speaker 3 speaker 4 "
                "speaker 5 speaker 6 speaker 7 speaker 8",
            )
            self.assertEqual(transcript["status"], "partial")
            self.assertEqual(speaker["status"], "partial")
            self.assertEqual(
                speaker["speakerCapacityDegradation"]["code"],
                "SPEAKER_CAPACITY_REACHED",
            )
            self.assertEqual(alice.get(created["jobId"])["status"], "partial")
            self.assertEqual(
                speaker["speakerTurns"][0]["attribution"],
                {"kind": "session_speaker", "sessionSpeakerId": "speaker-1"},
            )
            self.assertEqual(
                transcript["captureManifestSha256"],
                speaker["captureManifestSha256"],
            )
            self.assertTrue((job_root / "result-revision.json").is_file())
            self.assertTrue((job_root / "speaker-result-revision.json").is_file())
            with self.assertRaises(JobServiceError) as denied:
                service.for_principal(BOB).get_speaker_result(created["jobId"])
            self.assertEqual(
                (denied.exception.status, denied.exception.code),
                (404, "JOB_NOT_FOUND"),
            )

            restarted = RecordingJobService(
                root,
                # Historical result decoding is independent of the currently
                # selected worker profile.
                processor=_ControlledProcessor(),
                supported_languages=("en-US",),
                now=lambda: "2026-08-03T03:00:01Z",
                result_bundle_adapters=RESULT_BUNDLE_ADAPTERS,
                route_pcm_byte_limits=ROUTE_PCM_BYTE_LIMITS,
                development_principal=None,
            )
            restarted_alice = restarted.for_principal(ALICE)
            self.assertEqual(restarted_alice.get_result(created["jobId"]), transcript)
            self.assertEqual(
                restarted_alice.get_speaker_result(created["jobId"]),
                speaker,
            )

            next_authority = replace(
                AUTHORITY,
                provenance=replace(
                    AUTHORITY.provenance,
                    model=replace(
                        AUTHORITY.provenance.model,
                        revision="f" * 40,
                    ),
                ),
                runtime_lock_sha256="e" * 64,
            )
            next_adapters = ResultBundleAdapterRegistry(
                {
                    MEETING_TRANSCRIPTION_POOL_ID: MeetingResultBundleAdapter(
                        next_authority
                    )
                }
            )
            restarted_after_model_update = RecordingJobService(
                root,
                processor=_ControlledProcessor(),
                supported_languages=("en-US",),
                now=lambda: "2026-08-03T03:00:01Z",
                result_bundle_adapters=next_adapters,
                route_pcm_byte_limits=ROUTE_PCM_BYTE_LIMITS,
                development_principal=None,
            ).for_principal(ALICE)
            self.assertEqual(
                restarted_after_model_update.get_result(created["jobId"]),
                transcript,
            )
            self.assertEqual(
                restarted_after_model_update.get_speaker_result(created["jobId"]),
                speaker,
            )

            state_path = job_root / "state.json"
            state_bytes = state_path.read_bytes()
            persisted = json.loads(state_bytes)
            persisted["asrRouting"]["route"]["providerLanguage"] = "fr"
            state_path.write_text(json.dumps(persisted), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "route language"):
                RecordingJobService(
                    root,
                    processor=_ControlledProcessor(),
                    supported_languages=("en-US",),
                    now=lambda: "2026-08-03T03:00:01Z",
                    result_bundle_adapters=RESULT_BUNDLE_ADAPTERS,
                    route_pcm_byte_limits=ROUTE_PCM_BYTE_LIMITS,
                    development_principal=None,
                )
            state_path.write_bytes(state_bytes)

            persisted = json.loads(state_bytes)
            persisted["creation"]["metadata"]["localeHintBcp47"] = "en-GB"
            persisted["creation"]["metadata"]["preferredLanguagesBcp47"] = ["en-GB"]
            persisted["creation"]["languageDecision"]["languageBcp47"] = "en-GB"
            state_path.write_text(json.dumps(persisted), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "frozen job"):
                RecordingJobService(
                    root,
                    processor=_ControlledProcessor(),
                    supported_languages=("en-US",),
                    now=lambda: "2026-08-03T03:00:01Z",
                    result_bundle_adapters=RESULT_BUNDLE_ADAPTERS,
                    route_pcm_byte_limits=ROUTE_PCM_BYTE_LIMITS,
                    development_principal=None,
                )
            state_path.write_bytes(state_bytes)

            speaker_result_path = job_root / "speaker-result-revision.json"
            speaker_result_bytes = speaker_result_path.read_bytes()
            speaker_result_path.unlink()
            with self.assertRaisesRegex(ValueError, "aggregate is incomplete"):
                RecordingJobService(
                    root,
                    processor=_MeetingProcessor(),
                    supported_languages=("en-US",),
                    now=lambda: "2026-08-03T03:00:02Z",
                    result_bundle_adapters=RESULT_BUNDLE_ADAPTERS,
                    route_pcm_byte_limits=ROUTE_PCM_BYTE_LIMITS,
                    development_principal=None,
                )
            speaker_result_path.write_bytes(speaker_result_bytes)

            cancelled = restarted_alice.cancel(created["jobId"])
            self.assertEqual(cancelled["status"], "cancelled")
            self.assertFalse((job_root / "result-revision.json").exists())
            self.assertFalse(speaker_result_path.exists())
            for result_getter, expected_code in (
                (restarted_alice.get_result, "RESULT_NOT_READY"),
                (restarted_alice.get_speaker_result, "SPEAKER_RESULT_NOT_READY"),
            ):
                with self.assertRaises(JobServiceError) as unavailable:
                    result_getter(created["jobId"])
                self.assertEqual(unavailable.exception.code, expected_code)
                self.assertFalse(unavailable.exception.retryable)

            cancelled_restart = RecordingJobService(
                root,
                processor=_MeetingProcessor(),
                supported_languages=("en-US",),
                now=lambda: "2026-08-03T03:00:03Z",
                result_bundle_adapters=RESULT_BUNDLE_ADAPTERS,
                route_pcm_byte_limits=ROUTE_PCM_BYTE_LIMITS,
                development_principal=None,
                startup_worker_cleanup_verified=True,
            ).for_principal(ALICE)
            self.assertEqual(
                cancelled_restart.get(created["jobId"])["status"], "cancelled"
            )
            with self.assertRaises(JobServiceError) as unavailable_result:
                cancelled_restart.get_result(created["jobId"])
            self.assertFalse(unavailable_result.exception.retryable)
            with self.assertRaises(JobServiceError) as unavailable_speaker_result:
                cancelled_restart.get_speaker_result(created["jobId"])
            self.assertFalse(unavailable_speaker_result.exception.retryable)

    def test_restart_discards_speaker_only_terminal_publication_orphans(self) -> None:
        for terminal_status in ("failed", "cancelled"):
            with self.subTest(terminal_status=terminal_status):
                with tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    service = RecordingJobService(
                        root,
                        processor=_MeetingProcessor(),
                        supported_languages=("en-US",),
                        now=lambda: "2026-08-03T03:10:00Z",
                        result_bundle_adapters=RESULT_BUNDLE_ADAPTERS,
                        route_pcm_byte_limits=ROUTE_PCM_BYTE_LIMITS,
                        development_principal=None,
                    )
                    created = service.for_principal(ALICE).create(_create_request())
                    job_id = created["jobId"]
                    service.for_principal(ALICE).cancel(job_id)
                    job_root = root / "jobs" / job_id
                    state_path = job_root / "state.json"
                    state = json.loads(state_path.read_text(encoding="utf-8"))
                    state["cancellationRequested"] = False
                    state["projection"]["status"] = terminal_status
                    if terminal_status == "failed":
                        state["projection"]["error"] = {
                            "code": "ASR_RESULT_PUBLISH_FAILED",
                            "message": "The private ASR result could not be stored safely.",
                            "retryable": False,
                            "requestId": f"job-{job_id}",
                        }
                    else:
                        state["projection"].pop("error", None)
                    state_path.write_text(
                        json.dumps(state, separators=(",", ":")) + "\n",
                        encoding="utf-8",
                    )
                    orphan = job_root / "speaker-result-revision.json"
                    orphan.write_text("{}\n", encoding="utf-8")

                    restarted = RecordingJobService(
                        root,
                        processor=_MeetingProcessor(),
                        supported_languages=("en-US",),
                        now=lambda: "2026-08-03T03:10:01Z",
                        result_bundle_adapters=RESULT_BUNDLE_ADAPTERS,
                        route_pcm_byte_limits=ROUTE_PCM_BYTE_LIMITS,
                        development_principal=None,
                    )

                    self.assertEqual(
                        restarted.for_principal(ALICE).get(job_id)["status"],
                        terminal_status,
                    )
                    self.assertFalse(orphan.exists())

    def test_candidate_route_admits_three_hours_and_rejects_one_more_millisecond(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = RecordingJobService(
                Path(temporary),
                processor=_MeetingProcessor(),
                supported_languages=("en-US",),
                now=lambda: "2026-08-03T03:20:00Z",
                result_bundle_adapters=RESULT_BUNDLE_ADAPTERS,
                route_pcm_byte_limits=ROUTE_PCM_BYTE_LIMITS,
                development_principal=None,
            ).for_principal(ALICE)

            accepted = service.create(
                _request_with_pcm_bytes(
                    MAX_MEETING_PCM_BYTES,
                    session_id="meeting-three-hours",
                )
            )
            self.assertEqual(accepted["status"], "accepted")

            with self.assertRaises(JobServiceError) as rejected:
                service.create(
                    _request_with_pcm_bytes(
                        MAX_MEETING_PCM_BYTES + 32,
                        session_id="meeting-over-three-hours",
                    )
                )
            self.assertEqual(
                (rejected.exception.status, rejected.exception.code),
                (400, "INVALID_JOB"),
            )


if __name__ == "__main__":
    unittest.main()
