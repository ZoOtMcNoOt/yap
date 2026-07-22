from __future__ import annotations

import unittest

from yap_server.evaluation.word_error_rate import (
    tokenize_wer_words,
    word_error_rate,
)


class WordErrorRateTests(unittest.TestCase):
    def test_is_case_and_punctuation_insensitive(self) -> None:
        reference = "Well, I don't wish to see it."
        hypothesis = "well i don't wish to see it"
        self.assertEqual(word_error_rate(reference, hypothesis), 0.0)

    def test_counts_insertions_deletions_and_substitutions(self) -> None:
        self.assertEqual(word_error_rate("one two three", "one four"), 2 / 3)

    def test_tokenization_preserves_apostrophes(self) -> None:
        self.assertEqual(tokenize_wer_words("Don't stop."), ["don't", "stop"])

    def test_rejects_empty_reference_and_unbounded_alignment_work(self) -> None:
        with self.assertRaisesRegex(ValueError, "reference cannot be empty"):
            word_error_rate("", "words")
        oversized = " ".join(["word"] * 4_473)
        with self.assertRaisesRegex(ValueError, "work bound"):
            word_error_rate(oversized, oversized)


if __name__ == "__main__":
    unittest.main()
