from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
import unittest

from yap_server.meeting_transcription.runtime_provenance import (
    load_meeting_runtime_provenance,
)
from yap_server.meeting_transcription.result_revisions import (
    MeetingResultContext,
    build_meeting_result_revisions,
    load_meeting_result_authority,
    speaker_result_sha256,
    validate_speaker_result_revision,
)


SERVER_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_LOCK = SERVER_ROOT / "meeting-transcription-runtime.lock.json"
RUNTIME_LOCK_SHA256 = hashlib.sha256(RUNTIME_LOCK.read_bytes()).hexdigest()
PROVENANCE = load_meeting_runtime_provenance(RUNTIME_LOCK)
AUTHORITY = load_meeting_result_authority(RUNTIME_LOCK)


def _worker_result() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "jobId": "job-1",
        "captureManifestSha256": "a" * 64,
        "model": {
            "id": PROVENANCE.model.identifier,
            "revision": PROVENANCE.model.revision,
            "runtimeHarnessRevision": PROVENANCE.harness.revision,
            "speakerEncoderRevision": PROVENANCE.speaker_encoder.revision,
            "runtimeLockSha256": RUNTIME_LOCK_SHA256,
        },
        "audio": {
            "sha256": "b" * 64,
            "durationMs": 2_000,
            "sampleRateHz": 16_000,
            "frameCount": 32_000,
        },
        "meeting": {
            "language": "en",
            "speakers": ["SPEAKER_00", "SPEAKER_01"],
            "segments": [
                {
                    "index": 0,
                    "speaker": "SPEAKER_00",
                    "startSample": 0,
                    "endSample": 16_000,
                    "text": "hello there",
                },
                {
                    "index": 1,
                    "speaker": "SPEAKER_01",
                    "startSample": 8_000,
                    "endSample": 24_000,
                    "text": "overlapping reply",
                },
                {
                    "index": 2,
                    "speaker": "SPEAKER_00",
                    "startSample": 24_000,
                    "endSample": 32_000,
                    "text": "final words",
                },
            ],
            "numWindows": 1,
            "sourceTimeUnit": "samples",
        },
        "runtime": {
            "device": "cuda:0",
            "dtype": "bfloat16",
            "constrainedDecoding": True,
            "twoPass": True,
        },
    }


def _context() -> MeetingResultContext:
    return MeetingResultContext(
        job_id="job-1",
        session_id="session-1",
        created_at_utc="2026-08-03T02:00:00.000Z",
        capture_manifest_sha256="a" * 64,
        language_bcp47="en-US",
        provider_language="en",
        source_track_ids=("track-1",),
        maximum_end_ms=2_000,
        source_frame_count=32_000,
    )


class MeetingResultRevisionTests(unittest.TestCase):
    def test_splits_joint_output_into_separate_transcript_and_speaker_revisions(
        self,
    ) -> None:
        transcript, speaker = build_meeting_result_revisions(
            _worker_result(),
            context=_context(),
            authority=AUTHORITY,
        )

        self.assertEqual(
            transcript["transcript"],
            "hello there overlapping reply final words",
        )
        self.assertEqual(transcript["captureManifestSha256"], "a" * 64)
        self.assertEqual(len(transcript["speakerResultSha256"]), 64)
        self.assertNotIn("speakerTurns", transcript)
        self.assertEqual(speaker["captureManifestSha256"], "a" * 64)
        self.assertNotIn("transcript", speaker)
        self.assertEqual(speaker["runtimeLockSha256"], RUNTIME_LOCK_SHA256)
        self.assertEqual(transcript["status"], "complete")
        self.assertEqual(speaker["status"], "complete")
        self.assertIsNone(speaker["speakerCapacityDegradation"])
        self.assertEqual(
            [turn["attribution"] for turn in speaker["speakerTurns"]],
            [
                {"kind": "session_speaker", "sessionSpeakerId": "speaker-1"},
                {"kind": "session_speaker", "sessionSpeakerId": "speaker-2"},
                {"kind": "session_speaker", "sessionSpeakerId": "speaker-1"},
            ],
        )
        self.assertEqual(
            [turn["text"] for turn in speaker["speakerTurns"]],
            ["hello there", "overlapping reply", "final words"],
        )
        self.assertEqual(
            [turn["overlapGroupId"] for turn in speaker["speakerTurns"]],
            ["overlap-000001", "overlap-000001", None],
        )
        self.assertNotIn("SPEAKER_00", str(speaker))
        validate_speaker_result_revision(
            speaker,
            transcript_result=transcript,
            context=_context(),
            authority=AUTHORITY,
        )

    def test_eight_observed_speakers_publish_a_typed_partial_result(self) -> None:
        worker = _worker_result()
        speakers = [f"SPEAKER_{index:02d}" for index in range(8)]
        worker["meeting"] = {
            "language": "en",
            "speakers": speakers,
            "segments": [
                {
                    "index": index,
                    "speaker": speaker,
                    "startSample": index * 4_000,
                    "endSample": (index + 1) * 4_000,
                    "text": f"speaker {index + 1}",
                }
                for index, speaker in enumerate(speakers)
            ],
            "numWindows": 1,
            "sourceTimeUnit": "samples",
        }

        transcript, speaker = build_meeting_result_revisions(
            worker,
            context=_context(),
            authority=AUTHORITY,
        )

        self.assertEqual(transcript["status"], "partial")
        self.assertEqual(speaker["status"], "partial")
        self.assertEqual(
            speaker["speakerCapacityDegradation"],
            {
                "code": "SPEAKER_CAPACITY_REACHED",
                "fallbackDisposition": "not_run_recommended",
                "scope": "meeting",
                "startSample": 0,
                "endSample": 32_000,
                "observedSpeakerCount": 8,
                "speakerLimit": 8,
            },
        )
        validate_speaker_result_revision(
            speaker,
            transcript_result=transcript,
            context=_context(),
            authority=AUTHORITY,
        )

        missing_degradation = deepcopy(speaker)
        missing_degradation["status"] = "complete"
        missing_degradation["speakerCapacityDegradation"] = None
        matching_complete_transcript = deepcopy(transcript)
        matching_complete_transcript["status"] = "complete"
        matching_complete_transcript["speakerResultSha256"] = speaker_result_sha256(
            missing_degradation
        )
        with self.assertRaisesRegex(ValueError, "differs from the roster"):
            validate_speaker_result_revision(
                missing_degradation,
                transcript_result=matching_complete_transcript,
                context=_context(),
                authority=AUTHORITY,
            )

        complete_transcript, two_speaker_result = build_meeting_result_revisions(
            _worker_result(),
            context=_context(),
            authority=AUTHORITY,
        )
        spurious_degradation = deepcopy(two_speaker_result)
        spurious_degradation["status"] = "partial"
        spurious_degradation["speakerCapacityDegradation"] = deepcopy(
            speaker["speakerCapacityDegradation"]
        )
        matching_partial_transcript = deepcopy(complete_transcript)
        matching_partial_transcript["status"] = "partial"
        matching_partial_transcript["speakerResultSha256"] = speaker_result_sha256(
            spurious_degradation
        )
        with self.assertRaisesRegex(ValueError, "differs from the roster"):
            validate_speaker_result_revision(
                spurious_degradation,
                transcript_result=matching_partial_transcript,
                context=_context(),
                authority=AUTHORITY,
            )

    def test_rejects_forged_identity_bounds_or_named_attribution(self) -> None:
        transcript, baseline = build_meeting_result_revisions(
            _worker_result(),
            context=_context(),
            authority=AUTHORITY,
        )
        cases = {
            "capture": ("captureManifestSha256", "f" * 64),
            "runtime": ("runtimeLockSha256", "f" * 64),
            "bounds": (
                "speakerTurns",
                [
                    {
                        **baseline["speakerTurns"][0],
                        "endMs": 2_001,
                    }
                ],
            ),
            "named": (
                "speakerTurns",
                [
                    {
                        **baseline["speakerTurns"][0],
                        "attribution": {
                            "kind": "named",
                            "identityRef": "someone",
                            "displayName": "Someone",
                            "profileRevision": "revision-1",
                        },
                    }
                ],
            ),
        }
        for label, (field, value) in cases.items():
            with self.subTest(label):
                forged = deepcopy(baseline)
                forged[field] = value
                with self.assertRaises(ValueError):
                    validate_speaker_result_revision(
                        forged,
                        transcript_result=transcript,
                        context=_context(),
                        authority=AUTHORITY,
                    )

    def test_rejects_turn_text_that_does_not_reconstruct_the_transcript(self) -> None:
        transcript, speaker = build_meeting_result_revisions(
            _worker_result(),
            context=_context(),
            authority=AUTHORITY,
        )
        forged = deepcopy(speaker)
        forged["speakerTurns"][0]["text"] = "different words"

        with self.assertRaisesRegex(ValueError, "companion identity|differs"):
            validate_speaker_result_revision(
                forged,
                transcript_result=transcript,
                context=_context(),
                authority=AUTHORITY,
            )


if __name__ == "__main__":
    unittest.main()
