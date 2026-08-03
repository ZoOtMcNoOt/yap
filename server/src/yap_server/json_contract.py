"""Strict scalar and object fields shared by frozen JSON contracts."""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Mapping


_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,255}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def exact_object(value: object, keys: set[str], field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise ValueError(f"{field} fields differ from the contract")
    return value


def identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"{field} is invalid")
    return value


def model_id(value: object, field: str) -> str:
    if not isinstance(value, str) or _MODEL_ID.fullmatch(value) is None:
        raise ValueError(f"{field} is invalid")
    return value


def sha256(value: object, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{field} is invalid")
    return value


def enum_value(value: object, allowed: frozenset[str], field: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise ValueError(f"{field} is invalid")
    return value


def positive_int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{field} must be a positive integer")
    return value


def nonnegative_int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field} must be a nonnegative integer")
    return value


def https_uri(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.startswith("https://"):
        raise ValueError(f"{field} must be an HTTPS URI")
    return value


def utc(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"{field} must be UTC")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise ValueError(f"{field} is invalid") from error
    if parsed.tzinfo != timezone.utc:
        raise ValueError(f"{field} must be UTC")
    return parsed


def bounded_identifiers(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > 32:
        raise ValueError(f"{field} must be a bounded array")
    entries = tuple(identifier(item, field) for item in value)
    if len(set(entries)) != len(entries):
        raise ValueError(f"{field} must be unique")
    return entries
