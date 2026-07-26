from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from yap_server.auth.principal import PrincipalKey


Purpose = Literal["enrollment", "matching", "adaptation"]
PURPOSES = frozenset({"enrollment", "matching", "adaptation"})
MAX_DISPLAY_NAME_CHARS = 256
MAX_METADATA_CHARS = 256


def bounded_identity_text(
    value: str,
    *,
    field: str,
    maximum: int = MAX_METADATA_CHARS,
) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > maximum
        or not value.isprintable()
        or value.strip() != value
    ):
        raise ValueError(f"{field} is invalid")
    return value


def optional_display_name(value: str | None) -> str | None:
    if value is None:
        return None
    return bounded_identity_text(
        value,
        field="display_name_snapshot",
        maximum=MAX_DISPLAY_NAME_CHARS,
    )


def validated_purpose(value: str) -> Purpose:
    if value not in PURPOSES:
        raise ValueError("purpose is invalid")
    return value


def canonical_uuid(value: str, field: str) -> str:
    value = bounded_identity_text(value, field=field, maximum=64).lower()
    try:
        parsed = UUID(value)
    except ValueError as error:
        raise ValueError(f"{field} must be a UUID") from error
    if str(parsed) != value:
        raise ValueError(f"{field} must be a canonical UUID")
    return value


def utc_timestamp(value: datetime) -> tuple[str, int]:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("repository clock must return an aware datetime")
    utc = value.astimezone(UTC)
    return utc.isoformat(timespec="seconds").replace("+00:00", "Z"), int(
        utc.timestamp()
    )


@dataclass(frozen=True, slots=True)
class PrincipalRecord:
    key: PrincipalKey
    display_name_snapshot: str | None
    created_at_utc: str
    last_seen_at_utc: str
    access_revoked_after_unix: int


@dataclass(frozen=True, slots=True)
class PurposeGrantMetadata:
    grant_id: str
    legal_basis_code: str
    privacy_assessment_ref: str
    notice_version: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "grant_id",
            canonical_uuid(self.grant_id, "grant_id"),
        )
        for field in (
            "legal_basis_code",
            "privacy_assessment_ref",
            "notice_version",
        ):
            object.__setattr__(
                self,
                field,
                bounded_identity_text(getattr(self, field), field=field),
            )
