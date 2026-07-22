from __future__ import annotations

import hashlib
import json
import re


_LEXICAL_TOKEN = re.compile(r"[^\W_]+(?:['\u2019][^\W_]+)*")


def lexical_transcript_tokens(text: str | None) -> tuple[str, ...]:
    """Return case-insensitive word identities without rendering punctuation."""

    if text is None:
        return ()
    return tuple(
        token.replace("\u2019", "'").casefold()
        for token in _LEXICAL_TOKEN.findall(text)
    )


def transcripts_match_lexically(left: str | None, right: str | None) -> bool:
    """Compare non-empty ASR text while ignoring casing and punctuation."""

    left_tokens = lexical_transcript_tokens(left)
    return bool(left_tokens) and left_tokens == lexical_transcript_tokens(right)


def lexical_transcript_sha256(text: str) -> str:
    """Hash bounded lexical identities without exposing transcript content."""

    tokens = lexical_transcript_tokens(text)
    if not tokens:
        raise ValueError("lexical transcript identity requires spoken tokens")
    encoded = json.dumps(
        tokens,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
