from __future__ import annotations

import hashlib
import json

from psycopg import Connection
from psycopg.types.json import Jsonb

from yap_server.auth.principal import PrincipalKey

from .terminology_snapshot import (
    TerminologyRecord,
    TerminologySnapshot,
    freeze_terminology_snapshot,
    restore_terminology_snapshot,
    terminology_snapshot_payload,
    validate_terminology_record,
)


def install_terminology_schema(connection: Connection[object]) -> None:
    with connection.transaction():
        connection.execute(
            """CREATE TABLE IF NOT EXISTS yap_terminology_records (
                tenant_id text NOT NULL,
                record_id text NOT NULL,
                version bigint NOT NULL CHECK (version > 0),
                scope text NOT NULL,
                owner_id text NOT NULL,
                locale text NOT NULL,
                canonical_form text NOT NULL,
                variants jsonb NOT NULL,
                sensitivity text NOT NULL,
                deleted boolean NOT NULL,
                audit_revision text NOT NULL,
                changed_at timestamptz NOT NULL,
                PRIMARY KEY (tenant_id, record_id, version),
                UNIQUE (tenant_id, audit_revision)
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS yap_terminology_snapshots (
                tenant_id text NOT NULL,
                snapshot_sha256 text NOT NULL,
                subject_id text NOT NULL,
                source_revision text NOT NULL,
                payload jsonb NOT NULL,
                created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
                PRIMARY KEY (tenant_id, snapshot_sha256)
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS yap_terminology_job_bindings (
                tenant_id text NOT NULL,
                job_id text NOT NULL,
                snapshot_sha256 text NOT NULL,
                bound_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
                PRIMARY KEY (tenant_id, job_id),
                FOREIGN KEY (tenant_id, snapshot_sha256)
                    REFERENCES yap_terminology_snapshots
            )"""
        )


def append_terminology_record(
    connection: Connection[object],
    record: TerminologyRecord,
    *,
    actor: PrincipalKey,
    actor_team_ids: tuple[str, ...] = (),
    may_manage_organization: bool = False,
) -> None:
    """Append an authorized immutable record version; never overwrite history."""

    validate_terminology_record(record, tenant_id=actor.tenant_id)
    if not _actor_owns(
        record,
        actor=actor,
        actor_team_ids=actor_team_ids,
        may_manage_organization=may_manage_organization,
    ):
        raise PermissionError("terminology actor does not own the requested scope")
    with connection.transaction():
        connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"{record.tenant_id}:{record.record_id}",),
        )
        latest = connection.execute(
            """SELECT max(version) FROM yap_terminology_records
               WHERE tenant_id = %s AND record_id = %s""",
            (record.tenant_id, record.record_id),
        ).fetchone()
        latest_version = latest[0] if latest is not None else None
        if latest_version is not None and record.version <= latest_version:
            raise ValueError("terminology version does not advance")
        connection.execute(
            """INSERT INTO yap_terminology_records (
                tenant_id, record_id, version, scope, owner_id, locale,
                canonical_form, variants, sensitivity, deleted,
                audit_revision, changed_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                record.tenant_id,
                record.record_id,
                record.version,
                record.scope,
                record.owner_id,
                record.locale,
                record.canonical_form,
                Jsonb(list(record.variants)),
                record.sensitivity,
                record.deleted,
                record.audit_revision,
                record.changed_at,
            ),
        )


def bind_job_terminology_snapshot(
    connection: Connection[object],
    *,
    job_id: str,
    principal: PrincipalKey,
    team_ids: tuple[str, ...],
    locale: str,
) -> TerminologySnapshot:
    """Freeze current terminology and bind it once to a durable job identity."""

    records = _read_tenant_records(connection, principal.tenant_id)
    source_revision = _ledger_revision(records)
    snapshot = freeze_terminology_snapshot(
        records,
        principal=principal,
        team_ids=team_ids,
        locale=locale,
        source_revision=source_revision,
    )
    with connection.transaction():
        connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"{principal.tenant_id}:{job_id}",),
        )
        existing = connection.execute(
            """SELECT snapshot_sha256 FROM yap_terminology_job_bindings
               WHERE tenant_id = %s AND job_id = %s""",
            (principal.tenant_id, job_id),
        ).fetchone()
        if existing is not None:
            return read_job_terminology_snapshot(
                connection, tenant_id=principal.tenant_id, job_id=job_id
            )
        connection.execute(
            """INSERT INTO yap_terminology_snapshots (
                tenant_id, snapshot_sha256, subject_id, source_revision, payload
            ) VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, snapshot_sha256) DO NOTHING""",
            (
                snapshot.tenant_id,
                snapshot.snapshot_sha256,
                snapshot.subject_id,
                snapshot.source_revision,
                Jsonb(terminology_snapshot_payload(snapshot)),
            ),
        )
        connection.execute(
            """INSERT INTO yap_terminology_job_bindings
                (tenant_id, job_id, snapshot_sha256) VALUES (%s, %s, %s)""",
            (principal.tenant_id, job_id, snapshot.snapshot_sha256),
        )
    return snapshot


def read_job_terminology_snapshot(
    connection: Connection[object], *, tenant_id: str, job_id: str
) -> TerminologySnapshot:
    row = connection.execute(
        """SELECT s.payload
           FROM yap_terminology_job_bindings b
           JOIN yap_terminology_snapshots s
             ON s.tenant_id = b.tenant_id
            AND s.snapshot_sha256 = b.snapshot_sha256
           WHERE b.tenant_id = %s AND b.job_id = %s""",
        (tenant_id, job_id),
    ).fetchone()
    if row is None:
        raise LookupError("job has no terminology snapshot")
    return restore_terminology_snapshot(row[0])


def _read_tenant_records(
    connection: Connection[object], tenant_id: str
) -> tuple[TerminologyRecord, ...]:
    rows = connection.execute(
        """SELECT record_id, tenant_id, scope, owner_id, locale,
                  canonical_form, variants, sensitivity, version, deleted,
                  audit_revision, changed_at
           FROM yap_terminology_records WHERE tenant_id = %s
           ORDER BY record_id, version""",
        (tenant_id,),
    ).fetchall()
    return tuple(
        TerminologyRecord(
            record_id=row[0],
            tenant_id=row[1],
            scope=row[2],
            owner_id=row[3],
            locale=row[4],
            canonical_form=row[5],
            variants=tuple(row[6]),
            sensitivity=row[7],
            version=row[8],
            deleted=row[9],
            audit_revision=row[10],
            changed_at=row[11].isoformat().replace("+00:00", "Z"),
        )
        for row in rows
    )


def _ledger_revision(records: tuple[TerminologyRecord, ...]) -> str:
    identity = [
        {
            "recordId": item.record_id,
            "version": item.version,
            "auditRevision": item.audit_revision,
            "deleted": item.deleted,
        }
        for item in records
    ]
    return hashlib.sha256(
        json.dumps(identity, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def _actor_owns(
    record: TerminologyRecord,
    *,
    actor: PrincipalKey,
    actor_team_ids: tuple[str, ...],
    may_manage_organization: bool,
) -> bool:
    if record.scope == "personal":
        return record.owner_id == actor.subject_id
    if record.scope == "team":
        return record.owner_id in actor_team_ids
    return may_manage_organization and record.owner_id == actor.tenant_id


__all__ = [
    "append_terminology_record",
    "bind_job_terminology_snapshot",
    "install_terminology_schema",
    "read_job_terminology_snapshot",
]
