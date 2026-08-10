from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from psycopg import Connection
from psycopg.types.json import Jsonb

from .okf_compiler import CompiledKnowledgeGeneration
from .permission_policy import permission_record


@dataclass(frozen=True, slots=True)
class ActiveKnowledgeGeneration:
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
                permission_count integer NOT NULL CHECK (permission_count > 0),
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
                PRIMARY KEY (tenant_id, generation_sha256, concept_id),
                FOREIGN KEY (tenant_id, generation_sha256)
                    REFERENCES yap_knowledge_builds ON DELETE CASCADE,
                FOREIGN KEY (tenant_id, generation_sha256, permission_path_prefix)
                    REFERENCES yap_knowledge_permissions
                    (tenant_id, generation_sha256, path_prefix)
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS yap_knowledge_chunks (
                tenant_id text NOT NULL,
                generation_sha256 text NOT NULL,
                concept_id text NOT NULL,
                chunk_id text NOT NULL,
                body text NOT NULL,
                embedding vector(768),
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


def publish_compiled_generation(
    connection: Connection[object], generation: CompiledKnowledgeGeneration
) -> ActiveKnowledgeGeneration:
    """Stage and atomically activate one already-compiled immutable generation."""

    with connection.transaction():
        connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (generation.tenant_id,),
        )
        connection.execute(
            """INSERT INTO yap_knowledge_builds (
                tenant_id, generation_sha256, source_revision, okf_version,
                concept_count, permission_count
            ) VALUES (%s, %s, %s, %s, %s, %s)""",
            (
                generation.tenant_id,
                generation.generation_sha256,
                generation.source_revision,
                generation.okf_version,
                len(generation.concepts),
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
        for concept in generation.concepts:
            connection.execute(
                """INSERT INTO yap_knowledge_concepts (
                    tenant_id, generation_sha256, concept_id, source_path,
                    content_sha256, permission_path_prefix, frontmatter, body,
                    links, broken_links
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
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
                ),
            )
        counts = connection.execute(
            """SELECT
                (SELECT count(*) FROM yap_knowledge_concepts
                 WHERE tenant_id = %s AND generation_sha256 = %s),
                (SELECT count(*) FROM yap_knowledge_permissions
                 WHERE tenant_id = %s AND generation_sha256 = %s)""",
            (
                generation.tenant_id,
                generation.generation_sha256,
                generation.tenant_id,
                generation.generation_sha256,
            ),
        ).fetchone()
        if counts != (len(generation.concepts), len(generation.permissions)):
            raise RuntimeError("staged knowledge generation is incomplete")
        connection.execute(
            """INSERT INTO yap_knowledge_active_builds
                (tenant_id, generation_sha256)
                VALUES (%s, %s)
                ON CONFLICT (tenant_id) DO UPDATE SET
                    generation_sha256 = EXCLUDED.generation_sha256,
                    activated_at = transaction_timestamp()""",
            (generation.tenant_id, generation.generation_sha256),
        )
    return _descriptor(generation)


def read_active_generation(
    connection: Connection[object], *, tenant_id: str
) -> ActiveKnowledgeGeneration:
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
    return ActiveKnowledgeGeneration(*row)


def _descriptor(generation: CompiledKnowledgeGeneration) -> ActiveKnowledgeGeneration:
    return ActiveKnowledgeGeneration(
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


__all__ = [
    "ActiveKnowledgeGeneration",
    "install_knowledge_schema",
    "publish_compiled_generation",
    "read_active_generation",
]
