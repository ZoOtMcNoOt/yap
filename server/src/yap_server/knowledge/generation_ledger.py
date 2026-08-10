from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import math

from psycopg import Connection
from psycopg.types.json import Jsonb

from .okf_compiler import CompiledKnowledgeGeneration
from .okf_profile import identity
from .permission_policy import permission_record


@dataclass(frozen=True, slots=True)
class KnowledgeGenerationDescriptor:
    tenant_id: str
    generation_sha256: str
    source_revision: str
    okf_version: str
    concept_count: int
    permission_count: int


def install_knowledge_schema(connection: Connection[object]) -> None:
    """Install the durable knowledge-generation schema used by production and tests."""

    with connection.transaction():
        connection.execute("CREATE EXTENSION IF NOT EXISTS vector")
        connection.execute(
            """CREATE TABLE IF NOT EXISTS yap_knowledge_builds (
                tenant_id text NOT NULL,
                generation_sha256 text NOT NULL,
                source_revision text NOT NULL,
                okf_version text NOT NULL,
                concept_count integer NOT NULL CHECK (concept_count >= 0),
                chunk_count integer NOT NULL CHECK (chunk_count >= 0),
                relationship_count integer NOT NULL CHECK (relationship_count >= 0),
                permission_count integer NOT NULL CHECK (permission_count > 0),
                embedding_model_id text,
                embedding_model_revision text,
                created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
                PRIMARY KEY (tenant_id, generation_sha256)
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS yap_knowledge_permissions (
                tenant_id text NOT NULL,
                generation_sha256 text NOT NULL,
                path_prefix text NOT NULL,
                permission_sha256 text NOT NULL,
                policy jsonb NOT NULL,
                PRIMARY KEY (tenant_id, generation_sha256, path_prefix),
                FOREIGN KEY (tenant_id, generation_sha256)
                    REFERENCES yap_knowledge_builds ON DELETE CASCADE
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS yap_knowledge_concepts (
                tenant_id text NOT NULL,
                generation_sha256 text NOT NULL,
                concept_id text NOT NULL,
                source_path text NOT NULL,
                content_sha256 text NOT NULL,
                permission_path_prefix text NOT NULL,
                frontmatter jsonb NOT NULL,
                body text NOT NULL,
                links jsonb NOT NULL,
                broken_links jsonb NOT NULL,
                redirect_history jsonb NOT NULL,
                PRIMARY KEY (tenant_id, generation_sha256, concept_id),
                FOREIGN KEY (tenant_id, generation_sha256)
                    REFERENCES yap_knowledge_builds ON DELETE CASCADE,
                FOREIGN KEY (tenant_id, generation_sha256, permission_path_prefix)
                    REFERENCES yap_knowledge_permissions
                    (tenant_id, generation_sha256, path_prefix)
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS yap_knowledge_permission_audience (
                tenant_id text NOT NULL,
                generation_sha256 text NOT NULL,
                path_prefix text NOT NULL,
                subject_id text NOT NULL,
                PRIMARY KEY
                    (tenant_id, generation_sha256, path_prefix, subject_id),
                FOREIGN KEY (tenant_id, generation_sha256, path_prefix)
                    REFERENCES yap_knowledge_permissions
                    (tenant_id, generation_sha256, path_prefix) ON DELETE CASCADE
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS yap_knowledge_permission_denials (
                tenant_id text NOT NULL,
                generation_sha256 text NOT NULL,
                path_prefix text NOT NULL,
                subject_id text NOT NULL,
                PRIMARY KEY
                    (tenant_id, generation_sha256, path_prefix, subject_id),
                FOREIGN KEY (tenant_id, generation_sha256, path_prefix)
                    REFERENCES yap_knowledge_permissions
                    (tenant_id, generation_sha256, path_prefix) ON DELETE CASCADE
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS yap_knowledge_permission_purposes (
                tenant_id text NOT NULL,
                generation_sha256 text NOT NULL,
                path_prefix text NOT NULL,
                purpose text NOT NULL,
                PRIMARY KEY (tenant_id, generation_sha256, path_prefix, purpose),
                FOREIGN KEY (tenant_id, generation_sha256, path_prefix)
                    REFERENCES yap_knowledge_permissions
                    (tenant_id, generation_sha256, path_prefix) ON DELETE CASCADE
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS yap_knowledge_relationships (
                tenant_id text NOT NULL,
                generation_sha256 text NOT NULL,
                relationship_id text NOT NULL,
                source_concept_id text NOT NULL,
                target_concept_id text NOT NULL,
                relationship_type text NOT NULL,
                authority text NOT NULL,
                source_char_start integer,
                source_char_end integer,
                canonical boolean NOT NULL,
                PRIMARY KEY (tenant_id, generation_sha256, relationship_id),
                FOREIGN KEY (tenant_id, generation_sha256, source_concept_id)
                    REFERENCES yap_knowledge_concepts
                    (tenant_id, generation_sha256, concept_id) ON DELETE CASCADE
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS yap_knowledge_chunks (
                tenant_id text NOT NULL,
                generation_sha256 text NOT NULL,
                concept_id text NOT NULL,
                chunk_id text NOT NULL,
                permission_sha256 text NOT NULL,
                char_start integer NOT NULL CHECK (char_start >= 0),
                char_end integer NOT NULL CHECK (char_end >= char_start),
                body text NOT NULL,
                linked_concept_ids jsonb NOT NULL,
                embedding vector(768),
                embedding_model_id text,
                embedding_model_revision text,
                PRIMARY KEY (tenant_id, generation_sha256, chunk_id),
                FOREIGN KEY (tenant_id, generation_sha256, concept_id)
                    REFERENCES yap_knowledge_concepts
                    (tenant_id, generation_sha256, concept_id) ON DELETE CASCADE
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS yap_knowledge_active_builds (
                tenant_id text PRIMARY KEY,
                generation_sha256 text NOT NULL,
                activated_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
                FOREIGN KEY (tenant_id, generation_sha256)
                    REFERENCES yap_knowledge_builds
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS yap_knowledge_activation_history (
                activation_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                tenant_id text NOT NULL,
                generation_sha256 text NOT NULL,
                previous_generation_sha256 text,
                reason text NOT NULL CHECK (reason IN ('publish', 'rollback')),
                activated_at timestamptz NOT NULL DEFAULT transaction_timestamp()
            )"""
        )


def stage_compiled_generation(
    connection: Connection[object], generation: CompiledKnowledgeGeneration
) -> KnowledgeGenerationDescriptor:
    """Stage one immutable generation without making it queryable."""

    with connection.transaction():
        connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (generation.tenant_id,),
        )
        connection.execute(
            """INSERT INTO yap_knowledge_builds (
                tenant_id, generation_sha256, source_revision, okf_version,
                concept_count, chunk_count, relationship_count, permission_count
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                generation.tenant_id,
                generation.generation_sha256,
                generation.source_revision,
                generation.okf_version,
                len(generation.concepts),
                len(generation.chunks),
                len(generation.relationships),
                len(generation.permissions),
            ),
        )
        for permission in generation.permissions:
            connection.execute(
                """INSERT INTO yap_knowledge_permissions (
                    tenant_id, generation_sha256, path_prefix,
                    permission_sha256, policy
                ) VALUES (%s, %s, %s, %s, %s)""",
                (
                    generation.tenant_id,
                    generation.generation_sha256,
                    permission.path_prefix,
                    permission.permission_sha256,
                    Jsonb(permission_record(permission)),
                ),
            )
            for principal in permission.audience:
                connection.execute(
                    """INSERT INTO yap_knowledge_permission_audience
                        (tenant_id, generation_sha256, path_prefix, subject_id)
                        VALUES (%s, %s, %s, %s)""",
                    (
                        generation.tenant_id,
                        generation.generation_sha256,
                        permission.path_prefix,
                        principal.subject_id,
                    ),
                )
            for principal in permission.denials:
                connection.execute(
                    """INSERT INTO yap_knowledge_permission_denials
                        (tenant_id, generation_sha256, path_prefix, subject_id)
                        VALUES (%s, %s, %s, %s)""",
                    (
                        generation.tenant_id,
                        generation.generation_sha256,
                        permission.path_prefix,
                        principal.subject_id,
                    ),
                )
            for purpose in permission.purposes:
                connection.execute(
                    """INSERT INTO yap_knowledge_permission_purposes
                        (tenant_id, generation_sha256, path_prefix, purpose)
                        VALUES (%s, %s, %s, %s)""",
                    (
                        generation.tenant_id,
                        generation.generation_sha256,
                        permission.path_prefix,
                        purpose,
                    ),
                )
        for concept in generation.concepts:
            connection.execute(
                """INSERT INTO yap_knowledge_concepts (
                    tenant_id, generation_sha256, concept_id, source_path,
                    content_sha256, permission_path_prefix, frontmatter, body,
                    links, broken_links, redirect_history
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    generation.tenant_id,
                    generation.generation_sha256,
                    concept.concept_id,
                    concept.source_path,
                    concept.content_sha256,
                    concept.permission_path_prefix,
                    Jsonb(_json_value(concept.frontmatter)),
                    concept.body,
                    Jsonb(list(concept.links)),
                    Jsonb(list(concept.broken_links)),
                    Jsonb(list(concept.redirect_history)),
                ),
            )
        for chunk in generation.chunks:
            connection.execute(
                """INSERT INTO yap_knowledge_chunks (
                    tenant_id, generation_sha256, concept_id, chunk_id,
                    permission_sha256, char_start, char_end, body,
                    linked_concept_ids
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    generation.tenant_id,
                    generation.generation_sha256,
                    chunk.concept_id,
                    chunk.chunk_id,
                    chunk.permission_sha256,
                    chunk.char_start,
                    chunk.char_end,
                    chunk.text,
                    Jsonb(list(chunk.linked_concept_ids)),
                ),
            )
        for relationship in generation.relationships:
            connection.execute(
                """INSERT INTO yap_knowledge_relationships (
                    tenant_id, generation_sha256, relationship_id,
                    source_concept_id, target_concept_id, relationship_type,
                    authority, source_char_start, source_char_end, canonical
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    generation.tenant_id,
                    generation.generation_sha256,
                    relationship.relationship_id,
                    relationship.source_concept_id,
                    relationship.target_concept_id,
                    relationship.relationship_type,
                    relationship.authority,
                    relationship.source_char_start,
                    relationship.source_char_end,
                    relationship.canonical,
                ),
            )
        counts = connection.execute(
            """SELECT
                (SELECT count(*) FROM yap_knowledge_concepts
                 WHERE tenant_id = %s AND generation_sha256 = %s),
                (SELECT count(*) FROM yap_knowledge_chunks
                 WHERE tenant_id = %s AND generation_sha256 = %s),
                (SELECT count(*) FROM yap_knowledge_relationships
                 WHERE tenant_id = %s AND generation_sha256 = %s),
                (SELECT count(*) FROM yap_knowledge_permissions
                 WHERE tenant_id = %s AND generation_sha256 = %s)""",
            (
                generation.tenant_id,
                generation.generation_sha256,
                generation.tenant_id,
                generation.generation_sha256,
                generation.tenant_id,
                generation.generation_sha256,
                generation.tenant_id,
                generation.generation_sha256,
            ),
        ).fetchone()
        if counts != (
            len(generation.concepts),
            len(generation.chunks),
            len(generation.relationships),
            len(generation.permissions),
        ):
            raise RuntimeError("staged knowledge generation is incomplete")
    return _descriptor(generation)


def store_generation_embeddings(
    connection: Connection[object],
    *,
    tenant_id: str,
    generation_sha256: str,
    embedding_model_id: str,
    embedding_model_revision: str,
    embeddings: Mapping[str, tuple[float, ...]],
) -> None:
    """Store one complete, model-bound vector projection on a staged generation."""

    model_id = identity(embedding_model_id, "embedding_model_id")
    model_revision = identity(embedding_model_revision, "embedding_model_revision")
    expected = frozenset(
        row[0]
        for row in connection.execute(
            """SELECT chunk_id FROM yap_knowledge_chunks
               WHERE tenant_id = %s AND generation_sha256 = %s""",
            (tenant_id, generation_sha256),
        ).fetchall()
    )
    if frozenset(embeddings) != expected:
        raise ValueError("embedding projection differs from staged chunks")
    prepared = {
        chunk_id: serialize_embedding_vector(vector)
        for chunk_id, vector in embeddings.items()
    }
    with connection.transaction():
        connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (tenant_id,),
        )
        active = connection.execute(
            """SELECT 1 FROM yap_knowledge_active_builds
               WHERE tenant_id = %s AND generation_sha256 = %s""",
            (tenant_id, generation_sha256),
        ).fetchone()
        if active is not None:
            raise ValueError("active knowledge generation is immutable")
        for chunk_id, vector in prepared.items():
            connection.execute(
                """UPDATE yap_knowledge_chunks
                   SET embedding = %s::vector,
                       embedding_model_id = %s,
                       embedding_model_revision = %s
                   WHERE tenant_id = %s AND generation_sha256 = %s
                     AND chunk_id = %s""",
                (
                    vector,
                    model_id,
                    model_revision,
                    tenant_id,
                    generation_sha256,
                    chunk_id,
                ),
            )
        connection.execute(
            """UPDATE yap_knowledge_builds
               SET embedding_model_id = %s, embedding_model_revision = %s
               WHERE tenant_id = %s AND generation_sha256 = %s
                 AND embedding_model_id IS NULL
                 AND embedding_model_revision IS NULL""",
            (model_id, model_revision, tenant_id, generation_sha256),
        )
        build_identity = connection.execute(
            """SELECT embedding_model_id, embedding_model_revision
               FROM yap_knowledge_builds
               WHERE tenant_id = %s AND generation_sha256 = %s""",
            (tenant_id, generation_sha256),
        ).fetchone()
        if build_identity != (model_id, model_revision):
            raise ValueError("knowledge generation embedding identity is immutable")


def activate_complete_generation(
    connection: Connection[object],
    *,
    tenant_id: str,
    generation_sha256: str,
) -> KnowledgeGenerationDescriptor:
    """Atomically expose a complete relational and vector generation."""

    return _activate_complete_generation(
        connection,
        tenant_id=tenant_id,
        generation_sha256=generation_sha256,
        reason="publish",
    )


def rollback_to_generation(
    connection: Connection[object],
    *,
    tenant_id: str,
    generation_sha256: str,
) -> KnowledgeGenerationDescriptor:
    """Atomically restore one retained, fully validated generation."""

    return _activate_complete_generation(
        connection,
        tenant_id=tenant_id,
        generation_sha256=generation_sha256,
        reason="rollback",
    )


def _activate_complete_generation(
    connection: Connection[object],
    *,
    tenant_id: str,
    generation_sha256: str,
    reason: str,
) -> KnowledgeGenerationDescriptor:

    with connection.transaction():
        connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (tenant_id,)
        )
        row = connection.execute(
            """SELECT tenant_id, generation_sha256, source_revision,
                      okf_version, concept_count, permission_count,
                      chunk_count, relationship_count,
                      embedding_model_id, embedding_model_revision
               FROM yap_knowledge_builds
               WHERE tenant_id = %s AND generation_sha256 = %s""",
            (tenant_id, generation_sha256),
        ).fetchone()
        if row is None:
            raise LookupError("staged knowledge generation does not exist")
        if row[8] is None or row[9] is None:
            raise ValueError("staged knowledge embedding projection is absent")
        actual = connection.execute(
            """SELECT
                (SELECT count(*) FROM yap_knowledge_concepts
                 WHERE tenant_id = %s AND generation_sha256 = %s),
                (SELECT count(*) FROM yap_knowledge_permissions
                 WHERE tenant_id = %s AND generation_sha256 = %s),
                (SELECT count(*) FROM yap_knowledge_chunks
                 WHERE tenant_id = %s AND generation_sha256 = %s),
                (SELECT count(*) FROM yap_knowledge_relationships
                 WHERE tenant_id = %s AND generation_sha256 = %s),
                (SELECT count(*) FROM yap_knowledge_chunks
                 WHERE tenant_id = %s AND generation_sha256 = %s
                   AND embedding IS NOT NULL
                   AND embedding_model_id = %s
                   AND embedding_model_revision = %s)""",
            (
                tenant_id,
                generation_sha256,
                tenant_id,
                generation_sha256,
                tenant_id,
                generation_sha256,
                tenant_id,
                generation_sha256,
                tenant_id,
                generation_sha256,
                row[8],
                row[9],
            ),
        ).fetchone()
        expected = (row[4], row[5], row[6], row[7], row[6])
        if actual != expected:
            raise ValueError("staged knowledge projections are incomplete")
        previous = connection.execute(
            """SELECT generation_sha256 FROM yap_knowledge_active_builds
               WHERE tenant_id = %s""",
            (tenant_id,),
        ).fetchone()
        previous_sha256 = None if previous is None else str(previous[0])
        connection.execute(
            """INSERT INTO yap_knowledge_active_builds
                (tenant_id, generation_sha256)
                VALUES (%s, %s)
                ON CONFLICT (tenant_id) DO UPDATE SET
                    generation_sha256 = EXCLUDED.generation_sha256,
                    activated_at = transaction_timestamp()""",
            (tenant_id, generation_sha256),
        )
        connection.execute(
            """INSERT INTO yap_knowledge_activation_history (
                   tenant_id, generation_sha256, previous_generation_sha256, reason
               ) VALUES (%s, %s, %s, %s)""",
            (tenant_id, generation_sha256, previous_sha256, reason),
        )
    return KnowledgeGenerationDescriptor(*row[:6])


def prune_inactive_generations(
    connection: Connection[object], *, tenant_id: str, retain: int
) -> tuple[str, ...]:
    """Delete oldest inactive generations while retaining a bounded recent set."""

    if isinstance(retain, bool) or not isinstance(retain, int) or retain < 0:
        raise ValueError("knowledge generation retention bound is invalid")
    with connection.transaction():
        connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (tenant_id,)
        )
        rows = connection.execute(
            """SELECT b.generation_sha256
               FROM yap_knowledge_builds b
               LEFT JOIN yap_knowledge_active_builds a
                 ON a.tenant_id = b.tenant_id
                AND a.generation_sha256 = b.generation_sha256
               WHERE b.tenant_id = %s AND a.generation_sha256 IS NULL
               ORDER BY b.created_at DESC, b.generation_sha256 DESC
               OFFSET %s""",
            (tenant_id, retain),
        ).fetchall()
        removed = tuple(str(row[0]) for row in rows)
        if removed:
            connection.execute(
                """DELETE FROM yap_knowledge_builds
                   WHERE tenant_id = %s AND generation_sha256 = ANY(%s)""",
                (tenant_id, list(removed)),
            )
    return removed


def read_active_generation(
    connection: Connection[object], *, tenant_id: str
) -> KnowledgeGenerationDescriptor:
    row = connection.execute(
        """SELECT b.tenant_id, b.generation_sha256, b.source_revision,
                  b.okf_version, b.concept_count, b.permission_count
           FROM yap_knowledge_active_builds a
           JOIN yap_knowledge_builds b
             ON b.tenant_id = a.tenant_id
            AND b.generation_sha256 = a.generation_sha256
           WHERE a.tenant_id = %s""",
        (tenant_id,),
    ).fetchone()
    if row is None:
        raise LookupError("tenant has no active knowledge generation")
    return KnowledgeGenerationDescriptor(*row)


def _descriptor(
    generation: CompiledKnowledgeGeneration,
) -> KnowledgeGenerationDescriptor:
    return KnowledgeGenerationDescriptor(
        tenant_id=generation.tenant_id,
        generation_sha256=generation.generation_sha256,
        source_revision=generation.source_revision,
        okf_version=generation.okf_version,
        concept_count=len(generation.concepts),
        permission_count=len(generation.permissions),
    )


def _json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    return value


def serialize_embedding_vector(value: tuple[float, ...]) -> str:
    if not isinstance(value, tuple) or len(value) != 768:
        raise ValueError("knowledge embedding dimensions are invalid")
    numbers: list[str] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise ValueError("knowledge embedding value is invalid")
        number = float(item)
        if not math.isfinite(number):
            raise ValueError("knowledge embedding value is invalid")
        numbers.append(format(number, ".9g"))
    return "[" + ",".join(numbers) + "]"


__all__ = [
    "KnowledgeGenerationDescriptor",
    "activate_complete_generation",
    "install_knowledge_schema",
    "read_active_generation",
    "prune_inactive_generations",
    "rollback_to_generation",
    "serialize_embedding_vector",
    "stage_compiled_generation",
    "store_generation_embeddings",
]
