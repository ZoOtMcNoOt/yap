from __future__ import annotations

from dataclasses import dataclass, replace
import re

from psycopg import Connection

from yap_server.auth.principal import PrincipalKey

from .generation_ledger import serialize_embedding_vector
from .permission_view import PermissionFilteredConcept
from .postgres_permission_view import (
    AuthorizedKnowledgeQuery,
    authorize_knowledge_query,
)


_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)


@dataclass(frozen=True, slots=True)
class PostgresKnowledgeSearchResult:
    concept_id: str
    source_path: str
    source_revision: str
    content_sha256: str
    char_start: int
    char_end: int
    text: str
    generation_sha256: str
    permission_hash: str
    authorization_hash: str
    retrieval_score: float
    lexical_score: float | None
    vector_distance: float | None


def list_postgres_knowledge_tree(
    connection: Connection[object],
    *,
    principal: PrincipalKey,
    purpose: str,
    agent_capabilities: frozenset[str],
    expected_generation_sha256: str | None = None,
) -> tuple[PermissionFilteredConcept, ...]:
    query = authorize_knowledge_query(
        connection,
        principal=principal,
        purpose=purpose,
        agent_capabilities=agent_capabilities,
        required_capability="knowledge.tree",
        expected_generation_sha256=expected_generation_sha256,
    )
    if not query.visible_concept_ids:
        return ()
    rows = connection.execute(
        """SELECT concept_id, frontmatter->>'type', frontmatter->>'title',
                  frontmatter->>'resource'
           FROM yap_knowledge_concepts
           WHERE tenant_id = %s AND generation_sha256 = %s
             AND concept_id = ANY(%s)
           ORDER BY concept_id""",
        (
            query.tenant_id,
            query.generation_sha256,
            list(query.visible_concept_ids),
        ),
    ).fetchall()
    return tuple(PermissionFilteredConcept(*row) for row in rows)


def search_postgres_knowledge_lexical(
    connection: Connection[object],
    *,
    principal: PrincipalKey,
    purpose: str,
    agent_capabilities: frozenset[str],
    search_text: str,
    maximum_results: int = 10,
    expected_generation_sha256: str | None = None,
) -> tuple[PostgresKnowledgeSearchResult, ...]:
    _search_input(search_text, maximum_results)
    query = authorize_knowledge_query(
        connection,
        principal=principal,
        purpose=purpose,
        agent_capabilities=agent_capabilities,
        required_capability="knowledge.search.lexical",
        expected_generation_sha256=expected_generation_sha256,
    )
    return _lexical_results(connection, query, search_text, maximum_results)


def search_postgres_knowledge_vector(
    connection: Connection[object],
    *,
    principal: PrincipalKey,
    purpose: str,
    agent_capabilities: frozenset[str],
    query_embedding: tuple[float, ...],
    embedding_model_id: str,
    embedding_model_revision: str,
    maximum_results: int = 10,
    expected_generation_sha256: str | None = None,
) -> tuple[PostgresKnowledgeSearchResult, ...]:
    _result_limit(maximum_results)
    vector = serialize_embedding_vector(query_embedding)
    query = authorize_knowledge_query(
        connection,
        principal=principal,
        purpose=purpose,
        agent_capabilities=agent_capabilities,
        required_capability="knowledge.search.vector",
        expected_generation_sha256=expected_generation_sha256,
    )
    return _vector_results(
        connection,
        query,
        vector,
        embedding_model_id,
        embedding_model_revision,
        maximum_results,
    )


def search_postgres_knowledge_hybrid(
    connection: Connection[object],
    *,
    principal: PrincipalKey,
    purpose: str,
    agent_capabilities: frozenset[str],
    search_text: str,
    query_embedding: tuple[float, ...],
    embedding_model_id: str,
    embedding_model_revision: str,
    maximum_results: int = 10,
    expected_generation_sha256: str | None = None,
) -> tuple[PostgresKnowledgeSearchResult, ...]:
    _search_input(search_text, maximum_results)
    vector = serialize_embedding_vector(query_embedding)
    query = authorize_knowledge_query(
        connection,
        principal=principal,
        purpose=purpose,
        agent_capabilities=agent_capabilities,
        required_capability="knowledge.search.hybrid",
        expected_generation_sha256=expected_generation_sha256,
    )
    candidate_limit = min(100, maximum_results * 4)
    lexical = _lexical_results(connection, query, search_text, candidate_limit)
    semantic = _vector_results(
        connection,
        query,
        vector,
        embedding_model_id,
        embedding_model_revision,
        candidate_limit,
    )
    ranked: dict[tuple[str, int], PostgresKnowledgeSearchResult] = {}
    scores: dict[tuple[str, int], float] = {}
    for results in (lexical, semantic):
        for rank, result in enumerate(results, start=1):
            key = (result.concept_id, result.char_start)
            scores[key] = scores.get(key, 0.0) + 1.0 / (60 + rank)
            existing = ranked.get(key)
            if existing is None:
                ranked[key] = result
            elif result.lexical_score is not None:
                ranked[key] = replace(existing, lexical_score=result.lexical_score)
            else:
                ranked[key] = replace(existing, vector_distance=result.vector_distance)
    ordered = sorted(scores, key=lambda key: (-scores[key], key))[:maximum_results]
    return tuple(replace(ranked[key], retrieval_score=scores[key]) for key in ordered)


def _lexical_results(
    connection: Connection[object],
    query: AuthorizedKnowledgeQuery,
    search_text: str,
    maximum_results: int,
) -> tuple[PostgresKnowledgeSearchResult, ...]:
    if not query.visible_concept_ids:
        return ()
    visible = list(query.visible_concept_ids)
    rows = connection.execute(
        """WITH requested AS (SELECT plainto_tsquery('simple', %s) AS query)
           SELECT c.concept_id, c.source_path, b.source_revision,
                  c.content_sha256, h.char_start, h.char_end, h.body,
                  ts_rank_cd(to_tsvector('simple', h.body), requested.query)
           FROM yap_knowledge_chunks h
           JOIN yap_knowledge_concepts c
             ON c.tenant_id = h.tenant_id
            AND c.generation_sha256 = h.generation_sha256
            AND c.concept_id = h.concept_id
           JOIN yap_knowledge_builds b
             ON b.tenant_id = h.tenant_id
            AND b.generation_sha256 = h.generation_sha256
           CROSS JOIN requested
           WHERE h.tenant_id = %s AND h.generation_sha256 = %s
             AND h.concept_id = ANY(%s)
             AND NOT EXISTS (
                SELECT 1 FROM jsonb_array_elements_text(h.linked_concept_ids) link
                WHERE NOT (link = ANY(%s))
             )
             AND to_tsvector('simple', h.body) @@ requested.query
           ORDER BY 8 DESC, c.concept_id, h.char_start
           LIMIT %s""",
        (
            search_text,
            query.tenant_id,
            query.generation_sha256,
            visible,
            visible,
            maximum_results,
        ),
    ).fetchall()
    return tuple(_search_result(row, query, lexical=float(row[7])) for row in rows)


def _vector_results(
    connection: Connection[object],
    query: AuthorizedKnowledgeQuery,
    vector: str,
    model_id: str,
    model_revision: str,
    maximum_results: int,
) -> tuple[PostgresKnowledgeSearchResult, ...]:
    if not query.visible_concept_ids:
        return ()
    visible = list(query.visible_concept_ids)
    rows = connection.execute(
        """SELECT c.concept_id, c.source_path, b.source_revision,
                  c.content_sha256, h.char_start, h.char_end, h.body,
                  h.embedding <=> %s::vector AS distance
           FROM yap_knowledge_chunks h
           JOIN yap_knowledge_concepts c
             ON c.tenant_id = h.tenant_id
            AND c.generation_sha256 = h.generation_sha256
            AND c.concept_id = h.concept_id
           JOIN yap_knowledge_builds b
             ON b.tenant_id = h.tenant_id
            AND b.generation_sha256 = h.generation_sha256
           WHERE h.tenant_id = %s AND h.generation_sha256 = %s
             AND h.concept_id = ANY(%s)
             AND h.embedding_model_id = %s
             AND h.embedding_model_revision = %s
             AND NOT EXISTS (
                SELECT 1 FROM jsonb_array_elements_text(h.linked_concept_ids) link
                WHERE NOT (link = ANY(%s))
             )
           ORDER BY distance, c.concept_id, h.char_start
           LIMIT %s""",
        (
            vector,
            query.tenant_id,
            query.generation_sha256,
            visible,
            model_id,
            model_revision,
            visible,
            maximum_results,
        ),
    ).fetchall()
    return tuple(_search_result(row, query, vector=float(row[7])) for row in rows)


def _search_result(
    row: tuple[object, ...],
    query: AuthorizedKnowledgeQuery,
    *,
    lexical: float | None = None,
    vector: float | None = None,
) -> PostgresKnowledgeSearchResult:
    score = lexical if lexical is not None else 1.0 - float(vector)
    return PostgresKnowledgeSearchResult(
        concept_id=str(row[0]),
        source_path=str(row[1]),
        source_revision=str(row[2]),
        content_sha256=str(row[3]),
        char_start=int(row[4]),
        char_end=int(row[5]),
        text=str(row[6]),
        generation_sha256=query.generation_sha256,
        permission_hash=query.permission_hash,
        authorization_hash=query.authorization_hash,
        retrieval_score=score,
        lexical_score=lexical,
        vector_distance=vector,
    )


def _search_input(search_text: str, maximum_results: int) -> None:
    if (
        not isinstance(search_text, str)
        or not search_text
        or search_text.strip() != search_text
        or len(search_text) > 1_024
        or not _TOKEN.search(search_text)
    ):
        raise ValueError("knowledge query is invalid")
    _result_limit(maximum_results)


def _result_limit(maximum_results: int) -> None:
    if (
        isinstance(maximum_results, bool)
        or not isinstance(maximum_results, int)
        or not 1 <= maximum_results <= 100
    ):
        raise ValueError("knowledge result limit is invalid")


__all__ = [
    "PostgresKnowledgeSearchResult",
    "list_postgres_knowledge_tree",
    "search_postgres_knowledge_hybrid",
    "search_postgres_knowledge_lexical",
    "search_postgres_knowledge_vector",
]
