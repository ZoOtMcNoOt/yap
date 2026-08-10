from __future__ import annotations

from datetime import datetime, timezone

from psycopg import Connection

from yap_server.auth.principal import PrincipalKey


def install_knowledge_tool_audit_schema(connection: Connection[object]) -> None:
    with connection.transaction():
        connection.execute(
            """CREATE TABLE IF NOT EXISTS yap_knowledge_tool_audit (
                audit_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                tenant_id text NOT NULL,
                subject_id text NOT NULL,
                agent_id text NOT NULL,
                operation text NOT NULL,
                outcome text NOT NULL,
                result_count integer NOT NULL CHECK (result_count >= 0),
                generation_sha256 text,
                permission_hash text,
                authorization_hash text,
                duration_milliseconds integer NOT NULL CHECK (duration_milliseconds >= 0),
                created_at timestamptz NOT NULL
            )"""
        )


def record_knowledge_tool_audit(
    connection: Connection[object],
    *,
    principal: PrincipalKey,
    agent_id: str,
    operation: str,
    outcome: str,
    result_count: int,
    generation_sha256: str | None,
    permission_hash: str | None,
    authorization_hash: str | None,
    duration_milliseconds: int,
) -> None:
    connection.execute(
        """INSERT INTO yap_knowledge_tool_audit (
            tenant_id, subject_id, agent_id, operation, outcome, result_count,
            generation_sha256, permission_hash, authorization_hash,
            duration_milliseconds, created_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (
            principal.tenant_id,
            principal.subject_id,
            agent_id,
            operation,
            outcome,
            result_count,
            generation_sha256,
            permission_hash,
            authorization_hash,
            duration_milliseconds,
            datetime.now(timezone.utc),
        ),
    )


__all__ = ["install_knowledge_tool_audit_schema", "record_knowledge_tool_audit"]
