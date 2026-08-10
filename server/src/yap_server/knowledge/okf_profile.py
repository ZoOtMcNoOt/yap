from __future__ import annotations

from datetime import date, datetime
from pathlib import Path, PurePosixPath
import re
from types import MappingProxyType
from urllib.parse import unquote, urlparse


_MARKDOWN_LINK = re.compile(
    r"(?<!!)\[[^\]\r\n]+\]\(([^)\s]+)(?:\s+['\"][^'\"]*['\"])?\)"
)


def validate_concept_profile(
    value: dict[str, object], tenant_id: str, path: Path, resources: set[str]
) -> None:
    required = {"type", "title", "resource", "timestamp", "yap_schema", "provenance"}
    if not required.issubset(value):
        raise ValueError(f"OKF concept {path.as_posix()} lacks Yap profile fields")
    for field in ("type", "title"):
        item = value[field]
        if not isinstance(item, str) or not item.strip() or item != item.strip():
            raise ValueError(f"OKF concept {path.as_posix()} {field} is invalid")
    if value["yap_schema"] != 1:
        raise ValueError(f"OKF concept {path.as_posix()} yap_schema is unsupported")
    if not isinstance(value["provenance"], dict) or not value["provenance"]:
        raise ValueError(f"OKF concept {path.as_posix()} provenance is invalid")
    if not isinstance(value["timestamp"], (str, datetime)):
        raise ValueError(f"OKF concept {path.as_posix()} timestamp is invalid")
    resource = value["resource"]
    if not isinstance(resource, str):
        raise ValueError(f"OKF concept {path.as_posix()} resource is invalid")
    parsed = urlparse(resource)
    parts = tuple(part for part in parsed.path.split("/") if part)
    if (
        parsed.scheme != "yap"
        or parsed.netloc != "tenant"
        or parsed.params
        or parsed.query
        or parsed.fragment
        or len(parts) < 3
        or unquote(parts[0]) != tenant_id
    ):
        raise ValueError(f"OKF concept {path.as_posix()} resource is invalid")
    if resource in resources:
        raise ValueError(f"OKF concept {path.as_posix()} duplicates a resource")
    resources.add(resource)


def concept_links(source_path: Path, markdown: str) -> tuple[str, ...]:
    values: set[str] = set()
    for match in _MARKDOWN_LINK.finditer(markdown):
        raw = unquote(match.group(1)).split("#", 1)[0]
        parsed = urlparse(raw)
        if parsed.scheme or parsed.netloc or not raw or raw.startswith("#"):
            continue
        target = (
            PurePosixPath(raw.removeprefix("/"))
            if raw.startswith("/")
            else PurePosixPath(source_path.parent.as_posix()) / raw
        )
        normalized: list[str] = []
        for part in target.parts:
            if part in {"", "."}:
                continue
            if part == "..":
                if not normalized:
                    raise ValueError("OKF link escapes the bundle")
                normalized.pop()
            else:
                normalized.append(part)
        if not normalized or normalized[-1] in {"index.md", "log.md"}:
            continue
        value = PurePosixPath(*normalized)
        if value.suffix.casefold() == ".md":
            values.add(value.with_suffix("").as_posix())
    return tuple(sorted(values))


def identity(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 128
        or not value.isascii()
        or not value.isprintable()
        or value.strip() != value
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field} is invalid")
    return value


def json_value(value: object, field: str) -> object:
    if value is None or isinstance(value, (bool, int, float, str)):
        if isinstance(value, float) and not (-float("inf") < value < float("inf")):
            raise ValueError(f"{field} contains a non-finite number")
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, list):
        return [json_value(item, field) for item in value]
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        return {key: json_value(item, field) for key, item in value.items()}
    raise ValueError(f"{field} contains an unsupported YAML value")


def freeze(value: object) -> object:
    if isinstance(value, dict):
        return MappingProxyType({key: freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(freeze(item) for item in value)
    return value
