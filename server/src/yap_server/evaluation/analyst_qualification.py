"""Public synthetic qualification for grounded, server-derived Analyst answers."""

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

from yap_server.agents.analyst import (
    AnalystAnswer,
    AnalystRequest,
    build_analyst_answer,
)
from yap_server.agents.analyst_model import AnalystDecision
from yap_server.agents.analyst_service import AnalystJobView
from yap_server.agents.librarian import (
    LibrarianEvidenceItem,
    LibrarianEvidencePack,
)
from yap_server.private_artifact import read_json_object_with_identity

from .librarian_qualification import (
    LibrarianCompiledChunk as AnalystCompiledChunk,
    LibrarianCompiledConcept as AnalystCompiledConcept,
    LibrarianCompiledGeneration as AnalystCompiledGeneration,
    LibrarianCompiledPermission as AnalystCompiledPermission,
    LibrarianExpectedSelector,
    LibrarianQualificationCase,
    LibrarianQualificationCorpus,
    LibrarianQualificationGeneration,
    LibrarianQualificationRenderedFile as AnalystQualificationRenderedFile,
    LibrarianQualificationRenderedGeneration as AnalystQualificationRenderedGeneration,
    LibrarianQualificationRenderedSource as AnalystQualificationRenderedSource,
    LibrarianQualificationRequest,
    LibrarianQualificationRun,
    LibrarianQualificationSource,
    bind_librarian_compiled_corpus,
    render_librarian_qualification_generations,
)


_SCOPE = "analyst-grounded-cited-answers"
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


class AnalystQualificationExecutor(Protocol):
    def __call__(
        self,
        invocation: AnalystQualificationInvocation,
        cancellation: threading.Event,
    ) -> object: ...


@dataclass(frozen=True, slots=True)
class AnalystQualificationWave:
    wave_id: str
    case_order: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AnalystQualificationAcceptance:
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
    exact_answer_match_count: int
    unique_request_id_count: int
    answer_count: int
    citation_count: int
    terminal_mismatch_count: int
    warm_provider_repeatability_met: bool
    normal_p95_within_bound: bool
    server_derived_answer_exact: bool
    server_owned_citations_exact: bool
    unavailable_answer_absent: bool
    cancellation_failed_closed: bool
    deadline_failed_closed: bool
    stale_generation_failed_closed: bool
    invalid_output_failed_closed: bool
    worker_containment_met: bool
    synchronized_waves: tuple[AnalystQualificationWave, ...] = field(repr=False)

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
            "exactAnswerMatchCount": self.exact_answer_match_count,
            "uniqueRequestIdCount": self.unique_request_id_count,
            "answerCount": self.answer_count,
            "citationCount": self.citation_count,
            "terminalMismatchCount": self.terminal_mismatch_count,
            "warmProviderRepeatabilityMet": self.warm_provider_repeatability_met,
            "normalP95WithinBound": self.normal_p95_within_bound,
            "serverDerivedAnswerExact": self.server_derived_answer_exact,
            "serverOwnedCitationsExact": self.server_owned_citations_exact,
            "unavailableAnswerAbsent": self.unavailable_answer_absent,
            "cancellationFailedClosed": self.cancellation_failed_closed,
            "deadlineFailedClosed": self.deadline_failed_closed,
            "staleGenerationFailedClosed": self.stale_generation_failed_closed,
            "invalidOutputFailedClosed": self.invalid_output_failed_closed,
            "workerContainmentMet": self.worker_containment_met,
        }


@dataclass(frozen=True, slots=True)
class AnalystQualificationSource:
    concept_id: str
    source_revision: str
    body: str
    evidence_quote: str
    visible_to_owner_ids: frozenset[str]
    linked_concept_ids: tuple[str, ...]
    retrieval_rank: int


@dataclass(frozen=True, slots=True)
class AnalystQualificationGeneration:
    generation_id: str
    generation_sha256: str
    sources: tuple[AnalystQualificationSource, ...]


@dataclass(frozen=True, slots=True)
class AnalystExpectedSelector:
    concept_id: str
    quote: str


@dataclass(frozen=True, slots=True)
class AnalystQualificationRun:
    run_id: str
    mode: str
    expected_status: str
    expected_reason: str | None
    expected_evidence: tuple[AnalystExpectedSelector, ...]
    expected_answer_evidence_indexes: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class AnalystQualificationRequest:
    question: str
    maximum_results: int
    expected_generation_id: str


@dataclass(frozen=True, slots=True)
class AnalystQualificationCase:
    case_id: str
    owner_id: str
    active_generation_id: str
    request: AnalystQualificationRequest
    runs: tuple[AnalystQualificationRun, ...]


@dataclass(frozen=True, slots=True)
class AnalystQualificationCorpus:
    corpus_id: str
    corpus_sha256: str
    tenant_id: str
    generations: tuple[AnalystQualificationGeneration, ...]
    cases: tuple[AnalystQualificationCase, ...]


@dataclass(frozen=True, slots=True)
class AnalystExpectedView:
    status: str
    reason: str | None
    answer: AnalystAnswer | None


@dataclass(frozen=True, slots=True)
class AnalystBoundQualificationCorpus:
    corpus: AnalystQualificationCorpus
    tenant_id: str
    generation_sha256s: Mapping[str, str]
    evidence_by_case: Mapping[str, LibrarianEvidencePack]
    expected_views: Mapping[str, AnalystExpectedView]


@dataclass(frozen=True, slots=True)
class AnalystQualificationInvocation:
    invocation_id: str
    case_id: str
    run_id: str
    mode: str
    expected_view_id: str
    wave_id: str | None
    declared_position: int | None
    tenant_id: str
    owner_id: str
    question: str
    maximum_results: int
    expected_generation_sha256: str


@dataclass(frozen=True, slots=True)
class AnalystQualificationObservation:
    invocation: AnalystQualificationInvocation = field(repr=False)
    expected: AnalystExpectedView = field(repr=False)
    observed: AnalystExpectedView | None = field(repr=False)
    request_id: str | None = field(repr=False)
    duration_milliseconds: int = field(repr=False)
    exact_match: bool
    failure_kind: str | None


@dataclass(frozen=True, slots=True)
class AnalystQualificationResult:
    public_evidence: dict[str, int | bool]
    observations: tuple[AnalystQualificationObservation, ...] = field(repr=False)


def load_analyst_qualification_acceptance(
    path: Path,
) -> AnalystQualificationAcceptance:
    value, identity = read_json_object_with_identity(
        path,
        maximum_bytes=_MAXIMUM_ACCEPTANCE_BYTES,
        field="Analyst qualification acceptance",
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
        "exactAnswerMatchCount",
        "uniqueRequestIdCount",
        "answerCount",
        "citationCount",
        "terminalMismatchCount",
        "warmProviderRepeatabilityMet",
        "normalP95WithinBound",
        "serverDerivedAnswerExact",
        "serverOwnedCitationsExact",
        "unavailableAnswerAbsent",
        "cancellationFailedClosed",
        "deadlineFailedClosed",
        "staleGenerationFailedClosed",
        "invalidOutputFailedClosed",
        "workerContainmentMet",
    }
    if set(value) != fields:
        raise ValueError("Analyst qualification acceptance shape differs")
    if (
        type(value["schemaVersion"]) is not int
        or value["schemaVersion"] != 2
        or value["qualificationScope"] != _SCOPE
        or value["qualified"] is not True
    ):
        raise ValueError("Analyst qualification acceptance identity differs")
    raw_waves = value["synchronizedWaves"]
    if not isinstance(raw_waves, list):
        raise ValueError("Analyst qualification waves differ")
    waves = tuple(_acceptance_wave(item) for item in raw_waves)
    acceptance = AnalystQualificationAcceptance(
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
        exact_answer_match_count=_count(
            value["exactAnswerMatchCount"], "exactAnswerMatchCount"
        ),
        unique_request_id_count=_count(
            value["uniqueRequestIdCount"], "uniqueRequestIdCount"
        ),
        answer_count=_count(value["answerCount"], "answerCount"),
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
        server_derived_answer_exact=_flag(
            value["serverDerivedAnswerExact"], "serverDerivedAnswerExact"
        ),
        server_owned_citations_exact=_flag(
            value["serverOwnedCitationsExact"], "serverOwnedCitationsExact"
        ),
        unavailable_answer_absent=_flag(
            value["unavailableAnswerAbsent"], "unavailableAnswerAbsent"
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
        or acceptance.exact_answer_match_count != 12
        or acceptance.unique_request_id_count != 29
        or acceptance.answer_count != 12
        or acceptance.citation_count != 15
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
                acceptance.server_derived_answer_exact,
                acceptance.server_owned_citations_exact,
                acceptance.unavailable_answer_absent,
                acceptance.cancellation_failed_closed,
                acceptance.deadline_failed_closed,
                acceptance.stale_generation_failed_closed,
                acceptance.invalid_output_failed_closed,
                acceptance.worker_containment_met,
            )
        )
    ):
        raise ValueError("Analyst qualification acceptance values conflict")
    return acceptance


def _acceptance_wave(value: object) -> AnalystQualificationWave:
    if not isinstance(value, dict) or set(value) != {"waveId", "caseOrder"}:
        raise ValueError("Analyst qualification wave shape differs")
    order = value["caseOrder"]
    if (
        not isinstance(order, list)
        or len(order) != len(set(order))
        or not all(isinstance(item, str) for item in order)
    ):
        raise ValueError("Analyst qualification case order differs")
    return AnalystQualificationWave(
        _identity(value["waveId"], "wave identity"),
        tuple(_identity(item, "wave case identity") for item in order),
    )


def load_analyst_qualification_corpus(path: Path) -> AnalystQualificationCorpus:
    value, identity = read_json_object_with_identity(
        path,
        maximum_bytes=_MAXIMUM_FIXTURE_BYTES,
        field="Analyst qualification fixtures",
    )
    if set(value) != {
        "schemaVersion",
        "qualificationScope",
        "corpusId",
        "tenantId",
        "generations",
        "cases",
    }:
        raise ValueError("Analyst qualification fixture shape differs")
    if (
        type(value["schemaVersion"]) is not int
        or value["schemaVersion"] != 1
        or value["qualificationScope"] != _SCOPE
    ):
        raise ValueError("Analyst qualification fixture identity differs")
    generations_raw = value["generations"]
    cases_raw = value["cases"]
    if (
        not isinstance(generations_raw, list)
        or len(generations_raw) != 2
        or not isinstance(cases_raw, list)
        or len(cases_raw) != 8
    ):
        raise ValueError("Analyst qualification fixture cardinality differs")
    corpus = AnalystQualificationCorpus(
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
        raise ValueError("Analyst qualification wave contract differs")
    _analyst_librarian_corpus(corpus)
    return corpus


def _generation(value: object) -> AnalystQualificationGeneration:
    if not isinstance(value, dict) or set(value) != {
        "generationId",
        "generationSha256",
        "sources",
    }:
        raise ValueError("Analyst qualification generation shape differs")
    raw_sources = value["sources"]
    if not isinstance(raw_sources, list) or not 1 <= len(raw_sources) <= 64:
        raise ValueError("Analyst qualification generation sources differ")
    sources = tuple(_source(item) for item in raw_sources)
    concept_ids = {item.concept_id for item in sources}
    if len(concept_ids) != len(sources) or any(
        not set(item.linked_concept_ids) <= concept_ids for item in sources
    ):
        raise ValueError("Analyst qualification source identity differs")
    return AnalystQualificationGeneration(
        _identity(value["generationId"], "generation identity"),
        _sha(value["generationSha256"], "generation digest"),
        sources,
    )


def _source(value: object) -> AnalystQualificationSource:
    if not isinstance(value, dict) or set(value) != {
        "conceptId",
        "sourceRevision",
        "body",
        "evidenceQuote",
        "visibleToOwnerIds",
        "linkedConceptIds",
        "retrievalRank",
    }:
        raise ValueError("Analyst qualification source shape differs")
    owners = value["visibleToOwnerIds"]
    links = value["linkedConceptIds"]
    if (
        not isinstance(owners, list)
        or not owners
        or len(owners) != len(set(owners))
        or not isinstance(links, list)
        or len(links) != len(set(links))
    ):
        raise ValueError("Analyst qualification source permission differs")
    body = _text(value["body"], "source body", 4_096)
    quote = _text(value["evidenceQuote"], "evidence quote", 2_000)
    if body.count(quote) != 1:
        raise ValueError("Analyst qualification evidence quote differs")
    return AnalystQualificationSource(
        _concept(value["conceptId"], "source concept"),
        _text(value["sourceRevision"], "source revision", 512),
        body,
        quote,
        frozenset(_identity(item, "visible owner") for item in owners),
        tuple(_concept(item, "linked concept") for item in links),
        _bounded_int(value["retrievalRank"], 1, 2**31 - 1, "retrieval rank"),
    )


def _case(value: object) -> AnalystQualificationCase:
    if not isinstance(value, dict) or set(value) != {
        "caseId",
        "ownerId",
        "activeGenerationId",
        "request",
        "runs",
    }:
        raise ValueError("Analyst qualification case shape differs")
    raw_request = value["request"]
    raw_runs = value["runs"]
    if not isinstance(raw_request, dict) or set(raw_request) != {
        "question",
        "maximumResults",
        "expectedGenerationId",
    }:
        raise ValueError("Analyst qualification request shape differs")
    question = _text(raw_request["question"], "question", 1_024)
    if not any(character.isalnum() for character in question):
        raise ValueError("Analyst qualification question differs")
    request = AnalystQualificationRequest(
        question,
        _bounded_int(raw_request["maximumResults"], 1, 5, "result limit"),
        _identity(
            raw_request["expectedGenerationId"],
            "expected generation identity",
        ),
    )
    if not isinstance(raw_runs, list) or not 1 <= len(raw_runs) <= 3:
        raise ValueError("Analyst qualification run count differs")
    runs = tuple(_run(item) for item in raw_runs)
    if len({item.run_id for item in runs}) != len(runs):
        raise ValueError("Analyst qualification run identity differs")
    return AnalystQualificationCase(
        _identity(value["caseId"], "case identity"),
        _identity(value["ownerId"], "owner identity"),
        _identity(value["activeGenerationId"], "active generation identity"),
        request,
        runs,
    )


def _run(value: object) -> AnalystQualificationRun:
    if not isinstance(value, dict) or set(value) != {
        "runId",
        "mode",
        "expectedStatus",
        "expectedReason",
        "expectedEvidence",
        "expectedAnswerEvidenceIndexes",
    }:
        raise ValueError("Analyst qualification run shape differs")
    mode = value["mode"]
    status = value["expectedStatus"]
    reason = value["expectedReason"]
    raw_evidence = value["expectedEvidence"]
    raw_indexes = value["expectedAnswerEvidenceIndexes"]
    if (
        not isinstance(mode, str)
        or mode not in _MODES
        or not isinstance(status, str)
        or status not in _STATUSES
        or reason not in _REASONS
        or not isinstance(raw_evidence, list)
        or len(raw_evidence) > 5
        or not isinstance(raw_indexes, list)
        or len(raw_indexes) > 5
    ):
        raise ValueError("Analyst qualification run contract differs")
    selectors = tuple(_selector(item) for item in raw_evidence)
    indexes = tuple(
        _bounded_int(item, 0, 4, "answer evidence index") for item in raw_indexes
    )
    if (
        len({item.concept_id for item in selectors}) != len(selectors)
        or len(set(indexes)) != len(indexes)
        or (indexes and max(indexes) >= len(selectors))
    ):
        raise ValueError("Analyst qualification evidence selection differs")
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
            status == "complete" and reason is None and selectors and indexes
        ) or (
            status == "evidence-unavailable"
            and reason in {"empty-result", "model-evidence-unavailable"}
            and bool(selectors) == (reason == "model-evidence-unavailable")
            and not indexes
        )
        if not valid_normal:
            raise ValueError("Analyst qualification normal run differs")
    else:
        expected_status, expected_reason, has_evidence, has_indexes = expected_by_mode[
            mode
        ]
        if (
            status != expected_status
            or reason != expected_reason
            or bool(selectors) != has_evidence
            or bool(indexes) != has_indexes
        ):
            raise ValueError("Analyst qualification controlled run differs")
    return AnalystQualificationRun(
        _identity(value["runId"], "run identity"),
        mode,
        status,
        reason,
        selectors,
        indexes,
    )


def _selector(value: object) -> AnalystExpectedSelector:
    if not isinstance(value, dict) or set(value) != {"conceptId", "quote"}:
        raise ValueError("Analyst qualification selector shape differs")
    return AnalystExpectedSelector(
        _concept(value["conceptId"], "evidence concept"),
        _text(value["quote"], "evidence quote", 2_000),
    )


def _analyst_librarian_corpus(
    corpus: AnalystQualificationCorpus,
) -> LibrarianQualificationCorpus:
    if not isinstance(corpus, AnalystQualificationCorpus):
        raise TypeError("Analyst qualification corpus type is invalid")
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
                raise ValueError("Analyst controlled evidence map differs")
        cases.append(
            LibrarianQualificationCase(
                case.case_id,
                case.owner_id,
                case.active_generation_id,
                LibrarianQualificationRequest(
                    "knowledge.read",
                    case.request.question,
                    case.request.maximum_results,
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


def render_analyst_qualification_generations(
    corpus: AnalystQualificationCorpus,
    *,
    tenant_id: str,
) -> tuple[AnalystQualificationRenderedGeneration, ...]:
    """Render the exact OKF and permission bytes owned by the evaluator."""

    return render_librarian_qualification_generations(
        _analyst_librarian_corpus(corpus),
        tenant_id=_identity(tenant_id, "runtime tenant identity"),
    )


def bind_analyst_compiled_corpus(
    corpus: AnalystQualificationCorpus,
    rendered: tuple[AnalystQualificationRenderedGeneration, ...],
    compiled_generations: Mapping[str, AnalystCompiledGeneration],
) -> AnalystBoundQualificationCorpus:
    """Bind expected answers to independently rendered production compilation."""

    if not isinstance(corpus, AnalystQualificationCorpus):
        raise TypeError("Analyst qualification corpus type is invalid")
    librarian_bound = bind_librarian_compiled_corpus(
        _analyst_librarian_corpus(corpus),
        rendered,
        compiled_generations,
    )
    evidence_by_case: dict[str, LibrarianEvidencePack] = {}
    expected_views: dict[str, AnalystExpectedView] = {}
    for case in corpus.cases:
        librarian_expected = librarian_bound.expected_views[f"{case.case_id}:normal"]
        evidence: LibrarianEvidencePack | None = None
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
                raise ValueError("Analyst qualification Librarian evidence differs")
            evidence = LibrarianEvidencePack.create(
                generation_sha256=librarian_expected.generation_sha256,
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
            if evidence.evidence_sha256 != librarian_expected.evidence_sha256:
                raise ValueError("Analyst qualification evidence digest differs")
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
            raise ValueError("Analyst qualification Librarian terminal differs")
        request = AnalystRequest(
            question=case.request.question,
            maximum_results=case.request.maximum_results,
            expected_generation_sha256=librarian_bound.generation_sha256s[
                case.request.expected_generation_id
            ],
        )
        for run in case.runs:
            answer = None
            if run.expected_status == "complete":
                if evidence is None:
                    raise ValueError("Analyst qualification answer lacks evidence")
                answer = build_analyst_answer(
                    request,
                    evidence,
                    AnalystDecision("answer", run.expected_answer_evidence_indexes),
                )
                if answer is None:
                    raise ValueError("Analyst qualification answer is absent")
            expected_views[f"{case.case_id}:{run.run_id}"] = AnalystExpectedView(
                run.expected_status,
                run.expected_reason,
                answer,
            )
    return AnalystBoundQualificationCorpus(
        corpus,
        librarian_bound.tenant_id,
        MappingProxyType(dict(librarian_bound.generation_sha256s)),
        MappingProxyType(evidence_by_case),
        MappingProxyType(expected_views),
    )


def build_analyst_qualification_invocations(
    corpus: AnalystQualificationCorpus,
    acceptance: AnalystQualificationAcceptance,
    *,
    tenant_id: str | None = None,
    generation_sha256s: Mapping[str, str] | None = None,
) -> tuple[AnalystQualificationInvocation, ...]:
    if not isinstance(corpus, AnalystQualificationCorpus):
        raise TypeError("Analyst qualification corpus type is invalid")
    if not isinstance(acceptance, AnalystQualificationAcceptance):
        raise TypeError("Analyst qualification acceptance type is invalid")
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
        raise ValueError("Analyst qualification wave cases differ")
    normal: list[AnalystQualificationInvocation] = []
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
    case: AnalystQualificationCase,
    run: AnalystQualificationRun,
    *,
    runtime_tenant: str,
    runtime_generations: Mapping[str, str],
    invocation_id: str,
    wave_id: str | None,
    declared_position: int | None,
) -> AnalystQualificationInvocation:
    return AnalystQualificationInvocation(
        invocation_id=invocation_id,
        case_id=case.case_id,
        run_id=run.run_id,
        mode=run.mode,
        expected_view_id=f"{case.case_id}:{run.run_id}",
        wave_id=wave_id,
        declared_position=declared_position,
        tenant_id=runtime_tenant,
        owner_id=case.owner_id,
        question=case.request.question,
        maximum_results=case.request.maximum_results,
        expected_generation_sha256=runtime_generations[
            case.request.expected_generation_id
        ],
    )


def evaluate_analyst_qualification(
    *,
    executor: AnalystQualificationExecutor,
    corpus: AnalystBoundQualificationCorpus,
    acceptance: AnalystQualificationAcceptance,
) -> AnalystQualificationResult:
    if not callable(executor):
        raise TypeError("Analyst qualification executor is invalid")
    if not isinstance(acceptance, AnalystQualificationAcceptance):
        raise TypeError("Analyst qualification acceptance type is invalid")
    if not isinstance(corpus, AnalystBoundQualificationCorpus):
        raise TypeError("Analyst qualification corpus is not compiler-bound")
    invocations = build_analyst_qualification_invocations(
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
        raise ValueError("Analyst qualification synchronized waves differ")
    primary_observations: list[AnalystQualificationObservation] = []
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
    answer_observations = tuple(
        item for item in observations if item.expected.answer is not None
    )
    unavailable_observations = tuple(
        item for item in observations if item.expected.status == "evidence-unavailable"
    )
    cancellation_ids = (
        "control:exact-single-answer:client-cancelled",
        "control:missing-date-unavailable:pre-cancelled",
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
        "exactAnswerMatchCount": sum(item.exact_match for item in answer_observations),
        "uniqueRequestIdCount": len(set(request_ids)),
        "answerCount": sum(
            item.observed is not None and item.observed.answer is not None
            for item in observations
        ),
        "citationCount": sum(
            len(item.observed.answer.citations)
            if item.observed is not None and item.observed.answer is not None
            else 0
            for item in observations
        ),
        "terminalMismatchCount": sum(not item.exact_match for item in observations),
        "warmProviderRepeatabilityMet": (
            exact_wave_count == acceptance.synchronized_wave_count
        ),
        "normalP95WithinBound": normal_durations[p95_index]
        <= acceptance.maximum_normal_p95_milliseconds,
        "serverDerivedAnswerExact": bool(answer_observations)
        and all(item.exact_match for item in answer_observations),
        "serverOwnedCitationsExact": bool(answer_observations)
        and all(
            item.exact_match
            and item.observed is not None
            and item.observed.answer == item.expected.answer
            for item in answer_observations
        ),
        "unavailableAnswerAbsent": bool(unavailable_observations)
        and all(
            item.exact_match
            and item.observed is not None
            and item.observed.answer is None
            for item in unavailable_observations
        ),
        "cancellationFailedClosed": all(
            by_id[item].exact_match
            and by_id[item].observed is not None
            and by_id[item].observed.answer is None
            for item in cancellation_ids
        ),
        "deadlineFailedClosed": by_id[
            "control:numeric-unit-answer:deadline"
        ].exact_match,
        "staleGenerationFailedClosed": by_id[
            "control:instruction-as-data-answer:stale-generation"
        ].exact_match,
        "invalidOutputFailedClosed": by_id[
            "control:ordered-multi-answer:invalid-output"
        ].exact_match,
        "workerContainmentMet": True,
    }
    required = acceptance.expected_public_evidence()
    public["qualified"] = all(
        public[key] == value for key, value in required.items() if key != "qualified"
    )
    return AnalystQualificationResult(public, tuple(observations))


def _run_synchronized_wave(
    executor: AnalystQualificationExecutor,
    invocations: tuple[AnalystQualificationInvocation, ...],
    expected_views: Mapping[str, AnalystExpectedView],
) -> list[AnalystQualificationObservation]:
    barrier = threading.Barrier(len(invocations))
    cancellations = {item.invocation_id: threading.Event() for item in invocations}
    pool: ThreadPoolExecutor | None = ThreadPoolExecutor(
        max_workers=len(invocations),
        thread_name_prefix="analyst-qualification",
    )
    try:
        futures: list[Future[AnalystQualificationObservation]] = [
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
                    "Analyst qualification cancellation was not contained"
                )
            pool.shutdown(wait=True, cancel_futures=True)
            pool = None
            raise TimeoutError("Analyst qualification wave exceeded its timeout")
        return [future.result() for future in futures]
    finally:
        if pool is not None:
            pool.shutdown(wait=True, cancel_futures=True)


def _run_invocation(
    executor: AnalystQualificationExecutor,
    invocation: AnalystQualificationInvocation,
    expected: AnalystExpectedView,
    cancellation: threading.Event,
    barrier: threading.Barrier | None,
) -> AnalystQualificationObservation:
    if barrier is not None:
        try:
            barrier.wait(timeout=_PRIMARY_WAVE_TIMEOUT_SECONDS)
        except threading.BrokenBarrierError as error:
            raise RuntimeError(
                "Analyst qualification synchronization failed"
            ) from error
    started = time.monotonic()
    try:
        request_id, observed = _observed_view(executor(invocation, cancellation))
        exact = observed == expected
        return AnalystQualificationObservation(
            invocation,
            expected,
            observed,
            request_id,
            _duration(started),
            exact,
            None if exact else "view-mismatch",
        )
    except Exception:
        return AnalystQualificationObservation(
            invocation,
            expected,
            None,
            None,
            _duration(started),
            False,
            "executor-error",
        )


def _observed_view(view: object) -> tuple[str, AnalystExpectedView]:
    if not isinstance(view, AnalystJobView):
        raise ValueError("Analyst qualification view type differs")
    request_id = _text(view.request_id, "request identity", 128)
    if (
        view.status not in _STATUSES
        or view.reason not in _REASONS | {"empty-result"}
        or (view.answer is not None and not isinstance(view.answer, AnalystAnswer))
    ):
        raise ValueError("Analyst qualification terminal view differs")
    valid = (
        (view.status == "complete" and view.reason is None and view.answer is not None)
        or (
            view.status == "evidence-unavailable"
            and view.reason
            in {"empty-result", "model-evidence-unavailable", "stale-generation"}
            and view.answer is None
        )
        or (
            view.status == "failed"
            and view.reason == "invalid-output"
            and view.answer is None
        )
        or (
            view.status == "cancelled"
            and view.reason in {"client-cancelled", "deadline-exceeded"}
            and view.answer is None
        )
    )
    if not valid:
        raise ValueError("Analyst qualification terminal binding differs")
    return request_id, AnalystExpectedView(view.status, view.reason, view.answer)


def _runtime_generation_sha256s(
    corpus: AnalystQualificationCorpus,
    value: Mapping[str, str],
) -> dict[str, str]:
    expected = {item.generation_id for item in corpus.generations}
    if not isinstance(value, Mapping) or set(value) != expected:
        raise ValueError("Analyst qualification runtime generations differ")
    output = {
        generation_id: _sha(digest, "runtime generation digest")
        for generation_id, digest in value.items()
    }
    if len(set(output.values())) != len(output):
        raise ValueError("Analyst qualification runtime generations conflict")
    return output


def _identity(value: object, field: str) -> str:
    if not isinstance(value, str) or _IDENTITY.fullmatch(value) is None:
        raise ValueError(f"Analyst qualification {field} is invalid")
    return value


def _concept(value: object, field: str) -> str:
    if not isinstance(value, str) or _CONCEPT_ID.fullmatch(value) is None:
        raise ValueError(f"Analyst qualification {field} is invalid")
    return value


def _sha(value: object, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"Analyst qualification {field} is invalid")
    return value


def _text(value: object, field: str, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= maximum
        or value.strip() != value
        or "\0" in value
        or "\r" in value
    ):
        raise ValueError(f"Analyst qualification {field} is invalid")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError(f"Analyst qualification {field} is invalid") from error
    return value


def _bounded_int(value: object, minimum: int, maximum: int, field: str) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not minimum <= value <= maximum
    ):
        raise ValueError(f"Analyst qualification {field} is invalid")
    return value


def _count(value: object, field: str) -> int:
    return _bounded_int(value, 0, 1_000_000, field)


def _flag(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"Analyst qualification {field} is invalid")
    return value


def _duration(started: float) -> int:
    return max(0, round((time.monotonic() - started) * 1_000))


__all__ = [
    "AnalystBoundQualificationCorpus",
    "AnalystCompiledChunk",
    "AnalystCompiledConcept",
    "AnalystCompiledGeneration",
    "AnalystCompiledPermission",
    "AnalystExpectedSelector",
    "AnalystExpectedView",
    "AnalystQualificationAcceptance",
    "AnalystQualificationCase",
    "AnalystQualificationCorpus",
    "AnalystQualificationGeneration",
    "AnalystQualificationInvocation",
    "AnalystQualificationObservation",
    "AnalystQualificationRenderedFile",
    "AnalystQualificationRenderedGeneration",
    "AnalystQualificationRenderedSource",
    "AnalystQualificationRequest",
    "AnalystQualificationResult",
    "AnalystQualificationRun",
    "AnalystQualificationSource",
    "AnalystQualificationWave",
    "bind_analyst_compiled_corpus",
    "build_analyst_qualification_invocations",
    "evaluate_analyst_qualification",
    "load_analyst_qualification_acceptance",
    "load_analyst_qualification_corpus",
    "render_analyst_qualification_generations",
]
