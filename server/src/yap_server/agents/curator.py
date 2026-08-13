from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
import threading
import time

from psycopg import Connection
from psycopg.errors import QueryCanceled
from psycopg.pq import TransactionStatus

from yap_server.auth import AuthenticatedPrincipal
from yap_server.knowledge.cancellable_database_operation import (
    run_cancellable_database_operation,
)
from yap_server.knowledge.knowledge_tool_audit import record_knowledge_tool_audit
from yap_server.knowledge.knowledge_tool_contract import (
    KnowledgeToolCancellationFailed,
    KnowledgeToolCancelled,
    KnowledgeToolTimedOut,
    ProposalCitation,
    validate_bounded_text,
)
from yap_server.knowledge.postgres_knowledge_retrieval import (
    PostgresKnowledgeConceptEvidence,
    read_postgres_knowledge_concept_evidence,
)
from yap_server.private_postgres_connection import PrivatePostgresConnectionFactory

from .student import StudentEvidenceItem
from .student_model import (
    StudentQuestion,
    StudentQuestionSupport,
    student_question_text,
    validate_student_question_grounding,
)


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SUBMISSION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_MAXIMUM_REVIEWED_CONTENT_CHARACTERS = 2_048
_MAXIMUM_SOURCE_CITATIONS = 8
_MAXIMUM_SUPPORT_QUOTE_CHARACTERS = 1_024
_MAXIMUM_EXPLICIT_CITATION_CHARACTERS = 1_024
_MAXIMUM_STUDENT_CITATION_CHARACTERS = 8_192
_MAXIMUM_EVIDENCE_CHARACTERS = 8_192
_MAXIMUM_CONCEPT_ITEMS = 100
_MAXIMUM_CONCEPT_CHARACTERS = 1_000_000
_TRIGGERS = {"explicit-proposal", "reviewed-student-answer"}


@dataclass(frozen=True, slots=True)
class CuratorReviewedStudentQuestion:
    source_subject: str
    question: str
    source_citation: ProposalCitation
    support_quote: str
    support_char_start: int
    support_char_end: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.source_subject, str)
            or self.question != student_question_text(self.source_subject)
            or not isinstance(self.source_citation, ProposalCitation)
        ):
            raise ValueError("curator Student question is invalid")
        try:
            ProposalCitation.model_validate(self.source_citation, strict=True)
        except ValueError as error:
            raise ValueError("curator Student citation is invalid") from error
        _bounded_content(
            self.support_quote,
            field="curator Student support",
            maximum=_MAXIMUM_SUPPORT_QUOTE_CHARACTERS,
        )
        if (
            isinstance(self.support_char_start, bool)
            or not isinstance(self.support_char_start, int)
            or isinstance(self.support_char_end, bool)
            or not isinstance(self.support_char_end, int)
            or self.support_char_start < 0
            or self.support_char_end <= self.support_char_start
            or self.support_char_end - self.support_char_start
            != len(self.support_quote)
            or self.support_char_start < self.source_citation.char_start
            or self.support_char_end > self.source_citation.char_end
        ):
            raise ValueError("curator Student support span is invalid")

    @classmethod
    def from_wire(cls, value: object) -> CuratorReviewedStudentQuestion:
        if not isinstance(value, dict) or set(value) != {
            "schemaVersion",
            "sourceSubject",
            "question",
            "sourceSupports",
        }:
            raise ValueError("curator Student question fields differ")
        if type(value["schemaVersion"]) is not int or value["schemaVersion"] != 3:
            raise ValueError("curator Student question schema differs")
        supports = value["sourceSupports"]
        if (
            not isinstance(supports, list)
            or len(supports) != 1
            or not isinstance(supports[0], dict)
            or set(supports[0])
            != {
                "sourceCitation",
                "supportQuote",
                "supportCharStart",
                "supportCharEnd",
            }
        ):
            raise ValueError("curator Student support fields differ")
        support = supports[0]
        return cls(
            source_subject=value["sourceSubject"],
            question=value["question"],
            source_citation=_citation_from_wire(support["sourceCitation"]),
            support_quote=support["supportQuote"],
            support_char_start=support["supportCharStart"],
            support_char_end=support["supportCharEnd"],
        )

    def to_wire(self) -> dict[str, object]:
        return {
            "schemaVersion": 3,
            "sourceSubject": self.source_subject,
            "question": self.question,
            "sourceSupports": [
                {
                    "sourceCitation": _citation_wire(self.source_citation),
                    "supportQuote": self.support_quote,
                    "supportCharStart": self.support_char_start,
                    "supportCharEnd": self.support_char_end,
                }
            ],
        }


@dataclass(frozen=True, slots=True)
class CuratorRequest:
    submission_id: str
    trigger: str
    expected_generation_sha256: str
    reviewed_content: str
    source_citations: tuple[ProposalCitation, ...]
    student_question: CuratorReviewedStudentQuestion | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.submission_id, str)
            or _SUBMISSION_ID.fullmatch(self.submission_id) is None
            or not isinstance(self.trigger, str)
            or self.trigger not in _TRIGGERS
            or not isinstance(self.expected_generation_sha256, str)
            or _SHA256.fullmatch(self.expected_generation_sha256) is None
        ):
            raise ValueError("curator generation identity is invalid")
        _bounded_content(
            self.reviewed_content,
            field="curator reviewed content",
            maximum=_MAXIMUM_REVIEWED_CONTENT_CHARACTERS,
        )
        if (
            not isinstance(self.source_citations, tuple)
            or not 1 <= len(self.source_citations) <= _MAXIMUM_SOURCE_CITATIONS
            or any(
                not isinstance(item, ProposalCitation)
                for item in self.source_citations
            )
        ):
            raise ValueError("curator source citations are invalid")
        if (
            self.trigger == "explicit-proposal"
            and self.student_question is not None
        ) or (
            self.trigger == "reviewed-student-answer"
            and (
                not isinstance(
                    self.student_question,
                    CuratorReviewedStudentQuestion,
                )
                or len(self.source_citations) != 1
                or self.source_citations[0]
                != self.student_question.source_citation
            )
        ):
            raise ValueError("curator trigger authority is invalid")
        try:
            citations = tuple(
                ProposalCitation.model_validate(item, strict=True)
                for item in self.source_citations
            )
        except ValueError as error:
            raise ValueError("curator source citations are invalid") from error
        if (
            citations != self.source_citations
            or len({_citation_identity(item) for item in citations})
            != len(citations)
            or any(
                item.char_end - item.char_start
                > (
                    _MAXIMUM_STUDENT_CITATION_CHARACTERS
                    if self.trigger == "reviewed-student-answer"
                    else _MAXIMUM_EXPLICIT_CITATION_CHARACTERS
                )
                for item in citations
            )
            or sum(item.char_end - item.char_start for item in citations)
            > _MAXIMUM_EVIDENCE_CHARACTERS
            or _has_overlapping_citations(citations)
        ):
            raise ValueError("curator source citations are invalid")

    @classmethod
    def from_wire(cls, value: object) -> CuratorRequest:
        if not isinstance(value, dict):
            raise ValueError("curator request fields differ")
        trigger = value.get("trigger")
        expected_fields = {
            "schemaVersion",
            "submissionId",
            "trigger",
            "expectedGenerationSha256",
            "reviewedContent",
        }
        if trigger == "reviewed-student-answer":
            expected_fields.add("studentQuestion")
        else:
            expected_fields.add("sourceCitations")
        if set(value) != expected_fields:
            raise ValueError("curator request fields differ")
        if type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1:
            raise ValueError("curator request schema differs")
        student_question = (
            CuratorReviewedStudentQuestion.from_wire(value["studentQuestion"])
            if trigger == "reviewed-student-answer"
            else None
        )
        if student_question is not None:
            citations = (student_question.source_citation,)
        else:
            raw_citations = value["sourceCitations"]
            if (
                not isinstance(raw_citations, list)
                or not 1 <= len(raw_citations) <= _MAXIMUM_SOURCE_CITATIONS
            ):
                raise ValueError("curator source citations are invalid")
            citations = tuple(_citation_from_wire(item) for item in raw_citations)
        return cls(
            submission_id=value["submissionId"],
            trigger=trigger,
            expected_generation_sha256=value["expectedGenerationSha256"],
            reviewed_content=value["reviewedContent"],
            source_citations=citations,
            student_question=student_question,
        )


@dataclass(frozen=True, slots=True)
class CuratorEvidenceItem:
    citation: ProposalCitation
    text: str

    def __post_init__(self) -> None:
        if not isinstance(self.citation, ProposalCitation):
            raise ValueError("curator evidence citation is invalid")
        try:
            ProposalCitation.model_validate(self.citation, strict=True)
        except ValueError as error:
            raise ValueError("curator evidence citation is invalid") from error
        if self.citation.char_end - self.citation.char_start != len(self.text):
            raise ValueError("curator evidence span is invalid")
        _bounded_content(
            self.text,
            field="curator evidence text",
            maximum=_MAXIMUM_STUDENT_CITATION_CHARACTERS,
        )

    def to_wire(self) -> dict[str, object]:
        return {**_citation_wire(self.citation), "text": self.text}


@dataclass(frozen=True, slots=True)
class CuratorEvidence:
    generation_sha256: str
    permission_hash: str
    authorization_hash: str
    items: tuple[CuratorEvidenceItem, ...]
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
            raise ValueError("curator evidence identity is invalid")
        if (
            not isinstance(self.items, tuple)
            or not 1 <= len(self.items) <= _MAXIMUM_SOURCE_CITATIONS
            or any(not isinstance(item, CuratorEvidenceItem) for item in self.items)
            or len({_citation_identity(item.citation) for item in self.items})
            != len(self.items)
        ):
            raise ValueError("curator evidence pack is invalid")

    @classmethod
    def create(
        cls,
        *,
        generation_sha256: str,
        permission_hash: str,
        authorization_hash: str,
        items: tuple[CuratorEvidenceItem, ...],
    ) -> CuratorEvidence:
        provisional = cls(
            generation_sha256,
            permission_hash,
            authorization_hash,
            items,
            "0" * 64,
        )
        return cls(
            generation_sha256,
            permission_hash,
            authorization_hash,
            items,
            curator_evidence_sha256(provisional),
        )


class PostgresCuratorEvidenceReader:
    """Re-read every submitted citation from one permission-safe generation."""

    def __init__(self, connection_factory: PrivatePostgresConnectionFactory) -> None:
        self._connection_factory = connection_factory

    def read(
        self,
        request: CuratorRequest,
        *,
        principal: AuthenticatedPrincipal,
        cancellation: threading.Event,
    ) -> CuratorEvidence:
        if not isinstance(request, CuratorRequest):
            raise TypeError("curator request type is invalid")
        if not isinstance(principal, AuthenticatedPrincipal):
            raise TypeError("curator principal type is invalid")
        if not isinstance(cancellation, threading.Event):
            raise TypeError("curator cancellation type is invalid")
        started = time.monotonic()
        with self._connection_factory() as connection:
            try:
                with connection.transaction():
                    packs = run_cancellable_database_operation(
                        connection,
                        cancellation,
                        lambda: _read_concepts(connection, request, principal),
                    )
                    evidence = _resolved_evidence(request, packs)
                    record_knowledge_tool_audit(
                        connection,
                        principal=principal.key,
                        agent_id="curator",
                        operation="reviewed-source-evidence",
                        outcome="succeeded",
                        result_count=len(evidence.items),
                        generation_sha256=evidence.generation_sha256,
                        permission_hash=evidence.permission_hash,
                        authorization_hash=evidence.authorization_hash,
                        duration_milliseconds=_duration(started),
                    )
                return evidence
            except KnowledgeToolCancelled:
                _record_failure(
                    self._connection_factory,
                    principal,
                    "cancelled",
                    started,
                )
                raise
            except KnowledgeToolCancellationFailed:
                _record_failure(
                    self._connection_factory,
                    principal,
                    "failed",
                    started,
                )
                raise
            except QueryCanceled as error:
                if cancellation.is_set():
                    _record_failure(
                        self._connection_factory,
                        principal,
                        "cancelled",
                        started,
                    )
                    raise KnowledgeToolCancelled(
                        "curator evidence read was cancelled"
                    ) from error
                _record_failure(
                    self._connection_factory,
                    principal,
                    "timed_out",
                    started,
                )
                raise KnowledgeToolTimedOut(
                    "curator evidence read timed out"
                ) from error
            except Exception:
                _record_failure(
                    self._connection_factory,
                    principal,
                    "failed",
                    started,
                )
                raise


def read_curator_evidence_in_transaction(
    connection: Connection[object],
    request: CuratorRequest,
    *,
    principal: AuthenticatedPrincipal,
) -> CuratorEvidence:
    """Re-read exact Curator evidence inside the publication transaction."""

    if connection.info.transaction_status == TransactionStatus.IDLE:
        raise RuntimeError("curator evidence requires an owned transaction")
    if not isinstance(request, CuratorRequest):
        raise TypeError("curator request type is invalid")
    if not isinstance(principal, AuthenticatedPrincipal):
        raise TypeError("curator principal type is invalid")
    return _resolved_evidence(request, _read_concepts(connection, request, principal))


def curator_request_sha256(request: CuratorRequest) -> str:
    if not isinstance(request, CuratorRequest):
        raise TypeError("curator request type is invalid")
    value: dict[str, object] = {
        "submissionId": request.submission_id,
        "trigger": request.trigger,
        "expectedGenerationSha256": request.expected_generation_sha256,
        "reviewedContent": request.reviewed_content,
    }
    if request.student_question is None:
        value["sourceCitations"] = [
            _citation_wire(item) for item in request.source_citations
        ]
    else:
        value["studentQuestion"] = request.student_question.to_wire()
    return _sha256(value)


def curator_work_sha256(request: CuratorRequest, evidence: CuratorEvidence) -> str:
    validate_curator_evidence(request, evidence)
    return _sha256(
        {
            "requestSha256": curator_request_sha256(request),
            "evidenceSha256": evidence.evidence_sha256,
        }
    )


def curator_evidence_sha256(evidence: CuratorEvidence) -> str:
    if not isinstance(evidence, CuratorEvidence):
        raise TypeError("curator evidence type is invalid")
    return _sha256(
        {
            "generationSha256": evidence.generation_sha256,
            "permissionHash": evidence.permission_hash,
            "authorizationHash": evidence.authorization_hash,
            "items": [item.to_wire() for item in evidence.items],
        }
    )


def validate_curator_evidence(
    request: CuratorRequest,
    evidence: CuratorEvidence,
) -> None:
    if (
        not isinstance(evidence, CuratorEvidence)
        or evidence.generation_sha256 != request.expected_generation_sha256
        or evidence.evidence_sha256 != curator_evidence_sha256(evidence)
        or tuple(item.citation for item in evidence.items)
        != request.source_citations
    ):
        raise ValueError("curator evidence differs from the request")
    if request.student_question is not None:
        _validate_student_lineage(request.student_question, evidence.items[0])


def _validate_student_lineage(
    expected: CuratorReviewedStudentQuestion,
    evidence: CuratorEvidenceItem,
) -> None:
    item = StudentEvidenceItem(
        concept_id=evidence.citation.concept_id,
        source_revision=evidence.citation.source_revision,
        content_sha256=evidence.citation.content_sha256,
        char_start=evidence.citation.char_start,
        char_end=evidence.citation.char_end,
        text=evidence.text,
    )
    support = StudentQuestionSupport(item, expected.support_quote)
    if (
        support.support_char_start != expected.support_char_start
        or support.support_char_end != expected.support_char_end
    ):
        raise ValueError("curator Student support differs from source evidence")
    validate_student_question_grounding(
        StudentQuestion(
            expected.source_subject,
            expected.question,
            (support,),
        )
    )


def _read_concepts(
    connection: Connection[object],
    request: CuratorRequest,
    principal: AuthenticatedPrincipal,
) -> dict[str, PostgresKnowledgeConceptEvidence]:
    return {
        concept_id: read_postgres_knowledge_concept_evidence(
            connection,
            principal=principal.key,
            purpose="knowledge.read",
            agent_capabilities=frozenset({"knowledge.search.lexical"}),
            concept_id=concept_id,
            maximum_items=_MAXIMUM_CONCEPT_ITEMS,
            maximum_characters=_MAXIMUM_CONCEPT_CHARACTERS,
            expected_generation_sha256=request.expected_generation_sha256,
        )
        for concept_id in dict.fromkeys(
            citation.concept_id for citation in request.source_citations
        )
    }


def _resolved_evidence(
    request: CuratorRequest,
    packs: dict[str, PostgresKnowledgeConceptEvidence],
) -> CuratorEvidence:
    generations = {pack.generation_sha256 for pack in packs.values()}
    permissions = {pack.permission_hash for pack in packs.values()}
    authorizations = {pack.authorization_hash for pack in packs.values()}
    if (
        generations != {request.expected_generation_sha256}
        or len(permissions) != 1
        or len(authorizations) != 1
        or any(pack.output_budget_exhausted for pack in packs.values())
    ):
        raise ValueError("curator evidence generation differs")
    items = tuple(
        _resolve_citation(citation, packs.get(citation.concept_id))
        for citation in request.source_citations
    )
    return CuratorEvidence.create(
        generation_sha256=request.expected_generation_sha256,
        permission_hash=next(iter(permissions)),
        authorization_hash=next(iter(authorizations)),
        items=items,
    )


def _resolve_citation(
    citation: ProposalCitation,
    pack: PostgresKnowledgeConceptEvidence | None,
) -> CuratorEvidenceItem:
    if pack is None or pack.concept_id != citation.concept_id or not pack.items:
        raise LookupError("curator source evidence is unavailable")
    matches: list[CuratorEvidenceItem] = []
    for item in pack.items:
        if (
            item.source_revision == citation.source_revision
            and item.content_sha256 == citation.content_sha256
            and item.char_start <= citation.char_start
            and citation.char_end <= item.char_end
        ):
            relative_start = citation.char_start - item.char_start
            relative_end = citation.char_end - item.char_start
            matches.append(
                CuratorEvidenceItem(
                    citation,
                    item.text[relative_start:relative_end],
                )
            )
    if len(matches) != 1:
        raise ValueError("curator citation is stale, hidden, or ambiguous")
    return matches[0]


def _citation_from_wire(value: object) -> ProposalCitation:
    if not isinstance(value, dict) or set(value) != {
        "conceptId",
        "sourceRevision",
        "contentSha256",
        "charStart",
        "charEnd",
    }:
        raise ValueError("curator citation fields differ")
    try:
        return ProposalCitation.model_validate(
            {
                "concept_id": value["conceptId"],
                "source_revision": value["sourceRevision"],
                "content_sha256": value["contentSha256"],
                "char_start": value["charStart"],
                "char_end": value["charEnd"],
            },
            strict=True,
        )
    except ValueError as error:
        raise ValueError("curator citation is invalid") from error


def _citation_wire(citation: ProposalCitation) -> dict[str, object]:
    return {
        "conceptId": citation.concept_id,
        "sourceRevision": citation.source_revision,
        "contentSha256": citation.content_sha256,
        "charStart": citation.char_start,
        "charEnd": citation.char_end,
    }


def _citation_identity(citation: ProposalCitation) -> tuple[object, ...]:
    return (
        citation.concept_id,
        citation.source_revision,
        citation.content_sha256,
        citation.char_start,
        citation.char_end,
    )


def _has_overlapping_citations(
    citations: tuple[ProposalCitation, ...],
) -> bool:
    by_source: dict[tuple[str, str, str], list[tuple[int, int]]] = {}
    for item in citations:
        key = (item.concept_id, item.source_revision, item.content_sha256)
        by_source.setdefault(key, []).append((item.char_start, item.char_end))
    return any(
        prior_end > current_start
        for spans in by_source.values()
        for (_prior_start, prior_end), (current_start, _current_end) in zip(
            sorted(spans), sorted(spans)[1:], strict=False
        )
    )


def _record_failure(
    connection_factory: PrivatePostgresConnectionFactory,
    principal: AuthenticatedPrincipal,
    outcome: str,
    started: float,
) -> None:
    with connection_factory() as connection:
        with connection.transaction():
            record_knowledge_tool_audit(
                connection,
                principal=principal.key,
                agent_id="curator",
                operation="reviewed-source-evidence",
                outcome=outcome,
                result_count=0,
                generation_sha256=None,
                permission_hash=None,
                authorization_hash=None,
                duration_milliseconds=_duration(started),
            )


def _bounded_content(value: object, *, field: str, maximum: int) -> str:
    text = validate_bounded_text(value, field=field, maximum=maximum)
    if any(ord(character) < 32 and character not in "\n\t" for character in text):
        raise ValueError(f"{field} is invalid")
    try:
        text.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError(f"{field} is invalid") from error
    return text


def _sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _duration(started: float) -> int:
    return max(0, round((time.monotonic() - started) * 1_000))


__all__ = [
    "CuratorEvidence",
    "CuratorEvidenceItem",
    "CuratorRequest",
    "CuratorReviewedStudentQuestion",
    "PostgresCuratorEvidenceReader",
    "curator_evidence_sha256",
    "curator_request_sha256",
    "curator_work_sha256",
    "read_curator_evidence_in_transaction",
    "validate_curator_evidence",
]
