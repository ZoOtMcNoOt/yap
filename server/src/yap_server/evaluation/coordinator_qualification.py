"""Public synthetic qualification for selection-only Coordinator bundles."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
import hashlib
import json
import math
from pathlib import Path
import re
import threading
import time
from types import MappingProxyType
from typing import Mapping, Protocol

from yap_server.agents.coordinator import (
    CoordinatorEvidencePack,
    CoordinatorProposalBundle,
    CoordinatorProposalCandidate,
    CoordinatorRequest,
    build_coordinator_proposal_bundle,
)
from yap_server.agents.coordinator_model import CoordinatorDecision
from yap_server.agents.coordinator_service import CoordinatorJobView
from yap_server.agents.curator import (
    CuratorEvidence,
    CuratorEvidenceItem,
    CuratorRequest,
    curator_request_sha256,
    curator_work_sha256,
)
from yap_server.agents.librarian import LibrarianEvidenceItem
from yap_server.knowledge.knowledge_tool_contract import ProposalCitation
from yap_server.private_artifact import read_json_object_with_identity

from .librarian_qualification import (
    LibrarianCompiledGeneration as CoordinatorCompiledGeneration,
    LibrarianExpectedSelector,
    LibrarianQualificationCase,
    LibrarianQualificationCorpus,
    LibrarianQualificationGeneration,
    LibrarianQualificationRenderedFile as CoordinatorQualificationRenderedFile,
    LibrarianQualificationRenderedGeneration as CoordinatorQualificationRenderedGeneration,
    LibrarianQualificationRenderedSource as CoordinatorQualificationRenderedSource,
    LibrarianQualificationRequest,
    LibrarianQualificationRun,
    LibrarianQualificationSource,
    bind_librarian_compiled_corpus,
    render_librarian_qualification_generations,
)


_SCOPE = "coordinator-proposal-bundle-selection"
_MAXIMUM_ACCEPTANCE_BYTES = 32 * 1024
_MAXIMUM_FIXTURE_BYTES = 256 * 1024
_IDENTITY = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_CONCEPT_ID = re.compile(r"^[a-z0-9][a-z0-9./-]{0,511}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_LEXICAL_TOKEN = re.compile(r"[A-Za-z0-9]+")
_MODES = frozenset(
    {
        "normal",
        "pre-cancelled",
        "client-cancelled",
        "deadline",
        "stale-generation",
        "invalid-output",
    }
)
_STATUSES = frozenset({"complete", "evidence-unavailable", "failed", "cancelled"})
_REASONS = frozenset(
    {
        None,
        "empty-result",
        "model-evidence-unavailable",
        "stale-generation",
        "invalid-output",
        "client-cancelled",
        "deadline-exceeded",
    }
)
_CONTROLLED_MODES = (
    "client-cancelled",
    "deadline",
    "invalid-output",
    "stale-generation",
    "pre-cancelled",
)
_PRIMARY_WAVE_TIMEOUT_SECONDS = 90.0
_WORKER_CONTAINMENT_SECONDS = 2.0


class CoordinatorQualificationExecutor(Protocol):
    def __call__(
        self,
        invocation: CoordinatorQualificationInvocation,
        cancellation: threading.Event,
    ) -> object: ...


@dataclass(frozen=True, slots=True)
class CoordinatorQualificationWave:
    wave_id: str
    case_order: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CoordinatorQualificationAcceptance:
    plan_sha256: str
    case_count: int
    owner_count: int
    invocation_count: int
    maximum_normal_p95_milliseconds: int
    synchronized_wave_count: int
    owners_per_synchronized_wave: int
    synchronized_invocation_count: int
    exact_synchronized_invocation_count: int
    exact_synchronized_wave_count: int
    complete_count: int
    unavailable_count: int
    failed_count: int
    cancelled_count: int
    exact_terminal_match_count: int
    exact_bundle_match_count: int
    unique_request_id_count: int
    bundle_count: int
    item_count: int
    citation_count: int
    terminal_mismatch_count: int
    warm_provider_repeatability_met: bool
    normal_p95_within_bound: bool
    server_derived_bundle_exact: bool
    server_owned_citations_exact: bool
    selection_order_exact: bool
    selection_only_contract_met: bool
    noncanonical_review_required_exact: bool
    hidden_only_indistinguishable: bool
    unavailable_bundle_absent: bool
    cancellation_failed_closed: bool
    deadline_failed_closed: bool
    stale_generation_failed_closed: bool
    invalid_output_failed_closed: bool
    worker_containment_met: bool
    synchronized_waves: tuple[CoordinatorQualificationWave, ...] = field(repr=False)

    def expected_public_evidence(self) -> dict[str, int | bool]:
        return {
            "schemaVersion": 2,
            "qualified": True,
            "caseCount": self.case_count,
            "ownerCount": self.owner_count,
            "invocationCount": self.invocation_count,
            "synchronizedWaveCount": self.synchronized_wave_count,
            "ownersPerSynchronizedWave": self.owners_per_synchronized_wave,
            "synchronizedInvocationCount": self.synchronized_invocation_count,
            "exactSynchronizedInvocationCount": self.exact_synchronized_invocation_count,
            "exactSynchronizedWaveCount": self.exact_synchronized_wave_count,
            "completeCount": self.complete_count,
            "unavailableCount": self.unavailable_count,
            "failedCount": self.failed_count,
            "cancelledCount": self.cancelled_count,
            "exactTerminalMatchCount": self.exact_terminal_match_count,
            "exactBundleMatchCount": self.exact_bundle_match_count,
            "uniqueRequestIdCount": self.unique_request_id_count,
            "bundleCount": self.bundle_count,
            "itemCount": self.item_count,
            "citationCount": self.citation_count,
            "terminalMismatchCount": self.terminal_mismatch_count,
            "warmProviderRepeatabilityMet": self.warm_provider_repeatability_met,
            "normalP95WithinBound": self.normal_p95_within_bound,
            "serverDerivedBundleExact": self.server_derived_bundle_exact,
            "serverOwnedCitationsExact": self.server_owned_citations_exact,
            "selectionOrderExact": self.selection_order_exact,
            "selectionOnlyContractMet": self.selection_only_contract_met,
            "noncanonicalReviewRequiredExact": self.noncanonical_review_required_exact,
            "hiddenOnlyIndistinguishable": self.hidden_only_indistinguishable,
            "unavailableBundleAbsent": self.unavailable_bundle_absent,
            "cancellationFailedClosed": self.cancellation_failed_closed,
            "deadlineFailedClosed": self.deadline_failed_closed,
            "staleGenerationFailedClosed": self.stale_generation_failed_closed,
            "invalidOutputFailedClosed": self.invalid_output_failed_closed,
            "workerContainmentMet": self.worker_containment_met,
        }


@dataclass(frozen=True, slots=True)
class CoordinatorQualificationSource:
    concept_id: str
    source_revision: str
    body: str
    evidence_quote: str
    visible_to_owner_ids: frozenset[str]
    linked_concept_ids: tuple[str, ...]
    retrieval_rank: int


@dataclass(frozen=True, slots=True)
class CoordinatorQualificationGeneration:
    generation_id: str
    generation_sha256: str
    sources: tuple[CoordinatorQualificationSource, ...]


@dataclass(frozen=True, slots=True)
class CoordinatorQualificationProposal:
    proposal_key: str
    owner_id: str
    generation_id: str
    proposal_type: str
    proposed_content: str
    source_concept_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CoordinatorQualificationRun:
    run_id: str
    mode: str
    expected_status: str
    expected_reason: str | None
    expected_selected_proposal_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CoordinatorQualificationRequest:
    objective: str
    maximum_items: int
    expected_generation_id: str


@dataclass(frozen=True, slots=True)
class CoordinatorQualificationCase:
    case_id: str
    owner_id: str
    active_generation_id: str
    request: CoordinatorQualificationRequest
    expected_candidate_proposal_keys: tuple[str, ...]
    runs: tuple[CoordinatorQualificationRun, ...]


@dataclass(frozen=True, slots=True)
class CoordinatorQualificationCorpus:
    corpus_id: str
    corpus_sha256: str
    tenant_id: str
    generations: tuple[CoordinatorQualificationGeneration, ...]
    proposals: tuple[CoordinatorQualificationProposal, ...]
    cases: tuple[CoordinatorQualificationCase, ...]


@dataclass(frozen=True, slots=True)
class CoordinatorQualificationProposalSeed:
    proposal_key: str
    owner_id: str
    request: CuratorRequest
    evidence: CuratorEvidence
    proposal_id: str
    inherited_permission_sha256: str
    proposal_permission_hash: str
    proposal_authorization_hash: str


@dataclass(frozen=True, slots=True)
class CoordinatorCompiledQualificationCorpus:
    corpus: CoordinatorQualificationCorpus
    tenant_id: str
    generation_sha256s: Mapping[str, str]
    proposal_seeds_by_key: Mapping[str, CoordinatorQualificationProposalSeed]


@dataclass(frozen=True, slots=True)
class CoordinatorExpectedView:
    status: str
    reason: str | None
    bundle: CoordinatorProposalBundle | None


@dataclass(frozen=True, slots=True)
class CoordinatorBoundQualificationCorpus:
    corpus: CoordinatorQualificationCorpus
    tenant_id: str
    generation_sha256s: Mapping[str, str]
    proposal_seeds_by_key: Mapping[str, CoordinatorQualificationProposalSeed]
    evidence_by_case: Mapping[str, CoordinatorEvidencePack]
    expected_views: Mapping[str, CoordinatorExpectedView]


@dataclass(frozen=True, slots=True)
class CoordinatorQualificationInvocation:
    invocation_id: str
    case_id: str
    run_id: str
    mode: str
    expected_view_id: str
    wave_id: str | None
    declared_position: int | None
    tenant_id: str
    owner_id: str
    objective: str
    maximum_items: int
    expected_generation_sha256: str


@dataclass(frozen=True, slots=True)
class CoordinatorQualificationObservation:
    invocation: CoordinatorQualificationInvocation = field(repr=False)
    expected: CoordinatorExpectedView = field(repr=False)
    observed: CoordinatorExpectedView | None = field(repr=False)
    request_id: str | None = field(repr=False)
    duration_milliseconds: int = field(repr=False)
    exact_match: bool
    failure_kind: str | None


@dataclass(frozen=True, slots=True)
class CoordinatorQualificationResult:
    public_evidence: dict[str, int | bool]
    observations: tuple[CoordinatorQualificationObservation, ...] = field(repr=False)


def load_coordinator_qualification_acceptance(
    path: Path,
) -> CoordinatorQualificationAcceptance:
    value, identity = read_json_object_with_identity(
        path,
        maximum_bytes=_MAXIMUM_ACCEPTANCE_BYTES,
        field="Coordinator qualification acceptance",
    )
    numeric = (
        "caseCount",
        "ownerCount",
        "invocationCount",
        "maximumNormalP95Milliseconds",
        "synchronizedWaveCount",
        "ownersPerSynchronizedWave",
        "synchronizedInvocationCount",
        "exactSynchronizedInvocationCount",
        "exactSynchronizedWaveCount",
        "completeCount",
        "unavailableCount",
        "failedCount",
        "cancelledCount",
        "exactTerminalMatchCount",
        "exactBundleMatchCount",
        "uniqueRequestIdCount",
        "bundleCount",
        "itemCount",
        "citationCount",
        "terminalMismatchCount",
    )
    flags = (
        "warmProviderRepeatabilityMet",
        "normalP95WithinBound",
        "serverDerivedBundleExact",
        "serverOwnedCitationsExact",
        "selectionOrderExact",
        "selectionOnlyContractMet",
        "noncanonicalReviewRequiredExact",
        "hiddenOnlyIndistinguishable",
        "unavailableBundleAbsent",
        "cancellationFailedClosed",
        "deadlineFailedClosed",
        "staleGenerationFailedClosed",
        "invalidOutputFailedClosed",
        "workerContainmentMet",
    )
    expected_fields = {
        "schemaVersion",
        "qualificationScope",
        "qualified",
        "synchronizedWaves",
        *numeric,
        *flags,
    }
    if set(value) != expected_fields:
        raise ValueError("Coordinator qualification acceptance shape differs")
    if (
        type(value["schemaVersion"]) is not int
        or value["schemaVersion"] != 2
        or value["qualificationScope"] != _SCOPE
        or value["qualified"] is not True
    ):
        raise ValueError("Coordinator qualification acceptance identity differs")
    raw_waves = value["synchronizedWaves"]
    if not isinstance(raw_waves, list):
        raise ValueError("Coordinator qualification waves differ")
    waves = tuple(_acceptance_wave(item) for item in raw_waves)
    counts = {key: _count(value[key], key) for key in numeric}
    booleans = {key: _flag(value[key], key) for key in flags}
    acceptance = CoordinatorQualificationAcceptance(
        identity,
        *(counts[key] for key in numeric),
        *(booleans[key] for key in flags),
        waves,
    )
    if (
        tuple(counts[key] for key in numeric)
        != (
            8,
            8,
            29,
            85_000,
            3,
            8,
            24,
            24,
            3,
            15,
            10,
            1,
            3,
            29,
            15,
            29,
            15,
            18,
            18,
            0,
        )
        or not all(booleans.values())
        or len(waves) != 3
        or len({wave.wave_id for wave in waves}) != 3
        or any(len(wave.case_order) != 8 for wave in waves)
        or any(len(set(wave.case_order)) != 8 for wave in waves)
        or len({case for wave in waves for case in wave.case_order}) != 8
    ):
        raise ValueError("Coordinator qualification acceptance values conflict")
    return acceptance


def _acceptance_wave(value: object) -> CoordinatorQualificationWave:
    if not isinstance(value, dict) or set(value) != {"waveId", "caseOrder"}:
        raise ValueError("Coordinator qualification wave shape differs")
    order = value["caseOrder"]
    if (
        not isinstance(order, list)
        or len(order) != len(set(map(str, order)))
        or not all(isinstance(item, str) for item in order)
    ):
        raise ValueError("Coordinator qualification case order differs")
    return CoordinatorQualificationWave(
        _identity(value["waveId"], "wave identity"),
        tuple(_identity(item, "wave case identity") for item in order),
    )


def load_coordinator_qualification_corpus(path: Path) -> CoordinatorQualificationCorpus:
    value, identity = read_json_object_with_identity(
        path,
        maximum_bytes=_MAXIMUM_FIXTURE_BYTES,
        field="Coordinator qualification fixtures",
    )
    if set(value) != {
        "schemaVersion",
        "qualificationScope",
        "corpusId",
        "tenantId",
        "generations",
        "proposals",
        "cases",
    }:
        raise ValueError("Coordinator qualification fixture shape differs")
    if (
        type(value["schemaVersion"]) is not int
        or value["schemaVersion"] != 1
        or value["qualificationScope"] != _SCOPE
        or not isinstance(value["generations"], list)
        or not isinstance(value["proposals"], list)
        or not isinstance(value["cases"], list)
    ):
        raise ValueError("Coordinator qualification fixture identity differs")
    corpus = CoordinatorQualificationCorpus(
        _identity(value["corpusId"], "corpus identity"),
        identity,
        _identity(value["tenantId"], "tenant identity"),
        tuple(_generation(item) for item in value["generations"]),
        tuple(_proposal(item) for item in value["proposals"]),
        tuple(_case(item) for item in value["cases"]),
    )
    _validate_corpus(corpus)
    return corpus


def _generation(value: object) -> CoordinatorQualificationGeneration:
    if not isinstance(value, dict) or set(value) != {
        "generationId",
        "generationSha256",
        "sources",
    }:
        raise ValueError("Coordinator qualification generation shape differs")
    sources = value["sources"]
    if not isinstance(sources, list) or not sources:
        raise ValueError("Coordinator qualification generation sources differ")
    return CoordinatorQualificationGeneration(
        _identity(value["generationId"], "generation identity"),
        _sha(value["generationSha256"], "generation digest"),
        tuple(_source(item) for item in sources),
    )


def _source(value: object) -> CoordinatorQualificationSource:
    if not isinstance(value, dict) or set(value) != {
        "conceptId",
        "sourceRevision",
        "body",
        "evidenceQuote",
        "visibleToOwnerIds",
        "linkedConceptIds",
        "retrievalRank",
    }:
        raise ValueError("Coordinator qualification source shape differs")
    owners = value["visibleToOwnerIds"]
    links = value["linkedConceptIds"]
    if (
        not isinstance(owners, list)
        or not owners
        or not isinstance(links, list)
        or not all(isinstance(item, str) for item in (*owners, *links))
    ):
        raise ValueError("Coordinator qualification source authority differs")
    body = _text(value["body"], "source body", 8_192, multiline=True)
    quote = _text(value["evidenceQuote"], "evidence quote", 4_096, multiline=True)
    if body.count(quote) != 1:
        raise ValueError("Coordinator qualification evidence quote differs")
    concept_id = _concept(value["conceptId"])
    return CoordinatorQualificationSource(
        concept_id,
        _sha(value["sourceRevision"], "source revision"),
        body,
        quote,
        frozenset(_identity(item, "source owner") for item in owners),
        tuple(_concept(item) for item in links),
        _count(value["retrievalRank"], "retrieval rank"),
    )


def _proposal(value: object) -> CoordinatorQualificationProposal:
    if not isinstance(value, dict) or set(value) != {
        "proposalKey",
        "ownerId",
        "generationId",
        "proposalType",
        "proposedContent",
        "sourceConceptIds",
    }:
        raise ValueError("Coordinator qualification proposal shape differs")
    source_ids = value["sourceConceptIds"]
    if (
        value["proposalType"] != "summary"
        or not isinstance(source_ids, list)
        or not 1 <= len(source_ids) <= 8
        or len(source_ids) != len(set(map(str, source_ids)))
    ):
        raise ValueError("Coordinator qualification proposal identity differs")
    return CoordinatorQualificationProposal(
        _identity(value["proposalKey"], "proposal key"),
        _identity(value["ownerId"], "proposal owner"),
        _identity(value["generationId"], "proposal generation"),
        "summary",
        _text(value["proposedContent"], "proposed content", 2_048),
        tuple(_concept(item) for item in source_ids),
    )


def _case(value: object) -> CoordinatorQualificationCase:
    if not isinstance(value, dict) or set(value) != {
        "caseId",
        "ownerId",
        "activeGenerationId",
        "request",
        "expectedCandidateProposalKeys",
        "runs",
    }:
        raise ValueError("Coordinator qualification case shape differs")
    request = value["request"]
    candidates = value["expectedCandidateProposalKeys"]
    runs = value["runs"]
    if (
        not isinstance(request, dict)
        or set(request) != {"objective", "maximumItems", "expectedGenerationId"}
        or not isinstance(candidates, list)
        or len(candidates) != len(set(map(str, candidates)))
        or not isinstance(runs, list)
        or not runs
    ):
        raise ValueError("Coordinator qualification case contract differs")
    return CoordinatorQualificationCase(
        _identity(value["caseId"], "case identity"),
        _identity(value["ownerId"], "case owner"),
        _identity(value["activeGenerationId"], "active generation"),
        CoordinatorQualificationRequest(
            _text(request["objective"], "objective", 2_048),
            _count(request["maximumItems"], "maximum items"),
            _identity(request["expectedGenerationId"], "requested generation"),
        ),
        tuple(_identity(item, "candidate proposal key") for item in candidates),
        tuple(_run(item) for item in runs),
    )


def _run(value: object) -> CoordinatorQualificationRun:
    if not isinstance(value, dict) or set(value) != {
        "runId",
        "mode",
        "expectedStatus",
        "expectedReason",
        "expectedSelectedProposalKeys",
    }:
        raise ValueError("Coordinator qualification run shape differs")
    selected = value["expectedSelectedProposalKeys"]
    mode = value["mode"]
    status = value["expectedStatus"]
    reason = value["expectedReason"]
    if (
        not isinstance(mode, str)
        or mode not in _MODES
        or not isinstance(status, str)
        or status not in _STATUSES
        or (reason is not None and not isinstance(reason, str))
        or reason not in _REASONS
        or not isinstance(selected, list)
        or len(selected) != len(set(map(str, selected)))
    ):
        raise ValueError("Coordinator qualification run contract differs")
    return CoordinatorQualificationRun(
        _identity(value["runId"], "run identity"),
        mode,
        status,
        reason,
        tuple(_identity(item, "selected proposal key") for item in selected),
    )


def _validate_corpus(corpus: CoordinatorQualificationCorpus) -> None:
    generations = {item.generation_id: item for item in corpus.generations}
    proposals = {item.proposal_key: item for item in corpus.proposals}
    if (
        tuple(generations) != ("predecessor", "successor")
        or len(generations) != len(corpus.generations)
        or len({item.generation_sha256 for item in corpus.generations}) != 2
        or len(proposals) != len(corpus.proposals)
        or len(corpus.cases) != 8
        or len({case.case_id for case in corpus.cases}) != 8
        or len({case.owner_id for case in corpus.cases}) != 8
    ):
        raise ValueError("Coordinator qualification wave contract differs")
    for generation in corpus.generations:
        source_ids = {item.concept_id for item in generation.sources}
        if len(source_ids) != len(generation.sources) or any(
            not set(item.linked_concept_ids) <= source_ids
            for item in generation.sources
        ):
            raise ValueError("Coordinator qualification source graph differs")
    for proposal in corpus.proposals:
        generation = generations.get(proposal.generation_id)
        if generation is None:
            raise ValueError("Coordinator qualification proposal generation differs")
        by_id = {item.concept_id: item for item in generation.sources}
        if any(
            concept_id not in by_id
            or proposal.owner_id not in by_id[concept_id].visible_to_owner_ids
            for concept_id in proposal.source_concept_ids
        ):
            raise ValueError("Coordinator qualification proposal source differs")
    controls: list[str] = []
    for case in corpus.cases:
        if (
            case.active_generation_id not in generations
            or case.request.expected_generation_id not in generations
            or not 1 <= case.request.maximum_items <= 5
            or any(
                key not in proposals for key in case.expected_candidate_proposal_keys
            )
            or any(
                proposals[key].owner_id != case.owner_id
                or proposals[key].generation_id != case.active_generation_id
                for key in case.expected_candidate_proposal_keys
            )
            or sum(run.mode == "normal" for run in case.runs) != 1
        ):
            raise ValueError("Coordinator qualification case binding differs")
        for run in case.runs:
            if run.mode != "normal":
                controls.append(run.mode)
            if (
                any(
                    key not in case.expected_candidate_proposal_keys
                    for key in run.expected_selected_proposal_keys
                )
                or len(run.expected_selected_proposal_keys) > case.request.maximum_items
                or (run.expected_status == "complete")
                != bool(run.expected_selected_proposal_keys)
            ):
                raise ValueError("Coordinator qualification selection differs")
            status, reason = _derived_terminal(case, run)
            if (run.expected_status, run.expected_reason) != (status, reason):
                raise ValueError(
                    "Coordinator qualification terminal expectation differs"
                )
    if (
        tuple(sorted(controls)) != tuple(sorted(_CONTROLLED_MODES))
        or sum(len(case.runs) for case in corpus.cases) != 13
    ):
        raise ValueError("Coordinator qualification wave contract differs")


def _derived_terminal(
    case: CoordinatorQualificationCase,
    run: CoordinatorQualificationRun,
) -> tuple[str, str | None]:
    if run.mode == "normal":
        if run.expected_selected_proposal_keys:
            return "complete", None
        if case.expected_candidate_proposal_keys:
            return "evidence-unavailable", "model-evidence-unavailable"
        return "evidence-unavailable", "empty-result"
    return {
        "client-cancelled": ("cancelled", "client-cancelled"),
        "pre-cancelled": ("cancelled", "client-cancelled"),
        "deadline": ("cancelled", "deadline-exceeded"),
        "stale-generation": ("evidence-unavailable", "stale-generation"),
        "invalid-output": ("failed", "invalid-output"),
    }[run.mode]


def render_coordinator_qualification_generations(
    corpus: CoordinatorQualificationCorpus,
    *,
    tenant_id: str,
) -> tuple[CoordinatorQualificationRenderedGeneration, ...]:
    """Render exact OKF bytes whose production compilation binds the oracle."""

    return render_librarian_qualification_generations(
        _librarian_corpus(corpus),
        tenant_id=_identity(tenant_id, "runtime tenant identity"),
    )


def bind_coordinator_compiled_corpus(
    corpus: CoordinatorQualificationCorpus,
    rendered: tuple[CoordinatorQualificationRenderedGeneration, ...],
    compiled_generations: Mapping[str, CoordinatorCompiledGeneration],
) -> CoordinatorCompiledQualificationCorpus:
    """Bind Curator proposal seeds to independently compiled source authority."""

    if not isinstance(corpus, CoordinatorQualificationCorpus):
        raise TypeError("Coordinator qualification corpus type is invalid")
    librarian = _librarian_corpus(corpus)
    bound = bind_librarian_compiled_corpus(librarian, rendered, compiled_generations)
    seeds: dict[str, CoordinatorQualificationProposalSeed] = {}
    for proposal in corpus.proposals:
        evidence_items: list[CuratorEvidenceItem] = []
        permission_hash: str | None = None
        authorization_hash: str | None = None
        for index, _concept_id_value in enumerate(proposal.source_concept_ids, start=1):
            oracle = bound.expected_views[
                f"oracle-{proposal.proposal_key}-{index}:normal"
            ]
            if (
                oracle.status != "complete"
                or oracle.reason is not None
                or oracle.permission_hash is None
                or oracle.authorization_hash is None
                or len(oracle.items) != 1
            ):
                raise ValueError("Coordinator Curator source oracle differs")
            item = oracle.items[0]
            if permission_hash is None:
                permission_hash = oracle.permission_hash
                authorization_hash = oracle.authorization_hash
            elif (
                permission_hash != oracle.permission_hash
                or authorization_hash != oracle.authorization_hash
            ):
                raise ValueError("Coordinator Curator source authority differs")
            citation = ProposalCitation(
                concept_id=item.concept_id,
                source_revision=item.source_revision,
                content_sha256=item.content_sha256,
                char_start=item.char_start,
                char_end=item.char_end,
            )
            evidence_items.append(CuratorEvidenceItem(citation, item.text))
        if permission_hash is None or authorization_hash is None:
            raise ValueError("Coordinator Curator source evidence is absent")
        generation_sha256 = bound.generation_sha256s[proposal.generation_id]
        evidence = CuratorEvidence.create(
            generation_sha256=generation_sha256,
            permission_hash=permission_hash,
            authorization_hash=authorization_hash,
            items=tuple(evidence_items),
        )
        request = CuratorRequest(
            submission_id=f"coordinator-{proposal.proposal_key}",
            trigger="explicit-proposal",
            expected_generation_sha256=generation_sha256,
            reviewed_content=proposal.proposed_content,
            source_citations=tuple(item.citation for item in evidence_items),
        )
        inherited_policy = _inherited_policy(
            compiled_generations[proposal.generation_id],
            proposal.source_concept_ids,
        )
        inherited_hash = _sha256_json(inherited_policy)
        proposal_permission_hash = permission_hash
        proposal_authorization_hash = _authorization_hash(
            permission_hash, "knowledge.propose"
        )
        proposal_id = _sha256_json(
            {
                "tenantId": bound.tenant_id,
                "generationSha256": generation_sha256,
                "proposerSubjectId": proposal.owner_id,
                "proposerAgentId": "curator",
                "proposalType": proposal.proposal_type,
                "proposedContent": proposal.proposed_content,
                "sourceCitations": [
                    item.model_dump(mode="json") for item in request.source_citations
                ],
                "inheritedPermissionSha256": inherited_hash,
            }
        )
        seeds[proposal.proposal_key] = CoordinatorQualificationProposalSeed(
            proposal.proposal_key,
            proposal.owner_id,
            request,
            evidence,
            proposal_id,
            inherited_hash,
            proposal_permission_hash,
            proposal_authorization_hash,
        )
    if len(seeds) != len(corpus.proposals):
        raise ValueError("Coordinator proposal seed identities conflict")
    return CoordinatorCompiledQualificationCorpus(
        corpus,
        bound.tenant_id,
        MappingProxyType(dict(bound.generation_sha256s)),
        MappingProxyType(seeds),
    )


def bind_coordinator_curator_lineage(
    corpus: CoordinatorCompiledQualificationCorpus,
    curator_request_ids: Mapping[str, str],
) -> CoordinatorBoundQualificationCorpus:
    """Bind dynamic successful Curator request identities into exact candidates."""

    if not isinstance(corpus, CoordinatorCompiledQualificationCorpus):
        raise TypeError("Coordinator qualification corpus is not compiler-bound")
    if not isinstance(curator_request_ids, Mapping) or set(curator_request_ids) != set(
        corpus.proposal_seeds_by_key
    ):
        raise ValueError("Coordinator Curator request identities differ")
    candidates: dict[str, CoordinatorProposalCandidate] = {}
    for key, seed in corpus.proposal_seeds_by_key.items():
        request_id = _request_id(curator_request_ids[key])
        candidates[key] = CoordinatorProposalCandidate.create(
            proposal_id=seed.proposal_id,
            curator_request_id=request_id,
            curator_submission_id=seed.request.submission_id,
            curator_request_sha256=curator_request_sha256(seed.request),
            curator_work_sha256=curator_work_sha256(seed.request, seed.evidence),
            curator_evidence_sha256=seed.evidence.evidence_sha256,
            generation_sha256=seed.evidence.generation_sha256,
            proposal_type=next(
                item.proposal_type
                for item in corpus.corpus.proposals
                if item.proposal_key == key
            ),
            proposed_content=seed.request.reviewed_content,
            inherited_permission_sha256=seed.inherited_permission_sha256,
            proposal_permission_hash=seed.proposal_permission_hash,
            proposal_authorization_hash=seed.proposal_authorization_hash,
            citations=tuple(
                LibrarianEvidenceItem(
                    concept_id=item.citation.concept_id,
                    source_revision=item.citation.source_revision,
                    content_sha256=item.citation.content_sha256,
                    char_start=item.citation.char_start,
                    char_end=item.citation.char_end,
                    text=item.text,
                )
                for item in seed.evidence.items
            ),
        )
    evidence_by_case: dict[str, CoordinatorEvidencePack] = {}
    expected_views: dict[str, CoordinatorExpectedView] = {}
    for case in corpus.corpus.cases:
        generation = next(
            item
            for item in corpus.corpus.generations
            if item.generation_id == case.active_generation_id
        )
        generation_sha256 = corpus.generation_sha256s[case.active_generation_id]
        permission_hash = _permission_hash(
            corpus.tenant_id,
            case.owner_id,
            generation,
            generation_sha256,
        )
        authorization_hash = _authorization_hash(permission_hash, "knowledge.read")
        eligible = [
            (proposal.proposal_key, candidates[proposal.proposal_key])
            for proposal in corpus.corpus.proposals
            if proposal.owner_id == case.owner_id
            and proposal.generation_id == case.active_generation_id
        ]
        objective_tokens = _lexical_tokens(case.request.objective)
        ranked = sorted(
            eligible,
            key=lambda pair: (
                -len(
                    objective_tokens
                    & _lexical_tokens(
                        " ".join(
                            [pair[1].proposed_content]
                            + [citation.text for citation in pair[1].citations]
                        )
                    )
                ),
                pair[1].proposal_id,
            ),
        )[:8]
        ranked_keys = tuple(key for key, _candidate in ranked)
        if ranked_keys != case.expected_candidate_proposal_keys:
            raise ValueError("Coordinator frozen candidate ordering differs")
        evidence = CoordinatorEvidencePack.create(
            generation_sha256=generation_sha256,
            permission_hash=permission_hash,
            authorization_hash=authorization_hash,
            candidates=tuple(candidate for _key, candidate in ranked),
            output_budget_exhausted=False,
        )
        evidence_by_case[case.case_id] = evidence
        request = CoordinatorRequest(
            case.request.objective,
            case.request.maximum_items,
            corpus.generation_sha256s[case.request.expected_generation_id],
        )
        indexes = {key: index for index, key in enumerate(ranked_keys)}
        for run in case.runs:
            bundle = None
            if run.expected_status == "complete":
                bundle = build_coordinator_proposal_bundle(
                    request,
                    evidence,
                    CoordinatorDecision(
                        "bundle",
                        tuple(
                            indexes[key] for key in run.expected_selected_proposal_keys
                        ),
                    ),
                )
                if bundle is None:
                    raise ValueError("Coordinator expected bundle is absent")
            expected_views[f"{case.case_id}:{run.run_id}"] = CoordinatorExpectedView(
                run.expected_status,
                run.expected_reason,
                bundle,
            )
    return CoordinatorBoundQualificationCorpus(
        corpus.corpus,
        corpus.tenant_id,
        corpus.generation_sha256s,
        corpus.proposal_seeds_by_key,
        MappingProxyType(evidence_by_case),
        MappingProxyType(expected_views),
    )


def build_coordinator_qualification_invocations(
    corpus: CoordinatorQualificationCorpus,
    acceptance: CoordinatorQualificationAcceptance,
    *,
    tenant_id: str | None = None,
    generation_sha256s: Mapping[str, str] | None = None,
) -> tuple[CoordinatorQualificationInvocation, ...]:
    if not isinstance(corpus, CoordinatorQualificationCorpus):
        raise TypeError("Coordinator qualification corpus type is invalid")
    if not isinstance(acceptance, CoordinatorQualificationAcceptance):
        raise TypeError("Coordinator qualification acceptance type is invalid")
    runtime_tenant = (
        corpus.tenant_id
        if tenant_id is None
        else _identity(tenant_id, "runtime tenant identity")
    )
    runtime_generations = (
        {item.generation_id: item.generation_sha256 for item in corpus.generations}
        if generation_sha256s is None
        else _runtime_generation_sha256s(corpus, generation_sha256s)
    )
    cases = {item.case_id: item for item in corpus.cases}
    if any(
        set(wave.case_order) != set(cases) for wave in acceptance.synchronized_waves
    ):
        raise ValueError("Coordinator qualification wave cases differ")
    normal: list[CoordinatorQualificationInvocation] = []
    for wave in acceptance.synchronized_waves:
        for position, case_id in enumerate(wave.case_order, start=1):
            case = cases[case_id]
            run = next(item for item in case.runs if item.mode == "normal")
            normal.append(
                _invocation(
                    case,
                    run,
                    runtime_tenant=runtime_tenant,
                    runtime_generations=runtime_generations,
                    invocation_id=f"wave-{wave.wave_id}:{case_id}:{run.run_id}",
                    wave_id=wave.wave_id,
                    declared_position=position,
                )
            )
    controls = [
        _invocation(
            case,
            run,
            runtime_tenant=runtime_tenant,
            runtime_generations=runtime_generations,
            invocation_id=f"control:{case.case_id}:{run.run_id}",
            wave_id=None,
            declared_position=None,
        )
        for mode in _CONTROLLED_MODES
        for case in corpus.cases
        for run in case.runs
        if run.mode == mode
    ]
    return tuple((*normal, *controls))


def _invocation(
    case: CoordinatorQualificationCase,
    run: CoordinatorQualificationRun,
    *,
    runtime_tenant: str,
    runtime_generations: Mapping[str, str],
    invocation_id: str,
    wave_id: str | None,
    declared_position: int | None,
) -> CoordinatorQualificationInvocation:
    return CoordinatorQualificationInvocation(
        invocation_id,
        case.case_id,
        run.run_id,
        run.mode,
        f"{case.case_id}:{run.run_id}",
        wave_id,
        declared_position,
        runtime_tenant,
        case.owner_id,
        case.request.objective,
        case.request.maximum_items,
        runtime_generations[case.request.expected_generation_id],
    )


def evaluate_coordinator_qualification(
    *,
    executor: CoordinatorQualificationExecutor,
    corpus: CoordinatorBoundQualificationCorpus,
    acceptance: CoordinatorQualificationAcceptance,
) -> CoordinatorQualificationResult:
    if not callable(executor):
        raise TypeError("Coordinator qualification executor is invalid")
    if not isinstance(acceptance, CoordinatorQualificationAcceptance):
        raise TypeError("Coordinator qualification acceptance type is invalid")
    if not isinstance(corpus, CoordinatorBoundQualificationCorpus):
        raise TypeError("Coordinator qualification corpus is not Curator-lineage-bound")
    invocations = build_coordinator_qualification_invocations(
        corpus.corpus,
        acceptance,
        tenant_id=corpus.tenant_id,
        generation_sha256s=corpus.generation_sha256s,
    )
    primary = tuple(item for item in invocations if item.mode == "normal")
    controlled = tuple(item for item in invocations if item.mode != "normal")
    waves = tuple(
        tuple(item for item in primary if item.wave_id == wave.wave_id)
        for wave in acceptance.synchronized_waves
    )
    if (
        len(primary) != 24
        or len(waves) != 3
        or any(
            len(wave) != 8
            or len({item.owner_id for item in wave}) != 8
            or tuple(item.declared_position for item in wave) != tuple(range(1, 9))
            for wave in waves
        )
        or tuple(item.mode for item in controlled) != _CONTROLLED_MODES
    ):
        raise ValueError("Coordinator qualification synchronized waves differ")
    primary_observations: list[CoordinatorQualificationObservation] = []
    for wave in waves:
        primary_observations.extend(
            _run_synchronized_wave(executor, wave, corpus.expected_views)
        )
    observations = list(primary_observations)
    for invocation in controlled:
        cancellation = threading.Event()
        if invocation.mode == "pre-cancelled":
            cancellation.set()
        observations.append(
            _run_invocation(
                executor,
                invocation,
                corpus.expected_views[invocation.expected_view_id],
                cancellation,
                None,
            )
        )
    by_id = {item.invocation.invocation_id: item for item in observations}
    request_ids = [
        item.request_id for item in observations if item.request_id is not None
    ]
    normal_durations = sorted(
        item.duration_milliseconds for item in primary_observations
    )
    p95_index = max(0, math.ceil(len(normal_durations) * 0.95) - 1)
    wave_observations = {
        wave.wave_id: tuple(
            item
            for item in primary_observations
            if item.invocation.wave_id == wave.wave_id
        )
        for wave in acceptance.synchronized_waves
    }
    exact_wave_count = sum(
        len(items) == acceptance.owners_per_synchronized_wave
        and all(item.exact_match for item in items)
        for items in wave_observations.values()
    )
    bundle_observations = tuple(
        item for item in observations if item.expected.bundle is not None
    )
    unavailable_observations = tuple(
        item for item in observations if item.expected.status == "evidence-unavailable"
    )
    hidden = _normal_observations(primary_observations, "hidden-only-unavailable")
    absent = _normal_observations(primary_observations, "absent-unavailable")
    cancellation_ids = (
        "control:exact-single-selection:client-cancelled",
        "control:unsupported-objective-unavailable:pre-cancelled",
    )
    public: dict[str, int | bool] = {
        "schemaVersion": 2,
        "qualified": False,
        "caseCount": len(corpus.corpus.cases),
        "ownerCount": len({item.owner_id for item in corpus.corpus.cases}),
        "invocationCount": len(observations),
        "synchronizedWaveCount": len(wave_observations),
        "ownersPerSynchronizedWave": min(
            len({item.invocation.owner_id for item in items})
            for items in wave_observations.values()
        ),
        "synchronizedInvocationCount": len(primary_observations),
        "exactSynchronizedInvocationCount": sum(
            item.exact_match for item in primary_observations
        ),
        "exactSynchronizedWaveCount": exact_wave_count,
        "completeCount": _status_count(observations, "complete"),
        "unavailableCount": _status_count(observations, "evidence-unavailable"),
        "failedCount": _status_count(observations, "failed"),
        "cancelledCount": _status_count(observations, "cancelled"),
        "exactTerminalMatchCount": sum(item.exact_match for item in observations),
        "exactBundleMatchCount": sum(item.exact_match for item in bundle_observations),
        "uniqueRequestIdCount": len(set(request_ids)),
        "bundleCount": sum(
            item.observed is not None and item.observed.bundle is not None
            for item in observations
        ),
        "itemCount": sum(
            len(item.observed.bundle.items)
            if item.observed is not None and item.observed.bundle is not None
            else 0
            for item in observations
        ),
        "citationCount": sum(
            sum(len(candidate.citations) for candidate in item.observed.bundle.items)
            if item.observed is not None and item.observed.bundle is not None
            else 0
            for item in observations
        ),
        "terminalMismatchCount": sum(not item.exact_match for item in observations),
        "warmProviderRepeatabilityMet": exact_wave_count
        == acceptance.synchronized_wave_count,
        "normalP95WithinBound": normal_durations[p95_index]
        <= acceptance.maximum_normal_p95_milliseconds,
        "serverDerivedBundleExact": bool(bundle_observations)
        and all(item.exact_match for item in bundle_observations),
        "serverOwnedCitationsExact": bool(bundle_observations)
        and all(_citations_exact(item) for item in bundle_observations),
        "selectionOrderExact": bool(bundle_observations)
        and all(_selection_order_exact(item) for item in bundle_observations),
        "selectionOnlyContractMet": bool(bundle_observations)
        and all(_selection_only(item) for item in bundle_observations),
        "noncanonicalReviewRequiredExact": bool(bundle_observations)
        and all(_review_flags_exact(item) for item in bundle_observations),
        "hiddenOnlyIndistinguishable": len(hidden) == len(absent) == 3
        and all(item.exact_match for item in (*hidden, *absent))
        and all(
            item.observed == hidden[index].observed for index, item in enumerate(absent)
        ),
        "unavailableBundleAbsent": bool(unavailable_observations)
        and all(
            item.exact_match
            and item.observed is not None
            and item.observed.bundle is None
            for item in unavailable_observations
        ),
        "cancellationFailedClosed": all(
            by_id[item].exact_match
            and by_id[item].observed is not None
            and by_id[item].observed.bundle is None
            for item in cancellation_ids
        ),
        "deadlineFailedClosed": by_id[
            "control:relationship-review-selection:deadline"
        ].exact_match,
        "staleGenerationFailedClosed": by_id[
            "control:instruction-as-data-selection:stale-generation"
        ].exact_match,
        "invalidOutputFailedClosed": by_id[
            "control:ordered-multi-selection:invalid-output"
        ].exact_match,
        "workerContainmentMet": True,
    }
    required = acceptance.expected_public_evidence()
    public["qualified"] = all(
        public[key] == value for key, value in required.items() if key != "qualified"
    )
    return CoordinatorQualificationResult(public, tuple(observations))


def _run_synchronized_wave(
    executor: CoordinatorQualificationExecutor,
    invocations: tuple[CoordinatorQualificationInvocation, ...],
    expected_views: Mapping[str, CoordinatorExpectedView],
) -> list[CoordinatorQualificationObservation]:
    barrier = threading.Barrier(len(invocations))
    cancellations = {item.invocation_id: threading.Event() for item in invocations}
    pool: ThreadPoolExecutor | None = ThreadPoolExecutor(
        max_workers=len(invocations),
        thread_name_prefix="coordinator-qualification",
    )
    try:
        futures: list[Future[CoordinatorQualificationObservation]] = [
            pool.submit(
                _run_invocation,
                executor,
                invocation,
                expected_views[invocation.expected_view_id],
                cancellations[invocation.invocation_id],
                barrier,
            )
            for invocation in invocations
        ]
        _, incomplete = wait(futures, timeout=_PRIMARY_WAVE_TIMEOUT_SECONDS)
        if incomplete:
            for cancellation in cancellations.values():
                cancellation.set()
            _, uncontained = wait(incomplete, timeout=_WORKER_CONTAINMENT_SECONDS)
            if uncontained:
                pool.shutdown(wait=False, cancel_futures=True)
                pool = None
                raise RuntimeError(
                    "Coordinator qualification cancellation was not contained"
                )
            pool.shutdown(wait=True, cancel_futures=True)
            pool = None
            raise TimeoutError("Coordinator qualification wave exceeded its timeout")
        return [future.result() for future in futures]
    finally:
        if pool is not None:
            pool.shutdown(wait=True, cancel_futures=True)


def _run_invocation(
    executor: CoordinatorQualificationExecutor,
    invocation: CoordinatorQualificationInvocation,
    expected: CoordinatorExpectedView,
    cancellation: threading.Event,
    barrier: threading.Barrier | None,
) -> CoordinatorQualificationObservation:
    if barrier is not None:
        try:
            barrier.wait(timeout=_PRIMARY_WAVE_TIMEOUT_SECONDS)
        except threading.BrokenBarrierError as error:
            raise RuntimeError(
                "Coordinator qualification synchronization failed"
            ) from error
    started = time.monotonic()
    try:
        request_id, observed = _observed_view(executor(invocation, cancellation))
        exact = observed == expected
        return CoordinatorQualificationObservation(
            invocation,
            expected,
            observed,
            request_id,
            _duration(started),
            exact,
            None if exact else "view-mismatch",
        )
    except Exception:
        return CoordinatorQualificationObservation(
            invocation,
            expected,
            None,
            None,
            _duration(started),
            False,
            "executor-error",
        )


def _observed_view(view: object) -> tuple[str, CoordinatorExpectedView]:
    if not isinstance(view, CoordinatorJobView):
        raise ValueError("Coordinator qualification view type differs")
    request_id = _request_id(view.request_id)
    if (
        view.status not in _STATUSES
        or view.reason not in _REASONS
        or (
            view.bundle is not None
            and not isinstance(view.bundle, CoordinatorProposalBundle)
        )
    ):
        raise ValueError("Coordinator qualification terminal view differs")
    valid = (
        (view.status == "complete" and view.reason is None and view.bundle is not None)
        or (
            view.status == "evidence-unavailable"
            and view.reason
            in {"empty-result", "model-evidence-unavailable", "stale-generation"}
            and view.bundle is None
        )
        or (
            view.status == "failed"
            and view.reason == "invalid-output"
            and view.bundle is None
        )
        or (
            view.status == "cancelled"
            and view.reason in {"client-cancelled", "deadline-exceeded"}
            and view.bundle is None
        )
    )
    if not valid:
        raise ValueError("Coordinator qualification terminal binding differs")
    return request_id, CoordinatorExpectedView(view.status, view.reason, view.bundle)


def _librarian_corpus(
    corpus: CoordinatorQualificationCorpus,
) -> LibrarianQualificationCorpus:
    generations = tuple(
        LibrarianQualificationGeneration(
            generation.generation_id,
            generation.generation_sha256,
            tuple(
                LibrarianQualificationSource(
                    source.concept_id,
                    source.source_revision,
                    source.body,
                    source.evidence_quote,
                    source.visible_to_owner_ids,
                    source.linked_concept_ids,
                    source.retrieval_rank,
                )
                for source in generation.sources
            ),
        )
        for generation in corpus.generations
    )
    by_generation = {item.generation_id: item for item in corpus.generations}
    cases: list[LibrarianQualificationCase] = []
    for proposal in corpus.proposals:
        sources = {
            item.concept_id: item
            for item in by_generation[proposal.generation_id].sources
        }
        for index, concept_id in enumerate(proposal.source_concept_ids, start=1):
            source = sources[concept_id]
            cases.append(
                LibrarianQualificationCase(
                    f"oracle-{proposal.proposal_key}-{index}",
                    proposal.owner_id,
                    proposal.generation_id,
                    LibrarianQualificationRequest(
                        "knowledge.read",
                        source.evidence_quote,
                        1,
                        proposal.generation_id,
                    ),
                    (
                        LibrarianQualificationRun(
                            "normal",
                            "normal",
                            "complete",
                            None,
                            (
                                LibrarianExpectedSelector(
                                    source.concept_id, source.evidence_quote
                                ),
                            ),
                        ),
                    ),
                )
            )
    return LibrarianQualificationCorpus(
        f"{corpus.corpus_id}-oracle",
        corpus.corpus_sha256,
        corpus.tenant_id,
        generations,
        tuple(cases),
    )


def _inherited_policy(
    compiled: CoordinatorCompiledGeneration,
    source_concept_ids: tuple[str, ...],
) -> dict[str, object]:
    concepts = {item.concept_id: item for item in compiled.concepts}
    permissions = {item.path_prefix: item for item in compiled.permissions}
    policies = []
    for concept_id in source_concept_ids:
        concept = concepts.get(concept_id)
        if concept is None:
            raise ValueError("Coordinator compiled proposal concept differs")
        permission = permissions.get(concept.permission_path_prefix)
        if permission is None:
            raise ValueError("Coordinator compiled proposal permission differs")
        policies.append(
            {
                "audience": [
                    {"tenantId": item.tenant_id, "subjectId": item.subject_id}
                    for item in permission.audience
                ],
                "denials": [
                    {"tenantId": item.tenant_id, "subjectId": item.subject_id}
                    for item in permission.denials
                ],
                "purposes": list(permission.purposes),
                "classification": permission.classification,
            }
        )
    return _strictest_policy(tuple(policies))


def _strictest_policy(policies: tuple[dict[str, object], ...]) -> dict[str, object]:
    if not policies:
        raise ValueError("Coordinator inherited policy is absent")
    audiences = [
        {
            (str(item["tenantId"]), str(item["subjectId"]))
            for item in policy["audience"]  # type: ignore[union-attr]
        }
        for policy in policies
    ]
    purposes = [set(map(str, policy["purposes"])) for policy in policies]  # type: ignore[arg-type]
    denials = {
        (str(item["tenantId"]), str(item["subjectId"]))
        for policy in policies
        for item in policy["denials"]  # type: ignore[union-attr]
    }
    audience = set.intersection(*audiences) - denials
    order = {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}
    classification = max(
        (str(policy["classification"]) for policy in policies), key=order.__getitem__
    )
    return {
        "audience": [
            {"tenantId": tenant, "subjectId": subject}
            for tenant, subject in sorted(audience)
        ],
        "denials": [
            {"tenantId": tenant, "subjectId": subject}
            for tenant, subject in sorted(denials)
        ],
        "purposes": sorted(set.intersection(*purposes)),
        "classification": classification,
        "canonical": False,
    }


def _permission_hash(
    tenant_id: str,
    owner_id: str,
    generation: CoordinatorQualificationGeneration,
    generation_sha256: str,
) -> str:
    visible = {
        source.concept_id
        for source in generation.sources
        if owner_id in source.visible_to_owner_ids
    }
    permission_sha256s = sorted(
        {
            _sha256_json(
                {
                    "pathPrefix": f"{source.concept_id}/",
                    "audience": [
                        {"tenantId": tenant_id, "subjectId": item}
                        for item in sorted(source.visible_to_owner_ids)
                    ],
                    "denials": [],
                    "purposes": ["knowledge.read"],
                    "classification": "internal",
                }
            )
            for source in generation.sources
            if source.concept_id in visible
        }
    )
    return _sha256_json(
        {
            "tenantId": tenant_id,
            "subjectId": owner_id,
            "purpose": "knowledge.read",
            "generationSha256": generation_sha256,
            "permissionSha256s": permission_sha256s,
            "visibleConceptIds": sorted(visible),
        }
    )


def _authorization_hash(permission_hash: str, required_capability: str) -> str:
    return _sha256_json(
        {
            "permissionHash": permission_hash,
            "requiredCapability": required_capability,
        }
    )


def _runtime_generation_sha256s(
    corpus: CoordinatorQualificationCorpus,
    value: Mapping[str, str],
) -> dict[str, str]:
    expected = {item.generation_id for item in corpus.generations}
    if not isinstance(value, Mapping) or set(value) != expected:
        raise ValueError("Coordinator runtime generation identities differ")
    return {key: _sha(item, "runtime generation digest") for key, item in value.items()}


def _normal_observations(
    observations: list[CoordinatorQualificationObservation],
    case_id: str,
) -> tuple[CoordinatorQualificationObservation, ...]:
    return tuple(item for item in observations if item.invocation.case_id == case_id)


def _status_count(
    observations: list[CoordinatorQualificationObservation], status: str
) -> int:
    return sum(
        item.observed is not None and item.observed.status == status
        for item in observations
    )


def _citations_exact(observation: CoordinatorQualificationObservation) -> bool:
    return (
        observation.exact_match
        and observation.observed is not None
        and observation.observed.bundle is not None
        and observation.expected.bundle is not None
        and tuple(item.citations for item in observation.observed.bundle.items)
        == tuple(item.citations for item in observation.expected.bundle.items)
    )


def _selection_order_exact(observation: CoordinatorQualificationObservation) -> bool:
    return (
        observation.exact_match
        and observation.observed is not None
        and observation.observed.bundle is not None
        and observation.expected.bundle is not None
        and tuple(item.proposal_id for item in observation.observed.bundle.items)
        == tuple(item.proposal_id for item in observation.expected.bundle.items)
    )


def _selection_only(observation: CoordinatorQualificationObservation) -> bool:
    if observation.observed is None or observation.observed.bundle is None:
        return False
    wire = observation.observed.bundle.to_wire()
    items = wire.get("items")
    return (
        set(wire)
        == {
            "schemaVersion",
            "generationSha256",
            "evidenceSha256",
            "items",
            "bundleSha256",
            "citationSha256",
            "canonical",
            "requiresReview",
        }
        and isinstance(items, list)
        and bool(items)
        and all(
            isinstance(item, dict)
            and set(item)
            == {
                "proposalId",
                "proposalType",
                "proposedContent",
                "citations",
                "citationSha256",
                "candidateSha256",
            }
            for item in items
        )
    )


def _review_flags_exact(observation: CoordinatorQualificationObservation) -> bool:
    if observation.observed is None or observation.observed.bundle is None:
        return False
    wire = observation.observed.bundle.to_wire()
    return wire["canonical"] is False and wire["requiresReview"] is True


def _lexical_tokens(value: str) -> frozenset[str]:
    return frozenset(token.casefold() for token in _LEXICAL_TOKEN.findall(value))


def _sha256_json(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def _identity(value: object, field: str) -> str:
    if not isinstance(value, str) or _IDENTITY.fullmatch(value) is None:
        raise ValueError(f"Coordinator qualification {field} is invalid")
    return value


def _concept(value: object) -> str:
    if not isinstance(value, str) or _CONCEPT_ID.fullmatch(value) is None:
        raise ValueError("Coordinator qualification concept identity is invalid")
    return value


def _sha(value: object, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"Coordinator qualification {field} is invalid")
    return value


def _request_id(value: object) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 128
        or value.strip() != value
        or not value.isascii()
        or not value.isprintable()
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", value) is None
    ):
        raise ValueError("Coordinator qualification request identity is invalid")
    return value


def _text(value: object, field: str, maximum: int, *, multiline: bool = False) -> str:
    valid = (
        isinstance(value, str)
        and 1 <= len(value) <= maximum
        and value.strip() == value
        and "\r" not in value
        and all(character == "\n" or character.isprintable() for character in value)
    )
    if not valid or (not multiline and "\n" in value):
        raise ValueError(f"Coordinator qualification {field} is invalid")
    return value


def _count(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"Coordinator qualification {field} is invalid")
    return value


def _flag(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"Coordinator qualification {field} is invalid")
    return value


def _duration(started: float) -> int:
    return max(0, round((time.monotonic() - started) * 1_000))


__all__ = [
    "CoordinatorBoundQualificationCorpus",
    "CoordinatorCompiledGeneration",
    "CoordinatorCompiledQualificationCorpus",
    "CoordinatorExpectedView",
    "CoordinatorQualificationAcceptance",
    "CoordinatorQualificationCase",
    "CoordinatorQualificationCorpus",
    "CoordinatorQualificationGeneration",
    "CoordinatorQualificationInvocation",
    "CoordinatorQualificationObservation",
    "CoordinatorQualificationProposal",
    "CoordinatorQualificationProposalSeed",
    "CoordinatorQualificationRenderedFile",
    "CoordinatorQualificationRenderedGeneration",
    "CoordinatorQualificationRenderedSource",
    "CoordinatorQualificationRequest",
    "CoordinatorQualificationResult",
    "CoordinatorQualificationRun",
    "CoordinatorQualificationSource",
    "CoordinatorQualificationWave",
    "bind_coordinator_compiled_corpus",
    "bind_coordinator_curator_lineage",
    "build_coordinator_qualification_invocations",
    "evaluate_coordinator_qualification",
    "load_coordinator_qualification_acceptance",
    "load_coordinator_qualification_corpus",
    "render_coordinator_qualification_generations",
]
