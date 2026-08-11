from __future__ import annotations

from dataclasses import dataclass

from psycopg import Connection

from yap_server.auth.principal import PrincipalKey

from .knowledge_tool_contract import (
    MAX_CONCEPT_ID_CHARACTERS,
    MAX_STORAGE_RESULTS,
    MAX_TRAVERSAL_DEPTH,
    validate_bounded_text,
    validate_integer,
)
from .postgres_permission_view import _authorize_knowledge_query


@dataclass(frozen=True, slots=True)
class KnowledgeRelationshipResult:
    relationship_id: str
    source_concept_id: str
    target_concept_id: str
    relationship_type: str
    authority: str
    depth: int
    source_path: str
    source_revision: str
    content_sha256: str
    source_char_start: int | None
    source_char_end: int | None
    generation_sha256: str
    permission_hash: str
    authorization_hash: str


@dataclass(frozen=True, slots=True)
class PostgresRelationshipTraversal:
    generation_sha256: str
    permission_hash: str
    authorization_hash: str
    relationships: tuple[KnowledgeRelationshipResult, ...]


def traverse_postgres_knowledge_relationships(
    connection: Connection[object],
    *,
    principal: PrincipalKey,
    purpose: str,
    agent_capabilities: frozenset[str],
    start_concept_id: str,
    maximum_depth: int = 2,
    maximum_results: int = 50,
    expected_generation_sha256: str | None = None,
) -> PostgresRelationshipTraversal:
    with connection.transaction():
        return _traverse_postgres_knowledge_relationships(
            connection,
            principal=principal,
            purpose=purpose,
            agent_capabilities=agent_capabilities,
            start_concept_id=start_concept_id,
            maximum_depth=maximum_depth,
            maximum_results=maximum_results,
            expected_generation_sha256=expected_generation_sha256,
        )


def _traverse_postgres_knowledge_relationships(
    connection: Connection[object],
    *,
    principal: PrincipalKey,
    purpose: str,
    agent_capabilities: frozenset[str],
    start_concept_id: str,
    maximum_depth: int,
    maximum_results: int,
    expected_generation_sha256: str | None,
) -> PostgresRelationshipTraversal:
    validate_bounded_text(
        start_concept_id,
        field="knowledge traversal start",
        maximum=MAX_CONCEPT_ID_CHARACTERS,
    )
    validate_integer(
        maximum_depth,
        minimum=1,
        maximum=MAX_TRAVERSAL_DEPTH,
        field="knowledge traversal depth",
    )
    validate_integer(
        maximum_results,
        minimum=1,
        maximum=MAX_STORAGE_RESULTS,
        field="knowledge traversal result limit",
    )
    query = _authorize_knowledge_query(
        connection,
        principal=principal,
        purpose=purpose,
        agent_capabilities=agent_capabilities,
        required_capability="knowledge.relationship.traverse",
        expected_generation_sha256=expected_generation_sha256,
    )
    if start_concept_id not in query.visible_concept_ids:
        return PostgresRelationshipTraversal(
            query.generation_sha256,
            query.permission_hash,
            query.authorization_hash,
            (),
        )
    visible = list(query.visible_concept_ids)
    rows = connection.execute(
        """WITH RECURSIVE walk AS (
             SELECT r.relationship_id, r.source_concept_id, r.target_concept_id,
                    r.relationship_type, r.authority, r.source_char_start,
                    r.source_char_end, 1 AS depth,
                    ARRAY[r.source_concept_id, r.target_concept_id] AS visited
             FROM yap_knowledge_relationships r
             WHERE r.tenant_id = %s AND r.generation_sha256 = %s
               AND r.source_concept_id = %s AND r.canonical
               AND r.source_concept_id = ANY(%s)
               AND r.target_concept_id = ANY(%s)
             UNION ALL
             SELECT r.relationship_id, r.source_concept_id, r.target_concept_id,
                    r.relationship_type, r.authority, r.source_char_start,
                    r.source_char_end, w.depth + 1,
                    w.visited || r.target_concept_id
             FROM walk w
             JOIN yap_knowledge_relationships r
               ON r.tenant_id = %s AND r.generation_sha256 = %s
              AND r.source_concept_id = w.target_concept_id
             WHERE w.depth < %s AND r.canonical
               AND r.source_concept_id = ANY(%s)
               AND r.target_concept_id = ANY(%s)
               AND NOT r.target_concept_id = ANY(w.visited)
           )
           SELECT w.relationship_id, w.source_concept_id, w.target_concept_id,
                  w.relationship_type, w.authority, w.depth, c.source_path,
                  b.source_revision, c.content_sha256,
                  w.source_char_start, w.source_char_end
           FROM walk w
           JOIN yap_knowledge_concepts c
             ON c.tenant_id = %s AND c.generation_sha256 = %s
            AND c.concept_id = w.source_concept_id
           JOIN yap_knowledge_builds b
             ON b.tenant_id = c.tenant_id
            AND b.generation_sha256 = c.generation_sha256
           ORDER BY w.depth, w.relationship_id
           LIMIT %s""",
        (
            query.tenant_id,
            query.generation_sha256,
            start_concept_id,
            visible,
            visible,
            query.tenant_id,
            query.generation_sha256,
            maximum_depth,
            visible,
            visible,
            query.tenant_id,
            query.generation_sha256,
            maximum_results,
        ),
    ).fetchall()
    return PostgresRelationshipTraversal(
        query.generation_sha256,
        query.permission_hash,
        query.authorization_hash,
        tuple(
            KnowledgeRelationshipResult(
                *row,
                generation_sha256=query.generation_sha256,
                permission_hash=query.permission_hash,
                authorization_hash=query.authorization_hash,
            )
            for row in rows
        ),
    )


__all__ = [
    "KnowledgeRelationshipResult",
    "PostgresRelationshipTraversal",
    "traverse_postgres_knowledge_relationships",
]
