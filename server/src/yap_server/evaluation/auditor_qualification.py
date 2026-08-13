"""Public synthetic qualification for grounded, server-derived Auditor reports."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
import math
from pathlib import Path
import re
import threading
import time
from types import MappingProxyType
from typing import Mapping, Protocol

from yap_server.agents.auditor import (
    AuditorEvidencePack,
    AuditorReport,
    AuditorRequest,
    build_auditor_report,
)
from yap_server.agents.auditor_model import AuditorDecision
from yap_server.agents.auditor_service import AuditorJobView
from yap_server.agents.librarian import (
    LibrarianEvidenceItem,
)
from yap_server.private_artifact import read_json_object_with_identity

from .librarian_qualification import (
    LibrarianCompiledChunk as AuditorCompiledChunk,
    LibrarianCompiledConcept as AuditorCompiledConcept,
    LibrarianCompiledGeneration as AuditorCompiledGeneration,
    LibrarianCompiledPermission as AuditorCompiledPermission,
    LibrarianExpectedSelector,
    LibrarianQualificationCase,
    LibrarianQualificationCorpus,
    LibrarianQualificationGeneration,
    LibrarianQualificationRenderedFile as AuditorQualificationRenderedFile,
    LibrarianQualificationRenderedGeneration as AuditorQualificationRenderedGeneration,
    LibrarianQualificationRenderedSource as AuditorQualificationRenderedSource,
    LibrarianQualificationRequest,
    LibrarianQualificationRun,
    LibrarianQualificationSource,
    bind_librarian_compiled_corpus,
    render_librarian_qualification_generations,
)


_SCOPE = "auditor-source-cited-review-findings"
_MAXIMUM_ACCEPTANCE_BYTES = 32 * 1024
_MAXIMUM_FIXTURE_BYTES = 256 * 1024
_IDENTITY = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_CONCEPT_ID = re.compile(r"^[a-z0-9][a-z0-9./-]{0,511}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
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


class AuditorQualificationExecutor(Protocol):
    def __call__(
        self,
        invocation: AuditorQualificationInvocation,
        cancellation: threading.Event,
    ) -> object: ...


@dataclass(frozen=True, slots=True)
class AuditorQualificationWave:
    wave_id: str
    case_order: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AuditorQualificationAcceptance:
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
    exact_report_match_count: int
    unique_request_id_count: int
    report_count: int
    finding_count: int
    citation_count: int
    terminal_mismatch_count: int
    warm_provider_repeatability_met: bool
    normal_p95_within_bound: bool
    server_derived_report_exact: bool
    server_owned_citations_exact: bool
    canonical_pair_order_exact: bool
    review_only_contract_met: bool
    noncanonical_review_required_exact: bool
    hidden_only_indistinguishable: bool
    unavailable_report_absent: bool
    cancellation_failed_closed: bool
    deadline_failed_closed: bool
    stale_generation_failed_closed: bool
    invalid_output_failed_closed: bool
    worker_containment_met: bool
    synchronized_waves: tuple[AuditorQualificationWave, ...] = field(repr=False)

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
            "exactSynchronizedInvocationCount": (
                self.exact_synchronized_invocation_count
            ),
            "exactSynchronizedWaveCount": self.exact_synchronized_wave_count,
            "completeCount": self.complete_count,
            "unavailableCount": self.unavailable_count,
            "failedCount": self.failed_count,
            "cancelledCount": self.cancelled_count,
            "exactTerminalMatchCount": self.exact_terminal_match_count,
            "exactReportMatchCount": self.exact_report_match_count,
            "uniqueRequestIdCount": self.unique_request_id_count,
            "reportCount": self.report_count,
            "findingCount": self.finding_count,
            "citationCount": self.citation_count,
            "terminalMismatchCount": self.terminal_mismatch_count,
            "warmProviderRepeatabilityMet": self.warm_provider_repeatability_met,
            "normalP95WithinBound": self.normal_p95_within_bound,
            "serverDerivedReportExact": self.server_derived_report_exact,
            "serverOwnedCitationsExact": self.server_owned_citations_exact,
            "canonicalPairOrderExact": self.canonical_pair_order_exact,
            "reviewOnlyContractMet": self.review_only_contract_met,
            "noncanonicalReviewRequiredExact": (
                self.noncanonical_review_required_exact
            ),
            "hiddenOnlyIndistinguishable": self.hidden_only_indistinguishable,
            "unavailableReportAbsent": self.unavailable_report_absent,
            "cancellationFailedClosed": self.cancellation_failed_closed,
            "deadlineFailedClosed": self.deadline_failed_closed,
            "staleGenerationFailedClosed": self.stale_generation_failed_closed,
            "invalidOutputFailedClosed": self.invalid_output_failed_closed,
            "workerContainmentMet": self.worker_containment_met,
        }


@dataclass(frozen=True, slots=True)
class AuditorQualificationSource:
    concept_id: str
    source_revision: str
    body: str
    evidence_quote: str
    visible_to_owner_ids: frozenset[str]
    linked_concept_ids: tuple[str, ...]
    retrieval_rank: int


@dataclass(frozen=True, slots=True)
class AuditorQualificationGeneration:
    generation_id: str
    generation_sha256: str
    sources: tuple[AuditorQualificationSource, ...]


@dataclass(frozen=True, slots=True)
class AuditorExpectedSelector:
    concept_id: str
    quote: str


@dataclass(frozen=True, slots=True)
class AuditorQualificationRun:
    run_id: str
    mode: str
    expected_status: str
    expected_reason: str | None
    expected_evidence: tuple[AuditorExpectedSelector, ...]
    expected_finding_pairs: tuple[tuple[int, int], ...]


@dataclass(frozen=True, slots=True)
class AuditorQualificationRequest:
    focus: str
    maximum_findings: int
    expected_generation_id: str


@dataclass(frozen=True, slots=True)
class AuditorQualificationCase:
    case_id: str
    owner_id: str
    active_generation_id: str
    request: AuditorQualificationRequest
    runs: tuple[AuditorQualificationRun, ...]


@dataclass(frozen=True, slots=True)
class AuditorQualificationCorpus:
    corpus_id: str
    corpus_sha256: str
    tenant_id: str
    generations: tuple[AuditorQualificationGeneration, ...]
    cases: tuple[AuditorQualificationCase, ...]


@dataclass(frozen=True, slots=True)
class AuditorExpectedView:
    status: str
    reason: str | None
    report: AuditorReport | None


@dataclass(frozen=True, slots=True)
class AuditorBoundQualificationCorpus:
    corpus: AuditorQualificationCorpus
    tenant_id: str
    generation_sha256s: Mapping[str, str]
    source_admission_sha256s: Mapping[str, str]
    evidence_by_case: Mapping[str, AuditorEvidencePack]
    expected_views: Mapping[str, AuditorExpectedView]


@dataclass(frozen=True, slots=True)
class AuditorQualificationInvocation:
    invocation_id: str
    case_id: str
    run_id: str
    mode: str
    expected_view_id: str
    wave_id: str | None
    declared_position: int | None
    tenant_id: str
    owner_id: str
    focus: str
    maximum_findings: int
    expected_generation_sha256: str


@dataclass(frozen=True, slots=True)
class AuditorQualificationObservation:
    invocation: AuditorQualificationInvocation = field(repr=False)
    expected: AuditorExpectedView = field(repr=False)
    observed: AuditorExpectedView | None = field(repr=False)
    request_id: str | None = field(repr=False)
    duration_milliseconds: int = field(repr=False)
    exact_match: bool
    failure_kind: str | None


@dataclass(frozen=True, slots=True)
class AuditorQualificationResult:
    public_evidence: dict[str, int | bool]
    observations: tuple[AuditorQualificationObservation, ...] = field(repr=False)


def load_auditor_qualification_acceptance(
    path: Path,
) -> AuditorQualificationAcceptance:
    value, identity = read_json_object_with_identity(
        path,
        maximum_bytes=_MAXIMUM_ACCEPTANCE_BYTES,
        field="Auditor qualification acceptance",
    )
    fields = {
        "schemaVersion",
        "qualificationScope",
        "qualified",
        "caseCount",
        "ownerCount",
        "invocationCount",
        "maximumNormalP95Milliseconds",
        "synchronizedWaveCount",
        "ownersPerSynchronizedWave",
        "synchronizedInvocationCount",
        "exactSynchronizedInvocationCount",
        "exactSynchronizedWaveCount",
        "synchronizedWaves",
        "completeCount",
        "unavailableCount",
        "failedCount",
        "cancelledCount",
        "exactTerminalMatchCount",
        "exactReportMatchCount",
        "uniqueRequestIdCount",
        "reportCount",
        "findingCount",
        "citationCount",
        "terminalMismatchCount",
        "warmProviderRepeatabilityMet",
        "normalP95WithinBound",
        "serverDerivedReportExact",
        "serverOwnedCitationsExact",
        "canonicalPairOrderExact",
        "reviewOnlyContractMet",
        "noncanonicalReviewRequiredExact",
        "hiddenOnlyIndistinguishable",
        "unavailableReportAbsent",
        "cancellationFailedClosed",
        "deadlineFailedClosed",
        "staleGenerationFailedClosed",
        "invalidOutputFailedClosed",
        "workerContainmentMet",
    }
    if set(value) != fields:
        raise ValueError("Auditor qualification acceptance shape differs")
    if (
        type(value["schemaVersion"]) is not int
        or value["schemaVersion"] != 2
        or value["qualificationScope"] != _SCOPE
        or value["qualified"] is not True
    ):
        raise ValueError("Auditor qualification acceptance identity differs")
    raw_waves = value["synchronizedWaves"]
    if not isinstance(raw_waves, list):
        raise ValueError("Auditor qualification waves differ")
    waves = tuple(_acceptance_wave(item) for item in raw_waves)
    acceptance = AuditorQualificationAcceptance(
        plan_sha256=identity,
        case_count=_count(value["caseCount"], "caseCount"),
        owner_count=_count(value["ownerCount"], "ownerCount"),
        invocation_count=_count(value["invocationCount"], "invocationCount"),
        maximum_normal_p95_milliseconds=_count(
            value["maximumNormalP95Milliseconds"],
            "maximumNormalP95Milliseconds",
        ),
        synchronized_wave_count=_count(
            value["synchronizedWaveCount"], "synchronizedWaveCount"
        ),
        owners_per_synchronized_wave=_count(
            value["ownersPerSynchronizedWave"], "ownersPerSynchronizedWave"
        ),
        synchronized_invocation_count=_count(
            value["synchronizedInvocationCount"], "synchronizedInvocationCount"
        ),
        exact_synchronized_invocation_count=_count(
            value["exactSynchronizedInvocationCount"],
            "exactSynchronizedInvocationCount",
        ),
        exact_synchronized_wave_count=_count(
            value["exactSynchronizedWaveCount"], "exactSynchronizedWaveCount"
        ),
        complete_count=_count(value["completeCount"], "completeCount"),
        unavailable_count=_count(value["unavailableCount"], "unavailableCount"),
        failed_count=_count(value["failedCount"], "failedCount"),
        cancelled_count=_count(value["cancelledCount"], "cancelledCount"),
        exact_terminal_match_count=_count(
            value["exactTerminalMatchCount"], "exactTerminalMatchCount"
        ),
        exact_report_match_count=_count(
            value["exactReportMatchCount"], "exactReportMatchCount"
        ),
        unique_request_id_count=_count(
            value["uniqueRequestIdCount"], "uniqueRequestIdCount"
        ),
        report_count=_count(value["reportCount"], "reportCount"),
        finding_count=_count(value["findingCount"], "findingCount"),
        citation_count=_count(value["citationCount"], "citationCount"),
        terminal_mismatch_count=_count(
            value["terminalMismatchCount"], "terminalMismatchCount"
        ),
        warm_provider_repeatability_met=_flag(
            value["warmProviderRepeatabilityMet"],
            "warmProviderRepeatabilityMet",
        ),
        normal_p95_within_bound=_flag(
            value["normalP95WithinBound"], "normalP95WithinBound"
        ),
        server_derived_report_exact=_flag(
            value["serverDerivedReportExact"], "serverDerivedReportExact"
        ),
        server_owned_citations_exact=_flag(
            value["serverOwnedCitationsExact"], "serverOwnedCitationsExact"
        ),
        canonical_pair_order_exact=_flag(
            value["canonicalPairOrderExact"], "canonicalPairOrderExact"
        ),
        review_only_contract_met=_flag(
            value["reviewOnlyContractMet"], "reviewOnlyContractMet"
        ),
        noncanonical_review_required_exact=_flag(
            value["noncanonicalReviewRequiredExact"],
            "noncanonicalReviewRequiredExact",
        ),
        hidden_only_indistinguishable=_flag(
            value["hiddenOnlyIndistinguishable"],
            "hiddenOnlyIndistinguishable",
        ),
        unavailable_report_absent=_flag(
            value["unavailableReportAbsent"], "unavailableReportAbsent"
        ),
        cancellation_failed_closed=_flag(
            value["cancellationFailedClosed"], "cancellationFailedClosed"
        ),
        deadline_failed_closed=_flag(
            value["deadlineFailedClosed"], "deadlineFailedClosed"
        ),
        stale_generation_failed_closed=_flag(
            value["staleGenerationFailedClosed"], "staleGenerationFailedClosed"
        ),
        invalid_output_failed_closed=_flag(
            value["invalidOutputFailedClosed"], "invalidOutputFailedClosed"
        ),
        worker_containment_met=_flag(
            value["workerContainmentMet"], "workerContainmentMet"
        ),
        synchronized_waves=waves,
    )
    if (
        acceptance.case_count != 8
        or acceptance.owner_count != 8
        or acceptance.invocation_count != 29
        or acceptance.maximum_normal_p95_milliseconds != 85_000
        or acceptance.synchronized_wave_count != 3
        or acceptance.owners_per_synchronized_wave != 8
        or acceptance.synchronized_invocation_count != 24
        or acceptance.exact_synchronized_invocation_count != 24
        or acceptance.exact_synchronized_wave_count != 3
        or (
            acceptance.complete_count,
            acceptance.unavailable_count,
            acceptance.failed_count,
            acceptance.cancelled_count,
        )
        != (12, 13, 1, 3)
        or acceptance.exact_terminal_match_count != 29
        or acceptance.exact_report_match_count != 12
        or acceptance.unique_request_id_count != 29
        or acceptance.report_count != 12
        or acceptance.finding_count != 15
        or acceptance.citation_count != 30
        or acceptance.terminal_mismatch_count != 0
        or len(waves) != 3
        or len({item.wave_id for item in waves}) != 3
        or any(len(item.case_order) != 8 for item in waves)
        or any(len(set(item.case_order)) != 8 for item in waves)
        or len({case for item in waves for case in item.case_order}) != 8
        or not all(
            (
                acceptance.warm_provider_repeatability_met,
                acceptance.normal_p95_within_bound,
                acceptance.server_derived_report_exact,
                acceptance.server_owned_citations_exact,
                acceptance.canonical_pair_order_exact,
                acceptance.review_only_contract_met,
                acceptance.noncanonical_review_required_exact,
                acceptance.hidden_only_indistinguishable,
                acceptance.unavailable_report_absent,
                acceptance.cancellation_failed_closed,
                acceptance.deadline_failed_closed,
                acceptance.stale_generation_failed_closed,
                acceptance.invalid_output_failed_closed,
                acceptance.worker_containment_met,
            )
        )
    ):
        raise ValueError("Auditor qualification acceptance values conflict")
    return acceptance


def _acceptance_wave(value: object) -> AuditorQualificationWave:
    if not isinstance(value, dict) or set(value) != {"waveId", "caseOrder"}:
        raise ValueError("Auditor qualification wave shape differs")
    order = value["caseOrder"]
    if (
        not isinstance(order, list)
        or len(order) != len(set(order))
        or not all(isinstance(item, str) for item in order)
    ):
        raise ValueError("Auditor qualification case order differs")
    return AuditorQualificationWave(
        _identity(value["waveId"], "wave identity"),
        tuple(_identity(item, "wave case identity") for item in order),
    )


def load_auditor_qualification_corpus(path: Path) -> AuditorQualificationCorpus:
    value, identity = read_json_object_with_identity(
        path,
        maximum_bytes=_MAXIMUM_FIXTURE_BYTES,
        field="Auditor qualification fixtures",
    )
    if set(value) != {
        "schemaVersion",
        "qualificationScope",
        "corpusId",
        "tenantId",
        "generations",
        "cases",
    }:
        raise ValueError("Auditor qualification fixture shape differs")
    if (
        type(value["schemaVersion"]) is not int
        or value["schemaVersion"] != 1
        or value["qualificationScope"] != _SCOPE
    ):
        raise ValueError("Auditor qualification fixture identity differs")
    generations_raw = value["generations"]
    cases_raw = value["cases"]
    if (
        not isinstance(generations_raw, list)
        or len(generations_raw) != 2
        or not isinstance(cases_raw, list)
        or len(cases_raw) != 8
    ):
        raise ValueError("Auditor qualification fixture cardinality differs")
    corpus = AuditorQualificationCorpus(
        _identity(value["corpusId"], "corpus identity"),
        identity,
        _identity(value["tenantId"], "tenant identity"),
        tuple(_generation(item) for item in generations_raw),
        tuple(_case(item) for item in cases_raw),
    )
    generation_ids = {item.generation_id for item in corpus.generations}
    normal = tuple(
        (case, run)
        for case in corpus.cases
        for run in case.runs
        if run.mode == "normal"
    )
    controls = tuple(
        run.mode for case in corpus.cases for run in case.runs if run.mode != "normal"
    )
    if (
        len(generation_ids) != 2
        or len({item.generation_sha256 for item in corpus.generations}) != 2
        or len({item.case_id for item in corpus.cases}) != 8
        or len({item.owner_id for item in corpus.cases}) != 8
        or any(
            item.active_generation_id not in generation_ids
            or item.request.expected_generation_id not in generation_ids
            for item in corpus.cases
        )
        or len(normal) != 8
        or any(
            sum(run.mode == "normal" for run in case.runs) != 1 for case in corpus.cases
        )
        or tuple(sorted(controls)) != tuple(sorted(_CONTROLLED_MODES))
        or sum(len(item.runs) for item in corpus.cases) != 13
    ):
        raise ValueError("Auditor qualification wave contract differs")
    _auditor_librarian_corpus(corpus)
    return corpus


def _generation(value: object) -> AuditorQualificationGeneration:
    if not isinstance(value, dict) or set(value) != {
        "generationId",
        "generationSha256",
        "sources",
    }:
        raise ValueError("Auditor qualification generation shape differs")
    raw_sources = value["sources"]
    if not isinstance(raw_sources, list) or not 1 <= len(raw_sources) <= 64:
        raise ValueError("Auditor qualification generation sources differ")
    sources = tuple(_source(item) for item in raw_sources)
    concept_ids = {item.concept_id for item in sources}
    if len(concept_ids) != len(sources) or any(
        not set(item.linked_concept_ids) <= concept_ids for item in sources
    ):
        raise ValueError("Auditor qualification source identity differs")
    return AuditorQualificationGeneration(
        _identity(value["generationId"], "generation identity"),
        _sha(value["generationSha256"], "generation digest"),
        sources,
    )


def _source(value: object) -> AuditorQualificationSource:
    if not isinstance(value, dict) or set(value) != {
        "conceptId",
        "sourceRevision",
        "body",
        "evidenceQuote",
        "visibleToOwnerIds",
        "linkedConceptIds",
        "retrievalRank",
    }:
        raise ValueError("Auditor qualification source shape differs")
    owners = value["visibleToOwnerIds"]
    links = value["linkedConceptIds"]
    if (
        not isinstance(owners, list)
        or not owners
        or len(owners) != len(set(owners))
        or not isinstance(links, list)
        or len(links) != len(set(links))
    ):
        raise ValueError("Auditor qualification source permission differs")
    body = _text(value["body"], "source body", 4_096)
    quote = _text(value["evidenceQuote"], "evidence quote", 2_000)
    if body.count(quote) != 1:
        raise ValueError("Auditor qualification evidence quote differs")
    return AuditorQualificationSource(
        _concept(value["conceptId"], "source concept"),
        _text(value["sourceRevision"], "source revision", 512),
        body,
        quote,
        frozenset(_identity(item, "visible owner") for item in owners),
        tuple(_concept(item, "linked concept") for item in links),
        _bounded_int(value["retrievalRank"], 1, 2**31 - 1, "retrieval rank"),
    )


def _case(value: object) -> AuditorQualificationCase:
    if not isinstance(value, dict) or set(value) != {
        "caseId",
        "ownerId",
        "activeGenerationId",
        "request",
        "runs",
    }:
        raise ValueError("Auditor qualification case shape differs")
    raw_request = value["request"]
    raw_runs = value["runs"]
    if not isinstance(raw_request, dict) or set(raw_request) != {
        "focus",
        "maximumFindings",
        "expectedGenerationId",
    }:
        raise ValueError("Auditor qualification request shape differs")
    focus = _text(raw_request["focus"], "focus", 1_024)
    if not any(character.isalnum() for character in focus):
        raise ValueError("Auditor qualification focus differs")
    request = AuditorQualificationRequest(
        focus,
        _bounded_int(raw_request["maximumFindings"], 1, 5, "finding limit"),
        _identity(
            raw_request["expectedGenerationId"],
            "expected generation identity",
        ),
    )
    if not isinstance(raw_runs, list) or not 1 <= len(raw_runs) <= 3:
        raise ValueError("Auditor qualification run count differs")
    runs = tuple(_run(item) for item in raw_runs)
    if len({item.run_id for item in runs}) != len(runs):
        raise ValueError("Auditor qualification run identity differs")
    return AuditorQualificationCase(
        _identity(value["caseId"], "case identity"),
        _identity(value["ownerId"], "owner identity"),
        _identity(value["activeGenerationId"], "active generation identity"),
        request,
        runs,
    )


def _run(value: object) -> AuditorQualificationRun:
    if not isinstance(value, dict) or set(value) != {
        "runId",
        "mode",
        "expectedStatus",
        "expectedReason",
        "expectedEvidence",
        "expectedFindingPairs",
    }:
        raise ValueError("Auditor qualification run shape differs")
    mode = value["mode"]
    status = value["expectedStatus"]
    reason = value["expectedReason"]
    raw_evidence = value["expectedEvidence"]
    raw_pairs = value["expectedFindingPairs"]
    if (
        not isinstance(mode, str)
        or mode not in _MODES
        or not isinstance(status, str)
        or status not in _STATUSES
        or reason not in _REASONS
        or not isinstance(raw_evidence, list)
        or len(raw_evidence) > 8
        or not isinstance(raw_pairs, list)
        or len(raw_pairs) > 5
    ):
        raise ValueError("Auditor qualification run contract differs")
    selectors = tuple(_selector(item) for item in raw_evidence)
    pairs = tuple(
        tuple(_bounded_int(index, 0, 7, "finding evidence index") for index in pair)
        for pair in raw_pairs
        if isinstance(pair, list) and len(pair) == 2
    )
    if (
        len(pairs) != len(raw_pairs)
        or len({item.concept_id for item in selectors}) != len(selectors)
        or any(left >= right for left, right in pairs)
        or tuple(sorted(set(pairs))) != pairs
        or any(right >= len(selectors) for _, right in pairs)
    ):
        raise ValueError("Auditor qualification evidence selection differs")
    expected_by_mode = {
        "pre-cancelled": ("cancelled", "client-cancelled", False, False),
        "client-cancelled": ("cancelled", "client-cancelled", True, False),
        "deadline": ("cancelled", "deadline-exceeded", True, False),
        "stale-generation": (
            "evidence-unavailable",
            "stale-generation",
            True,
            False,
        ),
        "invalid-output": ("failed", "invalid-output", True, False),
    }
    if mode == "normal":
        valid_normal = (
            status == "complete" and reason is None and len(selectors) >= 2 and pairs
        ) or (
            status == "evidence-unavailable"
            and reason in {"empty-result", "model-evidence-unavailable"}
            and (len(selectors) >= 2) == (reason == "model-evidence-unavailable")
            and not pairs
        )
        if not valid_normal:
            raise ValueError("Auditor qualification normal run differs")
    else:
        expected_status, expected_reason, has_evidence, has_indexes = expected_by_mode[
            mode
        ]
        if (
            status != expected_status
            or reason != expected_reason
            or bool(selectors) != has_evidence
            or bool(pairs) != has_indexes
        ):
            raise ValueError("Auditor qualification controlled run differs")
    return AuditorQualificationRun(
        _identity(value["runId"], "run identity"),
        mode,
        status,
        reason,
        selectors,
        pairs,
    )


def _selector(value: object) -> AuditorExpectedSelector:
    if not isinstance(value, dict) or set(value) != {"conceptId", "quote"}:
        raise ValueError("Auditor qualification selector shape differs")
    return AuditorExpectedSelector(
        _concept(value["conceptId"], "evidence concept"),
        _text(value["quote"], "evidence quote", 2_000),
    )


def _auditor_librarian_corpus(
    corpus: AuditorQualificationCorpus,
) -> LibrarianQualificationCorpus:
    if not isinstance(corpus, AuditorQualificationCorpus):
        raise TypeError("Auditor qualification corpus type is invalid")
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
    cases: list[LibrarianQualificationCase] = []
    for case in corpus.cases:
        normal = next(run for run in case.runs if run.mode == "normal")
        for run in case.runs:
            if run.mode != "pre-cancelled" and (
                run.expected_evidence != normal.expected_evidence
            ):
                raise ValueError("Auditor controlled evidence map differs")
        cases.append(
            LibrarianQualificationCase(
                case.case_id,
                case.owner_id,
                case.active_generation_id,
                LibrarianQualificationRequest(
                    "knowledge.read",
                    case.request.focus,
                    8,
                    case.request.expected_generation_id,
                ),
                (
                    LibrarianQualificationRun(
                        "normal",
                        "normal",
                        (
                            "complete"
                            if normal.expected_evidence
                            else "evidence-unavailable"
                        ),
                        None if normal.expected_evidence else "empty-result",
                        tuple(
                            LibrarianExpectedSelector(item.concept_id, item.quote)
                            for item in normal.expected_evidence
                        ),
                    ),
                ),
            )
        )
    return LibrarianQualificationCorpus(
        corpus.corpus_id,
        corpus.corpus_sha256,
        corpus.tenant_id,
        generations,
        tuple(cases),
    )


def render_auditor_qualification_generations(
    corpus: AuditorQualificationCorpus,
    *,
    tenant_id: str,
) -> tuple[AuditorQualificationRenderedGeneration, ...]:
    """Render the exact OKF and permission bytes owned by the evaluator."""

    return render_librarian_qualification_generations(
        _auditor_librarian_corpus(corpus),
        tenant_id=_identity(tenant_id, "runtime tenant identity"),
    )


def bind_auditor_compiled_corpus(
    corpus: AuditorQualificationCorpus,
    rendered: tuple[AuditorQualificationRenderedGeneration, ...],
    compiled_generations: Mapping[str, AuditorCompiledGeneration],
    *,
    source_admission_sha256s: Mapping[str, str],
) -> AuditorBoundQualificationCorpus:
    """Bind expected reports to independently rendered production compilation."""

    if not isinstance(corpus, AuditorQualificationCorpus):
        raise TypeError("Auditor qualification corpus type is invalid")
    librarian_bound = bind_librarian_compiled_corpus(
        _auditor_librarian_corpus(corpus),
        rendered,
        compiled_generations,
    )
    source_admissions = _runtime_source_admission_sha256s(
        corpus, source_admission_sha256s
    )
    evidence_by_case: dict[str, AuditorEvidencePack] = {}
    expected_views: dict[str, AuditorExpectedView] = {}
    for case in corpus.cases:
        librarian_expected = librarian_bound.expected_views[f"{case.case_id}:normal"]
        evidence: AuditorEvidencePack | None = None
        if librarian_expected.status == "complete":
            if (
                librarian_expected.reason is not None
                or librarian_expected.generation_sha256 is None
                or librarian_expected.permission_hash is None
                or librarian_expected.authorization_hash is None
                or librarian_expected.evidence_sha256 is None
                or not librarian_expected.items
                or librarian_expected.output_budget_exhausted
            ):
                raise ValueError("Auditor qualification Librarian evidence differs")
            evidence = AuditorEvidencePack.create(
                generation_sha256=librarian_expected.generation_sha256,
                source_admission_sha256=source_admissions[case.active_generation_id],
                permission_hash=librarian_expected.permission_hash,
                authorization_hash=librarian_expected.authorization_hash,
                items=tuple(
                    LibrarianEvidenceItem(
                        item.concept_id,
                        item.source_revision,
                        item.content_sha256,
                        item.char_start,
                        item.char_end,
                        item.text,
                    )
                    for item in librarian_expected.items
                ),
                output_budget_exhausted=False,
            )
            evidence_by_case[case.case_id] = evidence
        elif librarian_expected != librarian_expected.__class__(
            "evidence-unavailable",
            None,
            None,
            None,
            None,
            (),
            False,
            "empty-result",
        ):
            raise ValueError("Auditor qualification Librarian terminal differs")
        request = AuditorRequest(
            focus=case.request.focus,
            maximum_findings=case.request.maximum_findings,
            expected_generation_sha256=librarian_bound.generation_sha256s[
                case.request.expected_generation_id
            ],
        )
        for run in case.runs:
            report = None
            if run.expected_status == "complete":
                if evidence is None:
                    raise ValueError("Auditor qualification report lacks evidence")
                report = build_auditor_report(
                    request,
                    evidence,
                    AuditorDecision("report", run.expected_finding_pairs),
                )
                if report is None:
                    raise ValueError("Auditor qualification report is absent")
            expected_views[f"{case.case_id}:{run.run_id}"] = AuditorExpectedView(
                run.expected_status,
                run.expected_reason,
                report,
            )
    return AuditorBoundQualificationCorpus(
        corpus,
        librarian_bound.tenant_id,
        MappingProxyType(dict(librarian_bound.generation_sha256s)),
        MappingProxyType(source_admissions),
        MappingProxyType(evidence_by_case),
        MappingProxyType(expected_views),
    )


def build_auditor_qualification_invocations(
    corpus: AuditorQualificationCorpus,
    acceptance: AuditorQualificationAcceptance,
    *,
    tenant_id: str | None = None,
    generation_sha256s: Mapping[str, str] | None = None,
) -> tuple[AuditorQualificationInvocation, ...]:
    if not isinstance(corpus, AuditorQualificationCorpus):
        raise TypeError("Auditor qualification corpus type is invalid")
    if not isinstance(acceptance, AuditorQualificationAcceptance):
        raise TypeError("Auditor qualification acceptance type is invalid")
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
        raise ValueError("Auditor qualification wave cases differ")
    normal: list[AuditorQualificationInvocation] = []
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
    case: AuditorQualificationCase,
    run: AuditorQualificationRun,
    *,
    runtime_tenant: str,
    runtime_generations: Mapping[str, str],
    invocation_id: str,
    wave_id: str | None,
    declared_position: int | None,
) -> AuditorQualificationInvocation:
    return AuditorQualificationInvocation(
        invocation_id=invocation_id,
        case_id=case.case_id,
        run_id=run.run_id,
        mode=run.mode,
        expected_view_id=f"{case.case_id}:{run.run_id}",
        wave_id=wave_id,
        declared_position=declared_position,
        tenant_id=runtime_tenant,
        owner_id=case.owner_id,
        focus=case.request.focus,
        maximum_findings=case.request.maximum_findings,
        expected_generation_sha256=runtime_generations[
            case.request.expected_generation_id
        ],
    )


def evaluate_auditor_qualification(
    *,
    executor: AuditorQualificationExecutor,
    corpus: AuditorBoundQualificationCorpus,
    acceptance: AuditorQualificationAcceptance,
) -> AuditorQualificationResult:
    if not callable(executor):
        raise TypeError("Auditor qualification executor is invalid")
    if not isinstance(acceptance, AuditorQualificationAcceptance):
        raise TypeError("Auditor qualification acceptance type is invalid")
    if not isinstance(corpus, AuditorBoundQualificationCorpus):
        raise TypeError("Auditor qualification corpus is not compiler-bound")
    invocations = build_auditor_qualification_invocations(
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
        raise ValueError("Auditor qualification synchronized waves differ")
    primary_observations: list[AuditorQualificationObservation] = []
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
    report_observations = tuple(
        item for item in observations if item.expected.report is not None
    )
    unavailable_observations = tuple(
        item for item in observations if item.expected.status == "evidence-unavailable"
    )
    cancellation_ids = (
        "control:numeric-limit-conflict:client-cancelled",
        "control:absent-unavailable:pre-cancelled",
    )
    hidden_normal = tuple(
        item
        for item in primary_observations
        if item.invocation.case_id == "hidden-only-unavailable"
    )
    absent_normal = tuple(
        item
        for item in primary_observations
        if item.invocation.case_id == "absent-unavailable"
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
        "completeCount": sum(
            item.observed is not None and item.observed.status == "complete"
            for item in observations
        ),
        "unavailableCount": sum(
            item.observed is not None and item.observed.status == "evidence-unavailable"
            for item in observations
        ),
        "failedCount": sum(
            item.observed is not None and item.observed.status == "failed"
            for item in observations
        ),
        "cancelledCount": sum(
            item.observed is not None and item.observed.status == "cancelled"
            for item in observations
        ),
        "exactTerminalMatchCount": sum(item.exact_match for item in observations),
        "exactReportMatchCount": sum(item.exact_match for item in report_observations),
        "uniqueRequestIdCount": len(set(request_ids)),
        "reportCount": sum(
            item.observed is not None and item.observed.report is not None
            for item in observations
        ),
        "findingCount": sum(
            len(item.observed.report.findings)
            if item.observed is not None and item.observed.report is not None
            else 0
            for item in observations
        ),
        "citationCount": sum(
            sum(len(finding.citations) for finding in item.observed.report.findings)
            if item.observed is not None and item.observed.report is not None
            else 0
            for item in observations
        ),
        "terminalMismatchCount": sum(not item.exact_match for item in observations),
        "warmProviderRepeatabilityMet": (
            exact_wave_count == acceptance.synchronized_wave_count
        ),
        "normalP95WithinBound": normal_durations[p95_index]
        <= acceptance.maximum_normal_p95_milliseconds,
        "serverDerivedReportExact": bool(report_observations)
        and all(item.exact_match for item in report_observations),
        "serverOwnedCitationsExact": bool(report_observations)
        and all(
            item.exact_match
            and item.observed is not None
            and item.observed.report == item.expected.report
            for item in report_observations
        ),
        "canonicalPairOrderExact": bool(report_observations)
        and all(
            item.exact_match
            and item.observed is not None
            and _report_pairs_are_canonical(
                item.observed.report,
                corpus.evidence_by_case[item.invocation.case_id],
            )
            for item in report_observations
        ),
        "reviewOnlyContractMet": bool(report_observations)
        and all(
            item.observed is not None
            and item.observed.report is not None
            and item.observed.report.canonical is False
            and item.observed.report.requires_review is True
            and all(
                finding.requires_review is True
                for finding in item.observed.report.findings
            )
            for item in report_observations
        ),
        "noncanonicalReviewRequiredExact": bool(report_observations)
        and all(
            item.exact_match
            and item.observed is not None
            and item.observed.report == item.expected.report
            and item.observed.report.canonical is False
            and item.observed.report.requires_review is True
            for item in report_observations
        ),
        "hiddenOnlyIndistinguishable": (
            len(hidden_normal) == acceptance.synchronized_wave_count
            and len(absent_normal) == acceptance.synchronized_wave_count
            and all(
                hidden.exact_match
                and absent.exact_match
                and hidden.observed
                == absent.observed
                == AuditorExpectedView("evidence-unavailable", "empty-result", None)
                for hidden, absent in zip(hidden_normal, absent_normal, strict=True)
            )
        ),
        "unavailableReportAbsent": bool(unavailable_observations)
        and all(
            item.exact_match
            and item.observed is not None
            and item.observed.report is None
            for item in unavailable_observations
        ),
        "cancellationFailedClosed": all(
            by_id[item].exact_match
            and by_id[item].observed is not None
            and by_id[item].observed.report is None
            for item in cancellation_ids
        ),
        "deadlineFailedClosed": by_id["control:status-conflict:deadline"].exact_match,
        "staleGenerationFailedClosed": by_id[
            "control:instruction-data-conflict:stale-generation"
        ].exact_match,
        "invalidOutputFailedClosed": by_id[
            "control:multi-conflict:invalid-output"
        ].exact_match,
        "workerContainmentMet": True,
    }
    required = acceptance.expected_public_evidence()
    public["qualified"] = all(
        public[key] == value for key, value in required.items() if key != "qualified"
    )
    return AuditorQualificationResult(public, tuple(observations))


def _report_pairs_are_canonical(
    report: AuditorReport | None,
    evidence: AuditorEvidencePack,
) -> bool:
    if not isinstance(report, AuditorReport):
        return False
    try:
        pairs = tuple(
            tuple(evidence.items.index(citation) for citation in finding.citations)
            for finding in report.findings
        )
    except ValueError:
        return False
    return all(
        len(pair) == 2 and pair[0] < pair[1] for pair in pairs
    ) and pairs == tuple(sorted(set(pairs)))


def _run_synchronized_wave(
    executor: AuditorQualificationExecutor,
    invocations: tuple[AuditorQualificationInvocation, ...],
    expected_views: Mapping[str, AuditorExpectedView],
) -> list[AuditorQualificationObservation]:
    barrier = threading.Barrier(len(invocations))
    cancellations = {item.invocation_id: threading.Event() for item in invocations}
    pool: ThreadPoolExecutor | None = ThreadPoolExecutor(
        max_workers=len(invocations),
        thread_name_prefix="auditor-qualification",
    )
    try:
        futures: list[Future[AuditorQualificationObservation]] = [
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
                    "Auditor qualification cancellation was not contained"
                )
            pool.shutdown(wait=True, cancel_futures=True)
            pool = None
            raise TimeoutError("Auditor qualification wave exceeded its timeout")
        return [future.result() for future in futures]
    finally:
        if pool is not None:
            pool.shutdown(wait=True, cancel_futures=True)


def _run_invocation(
    executor: AuditorQualificationExecutor,
    invocation: AuditorQualificationInvocation,
    expected: AuditorExpectedView,
    cancellation: threading.Event,
    barrier: threading.Barrier | None,
) -> AuditorQualificationObservation:
    if barrier is not None:
        try:
            barrier.wait(timeout=_PRIMARY_WAVE_TIMEOUT_SECONDS)
        except threading.BrokenBarrierError as error:
            raise RuntimeError(
                "Auditor qualification synchronization failed"
            ) from error
    started = time.monotonic()
    try:
        request_id, observed = _observed_view(executor(invocation, cancellation))
        exact = observed == expected
        return AuditorQualificationObservation(
            invocation,
            expected,
            observed,
            request_id,
            _duration(started),
            exact,
            None if exact else "view-mismatch",
        )
    except Exception:
        return AuditorQualificationObservation(
            invocation,
            expected,
            None,
            None,
            _duration(started),
            False,
            "executor-error",
        )


def _observed_view(view: object) -> tuple[str, AuditorExpectedView]:
    if not isinstance(view, AuditorJobView):
        raise ValueError("Auditor qualification view type differs")
    request_id = _text(view.request_id, "request identity", 128)
    if (
        view.status not in _STATUSES
        or view.reason not in _REASONS | {"empty-result"}
        or (view.report is not None and not isinstance(view.report, AuditorReport))
    ):
        raise ValueError("Auditor qualification terminal view differs")
    valid = (
        (view.status == "complete" and view.reason is None and view.report is not None)
        or (
            view.status == "evidence-unavailable"
            and view.reason
            in {"empty-result", "model-evidence-unavailable", "stale-generation"}
            and view.report is None
        )
        or (
            view.status == "failed"
            and view.reason == "invalid-output"
            and view.report is None
        )
        or (
            view.status == "cancelled"
            and view.reason in {"client-cancelled", "deadline-exceeded"}
            and view.report is None
        )
    )
    if not valid:
        raise ValueError("Auditor qualification terminal binding differs")
    return request_id, AuditorExpectedView(view.status, view.reason, view.report)


def _runtime_generation_sha256s(
    corpus: AuditorQualificationCorpus,
    value: Mapping[str, str],
) -> dict[str, str]:
    expected = {item.generation_id for item in corpus.generations}
    if not isinstance(value, Mapping) or set(value) != expected:
        raise ValueError("Auditor qualification runtime generations differ")
    output = {
        generation_id: _sha(digest, "runtime generation digest")
        for generation_id, digest in value.items()
    }
    if len(set(output.values())) != len(output):
        raise ValueError("Auditor qualification runtime generations conflict")
    return output


def _runtime_source_admission_sha256s(
    corpus: AuditorQualificationCorpus,
    value: Mapping[str, str],
) -> dict[str, str]:
    expected = {item.generation_id for item in corpus.generations}
    if not isinstance(value, Mapping) or set(value) != expected:
        raise ValueError("Auditor qualification source admissions differ")
    output = {
        generation_id: _sha(digest, "source admission digest")
        for generation_id, digest in value.items()
    }
    if len(set(output.values())) != len(output):
        raise ValueError("Auditor qualification source admissions conflict")
    return output


def _identity(value: object, field: str) -> str:
    if not isinstance(value, str) or _IDENTITY.fullmatch(value) is None:
        raise ValueError(f"Auditor qualification {field} is invalid")
    return value


def _concept(value: object, field: str) -> str:
    if not isinstance(value, str) or _CONCEPT_ID.fullmatch(value) is None:
        raise ValueError(f"Auditor qualification {field} is invalid")
    return value


def _sha(value: object, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"Auditor qualification {field} is invalid")
    return value


def _text(value: object, field: str, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= maximum
        or value.strip() != value
        or "\0" in value
        or "\r" in value
    ):
        raise ValueError(f"Auditor qualification {field} is invalid")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError(f"Auditor qualification {field} is invalid") from error
    return value


def _bounded_int(value: object, minimum: int, maximum: int, field: str) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not minimum <= value <= maximum
    ):
        raise ValueError(f"Auditor qualification {field} is invalid")
    return value


def _count(value: object, field: str) -> int:
    return _bounded_int(value, 0, 1_000_000, field)


def _flag(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"Auditor qualification {field} is invalid")
    return value


def _duration(started: float) -> int:
    return max(0, round((time.monotonic() - started) * 1_000))


__all__ = [
    "AuditorBoundQualificationCorpus",
    "AuditorCompiledChunk",
    "AuditorCompiledConcept",
    "AuditorCompiledGeneration",
    "AuditorCompiledPermission",
    "AuditorExpectedSelector",
    "AuditorExpectedView",
    "AuditorQualificationAcceptance",
    "AuditorQualificationCase",
    "AuditorQualificationCorpus",
    "AuditorQualificationGeneration",
    "AuditorQualificationInvocation",
    "AuditorQualificationObservation",
    "AuditorQualificationRenderedFile",
    "AuditorQualificationRenderedGeneration",
    "AuditorQualificationRenderedSource",
    "AuditorQualificationRequest",
    "AuditorQualificationResult",
    "AuditorQualificationRun",
    "AuditorQualificationSource",
    "AuditorQualificationWave",
    "bind_auditor_compiled_corpus",
    "build_auditor_qualification_invocations",
    "evaluate_auditor_qualification",
    "load_auditor_qualification_acceptance",
    "load_auditor_qualification_corpus",
    "render_auditor_qualification_generations",
]
