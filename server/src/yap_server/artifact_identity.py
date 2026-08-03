"""Small strict artifact identities shared by frozen source locks."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
import re

from yap_server.json_contract import (
    exact_object,
    positive_int,
    sha256,
)


_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)


@dataclass(frozen=True, slots=True)
class ArtifactIdentity:
    path: str
    size: int
    sha256: str


def artifact_identities(
    value: object,
    field: str,
    *,
    maximum_entries: int = 256,
    maximum_artifact_bytes: int = 8 * 1024 * 1024 * 1024,
) -> tuple[ArtifactIdentity, ...]:
    if (
        not isinstance(value, list)
        or not 1 <= len(value) <= maximum_entries
    ):
        raise ValueError(f"{field} must be a bounded non-empty array")
    artifacts: list[ArtifactIdentity] = []
    paths: set[str] = set()
    for entry_value in value:
        entry = exact_object(entry_value, {"path", "size", "sha256"}, field)
        path = portable_artifact_path(entry["path"], f"{field} path")
        if path in paths:
            raise ValueError(f"{field} paths must be unique")
        paths.add(path)
        size = positive_int(entry["size"], f"{field} size")
        if size > maximum_artifact_bytes:
            raise ValueError(f"{field} size exceeds the bound")
        artifacts.append(
            ArtifactIdentity(
                path=path,
                size=size,
                sha256=sha256(entry["sha256"], f"{field} SHA-256"),
            )
        )
    return tuple(artifacts)


def require_artifact_paths(
    artifacts: tuple[ArtifactIdentity, ...],
    expected_paths: frozenset[str],
    field: str,
) -> None:
    if {artifact.path for artifact in artifacts} != expected_paths:
        raise ValueError(f"{field} artifact paths differ from the contract")


def portable_artifact_path(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise ValueError(f"{field} is invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or str(path) != value:
        raise ValueError(f"{field} is invalid")
    for segment in path.parts:
        stem = segment.split(".", 1)[0].upper()
        if (
            segment in {".", ".."}
            or _SAFE_SEGMENT.fullmatch(segment) is None
            or stem in _WINDOWS_RESERVED_NAMES
        ):
            raise ValueError(f"{field} is invalid")
    return value
