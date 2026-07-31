from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Mapping


_CHAIN_ORIGIN = "0" * 64


class AuditChainInvalid(RuntimeError):
    """The durable authorization audit no longer matches its hash chain."""


def create_audit_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS authorization_audit (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT,
            event_json TEXT NOT NULL,
            previous_sha256 TEXT NOT NULL,
            event_sha256 TEXT NOT NULL UNIQUE
        )
        """
    )


def _event_hash(previous_sha256: str, event_json: str) -> str:
    return hashlib.sha256(
        f"{previous_sha256}\n{event_json}".encode("utf-8")
    ).hexdigest()


def append_audit_event(
    connection: sqlite3.Connection,
    event: Mapping[str, object],
) -> None:
    event_json = json.dumps(
        event,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    previous_row = connection.execute(
        """
        SELECT event_sha256
        FROM authorization_audit
        ORDER BY sequence DESC
        LIMIT 1
        """
    ).fetchone()
    previous_sha256 = _CHAIN_ORIGIN if previous_row is None else str(previous_row[0])
    connection.execute(
        """
        INSERT INTO authorization_audit (
            event_json,
            previous_sha256,
            event_sha256
        ) VALUES (?, ?, ?)
        """,
        (
            event_json,
            previous_sha256,
            _event_hash(previous_sha256, event_json),
        ),
    )


def verify_audit_chain(connection: sqlite3.Connection) -> None:
    previous_sha256 = _CHAIN_ORIGIN
    expected_sequence = 1
    for sequence, event_json, declared_previous, declared_hash in connection.execute(
        """
        SELECT sequence, event_json, previous_sha256, event_sha256
        FROM authorization_audit
        ORDER BY sequence
        """
    ):
        if (
            sequence != expected_sequence
            or declared_previous != previous_sha256
            or declared_hash != _event_hash(previous_sha256, event_json)
        ):
            raise AuditChainInvalid("authorization audit chain is invalid")
        try:
            event = json.loads(event_json)
        except (TypeError, json.JSONDecodeError) as error:
            raise AuditChainInvalid("authorization audit event is invalid") from error
        if not isinstance(event, dict) or event.get("schemaVersion") != 1:
            raise AuditChainInvalid("authorization audit event is invalid")
        previous_sha256 = declared_hash
        expected_sequence += 1
