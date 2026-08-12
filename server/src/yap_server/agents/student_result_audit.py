from __future__ import annotations

from dataclasses import dataclass
import re

from psycopg import Connection
from psycopg.errors import UniqueViolation

from yap_server.auth import AuthenticatedPrincipal
from yap_server.private_postgres_connection import (
    PrivatePostgresConnectionFactory,
)

from .student import (
    StudentEvidence,
    StudentRequest,
    student_request_sha256,
    student_work_sha256,
    validate_student_evidence,
)


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_OUTCOMES = {
    "complete": "succeeded",
    "cancelled": "cancelled",
    "evidence-unavailable": "unavailable",
    "failed": "failed",
}
_FAILURE_REASONS = {
    "admission-failed",
    "capacity-unavailable",
    "client-cancelled",
    "cancelled",
    "deadline-exceeded",
    "evidence-unavailable",
    "invalid-output",
    "provider-unavailable",
    "runtime-unavailable",
    "stale-or-invalid-generation",
    "storage-timeout",
    "storage-unavailable",
}


@dataclass(frozen=True, slots=True)
class StudentRuntimeAuditIdentity:
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
            raise ValueError("student runtime audit identity is invalid")


def install_student_result_audit_schema(connection: Connection[object]) -> None:
    """Install the immutable Student workflow-outcome ledger."""

    with connection.transaction():
        connection.execute(
            """CREATE TABLE IF NOT EXISTS yap_student_result_audit (
                audit_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                tenant_id text NOT NULL,
                subject_id text NOT NULL,
                request_id text NOT NULL,
                request_sha256 text NOT NULL
                    CHECK (request_sha256 ~ '^[0-9a-f]{64}$'),
                conversation_concept_id text NOT NULL,
                work_sha256 text
                    CHECK (work_sha256 IS NULL OR work_sha256 ~ '^[0-9a-f]{64}$'),
                purpose text NOT NULL CHECK (purpose = 'learning-questions'),
                route text NOT NULL CHECK (route = 'rapid-automation'),
                scheduling_class text NOT NULL CHECK (scheduling_class = 'background-llm'),
                provider_generation bigint CHECK (provider_generation > 0),
                candidate_id text NOT NULL,
                model text NOT NULL,
                model_revision text NOT NULL
                    CHECK (model_revision ~ '^[0-9a-f]{40}$'),
                runtime_id text NOT NULL,
                profile_sha256 text NOT NULL
                    CHECK (profile_sha256 ~ '^[0-9a-f]{64}$'),
                candidate_lock_sha256 text NOT NULL
                    CHECK (candidate_lock_sha256 ~ '^[0-9a-f]{64}$'),
                generation_sha256 text NOT NULL
                    CHECK (generation_sha256 ~ '^[0-9a-f]{64}$'),
                evidence_sha256 text
                    CHECK (evidence_sha256 IS NULL OR evidence_sha256 ~ '^[0-9a-f]{64}$'),
                permission_hash text
                    CHECK (permission_hash IS NULL OR permission_hash ~ '^[0-9a-f]{64}$'),
                authorization_hash text
                    CHECK (authorization_hash IS NULL OR authorization_hash ~ '^[0-9a-f]{64}$'),
                outcome text NOT NULL
                    CHECK (outcome IN ('succeeded', 'cancelled', 'unavailable', 'failed')),
                reason text,
                result_count integer NOT NULL CHECK (result_count >= 0),
                duration_milliseconds integer NOT NULL
                    CHECK (duration_milliseconds >= 0),
                created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
                UNIQUE (tenant_id, request_id),
                CHECK (
                    (outcome = 'succeeded' AND reason IS NULL
                        AND provider_generation IS NOT NULL
                        AND result_count = 1)
                    OR
                    (outcome != 'succeeded' AND reason IS NOT NULL
                        AND result_count = 0)
                )
            )"""
        )


class PostgresStudentResultAuditor:
    """Persist one source/runtime-bound outcome without question text."""

    def __init__(
        self,
        connection_factory: PrivatePostgresConnectionFactory,
        runtime_identity: StudentRuntimeAuditIdentity,
    ) -> None:
        if not isinstance(runtime_identity, StudentRuntimeAuditIdentity):
            raise TypeError("student runtime audit identity type is invalid")
        self._connection_factory = connection_factory
        self._runtime_identity = runtime_identity

    def record(
        self,
        *,
        principal: AuthenticatedPrincipal,
        request_id: str,
        request: StudentRequest,
        provider_generation: int | None,
        status: str,
        reason: str | None,
        evidence: StudentEvidence | None,
        question_count: int,
        duration_milliseconds: int,
    ) -> None:
        if not isinstance(request, StudentRequest):
            raise TypeError("student audit request type is invalid")
        if evidence is not None:
            validate_student_evidence(request, evidence)
        if (
            not isinstance(principal, AuthenticatedPrincipal)
            or not isinstance(request_id, str)
            or _REQUEST_ID.fullmatch(request_id) is None
            or status not in _OUTCOMES
            or (status == "complete" and reason is not None)
            or (status != "complete" and reason not in _FAILURE_REASONS)
            or isinstance(question_count, bool)
            or not isinstance(question_count, int)
            or question_count < 0
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
                status == "complete"
                and (
                    evidence is None
                    or provider_generation is None
                    or question_count != 1
                )
            )
            or (status != "complete" and question_count != 0)
            or (
                reason in {"invalid-output", "runtime-unavailable"}
                and provider_generation is None
            )
        ):
            raise ValueError("student result audit is invalid")

        identity = self._runtime_identity
        values = (
            principal.tenant_id,
            principal.subject_id,
            request_id,
            student_request_sha256(request),
            request.conversation_concept_id,
            (
                student_work_sha256(request, evidence)
                if evidence is not None
                else None
            ),
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
            _OUTCOMES[status],
            reason,
            question_count,
            duration_milliseconds,
        )
        with self._connection_factory() as connection:
            try:
                with connection.transaction():
                    inserted = connection.execute(
                        """INSERT INTO yap_student_result_audit (
                            tenant_id, subject_id, request_id, request_sha256,
                            conversation_concept_id, work_sha256, purpose,
                            route, scheduling_class,
                            provider_generation, candidate_id, model, model_revision,
                            runtime_id, profile_sha256, candidate_lock_sha256,
                            generation_sha256, evidence_sha256, permission_hash,
                            authorization_hash, outcome, reason, result_count,
                            duration_milliseconds
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s,
                            'learning-questions', 'rapid-automation', 'background-llm',
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s
                        ) RETURNING audit_id""",
                        values,
                    ).fetchone()
                    if inserted is None:
                        raise RuntimeError("student result audit was not observed")
            except UniqueViolation:
                with connection.transaction():
                    stored = connection.execute(
                        """SELECT tenant_id, subject_id, request_id,
                                  request_sha256, conversation_concept_id,
                                  work_sha256,
                                  provider_generation, candidate_id, model,
                                  model_revision, runtime_id, profile_sha256,
                                  candidate_lock_sha256, generation_sha256,
                                  evidence_sha256, permission_hash,
                                  authorization_hash, outcome, reason,
                                  result_count, duration_milliseconds
                           FROM yap_student_result_audit
                           WHERE tenant_id = %s AND request_id = %s""",
                        (principal.tenant_id, request_id),
                    ).fetchone()
                if stored != values:
                    raise ValueError("student result audit identity conflicts") from None


def _bounded_text(value: object, maximum: int) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and len(value) <= maximum
        and value.strip() == value
        and all(ord(character) >= 32 and ord(character) != 127 for character in value)
    )


__all__ = [
    "PostgresStudentResultAuditor",
    "StudentRuntimeAuditIdentity",
    "install_student_result_audit_schema",
]
