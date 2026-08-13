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

from .auditor import (
    AuditorEvidenceChanged,
    AuditorEvidencePack,
    AuditorReport,
    AuditorRequest,
    auditor_request_sha256,
    auditor_work_sha256,
    read_auditor_evidence_in_transaction,
    validate_auditor_evidence,
    validate_auditor_report,
)


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_MAXIMUM_DURATION_MILLISECONDS = 300_000
_AGENT_ROLE = "auditor"
_PURPOSE = "knowledge-audit"
_ROUTE = "complex-orchestration"
_SCHEDULING_CLASS = "idle-only"
AUDITOR_RESULT_AUDIT_CONNECTION_BUDGET_SECONDS = 3.1
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
class AuditorRuntimeAuditIdentity:
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
            raise ValueError("auditor runtime audit identity is invalid")


@dataclass(frozen=True, slots=True)
class AuditorStoredResult:
    request_id: str
    request_sha256: str
    work_sha256: str | None
    evidence_sha256: str | None
    report_sha256: str | None
    citation_sha256: str | None
    generation_sha256: str | None
    source_admission_sha256: str | None
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


def install_auditor_result_audit_schema(connection: Connection[object]) -> None:
    """Install the immutable, content-free Auditor terminal-result ledger."""

    with connection.transaction():
        connection.execute(
            """CREATE TABLE IF NOT EXISTS yap_auditor_result_audit (
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
                    CHECK (work_sha256 IS NULL OR work_sha256 ~ '^[0-9a-f]{64}$'),
                evidence_sha256 varchar(64)
                    CHECK (evidence_sha256 IS NULL OR evidence_sha256 ~ '^[0-9a-f]{64}$'),
                report_sha256 varchar(64)
                    CHECK (report_sha256 IS NULL OR report_sha256 ~ '^[0-9a-f]{64}$'),
                citation_sha256 varchar(64)
                    CHECK (citation_sha256 IS NULL OR citation_sha256 ~ '^[0-9a-f]{64}$'),
                generation_sha256 varchar(64)
                    CHECK (generation_sha256 IS NULL OR generation_sha256 ~ '^[0-9a-f]{64}$'),
                source_admission_sha256 varchar(64)
                    CHECK (source_admission_sha256 IS NULL
                        OR source_admission_sha256 ~ '^[0-9a-f]{64}$'),
                permission_hash varchar(64)
                    CHECK (permission_hash IS NULL OR permission_hash ~ '^[0-9a-f]{64}$'),
                authorization_hash varchar(64)
                    CHECK (authorization_hash IS NULL OR authorization_hash ~ '^[0-9a-f]{64}$'),
                agent_role varchar(16) NOT NULL CHECK (agent_role = 'auditor'),
                purpose varchar(32) NOT NULL
                    CHECK (purpose = 'knowledge-audit'),
                route varchar(32) NOT NULL CHECK (route = 'complex-orchestration'),
                scheduling_class varchar(16) NOT NULL
                    CHECK (scheduling_class = 'idle-only'),
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
                result_count smallint NOT NULL
                    CHECK (result_count BETWEEN 0 AND 5),
                duration_milliseconds integer NOT NULL
                    CHECK (duration_milliseconds BETWEEN 0 AND 300000),
                created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
                UNIQUE (tenant_id, request_id),
                CHECK (
                    (work_sha256 IS NULL AND evidence_sha256 IS NULL
                        AND generation_sha256 IS NULL
                        AND source_admission_sha256 IS NULL
                        AND permission_hash IS NULL
                        AND authorization_hash IS NULL)
                    OR
                    (work_sha256 IS NOT NULL AND evidence_sha256 IS NOT NULL
                        AND generation_sha256 IS NOT NULL
                        AND source_admission_sha256 IS NOT NULL
                        AND permission_hash IS NOT NULL
                        AND authorization_hash IS NOT NULL)
                ),
                CHECK (
                    (report_sha256 IS NULL AND citation_sha256 IS NULL)
                    OR
                    (report_sha256 IS NOT NULL AND citation_sha256 IS NOT NULL)
                ),
                CHECK (evidence_sha256 IS NULL OR provider_generation IS NOT NULL),
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
                        AND provider_generation IS NOT NULL
                        AND work_sha256 IS NOT NULL
                        AND evidence_sha256 IS NOT NULL
                        AND report_sha256 IS NOT NULL
                        AND citation_sha256 IS NOT NULL
                        AND generation_sha256 IS NOT NULL
                        AND source_admission_sha256 IS NOT NULL
                        AND permission_hash IS NOT NULL
                        AND authorization_hash IS NOT NULL
                        AND result_count BETWEEN 1 AND 5)
                    OR
                    (outcome = 'unavailable' AND reason IN (
                        'empty-result', 'evidence-unavailable', 'stale-generation',
                        'incomplete-evidence', 'model-evidence-unavailable'
                    ) AND report_sha256 IS NULL AND citation_sha256 IS NULL
                        AND result_count = 0)
                    OR
                    (outcome = 'cancelled'
                        AND reason IN ('client-cancelled', 'deadline-exceeded')
                        AND report_sha256 IS NULL AND citation_sha256 IS NULL
                        AND result_count = 0)
                    OR
                    (outcome = 'failed' AND reason IN (
                        'unauthorized', 'admission-failed', 'capacity-unavailable',
                        'invalid-output', 'provider-unavailable',
                        'runtime-unavailable', 'storage-timeout',
                        'storage-unavailable'
                    ) AND report_sha256 IS NULL AND citation_sha256 IS NULL
                        AND result_count = 0)
                )
            )"""
        )


class PostgresAuditorResultAuditor:
    """Persist one exact Auditor outcome without objective or report bytes."""

    def __init__(
        self,
        connection_factory: PrivatePostgresConnectionFactory,
        runtime_identity: AuditorRuntimeAuditIdentity,
    ) -> None:
        if not isinstance(runtime_identity, AuditorRuntimeAuditIdentity):
            raise TypeError("auditor runtime audit identity type is invalid")
        self._connection_factory = connection_factory
        self.runtime_identity = runtime_identity

    def read(
        self,
        *,
        principal: AuthenticatedPrincipal,
        request_id: str,
    ) -> AuditorStoredResult | None:
        if (
            not isinstance(principal, AuthenticatedPrincipal)
            or not isinstance(request_id, str)
            or _REQUEST_ID.fullmatch(request_id) is None
        ):
            raise ValueError("auditor stored result lookup is invalid")
        with self._connection_factory() as connection:
            row = connection.execute(
                """SELECT request_id, request_sha256, work_sha256,
                          evidence_sha256, report_sha256, citation_sha256,
                          generation_sha256, source_admission_sha256,
                          permission_hash, authorization_hash,
                          provider_generation, candidate_id, model, model_revision,
                          runtime_id, profile_sha256, candidate_lock_sha256,
                          outcome, reason, result_count, duration_milliseconds
                   FROM yap_auditor_result_audit
                   WHERE tenant_id = %s AND subject_id = %s AND request_id = %s""",
                (principal.tenant_id, principal.subject_id, request_id),
            ).fetchone()
        if row is None:
            return None
        status = _STORED_STATUSES.get(str(row[17]))
        if status is None:
            raise ValueError("auditor stored result outcome is invalid")
        return AuditorStoredResult(
            request_id=str(row[0]),
            request_sha256=str(row[1]),
            work_sha256=(str(row[2]) if row[2] is not None else None),
            evidence_sha256=(str(row[3]) if row[3] is not None else None),
            report_sha256=(str(row[4]) if row[4] is not None else None),
            citation_sha256=(str(row[5]) if row[5] is not None else None),
            generation_sha256=(str(row[6]) if row[6] is not None else None),
            source_admission_sha256=(str(row[7]) if row[7] is not None else None),
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
        request: AuditorRequest,
        provider_generation: int | None,
        status: str,
        reason: str | None,
        evidence: AuditorEvidencePack | None,
        report: AuditorReport | None,
        duration_milliseconds: int,
        cancellation: threading.Event,
        deadline: float,
    ) -> None:
        values = self._values(
            principal=principal,
            request_id=request_id,
            request=request,
            provider_generation=provider_generation,
            status=status,
            reason=reason,
            evidence=evidence,
            report=report,
            duration_milliseconds=duration_milliseconds,
        )
        if (
            not isinstance(cancellation, threading.Event)
            or isinstance(deadline, bool)
            or not isinstance(deadline, (int, float))
        ):
            raise ValueError("auditor result audit is invalid")
        if (
            deadline - time.monotonic()
            <= AUDITOR_RESULT_AUDIT_CONNECTION_BUDGET_SECONDS
        ):
            raise KnowledgeToolTimedOut(
                "auditor result audit lacks a bounded connection window"
            )

        with self._connection_factory() as connection:
            remaining_seconds = deadline - time.monotonic()
            if remaining_seconds <= 0:
                raise KnowledgeToolTimedOut(
                    "auditor result audit exceeded its deadline"
                )
            remaining_milliseconds = max(1, int(remaining_seconds * 1_000))
            operation_cancellation = threading.Event()
            if cancellation.is_set():
                operation_cancellation.set()
            forwarding_stopped = threading.Event()
            forwarder = threading.Thread(
                target=_forward_cancellation,
                args=(cancellation, operation_cancellation, forwarding_stopped),
                name="auditor-result-audit-cancellation",
                daemon=False,
            )
            deadline_timer = threading.Timer(
                remaining_seconds,
                operation_cancellation.set,
            )
            deadline_timer.name = "auditor-result-audit-deadline"
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
                    if status == "complete":
                        assert evidence is not None
                        current = read_auditor_evidence_in_transaction(
                            connection,
                            request,
                            principal=principal,
                        )
                        if current != evidence:
                            raise AuditorEvidenceChanged(
                                "auditor evidence changed before result publication"
                            )
                    _insert_or_verify(connection, values, principal, request_id)
                    if cancellation.is_set():
                        raise KnowledgeToolCancelled(
                            "auditor result audit was cancelled before commit"
                        )
                    if deadline <= time.monotonic():
                        raise KnowledgeToolTimedOut(
                            "auditor result audit exceeded its deadline before commit"
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
                            "auditor result audit exceeded its deadline"
                        ) from error
                    if operation_cancellation.is_set():
                        raise KnowledgeToolCancelled(
                            "auditor result audit was cancelled"
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
        request: AuditorRequest,
        provider_generation: int | None,
        status: str,
        reason: str | None,
        evidence: AuditorEvidencePack | None,
        report: AuditorReport | None,
        duration_milliseconds: int,
    ) -> tuple[object, ...]:
        if (
            not isinstance(principal, AuthenticatedPrincipal)
            or not isinstance(request, AuditorRequest)
            or not isinstance(request_id, str)
            or _REQUEST_ID.fullmatch(request_id) is None
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
            or isinstance(duration_milliseconds, bool)
            or not isinstance(duration_milliseconds, int)
            or not 0 <= duration_milliseconds <= _MAXIMUM_DURATION_MILLISECONDS
            or (evidence is not None and not isinstance(evidence, AuditorEvidencePack))
            or (report is not None and not isinstance(report, AuditorReport))
            or (evidence is None and report is not None)
            or (evidence is not None and provider_generation is None)
            or (status == "complete" and (evidence is None or report is None))
            or (status == "complete" and provider_generation is None)
            or (status != "complete" and report is not None)
            or (
                reason
                in {
                    "invalid-output",
                    "runtime-unavailable",
                    "model-evidence-unavailable",
                }
                and (evidence is None or provider_generation is None)
            )
        ):
            raise ValueError("auditor result audit is invalid")
        if evidence is not None:
            validate_auditor_evidence(request, evidence)
        if report is not None:
            assert evidence is not None
            validate_auditor_report(request, evidence, report)
        request_sha256 = auditor_request_sha256(request)
        work_sha256 = (
            auditor_work_sha256(request, evidence) if evidence is not None else None
        )
        identity = self.runtime_identity
        return (
            principal.tenant_id,
            principal.subject_id,
            request_id,
            request_sha256,
            work_sha256,
            evidence.evidence_sha256 if evidence is not None else None,
            report.report_sha256 if report is not None else None,
            report.citation_sha256 if report is not None else None,
            evidence.generation_sha256 if evidence is not None else None,
            evidence.source_admission_sha256 if evidence is not None else None,
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
            len(report.findings) if report is not None else 0,
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
            <= AUDITOR_RESULT_AUDIT_CONNECTION_BUDGET_SECONDS
        ):
            return False
        with self._connection_factory() as connection:
            remaining_seconds = deadline - time.monotonic()
            if remaining_seconds <= 0:
                return False
            cancellation = threading.Event()
            deadline_timer = threading.Timer(remaining_seconds, cancellation.set)
            deadline_timer.name = "auditor-result-audit-recovery-deadline"
            deadline_timer.daemon = False

            def recover() -> tuple[object, ...] | None:
                remaining_milliseconds = max(
                    1,
                    int(max(0.0, deadline - time.monotonic()) * 1_000),
                )
                if deadline <= time.monotonic():
                    raise KnowledgeToolTimedOut(
                        "auditor result audit recovery exceeded its deadline"
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
            raise ValueError("auditor result audit identity conflicts")
        return True


def _insert_or_verify(
    connection: Connection[object],
    values: tuple[object, ...],
    principal: AuthenticatedPrincipal,
    request_id: str,
) -> None:
    inserted = connection.execute(
        """INSERT INTO yap_auditor_result_audit (
            tenant_id, subject_id, request_id, request_sha256, work_sha256,
            evidence_sha256, report_sha256, citation_sha256, generation_sha256,
            source_admission_sha256, permission_hash, authorization_hash,
            agent_role, purpose, route,
            scheduling_class, provider_generation, candidate_id, model,
            model_revision, runtime_id, profile_sha256, candidate_lock_sha256,
            outcome, reason, result_count, duration_milliseconds
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
        raise ValueError("auditor result audit identity conflicts")


def _read_stored(
    connection: Connection[object],
    principal: AuthenticatedPrincipal,
    request_id: str,
) -> tuple[object, ...] | None:
    return connection.execute(
        """SELECT tenant_id, subject_id, request_id, request_sha256,
                  work_sha256, evidence_sha256, report_sha256,
                  citation_sha256, generation_sha256,
                  source_admission_sha256, permission_hash,
                  authorization_hash, agent_role, purpose, route,
                  scheduling_class, provider_generation, candidate_id, model,
                  model_revision, runtime_id, profile_sha256,
                  candidate_lock_sha256, outcome, reason, result_count,
                  duration_milliseconds
           FROM yap_auditor_result_audit
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
    "AUDITOR_RESULT_AUDIT_CONNECTION_BUDGET_SECONDS",
    "AuditorRuntimeAuditIdentity",
    "AuditorStoredResult",
    "PostgresAuditorResultAuditor",
    "install_auditor_result_audit_schema",
]
