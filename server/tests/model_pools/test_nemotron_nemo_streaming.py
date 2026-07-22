from __future__ import annotations

import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from yap_server.pools.batch_asr_worker import PcmAudio, WorkerInputError, transcribe
from yap_server.pools.nemotron_nemo_streaming import parse_nemo_transcript
from yap_server.pools.utterance_plan import UtterancePlan, build_utterance_plan


class NemoTranscriptMetadataTests(unittest.TestCase):
    def test_fixed_language_tags_are_validated_and_removed_from_spoken_text(self) -> None:
        transcript, segments = parse_nemo_transcript(
            "First sentence. <en-US> Second sentence. <en-US>",
            requested_language="en-US",
            prompt_locales=("auto", "en-US", "fr-FR"),
            enabled_locales=("en-US", "fr-FR"),
        )

        self.assertEqual(transcript, "First sentence. Second sentence.")
        self.assertIsNone(segments)

    def test_fixed_language_route_strips_known_metadata_without_overriding_route(
        self,
    ) -> None:
        transcript, segments = parse_nemo_transcript(
            "Hello. <en-US> Bonjour. <fr-FR>",
            requested_language="en-US",
            prompt_locales=("auto", "en-US", "fr-FR"),
            enabled_locales=("en-US", "fr-FR"),
        )

        self.assertEqual(transcript, "Hello. Bonjour.")
        self.assertIsNone(segments)

    def test_automatic_tags_become_ordered_language_evidence(self) -> None:
        transcript, segments = parse_nemo_transcript(
            "Hello. <en-US> Bonjour. <fr-FR>",
            requested_language="auto",
            prompt_locales=("auto", "en-US", "fr-FR"),
            enabled_locales=("en-US", "fr-FR"),
        )

        self.assertEqual(transcript, "Hello. Bonjour.")
        self.assertEqual(
            segments,
            [
                {
                    "index": 0,
                    "text": "Hello.",
                    "status": "detected",
                    "languageBcp47": "en-US",
                    "rawLanguageTag": "en-US",
                    "reason": None,
                },
                {
                    "index": 1,
                    "text": "Bonjour.",
                    "status": "detected",
                    "languageBcp47": "fr-FR",
                    "rawLanguageTag": "fr-FR",
                    "reason": None,
                },
            ],
        )

    def test_disabled_and_missing_automatic_tags_remain_unknown(self) -> None:
        transcript, segments = parse_nemo_transcript(
            "Adapted. <el-GR> trailing words",
            requested_language="auto",
            prompt_locales=("auto", "en-US", "el-GR"),
            enabled_locales=("en-US",),
        )

        self.assertEqual(transcript, "Adapted. trailing words")
        assert segments is not None
        self.assertEqual(segments[0]["status"], "unknown")
        self.assertEqual(segments[0]["rawLanguageTag"], "el-GR")
        self.assertEqual(segments[0]["reason"], "DISABLED_LANGUAGE_TAG")
        self.assertEqual(segments[1]["status"], "unknown")
        self.assertEqual(segments[1]["rawLanguageTag"], None)
        self.assertEqual(segments[1]["reason"], "MISSING_LANGUAGE_TAG")

    def test_unknown_metadata_like_tag_fails_closed(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "outside the prompt catalog"):
            parse_nemo_transcript(
                "Hello. <zz-ZZ>",
                requested_language="auto",
                prompt_locales=("auto", "en-US"),
                enabled_locales=("en-US",),
            )


class NemoWorkerDispatchTests(unittest.TestCase):
    def test_nemo_lock_selects_the_native_engine(self) -> None:
        audio, plan = _one_sample_input()
        lock = SimpleNamespace(
            pool_id="nemotron-batch",
            engine="nemo",
            supported_languages=("auto", "en-US"),
        )
        expected = {"schemaVersion": 1, "jobId": "job-1"}

        with patch(
            "yap_server.pools.nemotron_nemo_streaming.NemotronNemoStreamingEngine"
        ) as engine_type:
            engine_type.return_value.transcribe_recording.return_value = expected
            result = transcribe(
                job_id="job-1",
                model_dir=SimpleNamespace(),  # type: ignore[arg-type]
                lock=lock,  # type: ignore[arg-type]
                audio=audio,
                language="en-US",
                punctuation=True,
                utterance_plan=plan,
            )

        self.assertEqual(result, expected)
        engine_type.assert_called_once()
        engine_type.return_value.transcribe_recording.assert_called_once()

    def test_native_engine_diagnostics_cannot_contaminate_result_stdout(self) -> None:
        audio, plan = _one_sample_input()
        lock = SimpleNamespace(
            pool_id="nemotron-batch",
            engine="nemo",
            supported_languages=("auto", "en-US"),
        )
        expected = {"schemaVersion": 1, "jobId": "job-1"}
        captured_stdout = StringIO()
        captured_stderr = StringIO()

        with patch(
            "yap_server.pools.nemotron_nemo_streaming.NemotronNemoStreamingEngine"
        ) as engine_type:
            def noisy_transcription(
                *_args: object,
                **_kwargs: object,
            ) -> dict[str, object]:
                print("third-party diagnostic")
                return expected

            engine_type.return_value.transcribe_recording.side_effect = (
                noisy_transcription
            )
            with redirect_stdout(captured_stdout), redirect_stderr(captured_stderr):
                result = transcribe(
                    job_id="job-1",
                    model_dir=SimpleNamespace(),  # type: ignore[arg-type]
                    lock=lock,  # type: ignore[arg-type]
                    audio=audio,
                    language="en-US",
                    punctuation=True,
                    utterance_plan=plan,
                )

        self.assertEqual(result, expected)
        self.assertEqual(captured_stdout.getvalue(), "")
        self.assertIn("third-party diagnostic", captured_stderr.getvalue())

    def test_unknown_nemotron_engine_fails_closed(self) -> None:
        audio, plan = _one_sample_input()
        lock = SimpleNamespace(pool_id="nemotron-batch", engine="unknown")

        with self.assertRaisesRegex(WorkerInputError, "unsupported engine"):
            transcribe(
                job_id="job-1",
                model_dir=SimpleNamespace(),  # type: ignore[arg-type]
                lock=lock,  # type: ignore[arg-type]
                audio=audio,
                language="en-US",
                punctuation=True,
                utterance_plan=plan,
            )


def _one_sample_input() -> tuple[PcmAudio, UtterancePlan]:
    audio = PcmAudio(
        pcm_bytes=b"\0\0",
        sample_rate=16_000,
        frame_count=1,
        duration_ms=1,
        sha256="a" * 64,
    )
    plan = build_utterance_plan(
        input_wav_sha256=audio.sha256,
        input_sample_count=1,
        source_sample_count=1,
        vad_status="error",
        vad_evidence_sha256="b" * 64,
        vad_intervals=(),
    )
    return audio, plan


if __name__ == "__main__":
    unittest.main()
