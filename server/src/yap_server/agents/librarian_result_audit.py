from __future__ import annotations

import re
import threading
import time

from psycopg import Connection, Error as PostgresError
from psycopg.errors import QueryCanceled

from yap_server.auth import AuthenticatedPrincipal
from yap_server.knowledge.cancellable_database_operation import (
    run_cancellable_database_operation,
)
from yap_server.knowledge.knowledge_tool_contract import (
    KnowledgeToolCancellationFailed,
    KnowledgeToolCancelled,
    KnowledgeToolTimedOut,
)
from yap_server.private_postgres_connection import PrivatePostgresConnectionFactory


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_MAXIMUM_DURATION_MILLISECONDS = 300_000
_AGENT_ROLE = "librarian"
_PURPOSE = "knowledge-read"
_ROUTE = "server-io"
_SCHEDULING_CLASS = "interactive"
LIBRARIAN_RESULT_AUDIT_CONNECTION_BUDGET_SECONDS = 3.1
_OUTCOME_REASONS = {
    "succeeded": frozenset({None}),
    "unavailable": frozenset(
        {"empty-result", "evidence-unavailable", "stale-generation"}
    ),
    "unauthorized": frozenset({"unauthorized"}),
    "cancelled": frozenset({"client-cancelled", "deadline-exceeded"}),
    "failed": frozenset(
        {
            "admission-failed",
            "capacity-unavailable",
            "storage-timeout",
            "storage-unavailable",
        }
    ),
}


def install_librarian_result_audit_schema(connection: Connection[object]) -> None:
    """Install the immutable, content-free Librarian outcome ledger."""

    with connection.transaction():
        connection.execute(
            """CREATE TABLE IF NOT EXISTS yap_librarian_result_audit (
                audit_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                tenant_id varchar(128) NOT NULL
                    CHECK (tenant_id ~ '^[ -~]{1,128}$'
                        AND tenant_id = btrim(tenant_id)),
                subject_id varchar(128) NOT NULL
                    CHECK (subject_id ~ '^[ -~]{1,128}$'
                        AND subject_id = btrim(subject_id)),
                request_id varchar(128) NOT NULL
                    CHECK (request_id ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$'),
                request_sha256 varchar(64) NOT NULL
                    CHECK (request_sha256 ~ '^[0-9a-f]{64}$'),
                work_sha256 varchar(64)
                    CHECK (work_sha256 IS NULL
                        OR work_sha256 ~ '^[0-9a-f]{64}$'),
                evidence_sha256 varchar(64)
                    CHECK (evidence_sha256 IS NULL
                        OR evidence_sha256 ~ '^[0-9a-f]{64}$'),
                generation_sha256 varchar(64)
                    CHECK (generation_sha256 IS NULL
                        OR generation_sha256 ~ '^[0-9a-f]{64}$'),
                permission_hash varchar(64)
                    CHECK (permission_hash IS NULL
                        OR permission_hash ~ '^[0-9a-f]{64}$'),
                authorization_hash varchar(64)
                    CHECK (authorization_hash IS NULL
                        OR authorization_hash ~ '^[0-9a-f]{64}$'),
                agent_role varchar(16) NOT NULL
                    CHECK (agent_role = 'librarian'),
                purpose varchar(32) NOT NULL
                    CHECK (purpose = 'knowledge-read'),
                route varchar(16) NOT NULL
                    CHECK (route = 'server-io'),
                scheduling_class varchar(16) NOT NULL
                    CHECK (scheduling_class = 'interactive'),
                outcome varchar(16) NOT NULL
                    CHECK (outcome IN (
                        'succeeded', 'unavailable', 'unauthorized',
                        'cancelled', 'failed'
                    )),
                reason varchar(32),
                result_count smallint NOT NULL
                    CHECK (result_count BETWEEN 0 AND 5),
                duration_milliseconds integer NOT NULL
                    CHECK (duration_milliseconds BETWEEN 0 AND 300000),
                created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
                UNIQUE (tenant_id, request_id),
                CHECK (
                    (work_sha256 IS NULL
                        AND evidence_sha256 IS NULL
                        AND permission_hash IS NULL
                        AND authorization_hash IS NULL)
                    OR
                    (work_sha256 IS NOT NULL
                        AND evidence_sha256 IS NOT NULL
                        AND generation_sha256 IS NOT NULL
                        AND permission_hash IS NOT NULL
                        AND authorization_hash IS NOT NULL)
                ),
                CHECK (
                    (outcome = 'succeeded' AND reason IS NULL
                        AND work_sha256 IS NOT NULL
                        AND evidence_sha256 IS NOT NULL
                        AND generation_sha256 IS NOT NULL
                        AND permission_hash IS NOT NULL
                        AND authorization_hash IS NOT NULL
                        AND result_count BETWEEN 1 AND 5)
                    OR
                    (outcome = 'unavailable'
                        AND reason IN (
                            'empty-result', 'evidence-unavailable',
                            'stale-generation'
                        ) AND result_count = 0)
                    OR
                    (outcome = 'unauthorized'
                        AND reason = 'unauthorized' AND result_count = 0)
                    OR
                    (outcome = 'cancelled'
                        AND reason IN ('client-cancelled', 'deadline-exceeded')
                        AND result_count = 0)
                    OR
                    (outcome = 'failed'
                        AND reason IN (
                            'admission-failed', 'capacity-unavailable',
                            'storage-timeout', 'storage-unavailable'
                        ) AND result_count = 0)
                )
            )"""
        )


class PostgresLibrarianResultAuditor:
    """Persist one request- and evidence-bound result without evidence bytes."""

    def __init__(self, connection_factory: PrivatePostgresConnectionFactory) -> None:
        self._connection_factory = connection_factory

    def record(
        self,
        *,
        principal: AuthenticatedPrincipal,
        request_id: str,
        request_sha256: str,
        work_sha256: str | None,
        evidence_sha256: str | None,
        generation_sha256: str | None,
        permission_hash: str | None,
        authorization_hash: str | None,
        outcome: str,
        reason: str | None,
        result_count: int,
        duration_milliseconds: int,
        cancellation: threading.Event,
        deadline: float,
    ) -> None:
        binding_hashes = (
            work_sha256,
            evidence_sha256,
            permission_hash,
            authorization_hash,
        )
        complete_binding = all(value is not None for value in binding_hashes)
        empty_binding = all(value is None for value in binding_hashes)
        if (
            not isinstance(principal, AuthenticatedPrincipal)
            or not isinstance(request_id, str)
            or _REQUEST_ID.fullmatch(request_id) is None
            or not _valid_sha256(request_sha256)
            or not all(_valid_optional_sha256(value) for value in binding_hashes)
            or not _valid_optional_sha256(generation_sha256)
            or not (empty_binding or (complete_binding and generation_sha256 is not None))
            or not isinstance(outcome, str)
            or outcome not in _OUTCOME_REASONS
            or (reason is not None and not isinstance(reason, str))
            or reason not in _OUTCOME_REASONS.get(outcome, ())
            or isinstance(result_count, bool)
            or not isinstance(result_count, int)
            or not 0 <= result_count <= 5
            or isinstance(duration_milliseconds, bool)
            or not isinstance(duration_milliseconds, int)
            or not 0 <= duration_milliseconds <= _MAXIMUM_DURATION_MILLISECONDS
            or not isinstance(cancellation, threading.Event)
            or isinstance(deadline, bool)
            or not isinstance(deadline, (int, float))
            or (
                outcome == "succeeded"
                and (not complete_binding or generation_sha256 is None or result_count < 1)
            )
            or (outcome != "succeeded" and result_count != 0)
        ):
            raise ValueError("librarian result audit is invalid")

        if (
            deadline - time.monotonic()
            <= LIBRARIAN_RESULT_AUDIT_CONNECTION_BUDGET_SECONDS
        ):
            raise KnowledgeToolTimedOut(
                "librarian result audit lacks a bounded connection window"
            )

        values = (
            principal.tenant_id,
            principal.subject_id,
            request_id,
            request_sha256,
            work_sha256,
            evidence_sha256,
            generation_sha256,
            permission_hash,
            authorization_hash,
            _AGENT_ROLE,
            _PURPOSE,
            _ROUTE,
            _SCHEDULING_CLASS,
            outcome,
            reason,
            result_count,
            duration_milliseconds,
        )
        with self._connection_factory() as connection:
            remaining_seconds = deadline - time.monotonic()
            if remaining_seconds <= 0:
                raise KnowledgeToolTimedOut(
                    "librarian result audit exceeded its deadline"
                )
            remaining_milliseconds = max(1, int(remaining_seconds * 1_000))
            operation_cancellation = threading.Event()
            if cancellation.is_set():
                operation_cancellation.set()
            forwarding_stopped = threading.Event()
            forwarder = threading.Thread(
                target=_forward_cancellation,
                args=(cancellation, operation_cancellation, forwarding_stopped),
                name="librarian-result-audit-cancellation",
                daemon=False,
            )
            deadline_timer = threading.Timer(
                remaining_seconds,
                operation_cancellation.set,
            )
            deadline_timer.name = "librarian-result-audit-deadline"
            deadline_timer.daemon = False

            def persist() -> None:
                with connection.transaction():
                    connection.execute(
                        "SELECT set_config('statement_timeout', %s, true)",
                        (str(remaining_milliseconds),),
                    )
                    connection.execute(
                        "SELECT set_config('lock_timeout', %s, true)",
                        (str(remaining_milliseconds),),
                    )
                    _insert_or_verify(connection, values, principal, request_id)
                    if cancellation.is_set():
                        raise KnowledgeToolCancelled(
                            "librarian result audit was cancelled before commit"
                        )
                    if deadline <= time.monotonic():
                        raise KnowledgeToolTimedOut(
                            "librarian result audit exceeded its deadline before commit"
                        )

            forwarder.start()
            deadline_timer.start()
            try:
                try:
                    run_cancellable_database_operation(
                        connection,
                        operation_cancellation,
                        persist,
                    )
                except (
                    KnowledgeToolCancellationFailed,
                    KnowledgeToolCancelled,
                    OSError,
                    PostgresError,
                    QueryCanceled,
                ) as error:
                    if self._recover_exact(
                        values,
                        principal,
                        request_id,
                        deadline=deadline,
                    ):
                        return
                    if time.monotonic() >= deadline and not cancellation.is_set():
                        raise KnowledgeToolTimedOut(
                            "librarian result audit exceeded its deadline"
                        ) from error
                    if operation_cancellation.is_set():
                        raise KnowledgeToolCancelled(
                            "librarian result audit was cancelled"
                        ) from error
                    raise
            finally:
                forwarding_stopped.set()
                forwarder.join()
                deadline_timer.cancel()
                deadline_timer.join()

    def _recover_exact(
        self,
        values: tuple[object, ...],
        principal: AuthenticatedPrincipal,
        request_id: str,
        *,
        deadline: float,
    ) -> bool:
        if (
            deadline - time.monotonic()
            <= LIBRARIAN_RESULT_AUDIT_CONNECTION_BUDGET_SECONDS
        ):
            return False
        with self._connection_factory() as connection:
            remaining_seconds = deadline - time.monotonic()
            if remaining_seconds <= 0:
                return False
            cancellation = threading.Event()
            deadline_timer = threading.Timer(remaining_seconds, cancellation.set)
            deadline_timer.name = "librarian-result-audit-recovery-deadline"
            deadline_timer.daemon = False

            def recover() -> tuple[object, ...] | None:
                remaining_milliseconds = max(
                    1,
                    int(max(0.0, deadline - time.monotonic()) * 1_000),
                )
                if deadline <= time.monotonic():
                    raise KnowledgeToolTimedOut(
                        "librarian result audit recovery exceeded its deadline"
                    )
                connection.execute(
                    "SELECT set_config('statement_timeout', %s, false)",
                    (str(remaining_milliseconds),),
                )
                connection.execute(
                    "SELECT set_config('lock_timeout', %s, false)",
                    (str(remaining_milliseconds),),
                )
                return _read_stored(connection, principal, request_id)

            deadline_timer.start()
            try:
                try:
                    stored = run_cancellable_database_operation(
                        connection,
                        cancellation,
                        recover,
                    )
                except (
                    KnowledgeToolCancelled,
                    KnowledgeToolTimedOut,
                    QueryCanceled,
                ):
                    return False
            finally:
                deadline_timer.cancel()
                deadline_timer.join()
        if stored is None:
            return False
        if tuple(stored) != values:
            raise ValueError("librarian result audit identity conflicts")
        return True


def _insert_or_verify(
    connection: Connection[object],
    values: tuple[object, ...],
    principal: AuthenticatedPrincipal,
    request_id: str,
) -> None:
    inserted = connection.execute(
        """INSERT INTO yap_librarian_result_audit (
            tenant_id, subject_id, request_id, request_sha256,
            work_sha256, evidence_sha256, generation_sha256,
            permission_hash, authorization_hash, agent_role, purpose,
            route, scheduling_class, outcome, reason, result_count,
            duration_milliseconds
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s
        ) ON CONFLICT (tenant_id, request_id) DO NOTHING
        RETURNING audit_id""",
        values,
    ).fetchone()
    if inserted is not None:
        return
    stored = _read_stored(connection, principal, request_id)
    if stored is None or tuple(stored) != values:
        raise ValueError("librarian result audit identity conflicts")


def _read_stored(
    connection: Connection[object],
    principal: AuthenticatedPrincipal,
    request_id: str,
) -> tuple[object, ...] | None:
    return connection.execute(
        """SELECT tenant_id, subject_id, request_id, request_sha256,
                  work_sha256, evidence_sha256, generation_sha256,
                  permission_hash, authorization_hash, agent_role,
                  purpose, route, scheduling_class, outcome, reason,
                  result_count, duration_milliseconds
           FROM yap_librarian_result_audit
           WHERE tenant_id = %s AND request_id = %s""",
        (principal.tenant_id, request_id),
    ).fetchone()


def _forward_cancellation(
    source: threading.Event,
    target: threading.Event,
    stopped: threading.Event,
) -> None:
    while not stopped.wait(0.01):
        if source.is_set():
            target.set()
            return


def _valid_sha256(value: object) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _valid_optional_sha256(value: object) -> bool:
    return value is None or _valid_sha256(value)


__all__ = [
    "LIBRARIAN_RESULT_AUDIT_CONNECTION_BUDGET_SECONDS",
    "PostgresLibrarianResultAuditor",
    "install_librarian_result_audit_schema",
]
