from __future__ import annotations

from dataclasses import dataclass, replace
import re

from psycopg import Connection

from yap_server.auth.principal import PrincipalKey

from .generation_ledger import serialize_embedding_vector
from .knowledge_tool_contract import (
    MAX_STORAGE_RESULTS,
    MAX_CONCEPT_ID_CHARACTERS,
    validate_bounded_text,
    validate_integer,
    validate_search_text,
)
from .postgres_permission_view import (
    AuthorizedKnowledgeQuery,
    _authorize_knowledge_query,
)


_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)


@dataclass(frozen=True, slots=True)
class PostgresKnowledgeConcept:
    concept_id: str
    type: str
    title: str
    resource: str


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


@dataclass(frozen=True, slots=True)
class PostgresKnowledgeTree:
    generation_sha256: str
    permission_hash: str
    authorization_hash: str
    concepts: tuple[PostgresKnowledgeConcept, ...]


@dataclass(frozen=True, slots=True)
class PostgresKnowledgeSearch:
    generation_sha256: str
    permission_hash: str
    authorization_hash: str
    results: tuple[PostgresKnowledgeSearchResult, ...]


@dataclass(frozen=True, slots=True)
class PostgresKnowledgeEvidenceItem:
    concept_id: str
    source_revision: str
    content_sha256: str
    char_start: int
    char_end: int
    text: str


@dataclass(frozen=True, slots=True)
class PostgresKnowledgeConceptEvidence:
    generation_sha256: str
    permission_hash: str
    authorization_hash: str
    concept_id: str
    items: tuple[PostgresKnowledgeEvidenceItem, ...]
    output_budget_exhausted: bool


def read_postgres_knowledge_concept_evidence(
    connection: Connection[object],
    *,
    principal: PrincipalKey,
    purpose: str,
    agent_capabilities: frozenset[str],
    concept_id: str,
    maximum_items: int = 10,
    maximum_characters: int = 8_192,
    expected_generation_sha256: str | None = None,
) -> PostgresKnowledgeConceptEvidence:
    """Read bounded visible chunks for one exact concept and active generation."""

    validate_bounded_text(
        concept_id,
        field="knowledge evidence concept",
        maximum=MAX_CONCEPT_ID_CHARACTERS,
    )
    validate_integer(
        maximum_items,
        minimum=1,
        maximum=MAX_STORAGE_RESULTS,
        field="knowledge evidence item limit",
    )
    validate_integer(
        maximum_characters,
        minimum=1,
        maximum=1_000_000,
        field="knowledge evidence character limit",
    )
    with connection.transaction():
        query = _authorize_knowledge_query(
            connection,
            principal=principal,
            purpose=purpose,
            agent_capabilities=agent_capabilities,
            required_capability="knowledge.search.lexical",
            expected_generation_sha256=expected_generation_sha256,
        )
        if concept_id not in query.visible_concept_ids:
            return PostgresKnowledgeConceptEvidence(
                query.generation_sha256,
                query.permission_hash,
                query.authorization_hash,
                concept_id,
                (),
                False,
            )
        rows = connection.execute(
            """SELECT c.concept_id, b.source_revision, c.content_sha256,
                      h.char_start, h.char_end, h.body
               FROM yap_knowledge_chunks h
               JOIN yap_knowledge_concepts c
                 ON c.tenant_id = h.tenant_id
                AND c.generation_sha256 = h.generation_sha256
                AND c.concept_id = h.concept_id
               JOIN yap_knowledge_builds b
                 ON b.tenant_id = h.tenant_id
                AND b.generation_sha256 = h.generation_sha256
               WHERE h.tenant_id = %s AND h.generation_sha256 = %s
                 AND h.concept_id = %s
                 AND NOT EXISTS (
                    SELECT 1
                    FROM jsonb_array_elements_text(h.linked_concept_ids) link
                    WHERE NOT (link = ANY(%s))
                 )
               ORDER BY h.char_start, h.chunk_id
               LIMIT %s""",
            (
                query.tenant_id,
                query.generation_sha256,
                concept_id,
                list(query.visible_concept_ids),
                maximum_items + 1,
            ),
        ).fetchall()
        output: list[PostgresKnowledgeEvidenceItem] = []
        used = 0
        exhausted = len(rows) > maximum_items
        for row in rows[:maximum_items]:
            item = PostgresKnowledgeEvidenceItem(
                concept_id=str(row[0]),
                source_revision=str(row[1]),
                content_sha256=str(row[2]),
                char_start=int(row[3]),
                char_end=int(row[4]),
                text=str(row[5]),
            )
            size = sum(
                len(value)
                for value in (
                    item.concept_id,
                    item.source_revision,
                    item.content_sha256,
                    item.text,
                )
            )
            if used + size > maximum_characters:
                exhausted = True
                break
            used += size
            output.append(item)
        return PostgresKnowledgeConceptEvidence(
            query.generation_sha256,
            query.permission_hash,
            query.authorization_hash,
            concept_id,
            tuple(output),
            exhausted,
        )


def list_postgres_knowledge_tree(
    connection: Connection[object],
    *,
    principal: PrincipalKey,
    purpose: str,
    agent_capabilities: frozenset[str],
    expected_generation_sha256: str | None = None,
) -> PostgresKnowledgeTree:
    with connection.transaction():
        return _list_postgres_knowledge_tree(
            connection,
            principal=principal,
            purpose=purpose,
            agent_capabilities=agent_capabilities,
            expected_generation_sha256=expected_generation_sha256,
        )


def _list_postgres_knowledge_tree(
    connection: Connection[object],
    *,
    principal: PrincipalKey,
    purpose: str,
    agent_capabilities: frozenset[str],
    expected_generation_sha256: str | None,
) -> PostgresKnowledgeTree:
    query = _authorize_knowledge_query(
        connection,
        principal=principal,
        purpose=purpose,
        agent_capabilities=agent_capabilities,
        required_capability="knowledge.tree",
        expected_generation_sha256=expected_generation_sha256,
    )
    if not query.visible_concept_ids:
        return PostgresKnowledgeTree(
            query.generation_sha256,
            query.permission_hash,
            query.authorization_hash,
            (),
        )
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
    return PostgresKnowledgeTree(
        query.generation_sha256,
        query.permission_hash,
        query.authorization_hash,
        tuple(PostgresKnowledgeConcept(*row) for row in rows),
    )


def search_postgres_knowledge_lexical(
    connection: Connection[object],
    *,
    principal: PrincipalKey,
    purpose: str,
    agent_capabilities: frozenset[str],
    search_text: str,
    maximum_results: int = 10,
    expected_generation_sha256: str | None = None,
) -> PostgresKnowledgeSearch:
    with connection.transaction():
        _search_input(search_text, maximum_results)
        query = _authorize_knowledge_query(
            connection,
            principal=principal,
            purpose=purpose,
            agent_capabilities=agent_capabilities,
            required_capability="knowledge.search.lexical",
            expected_generation_sha256=expected_generation_sha256,
        )
        return _search_response(
            query, _lexical_results(connection, query, search_text, maximum_results)
        )


def search_postgres_knowledge_vector(
    connection: Connection[object],
    *,
    principal: PrincipalKey,
    purpose: str,
    agent_capabilities: frozenset[str],
    query_embedding: tuple[float, ...],
    maximum_results: int = 10,
    expected_generation_sha256: str | None = None,
) -> PostgresKnowledgeSearch:
    with connection.transaction():
        _result_limit(maximum_results)
        vector = serialize_embedding_vector(query_embedding)
        query = _authorize_knowledge_query(
            connection,
            principal=principal,
            purpose=purpose,
            agent_capabilities=agent_capabilities,
            required_capability="knowledge.search.vector",
            expected_generation_sha256=expected_generation_sha256,
        )
        return _search_response(
            query,
            _vector_results(
                connection,
                query,
                vector,
                maximum_results,
            ),
        )


def search_postgres_knowledge_hybrid(
    connection: Connection[object],
    *,
    principal: PrincipalKey,
    purpose: str,
    agent_capabilities: frozenset[str],
    search_text: str,
    query_embedding: tuple[float, ...],
    maximum_results: int = 10,
    expected_generation_sha256: str | None = None,
) -> PostgresKnowledgeSearch:
    with connection.transaction():
        return _search_postgres_knowledge_hybrid(
            connection,
            principal=principal,
            purpose=purpose,
            agent_capabilities=agent_capabilities,
            search_text=search_text,
            query_embedding=query_embedding,
            maximum_results=maximum_results,
            expected_generation_sha256=expected_generation_sha256,
        )


def _search_postgres_knowledge_hybrid(
    connection: Connection[object],
    *,
    principal: PrincipalKey,
    purpose: str,
    agent_capabilities: frozenset[str],
    search_text: str,
    query_embedding: tuple[float, ...],
    maximum_results: int,
    expected_generation_sha256: str | None,
) -> PostgresKnowledgeSearch:
    _search_input(search_text, maximum_results)
    vector = serialize_embedding_vector(query_embedding)
    query = _authorize_knowledge_query(
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
    return _search_response(
        query,
        tuple(replace(ranked[key], retrieval_score=scores[key]) for key in ordered),
    )


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
             AND h.embedding IS NOT NULL
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


def _search_response(
    query: AuthorizedKnowledgeQuery,
    results: tuple[PostgresKnowledgeSearchResult, ...],
) -> PostgresKnowledgeSearch:
    return PostgresKnowledgeSearch(
        query.generation_sha256,
        query.permission_hash,
        query.authorization_hash,
        results,
    )


def _search_input(search_text: str, maximum_results: int) -> None:
    validate_search_text(search_text)
    _result_limit(maximum_results)


def _result_limit(maximum_results: int) -> None:
    validate_integer(
        maximum_results,
        minimum=1,
        maximum=MAX_STORAGE_RESULTS,
        field="knowledge result limit",
    )


__all__ = [
    "PostgresKnowledgeConceptEvidence",
    "PostgresKnowledgeConcept",
    "PostgresKnowledgeEvidenceItem",
    "PostgresKnowledgeSearchResult",
    "PostgresKnowledgeSearch",
    "PostgresKnowledgeTree",
    "list_postgres_knowledge_tree",
    "read_postgres_knowledge_concept_evidence",
    "search_postgres_knowledge_hybrid",
    "search_postgres_knowledge_lexical",
    "search_postgres_knowledge_vector",
]
