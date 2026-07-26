from __future__ import annotations

import unittest
from unittest.mock import patch

from yap_server.alignment_contract import (
    ALIGNMENT_COMPONENT_REVISION,
    AlignedWordEvidence,
    AlignmentUnavailable,
    AlignmentUnavailableReason,
)
from yap_server.pools.batch_asr_worker import PcmAudio
from yap_server.pools.cohere_engine import (
    CohereAsrInput,
    _ChunkAlignment,
    _ChunkPlan,
    _GeneratedChunk,
    _alignment_token_metadata,
    _merge_chunk_alignments,
    _result_payload,
    _selected_teacher_inputs,
)

from .batch_asr_fixtures import AUDIO_SHA256, test_lock as _test_lock


class _Tokenizer:
    eos_token_id = 99

    def convert_ids_to_tokens(self, token_ids: list[int]) -> list[str]:
        pieces = {
            10: "<|prompt|>",
            11: "<|en|>",
            20: "▁hello",
            21: "▁world",
            99: "</s>",
            0: "<pad>",
        }
        return [pieces[token_id] for token_id in token_ids]


class _Processor:
    tokenizer = _Tokenizer()

    def decode(self, rows: list[list[int]], **kwargs: object) -> list[str]:
        self.rows = rows
        self.kwargs = kwargs
        return ["hello world"]


class _SelectableTensor:
    def __init__(self, name: str) -> None:
        self.name = name

    def index_select(self, dimension: int, index: object) -> tuple[str, int, object]:
        return self.name, dimension, index


def _generated_chunk(
    *,
    chunk_index: int,
    word: AlignedWordEvidence | None = None,
    reason: AlignmentUnavailableReason | None = None,
) -> _GeneratedChunk:
    return _GeneratedChunk(
        plan=_ChunkPlan(
            request_index=0,
            chunk_index=chunk_index,
            start_frame=chunk_index * 1_280,
            end_frame=(chunk_index + 1) * 1_280,
        ),
        token_ids=[10, 11, 20, 99],
        alignment=_ChunkAlignment(
            words=() if word is None else (word,),
            unavailable_reason=reason,
        ),
    )


class CohereEngineContractTests(unittest.TestCase):
    def test_alignment_metadata_keeps_prompt_content_and_eos_rows(self) -> None:
        processor = _Processor()

        transcript, pieces, matrix_token_count = _alignment_token_metadata(
            processor,
            [10, 11, 20, 21, 99, 0],
            prompt_token_count=2,
            language="en",
        )

        self.assertEqual(transcript, "hello world")
        self.assertEqual(pieces, ("▁hello", "▁world"))
        self.assertEqual(matrix_token_count, 5)
        self.assertEqual(processor.rows, [[10, 11, 20, 21, 99]])
        self.assertEqual(processor.kwargs["audio_chunk_index"], [(0, None)])

    def test_alignment_metadata_fails_closed_without_content_or_eos(self) -> None:
        processor = _Processor()
        cases = (
            ([10, 11, 99], AlignmentUnavailableReason.EMPTY_TRANSCRIPT),
            ([10, 11, 20], AlignmentUnavailableReason.TOKEN_TRANSCRIPT_DIVERGED),
        )
        for token_ids, reason in cases:
            with self.subTest(reason=reason):
                with self.assertRaises(AlignmentUnavailable) as raised:
                    _alignment_token_metadata(
                        processor,
                        token_ids,
                        prompt_token_count=2,
                        language="en",
                    )
                self.assertEqual(raised.exception.reason, reason)

    def test_teacher_pass_selects_only_model_tensors(self) -> None:
        index = object()
        selected = _selected_teacher_inputs(
            {
                "audio_chunk_index": [(0, None)],
                "decoder_input_ids": _SelectableTensor("decoder"),
                "input_features": _SelectableTensor("features"),
                "attention_mask": _SelectableTensor("mask"),
            },
            index,
        )

        self.assertEqual(
            selected,
            {
                "input_features": ("features", 0, index),
                "attention_mask": ("mask", 0, index),
            },
        )
        with self.assertRaisesRegex(RuntimeError, "not a tensor"):
            _selected_teacher_inputs({"unexpected_metadata": []}, index)

    def test_chunk_alignment_reassembly_reindexes_and_fails_closed(self) -> None:
        first = _generated_chunk(
            chunk_index=0,
            word=AlignedWordEvidence(0, "hello", 0, 80),
        )
        second = _generated_chunk(
            chunk_index=1,
            word=AlignedWordEvidence(0, "world", 80, 160),
        )

        self.assertEqual(
            _merge_chunk_alignments([first, second], "hello world"),
            {
                "status": "available",
                "reason": None,
                "componentRevision": ALIGNMENT_COMPONENT_REVISION,
                "alignedWords": [
                    first.alignment.words[0].to_result(),
                    {
                        **second.alignment.words[0].to_result(),
                        "wordIndex": 1,
                    },
                ],
            },
        )
        diverged = _merge_chunk_alignments([first, second], "hello there")
        self.assertEqual(
            diverged["reason"],
            AlignmentUnavailableReason.TOKEN_TRANSCRIPT_DIVERGED.value,
        )
        runtime_failed = _merge_chunk_alignments(
            [
                first,
                _generated_chunk(
                    chunk_index=1,
                    reason=AlignmentUnavailableReason.RUNTIME_FAILED,
                ),
            ],
            "hello world",
        )
        self.assertEqual(
            runtime_failed["reason"],
            AlignmentUnavailableReason.RUNTIME_FAILED.value,
        )

    def test_worker_result_drops_alignment_before_crossing_its_byte_bound(self) -> None:
        lock = _test_lock()
        request = CohereAsrInput(
            job_id="job-1",
            audio=PcmAudio(
                pcm_bytes=bytes(320),
                sample_rate=16_000,
                frame_count=160,
                duration_ms=10,
                sha256=AUDIO_SHA256,
            ),
            language="en",
            punctuation=True,
        )
        alignment = {
            "status": "available",
            "reason": None,
            "componentRevision": ALIGNMENT_COMPONENT_REVISION,
            "alignedWords": [AlignedWordEvidence(0, "hello", 0, 10).to_result()],
        }

        with patch("yap_server.pools.cohere_engine.MAX_WORKER_RESULT_BYTES", 1):
            payload = _result_payload(
                request=request,
                lock=lock,
                transcript="hello",
                alignment=alignment,
                runtime={"device": "cuda"},
            )

        self.assertEqual(payload["alignment"]["status"], "unavailable")
        self.assertEqual(
            payload["alignment"]["reason"],
            AlignmentUnavailableReason.RESULT_LIMIT.value,
        )


if __name__ == "__main__":
    unittest.main()
