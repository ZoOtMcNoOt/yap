"""Compatibility import for evaluation callers of the shared bounded metric."""

from yap_server.transcript_metrics import tokenize_wer_words, word_error_rate


__all__ = ["tokenize_wer_words", "word_error_rate"]
