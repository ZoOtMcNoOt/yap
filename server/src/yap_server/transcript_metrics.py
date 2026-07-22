from __future__ import annotations

import re


_MAX_WORDS = 250_000
_MAX_EDIT_DISTANCE_CELLS = 20_000_000


def tokenize_wer_words(value: str) -> list[str]:
    """Return bounded case/punctuation-insensitive transcript tokens."""

    if not isinstance(value, str) or "\0" in value:
        raise ValueError("WER transcript must be valid text")
    words = re.findall(r"[\w']+", value.casefold(), flags=re.UNICODE)
    if len(words) > _MAX_WORDS:
        raise ValueError("WER transcript exceeds the word bound")
    return words


def word_error_rate(reference: str, hypothesis: str) -> float:
    """Measure bounded Levenshtein word error rate for regression gates."""

    expected = tokenize_wer_words(reference)
    actual = tokenize_wer_words(hypothesis)
    if not expected:
        raise ValueError("WER reference cannot be empty")
    if len(expected) * len(actual) > _MAX_EDIT_DISTANCE_CELLS:
        raise ValueError("WER alignment exceeds the work bound")
    previous = list(range(len(actual) + 1))
    for expected_word in expected:
        current = [previous[0] + 1]
        for index, actual_word in enumerate(actual, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[index] + 1,
                    previous[index - 1] + (expected_word != actual_word),
                )
            )
        previous = current
    return previous[-1] / len(expected)
