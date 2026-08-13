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
from yap_server.knowledge.governed_knowledge_tools import GovernedKnowledgeTools
from yap_server.knowledge.knowledge_agent_authority import KnowledgeAgentAuthority
from yap_server.knowledge.knowledge_source_admission import (
    require_knowledge_source_admission,
)
from yap_server.knowledge.knowledge_tool_contract import (
    KnowledgeAgentProfile,
    KnowledgeToolCancelled,
    KnowledgeToolResponse,
    SearchKnowledgeRequest,
    validate_expected_generation,
    validate_integer,
    validate_search_text,
)
from yap_server.knowledge.postgres_knowledge_retrieval import (
    search_postgres_knowledge_lexical,
)
from yap_server.private_postgres_connection import PrivatePostgresConnectionFactory

from .librarian import LibrarianEvidenceItem

if TYPE_CHECKING:
    from .auditor_model import AuditorDecision


AUDITOR_AGENT_ID = "auditor"
AUDITOR_KNOWLEDGE_PURPOSE = "knowledge.read"
AUDITOR_MAXIMUM_EVIDENCE_ITEMS = 8
AUDITOR_MAXIMUM_FINDINGS = 5
AUDITOR_MAXIMUM_EVIDENCE_CHARACTERS = 16_000
AUDITOR_MAXIMUM_EVIDENCE_WIRE_BYTES = 65_536
AUDITOR_STATEMENT_TIMEOUT_MILLISECONDS = 5_000

_FINDING_KIND = "potential-contradiction"
_FINDING_SUMMARY = "These two current reviewed knowledge statements may conflict."
_KNOWLEDGE_CAPABILITIES = frozenset({"knowledge.search.lexical"})
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class AuditorEvidenceChanged(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class AuditorRequest:
    focus: str
    maximum_findings: int
    expected_generation_sha256: str | None

    def __post_init__(self) -> None:
        validate_search_text(self.focus)
        _utf8(self.focus, "auditor focus")
        if len(self.focus) > 1_024 or "\0" in self.focus:
            raise ValueError("auditor focus is invalid")
        validate_integer(
            self.maximum_findings,
            minimum=1,
            maximum=AUDITOR_MAXIMUM_FINDINGS,
            field="auditor finding limit",
        )
        validate_expected_generation(self.expected_generation_sha256)

    @classmethod
    def from_wire(cls, value: object) -> AuditorRequest:
        if not isinstance(value, dict) or set(value) != {
            "schemaVersion",
            "focus",
            "maximumFindings",
            "expectedGenerationSha256",
        }:
            raise ValueError("auditor request fields differ from the contract")
        if type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1:
            raise ValueError("auditor request schema is unsupported")
        return cls(
            focus=value["focus"],
            maximum_findings=value["maximumFindings"],
            expected_generation_sha256=value["expectedGenerationSha256"],
        )

    def to_wire(self) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "focus": self.focus,
            "maximumFindings": self.maximum_findings,
            "expectedGenerationSha256": self.expected_generation_sha256,
        }


@dataclass(frozen=True, slots=True)
class AuditorEvidencePack:
    generation_sha256: str
    source_admission_sha256: str
    permission_hash: str
    authorization_hash: str
    items: tuple[LibrarianEvidenceItem, ...]
    output_budget_exhausted: bool
    evidence_sha256: str

    def __post_init__(self) -> None:
        if any(
            not _valid_sha256(value)
            for value in (
                self.generation_sha256,
                self.source_admission_sha256,
                self.permission_hash,
                self.authorization_hash,
                self.evidence_sha256,
            )
        ):
            raise ValueError("auditor evidence identity is invalid")
        if (
            not isinstance(self.items, tuple)
            or len(self.items) > AUDITOR_MAXIMUM_EVIDENCE_ITEMS
            or any(not isinstance(item, LibrarianEvidenceItem) for item in self.items)
            or len({_citation_identity(item) for item in self.items}) != len(self.items)
            or not isinstance(self.output_budget_exhausted, bool)
            or _evidence_character_count(self.items)
            > AUDITOR_MAXIMUM_EVIDENCE_CHARACTERS
            or _evidence_wire_bytes(self) > AUDITOR_MAXIMUM_EVIDENCE_WIRE_BYTES
            or self.evidence_sha256 != auditor_evidence_sha256(self)
        ):
            raise ValueError("auditor evidence pack is invalid")

    @classmethod
    def create(
        cls,
        *,
        generation_sha256: str,
        source_admission_sha256: str,
        permission_hash: str,
        authorization_hash: str,
        items: tuple[LibrarianEvidenceItem, ...],
        output_budget_exhausted: bool,
    ) -> AuditorEvidencePack:
        value = _evidence_value(
            generation_sha256=generation_sha256,
            source_admission_sha256=source_admission_sha256,
            permission_hash=permission_hash,
            authorization_hash=authorization_hash,
            items=items,
            output_budget_exhausted=output_budget_exhausted,
        )
        return cls(
            generation_sha256,
            source_admission_sha256,
            permission_hash,
            authorization_hash,
            items,
            output_budget_exhausted,
            _sha256(value),
        )

    def to_wire(self) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            **_evidence_value(
                generation_sha256=self.generation_sha256,
                source_admission_sha256=self.source_admission_sha256,
                permission_hash=self.permission_hash,
                authorization_hash=self.authorization_hash,
                items=self.items,
                output_budget_exhausted=self.output_budget_exhausted,
            ),
            "evidenceSha256": self.evidence_sha256,
        }


@dataclass(frozen=True, slots=True)
class AuditorFinding:
    kind: str
    summary: str
    citations: tuple[LibrarianEvidenceItem, LibrarianEvidenceItem]
    finding_sha256: str
    requires_review: bool

    def __post_init__(self) -> None:
        if (
            self.kind != _FINDING_KIND
            or self.summary != _FINDING_SUMMARY
            or not isinstance(self.citations, tuple)
            or len(self.citations) != 2
            or any(
                not isinstance(item, LibrarianEvidenceItem) for item in self.citations
            )
            or self.citations[0] == self.citations[1]
            or not _valid_sha256(self.finding_sha256)
            or self.finding_sha256 != auditor_finding_sha256(self)
            or self.requires_review is not True
        ):
            raise ValueError("auditor finding is invalid")

    @classmethod
    def create(
        cls,
        citations: tuple[LibrarianEvidenceItem, LibrarianEvidenceItem],
    ) -> AuditorFinding:
        return cls(
            _FINDING_KIND,
            _FINDING_SUMMARY,
            citations,
            _sha256(_finding_value(_FINDING_KIND, _FINDING_SUMMARY, citations)),
            True,
        )

    def to_wire(self) -> dict[str, object]:
        return {
            **_finding_value(self.kind, self.summary, self.citations),
            "findingSha256": self.finding_sha256,
            "requiresReview": self.requires_review,
        }


@dataclass(frozen=True, slots=True)
class AuditorReport:
    generation_sha256: str
    source_admission_sha256: str
    evidence_sha256: str
    findings: tuple[AuditorFinding, ...]
    report_sha256: str
    citation_sha256: str
    canonical: bool
    requires_review: bool

    def __post_init__(self) -> None:
        if (
            not _valid_sha256(self.generation_sha256)
            or not _valid_sha256(self.source_admission_sha256)
            or not _valid_sha256(self.evidence_sha256)
            or not _valid_sha256(self.report_sha256)
            or not _valid_sha256(self.citation_sha256)
            or not isinstance(self.findings, tuple)
            or not 1 <= len(self.findings) <= AUDITOR_MAXIMUM_FINDINGS
            or any(not isinstance(item, AuditorFinding) for item in self.findings)
            or len({item.finding_sha256 for item in self.findings})
            != len(self.findings)
            or self.citation_sha256 != auditor_report_citation_sha256(self.findings)
            or self.report_sha256 != auditor_report_sha256(self)
            or self.canonical is not False
            or self.requires_review is not True
        ):
            raise ValueError("auditor report is invalid")

    @classmethod
    def create(
        cls,
        *,
        generation_sha256: str,
        source_admission_sha256: str,
        evidence_sha256: str,
        findings: tuple[AuditorFinding, ...],
    ) -> AuditorReport:
        citation_sha256 = auditor_report_citation_sha256(findings)
        value = _report_value(
            generation_sha256=generation_sha256,
            source_admission_sha256=source_admission_sha256,
            evidence_sha256=evidence_sha256,
            findings=findings,
            citation_sha256=citation_sha256,
        )
        return cls(
            generation_sha256,
            source_admission_sha256,
            evidence_sha256,
            findings,
            _sha256(value),
            citation_sha256,
            False,
            True,
        )

    def to_wire(self) -> dict[str, object]:
        return {
            **_report_value(
                generation_sha256=self.generation_sha256,
                source_admission_sha256=self.source_admission_sha256,
                evidence_sha256=self.evidence_sha256,
                findings=self.findings,
                citation_sha256=self.citation_sha256,
            ),
            "reportSha256": self.report_sha256,
        }


class PostgresAuditorEvidenceReader:
    """Run one fixed permission-safe lexical read for an admitted Auditor."""

    def __init__(self, connection_factory: PrivatePostgresConnectionFactory) -> None:
        self._connection_factory = connection_factory
        self._tools = GovernedKnowledgeTools(
            KnowledgeAgentAuthority(
                (
                    KnowledgeAgentProfile(
                        agent_id=AUDITOR_AGENT_ID,
                        capabilities=_KNOWLEDGE_CAPABILITIES,
                        purposes=frozenset({AUDITOR_KNOWLEDGE_PURPOSE}),
                        maximum_results=AUDITOR_MAXIMUM_EVIDENCE_ITEMS,
                        maximum_output_characters=AUDITOR_MAXIMUM_EVIDENCE_CHARACTERS,
                        statement_timeout_milliseconds=(
                            AUDITOR_STATEMENT_TIMEOUT_MILLISECONDS
                        ),
                    ),
                )
            )
        )

    def read(
        self,
        request: AuditorRequest,
        *,
        principal: AuthenticatedPrincipal,
        cancellation: threading.Event,
    ) -> AuditorEvidencePack:
        if not isinstance(request, AuditorRequest):
            raise TypeError("auditor request type is invalid")
        if not isinstance(principal, AuthenticatedPrincipal):
            raise TypeError("auditor principal type is invalid")
        if not isinstance(cancellation, threading.Event):
            raise TypeError("auditor cancellation type is invalid")
        with self._connection_factory() as connection:
            response = self._tools.execute(
                connection,
                principal=principal.key,
                agent_id=AUDITOR_AGENT_ID,
                request=SearchKnowledgeRequest(
                    purpose=AUDITOR_KNOWLEDGE_PURPOSE,
                    search_text=request.focus,
                    maximum_results=AUDITOR_MAXIMUM_EVIDENCE_ITEMS,
                    expected_generation_sha256=request.expected_generation_sha256,
                ),
                cancellation=cancellation,
            )
            if cancellation.is_set():
                raise KnowledgeToolCancelled("auditor evidence read was cancelled")
            with connection.transaction():
                source_admission_sha256 = _source_admission_sha256(
                    connection,
                    tenant_id=principal.tenant_id,
                    generation_sha256=response.generation_sha256,
                )
        evidence = _evidence_from_tool_response(
            response,
            source_admission_sha256=source_admission_sha256,
        )
        validate_auditor_evidence(request, evidence)
        return evidence


class PostgresAuditorEvidenceVerifier:
    def __init__(self, connection_factory: PrivatePostgresConnectionFactory) -> None:
        self._connection_factory = connection_factory

    def verify(
        self,
        request: AuditorRequest,
        evidence: AuditorEvidencePack,
        *,
        principal: AuthenticatedPrincipal,
        cancellation: threading.Event,
    ) -> None:
        if not isinstance(cancellation, threading.Event):
            raise TypeError("auditor cancellation type is invalid")
        with self._connection_factory() as connection:
            with connection.transaction():
                current = run_cancellable_database_operation(
                    connection,
                    cancellation,
                    lambda: read_auditor_evidence_in_transaction(
                        connection,
                        request,
                        principal=principal,
                    ),
                )
        validate_auditor_evidence_current(request, evidence, current)


def auditor_request_sha256(request: AuditorRequest) -> str:
    if not isinstance(request, AuditorRequest):
        raise TypeError("auditor request type is invalid")
    return _sha256(
        {
            "expectedGenerationSha256": request.expected_generation_sha256,
            "focus": request.focus,
            "maximumFindings": request.maximum_findings,
        }
    )


def auditor_evidence_sha256(evidence: AuditorEvidencePack) -> str:
    if not isinstance(evidence, AuditorEvidencePack):
        raise TypeError("auditor evidence type is invalid")
    return _sha256(
        _evidence_value(
            generation_sha256=evidence.generation_sha256,
            source_admission_sha256=evidence.source_admission_sha256,
            permission_hash=evidence.permission_hash,
            authorization_hash=evidence.authorization_hash,
            items=evidence.items,
            output_budget_exhausted=evidence.output_budget_exhausted,
        )
    )


def auditor_work_sha256(
    request: AuditorRequest,
    evidence: AuditorEvidencePack,
) -> str:
    validate_auditor_evidence(request, evidence)
    return _sha256(
        {
            "evidenceSha256": evidence.evidence_sha256,
            "requestSha256": auditor_request_sha256(request),
        }
    )


def auditor_finding_sha256(finding: AuditorFinding) -> str:
    if not isinstance(finding, AuditorFinding):
        raise TypeError("auditor finding type is invalid")
    return _sha256(_finding_value(finding.kind, finding.summary, finding.citations))


def auditor_report_citation_sha256(findings: tuple[AuditorFinding, ...]) -> str:
    if (
        not isinstance(findings, tuple)
        or not findings
        or any(not isinstance(finding, AuditorFinding) for finding in findings)
    ):
        raise ValueError("auditor report citations are invalid")
    return _sha256(
        [[citation.to_wire() for citation in finding.citations] for finding in findings]
    )


def auditor_report_sha256(report: AuditorReport) -> str:
    if not isinstance(report, AuditorReport):
        raise TypeError("auditor report type is invalid")
    return _sha256(
        _report_value(
            generation_sha256=report.generation_sha256,
            source_admission_sha256=report.source_admission_sha256,
            evidence_sha256=report.evidence_sha256,
            findings=report.findings,
            citation_sha256=report.citation_sha256,
        )
    )


def build_auditor_report(
    request: AuditorRequest,
    evidence: AuditorEvidencePack,
    decision: AuditorDecision,
) -> AuditorReport | None:
    validate_auditor_evidence(request, evidence)
    outcome = getattr(decision, "outcome", None)
    pairs = getattr(decision, "finding_pairs", None)
    if outcome == "evidence-unavailable" and pairs == ():
        return None
    if (
        outcome != "report"
        or not isinstance(pairs, tuple)
        or not 1 <= len(pairs) <= request.maximum_findings
    ):
        raise ValueError("auditor decision differs from the report contract")
    canonical: list[tuple[int, int]] = []
    for pair in pairs:
        left = getattr(pair, "left_evidence_index", None)
        right = getattr(pair, "right_evidence_index", None)
        if (
            isinstance(left, bool)
            or not isinstance(left, int)
            or isinstance(right, bool)
            or not isinstance(right, int)
            or left < 0
            or right < 0
            or left == right
        ):
            raise ValueError("auditor finding pair is invalid")
        canonical.append(tuple(sorted((left, right))))
    if len(set(canonical)) != len(canonical):
        raise ValueError("auditor finding pairs are duplicated")
    canonical.sort()
    try:
        findings = tuple(
            AuditorFinding.create((evidence.items[left], evidence.items[right]))
            for left, right in canonical
        )
    except (IndexError, TypeError) as error:
        raise ValueError("auditor finding indexes are invalid") from error
    report = AuditorReport.create(
        generation_sha256=evidence.generation_sha256,
        source_admission_sha256=evidence.source_admission_sha256,
        evidence_sha256=evidence.evidence_sha256,
        findings=findings,
    )
    validate_auditor_report(request, evidence, report)
    return report


def validate_auditor_evidence(
    request: AuditorRequest,
    evidence: AuditorEvidencePack,
) -> None:
    if (
        not isinstance(request, AuditorRequest)
        or not isinstance(evidence, AuditorEvidencePack)
        or (
            request.expected_generation_sha256 is not None
            and evidence.generation_sha256 != request.expected_generation_sha256
        )
        or evidence.evidence_sha256 != auditor_evidence_sha256(evidence)
    ):
        raise ValueError("auditor evidence differs from the request")


def validate_auditor_evidence_current(
    request: AuditorRequest,
    evidence: AuditorEvidencePack,
    current_evidence: AuditorEvidencePack,
) -> None:
    validate_auditor_evidence(request, evidence)
    validate_auditor_evidence(request, current_evidence)
    if current_evidence != evidence:
        raise AuditorEvidenceChanged("auditor evidence changed under current authority")


def validate_auditor_report(
    request: AuditorRequest,
    evidence: AuditorEvidencePack,
    report: AuditorReport,
) -> None:
    validate_auditor_evidence(request, evidence)
    if (
        not isinstance(report, AuditorReport)
        or report.generation_sha256 != evidence.generation_sha256
        or report.source_admission_sha256 != evidence.source_admission_sha256
        or report.evidence_sha256 != evidence.evidence_sha256
        or not 1 <= len(report.findings) <= request.maximum_findings
        or report.canonical is not False
        or report.requires_review is not True
    ):
        raise ValueError("auditor report differs from its evidence")
    pairs: list[tuple[int, int]] = []
    for finding in report.findings:
        if any(item not in evidence.items for item in finding.citations):
            raise ValueError("auditor finding citation is unavailable")
        indexes = tuple(evidence.items.index(item) for item in finding.citations)
        if indexes[0] >= indexes[1]:
            raise ValueError("auditor finding citation order is invalid")
        pairs.append(indexes)
    if pairs != sorted(pairs) or len(set(pairs)) != len(pairs):
        raise ValueError("auditor report finding order is invalid")


def read_auditor_evidence_in_transaction(
    connection: Connection[object],
    request: AuditorRequest,
    *,
    principal: AuthenticatedPrincipal,
) -> AuditorEvidencePack:
    if connection.info.transaction_status is TransactionStatus.IDLE:
        raise RuntimeError("auditor evidence requires an owned transaction")
    if not isinstance(request, AuditorRequest):
        raise TypeError("auditor request type is invalid")
    if not isinstance(principal, AuthenticatedPrincipal):
        raise TypeError("auditor principal type is invalid")
    search = search_postgres_knowledge_lexical(
        connection,
        principal=principal.key,
        purpose=AUDITOR_KNOWLEDGE_PURPOSE,
        agent_capabilities=_KNOWLEDGE_CAPABILITIES,
        search_text=request.focus,
        maximum_results=AUDITOR_MAXIMUM_EVIDENCE_ITEMS,
        expected_generation_sha256=request.expected_generation_sha256,
    )
    source_admission_sha256 = _source_admission_sha256(
        connection,
        tenant_id=principal.tenant_id,
        generation_sha256=search.generation_sha256,
    )
    items, exhausted = _bounded_search_items(search.results)
    return AuditorEvidencePack.create(
        generation_sha256=search.generation_sha256,
        source_admission_sha256=source_admission_sha256,
        permission_hash=search.permission_hash,
        authorization_hash=search.authorization_hash,
        items=items,
        output_budget_exhausted=exhausted,
    )


def _source_admission_sha256(
    connection: Connection[object],
    *,
    tenant_id: str,
    generation_sha256: str,
) -> str:
    row = connection.execute(
        """SELECT source_admission_sha256, source_revision
           FROM yap_knowledge_builds
           WHERE tenant_id = %s AND generation_sha256 = %s""",
        (tenant_id, generation_sha256),
    ).fetchone()
    if row is None:
        raise LookupError("auditor knowledge generation is unavailable")
    admission = require_knowledge_source_admission(
        connection,
        tenant_id=tenant_id,
        admission_sha256=str(row[0]),
        generation_sha256=generation_sha256,
        source_revision=str(row[1]),
    )
    return admission.admission_sha256


def _evidence_from_tool_response(
    response: KnowledgeToolResponse,
    *,
    source_admission_sha256: str,
) -> AuditorEvidencePack:
    if (
        not isinstance(response, KnowledgeToolResponse)
        or response.operation != "search"
    ):
        raise ValueError("auditor tool response differs from the contract")
    items: list[LibrarianEvidenceItem] = []
    for item in response.items:
        citation = item.citation
        if (
            item.text is None
            or item.relationship_type is not None
            or item.target_concept_id is not None
            or citation.char_start is None
            or citation.char_end is None
        ):
            raise ValueError("auditor tool item differs from the contract")
        items.append(
            LibrarianEvidenceItem(
                concept_id=citation.concept_id,
                source_revision=citation.source_revision,
                content_sha256=citation.content_sha256,
                char_start=citation.char_start,
                char_end=citation.char_end,
                text=item.text,
            )
        )
    return AuditorEvidencePack.create(
        generation_sha256=response.generation_sha256,
        source_admission_sha256=source_admission_sha256,
        permission_hash=response.permission_hash,
        authorization_hash=response.authorization_hash,
        items=tuple(items),
        output_budget_exhausted=response.output_budget_exhausted,
    )


def _bounded_search_items(
    results: tuple[object, ...],
) -> tuple[tuple[LibrarianEvidenceItem, ...], bool]:
    output: list[LibrarianEvidenceItem] = []
    used = 0
    exhausted = False
    for result in results:
        item = LibrarianEvidenceItem(
            concept_id=result.concept_id,
            source_revision=result.source_revision,
            content_sha256=result.content_sha256,
            char_start=result.char_start,
            char_end=result.char_end,
            text=result.text,
        )
        size = _item_character_count(item)
        if used + size > AUDITOR_MAXIMUM_EVIDENCE_CHARACTERS:
            exhausted = True
            break
        used += size
        output.append(item)
    return tuple(output), exhausted


def _evidence_value(
    *,
    generation_sha256: str,
    source_admission_sha256: str,
    permission_hash: str,
    authorization_hash: str,
    items: tuple[LibrarianEvidenceItem, ...],
    output_budget_exhausted: bool,
) -> dict[str, object]:
    return {
        "generationSha256": generation_sha256,
        "sourceAdmissionSha256": source_admission_sha256,
        "permissionHash": permission_hash,
        "authorizationHash": authorization_hash,
        "items": [item.to_wire() for item in items],
        "outputBudgetExhausted": output_budget_exhausted,
    }


def _finding_value(
    kind: str,
    summary: str,
    citations: tuple[LibrarianEvidenceItem, LibrarianEvidenceItem],
) -> dict[str, object]:
    return {
        "kind": kind,
        "summary": summary,
        "citations": [item.to_wire() for item in citations],
    }


def _report_value(
    *,
    generation_sha256: str,
    source_admission_sha256: str,
    evidence_sha256: str,
    findings: tuple[AuditorFinding, ...],
    citation_sha256: str,
) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "generationSha256": generation_sha256,
        "sourceAdmissionSha256": source_admission_sha256,
        "evidenceSha256": evidence_sha256,
        "findings": [finding.to_wire() for finding in findings],
        "citationSha256": citation_sha256,
        "canonical": False,
        "requiresReview": True,
    }


def _citation_identity(item: LibrarianEvidenceItem) -> tuple[object, ...]:
    return (
        item.concept_id,
        item.source_revision,
        item.content_sha256,
        item.char_start,
        item.char_end,
    )


def _item_character_count(item: LibrarianEvidenceItem) -> int:
    return sum(
        len(value)
        for value in (
            item.concept_id,
            item.source_revision,
            item.content_sha256,
            item.text,
        )
    )


def _evidence_character_count(items: tuple[LibrarianEvidenceItem, ...]) -> int:
    return sum(_item_character_count(item) for item in items)


def _evidence_wire_bytes(evidence: AuditorEvidencePack) -> int:
    return len(
        _canonical_json(
            evidence.to_wire() if _valid_sha256(evidence.evidence_sha256) else {}
        )
    )


def _valid_sha256(value: object) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _utf8(value: object, field: str) -> None:
    if not isinstance(value, str):
        raise ValueError(f"{field} is invalid")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError(f"{field} is invalid") from error


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


__all__ = [
    "AUDITOR_AGENT_ID",
    "AUDITOR_KNOWLEDGE_PURPOSE",
    "AUDITOR_MAXIMUM_EVIDENCE_CHARACTERS",
    "AUDITOR_MAXIMUM_EVIDENCE_ITEMS",
    "AUDITOR_MAXIMUM_EVIDENCE_WIRE_BYTES",
    "AUDITOR_MAXIMUM_FINDINGS",
    "AUDITOR_STATEMENT_TIMEOUT_MILLISECONDS",
    "AuditorEvidenceChanged",
    "AuditorEvidencePack",
    "AuditorFinding",
    "AuditorReport",
    "AuditorRequest",
    "PostgresAuditorEvidenceReader",
    "PostgresAuditorEvidenceVerifier",
    "auditor_evidence_sha256",
    "auditor_finding_sha256",
    "auditor_report_citation_sha256",
    "auditor_report_sha256",
    "auditor_request_sha256",
    "auditor_work_sha256",
    "build_auditor_report",
    "read_auditor_evidence_in_transaction",
    "validate_auditor_evidence",
    "validate_auditor_evidence_current",
    "validate_auditor_report",
]
