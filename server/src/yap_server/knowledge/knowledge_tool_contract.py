from __future__ import annotations

from dataclasses import dataclass


class KnowledgeToolCancelled(RuntimeError):
    pass


class KnowledgeToolTimedOut(TimeoutError):
    pass


@dataclass(frozen=True, slots=True)
class KnowledgeAgentProfile:
    agent_id: str
    capabilities: frozenset[str]
    purposes: frozenset[str]
    maximum_results: int
    maximum_output_characters: int
    statement_timeout_milliseconds: int


@dataclass(frozen=True, slots=True)
class SearchKnowledgeRequest:
    purpose: str
    search_text: str
    maximum_results: int = 10
    expected_generation_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class BrowseKnowledgeRequest:
    purpose: str
    expected_generation_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class TraverseKnowledgeRequest:
    purpose: str
    start_concept_id: str
    maximum_depth: int = 2
    maximum_results: int = 50
    expected_generation_sha256: str | None = None


KnowledgeToolRequest = (
    SearchKnowledgeRequest | BrowseKnowledgeRequest | TraverseKnowledgeRequest
)


@dataclass(frozen=True, slots=True)
class KnowledgeToolCitation:
    concept_id: str
    source_revision: str
    content_sha256: str
    char_start: int | None
    char_end: int | None


@dataclass(frozen=True, slots=True)
class KnowledgeToolItem:
    citation: KnowledgeToolCitation
    text: str | None
    relationship_type: str | None
    target_concept_id: str | None


@dataclass(frozen=True, slots=True)
class KnowledgeToolResponse:
    operation: str
    generation_sha256: str
    permission_hash: str
    authorization_hash: str
    items: tuple[KnowledgeToolItem, ...]
    output_budget_exhausted: bool


__all__ = [
    "BrowseKnowledgeRequest",
    "KnowledgeAgentProfile",
    "KnowledgeToolCancelled",
    "KnowledgeToolCitation",
    "KnowledgeToolItem",
    "KnowledgeToolRequest",
    "KnowledgeToolResponse",
    "KnowledgeToolTimedOut",
    "SearchKnowledgeRequest",
    "TraverseKnowledgeRequest",
]
