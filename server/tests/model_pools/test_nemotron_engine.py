from __future__ import annotations

from types import MethodType, SimpleNamespace
import unittest

from yap_server.pools.nemotron_engine import (
    MAX_NEMOTRON_LANGUAGE_SEGMENTS,
    NemotronAsrEngine,
    NemotronAsrInput,
    NemotronInferenceCancelled,
    NemotronUtteranceTranscript,
    language_tag_token_map,
    tagged_language_segments,
)
from yap_server.pools.pcm_audio import PcmAudio
from yap_server.pools.utterance_plan import (
    SAMPLE_RATE_HZ,
    build_utterance_plan,
    snapshot_utterance_plan,
)


class _Tokenizer:
    def __init__(self, added_vocab: object) -> None:
        self._added_vocab = added_vocab

    def get_added_vocab(self) -> object:
        return self._added_vocab


_WORDS = {
    1: "hello",
    2: "world",
    3: "bonjour",
    4: "encore",
}


def _decode(token_ids: list[int]) -> str:
    return " ".join(_WORDS[token_id] for token_id in token_ids if token_id in _WORDS)


class NemotronLanguageEvidenceTests(unittest.TestCase):
    def test_reads_only_canonical_language_tokens_from_added_vocabulary(self) -> None:
        tags = language_tag_token_map(
            _Tokenizer(
                {
                    "<blank>": 0,
                    "<pad>": 1,
                    "<unk>": 2,
                    "<en-US>": 100,
                    "<fr-FR>": 101,
                    "<sl-SL>": 102,
                    "ordinary": 103,
                }
            ),
            prompt_locales=("auto", "en", "en-US", "fr-FR", "sl", "enGB"),
        )

        self.assertEqual(tags, {100: "en-US", 101: "fr-FR", 102: "sl-SL"})

    def test_rejects_duplicate_language_token_ids(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "language tokens"):
            language_tag_token_map(
                _Tokenizer({"<en-US>": 100, "<fr-FR>": 100}),
                prompt_locales=("en-US", "fr-FR"),
            )

    def test_preserves_multiple_detected_tags_before_display_decode(self) -> None:
        transcript, segments = tagged_language_segments(
            [1, 100, 2, 101],
            tag_tokens={100: "en-US", 101: "fr-FR"},
            enabled_locales=("en-US", "fr-FR"),
            decode=_decode,
        )

        self.assertEqual(transcript, "hello world")
        self.assertEqual(
            segments,
            [
                {
                    "index": 0,
                    "text": "hello",
                    "status": "detected",
                    "languageBcp47": "en-US",
                    "rawLanguageTag": "en-US",
                    "reason": None,
                },
                {
                    "index": 1,
                    "text": "world",
                    "status": "detected",
                    "languageBcp47": "fr-FR",
                    "rawLanguageTag": "fr-FR",
                    "reason": None,
                },
            ],
        )

    def test_disabled_and_missing_tags_remain_unknown_without_primary_fallback(self) -> None:
        transcript, segments = tagged_language_segments(
            [3, 102, 4],
            tag_tokens={102: "el-GR"},
            enabled_locales=("en-US",),
            decode=_decode,
        )

        self.assertEqual(transcript, "bonjour encore")
        self.assertEqual(segments[0]["languageBcp47"], None)
        self.assertEqual(segments[0]["rawLanguageTag"], "el-GR")
        self.assertEqual(segments[0]["reason"], "DISABLED_LANGUAGE_TAG")
        self.assertEqual(segments[1]["languageBcp47"], None)
        self.assertEqual(segments[1]["rawLanguageTag"], None)
        self.assertEqual(segments[1]["reason"], "MISSING_LANGUAGE_TAG")

    def test_no_tag_and_empty_tagged_text_are_explicit_unknown_evidence(self) -> None:
        transcript, segments = tagged_language_segments(
            [1, 2],
            tag_tokens={100: "en-US"},
            enabled_locales=("en-US",),
            decode=_decode,
        )
        self.assertEqual(transcript, "hello world")
        self.assertEqual(segments[0]["reason"], "MISSING_LANGUAGE_TAG")

        transcript, segments = tagged_language_segments(
            [100],
            tag_tokens={100: "en-US"},
            enabled_locales=("en-US",),
            decode=_decode,
        )
        self.assertEqual(transcript, "")
        self.assertEqual(segments[0]["reason"], "EMPTY_TAGGED_TRANSCRIPT")
        self.assertEqual(segments[0]["rawLanguageTag"], "en-US")

    def test_language_segment_count_is_bounded(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "segment bound"):
            tagged_language_segments(
                [100] * (MAX_NEMOTRON_LANGUAGE_SEGMENTS + 1),
                tag_tokens={100: "en-US"},
                enabled_locales=("en-US",),
                decode=_decode,
            )

    def test_one_loaded_engine_aggregates_a_complete_bounded_recording(self) -> None:
        frame_count = 40 * SAMPLE_RATE_HZ
        audio = PcmAudio(
            pcm_bytes=bytes(frame_count * 2),
            sample_rate=SAMPLE_RATE_HZ,
            frame_count=frame_count,
            duration_ms=40_000,
            sha256="a" * 64,
        )
        plan = build_utterance_plan(
            input_wav_sha256=audio.sha256,
            input_sample_count=frame_count,
            source_sample_count=frame_count,
            vad_status="error",
            vad_evidence_sha256="b" * 64,
            vad_intervals=(),
        )
        engine = object.__new__(NemotronAsrEngine)
        engine._lock = SimpleNamespace(
            pool_id="nemotron-batch",
            model_id="nvidia/nemotron-3.5-asr-streaming-0.6b",
            model_revision="d" * 40,
            supported_languages=("auto", "en-US", "fr-FR"),
        )
        seen_frames: list[int] = []

        def infer(
            _engine: object,
            request: NemotronAsrInput,
            *,
            cancelled=None,
        ):
            seen_frames.append(request.audio.frame_count)
            language = "en-US" if len(seen_frames) == 1 else "fr-FR"
            text = "hello" if len(seen_frames) == 1 else "bonjour"
            return NemotronUtteranceTranscript(
                text=text,
                language_segments=[
                    {
                        "index": 0,
                        "text": text,
                        "status": "detected",
                        "languageBcp47": language,
                        "rawLanguageTag": language,
                        "reason": None,
                    }
                ],
                inference_ms=7,
                inference_passes=3,
                max_batch_size=2,
                queue_ms=1,
                total_ms=8,
            )

        def runtime(_engine: object, **values: int):
            return values

        engine._infer_utterance = MethodType(infer, engine)
        engine._runtime_payload = MethodType(runtime, engine)

        result = engine.transcribe_recording(
            NemotronAsrInput(
                job_id="job-dynamic",
                audio=audio,
                language="auto",
                punctuation=True,
            ),
            plan,
        )

        self.assertEqual(seen_frames, [30 * SAMPLE_RATE_HZ, 10 * SAMPLE_RATE_HZ])
        self.assertEqual(result["audio"]["sha256"], audio.sha256)
        self.assertEqual(result["transcript"]["text"], "hello bonjour")
        self.assertEqual(
            [segment["index"] for segment in result["transcript"]["languageSegments"]],
            [0, 1],
        )
        self.assertEqual(
            [
                segment["sourceSpanIndex"]
                for segment in result["transcript"]["languageSegments"]
            ],
            [0, 1],
        )
        span_evidence = result["transcript"]["languageSpanEvidence"]
        self.assertEqual(span_evidence["boundaryAuthority"], "serverUtterance")
        self.assertEqual(
            span_evidence["utterancePlanSha256"],
            snapshot_utterance_plan(plan).sha256,
        )
        self.assertEqual(
            [span["languageBcp47"] for span in span_evidence["spans"]],
            ["en-US", "fr-FR"],
        )
        self.assertEqual(span_evidence["sourceEndSample"], frame_count)
        self.assertEqual(
            result["runtime"],
            {
                "inference_ms": 14,
                "chunk_count": 2,
                "inference_passes": 6,
                "max_batch_size": 2,
                "queue_ms": 2,
                "total_ms": 16,
            },
        )

        seen_frames.clear()
        with self.assertRaises(NemotronInferenceCancelled):
            engine.transcribe_recording(
                NemotronAsrInput(
                    job_id="job-dynamic",
                    audio=audio,
                    language="auto",
                    punctuation=True,
                ),
                plan,
                cancelled=lambda: bool(seen_frames),
            )
        self.assertEqual(seen_frames, [30 * SAMPLE_RATE_HZ])


if __name__ == "__main__":
    unittest.main()
