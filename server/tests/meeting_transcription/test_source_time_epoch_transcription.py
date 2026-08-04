from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import wave

from yap_server.meeting_transcription.source_time_epoch_transcription import (
    transcribe_source_time_epochs,
)
from yap_server.pools import pcm_audio


class _FakeTironEngine:
    def __init__(self, rosters: Sequence[tuple[str, ...]]) -> None:
        self._rosters = iter(rosters)
        self.calls: list[tuple[Path, str, int, bool, int]] = []

    def transcribe(
        self,
        audio: str,
        *,
        language: str,
        max_speakers: int,
        two_pass: bool,
    ) -> dict[str, object]:
        path = Path(audio)
        with wave.open(str(path), "rb") as source:
            frames = source.getnframes()
            duration = frames / source.getframerate()
        roster = next(self._rosters)
        segment_frames = max(1, frames // len(roster)) if roster else 0
        segments = []
        for index, speaker in enumerate(roster):
            start_frame = index * segment_frames
            end_frame = (
                frames if index + 1 == len(roster) else (index + 1) * segment_frames
            )
            segments.append(
                {
                    "speaker": speaker,
                    "start": start_frame / 16_000,
                    "end": end_frame / 16_000,
                    "text": f"epoch {len(self.calls)} speaker {index}",
                }
            )
        self.calls.append((path, language, max_speakers, two_pass, frames))
        return {
            "duration": duration,
            "elapsed_s": 0.1,
            "language": language,
            "num_chunks": 1,
            "segments": segments,
            "speakers": list(roster),
            "two_pass": {"engaged": True},
        }


class _QueuedEmbeddingEncoder:
    def __init__(self, embeddings: Sequence[tuple[float, ...]]) -> None:
        self._embeddings = iter(embeddings)
        self.input_sizes: list[int] = []

    def encode_pcm16(self, pcm_bytes: bytes) -> tuple[float, ...]:
        self.input_sizes.append(len(pcm_bytes))
        return next(self._embeddings)


def _write_wav(path: Path, seconds: int) -> pcm_audio.PcmAudio:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16_000)
        output.writeframes(b"\x01\x00" * 16_000 * seconds)
    return pcm_audio.read_pcm16_wav(path, max_audio_seconds=10_800)


class SourceTimeEpochTranscriptionTests(unittest.TestCase):
    def test_accepts_a_silent_epoch_without_inventing_a_speaker(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source_path = Path(temporary) / "silence.wav"
            audio = _write_wav(source_path, 1)
            engine = _FakeTironEngine(((),))
            encoder = _QueuedEmbeddingEncoder(())

            result = transcribe_source_time_epochs(
                audio=audio,
                engine=engine,
                language="en",
                speaker_encoder=encoder,
            )

            self.assertEqual(result.session_speaker_ids, ())
            self.assertEqual(result.turns, ())
            self.assertEqual(result.num_decode_windows, 1)
            self.assertEqual(encoder.input_sizes, [])

    def test_short_clean_speech_remains_unknown_without_running_ecapa(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source_path = Path(temporary) / "short.wav"
            audio = _write_wav(source_path, 1)
            engine = _FakeTironEngine((("SPEAKER_00",),))
            encoder = _QueuedEmbeddingEncoder(())

            result = transcribe_source_time_epochs(
                audio=audio,
                engine=engine,
                language="en",
                speaker_encoder=encoder,
            )

            self.assertEqual(result.session_speaker_ids, ())
            self.assertIsNone(result.turns[0].session_speaker_id)
            self.assertEqual(encoder.input_sizes, [])

    def test_reconciles_three_source_epochs_and_removes_temporary_audio(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source_path = Path(temporary) / "meeting.wav"
            audio = _write_wav(source_path, 65)
            engine = _FakeTironEngine(
                (("SPEAKER_00",), ("SPEAKER_00",), ("SPEAKER_00",))
            )
            encoder = _QueuedEmbeddingEncoder(((1.0, 0.0), (0.0, 1.0), (0.99, 0.01)))

            result = transcribe_source_time_epochs(
                audio=audio,
                engine=engine,
                language="en",
                speaker_encoder=encoder,
            )

            self.assertEqual(
                [call[4] for call in engine.calls], [480_000, 480_000, 80_000]
            )
            self.assertTrue(all(call[1:4] == ("en", 8, True) for call in engine.calls))
            self.assertTrue(all(not call[0].exists() for call in engine.calls))
            self.assertEqual(result.session_speaker_ids, ("speaker-1", "speaker-2"))
            self.assertEqual(
                [turn.session_speaker_id for turn in result.turns],
                ["speaker-1", "speaker-2", "speaker-1"],
            )
            self.assertEqual(
                [(turn.start_sample, turn.end_sample) for turn in result.turns],
                [(0, 480_000), (480_000, 960_000), (960_000, 1_040_000)],
            )
            self.assertEqual(result.num_decode_windows, 3)
            self.assertIsNone(result.capacity_degradation)
            self.assertEqual(encoder.input_sizes, [960_000, 960_000, 160_000])

    def test_reports_the_first_exactly_saturated_decode_epoch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source_path = Path(temporary) / "meeting.wav"
            audio = _write_wav(source_path, 30)
            roster = tuple(f"SPEAKER_{index:02d}" for index in range(8))
            engine = _FakeTironEngine((roster,))
            encoder = _QueuedEmbeddingEncoder(
                tuple(
                    tuple(1.0 if column == row else 0.0 for column in range(8))
                    for row in range(8)
                )
            )

            result = transcribe_source_time_epochs(
                audio=audio,
                engine=engine,
                language="en",
                speaker_encoder=encoder,
            )

            self.assertEqual(len(result.session_speaker_ids), 8)
            self.assertIsNotNone(result.capacity_degradation)
            assert result.capacity_degradation is not None
            self.assertEqual(result.capacity_degradation.scope, "decode_window")
            self.assertEqual(result.capacity_degradation.start_sample, 0)
            self.assertEqual(result.capacity_degradation.end_sample, 480_000)
            self.assertEqual(result.capacity_degradation.speaker_limit, 8)

    def test_bounds_the_composed_result_across_epochs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source_path = Path(temporary) / "meeting.wav"
            audio = _write_wav(source_path, 1)
            engine = _FakeTironEngine((("SPEAKER_00", "SPEAKER_01"),))
            encoder = _QueuedEmbeddingEncoder(((1.0, 0.0), (0.0, 1.0)))

            with patch(
                "yap_server.meeting_transcription.source_time_epoch_transcription.MAX_MEETING_SEGMENT_COUNT",
                1,
            ):
                with self.assertRaisesRegex(
                    ValueError, "meeting turns exceed the bounded contract"
                ):
                    transcribe_source_time_epochs(
                        audio=audio,
                        engine=engine,
                        language="en",
                        speaker_encoder=encoder,
                    )


if __name__ == "__main__":
    unittest.main()
