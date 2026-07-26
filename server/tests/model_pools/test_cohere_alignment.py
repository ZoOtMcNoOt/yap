from __future__ import annotations

import math
import unittest

from yap_server.alignment_contract import (
    AlignmentUnavailable,
    AlignmentUnavailableReason,
)
from yap_server.pools.cohere_alignment import (
    align_cohere_word_scores,
    valid_encoder_frame_count,
)


def _scores(starts: tuple[int, ...], frames: int) -> list[list[float]]:
    return [
        [-abs(frame - start) for frame in range(frames)]
        for start in starts
    ]


class CohereAlignmentTests(unittest.TestCase):
    def test_aligns_sentencepiece_words_on_the_source_timeline(self) -> None:
        words = align_cohere_word_scores(
            transcript="Well, I don't.",
            token_pieces=("▁Well", ",", "▁I", "▁don", "'", "t", "."),
            score_matrix=_scores((0, 1, 2, 3, 5, 6, 7, 8, 9), 10),
            content_token_offset=1,
            source_start_sample=1_600,
            source_frame_count=12_800,
        )

        self.assertEqual(
            [word.to_result() for word in words],
            [
                {
                    "wordIndex": 0,
                    "text": "Well,",
                    "startMs": 180,
                    "endMs": 340,
                    "turnId": None,
                    "attribution": {"kind": "unknown"},
                    "confidence": None,
                },
                {
                    "wordIndex": 1,
                    "text": "I",
                    "startMs": 340,
                    "endMs": 420,
                    "turnId": None,
                    "attribution": {"kind": "unknown"},
                    "confidence": None,
                },
                {
                    "wordIndex": 2,
                    "text": "don't.",
                    "startMs": 420,
                    "endMs": 820,
                    "turnId": None,
                    "attribution": {"kind": "unknown"},
                    "confidence": None,
                },
            ],
        )

    def test_rejects_divergent_nonfinite_degenerate_and_colliding_evidence(self) -> None:
        cases = (
            {
                "transcript": "hello",
                "token_pieces": ("▁goodbye",),
                "score_matrix": _scores((0, 1, 2), 3),
                "reason": AlignmentUnavailableReason.TOKEN_TRANSCRIPT_DIVERGED,
            },
            {
                "transcript": "hello",
                "token_pieces": ("▁hello",),
                "score_matrix": [[0.0, 1.0, 2.0], [0.0, math.nan, 2.0], [0.0, 1.0, 2.0]],
                "reason": AlignmentUnavailableReason.EVIDENCE_INVALID,
            },
            {
                "transcript": "hello",
                "token_pieces": ("▁hello",),
                "score_matrix": [[1.0, 1.0, 1.0]] * 3,
                "reason": AlignmentUnavailableReason.EVIDENCE_INVALID,
            },
            {
                "transcript": "a b",
                "token_pieces": ("▁a", "▁b"),
                "score_matrix": [[1.0], [2.0], [3.0], [4.0]],
                "reason": AlignmentUnavailableReason.EVIDENCE_INVALID,
            },
        )
        for case in cases:
            with self.subTest(case=case["reason"]):
                with self.assertRaises(AlignmentUnavailable) as raised:
                    align_cohere_word_scores(
                        transcript=case["transcript"],
                        token_pieces=case["token_pieces"],
                        score_matrix=case["score_matrix"],
                        content_token_offset=1,
                        source_start_sample=0,
                        source_frame_count=len(case["score_matrix"][0]) * 1_280,
                    )
                self.assertEqual(raised.exception.reason, case["reason"])

    def test_bounds_encoder_frames_tokens_and_global_word_indices(self) -> None:
        self.assertEqual(valid_encoder_frame_count(1), 1)
        self.assertEqual(valid_encoder_frame_count(1_280), 1)
        self.assertEqual(valid_encoder_frame_count(1_281), 2)
        with self.assertRaises(AlignmentUnavailable) as oversized:
            valid_encoder_frame_count(35 * 16_000 + 1)
        self.assertEqual(
            oversized.exception.reason,
            AlignmentUnavailableReason.SOURCE_LIMIT,
        )
        with self.assertRaises(AlignmentUnavailable) as word_limit:
            align_cohere_word_scores(
                transcript="hello",
                token_pieces=("▁hello",),
                score_matrix=_scores((0, 1, 2), 3),
                content_token_offset=1,
                source_start_sample=0,
                source_frame_count=3_840,
                first_word_index=16_384,
            )
        self.assertEqual(
            word_limit.exception.reason,
            AlignmentUnavailableReason.EVIDENCE_INVALID,
        )

    def test_sample_exact_chunk_offsets_round_consistently_to_milliseconds(self) -> None:
        words = align_cohere_word_scores(
            transcript="hello",
            token_pieces=("▁hello",),
            score_matrix=_scores((0, 1, 2), 3),
            content_token_offset=1,
            source_start_sample=1,
            source_frame_count=3_840,
        )

        self.assertEqual((words[0].start_ms, words[0].end_ms), (81, 161))

if __name__ == "__main__":
    unittest.main()
