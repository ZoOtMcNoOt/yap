from __future__ import annotations

import json
import sqlite3
from typing import Literal, Sequence
from uuid import uuid4

from yap_server.auth.authorization_audit import (
    append_audit_event,
    create_audit_schema,
)
from yap_server.auth.identity_records import (
    PrincipalRecord,
    Purpose,
    PurposeGrantMetadata,
)
from yap_server.auth.principal import PrincipalKey


SCHEMA_VERSION = 2


def create_identity_schema(connection: sqlite3.Connection) -> None:
    connection.execute("BEGIN IMMEDIATE")
    try:
        _create_identity_schema(connection)
    except BaseException:
        connection.rollback()
        raise
    else:
        connection.commit()


def _create_identity_schema(connection: sqlite3.Connection) -> None:
    user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if user_version not in {0, 1, SCHEMA_VERSION}:
        raise ValueError("identity repository schema is unsupported")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS principal_identity (
            tenant_id TEXT NOT NULL,
            subject_id TEXT NOT NULL,
            display_name_snapshot TEXT,
            created_at_utc TEXT NOT NULL,
            last_seen_at_utc TEXT NOT NULL,
            access_revoked_after_unix INTEGER NOT NULL DEFAULT 0,
            access_disabled INTEGER NOT NULL DEFAULT 0
                CHECK (access_disabled IN (0, 1)),
            PRIMARY KEY (tenant_id, subject_id)
        )
        """
    )
    if user_version == 1:
        connection.execute(
            """
            ALTER TABLE principal_identity
            ADD COLUMN access_disabled INTEGER NOT NULL DEFAULT 0
                CHECK (access_disabled IN (0, 1))
            """
        )
        connection.execute(
            """
            UPDATE principal_identity
            SET access_disabled = 1
            WHERE access_revoked_after_unix > 0
            """
        )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS purpose_grant_revision (
            tenant_id TEXT NOT NULL,
            subject_id TEXT NOT NULL,
            purpose TEXT NOT NULL,
            epoch INTEGER NOT NULL,
            state TEXT NOT NULL,
            grant_id TEXT NOT NULL,
            legal_basis_code TEXT NOT NULL,
            privacy_assessment_ref TEXT NOT NULL,
            notice_version TEXT NOT NULL,
            changed_at_utc TEXT NOT NULL,
            actor_tenant_id TEXT NOT NULL,
            actor_subject_id TEXT NOT NULL,
            PRIMARY KEY (tenant_id, subject_id, purpose, epoch),
            FOREIGN KEY (tenant_id, subject_id)
                REFERENCES principal_identity (tenant_id, subject_id)
        )
        """
    )
    create_audit_schema(connection)
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def principal_row(
    connection: sqlite3.Connection,
    key: PrincipalKey,
) -> tuple[object, ...] | None:
    return connection.execute(
        """
        SELECT
            tenant_id,
            subject_id,
            display_name_snapshot,
            created_at_utc,
            last_seen_at_utc,
            access_revoked_after_unix,
            access_disabled
        FROM principal_identity
        WHERE tenant_id = ? AND subject_id = ?
        """,
        (key.tenant_id, key.subject_id),
    ).fetchone()


def principal_record(row: tuple[object, ...]) -> PrincipalRecord:
    return PrincipalRecord(
        key=PrincipalKey(str(row[0]), str(row[1])),
        display_name_snapshot=None if row[2] is None else str(row[2]),
        created_at_utc=str(row[3]),
        last_seen_at_utc=str(row[4]),
        access_revoked_after_unix=int(row[5]),
        access_disabled=bool(row[6]),
    )


def require_principal(
    connection: sqlite3.Connection,
    key: PrincipalKey,
) -> tuple[object, ...]:
    row = principal_row(connection, key)
    if row is None:
        raise KeyError("principal not found")
    return row


def next_purpose_epoch(
    connection: sqlite3.Connection,
    target: PrincipalKey,
    purpose: Purpose,
) -> int:
    row = connection.execute(
        """
        SELECT MAX(epoch)
        FROM purpose_grant_revision
        WHERE tenant_id = ? AND subject_id = ? AND purpose = ?
        """,
        (target.tenant_id, target.subject_id, purpose),
    ).fetchone()
    return 1 if row is None or row[0] is None else int(row[0]) + 1


def latest_purpose(
    connection: sqlite3.Connection,
    target: PrincipalKey,
    purpose: Purpose,
) -> tuple[object, ...] | None:
    return connection.execute(
        """
        SELECT
            epoch,
            state,
            grant_id,
            legal_basis_code,
            privacy_assessment_ref,
            notice_version
        FROM purpose_grant_revision
        WHERE tenant_id = ? AND subject_id = ? AND purpose = ?
        ORDER BY epoch DESC
        LIMIT 1
        """,
        (target.tenant_id, target.subject_id, purpose),
    ).fetchone()


def insert_purpose_revision(
    connection: sqlite3.Connection,
    actor: PrincipalKey,
    target: PrincipalKey,
    *,
    purpose: Purpose,
    epoch: int,
    state: Literal["granted", "revoked"],
    metadata: PurposeGrantMetadata,
    occurred_at_utc: str,
) -> None:
    connection.execute(
        """
        INSERT INTO purpose_grant_revision (
            tenant_id,
            subject_id,
            purpose,
            epoch,
            state,
            grant_id,
            legal_basis_code,
            privacy_assessment_ref,
            notice_version,
            changed_at_utc,
            actor_tenant_id,
            actor_subject_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            target.tenant_id,
            target.subject_id,
            purpose,
            epoch,
            state,
            metadata.grant_id,
            metadata.legal_basis_code,
            metadata.privacy_assessment_ref,
            metadata.notice_version,
            occurred_at_utc,
            actor.tenant_id,
            actor.subject_id,
        ),
    )


def append_identity_audit(
    connection: sqlite3.Connection,
    *,
    actor: PrincipalKey,
    target: PrincipalKey,
    action: str,
    outcome: str,
    occurred_at_utc: str,
    epoch: int,
    purpose: Purpose | None = None,
    required_purposes: Sequence[Purpose] = (),
    reason: str | None = None,
    operation_id: str | None = None,
) -> None:
    event: dict[str, object] = {
        "schemaVersion": 1,
        "eventId": str(uuid4()),
        "occurredAtUtc": occurred_at_utc,
        "actor": {
            "tenantId": actor.tenant_id,
            "subjectId": actor.subject_id,
        },
        "target": {
            "tenantId": target.tenant_id,
            "subjectId": target.subject_id,
        },
        "action": action,
        "outcome": outcome,
        "purpose": purpose,
        "epoch": epoch,
    }
    if required_purposes:
        event["requiredPurposes"] = list(required_purposes)
    if reason is not None:
        event["reason"] = reason
    if operation_id is not None:
        event["operationId"] = operation_id
    append_audit_event(
        connection,
        event,
    )


def audit_events(connection: sqlite3.Connection) -> list[dict[str, object]]:
    rows = connection.execute(
        """
        SELECT event_json
        FROM authorization_audit
        ORDER BY sequence
        """
    ).fetchall()
    return [json.loads(row[0]) for row in rows]
