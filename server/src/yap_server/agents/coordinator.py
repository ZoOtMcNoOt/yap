from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import TYPE_CHECKING

from yap_server.knowledge.knowledge_tool_contract import (
    validate_bounded_text,
    validate_expected_generation,
    validate_integer,
    validate_search_text,
)

from .librarian import LibrarianEvidenceItem

if TYPE_CHECKING:
    from .coordinator_model import CoordinatorDecision


COORDINATOR_MAXIMUM_CANDIDATES = 8
COORDINATOR_MAXIMUM_ITEMS = 5
COORDINATOR_MAXIMUM_CITATIONS_PER_CANDIDATE = 8
COORDINATOR_MAXIMUM_PROPOSAL_CHARACTERS = 2_048
COORDINATOR_MAXIMUM_CANDIDATE_CHARACTERS = 12_288
COORDINATOR_MAXIMUM_EVIDENCE_CHARACTERS = 32_768
COORDINATOR_MAXIMUM_EVIDENCE_WIRE_BYTES = 131_072

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_PROPOSAL_TYPES = {"summary", "relationship"}


@dataclass(frozen=True, slots=True)
class CoordinatorRequest:
    objective: str
    maximum_items: int
    expected_generation_sha256: str | None

    def __post_init__(self) -> None:
        objective = validate_search_text(self.objective)
        _utf8(objective, "coordinator objective")
        if "\0" in objective:
            raise ValueError("coordinator objective is invalid")
        validate_integer(
            self.maximum_items,
            minimum=1,
            maximum=COORDINATOR_MAXIMUM_ITEMS,
            field="coordinator item limit",
        )
        validate_expected_generation(self.expected_generation_sha256)

    @classmethod
    def from_wire(cls, value: object) -> CoordinatorRequest:
        if not isinstance(value, dict) or set(value) != {
            "schemaVersion",
            "objective",
            "maximumItems",
            "expectedGenerationSha256",
        }:
            raise ValueError("coordinator request fields differ from the contract")
        if type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1:
            raise ValueError("coordinator request schema is unsupported")
        return cls(
            objective=value["objective"],
            maximum_items=value["maximumItems"],
            expected_generation_sha256=value["expectedGenerationSha256"],
        )

    def to_wire(self) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "objective": self.objective,
            "maximumItems": self.maximum_items,
            "expectedGenerationSha256": self.expected_generation_sha256,
        }


@dataclass(frozen=True, slots=True)
class CoordinatorProposalCandidate:
    proposal_id: str
    curator_request_id: str
    curator_submission_id: str
    curator_request_sha256: str
    curator_work_sha256: str
    curator_evidence_sha256: str
    generation_sha256: str
    proposal_type: str
    proposed_content: str
    inherited_permission_sha256: str
    proposal_permission_hash: str
    proposal_authorization_hash: str
    citations: tuple[LibrarianEvidenceItem, ...]
    citation_sha256: str
    candidate_sha256: str

    def __post_init__(self) -> None:
        if (
            not _valid_sha256(self.proposal_id)
            or not _valid_request_id(self.curator_request_id)
            or not _valid_request_id(self.curator_submission_id)
            or not _valid_sha256(self.curator_request_sha256)
            or not _valid_sha256(self.curator_work_sha256)
            or not _valid_sha256(self.curator_evidence_sha256)
            or not _valid_sha256(self.generation_sha256)
            or self.proposal_type not in _PROPOSAL_TYPES
            or not _valid_sha256(self.inherited_permission_sha256)
            or not _valid_sha256(self.proposal_permission_hash)
            or not _valid_sha256(self.proposal_authorization_hash)
            or not _valid_sha256(self.citation_sha256)
            or not _valid_sha256(self.candidate_sha256)
        ):
            raise ValueError("coordinator proposal identity is invalid")
        _bounded_content(
            self.proposed_content,
            field="coordinator proposed content",
            maximum=COORDINATOR_MAXIMUM_PROPOSAL_CHARACTERS,
        )
        if (
            not isinstance(self.citations, tuple)
            or not 1
            <= len(self.citations)
            <= COORDINATOR_MAXIMUM_CITATIONS_PER_CANDIDATE
            or any(
                not isinstance(citation, LibrarianEvidenceItem)
                for citation in self.citations
            )
            or len({_citation_identity(item) for item in self.citations})
            != len(self.citations)
            or _candidate_character_count(self)
            > COORDINATOR_MAXIMUM_CANDIDATE_CHARACTERS
            or self.citation_sha256 != coordinator_citation_sha256(self.citations)
            or self.candidate_sha256 != coordinator_candidate_sha256(self)
        ):
            raise ValueError("coordinator proposal candidate is invalid")

    @classmethod
    def create(
        cls,
        *,
        proposal_id: str,
        curator_request_id: str,
        curator_submission_id: str,
        curator_request_sha256: str,
        curator_work_sha256: str,
        curator_evidence_sha256: str,
        generation_sha256: str,
        proposal_type: str,
        proposed_content: str,
        inherited_permission_sha256: str,
        proposal_permission_hash: str,
        proposal_authorization_hash: str,
        citations: tuple[LibrarianEvidenceItem, ...],
    ) -> CoordinatorProposalCandidate:
        citation_sha256 = coordinator_citation_sha256(citations)
        candidate_sha256 = _sha256(
            _candidate_authority_value(
                proposal_id=proposal_id,
                curator_request_id=curator_request_id,
                curator_submission_id=curator_submission_id,
                curator_request_sha256=curator_request_sha256,
                curator_work_sha256=curator_work_sha256,
                curator_evidence_sha256=curator_evidence_sha256,
                generation_sha256=generation_sha256,
                proposal_type=proposal_type,
                proposed_content=proposed_content,
                inherited_permission_sha256=inherited_permission_sha256,
                proposal_permission_hash=proposal_permission_hash,
                proposal_authorization_hash=proposal_authorization_hash,
                citations=citations,
                citation_sha256=citation_sha256,
            )
        )
        return cls(
            proposal_id,
            curator_request_id,
            curator_submission_id,
            curator_request_sha256,
            curator_work_sha256,
            curator_evidence_sha256,
            generation_sha256,
            proposal_type,
            proposed_content,
            inherited_permission_sha256,
            proposal_permission_hash,
            proposal_authorization_hash,
            citations,
            citation_sha256,
            candidate_sha256,
        )

    def to_wire(self) -> dict[str, object]:
        """Return the reviewed bundle projection without internal audit identities."""

        return {
            "proposalId": self.proposal_id,
            "proposalType": self.proposal_type,
            "proposedContent": self.proposed_content,
            "citations": [item.to_wire() for item in self.citations],
            "citationSha256": self.citation_sha256,
            "candidateSha256": self.candidate_sha256,
        }


@dataclass(frozen=True, slots=True)
class CoordinatorEvidencePack:
    generation_sha256: str
    permission_hash: str
    authorization_hash: str
    candidates: tuple[CoordinatorProposalCandidate, ...]
    output_budget_exhausted: bool
    evidence_sha256: str

    def __post_init__(self) -> None:
        if any(
            not _valid_sha256(value)
            for value in (
                self.generation_sha256,
                self.permission_hash,
                self.authorization_hash,
                self.evidence_sha256,
            )
        ):
            raise ValueError("coordinator evidence identity is invalid")
        if not isinstance(self.candidates, tuple) or any(
            not isinstance(candidate, CoordinatorProposalCandidate)
            for candidate in self.candidates
        ):
            raise ValueError("coordinator evidence candidates are invalid")
        if len(self.candidates) > COORDINATOR_MAXIMUM_CANDIDATES:
            raise ValueError("coordinator evidence candidate limit is invalid")
        if any(
            candidate.generation_sha256 != self.generation_sha256
            for candidate in self.candidates
        ):
            raise ValueError("coordinator evidence generation is invalid")
        if (
            len({candidate.proposal_id for candidate in self.candidates})
            != len(self.candidates)
            or len({candidate.candidate_sha256 for candidate in self.candidates})
            != len(self.candidates)
            or not isinstance(self.output_budget_exhausted, bool)
            or _evidence_character_count(self.candidates)
            > COORDINATOR_MAXIMUM_EVIDENCE_CHARACTERS
            or _evidence_wire_bytes(self) > COORDINATOR_MAXIMUM_EVIDENCE_WIRE_BYTES
            or self.evidence_sha256 != coordinator_evidence_sha256(self)
        ):
            raise ValueError("coordinator evidence pack is invalid")

    @classmethod
    def create(
        cls,
        *,
        generation_sha256: str,
        permission_hash: str,
        authorization_hash: str,
        candidates: tuple[CoordinatorProposalCandidate, ...],
        output_budget_exhausted: bool,
    ) -> CoordinatorEvidencePack:
        evidence_sha256 = _sha256(
            _evidence_value(
                generation_sha256=generation_sha256,
                permission_hash=permission_hash,
                authorization_hash=authorization_hash,
                candidates=candidates,
                output_budget_exhausted=output_budget_exhausted,
            )
        )
        return cls(
            generation_sha256,
            permission_hash,
            authorization_hash,
            candidates,
            output_budget_exhausted,
            evidence_sha256,
        )

    def to_wire(self) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "generationSha256": self.generation_sha256,
            "permissionHash": self.permission_hash,
            "authorizationHash": self.authorization_hash,
            "candidates": [
                _candidate_authority_wire(candidate) for candidate in self.candidates
            ],
            "outputBudgetExhausted": self.output_budget_exhausted,
            "evidenceSha256": self.evidence_sha256,
        }


@dataclass(frozen=True, slots=True)
class CoordinatorProposalBundle:
    generation_sha256: str
    evidence_sha256: str
    items: tuple[CoordinatorProposalCandidate, ...]
    bundle_sha256: str
    citation_sha256: str

    def __post_init__(self) -> None:
        if (
            not _valid_sha256(self.generation_sha256)
            or not _valid_sha256(self.evidence_sha256)
            or not _valid_sha256(self.bundle_sha256)
            or not _valid_sha256(self.citation_sha256)
            or not isinstance(self.items, tuple)
            or not 1 <= len(self.items) <= COORDINATOR_MAXIMUM_ITEMS
            or any(
                not isinstance(item, CoordinatorProposalCandidate)
                for item in self.items
            )
            or len({item.proposal_id for item in self.items}) != len(self.items)
            or any(
                item.generation_sha256 != self.generation_sha256 for item in self.items
            )
            or self.citation_sha256 != coordinator_bundle_citation_sha256(self.items)
            or self.bundle_sha256 != coordinator_bundle_sha256(self)
        ):
            raise ValueError("coordinator proposal bundle is invalid")

    @classmethod
    def create(
        cls,
        *,
        generation_sha256: str,
        evidence_sha256: str,
        items: tuple[CoordinatorProposalCandidate, ...],
    ) -> CoordinatorProposalBundle:
        citation_sha256 = coordinator_bundle_citation_sha256(items)
        bundle_sha256 = _sha256(
            _bundle_value(
                generation_sha256=generation_sha256,
                evidence_sha256=evidence_sha256,
                items=items,
                citation_sha256=citation_sha256,
            )
        )
        return cls(
            generation_sha256,
            evidence_sha256,
            items,
            bundle_sha256,
            citation_sha256,
        )

    def to_wire(self) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "generationSha256": self.generation_sha256,
            "evidenceSha256": self.evidence_sha256,
            "items": [item.to_wire() for item in self.items],
            "bundleSha256": self.bundle_sha256,
            "citationSha256": self.citation_sha256,
            "canonical": False,
            "requiresReview": True,
        }


def coordinator_request_sha256(request: CoordinatorRequest) -> str:
    if not isinstance(request, CoordinatorRequest):
        raise TypeError("coordinator request type is invalid")
    return _sha256(
        {
            "expectedGenerationSha256": request.expected_generation_sha256,
            "maximumItems": request.maximum_items,
            "objective": request.objective,
        }
    )


def coordinator_candidate_sha256(candidate: CoordinatorProposalCandidate) -> str:
    if not isinstance(candidate, CoordinatorProposalCandidate):
        raise TypeError("coordinator proposal candidate type is invalid")
    return _sha256(
        _candidate_authority_value(
            proposal_id=candidate.proposal_id,
            curator_request_id=candidate.curator_request_id,
            curator_submission_id=candidate.curator_submission_id,
            curator_request_sha256=candidate.curator_request_sha256,
            curator_work_sha256=candidate.curator_work_sha256,
            curator_evidence_sha256=candidate.curator_evidence_sha256,
            generation_sha256=candidate.generation_sha256,
            proposal_type=candidate.proposal_type,
            proposed_content=candidate.proposed_content,
            inherited_permission_sha256=candidate.inherited_permission_sha256,
            proposal_permission_hash=candidate.proposal_permission_hash,
            proposal_authorization_hash=candidate.proposal_authorization_hash,
            citations=candidate.citations,
            citation_sha256=candidate.citation_sha256,
        )
    )


def coordinator_citation_sha256(
    citations: tuple[LibrarianEvidenceItem, ...],
) -> str:
    if (
        not isinstance(citations, tuple)
        or not citations
        or any(not isinstance(item, LibrarianEvidenceItem) for item in citations)
    ):
        raise ValueError("coordinator citations are invalid")
    return _sha256([item.to_wire() for item in citations])


def coordinator_evidence_sha256(evidence: CoordinatorEvidencePack) -> str:
    if not isinstance(evidence, CoordinatorEvidencePack):
        raise TypeError("coordinator evidence type is invalid")
    return _sha256(
        _evidence_value(
            generation_sha256=evidence.generation_sha256,
            permission_hash=evidence.permission_hash,
            authorization_hash=evidence.authorization_hash,
            candidates=evidence.candidates,
            output_budget_exhausted=evidence.output_budget_exhausted,
        )
    )


def coordinator_work_sha256(
    request: CoordinatorRequest,
    evidence: CoordinatorEvidencePack,
) -> str:
    validate_coordinator_evidence(request, evidence)
    return _sha256(
        {
            "evidenceSha256": evidence.evidence_sha256,
            "requestSha256": coordinator_request_sha256(request),
        }
    )


def coordinator_bundle_citation_sha256(
    items: tuple[CoordinatorProposalCandidate, ...],
) -> str:
    if (
        not isinstance(items, tuple)
        or not items
        or any(not isinstance(item, CoordinatorProposalCandidate) for item in items)
    ):
        raise ValueError("coordinator bundle citations are invalid")
    return _sha256(
        [
            {
                "proposalId": item.proposal_id,
                "citations": [citation.to_wire() for citation in item.citations],
            }
            for item in items
        ]
    )


def coordinator_bundle_sha256(bundle: CoordinatorProposalBundle) -> str:
    if not isinstance(bundle, CoordinatorProposalBundle):
        raise TypeError("coordinator bundle type is invalid")
    return _sha256(
        _bundle_value(
            generation_sha256=bundle.generation_sha256,
            evidence_sha256=bundle.evidence_sha256,
            items=bundle.items,
            citation_sha256=bundle.citation_sha256,
        )
    )


def build_coordinator_proposal_bundle(
    request: CoordinatorRequest,
    evidence: CoordinatorEvidencePack,
    decision: CoordinatorDecision,
) -> CoordinatorProposalBundle | None:
    validate_coordinator_evidence(request, evidence)
    outcome = getattr(decision, "outcome", None)
    indexes = getattr(decision, "proposal_indexes", None)
    if outcome == "evidence-unavailable" and indexes == ():
        return None
    if (
        outcome != "bundle"
        or not isinstance(indexes, tuple)
        or not 1 <= len(indexes) <= request.maximum_items
        or any(
            isinstance(index, bool) or not isinstance(index, int) or index < 0
            for index in indexes
        )
        or len(set(indexes)) != len(indexes)
    ):
        raise ValueError("coordinator decision differs from the bundle contract")
    try:
        items = tuple(evidence.candidates[index] for index in indexes)
    except (IndexError, TypeError) as error:
        raise ValueError("coordinator proposal indexes are invalid") from error
    bundle = CoordinatorProposalBundle.create(
        generation_sha256=evidence.generation_sha256,
        evidence_sha256=evidence.evidence_sha256,
        items=items,
    )
    validate_coordinator_bundle(request, evidence, bundle)
    return bundle


def validate_coordinator_evidence(
    request: CoordinatorRequest,
    evidence: CoordinatorEvidencePack,
) -> None:
    if not isinstance(request, CoordinatorRequest):
        raise TypeError("coordinator request type is invalid")
    if not isinstance(evidence, CoordinatorEvidencePack):
        raise TypeError("coordinator evidence type is invalid")
    if (
        request.expected_generation_sha256 is not None
        and evidence.generation_sha256 != request.expected_generation_sha256
    ):
        raise ValueError("coordinator evidence generation differs from the request")
    if evidence.evidence_sha256 != coordinator_evidence_sha256(evidence):
        raise ValueError("coordinator evidence differs from the request")


def validate_coordinator_bundle(
    request: CoordinatorRequest,
    evidence: CoordinatorEvidencePack,
    bundle: CoordinatorProposalBundle,
) -> None:
    validate_coordinator_evidence(request, evidence)
    if (
        not isinstance(bundle, CoordinatorProposalBundle)
        or bundle.generation_sha256 != evidence.generation_sha256
        or bundle.evidence_sha256 != evidence.evidence_sha256
        or not 1 <= len(bundle.items) <= request.maximum_items
        or any(item not in evidence.candidates for item in bundle.items)
        or len({item.proposal_id for item in bundle.items}) != len(bundle.items)
        or bundle.bundle_sha256 != coordinator_bundle_sha256(bundle)
        or bundle.citation_sha256 != coordinator_bundle_citation_sha256(bundle.items)
    ):
        raise ValueError("coordinator bundle differs from its evidence")


def _candidate_authority_wire(
    candidate: CoordinatorProposalCandidate,
) -> dict[str, object]:
    return {
        **_candidate_authority_value(
            proposal_id=candidate.proposal_id,
            curator_request_id=candidate.curator_request_id,
            curator_submission_id=candidate.curator_submission_id,
            curator_request_sha256=candidate.curator_request_sha256,
            curator_work_sha256=candidate.curator_work_sha256,
            curator_evidence_sha256=candidate.curator_evidence_sha256,
            generation_sha256=candidate.generation_sha256,
            proposal_type=candidate.proposal_type,
            proposed_content=candidate.proposed_content,
            inherited_permission_sha256=candidate.inherited_permission_sha256,
            proposal_permission_hash=candidate.proposal_permission_hash,
            proposal_authorization_hash=candidate.proposal_authorization_hash,
            citations=candidate.citations,
            citation_sha256=candidate.citation_sha256,
        ),
        "candidateSha256": candidate.candidate_sha256,
    }


def _candidate_authority_value(
    *,
    proposal_id: str,
    curator_request_id: str,
    curator_submission_id: str,
    curator_request_sha256: str,
    curator_work_sha256: str,
    curator_evidence_sha256: str,
    generation_sha256: str,
    proposal_type: str,
    proposed_content: str,
    inherited_permission_sha256: str,
    proposal_permission_hash: str,
    proposal_authorization_hash: str,
    citations: tuple[LibrarianEvidenceItem, ...],
    citation_sha256: str,
) -> dict[str, object]:
    return {
        "proposalId": proposal_id,
        "curatorRequestId": curator_request_id,
        "curatorSubmissionId": curator_submission_id,
        "curatorRequestSha256": curator_request_sha256,
        "curatorWorkSha256": curator_work_sha256,
        "curatorEvidenceSha256": curator_evidence_sha256,
        "generationSha256": generation_sha256,
        "proposalType": proposal_type,
        "proposedContent": proposed_content,
        "inheritedPermissionSha256": inherited_permission_sha256,
        "proposalPermissionHash": proposal_permission_hash,
        "proposalAuthorizationHash": proposal_authorization_hash,
        "citations": [item.to_wire() for item in citations],
        "citationSha256": citation_sha256,
    }


def _evidence_value(
    *,
    generation_sha256: str,
    permission_hash: str,
    authorization_hash: str,
    candidates: tuple[CoordinatorProposalCandidate, ...],
    output_budget_exhausted: bool,
) -> dict[str, object]:
    return {
        "generationSha256": generation_sha256,
        "permissionHash": permission_hash,
        "authorizationHash": authorization_hash,
        "candidates": [_candidate_authority_wire(item) for item in candidates],
        "outputBudgetExhausted": output_budget_exhausted,
    }


def _bundle_value(
    *,
    generation_sha256: str,
    evidence_sha256: str,
    items: tuple[CoordinatorProposalCandidate, ...],
    citation_sha256: str,
) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "generationSha256": generation_sha256,
        "evidenceSha256": evidence_sha256,
        "items": [item.to_wire() for item in items],
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


def _candidate_character_count(candidate: CoordinatorProposalCandidate) -> int:
    return sum(
        len(value)
        for value in (
            candidate.proposal_id,
            candidate.curator_request_id,
            candidate.curator_submission_id,
            candidate.curator_request_sha256,
            candidate.curator_work_sha256,
            candidate.curator_evidence_sha256,
            candidate.generation_sha256,
            candidate.proposal_type,
            candidate.proposed_content,
            candidate.inherited_permission_sha256,
            candidate.proposal_permission_hash,
            candidate.proposal_authorization_hash,
            candidate.citation_sha256,
            candidate.candidate_sha256,
        )
    ) + sum(
        len(value)
        for item in candidate.citations
        for value in (
            item.concept_id,
            item.source_revision,
            item.content_sha256,
            item.text,
        )
    )


def _evidence_character_count(
    candidates: tuple[CoordinatorProposalCandidate, ...],
) -> int:
    return sum(_candidate_character_count(item) for item in candidates)


def _evidence_wire_bytes(evidence: CoordinatorEvidencePack) -> int:
    value = {
        **_evidence_value(
            generation_sha256=evidence.generation_sha256,
            permission_hash=evidence.permission_hash,
            authorization_hash=evidence.authorization_hash,
            candidates=evidence.candidates,
            output_budget_exhausted=evidence.output_budget_exhausted,
        ),
        "schemaVersion": 1,
        "evidenceSha256": evidence.evidence_sha256,
    }
    return len(_canonical_json(value))


def _bounded_content(value: object, *, field: str, maximum: int) -> str:
    text = validate_bounded_text(value, field=field, maximum=maximum)
    if any(ord(character) < 32 and character not in "\n\t" for character in text):
        raise ValueError(f"{field} is invalid")
    _utf8(text, field)
    return text


def _valid_sha256(value: object) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _valid_request_id(value: object) -> bool:
    return isinstance(value, str) and _REQUEST_ID.fullmatch(value) is not None


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
    "COORDINATOR_MAXIMUM_CANDIDATES",
    "COORDINATOR_MAXIMUM_CANDIDATE_CHARACTERS",
    "COORDINATOR_MAXIMUM_CITATIONS_PER_CANDIDATE",
    "COORDINATOR_MAXIMUM_EVIDENCE_CHARACTERS",
    "COORDINATOR_MAXIMUM_EVIDENCE_WIRE_BYTES",
    "COORDINATOR_MAXIMUM_ITEMS",
    "COORDINATOR_MAXIMUM_PROPOSAL_CHARACTERS",
    "CoordinatorEvidencePack",
    "CoordinatorProposalBundle",
    "CoordinatorProposalCandidate",
    "CoordinatorRequest",
    "build_coordinator_proposal_bundle",
    "coordinator_bundle_citation_sha256",
    "coordinator_bundle_sha256",
    "coordinator_candidate_sha256",
    "coordinator_citation_sha256",
    "coordinator_evidence_sha256",
    "coordinator_request_sha256",
    "coordinator_work_sha256",
    "validate_coordinator_bundle",
    "validate_coordinator_evidence",
]
