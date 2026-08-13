from __future__ import annotations

from dataclasses import dataclass
import re

from psycopg import Connection
from psycopg.pq import TransactionStatus

from yap_server.auth import AuthenticatedPrincipal
from yap_server.private_postgres_connection import PrivatePostgresConnectionFactory

from .curator import (
    CuratorEvidence,
    CuratorRequest,
    curator_request_sha256,
    curator_work_sha256,
    validate_curator_evidence,
)


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_OUTCOMES = {
    "proposed": "succeeded",
    "rejected": "rejected",
    "cancelled": "cancelled",
    "failed": "failed",
}
_STORED_STATUSES = {value: key for key, value in _OUTCOMES.items()}
_FAILURE_REASONS = {
    "admission-failed",
    "capacity-unavailable",
    "client-cancelled",
    "deadline-exceeded",
    "evidence-unavailable",
    "invalid-output",
    "model-rejected",
    "provider-unavailable",
    "runtime-unavailable",
    "stale-or-invalid-generation",
    "storage-timeout",
    "storage-unavailable",
}


@dataclass(frozen=True, slots=True)
class CuratorRuntimeAuditIdentity:
    candidate_id: str
    model: str
    model_revision: str
    runtime_id: str
    profile_sha256: str
    candidate_lock_sha256: str

    def __post_init__(self) -> None:
        if (
            not _bounded_text(self.candidate_id, 128)
            or not _bounded_text(self.model, 512)
            or not _GIT_SHA.fullmatch(self.model_revision)
            or not _bounded_text(self.runtime_id, 128)
            or not _SHA256.fullmatch(self.profile_sha256)
            or not _SHA256.fullmatch(self.candidate_lock_sha256)
        ):
            raise ValueError("curator runtime audit identity is invalid")


@dataclass(frozen=True, slots=True)
class CuratorStoredResult:
    request_id: str
    submission_id: str
    request_sha256: str
    generation_sha256: str
    evidence_sha256: str | None
    proposal_id: str | None
    proposal_permission_hash: str | None
    proposal_authorization_hash: str | None
    provider_generation: int | None
    status: str
    reason: str | None


def install_curator_result_audit_schema(connection: Connection[object]) -> None:
    with connection.transaction():
        connection.execute(
            """CREATE TABLE IF NOT EXISTS yap_curator_result_audit (
                audit_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                tenant_id text NOT NULL,
                subject_id text NOT NULL,
                request_id text NOT NULL,
                submission_id text NOT NULL,
                request_sha256 text NOT NULL CHECK (request_sha256 ~ '^[0-9a-f]{64}$'),
                work_sha256 text CHECK (work_sha256 IS NULL OR work_sha256 ~ '^[0-9a-f]{64}$'),
                purpose text NOT NULL CHECK (purpose = 'knowledge-propose'),
                route text NOT NULL CHECK (route = 'complex-orchestration'),
                scheduling_class text NOT NULL CHECK (scheduling_class = 'background-llm'),
                provider_generation bigint CHECK (provider_generation > 0),
                candidate_id text NOT NULL,
                model text NOT NULL,
                model_revision text NOT NULL CHECK (model_revision ~ '^[0-9a-f]{40}$'),
                runtime_id text NOT NULL,
                profile_sha256 text NOT NULL CHECK (profile_sha256 ~ '^[0-9a-f]{64}$'),
                candidate_lock_sha256 text NOT NULL CHECK (candidate_lock_sha256 ~ '^[0-9a-f]{64}$'),
                generation_sha256 text NOT NULL CHECK (generation_sha256 ~ '^[0-9a-f]{64}$'),
                evidence_sha256 text CHECK (evidence_sha256 IS NULL OR evidence_sha256 ~ '^[0-9a-f]{64}$'),
                permission_hash text CHECK (permission_hash IS NULL OR permission_hash ~ '^[0-9a-f]{64}$'),
                authorization_hash text CHECK (authorization_hash IS NULL OR authorization_hash ~ '^[0-9a-f]{64}$'),
                proposal_permission_hash text CHECK (proposal_permission_hash IS NULL OR proposal_permission_hash ~ '^[0-9a-f]{64}$'),
                proposal_authorization_hash text CHECK (proposal_authorization_hash IS NULL OR proposal_authorization_hash ~ '^[0-9a-f]{64}$'),
                proposal_id text CHECK (proposal_id IS NULL OR proposal_id ~ '^[0-9a-f]{64}$'),
                outcome text NOT NULL CHECK (outcome IN ('succeeded', 'rejected', 'cancelled', 'failed')),
                reason text,
                result_count integer NOT NULL CHECK (result_count IN (0, 1)),
                duration_milliseconds integer NOT NULL CHECK (duration_milliseconds >= 0),
                created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
                UNIQUE (tenant_id, request_id),
                UNIQUE (tenant_id, subject_id, submission_id),
                CHECK (
                    (outcome = 'succeeded' AND reason IS NULL
                        AND provider_generation IS NOT NULL
                        AND work_sha256 IS NOT NULL
                        AND evidence_sha256 IS NOT NULL
                        AND permission_hash IS NOT NULL
                        AND authorization_hash IS NOT NULL
                        AND proposal_permission_hash IS NOT NULL
                        AND proposal_authorization_hash IS NOT NULL
                        AND proposal_id IS NOT NULL AND result_count = 1)
                    OR
                    (outcome != 'succeeded' AND reason IS NOT NULL
                        AND proposal_id IS NULL AND result_count = 0)
                )
            )"""
        )


class PostgresCuratorResultAuditor:
    """Persist immutable Curator outcomes; success can join proposal publication."""

    def __init__(
        self,
        connection_factory: PrivatePostgresConnectionFactory,
        runtime_identity: CuratorRuntimeAuditIdentity,
    ) -> None:
        if not isinstance(runtime_identity, CuratorRuntimeAuditIdentity):
            raise TypeError("curator runtime audit identity type is invalid")
        self.connection_factory = connection_factory
        self.runtime_identity = runtime_identity

    def read(
        self,
        *,
        principal: AuthenticatedPrincipal,
        submission_id: str,
    ) -> CuratorStoredResult | None:
        if (
            not isinstance(principal, AuthenticatedPrincipal)
            or not isinstance(submission_id, str)
            or _REQUEST_ID.fullmatch(submission_id) is None
        ):
            raise ValueError("curator stored result lookup is invalid")
        with self.connection_factory() as connection:
            row = connection.execute(
                """SELECT request_id, submission_id, request_sha256,
                          generation_sha256, evidence_sha256, proposal_id,
                          proposal_permission_hash, proposal_authorization_hash,
                          provider_generation, outcome, reason
                   FROM yap_curator_result_audit
                   WHERE tenant_id = %s AND subject_id = %s
                     AND submission_id = %s""",
                (principal.tenant_id, principal.subject_id, submission_id),
            ).fetchone()
        if row is None:
            return None
        status = _STORED_STATUSES.get(str(row[9]))
        if status is None:
            raise ValueError("curator stored result outcome is invalid")
        return CuratorStoredResult(
            request_id=str(row[0]),
            submission_id=str(row[1]),
            request_sha256=str(row[2]),
            generation_sha256=str(row[3]),
            evidence_sha256=(str(row[4]) if row[4] is not None else None),
            proposal_id=(str(row[5]) if row[5] is not None else None),
            proposal_permission_hash=(
                str(row[6]) if row[6] is not None else None
            ),
            proposal_authorization_hash=(
                str(row[7]) if row[7] is not None else None
            ),
            provider_generation=(int(row[8]) if row[8] is not None else None),
            status=status,
            reason=(str(row[10]) if row[10] is not None else None),
        )

    def record(
        self,
        *,
        principal: AuthenticatedPrincipal,
        request_id: str,
        request: CuratorRequest,
        provider_generation: int | None,
        status: str,
        reason: str | None,
        evidence: CuratorEvidence | None,
        proposal_id: str | None,
        proposal_permission_hash: str | None = None,
        proposal_authorization_hash: str | None = None,
        duration_milliseconds: int,
    ) -> None:
        with self.connection_factory() as connection:
            with connection.transaction():
                self.record_in_transaction(
                    connection,
                    principal=principal,
                    request_id=request_id,
                    request=request,
                    provider_generation=provider_generation,
                    status=status,
                    reason=reason,
                    evidence=evidence,
                    proposal_id=proposal_id,
                    proposal_permission_hash=proposal_permission_hash,
                    proposal_authorization_hash=proposal_authorization_hash,
                    duration_milliseconds=duration_milliseconds,
                )

    def record_in_transaction(
        self,
        connection: Connection[object],
        *,
        principal: AuthenticatedPrincipal,
        request_id: str,
        request: CuratorRequest,
        provider_generation: int | None,
        status: str,
        reason: str | None,
        evidence: CuratorEvidence | None,
        proposal_id: str | None,
        proposal_permission_hash: str | None,
        proposal_authorization_hash: str | None,
        duration_milliseconds: int,
    ) -> None:
        if connection.info.transaction_status == TransactionStatus.IDLE:
            raise RuntimeError("curator result audit requires an owned transaction")
        if evidence is not None:
            validate_curator_evidence(request, evidence)
        if (
            not isinstance(principal, AuthenticatedPrincipal)
            or not isinstance(request_id, str)
            or _REQUEST_ID.fullmatch(request_id) is None
            or status not in _OUTCOMES
            or (status == "proposed" and reason is not None)
            or (status != "proposed" and reason not in _FAILURE_REASONS)
            or isinstance(duration_milliseconds, bool)
            or not isinstance(duration_milliseconds, int)
            or duration_milliseconds < 0
            or (
                provider_generation is not None
                and (
                    isinstance(provider_generation, bool)
                    or not isinstance(provider_generation, int)
                    or provider_generation < 1
                )
            )
            or (
                status == "proposed"
                and (
                    evidence is None
                    or provider_generation is None
                    or not isinstance(proposal_id, str)
                    or _SHA256.fullmatch(proposal_id) is None
                    or not isinstance(proposal_permission_hash, str)
                    or _SHA256.fullmatch(proposal_permission_hash) is None
                    or not isinstance(proposal_authorization_hash, str)
                    or _SHA256.fullmatch(proposal_authorization_hash) is None
                )
            )
            or (
                status != "proposed"
                and any(
                    value is not None
                    for value in (
                        proposal_id,
                        proposal_permission_hash,
                        proposal_authorization_hash,
                    )
                )
            )
            or (
                reason in {"invalid-output", "model-rejected", "runtime-unavailable"}
                and provider_generation is None
            )
        ):
            raise ValueError("curator result audit is invalid")
        identity = self.runtime_identity
        values = (
            principal.tenant_id,
            principal.subject_id,
            request_id,
            request.submission_id,
            curator_request_sha256(request),
            curator_work_sha256(request, evidence) if evidence is not None else None,
            provider_generation,
            identity.candidate_id,
            identity.model,
            identity.model_revision,
            identity.runtime_id,
            identity.profile_sha256,
            identity.candidate_lock_sha256,
            request.expected_generation_sha256,
            evidence.evidence_sha256 if evidence is not None else None,
            evidence.permission_hash if evidence is not None else None,
            evidence.authorization_hash if evidence is not None else None,
            proposal_permission_hash,
            proposal_authorization_hash,
            proposal_id,
            _OUTCOMES[status],
            reason,
            1 if status == "proposed" else 0,
            duration_milliseconds,
        )
        inserted = connection.execute(
                """INSERT INTO yap_curator_result_audit (
                    tenant_id, subject_id, request_id, submission_id,
                    request_sha256, work_sha256, purpose, route, scheduling_class,
                    provider_generation, candidate_id, model, model_revision,
                    runtime_id, profile_sha256, candidate_lock_sha256,
                    generation_sha256, evidence_sha256, permission_hash,
                    authorization_hash, proposal_permission_hash,
                    proposal_authorization_hash, proposal_id, outcome, reason, result_count,
                    duration_milliseconds
                ) VALUES (
                    %s, %s, %s, %s, %s, %s,
                    'knowledge-propose', 'complex-orchestration', 'background-llm',
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s
                ) ON CONFLICT DO NOTHING RETURNING audit_id""",
                values,
        ).fetchone()
        if inserted is None:
            stored_rows = connection.execute(
                """SELECT tenant_id, subject_id, request_id, submission_id,
                          request_sha256, work_sha256,
                          provider_generation, candidate_id, model, model_revision,
                          runtime_id, profile_sha256, candidate_lock_sha256,
                          generation_sha256, evidence_sha256, permission_hash,
                          authorization_hash, proposal_permission_hash,
                          proposal_authorization_hash, proposal_id, outcome, reason,
                          result_count, duration_milliseconds
                   FROM yap_curator_result_audit
                   WHERE tenant_id = %s AND subject_id = %s
                     AND (request_id = %s OR submission_id = %s)""",
                (
                    principal.tenant_id,
                    principal.subject_id,
                    request_id,
                    request.submission_id,
                ),
            ).fetchall()
            if len(stored_rows) != 1 or tuple(stored_rows[0]) != values:
                raise ValueError("curator result audit identity conflicts")


def _bounded_text(value: object, maximum: int) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and len(value) <= maximum
        and value.strip() == value
        and all(ord(character) >= 32 and ord(character) != 127 for character in value)
    )


__all__ = [
    "CuratorRuntimeAuditIdentity",
    "CuratorStoredResult",
    "PostgresCuratorResultAuditor",
    "install_curator_result_audit_schema",
]
