from __future__ import annotations

from dataclasses import dataclass
import re

from yap_server.auth.principal import PrincipalKey
from yap_server.knowledge.okf_compiler import CompiledKnowledgeGeneration
from yap_server.knowledge.permission_view import build_permission_filtered_view


_MAX_QUERY_CHARS = 1_024
_MAX_RESULTS = 100
_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)


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
    concepts = {item.concept_id: item for item in generation.concepts}
    for chunk in generation.chunks:
        if chunk.concept_id not in visible_ids or not set(
            chunk.linked_concept_ids
        ).issubset(visible_ids):
            continue
        tokens = _tokens(chunk.text)
        matched = query_tokens.intersection(tokens)
        if not matched:
            continue
        score = len(matched) / len(query_tokens)
        concept = concepts[chunk.concept_id]
        candidates.append(
            KnowledgeSearchResult(
                concept_id=concept.concept_id,
                source_path=concept.source_path,
                source_revision=generation.source_revision,
                content_sha256=concept.content_sha256,
                char_start=chunk.char_start,
                char_end=chunk.char_end,
                text=chunk.text,
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
