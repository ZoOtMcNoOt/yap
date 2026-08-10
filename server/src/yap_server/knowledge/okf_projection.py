from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import PurePosixPath
import re
from typing import Mapping
from urllib.parse import unquote, urlparse


_PARAGRAPH = re.compile(r"(?ms)(?:\A|(?:\r?\n){2,})([^\r\n].*?)(?=(?:\r?\n){2,}|\Z)")
_MARKDOWN_LINK = re.compile(
    r"(?<!!)\[[^\]\r\n]+\]\(([^)\s]+)(?:\s+['\"][^'\"]*['\"])?\)"
)
_RELATIONSHIP_AUTHORITIES = {
    "asserted",
    "human_confirmed",
    "derived",
    "agent_proposed",
}


@dataclass(frozen=True, slots=True)
class CompiledChunk:
    chunk_id: str
    concept_id: str
    permission_sha256: str
    char_start: int
    char_end: int
    text: str
    linked_concept_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CompiledRelationship:
    relationship_id: str
    source_concept_id: str
    target_concept_id: str
    relationship_type: str
    authority: str
    source_char_start: int | None
    source_char_end: int | None
    canonical: bool


def compile_chunks(
    *,
    concept_id: str,
    source_path: str,
    body: str,
    permission_sha256: str,
) -> tuple[CompiledChunk, ...]:
    chunks: list[CompiledChunk] = []
    for match in _PARAGRAPH.finditer(body):
        raw = match.group(1)
        leading = len(raw) - len(raw.lstrip())
        trailing = len(raw) - len(raw.rstrip())
        start = match.start(1) + leading
        end = match.end(1) - trailing
        text = body[start:end]
        if not text or text.startswith("#"):
            continue
        links = tuple(
            sorted(
                {
                    target
                    for link in _MARKDOWN_LINK.finditer(text)
                    if (target := internal_concept_id(source_path, link.group(1)))
                    is not None
                }
            )
        )
        identity = f"{concept_id}\0{start}\0{end}\0{text}".encode("utf-8")
        chunks.append(
            CompiledChunk(
                chunk_id=hashlib.sha256(identity).hexdigest(),
                concept_id=concept_id,
                permission_sha256=permission_sha256,
                char_start=start,
                char_end=end,
                text=text,
                linked_concept_ids=links,
            )
        )
    return tuple(chunks)


def compile_relationships(
    *,
    concept_id: str,
    source_path: str,
    body: str,
    frontmatter: Mapping[str, object],
) -> tuple[CompiledRelationship, ...]:
    records: list[CompiledRelationship] = []
    for match in _MARKDOWN_LINK.finditer(body):
        target = internal_concept_id(source_path, match.group(1))
        if target is not None:
            records.append(
                _relationship(
                    concept_id,
                    target,
                    relationship_type="links_to",
                    authority="asserted",
                    source_char_start=match.start(),
                    source_char_end=match.end(),
                )
            )
    declared = frontmatter.get("relationships", [])
    if not isinstance(declared, (list, tuple)):
        raise ValueError("OKF relationships are invalid")
    for item in declared:
        if not isinstance(item, Mapping) or set(item) != {
            "type",
            "target",
            "authority",
        }:
            raise ValueError("OKF relationship fields differ from the contract")
        relationship_type = _identity(item["type"], "relationship type")
        authority = _identity(item["authority"], "relationship authority")
        if authority not in _RELATIONSHIP_AUTHORITIES:
            raise ValueError("OKF relationship authority is invalid")
        raw_target = item["target"]
        if not isinstance(raw_target, str):
            raise ValueError("OKF relationship target is invalid")
        target = internal_concept_id(source_path, raw_target)
        if target is None:
            raise ValueError("OKF relationship target is invalid")
        records.append(
            _relationship(
                concept_id,
                target,
                relationship_type=relationship_type,
                authority=authority,
                source_char_start=None,
                source_char_end=None,
            )
        )
    unique = {record.relationship_id: record for record in records}
    return tuple(unique[key] for key in sorted(unique))


def internal_concept_id(source_path: str, raw_target: str) -> str | None:
    raw = unquote(raw_target).split("#", 1)[0]
    parsed = urlparse(raw)
    if parsed.scheme or parsed.netloc or not raw or raw.startswith("#"):
        return None
    target = (
        PurePosixPath(raw.removeprefix("/"))
        if raw.startswith("/")
        else PurePosixPath(source_path).parent / raw
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
    if not normalized:
        return None
    value = PurePosixPath(*normalized)
    if value.suffix.casefold() != ".md":
        return None
    return value.with_suffix("").as_posix()


def _relationship(
    source: str,
    target: str,
    *,
    relationship_type: str,
    authority: str,
    source_char_start: int | None,
    source_char_end: int | None,
) -> CompiledRelationship:
    identity = (
        f"{source}\0{target}\0{relationship_type}\0{authority}\0"
        f"{source_char_start}\0{source_char_end}"
    )
    return CompiledRelationship(
        relationship_id=hashlib.sha256(identity.encode("utf-8")).hexdigest(),
        source_concept_id=source,
        target_concept_id=target,
        relationship_type=relationship_type,
        authority=authority,
        source_char_start=source_char_start,
        source_char_end=source_char_end,
        canonical=authority != "agent_proposed",
    )


def _identity(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 128
        or value.strip() != value
        or not value.isascii()
        or not value.isprintable()
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"OKF {field} is invalid")
    return value


__all__ = [
    "CompiledChunk",
    "CompiledRelationship",
    "compile_chunks",
    "compile_relationships",
    "internal_concept_id",
]
