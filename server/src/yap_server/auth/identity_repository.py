from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
import sqlite3
import threading
from typing import Callable, Iterator

from yap_server.auth.authorization_audit import (
    AuditChainInvalid,
    verify_audit_chain,
)
from yap_server.auth.identity_records import (
    PrincipalRecord,
    Purpose,
    PurposeGrantMetadata,
    optional_display_name,
    utc_timestamp,
    validated_purpose,
)
from yap_server.auth.principal_admission import PrincipalAdmissionUnavailable
from yap_server.auth.identity_storage import (
    append_identity_audit,
    audit_events,
    create_identity_schema,
    insert_purpose_revision,
    latest_purpose,
    next_purpose_epoch,
    principal_record,
    principal_row,
    require_principal,
)
from yap_server.auth.principal import AuthenticatedPrincipal, PrincipalKey


class SqliteIdentityRepository:
    def __init__(
        self,
        path: Path,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._path = Path(path)
        self._clock = clock
        self._lock = threading.RLock()
        self._connection: sqlite3.Connection | None = None
        self._open()

    def _open(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if self._path.is_symlink():
            raise ValueError("identity repository path must not be a link")
        connection = sqlite3.connect(
            self._path,
            timeout=2.0,
            isolation_level=None,
            check_same_thread=False,
        )
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA synchronous = FULL")
            connection.execute("PRAGMA busy_timeout = 2000")
            create_identity_schema(connection)
            verify_audit_chain(connection)
        except BaseException:
            connection.close()
            raise
        self._connection = connection

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None

    def _active_connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("identity repository is closed")
        return self._connection

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._active_connection()
        connection.execute("BEGIN IMMEDIATE")
        try:
            yield connection
        except BaseException:
            connection.rollback()
            raise
        else:
            connection.commit()

    def upsert_principal(
        self,
        principal: AuthenticatedPrincipal,
        *,
        display_name_snapshot: str | None = None,
    ) -> PrincipalRecord:
        display_name_snapshot = optional_display_name(display_name_snapshot)
        occurred_at_utc, _ = utc_timestamp(self._clock())
        with self._lock, self._transaction() as connection:
            existing = principal_row(connection, principal.key)
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO principal_identity (
                        tenant_id,
                        subject_id,
                        display_name_snapshot,
                        created_at_utc,
                        last_seen_at_utc,
                        access_revoked_after_unix,
                        access_disabled
                    ) VALUES (?, ?, ?, ?, ?, 0, 0)
                    """,
                    (
                        principal.tenant_id,
                        principal.subject_id,
                        display_name_snapshot,
                        occurred_at_utc,
                        occurred_at_utc,
                    ),
                )
                append_identity_audit(
                    connection,
                    actor=principal.key,
                    target=principal.key,
                    action="principal.created",
                    outcome="succeeded",
                    occurred_at_utc=occurred_at_utc,
                    epoch=0,
                )
            else:
                self._update_existing_principal(
                    connection,
                    principal,
                    existing,
                    display_name_snapshot=display_name_snapshot,
                    occurred_at_utc=occurred_at_utc,
                )
            record = principal_row(connection, principal.key)
            assert record is not None
            return principal_record(record)

    @staticmethod
    def _update_existing_principal(
        connection: sqlite3.Connection,
        principal: AuthenticatedPrincipal,
        existing: tuple[object, ...],
        *,
        display_name_snapshot: str | None,
        occurred_at_utc: str,
    ) -> None:
        snapshot_changed = (
            display_name_snapshot is not None and display_name_snapshot != existing[2]
        )
        connection.execute(
            """
            UPDATE principal_identity
            SET display_name_snapshot = COALESCE(?, display_name_snapshot),
                last_seen_at_utc = ?
            WHERE tenant_id = ? AND subject_id = ?
            """,
            (
                display_name_snapshot,
                occurred_at_utc,
                principal.tenant_id,
                principal.subject_id,
            ),
        )
        if snapshot_changed:
            append_identity_audit(
                connection,
                actor=principal.key,
                target=principal.key,
                action="principal.snapshot_updated",
                outcome="succeeded",
                occurred_at_utc=occurred_at_utc,
                epoch=int(existing[5]),
            )

    def principal(self, key: PrincipalKey) -> PrincipalRecord | None:
        with self._lock:
            row = principal_row(self._active_connection(), key)
            return None if row is None else principal_record(row)

    def access_is_allowed(self, principal: AuthenticatedPrincipal) -> bool:
        with self._lock:
            row = principal_row(self._active_connection(), principal.key)
            if row is None:
                return False
            return self._row_allows_access(principal, row)

    @staticmethod
    def _row_allows_access(
        principal: AuthenticatedPrincipal,
        row: tuple[object, ...],
    ) -> bool:
        if bool(row[6]):
            return False
        if principal.issued_at_unix is None:
            return principal.tenant_id == "development-loopback"
        return principal.issued_at_unix > int(row[5])

    def admit_principal(self, principal: AuthenticatedPrincipal) -> bool:
        """Create once, then keep the request authorization path read-only."""
        try:
            with self._lock:
                row = principal_row(self._active_connection(), principal.key)
                if row is None:
                    self.upsert_principal(principal)
                    row = principal_row(self._active_connection(), principal.key)
                    assert row is not None
                return self._row_allows_access(principal, row)
        except (sqlite3.Error, RuntimeError) as error:
            raise PrincipalAdmissionUnavailable(
                "principal admission repository is unavailable"
            ) from error

    def revoke_access(
        self,
        actor: PrincipalKey,
        target: PrincipalKey,
    ) -> int:
        occurred_at_utc, occurred_at_unix = utc_timestamp(self._clock())
        self._require_same_tenant(actor, target)
        with self._lock, self._transaction() as connection:
            require_principal(connection, actor)
            target_row = require_principal(connection, target)
            epoch = max(occurred_at_unix, int(target_row[5]) + 1)
            connection.execute(
                """
                UPDATE principal_identity
                SET access_revoked_after_unix = ?,
                    access_disabled = 1
                WHERE tenant_id = ? AND subject_id = ?
                """,
                (epoch, target.tenant_id, target.subject_id),
            )
            append_identity_audit(
                connection,
                actor=actor,
                target=target,
                action="principal.access_revoked",
                outcome="succeeded",
                occurred_at_utc=occurred_at_utc,
                epoch=epoch,
            )
            return epoch

    def restore_access(
        self,
        actor: PrincipalKey,
        target: PrincipalKey,
    ) -> int:
        occurred_at_utc, occurred_at_unix = utc_timestamp(self._clock())
        self._require_same_tenant(actor, target)
        with self._lock, self._transaction() as connection:
            require_principal(connection, actor)
            target_row = require_principal(connection, target)
            epoch = max(occurred_at_unix, int(target_row[5]) + 1)
            connection.execute(
                """
                UPDATE principal_identity
                SET access_revoked_after_unix = ?,
                    access_disabled = 0
                WHERE tenant_id = ? AND subject_id = ?
                """,
                (epoch, target.tenant_id, target.subject_id),
            )
            append_identity_audit(
                connection,
                actor=actor,
                target=target,
                action="principal.access_restored",
                outcome="succeeded",
                occurred_at_utc=occurred_at_utc,
                epoch=epoch,
            )
            return epoch

    def grant_purpose(
        self,
        actor: PrincipalKey,
        target: PrincipalKey,
        *,
        purpose: Purpose,
        metadata: PurposeGrantMetadata,
    ) -> int:
        purpose = validated_purpose(purpose)
        occurred_at_utc, _ = utc_timestamp(self._clock())
        self._require_same_tenant(actor, target)
        with self._lock, self._transaction() as connection:
            require_principal(connection, actor)
            require_principal(connection, target)
            epoch = next_purpose_epoch(connection, target, purpose)
            insert_purpose_revision(
                connection,
                actor,
                target,
                purpose=purpose,
                epoch=epoch,
                state="granted",
                metadata=metadata,
                occurred_at_utc=occurred_at_utc,
            )
            append_identity_audit(
                connection,
                actor=actor,
                target=target,
                action="purpose.granted",
                outcome="succeeded",
                occurred_at_utc=occurred_at_utc,
                epoch=epoch,
                purpose=purpose,
            )
            return epoch

    def revoke_purpose(
        self,
        actor: PrincipalKey,
        target: PrincipalKey,
        *,
        purpose: Purpose,
    ) -> int:
        purpose = validated_purpose(purpose)
        occurred_at_utc, _ = utc_timestamp(self._clock())
        self._require_same_tenant(actor, target)
        with self._lock, self._transaction() as connection:
            require_principal(connection, actor)
            require_principal(connection, target)
            current = latest_purpose(connection, target, purpose)
            if current is None or current[1] != "granted":
                raise KeyError("active purpose grant not found")
            epoch = int(current[0]) + 1
            metadata = PurposeGrantMetadata(
                grant_id=str(current[2]),
                legal_basis_code=str(current[3]),
                privacy_assessment_ref=str(current[4]),
                notice_version=str(current[5]),
            )
            insert_purpose_revision(
                connection,
                actor,
                target,
                purpose=purpose,
                epoch=epoch,
                state="revoked",
                metadata=metadata,
                occurred_at_utc=occurred_at_utc,
            )
            append_identity_audit(
                connection,
                actor=actor,
                target=target,
                action="purpose.revoked",
                outcome="succeeded",
                occurred_at_utc=occurred_at_utc,
                epoch=epoch,
                purpose=purpose,
            )
            return epoch

    def purpose_is_active(self, target: PrincipalKey, purpose: Purpose) -> bool:
        purpose = validated_purpose(purpose)
        with self._lock:
            latest = latest_purpose(
                self._active_connection(),
                target,
                purpose,
            )
            return latest is not None and latest[1] == "granted"

    def verify_audit_chain(self) -> None:
        with self._lock:
            verify_audit_chain(self._active_connection())

    def audit_events(self) -> list[dict[str, object]]:
        with self._lock:
            return audit_events(self._active_connection())

    @staticmethod
    def _require_same_tenant(actor: PrincipalKey, target: PrincipalKey) -> None:
        if actor.tenant_id != target.tenant_id:
            raise KeyError("principal not found")


__all__ = [
    "AuditChainInvalid",
    "PrincipalRecord",
    "PurposeGrantMetadata",
    "SqliteIdentityRepository",
]
