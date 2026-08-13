from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
import threading
from typing import TYPE_CHECKING

from psycopg import Connection
from psycopg.pq import TransactionStatus

from yap_server.auth import AuthenticatedPrincipal
from yap_server.knowledge.cancellable_database_operation import (
    run_cancellable_database_operation,
)
from yap_server.knowledge.knowledge_tool_contract import (
    validate_expected_generation,
    validate_integer,
    validate_search_text,
)
from yap_server.knowledge.postgres_knowledge_retrieval import (
    search_postgres_knowledge_lexical,
)
from yap_server.private_postgres_connection import PrivatePostgresConnectionFactory

from .librarian import (
    LIBRARIAN_KNOWLEDGE_PURPOSE,
    LIBRARIAN_MAXIMUM_OUTPUT_CHARACTERS,
    LIBRARIAN_MAXIMUM_RESULTS,
    LibrarianEvidenceItem,
    LibrarianEvidencePack,
    LibrarianRequest,
    librarian_request_sha256,
    validate_librarian_evidence,
)

if TYPE_CHECKING:
    from .analyst_model import AnalystDecision


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_KNOWLEDGE_CAPABILITIES = frozenset({"knowledge.search.lexical"})


class AnalystEvidenceChanged(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class AnalystRequest:
    question: str
    maximum_results: int
    expected_generation_sha256: str | None

    def __post_init__(self) -> None:
        validate_search_text(self.question)
        _utf8(self.question, "analyst question")
        if len(self.question) > 1_024 or "\0" in self.question:
            raise ValueError("analyst question is invalid")
        validate_integer(
            self.maximum_results,
            minimum=1,
            maximum=LIBRARIAN_MAXIMUM_RESULTS,
            field="analyst result limit",
        )
        validate_expected_generation(self.expected_generation_sha256)

    @classmethod
    def from_wire(cls, value: object) -> AnalystRequest:
        if not isinstance(value, dict) or set(value) != {
            "schemaVersion",
            "question",
            "maximumResults",
            "expectedGenerationSha256",
        }:
            raise ValueError("analyst request fields differ from the contract")
        if type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1:
            raise ValueError("analyst request schema is unsupported")
        return cls(
            question=value["question"],
            maximum_results=value["maximumResults"],
            expected_generation_sha256=value["expectedGenerationSha256"],
        )

    def to_wire(self) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "question": self.question,
            "maximumResults": self.maximum_results,
            "expectedGenerationSha256": self.expected_generation_sha256,
        }


@dataclass(frozen=True, slots=True)
class AnalystAnswer:
    answer: str
    citations: tuple[LibrarianEvidenceItem, ...]
    answer_sha256: str
    citation_sha256: str
    evidence_sha256: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.answer, str)
            or not self.answer
            or self.answer != "\n\n".join(item.text for item in self.citations)
            or not isinstance(self.citations, tuple)
            or not 1 <= len(self.citations) <= LIBRARIAN_MAXIMUM_RESULTS
            or any(
                not isinstance(item, LibrarianEvidenceItem) for item in self.citations
            )
            or len({_citation_identity(item) for item in self.citations})
            != len(self.citations)
            or not _valid_sha256(self.answer_sha256)
            or not _valid_sha256(self.citation_sha256)
            or not _valid_sha256(self.evidence_sha256)
            or self.answer_sha256 != _text_sha256(self.answer)
            or self.citation_sha256 != analyst_citation_sha256(self.citations)
        ):
            raise ValueError("analyst answer is invalid")

    def to_wire(self) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "answer": self.answer,
            "citations": [item.to_wire() for item in self.citations],
            "answerSha256": self.answer_sha256,
            "citationSha256": self.citation_sha256,
            "evidenceSha256": self.evidence_sha256,
        }


class PostgresAnalystEvidenceVerifier:
    """Re-run the exact Librarian query without acquiring a nested broker lease."""

    def __init__(self, connection_factory: PrivatePostgresConnectionFactory) -> None:
        self._connection_factory = connection_factory

    def verify(
        self,
        request: AnalystRequest,
        evidence: LibrarianEvidencePack,
        *,
        principal: AuthenticatedPrincipal,
        cancellation: threading.Event,
    ) -> None:
        if not isinstance(cancellation, threading.Event):
            raise TypeError("analyst cancellation type is invalid")
        with self._connection_factory() as connection:
            with connection.transaction():
                current = run_cancellable_database_operation(
                    connection,
                    cancellation,
                    lambda: read_analyst_evidence_in_transaction(
                        connection,
                        request,
                        principal=principal,
                    ),
                )
        validate_analyst_evidence_current(request, evidence, current)


def analyst_librarian_request(request: AnalystRequest) -> LibrarianRequest:
    if not isinstance(request, AnalystRequest):
        raise TypeError("analyst request type is invalid")
    return LibrarianRequest(
        search_text=request.question,
        maximum_results=request.maximum_results,
        expected_generation_sha256=request.expected_generation_sha256,
    )


def analyst_request_sha256(request: AnalystRequest) -> str:
    if not isinstance(request, AnalystRequest):
        raise TypeError("analyst request type is invalid")
    return _sha256(
        {
            "expectedGenerationSha256": request.expected_generation_sha256,
            "maximumResults": request.maximum_results,
            "question": request.question,
        }
    )


def analyst_work_sha256(
    request: AnalystRequest,
    evidence: LibrarianEvidencePack,
) -> str:
    validate_analyst_evidence(request, evidence)
    return _sha256(
        {
            "analystRequestSha256": analyst_request_sha256(request),
            "evidenceSha256": evidence.evidence_sha256,
            "librarianRequestSha256": librarian_request_sha256(
                analyst_librarian_request(request)
            ),
        }
    )


def analyst_citation_sha256(
    citations: tuple[LibrarianEvidenceItem, ...],
) -> str:
    if (
        not isinstance(citations, tuple)
        or not citations
        or any(not isinstance(item, LibrarianEvidenceItem) for item in citations)
    ):
        raise ValueError("analyst citations are invalid")
    return _sha256([item.to_wire() for item in citations])


def build_analyst_answer(
    request: AnalystRequest,
    evidence: LibrarianEvidencePack,
    decision: AnalystDecision,
) -> AnalystAnswer | None:
    validate_analyst_evidence(request, evidence)
    outcome = getattr(decision, "outcome", None)
    indexes = getattr(decision, "evidence_indexes", None)
    if outcome == "evidence-unavailable" and indexes == ():
        return None
    if (
        outcome != "answer"
        or not isinstance(indexes, tuple)
        or not 1 <= len(indexes) <= LIBRARIAN_MAXIMUM_RESULTS
        or any(
            isinstance(index, bool) or not isinstance(index, int) or index < 0
            for index in indexes
        )
        or len(set(indexes)) != len(indexes)
    ):
        raise ValueError("analyst decision differs from the answer contract")
    try:
        citations = tuple(evidence.items[index] for index in sorted(indexes))
    except (IndexError, TypeError) as error:
        raise ValueError("analyst evidence indexes are invalid") from error
    answer_text = "\n\n".join(item.text for item in citations)
    answer = AnalystAnswer(
        answer=answer_text,
        citations=citations,
        answer_sha256=_text_sha256(answer_text),
        citation_sha256=analyst_citation_sha256(citations),
        evidence_sha256=evidence.evidence_sha256,
    )
    validate_analyst_answer(request, evidence, answer)
    return answer


def validate_analyst_evidence(
    request: AnalystRequest,
    evidence: LibrarianEvidencePack,
) -> None:
    if not isinstance(request, AnalystRequest):
        raise TypeError("analyst request type is invalid")
    validate_librarian_evidence(analyst_librarian_request(request), evidence)


def validate_analyst_evidence_current(
    request: AnalystRequest,
    evidence: LibrarianEvidencePack,
    current_evidence: LibrarianEvidencePack,
) -> None:
    validate_analyst_evidence(request, evidence)
    validate_analyst_evidence(request, current_evidence)
    if current_evidence != evidence:
        raise AnalystEvidenceChanged("analyst evidence changed under current authority")


def validate_analyst_answer(
    request: AnalystRequest,
    evidence: LibrarianEvidencePack,
    answer: AnalystAnswer,
) -> None:
    validate_analyst_evidence(request, evidence)
    if (
        not isinstance(answer, AnalystAnswer)
        or answer.evidence_sha256 != evidence.evidence_sha256
        or not answer.citations
        or any(item not in evidence.items for item in answer.citations)
        or len({_citation_identity(item) for item in answer.citations})
        != len(answer.citations)
        or tuple(evidence.items.index(item) for item in answer.citations)
        != tuple(sorted(evidence.items.index(item) for item in answer.citations))
    ):
        raise ValueError("analyst answer differs from its evidence")


def read_analyst_evidence_in_transaction(
    connection: Connection[object],
    request: AnalystRequest,
    *,
    principal: AuthenticatedPrincipal,
) -> LibrarianEvidencePack:
    if connection.info.transaction_status is TransactionStatus.IDLE:
        raise RuntimeError("analyst evidence requires an owned transaction")
    if not isinstance(request, AnalystRequest):
        raise TypeError("analyst request type is invalid")
    if not isinstance(principal, AuthenticatedPrincipal):
        raise TypeError("analyst principal type is invalid")
    search = search_postgres_knowledge_lexical(
        connection,
        principal=principal.key,
        purpose=LIBRARIAN_KNOWLEDGE_PURPOSE,
        agent_capabilities=_KNOWLEDGE_CAPABILITIES,
        search_text=request.question,
        maximum_results=request.maximum_results,
        expected_generation_sha256=request.expected_generation_sha256,
    )
    output: list[LibrarianEvidenceItem] = []
    used = 0
    exhausted = False
    for result in search.results:
        item = LibrarianEvidenceItem(
            concept_id=result.concept_id,
            source_revision=result.source_revision,
            content_sha256=result.content_sha256,
            char_start=result.char_start,
            char_end=result.char_end,
            text=result.text,
        )
        size = sum(
            len(value)
            for value in (
                item.concept_id,
                item.source_revision,
                item.content_sha256,
                item.text,
            )
        )
        if used + size > LIBRARIAN_MAXIMUM_OUTPUT_CHARACTERS:
            exhausted = True
            break
        used += size
        output.append(item)
    return LibrarianEvidencePack.create(
        generation_sha256=search.generation_sha256,
        permission_hash=search.permission_hash,
        authorization_hash=search.authorization_hash,
        items=tuple(output),
        output_budget_exhausted=exhausted,
    )


def _citation_identity(item: LibrarianEvidenceItem) -> tuple[object, ...]:
    return (
        item.concept_id,
        item.source_revision,
        item.content_sha256,
        item.char_start,
        item.char_end,
    )


def _text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _valid_sha256(value: object) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _utf8(value: object, field: str) -> None:
    if not isinstance(value, str):
        raise ValueError(f"{field} is invalid")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError(f"{field} is invalid") from error


__all__ = [
    "AnalystAnswer",
    "AnalystEvidenceChanged",
    "AnalystRequest",
    "PostgresAnalystEvidenceVerifier",
    "analyst_citation_sha256",
    "analyst_librarian_request",
    "analyst_request_sha256",
    "analyst_work_sha256",
    "build_analyst_answer",
    "read_analyst_evidence_in_transaction",
    "validate_analyst_answer",
    "validate_analyst_evidence",
    "validate_analyst_evidence_current",
]
