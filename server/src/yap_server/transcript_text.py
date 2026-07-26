from __future__ import annotations

from yap_server.limits import MAX_TRANSCRIPT_BYTES


def canonical_transcript(value: object, field: str) -> str:
    """Validate bounded canonical ASR text while allowing a valid empty result."""

    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    if "\0" in value or value != " ".join(value.split()):
        raise ValueError(f"{field} is not canonical")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError(f"{field} contains invalid Unicode") from error
    if len(encoded) > MAX_TRANSCRIPT_BYTES:
        raise ValueError(f"{field} exceeds the byte bound")
    return value
