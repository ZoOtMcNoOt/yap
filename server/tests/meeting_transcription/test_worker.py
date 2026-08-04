from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest
import wave

from yap_server.meeting_transcription.runtime_provenance import (
    load_meeting_runtime_provenance,
)
from yap_server.meeting_transcription.worker import (
    MeetingWorkerRequest,
    transcribe_meeting,
)
from yap_server.pools import pcm_audio


SERVER_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_LOCK = SERVER_ROOT / "meeting-transcription-runtime.lock.json"
APPLICATION_REVISION = "e" * 40


class _FakeEngine:
    def __init__(self, result: dict[str, object]) -> None:
        self.result = result
        self.calls: list[tuple[str, str, int, bool]] = []

    def transcribe(
        self,
        audio: str,
        *,
        language: str,
        max_speakers: int,
        two_pass: bool,
    ) -> dict[str, object]:
        self.calls.append((audio, language, max_speakers, two_pass))
        return self.result


class _FakeSpeakerEncoder:
    def encode_pcm16(self, pcm_bytes: bytes) -> tuple[float, ...]:
        if not pcm_bytes:
            raise AssertionError("speaker evidence must not be empty")
        return (1.0, 0.0)


def _write_wav(path: Path, frames: int = 16_000) -> pcm_audio.PcmAudio:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16_000)
        output.writeframes(b"\0\0" * frames)
    return pcm_audio.read_pcm16_wav(path, max_audio_seconds=10_800)


class MeetingWorkerTests(unittest.TestCase):
    def test_publishes_only_validated_source_bound_upstream_results(self) -> None:
        provenance = load_meeting_runtime_provenance(RUNTIME_LOCK)
        with tempfile.TemporaryDirectory() as temporary:
            audio_path = Path(temporary) / "meeting.wav"
            audio = _write_wav(audio_path, frames=32_000)
            engine = _FakeEngine(
                {
                    "duration": 2.0,
                    "language": "en",
                    "speakers": ["SPEAKER_00"],
                    "segments": [
                        {
                            "speaker": "SPEAKER_00",
                            "start": 0.0,
                            "end": 1.7,
                            "text": "hello there",
                        }
                    ],
                    "num_chunks": 1,
                    "elapsed_s": 0.25,
                    "two_pass": {"mode": "single_pass", "engaged": False},
                }
            )
            request = MeetingWorkerRequest(
                job_id="meeting-1",
                input_sha256=audio.sha256,
                capture_manifest_sha256="a" * 64,
                language="en",
            )

            result = transcribe_meeting(
                request=request,
                audio=audio,
                runtime_lock_sha256=hashlib.sha256(
                    RUNTIME_LOCK.read_bytes()
                ).hexdigest(),
                application_revision=APPLICATION_REVISION,
                provenance=provenance,
                engine=engine,
                speaker_encoder=_FakeSpeakerEncoder(),
            )

            self.assertEqual(len(engine.calls), 1)
            self.assertEqual(engine.calls[0][1:], ("en", 8, True))
            self.assertFalse(Path(engine.calls[0][0]).exists())
            self.assertEqual(result["jobId"], "meeting-1")
            self.assertEqual(result["captureManifestSha256"], "a" * 64)
            self.assertEqual(
                result["model"]["applicationRevision"],  # type: ignore[index]
                APPLICATION_REVISION,
            )
            self.assertEqual(result["audio"]["sha256"], audio.sha256)  # type: ignore[index]
            meeting = result["meeting"]
            assert isinstance(meeting, dict)
            self.assertEqual(meeting["sessionSpeakerIds"], ["speaker-1"])
            self.assertEqual(
                meeting["turns"],
                [
                    {
                        "index": 0,
                        "sessionSpeakerId": "speaker-1",
                        "startSample": 0,
                        "endSample": 27_200,
                        "text": "hello there",
                    }
                ],
            )
            self.assertNotIn("elapsed_s", result)
            self.assertNotIn("two_pass", result)

    def test_rejects_upstream_segments_outside_the_canonical_source(self) -> None:
        provenance = load_meeting_runtime_provenance(RUNTIME_LOCK)
        with tempfile.TemporaryDirectory() as temporary:
            audio_path = Path(temporary) / "meeting.wav"
            audio = _write_wav(audio_path)
            engine = _FakeEngine(
                {
                    "duration": 1.0,
                    "language": "en",
                    "speakers": ["SPEAKER_00"],
                    "segments": [
                        {
                            "speaker": "SPEAKER_00",
                            "start": 0.9,
                            "end": 1.2,
                            "text": "outside",
                        }
                    ],
                    "num_chunks": 1,
                    "elapsed_s": 0.1,
                    "two_pass": None,
                }
            )
            request = MeetingWorkerRequest(
                job_id="meeting-1",
                input_sha256=audio.sha256,
                capture_manifest_sha256="b" * 64,
                language="en",
            )

            with self.assertRaisesRegex(ValueError, "source bounds"):
                transcribe_meeting(
                    request=request,
                    audio=audio,
                    runtime_lock_sha256=hashlib.sha256(
                        RUNTIME_LOCK.read_bytes()
                    ).hexdigest(),
                    application_revision=APPLICATION_REVISION,
                    provenance=provenance,
                    engine=engine,
                    speaker_encoder=_FakeSpeakerEncoder(),
                )

    def test_accepts_two_upstream_windows_inside_one_source_epoch(self) -> None:
        provenance = load_meeting_runtime_provenance(RUNTIME_LOCK)
        with tempfile.TemporaryDirectory() as temporary:
            audio_path = Path(temporary) / "snapped-meeting.wav"
            audio = _write_wav(audio_path, frames=30 * 16_000)
            engine = _FakeEngine(
                {
                    "duration": 30.0,
                    "language": "en",
                    "speakers": ["SPEAKER_00"],
                    "segments": [
                        {
                            "speaker": "SPEAKER_00",
                            "start": 0.0,
                            "end": 29.5,
                            "text": "two windows after right padding",
                        }
                    ],
                    "num_chunks": 2,
                    "elapsed_s": 1.0,
                    "two_pass": {"mode": "staggered", "engaged": True},
                }
            )
            request = MeetingWorkerRequest(
                job_id="meeting-snapped-windows",
                input_sha256=audio.sha256,
                capture_manifest_sha256="c" * 64,
                language="en",
            )

            result = transcribe_meeting(
                request=request,
                audio=audio,
                runtime_lock_sha256=hashlib.sha256(
                    RUNTIME_LOCK.read_bytes()
                ).hexdigest(),
                application_revision=APPLICATION_REVISION,
                provenance=provenance,
                engine=engine,
                speaker_encoder=_FakeSpeakerEncoder(),
            )

            self.assertEqual(result["meeting"]["numDecodeWindows"], 2)  # type: ignore[index]


if __name__ == "__main__":
    unittest.main()
