from __future__ import annotations

from dataclasses import dataclass
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

from .analyst import (
    AnalystAnswer,
    AnalystEvidenceChanged,
    AnalystRequest,
    analyst_librarian_request,
    analyst_request_sha256,
    analyst_work_sha256,
    read_analyst_evidence_in_transaction,
    validate_analyst_answer,
)
from .librarian import (
    LibrarianEvidencePack,
    librarian_request_sha256,
    librarian_work_sha256,
)


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_MAXIMUM_DURATION_MILLISECONDS = 300_000
_AGENT_ROLE = "analyst"
_PURPOSE = "knowledge-answer"
_ROUTE = "complex-orchestration"
_SCHEDULING_CLASS = "interactive"
ANALYST_RESULT_AUDIT_CONNECTION_BUDGET_SECONDS = 3.1
_OUTCOMES = {
    "complete": "succeeded",
    "evidence-unavailable": "unavailable",
    "cancelled": "cancelled",
    "failed": "failed",
}
_STORED_STATUSES = {value: key for key, value in _OUTCOMES.items()}
_OUTCOME_REASONS = {
    "succeeded": frozenset({None}),
    "unavailable": frozenset(
        {
            "empty-result",
            "evidence-unavailable",
            "stale-generation",
            "incomplete-evidence",
            "model-evidence-unavailable",
        }
    ),
    "cancelled": frozenset({"client-cancelled", "deadline-exceeded"}),
    "failed": frozenset(
        {
            "unauthorized",
            "admission-failed",
            "capacity-unavailable",
            "invalid-output",
            "provider-unavailable",
            "runtime-unavailable",
            "storage-timeout",
            "storage-unavailable",
        }
    ),
}


@dataclass(frozen=True, slots=True)
class AnalystRuntimeAuditIdentity:
    candidate_id: str
    model: str
    model_revision: str
    runtime_id: str
    profile_sha256: str
    candidate_lock_sha256: str

    def __post_init__(self) -> None:
        if (
            not _bounded_ascii(self.candidate_id, 128)
            or not _bounded_ascii(self.model, 512)
            or not isinstance(self.model_revision, str)
            or _GIT_SHA.fullmatch(self.model_revision) is None
            or not _bounded_ascii(self.runtime_id, 128)
            or not _valid_sha256(self.profile_sha256)
            or not _valid_sha256(self.candidate_lock_sha256)
        ):
            raise ValueError("analyst runtime audit identity is invalid")


@dataclass(frozen=True, slots=True)
class AnalystStoredResult:
    request_id: str
    librarian_request_id: str | None
    request_sha256: str
    work_sha256: str | None
    evidence_sha256: str | None
    answer_sha256: str | None
    citation_sha256: str | None
    generation_sha256: str | None
    permission_hash: str | None
    authorization_hash: str | None
    provider_generation: int | None
    candidate_id: str
    model: str
    model_revision: str
    runtime_id: str
    profile_sha256: str
    candidate_lock_sha256: str
    status: str
    reason: str | None
    result_count: int
    duration_milliseconds: int


def install_analyst_result_audit_schema(connection: Connection[object]) -> None:
    """Install the immutable, content-free Analyst terminal-result ledger."""

    with connection.transaction():
        connection.execute(
            """CREATE TABLE IF NOT EXISTS yap_analyst_result_audit (
                audit_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                tenant_id varchar(128) NOT NULL
                    CHECK (tenant_id ~ '^[ -~]{1,128}$'
                        AND tenant_id = btrim(tenant_id)),
                subject_id varchar(128) NOT NULL
                    CHECK (subject_id ~ '^[ -~]{1,128}$'
                        AND subject_id = btrim(subject_id)),
                request_id varchar(128) NOT NULL
                    CHECK (request_id ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$'),
                librarian_request_id varchar(128)
                    CHECK (librarian_request_id IS NULL OR
                        librarian_request_id ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$'),
                request_sha256 varchar(64) NOT NULL
                    CHECK (request_sha256 ~ '^[0-9a-f]{64}$'),
                work_sha256 varchar(64)
                    CHECK (work_sha256 IS NULL OR work_sha256 ~ '^[0-9a-f]{64}$'),
                evidence_sha256 varchar(64)
                    CHECK (evidence_sha256 IS NULL OR evidence_sha256 ~ '^[0-9a-f]{64}$'),
                answer_sha256 varchar(64)
                    CHECK (answer_sha256 IS NULL OR answer_sha256 ~ '^[0-9a-f]{64}$'),
                citation_sha256 varchar(64)
                    CHECK (citation_sha256 IS NULL OR citation_sha256 ~ '^[0-9a-f]{64}$'),
                generation_sha256 varchar(64)
                    CHECK (generation_sha256 IS NULL OR generation_sha256 ~ '^[0-9a-f]{64}$'),
                permission_hash varchar(64)
                    CHECK (permission_hash IS NULL OR permission_hash ~ '^[0-9a-f]{64}$'),
                authorization_hash varchar(64)
                    CHECK (authorization_hash IS NULL OR authorization_hash ~ '^[0-9a-f]{64}$'),
                agent_role varchar(16) NOT NULL CHECK (agent_role = 'analyst'),
                purpose varchar(32) NOT NULL CHECK (purpose = 'knowledge-answer'),
                route varchar(32) NOT NULL CHECK (route = 'complex-orchestration'),
                scheduling_class varchar(16) NOT NULL
                    CHECK (scheduling_class = 'interactive'),
                provider_generation bigint CHECK (provider_generation > 0),
                candidate_id varchar(128) NOT NULL
                    CHECK (candidate_id ~ '^[ -~]{1,128}$'
                        AND candidate_id = btrim(candidate_id)),
                model varchar(512) NOT NULL
                    CHECK (model ~ '^[ -~]+$'
                        AND char_length(model) BETWEEN 1 AND 512
                        AND model = btrim(model)),
                model_revision varchar(40) NOT NULL
                    CHECK (model_revision ~ '^[0-9a-f]{40}$'),
                runtime_id varchar(128) NOT NULL
                    CHECK (runtime_id ~ '^[ -~]{1,128}$'
                        AND runtime_id = btrim(runtime_id)),
                profile_sha256 varchar(64) NOT NULL
                    CHECK (profile_sha256 ~ '^[0-9a-f]{64}$'),
                candidate_lock_sha256 varchar(64) NOT NULL
                    CHECK (candidate_lock_sha256 ~ '^[0-9a-f]{64}$'),
                outcome varchar(16) NOT NULL CHECK (outcome IN (
                    'succeeded', 'unavailable', 'cancelled', 'failed'
                )),
                reason varchar(32),
                result_count smallint NOT NULL CHECK (result_count IN (0, 1)),
                duration_milliseconds integer NOT NULL
                    CHECK (duration_milliseconds BETWEEN 0 AND 300000),
                created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
                UNIQUE (tenant_id, request_id),
                CHECK (
                    (work_sha256 IS NULL AND evidence_sha256 IS NULL
                        AND generation_sha256 IS NULL AND permission_hash IS NULL
                        AND authorization_hash IS NULL)
                    OR
                    (librarian_request_id IS NOT NULL AND work_sha256 IS NOT NULL
                        AND evidence_sha256 IS NOT NULL
                        AND generation_sha256 IS NOT NULL
                        AND permission_hash IS NOT NULL
                        AND authorization_hash IS NOT NULL)
                ),
                CHECK (
                    (answer_sha256 IS NULL AND citation_sha256 IS NULL)
                    OR
                    (answer_sha256 IS NOT NULL AND citation_sha256 IS NOT NULL)
                ),
                CHECK (
                    reason NOT IN (
                        'invalid-output', 'runtime-unavailable',
                        'model-evidence-unavailable'
                    )
                    OR
                    (provider_generation IS NOT NULL
                        AND evidence_sha256 IS NOT NULL)
                ),
                CHECK (
                    (outcome = 'succeeded' AND reason IS NULL
                        AND librarian_request_id IS NOT NULL
                        AND provider_generation IS NOT NULL
                        AND work_sha256 IS NOT NULL
                        AND evidence_sha256 IS NOT NULL
                        AND answer_sha256 IS NOT NULL
                        AND citation_sha256 IS NOT NULL
                        AND generation_sha256 IS NOT NULL
                        AND permission_hash IS NOT NULL
                        AND authorization_hash IS NOT NULL
                        AND result_count = 1)
                    OR
                    (outcome = 'unavailable' AND reason IN (
                        'empty-result', 'evidence-unavailable', 'stale-generation',
                        'incomplete-evidence', 'model-evidence-unavailable'
                    ) AND answer_sha256 IS NULL AND citation_sha256 IS NULL
                        AND result_count = 0)
                    OR
                    (outcome = 'cancelled'
                        AND reason IN ('client-cancelled', 'deadline-exceeded')
                        AND answer_sha256 IS NULL AND citation_sha256 IS NULL
                        AND result_count = 0)
                    OR
                    (outcome = 'failed' AND reason IN (
                        'unauthorized', 'admission-failed', 'capacity-unavailable',
                        'invalid-output', 'provider-unavailable',
                        'runtime-unavailable', 'storage-timeout',
                        'storage-unavailable'
                    ) AND answer_sha256 IS NULL AND citation_sha256 IS NULL
                        AND result_count = 0)
                )
            )"""
        )


class PostgresAnalystResultAuditor:
    """Persist one exact Analyst outcome without question, evidence, or answer bytes."""

    def __init__(
        self,
        connection_factory: PrivatePostgresConnectionFactory,
        runtime_identity: AnalystRuntimeAuditIdentity,
    ) -> None:
        if not isinstance(runtime_identity, AnalystRuntimeAuditIdentity):
            raise TypeError("analyst runtime audit identity type is invalid")
        self._connection_factory = connection_factory
        self.runtime_identity = runtime_identity

    def read(
        self,
        *,
        principal: AuthenticatedPrincipal,
        request_id: str,
    ) -> AnalystStoredResult | None:
        if (
            not isinstance(principal, AuthenticatedPrincipal)
            or not isinstance(request_id, str)
            or _REQUEST_ID.fullmatch(request_id) is None
        ):
            raise ValueError("analyst stored result lookup is invalid")
        with self._connection_factory() as connection:
            row = connection.execute(
                """SELECT request_id, librarian_request_id, request_sha256,
                          work_sha256, evidence_sha256, answer_sha256,
                          citation_sha256, generation_sha256, permission_hash,
                          authorization_hash, provider_generation, candidate_id,
                          model, model_revision, runtime_id, profile_sha256,
                          candidate_lock_sha256, outcome, reason, result_count,
                          duration_milliseconds
                   FROM yap_analyst_result_audit
                   WHERE tenant_id = %s AND subject_id = %s AND request_id = %s""",
                (principal.tenant_id, principal.subject_id, request_id),
            ).fetchone()
        if row is None:
            return None
        status = _STORED_STATUSES.get(str(row[17]))
        if status is None:
            raise ValueError("analyst stored result outcome is invalid")
        return AnalystStoredResult(
            request_id=str(row[0]),
            librarian_request_id=(str(row[1]) if row[1] is not None else None),
            request_sha256=str(row[2]),
            work_sha256=(str(row[3]) if row[3] is not None else None),
            evidence_sha256=(str(row[4]) if row[4] is not None else None),
            answer_sha256=(str(row[5]) if row[5] is not None else None),
            citation_sha256=(str(row[6]) if row[6] is not None else None),
            generation_sha256=(str(row[7]) if row[7] is not None else None),
            permission_hash=(str(row[8]) if row[8] is not None else None),
            authorization_hash=(str(row[9]) if row[9] is not None else None),
            provider_generation=(int(row[10]) if row[10] is not None else None),
            candidate_id=str(row[11]),
            model=str(row[12]),
            model_revision=str(row[13]),
            runtime_id=str(row[14]),
            profile_sha256=str(row[15]),
            candidate_lock_sha256=str(row[16]),
            status=status,
            reason=(str(row[18]) if row[18] is not None else None),
            result_count=int(row[19]),
            duration_milliseconds=int(row[20]),
        )

    def record(
        self,
        *,
        principal: AuthenticatedPrincipal,
        request_id: str,
        librarian_request_id: str | None,
        request: AnalystRequest,
        provider_generation: int | None,
        status: str,
        reason: str | None,
        evidence: LibrarianEvidencePack | None,
        answer: AnalystAnswer | None,
        duration_milliseconds: int,
        cancellation: threading.Event,
        deadline: float,
    ) -> None:
        values = self._values(
            principal=principal,
            request_id=request_id,
            librarian_request_id=librarian_request_id,
            request=request,
            provider_generation=provider_generation,
            status=status,
            reason=reason,
            evidence=evidence,
            answer=answer,
            duration_milliseconds=duration_milliseconds,
        )
        if (
            not isinstance(cancellation, threading.Event)
            or isinstance(deadline, bool)
            or not isinstance(deadline, (int, float))
        ):
            raise ValueError("analyst result audit is invalid")
        if (
            deadline - time.monotonic()
            <= ANALYST_RESULT_AUDIT_CONNECTION_BUDGET_SECONDS
        ):
            raise KnowledgeToolTimedOut(
                "analyst result audit lacks a bounded connection window"
            )

        with self._connection_factory() as connection:
            remaining_seconds = deadline - time.monotonic()
            if remaining_seconds <= 0:
                raise KnowledgeToolTimedOut(
                    "analyst result audit exceeded its deadline"
                )
            remaining_milliseconds = max(1, int(remaining_seconds * 1_000))
            operation_cancellation = threading.Event()
            if cancellation.is_set():
                operation_cancellation.set()
            forwarding_stopped = threading.Event()
            forwarder = threading.Thread(
                target=_forward_cancellation,
                args=(cancellation, operation_cancellation, forwarding_stopped),
                name="analyst-result-audit-cancellation",
                daemon=False,
            )
            deadline_timer = threading.Timer(
                remaining_seconds,
                operation_cancellation.set,
            )
            deadline_timer.name = "analyst-result-audit-deadline"
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
                    if evidence is not None:
                        _require_librarian_success(
                            connection,
                            principal=principal,
                            librarian_request_id=librarian_request_id,
                            request=request,
                            evidence=evidence,
                        )
                    if status == "complete":
                        current = read_analyst_evidence_in_transaction(
                            connection,
                            request,
                            principal=principal,
                        )
                        if current != evidence:
                            raise AnalystEvidenceChanged(
                                "analyst evidence changed before result publication"
                            )
                    _insert_or_verify(connection, values, principal, request_id)
                    if cancellation.is_set():
                        raise KnowledgeToolCancelled(
                            "analyst result audit was cancelled before commit"
                        )
                    if deadline <= time.monotonic():
                        raise KnowledgeToolTimedOut(
                            "analyst result audit exceeded its deadline before commit"
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
                            "analyst result audit exceeded its deadline"
                        ) from error
                    if operation_cancellation.is_set():
                        raise KnowledgeToolCancelled(
                            "analyst result audit was cancelled"
                        ) from error
                    raise
            finally:
                forwarding_stopped.set()
                forwarder.join()
                deadline_timer.cancel()
                deadline_timer.join()

    def _values(
        self,
        *,
        principal: AuthenticatedPrincipal,
        request_id: str,
        librarian_request_id: str | None,
        request: AnalystRequest,
        provider_generation: int | None,
        status: str,
        reason: str | None,
        evidence: LibrarianEvidencePack | None,
        answer: AnalystAnswer | None,
        duration_milliseconds: int,
    ) -> tuple[object, ...]:
        if (
            not isinstance(principal, AuthenticatedPrincipal)
            or not isinstance(request, AnalystRequest)
            or not isinstance(request_id, str)
            or _REQUEST_ID.fullmatch(request_id) is None
            or (
                librarian_request_id is not None
                and (
                    not isinstance(librarian_request_id, str)
                    or _REQUEST_ID.fullmatch(librarian_request_id) is None
                )
            )
            or (
                provider_generation is not None
                and (
                    isinstance(provider_generation, bool)
                    or not isinstance(provider_generation, int)
                    or provider_generation < 1
                )
            )
            or not isinstance(status, str)
            or status not in _OUTCOMES
            or (reason is not None and not isinstance(reason, str))
            or reason not in _OUTCOME_REASONS[_OUTCOMES.get(status, "")]
            or not isinstance(duration_milliseconds, int)
            or isinstance(duration_milliseconds, bool)
            or not 0 <= duration_milliseconds <= _MAXIMUM_DURATION_MILLISECONDS
            or (
                evidence is not None and not isinstance(evidence, LibrarianEvidencePack)
            )
            or (answer is not None and not isinstance(answer, AnalystAnswer))
            or (evidence is None and answer is not None)
            or (evidence is not None and librarian_request_id is None)
            or (status == "complete" and (evidence is None or answer is None))
            or (status == "complete" and provider_generation is None)
            or (status != "complete" and answer is not None)
            or (
                reason
                in {
                    "invalid-output",
                    "runtime-unavailable",
                    "model-evidence-unavailable",
                }
                and (evidence is None or provider_generation is None)
            )
            or (
                answer is not None
                and evidence is not None
                and answer.evidence_sha256 != evidence.evidence_sha256
            )
        ):
            raise ValueError("analyst result audit is invalid")
        if answer is not None:
            assert evidence is not None
            validate_analyst_answer(request, evidence, answer)
        request_sha256 = analyst_request_sha256(request)
        work_sha256 = (
            analyst_work_sha256(request, evidence) if evidence is not None else None
        )
        identity = self.runtime_identity
        return (
            principal.tenant_id,
            principal.subject_id,
            request_id,
            librarian_request_id,
            request_sha256,
            work_sha256,
            evidence.evidence_sha256 if evidence is not None else None,
            answer.answer_sha256 if answer is not None else None,
            answer.citation_sha256 if answer is not None else None,
            evidence.generation_sha256 if evidence is not None else None,
            evidence.permission_hash if evidence is not None else None,
            evidence.authorization_hash if evidence is not None else None,
            _AGENT_ROLE,
            _PURPOSE,
            _ROUTE,
            _SCHEDULING_CLASS,
            provider_generation,
            identity.candidate_id,
            identity.model,
            identity.model_revision,
            identity.runtime_id,
            identity.profile_sha256,
            identity.candidate_lock_sha256,
            _OUTCOMES[status],
            reason,
            1 if status == "complete" else 0,
            duration_milliseconds,
        )

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
            <= ANALYST_RESULT_AUDIT_CONNECTION_BUDGET_SECONDS
        ):
            return False
        with self._connection_factory() as connection:
            remaining_seconds = deadline - time.monotonic()
            if remaining_seconds <= 0:
                return False
            cancellation = threading.Event()
            deadline_timer = threading.Timer(remaining_seconds, cancellation.set)
            deadline_timer.name = "analyst-result-audit-recovery-deadline"
            deadline_timer.daemon = False

            def recover() -> tuple[object, ...] | None:
                remaining_milliseconds = max(
                    1,
                    int(max(0.0, deadline - time.monotonic()) * 1_000),
                )
                if deadline <= time.monotonic():
                    raise KnowledgeToolTimedOut(
                        "analyst result audit recovery exceeded its deadline"
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
            raise ValueError("analyst result audit identity conflicts")
        return True


def _require_librarian_success(
    connection: Connection[object],
    *,
    principal: AuthenticatedPrincipal,
    librarian_request_id: str | None,
    request: AnalystRequest,
    evidence: LibrarianEvidencePack,
) -> None:
    if librarian_request_id is None:
        raise ValueError("analyst Librarian lineage is incomplete")
    librarian_request = analyst_librarian_request(request)
    row = connection.execute(
        """SELECT subject_id, request_sha256, work_sha256, evidence_sha256,
                  generation_sha256, permission_hash, authorization_hash,
                  agent_role, purpose, route, scheduling_class, outcome, reason,
                  result_count
           FROM yap_librarian_result_audit
           WHERE tenant_id = %s AND request_id = %s""",
        (principal.tenant_id, librarian_request_id),
    ).fetchone()
    expected = (
        principal.subject_id,
        librarian_request_sha256(librarian_request),
        librarian_work_sha256(librarian_request, evidence),
        evidence.evidence_sha256,
        evidence.generation_sha256,
        evidence.permission_hash,
        evidence.authorization_hash,
        "librarian",
        "knowledge-read",
        "server-io",
        "interactive",
        "succeeded",
        None,
        len(evidence.items),
    )
    if row is None or tuple(row) != expected:
        raise ValueError("analyst Librarian success lineage differs")


def _insert_or_verify(
    connection: Connection[object],
    values: tuple[object, ...],
    principal: AuthenticatedPrincipal,
    request_id: str,
) -> None:
    inserted = connection.execute(
        """INSERT INTO yap_analyst_result_audit (
            tenant_id, subject_id, request_id, librarian_request_id,
            request_sha256, work_sha256, evidence_sha256, answer_sha256,
            citation_sha256, generation_sha256, permission_hash,
            authorization_hash, agent_role, purpose, route, scheduling_class,
            provider_generation, candidate_id, model, model_revision,
            runtime_id, profile_sha256, candidate_lock_sha256, outcome, reason,
            result_count, duration_milliseconds
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s, %s
        ) ON CONFLICT (tenant_id, request_id) DO NOTHING
        RETURNING audit_id""",
        values,
    ).fetchone()
    if inserted is not None:
        return
    stored = _read_stored(connection, principal, request_id)
    if stored is None or tuple(stored) != values:
        raise ValueError("analyst result audit identity conflicts")


def _read_stored(
    connection: Connection[object],
    principal: AuthenticatedPrincipal,
    request_id: str,
) -> tuple[object, ...] | None:
    return connection.execute(
        """SELECT tenant_id, subject_id, request_id, librarian_request_id,
                  request_sha256, work_sha256, evidence_sha256, answer_sha256,
                  citation_sha256, generation_sha256, permission_hash,
                  authorization_hash, agent_role, purpose, route,
                  scheduling_class, provider_generation, candidate_id, model,
                  model_revision, runtime_id, profile_sha256,
                  candidate_lock_sha256, outcome, reason, result_count,
                  duration_milliseconds
           FROM yap_analyst_result_audit
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


def _bounded_ascii(value: object, maximum: int) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= maximum
        and value.strip() == value
        and value.isascii()
        and value.isprintable()
    )


def _valid_sha256(value: object) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


__all__ = [
    "ANALYST_RESULT_AUDIT_CONNECTION_BUDGET_SECONDS",
    "AnalystRuntimeAuditIdentity",
    "AnalystStoredResult",
    "PostgresAnalystResultAuditor",
    "install_analyst_result_audit_schema",
]
