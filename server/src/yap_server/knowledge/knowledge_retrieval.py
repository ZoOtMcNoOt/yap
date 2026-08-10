from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
import re
from urllib.parse import unquote, urlparse

from yap_server.auth.principal import PrincipalKey
from yap_server.knowledge.okf_compiler import CompiledKnowledgeGeneration
from yap_server.knowledge.permission_view import build_permission_filtered_view


_MAX_QUERY_CHARS = 1_024
_MAX_RESULTS = 100
_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)
_PARAGRAPH = re.compile(r"(?ms)(?:\A|(?:\r?\n){2,})([^\r\n].*?)(?=(?:\r?\n){2,}|\Z)")
_MARKDOWN_LINK = re.compile(
    r"(?<!!)\[[^\]\r\n]+\]\(([^)\s]+)(?:\s+['\"][^'\"]*['\"])?\)"
)


@dataclass(frozen=True, slots=True)
class KnowledgeSearchResult:
    concept_id: str
    source_path: str
    source_revision: str
    content_sha256: str
    char_start: int
    char_end: int
    text: str
    lexical_score: float


def search_compiled_knowledge(
    generation: CompiledKnowledgeGeneration,
    *,
    principal: PrincipalKey,
    purpose: str,
    query: str,
    maximum_results: int = 10,
) -> tuple[KnowledgeSearchResult, ...]:
    """Search only an authorized induced view and return exact citations."""

    query_tokens = _query_tokens(query)
    if (
        not isinstance(maximum_results, int)
        or isinstance(maximum_results, bool)
        or not 1 <= maximum_results <= _MAX_RESULTS
    ):
        raise ValueError("knowledge result limit is invalid")
    view = build_permission_filtered_view(
        generation,
        principal=principal,
        purpose=purpose,
    )
    visible_ids = frozenset(item.concept_id for item in view.concepts)
    candidates: list[KnowledgeSearchResult] = []
    for concept in generation.concepts:
        if concept.concept_id not in visible_ids:
            continue
        for start, end, text in _safe_paragraphs(
            concept.source_path,
            concept.body,
            visible_ids,
        ):
            tokens = _tokens(text)
            matched = query_tokens.intersection(tokens)
            if not matched:
                continue
            score = len(matched) / len(query_tokens)
            candidates.append(
                KnowledgeSearchResult(
                    concept_id=concept.concept_id,
                    source_path=concept.source_path,
                    source_revision=generation.source_revision,
                    content_sha256=concept.content_sha256,
                    char_start=start,
                    char_end=end,
                    text=text,
                    lexical_score=score,
                )
            )
    candidates.sort(
        key=lambda item: (
            -item.lexical_score,
            item.concept_id,
            item.char_start,
        )
    )
    return tuple(candidates[:maximum_results])


def _safe_paragraphs(
    source_path: str,
    body: str,
    visible_ids: frozenset[str],
) -> tuple[tuple[int, int, str], ...]:
    paragraphs: list[tuple[int, int, str]] = []
    for match in _PARAGRAPH.finditer(body):
        raw = match.group(1)
        leading = len(raw) - len(raw.lstrip())
        trailing = len(raw) - len(raw.rstrip())
        start = match.start(1) + leading
        end = match.end(1) - trailing
        text = body[start:end]
        if (
            not text
            or text.startswith("#")
            or _contains_hidden_link(source_path, text, visible_ids)
        ):
            continue
        paragraphs.append((start, end, text))
    return tuple(paragraphs)


def _contains_hidden_link(
    source_path: str,
    text: str,
    visible_ids: frozenset[str],
) -> bool:
    for match in _MARKDOWN_LINK.finditer(text):
        target = _internal_concept_id(source_path, match.group(1))
        if target is not None and target not in visible_ids:
            return True
    return False


def _internal_concept_id(source_path: str, raw_target: str) -> str | None:
    raw = unquote(raw_target).split("#", 1)[0]
    parsed = urlparse(raw)
    if parsed.scheme or parsed.netloc or not raw or raw.startswith("#"):
        return None
    if raw.startswith("/"):
        target = PurePosixPath(raw.removeprefix("/"))
    else:
        target = PurePosixPath(source_path).parent / raw
    normalized: list[str] = []
    for part in target.parts:
        if part in {"", "."}:
            continue
        if part == "..":
            if not normalized:
                return ""
            normalized.pop()
        else:
            normalized.append(part)
    if not normalized:
        return None
    value = PurePosixPath(*normalized)
    if value.suffix.casefold() != ".md":
        return None
    return value.with_suffix("").as_posix()


def _query_tokens(query: str) -> frozenset[str]:
    if (
        not isinstance(query, str)
        or not query.strip()
        or query != query.strip()
        or len(query) > _MAX_QUERY_CHARS
    ):
        raise ValueError("knowledge query is invalid")
    values = _tokens(query)
    if not values:
        raise ValueError("knowledge query is invalid")
    return values


def _tokens(value: str) -> frozenset[str]:
    return frozenset(match.group(0).casefold() for match in _TOKEN.finditer(value))


__all__ = ["KnowledgeSearchResult", "search_compiled_knowledge"]
