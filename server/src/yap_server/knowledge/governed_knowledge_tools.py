from __future__ import annotations

import threading
import time
from typing import Callable
import re

from psycopg import Connection
from psycopg.errors import QueryCanceled

from yap_server.auth.principal import PrincipalKey

from .knowledge_tool_audit import record_knowledge_tool_audit
from .knowledge_tool_contract import (
    BrowseKnowledgeRequest,
    KnowledgeAgentProfile,
    KnowledgeToolCancelled,
    KnowledgeToolCitation,
    KnowledgeToolItem,
    KnowledgeToolRequest,
    KnowledgeToolResponse,
    KnowledgeToolTimedOut,
    SearchKnowledgeRequest,
    TraverseKnowledgeRequest,
)
from .postgres_knowledge_retrieval import (
    list_postgres_knowledge_tree,
    search_postgres_knowledge_lexical,
)
from .postgres_relationship_retrieval import (
    traverse_postgres_knowledge_relationships,
)


_PROFILE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SUPPORTED_CAPABILITIES = frozenset(
    {
        "knowledge.tree",
        "knowledge.search.lexical",
        "knowledge.search.vector",
        "knowledge.search.hybrid",
        "knowledge.relationship.traverse",
        "knowledge.propose",
    }
)


class GovernedKnowledgeTools:
    """Expose bounded governed queries while keeping storage authority private."""

    def __init__(self, profiles: tuple[KnowledgeAgentProfile, ...]) -> None:
        if not isinstance(profiles, tuple):
            raise TypeError("knowledge agent profiles must be immutable")
        validated = {_profile(item).agent_id: item for item in profiles}
        if len(validated) != len(profiles):
            raise ValueError("knowledge agent profile is duplicated")
        self._profiles = validated

    def execute(
        self,
        connection: Connection[object],
        *,
        principal: PrincipalKey,
        agent_id: str,
        request: KnowledgeToolRequest,
        cancellation: threading.Event,
    ) -> KnowledgeToolResponse:
        started = time.monotonic()
        operation = _operation_name(request)
        profile = self._profiles.get(agent_id)
        if profile is None:
            _record_failure(
                connection, principal, agent_id, operation, "denied", started
            )
            raise PermissionError("knowledge agent profile is not authorized")
        if request.purpose not in profile.purposes:
            _record_failure(
                connection, principal, agent_id, operation, "denied", started
            )
            raise PermissionError("knowledge purpose is not authorized for agent")
        if cancellation.is_set():
            _record_failure(
                connection, principal, agent_id, operation, "cancelled", started
            )
            raise KnowledgeToolCancelled("knowledge tool request was cancelled")
        try:
            with connection.transaction():
                connection.execute(
                    "SELECT set_config('statement_timeout', %s, true)",
                    (str(profile.statement_timeout_milliseconds),),
                )
                response = _run_cancellable(
                    connection,
                    cancellation,
                    lambda: self._execute_query(
                        connection, principal, profile, request, operation
                    ),
                )
                record_knowledge_tool_audit(
                    connection,
                    principal=principal,
                    agent_id=agent_id,
                    operation=operation,
                    outcome="succeeded",
                    result_count=len(response.items),
                    generation_sha256=response.generation_sha256,
                    permission_hash=response.permission_hash,
                    authorization_hash=response.authorization_hash,
                    duration_milliseconds=_duration(started),
                )
            return response
        except KnowledgeToolCancelled:
            _record_failure(
                connection, principal, agent_id, operation, "cancelled", started
            )
            raise
        except QueryCanceled as error:
            if cancellation.is_set():
                _record_failure(
                    connection, principal, agent_id, operation, "cancelled", started
                )
                raise KnowledgeToolCancelled(
                    "knowledge tool request was cancelled"
                ) from error
            _record_failure(
                connection, principal, agent_id, operation, "timed_out", started
            )
            raise KnowledgeToolTimedOut("knowledge tool request timed out") from error
        except Exception:
            _record_failure(
                connection, principal, agent_id, operation, "failed", started
            )
            raise

    def _execute_query(
        self,
        connection: Connection[object],
        principal: PrincipalKey,
        profile: KnowledgeAgentProfile,
        request: KnowledgeToolRequest,
        operation: str,
    ) -> KnowledgeToolResponse:
        if isinstance(request, SearchKnowledgeRequest):
            search = search_postgres_knowledge_lexical(
                connection,
                principal=principal,
                purpose=request.purpose,
                agent_capabilities=profile.capabilities,
                search_text=request.search_text,
                maximum_results=_bounded_results(request.maximum_results, profile),
                expected_generation_sha256=request.expected_generation_sha256,
            )
            items, exhausted = _bounded_search_items(
                search.results, profile.maximum_output_characters
            )
            return KnowledgeToolResponse(
                operation,
                search.generation_sha256,
                search.permission_hash,
                search.authorization_hash,
                items,
                exhausted,
            )
        if isinstance(request, TraverseKnowledgeRequest):
            traversal = traverse_postgres_knowledge_relationships(
                connection,
                principal=principal,
                purpose=request.purpose,
                agent_capabilities=profile.capabilities,
                start_concept_id=request.start_concept_id,
                maximum_depth=request.maximum_depth,
                maximum_results=_bounded_results(request.maximum_results, profile),
                expected_generation_sha256=request.expected_generation_sha256,
            )
            relationship_items = tuple(
                KnowledgeToolItem(
                    citation=KnowledgeToolCitation(
                        item.source_concept_id,
                        item.source_revision,
                        item.content_sha256,
                        item.source_char_start,
                        item.source_char_end,
                    ),
                    text=None,
                    relationship_type=item.relationship_type,
                    target_concept_id=item.target_concept_id,
                )
                for item in traversal.relationships
            )
            items, exhausted = _bounded_items(
                relationship_items, profile.maximum_output_characters
            )
            return KnowledgeToolResponse(
                operation,
                traversal.generation_sha256,
                traversal.permission_hash,
                traversal.authorization_hash,
                items,
                exhausted,
            )
        tree = list_postgres_knowledge_tree(
            connection,
            principal=principal,
            purpose=request.purpose,
            agent_capabilities=profile.capabilities,
            expected_generation_sha256=request.expected_generation_sha256,
        )
        tree_items = tuple(
            KnowledgeToolItem(
                citation=KnowledgeToolCitation(item.concept_id, "", "", None, None),
                text=item.title,
                relationship_type=None,
                target_concept_id=None,
            )
            for item in tree.concepts[: profile.maximum_results]
        )
        items, exhausted = _bounded_items(tree_items, profile.maximum_output_characters)
        return KnowledgeToolResponse(
            operation,
            tree.generation_sha256,
            tree.permission_hash,
            tree.authorization_hash,
            items,
            exhausted or len(tree.concepts) > profile.maximum_results,
        )


def _bounded_search_items(
    results: tuple[object, ...], maximum_characters: int
) -> tuple[tuple[KnowledgeToolItem, ...], bool]:
    items: list[KnowledgeToolItem] = []
    for result in results:
        text = str(getattr(result, "text"))
        items.append(
            KnowledgeToolItem(
                citation=KnowledgeToolCitation(
                    str(getattr(result, "concept_id")),
                    str(getattr(result, "source_revision")),
                    str(getattr(result, "content_sha256")),
                    int(getattr(result, "char_start")),
                    int(getattr(result, "char_end")),
                ),
                text=text,
                relationship_type=None,
                target_concept_id=None,
            )
        )
    return _bounded_items(tuple(items), maximum_characters)


def _bounded_items(
    items: tuple[KnowledgeToolItem, ...], maximum_characters: int
) -> tuple[tuple[KnowledgeToolItem, ...], bool]:
    output: list[KnowledgeToolItem] = []
    used = 0
    for item in items:
        size = sum(
            len(value)
            for value in (
                item.citation.concept_id,
                item.citation.source_revision,
                item.citation.content_sha256,
                item.text or "",
                item.relationship_type or "",
                item.target_concept_id or "",
            )
        )
        if used + size > maximum_characters:
            return tuple(output), True
        used += size
        output.append(item)
    return tuple(output), False


def _run_cancellable(
    connection: Connection[object],
    cancellation: threading.Event,
    operation: Callable[[], KnowledgeToolResponse],
) -> KnowledgeToolResponse:
    completed = threading.Event()

    def cancel_when_requested() -> None:
        while not completed.wait(0.01):
            if cancellation.is_set():
                connection.cancel_safe(timeout=1.0)
                return

    watcher = threading.Thread(target=cancel_when_requested, daemon=True)
    watcher.start()
    try:
        return operation()
    finally:
        completed.set()
        watcher.join(timeout=1.0)


def _profile(value: KnowledgeAgentProfile) -> KnowledgeAgentProfile:
    if (
        not _PROFILE_ID.fullmatch(value.agent_id)
        or not isinstance(value.capabilities, frozenset)
        or not value.capabilities
        or not value.capabilities <= _SUPPORTED_CAPABILITIES
        or not isinstance(value.purposes, frozenset)
        or not value.purposes
        or len(value.purposes) > 32
        or any(not _PROFILE_ID.fullmatch(item) for item in value.purposes)
    ):
        raise ValueError("knowledge agent profile is invalid")
    if not 1 <= value.maximum_results <= 100:
        raise ValueError("knowledge agent result bound is invalid")
    if not 1 <= value.maximum_output_characters <= 1_000_000:
        raise ValueError("knowledge agent output bound is invalid")
    if not 1 <= value.statement_timeout_milliseconds <= 300_000:
        raise ValueError("knowledge agent timeout is invalid")
    return value


def _record_failure(
    connection: Connection[object],
    principal: PrincipalKey,
    agent_id: str,
    operation: str,
    outcome: str,
    started: float,
) -> None:
    with connection.transaction():
        record_knowledge_tool_audit(
            connection,
            principal=principal,
            agent_id=agent_id,
            operation=operation,
            outcome=outcome,
            result_count=0,
            generation_sha256=None,
            permission_hash=None,
            authorization_hash=None,
            duration_milliseconds=_duration(started),
        )


def _bounded_results(requested: int, profile: KnowledgeAgentProfile) -> int:
    if isinstance(requested, bool) or not isinstance(requested, int) or requested < 1:
        raise ValueError("knowledge tool result limit is invalid")
    return min(requested, profile.maximum_results)


def _operation_name(request: KnowledgeToolRequest) -> str:
    if isinstance(request, SearchKnowledgeRequest):
        return "search"
    if isinstance(request, TraverseKnowledgeRequest):
        return "traverse"
    if isinstance(request, BrowseKnowledgeRequest):
        return "browse"
    raise TypeError("knowledge tool request type is invalid")


def _duration(started: float) -> int:
    return max(0, round((time.monotonic() - started) * 1_000))


__all__ = ["GovernedKnowledgeTools"]
