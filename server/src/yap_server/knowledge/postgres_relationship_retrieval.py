from __future__ import annotations

from dataclasses import dataclass

from psycopg import Connection

from yap_server.auth.principal import PrincipalKey

from .postgres_permission_view import authorize_knowledge_query


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
) -> tuple[KnowledgeRelationshipResult, ...]:
    if not isinstance(start_concept_id, str) or not start_concept_id:
        raise ValueError("knowledge traversal start is invalid")
    if isinstance(maximum_depth, bool) or not 1 <= maximum_depth <= 4:
        raise ValueError("knowledge traversal depth is invalid")
    if isinstance(maximum_results, bool) or not 1 <= maximum_results <= 100:
        raise ValueError("knowledge traversal result limit is invalid")
    query = authorize_knowledge_query(
        connection,
        principal=principal,
        purpose=purpose,
        agent_capabilities=agent_capabilities,
        required_capability="knowledge.relationship.traverse",
        expected_generation_sha256=expected_generation_sha256,
    )
    if start_concept_id not in query.visible_concept_ids:
        return ()
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
    return tuple(
        KnowledgeRelationshipResult(
            *row,
            generation_sha256=query.generation_sha256,
            permission_hash=query.permission_hash,
            authorization_hash=query.authorization_hash,
        )
        for row in rows
    )


__all__ = [
    "KnowledgeRelationshipResult",
    "traverse_postgres_knowledge_relationships",
]
