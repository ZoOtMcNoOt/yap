from __future__ import annotations

import threading
import time

from psycopg import Connection
from psycopg.errors import QueryCanceled

from yap_server.auth.principal import PrincipalKey

from .cancellable_database_operation import run_cancellable_database_operation
from .knowledge_agent_authority import KnowledgeAgentAuthority
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


class GovernedKnowledgeTools:
    """Expose bounded governed queries while keeping storage authority private."""

    def __init__(self, authority: KnowledgeAgentAuthority) -> None:
        self._authority = authority

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
        try:
            profile = self._authority.authorize(
                agent_id=agent_id, purpose=request.purpose
            )
        except PermissionError:
            _record_failure(
                connection, principal, agent_id, operation, "denied", started
            )
            raise
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
                response = run_cancellable_database_operation(
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
