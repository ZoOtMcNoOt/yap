from __future__ import annotations

import re


_MAX_BCP47_LENGTH = 35
_CANONICAL_BCP47 = re.compile(
    r"^[a-z]{2,3}"
    r"(?:-[A-Z][a-z]{3})?"
    r"(?:-(?:[A-Z]{2}|[0-9]{3}))?"
    r"(?:-(?:[A-Za-z0-9]{5,8}|[0-9][A-Za-z0-9]{3}))*$"
)


def canonical_bcp47(value: object, field: str) -> str:
    """Validate the bounded canonical BCP-47 subset used by Yap contracts."""

    if (
        not isinstance(value, str)
        or not value
        or len(value) > _MAX_BCP47_LENGTH
        or _CANONICAL_BCP47.fullmatch(value) is None
    ):
        raise ValueError(f"{field} must be a canonical BCP 47 tag")
    return value
