from __future__ import annotations

import unittest

from yap_server.evaluation.transcript_equivalence import (
    lexical_transcript_sha256,
    lexical_transcript_tokens,
    transcripts_match_lexically,
)


class TranscriptEquivalenceTests(unittest.TestCase):
    def test_ignores_casing_and_rendering_punctuation(self) -> None:
        self.assertTrue(
            transcripts_match_lexically(
                "We\u2019ll test this, carefully.",
                "we'll test this carefully",
            )
        )
        self.assertEqual(
            lexical_transcript_tokens("We\u2019ll test this, carefully."),
            ("we'll", "test", "this", "carefully"),
        )

    def test_preserves_spoken_word_differences(self) -> None:
        self.assertFalse(
            transcripts_match_lexically(
                "test this carefully",
                "test that carefully",
            )
        )
        self.assertFalse(transcripts_match_lexically(None, None))

    def test_hashes_only_the_lexical_identity(self) -> None:
        first = lexical_transcript_sha256("Stable, transcript.")
        second = lexical_transcript_sha256("stable transcript")
        self.assertEqual(first, second)
        self.assertRegex(first, r"^[0-9a-f]{64}$")
        with self.assertRaisesRegex(ValueError, "spoken tokens"):
            lexical_transcript_sha256("...")


if __name__ == "__main__":
    unittest.main()
