from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
import threading
import time

from psycopg import Connection
from psycopg.errors import QueryCanceled

from yap_server.auth import AuthenticatedPrincipal
from yap_server.knowledge.cancellable_database_operation import (
    run_cancellable_database_operation,
)
from yap_server.knowledge.knowledge_tool_audit import record_knowledge_tool_audit
from yap_server.knowledge.knowledge_tool_contract import (
    KnowledgeToolCancelled,
    KnowledgeToolTimedOut,
    MAX_CONCEPT_ID_CHARACTERS,
    validate_bounded_text,
)
from yap_server.knowledge.postgres_knowledge_retrieval import (
    PostgresKnowledgeConceptEvidence,
    read_postgres_knowledge_concept_evidence,
)
from yap_server.private_postgres_connection import (
    PrivatePostgresConnectionFactory,
)


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CONVERSATION_PREFIX = "meetings/"
_CONVERSATION_SUFFIX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_MAXIMUM_FOCUS_CHARACTERS = 512
_MAXIMUM_EVIDENCE_ITEMS = 8
_MAXIMUM_EVIDENCE_CHARACTERS = 8_192
_STATEMENT_TIMEOUT_MILLISECONDS = 15_000


@dataclass(frozen=True, slots=True)
class StudentRequest:
    conversation_concept_id: str
    expected_generation_sha256: str
    focus: str

    def __post_init__(self) -> None:
        concept_id = validate_bounded_text(
            self.conversation_concept_id,
            field="student conversation concept",
            maximum=MAX_CONCEPT_ID_CHARACTERS,
        )
        if not concept_id.startswith(_CONVERSATION_PREFIX):
            raise ValueError("student conversation concept is invalid")
        suffix = concept_id.removeprefix(_CONVERSATION_PREFIX)
        if _CONVERSATION_SUFFIX.fullmatch(suffix) is None:
            raise ValueError("student conversation concept is invalid")
        if (
            not isinstance(self.expected_generation_sha256, str)
            or _SHA256.fullmatch(self.expected_generation_sha256) is None
        ):
            raise ValueError("student generation identity is invalid")
        validate_bounded_text(
            self.focus,
            field="student focus",
            maximum=_MAXIMUM_FOCUS_CHARACTERS,
        )

    @classmethod
    def from_wire(cls, value: object) -> StudentRequest:
        if not isinstance(value, dict) or set(value) != {
            "schemaVersion",
            "conversationConceptId",
            "expectedGenerationSha256",
            "focus",
        }:
            raise ValueError("student request fields differ")
        if isinstance(value["schemaVersion"], bool) or value["schemaVersion"] != 1:
            raise ValueError("student request schema differs")
        return cls(
            conversation_concept_id=value["conversationConceptId"],
            expected_generation_sha256=value["expectedGenerationSha256"],
            focus=value["focus"],
        )


@dataclass(frozen=True, slots=True)
class StudentEvidenceItem:
    concept_id: str
    source_revision: str
    content_sha256: str
    char_start: int
    char_end: int
    text: str

    def __post_init__(self) -> None:
        validate_bounded_text(
            self.concept_id,
            field="student evidence concept",
            maximum=MAX_CONCEPT_ID_CHARACTERS,
        )
        validate_bounded_text(
            self.source_revision,
            field="student evidence revision",
            maximum=512,
        )
        if (
            _SHA256.fullmatch(self.source_revision) is None
            or not isinstance(self.content_sha256, str)
            or _SHA256.fullmatch(self.content_sha256) is None
        ):
            raise ValueError("student evidence source identity is invalid")
        if (
            isinstance(self.char_start, bool)
            or not isinstance(self.char_start, int)
            or isinstance(self.char_end, bool)
            or not isinstance(self.char_end, int)
            or self.char_start < 0
            or self.char_end <= self.char_start
            or not isinstance(self.text, str)
            or not self.text
            or self.char_end - self.char_start != len(self.text)
        ):
            raise ValueError("student evidence span is invalid")

    def citation_wire(self) -> dict[str, object]:
        return {
            "conceptId": self.concept_id,
            "sourceRevision": self.source_revision,
            "contentSha256": self.content_sha256,
            "charStart": self.char_start,
            "charEnd": self.char_end,
        }


@dataclass(frozen=True, slots=True)
class StudentEvidence:
    generation_sha256: str
    permission_hash: str
    authorization_hash: str
    conversation_concept_id: str
    items: tuple[StudentEvidenceItem, ...]
    output_budget_exhausted: bool
    evidence_sha256: str

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, str) or _SHA256.fullmatch(value) is None
            for value in (
                self.generation_sha256,
                self.permission_hash,
                self.authorization_hash,
                self.evidence_sha256,
            )
        ):
            raise ValueError("student evidence identity is invalid")
        validate_bounded_text(
            self.conversation_concept_id,
            field="student evidence conversation",
            maximum=MAX_CONCEPT_ID_CHARACTERS,
        )
        if (
            not isinstance(self.items, tuple)
            or len(self.items) > _MAXIMUM_EVIDENCE_ITEMS
            or not isinstance(self.output_budget_exhausted, bool)
            or any(
                not isinstance(item, StudentEvidenceItem)
                or item.concept_id != self.conversation_concept_id
                for item in self.items
            )
            or len({_evidence_item_identity(item) for item in self.items})
            != len(self.items)
        ):
            raise ValueError("student evidence pack is invalid")

    @classmethod
    def create(
        cls,
        *,
        generation_sha256: str,
        permission_hash: str,
        authorization_hash: str,
        conversation_concept_id: str,
        items: tuple[StudentEvidenceItem, ...],
        output_budget_exhausted: bool,
    ) -> StudentEvidence:
        provisional = cls(
            generation_sha256,
            permission_hash,
            authorization_hash,
            conversation_concept_id,
            items,
            output_budget_exhausted,
            "0" * 64,
        )
        return cls(
            generation_sha256,
            permission_hash,
            authorization_hash,
            conversation_concept_id,
            items,
            output_budget_exhausted,
            student_evidence_sha256(provisional),
        )


class PostgresStudentEvidenceReader:
    """Read one exact permission-safe conversation evidence pack."""

    def __init__(
        self,
        connection_factory: PrivatePostgresConnectionFactory,
    ) -> None:
        self._connection_factory = connection_factory

    def read(
        self,
        request: StudentRequest,
        *,
        principal: AuthenticatedPrincipal,
        cancellation: threading.Event,
    ) -> StudentEvidence:
        if not isinstance(request, StudentRequest):
            raise TypeError("student request type is invalid")
        if not isinstance(principal, AuthenticatedPrincipal):
            raise TypeError("student principal type is invalid")
        if not isinstance(cancellation, threading.Event):
            raise TypeError("student cancellation type is invalid")
        started = time.monotonic()
        with self._connection_factory() as connection:
            try:
                with connection.transaction():
                    connection.execute(
                        "SELECT set_config('statement_timeout', %s, true)",
                        (str(_STATEMENT_TIMEOUT_MILLISECONDS),),
                    )
                    stored = run_cancellable_database_operation(
                        connection,
                        cancellation,
                        lambda: read_postgres_knowledge_concept_evidence(
                            connection,
                            principal=principal.key,
                            purpose="knowledge.read",
                            agent_capabilities=frozenset(
                                {"knowledge.search.lexical"}
                            ),
                            concept_id=request.conversation_concept_id,
                            maximum_items=_MAXIMUM_EVIDENCE_ITEMS,
                            maximum_characters=_MAXIMUM_EVIDENCE_CHARACTERS,
                            expected_generation_sha256=(
                                request.expected_generation_sha256
                            ),
                        ),
                    )
                    evidence = _student_evidence(stored)
                    record_knowledge_tool_audit(
                        connection,
                        principal=principal.key,
                        agent_id="student",
                        operation="conversation-evidence",
                        outcome="succeeded",
                        result_count=len(evidence.items),
                        generation_sha256=evidence.generation_sha256,
                        permission_hash=evidence.permission_hash,
                        authorization_hash=evidence.authorization_hash,
                        duration_milliseconds=_duration(started),
                    )
                return evidence
            except KnowledgeToolCancelled:
                _record_failure(connection, principal, "cancelled", started)
                raise
            except QueryCanceled as error:
                if cancellation.is_set():
                    _record_failure(connection, principal, "cancelled", started)
                    raise KnowledgeToolCancelled(
                        "student evidence read was cancelled"
                    ) from error
                _record_failure(connection, principal, "timed_out", started)
                raise KnowledgeToolTimedOut(
                    "student evidence read timed out"
                ) from error
            except Exception:
                _record_failure(connection, principal, "failed", started)
                raise


def student_request_sha256(request: StudentRequest) -> str:
    if not isinstance(request, StudentRequest):
        raise TypeError("student request type is invalid")
    value = {
        "conversationConceptId": request.conversation_concept_id,
        "expectedGenerationSha256": request.expected_generation_sha256,
        "focus": request.focus,
    }
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def student_work_sha256(
    request: StudentRequest,
    evidence: StudentEvidence,
) -> str:
    validate_student_evidence(request, evidence)
    return student_work_identity_sha256(request, evidence.evidence_sha256)


def student_work_identity_sha256(
    request: StudentRequest,
    evidence_sha256: str,
) -> str:
    if not isinstance(request, StudentRequest):
        raise TypeError("student request type is invalid")
    if not isinstance(evidence_sha256, str) or _SHA256.fullmatch(evidence_sha256) is None:
        raise ValueError("student evidence identity is invalid")
    value = {
        "conversationConceptId": request.conversation_concept_id,
        "evidenceSha256": evidence_sha256,
        "expectedGenerationSha256": request.expected_generation_sha256,
        "focus": request.focus,
    }
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def student_evidence_sha256(evidence: StudentEvidence) -> str:
    value = {
        "authorizationHash": evidence.authorization_hash,
        "conversationConceptId": evidence.conversation_concept_id,
        "generationSha256": evidence.generation_sha256,
        "items": [
            {**item.citation_wire(), "text": item.text}
            for item in evidence.items
        ],
        "outputBudgetExhausted": evidence.output_budget_exhausted,
        "permissionHash": evidence.permission_hash,
    }
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def validate_student_evidence(
    request: StudentRequest,
    evidence: StudentEvidence,
) -> None:
    if (
        not isinstance(evidence, StudentEvidence)
        or evidence.conversation_concept_id != request.conversation_concept_id
        or evidence.generation_sha256 != request.expected_generation_sha256
        or evidence.evidence_sha256 != student_evidence_sha256(evidence)
    ):
        raise ValueError("student evidence differs from the request")


def _student_evidence(stored: PostgresKnowledgeConceptEvidence) -> StudentEvidence:
    items = tuple(
        StudentEvidenceItem(
            concept_id=item.concept_id,
            source_revision=item.source_revision,
            content_sha256=item.content_sha256,
            char_start=item.char_start,
            char_end=item.char_end,
            text=item.text,
        )
        for item in stored.items
    )
    return StudentEvidence.create(
        generation_sha256=stored.generation_sha256,
        permission_hash=stored.permission_hash,
        authorization_hash=stored.authorization_hash,
        conversation_concept_id=stored.concept_id,
        items=items,
        output_budget_exhausted=stored.output_budget_exhausted,
    )


def _evidence_item_identity(item: StudentEvidenceItem) -> tuple[object, ...]:
    return (
        item.concept_id,
        item.source_revision,
        item.content_sha256,
        item.char_start,
        item.char_end,
    )


def _record_failure(
    connection: Connection[object],
    principal: AuthenticatedPrincipal,
    outcome: str,
    started: float,
) -> None:
    with connection.transaction():
        record_knowledge_tool_audit(
            connection,
            principal=principal.key,
            agent_id="student",
            operation="conversation-evidence",
            outcome=outcome,
            result_count=0,
            generation_sha256=None,
            permission_hash=None,
            authorization_hash=None,
            duration_milliseconds=_duration(started),
        )


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _duration(started: float) -> int:
    return max(0, round((time.monotonic() - started) * 1_000))


__all__ = [
    "PostgresStudentEvidenceReader",
    "StudentEvidence",
    "StudentEvidenceItem",
    "StudentRequest",
    "student_evidence_sha256",
    "student_request_sha256",
    "student_work_identity_sha256",
    "student_work_sha256",
    "validate_student_evidence",
]
