"""Public synthetic qualification for permission-safe Librarian evidence."""

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

from yap_server.private_artifact import read_json_object_with_identity


_MAXIMUM_ACCEPTANCE_BYTES = 32 * 1024
_MAXIMUM_FIXTURE_BYTES = 256 * 1024
_IDENTITY = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_CONCEPT_ID = re.compile(r"^[a-z0-9][a-z0-9./-]{0,511}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MODES = frozenset({"normal", "pre-cancelled", "deadline"})
_STATUSES = frozenset(
    {"complete", "evidence-unavailable", "failed", "cancelled"}
)
_REASONS = frozenset(
    {
        None,
        "empty-result",
        "stale-generation",
        "client-cancelled",
        "deadline-exceeded",
    }
)
_REQUIRED_CAPABILITY = "knowledge.search.lexical"
_PRIMARY_WAVE_TIMEOUT_SECONDS = 20.0
_WORKER_CONTAINMENT_SECONDS = 2.0


class LibrarianEvidenceItemView(Protocol):
    concept_id: str
    source_revision: str
    content_sha256: str
    char_start: int
    char_end: int
    text: str


class LibrarianJobView(Protocol):
    request_id: str
    status: str
    generation_sha256: str | None
    permission_hash: str | None
    authorization_hash: str | None
    evidence_sha256: str | None
    items: tuple[LibrarianEvidenceItemView, ...]
    output_budget_exhausted: bool
    reason: str | None


class LibrarianQualificationExecutor(Protocol):
    def __call__(
        self,
        invocation: LibrarianQualificationInvocation,
        cancellation: threading.Event,
    ) -> LibrarianJobView: ...


class LibrarianCompiledConcept(Protocol):
    concept_id: str
    source_path: str
    content_sha256: str
    body: str
    links: tuple[str, ...]
    permission_path_prefix: str


class LibrarianCompiledChunk(Protocol):
    concept_id: str
    permission_sha256: str
    char_start: int
    char_end: int
    text: str
    linked_concept_ids: tuple[str, ...]


class LibrarianCompiledPermission(Protocol):
    path_prefix: str
    audience: tuple[object, ...]
    denials: tuple[object, ...]
    purposes: tuple[str, ...]
    classification: str
    permission_sha256: str


class LibrarianCompiledGeneration(Protocol):
    tenant_id: str
    source_revision: str
    generation_sha256: str
    concepts: tuple[LibrarianCompiledConcept, ...]
    chunks: tuple[LibrarianCompiledChunk, ...]
    permissions: tuple[LibrarianCompiledPermission, ...]


@dataclass(frozen=True, slots=True)
class LibrarianQualificationAcceptance:
    plan_sha256: str
    case_count: int
    owner_count: int
    invocation_count: int
    maximum_p95_milliseconds: int
    synchronized_owner_wave_count: int
    complete_count: int
    unavailable_count: int
    failed_count: int
    cancelled_count: int
    nonempty_pack_count: int
    exact_evidence_match_count: int
    unique_request_id_count: int
    output_budget_exhausted_count: int
    terminal_mismatch_count: int
    synchronized_owner_wave_met: bool
    p95_within_bound: bool
    hidden_only_indistinguishable: bool
    hidden_link_suppressed: bool
    hidden_filtered_before_limit: bool
    stale_generation_failed_closed: bool
    successor_revocation_enforced: bool
    cancellation_failed_closed: bool
    deadline_failed_closed: bool

    def expected_public_evidence(self) -> dict[str, int | bool]:
        return {
            "schemaVersion": 1,
            "qualified": True,
            "caseCount": self.case_count,
            "ownerCount": self.owner_count,
            "invocationCount": self.invocation_count,
            "synchronizedOwnerWaveCount": (
                self.synchronized_owner_wave_count
            ),
            "completeCount": self.complete_count,
            "unavailableCount": self.unavailable_count,
            "failedCount": self.failed_count,
            "cancelledCount": self.cancelled_count,
            "nonemptyPackCount": self.nonempty_pack_count,
            "exactEvidenceMatchCount": self.exact_evidence_match_count,
            "uniqueRequestIdCount": self.unique_request_id_count,
            "outputBudgetExhaustedCount": (
                self.output_budget_exhausted_count
            ),
            "terminalMismatchCount": self.terminal_mismatch_count,
            "synchronizedOwnerWaveMet": self.synchronized_owner_wave_met,
            "p95WithinBound": self.p95_within_bound,
            "hiddenOnlyIndistinguishable": (
                self.hidden_only_indistinguishable
            ),
            "hiddenLinkSuppressed": self.hidden_link_suppressed,
            "hiddenFilteredBeforeLimit": self.hidden_filtered_before_limit,
            "staleGenerationFailedClosed": (
                self.stale_generation_failed_closed
            ),
            "successorRevocationEnforced": (
                self.successor_revocation_enforced
            ),
            "cancellationFailedClosed": self.cancellation_failed_closed,
            "deadlineFailedClosed": self.deadline_failed_closed,
        }


@dataclass(frozen=True, slots=True)
class LibrarianQualificationSource:
    concept_id: str
    source_revision: str
    body: str
    evidence_quote: str
    visible_to_owner_ids: frozenset[str]
    linked_concept_ids: tuple[str, ...]
    retrieval_rank: int

@dataclass(frozen=True, slots=True)
class LibrarianQualificationGeneration:
    generation_id: str
    generation_sha256: str
    sources: tuple[LibrarianQualificationSource, ...]


@dataclass(frozen=True, slots=True)
class LibrarianExpectedSelector:
    concept_id: str
    quote: str


@dataclass(frozen=True, slots=True)
class LibrarianQualificationRun:
    run_id: str
    mode: str
    expected_status: str
    expected_reason: str | None
    expected_evidence: tuple[LibrarianExpectedSelector, ...]


@dataclass(frozen=True, slots=True)
class LibrarianQualificationRequest:
    purpose: str
    search_text: str
    maximum_results: int
    expected_generation_id: str


@dataclass(frozen=True, slots=True)
class LibrarianQualificationCase:
    case_id: str
    owner_id: str
    active_generation_id: str
    request: LibrarianQualificationRequest
    runs: tuple[LibrarianQualificationRun, ...]


@dataclass(frozen=True, slots=True)
class LibrarianQualificationCorpus:
    corpus_id: str
    corpus_sha256: str
    tenant_id: str
    generations: tuple[LibrarianQualificationGeneration, ...]
    cases: tuple[LibrarianQualificationCase, ...]


@dataclass(frozen=True, slots=True)
class LibrarianQualificationRenderedFile:
    relative_path: str
    body: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class LibrarianQualificationRenderedSource:
    generation_id: str
    concept_id: str
    relative_path: str
    body: bytes = field(repr=False)
    source_revision: str
    content_sha256: str
    char_start: int
    char_end: int
    text: str


@dataclass(frozen=True, slots=True)
class LibrarianQualificationRenderedGeneration:
    generation_id: str
    tenant_id: str
    source_revision: str
    files: tuple[LibrarianQualificationRenderedFile, ...]
    sources: tuple[LibrarianQualificationRenderedSource, ...]


@dataclass(frozen=True, slots=True)
class LibrarianBoundQualificationCorpus:
    corpus: LibrarianQualificationCorpus
    tenant_id: str
    generation_sha256s: Mapping[str, str]
    expected_views: Mapping[str, LibrarianExpectedView]


@dataclass(frozen=True, slots=True)
class LibrarianExpectedEvidenceItem:
    concept_id: str
    source_revision: str
    content_sha256: str
    char_start: int
    char_end: int
    text: str

    def to_wire(self) -> dict[str, object]:
        return {
            "conceptId": self.concept_id,
            "sourceRevision": self.source_revision,
            "contentSha256": self.content_sha256,
            "charStart": self.char_start,
            "charEnd": self.char_end,
            "text": self.text,
        }


@dataclass(frozen=True, slots=True)
class LibrarianExpectedView:
    status: str
    generation_sha256: str | None
    permission_hash: str | None
    authorization_hash: str | None
    evidence_sha256: str | None
    items: tuple[LibrarianExpectedEvidenceItem, ...]
    output_budget_exhausted: bool
    reason: str | None

    def terminal_shape(self) -> tuple[object, ...]:
        return (
            self.status,
            self.generation_sha256,
            self.permission_hash,
            self.authorization_hash,
            self.evidence_sha256,
            self.items,
            self.output_budget_exhausted,
            self.reason,
        )


@dataclass(frozen=True, slots=True)
class LibrarianQualificationInvocation:
    invocation_id: str
    case_id: str
    run_id: str
    mode: str
    tenant_id: str
    owner_id: str
    purpose: str
    search_text: str
    maximum_results: int
    expected_generation_sha256: str


@dataclass(frozen=True, slots=True)
class LibrarianQualificationObservation:
    invocation: LibrarianQualificationInvocation = field(repr=False)
    expected: LibrarianExpectedView = field(repr=False)
    observed: LibrarianExpectedView | None = field(repr=False)
    request_id: str | None = field(repr=False)
    duration_milliseconds: int = field(repr=False)
    exact_match: bool
    failure_kind: str | None


@dataclass(frozen=True, slots=True)
class LibrarianQualificationResult:
    public_evidence: dict[str, int | bool]
    observations: tuple[LibrarianQualificationObservation, ...] = field(
        repr=False
    )


def load_librarian_qualification_acceptance(
    path: Path,
) -> LibrarianQualificationAcceptance:
    value, identity = read_json_object_with_identity(
        path,
        maximum_bytes=_MAXIMUM_ACCEPTANCE_BYTES,
        field="Librarian qualification acceptance",
    )
    expected_fields = {
        "schemaVersion",
        "qualificationScope",
        "qualified",
        "caseCount",
        "ownerCount",
        "invocationCount",
        "maximumP95Milliseconds",
        "synchronizedOwnerWaveCount",
        "completeCount",
        "unavailableCount",
        "failedCount",
        "cancelledCount",
        "nonemptyPackCount",
        "exactEvidenceMatchCount",
        "uniqueRequestIdCount",
        "outputBudgetExhaustedCount",
        "terminalMismatchCount",
        "synchronizedOwnerWaveMet",
        "p95WithinBound",
        "hiddenOnlyIndistinguishable",
        "hiddenLinkSuppressed",
        "hiddenFilteredBeforeLimit",
        "staleGenerationFailedClosed",
        "successorRevocationEnforced",
        "cancellationFailedClosed",
        "deadlineFailedClosed",
    }
    if set(value) != expected_fields:
        raise ValueError("Librarian qualification acceptance shape differs")
    if (
        type(value["schemaVersion"]) is not int
        or value["schemaVersion"] != 1
        or value["qualificationScope"]
        != "librarian-permission-safe-evidence"
        or value["qualified"] is not True
    ):
        raise ValueError("Librarian qualification acceptance identity differs")
    acceptance = LibrarianQualificationAcceptance(
        plan_sha256=identity,
        case_count=_count(value["caseCount"], "case count"),
        owner_count=_count(value["ownerCount"], "owner count"),
        invocation_count=_count(value["invocationCount"], "invocation count"),
        maximum_p95_milliseconds=_positive_int(
            value["maximumP95Milliseconds"], "p95 duration bound"
        ),
        synchronized_owner_wave_count=_positive_int(
            value["synchronizedOwnerWaveCount"], "synchronized owner wave"
        ),
        complete_count=_count(value["completeCount"], "complete count"),
        unavailable_count=_count(
            value["unavailableCount"], "unavailable count"
        ),
        failed_count=_count(value["failedCount"], "failed count"),
        cancelled_count=_count(
            value["cancelledCount"], "cancelled count"
        ),
        nonempty_pack_count=_count(
            value["nonemptyPackCount"], "nonempty pack count"
        ),
        exact_evidence_match_count=_count(
            value["exactEvidenceMatchCount"], "exact evidence match count"
        ),
        unique_request_id_count=_count(
            value["uniqueRequestIdCount"], "unique request identity count"
        ),
        output_budget_exhausted_count=_count(
            value["outputBudgetExhaustedCount"],
            "output budget exhaustion count",
        ),
        terminal_mismatch_count=_count(
            value["terminalMismatchCount"], "terminal mismatch count"
        ),
        synchronized_owner_wave_met=_flag(
            value["synchronizedOwnerWaveMet"], "synchronized owner wave"
        ),
        p95_within_bound=_flag(value["p95WithinBound"], "p95 duration"),
        hidden_only_indistinguishable=_flag(
            value["hiddenOnlyIndistinguishable"],
            "hidden-only indistinguishability",
        ),
        hidden_link_suppressed=_flag(
            value["hiddenLinkSuppressed"], "hidden-link suppression"
        ),
        hidden_filtered_before_limit=_flag(
            value["hiddenFilteredBeforeLimit"], "hidden-before-limit filtering"
        ),
        stale_generation_failed_closed=_flag(
            value["staleGenerationFailedClosed"], "stale generation"
        ),
        successor_revocation_enforced=_flag(
            value["successorRevocationEnforced"], "successor revocation"
        ),
        cancellation_failed_closed=_flag(
            value["cancellationFailedClosed"], "cancellation"
        ),
        deadline_failed_closed=_flag(
            value["deadlineFailedClosed"], "deadline"
        ),
    )
    if (
        acceptance.case_count != 8
        or acceptance.owner_count != acceptance.case_count
        or acceptance.invocation_count != 10
        or acceptance.maximum_p95_milliseconds != 16_000
        or acceptance.synchronized_owner_wave_count != 8
        or acceptance.complete_count
        + acceptance.unavailable_count
        + acceptance.failed_count
        + acceptance.cancelled_count
        != acceptance.invocation_count
        or acceptance.nonempty_pack_count != acceptance.complete_count
        or acceptance.exact_evidence_match_count
        != acceptance.invocation_count
        or acceptance.unique_request_id_count != acceptance.invocation_count
        or acceptance.output_budget_exhausted_count != 0
        or acceptance.terminal_mismatch_count != 0
        or not all(
            (
                acceptance.hidden_only_indistinguishable,
                acceptance.synchronized_owner_wave_met,
                acceptance.p95_within_bound,
                acceptance.hidden_link_suppressed,
                acceptance.hidden_filtered_before_limit,
                acceptance.stale_generation_failed_closed,
                acceptance.successor_revocation_enforced,
                acceptance.cancellation_failed_closed,
                acceptance.deadline_failed_closed,
            )
        )
    ):
        raise ValueError("Librarian qualification acceptance values conflict")
    return acceptance


def load_librarian_qualification_corpus(
    path: Path,
) -> LibrarianQualificationCorpus:
    value, identity = read_json_object_with_identity(
        path,
        maximum_bytes=_MAXIMUM_FIXTURE_BYTES,
        field="Librarian qualification fixtures",
    )
    if set(value) != {
        "schemaVersion",
        "qualificationScope",
        "corpusId",
        "tenantId",
        "generations",
        "cases",
    }:
        raise ValueError("Librarian qualification fixture shape differs")
    if (
        type(value["schemaVersion"]) is not int
        or value["schemaVersion"] != 1
        or value["qualificationScope"]
        != "librarian-permission-safe-evidence"
    ):
        raise ValueError("Librarian qualification fixture identity differs")
    corpus_id = _identity(value["corpusId"], "corpus identity")
    tenant_id = _identity(value["tenantId"], "tenant identity")
    raw_generations = value["generations"]
    raw_cases = value["cases"]
    if (
        not isinstance(raw_generations, list)
        or len(raw_generations) != 2
        or not isinstance(raw_cases, list)
        or len(raw_cases) != 8
    ):
        raise ValueError("Librarian qualification fixture cardinality differs")
    generations = tuple(_generation(item) for item in raw_generations)
    cases = tuple(_case(item) for item in raw_cases)
    if (
        len({item.generation_id for item in generations}) != len(generations)
        or len({item.generation_sha256 for item in generations})
        != len(generations)
        or len({item.case_id for item in cases}) != len(cases)
        or len({item.owner_id for item in cases}) != len(cases)
        or sum(len(item.runs) for item in cases) != 10
    ):
        raise ValueError("Librarian qualification fixture identities differ")
    known_generations = {item.generation_id for item in generations}
    if any(
        item.active_generation_id not in known_generations
        or item.request.expected_generation_id not in known_generations
        for item in cases
    ):
        raise ValueError("Librarian qualification generation reference differs")
    if (
        any(sum(run.mode == "normal" for run in case.runs) != 1 for case in cases)
        or tuple(
            (case.case_id, run.run_id, run.mode)
            for case in cases
            for run in case.runs
            if run.mode != "normal"
        )
        != (
            ("terminal-cutover", "client-cancelled", "pre-cancelled"),
            ("terminal-cutover", "deadline-exceeded", "deadline"),
        )
    ):
        raise ValueError("Librarian qualification wave contract differs")
    corpus = LibrarianQualificationCorpus(
        corpus_id,
        identity,
        tenant_id,
        generations,
        cases,
    )
    compile_librarian_expected_evidence(corpus)
    return corpus


def render_librarian_qualification_generations(
    corpus: LibrarianQualificationCorpus,
    *,
    tenant_id: str,
) -> tuple[LibrarianQualificationRenderedGeneration, ...]:
    """Render the exact OKF and permission bytes seeded by a live gate."""

    if not isinstance(corpus, LibrarianQualificationCorpus):
        raise TypeError("Librarian qualification corpus type is invalid")
    tenant = _identity(tenant_id, "runtime tenant identity")
    rendered: list[LibrarianQualificationRenderedGeneration] = []
    for generation in corpus.generations:
        source_revisions = {item.source_revision for item in generation.sources}
        if len(source_revisions) != 1:
            raise ValueError(
                "Librarian qualification generation source revisions differ"
            )
        source_revision = next(iter(source_revisions))
        files: list[LibrarianQualificationRenderedFile] = [
            LibrarianQualificationRenderedFile(
                "index.md",
                b"---\nokf_version: '0.1'\n---\n# Librarian public synthetic\n",
            )
        ]
        sources: list[LibrarianQualificationRenderedSource] = []
        for source in generation.sources:
            relative_path = f"{source.concept_id}.md"
            frontmatter = (
                "---\n"
                "type: Note\n"
                f"title: {source.concept_id}\n"
                f"resource: yap://tenant/{tenant}/{source.concept_id}/source\n"
                "timestamp: '2026-08-12T00:00:00Z'\n"
                "yap_schema: 1\n"
                "provenance:\n"
                "  source: librarian-public-synthetic\n"
                f"  source_revision: {source.source_revision}\n"
                "---\n"
            )
            markdown_body = _source_markdown(source)
            document = (frontmatter + markdown_body).encode("utf-8")
            body_start = markdown_body.index(source.evidence_quote)
            files.append(
                LibrarianQualificationRenderedFile(relative_path, document)
            )
            sources.append(
                LibrarianQualificationRenderedSource(
                    generation.generation_id,
                    source.concept_id,
                    relative_path,
                    document,
                    source.source_revision,
                    hashlib.sha256(document).hexdigest(),
                    body_start,
                    body_start + len(source.evidence_quote),
                    source.evidence_quote,
                )
            )
        for index, (owners, concept_ids) in enumerate(
            _permission_groups(generation),
            start=1,
        ):
            prefixes = tuple(f"{concept_id}/" for concept_id in concept_ids)
            if len(prefixes) != 1:
                raise ValueError(
                    "Librarian qualification permission path is not exact"
                )
            permission = _permission_document(
                tenant_id=tenant,
                path_prefix=prefixes[0],
                owners=owners,
            )
            files.append(
                LibrarianQualificationRenderedFile(
                    f"permissions/rule-{index:02d}.yml",
                    permission,
                )
            )
        rendered.append(
            LibrarianQualificationRenderedGeneration(
                generation.generation_id,
                tenant,
                source_revision,
                tuple(sorted(files, key=lambda item: item.relative_path)),
                tuple(sorted(sources, key=lambda item: item.concept_id)),
            )
        )
    return tuple(rendered)


def compile_librarian_expected_evidence(
    corpus: LibrarianQualificationCorpus,
    *,
    tenant_id: str | None = None,
    generation_sha256s: Mapping[str, str] | None = None,
) -> dict[str, LibrarianExpectedView]:
    """Compile exact packs from only the frozen public corpus and permissions."""

    if not isinstance(corpus, LibrarianQualificationCorpus):
        raise TypeError("Librarian qualification corpus type is invalid")
    runtime_tenant = (
        corpus.tenant_id
        if tenant_id is None
        else _identity(tenant_id, "runtime tenant identity")
    )
    rendered = {
        item.generation_id: item
        for item in render_librarian_qualification_generations(
            corpus, tenant_id=runtime_tenant
        )
    }
    generations = {item.generation_id: item for item in corpus.generations}
    runtime_generation_sha256s = (
        {item.generation_id: item.generation_sha256 for item in corpus.generations}
        if generation_sha256s is None
        else _runtime_generation_sha256s(corpus, generation_sha256s)
    )
    expected: dict[str, LibrarianExpectedView] = {}
    for case in corpus.cases:
        active = generations[case.active_generation_id]
        active_sha256 = runtime_generation_sha256s[case.active_generation_id]
        requested_sha256 = runtime_generation_sha256s[
            case.request.expected_generation_id
        ]
        visible = {
            source.concept_id
            for source in active.sources
            if case.owner_id in source.visible_to_owner_ids
        }
        selected = tuple(
            sorted(
                (
                    source
                    for source in active.sources
                    if case.request.search_text.casefold()
                    in source.body.casefold()
                    and source.concept_id in visible
                    and set(source.linked_concept_ids) <= visible
                ),
                key=lambda item: (item.retrieval_rank, item.concept_id),
            )[: case.request.maximum_results]
        )
        for run in case.runs:
            invocation_id = f"{case.case_id}:{run.run_id}"
            if invocation_id in expected:
                raise ValueError("Librarian qualification invocation is duplicated")
            stale = requested_sha256 != active_sha256
            expected_sources = (
                selected if run.mode == "normal" and not stale else ()
            )
            declared = tuple(
                (item.concept_id, item.quote) for item in run.expected_evidence
            )
            compiled = tuple(
                (item.concept_id, item.evidence_quote)
                for item in expected_sources
            )
            if declared != compiled:
                raise ValueError(
                    "Librarian qualification frozen evidence map differs"
                )
            derived_status, derived_reason = _derived_terminal(
                run.mode,
                stale=stale,
                has_evidence=bool(expected_sources),
            )
            if (
                run.expected_status != derived_status
                or run.expected_reason != derived_reason
            ):
                raise ValueError(
                    "Librarian qualification terminal expectation differs"
                )
            rendered_sources = {
                item.concept_id: item
                for item in rendered[case.active_generation_id].sources
            }
            items = tuple(
                _expected_item(source, rendered_sources[source.concept_id])
                for source in expected_sources
            )
            if derived_status == "complete":
                permission_hash, authorization_hash = _authorization_identity(
                    tenant_id=runtime_tenant,
                    owner_id=case.owner_id,
                    purpose=case.request.purpose,
                    generation=active,
                    generation_sha256=active_sha256,
                    visible_concept_ids=visible,
                )
                evidence_sha256 = _evidence_sha256(
                    generation_sha256=active_sha256,
                    permission_hash=permission_hash,
                    authorization_hash=authorization_hash,
                    items=items,
                    output_budget_exhausted=False,
                )
                expected[invocation_id] = LibrarianExpectedView(
                    derived_status,
                    active_sha256,
                    permission_hash,
                    authorization_hash,
                    evidence_sha256,
                    items,
                    False,
                    derived_reason,
                )
            else:
                expected[invocation_id] = LibrarianExpectedView(
                    derived_status,
                    None,
                    None,
                    None,
                    None,
                    (),
                    False,
                    derived_reason,
                )
    return expected


def bind_librarian_compiled_corpus(
    corpus: LibrarianQualificationCorpus,
    rendered: tuple[LibrarianQualificationRenderedGeneration, ...],
    compiled_generations: Mapping[str, LibrarianCompiledGeneration],
) -> LibrarianBoundQualificationCorpus:
    """Verify production compilation against renderer-owned bytes and bind it."""

    if not isinstance(corpus, LibrarianQualificationCorpus):
        raise TypeError("Librarian qualification corpus type is invalid")
    generation_ids = {item.generation_id for item in corpus.generations}
    if (
        not isinstance(rendered, tuple)
        or {item.generation_id for item in rendered} != generation_ids
        or not isinstance(compiled_generations, Mapping)
        or set(compiled_generations) != generation_ids
    ):
        raise ValueError("Librarian compiled corpus generations differ")
    tenant_ids = {item.tenant_id for item in rendered}
    if len(rendered) != len(generation_ids) or len(tenant_ids) != 1:
        raise ValueError("Librarian compiled corpus tenant differs")
    tenant_id = next(iter(tenant_ids))
    canonical_rendered = render_librarian_qualification_generations(
        corpus,
        tenant_id=tenant_id,
    )
    if rendered != canonical_rendered:
        raise ValueError("Librarian rendered corpus differs")
    rendered_by_id = {item.generation_id: item for item in rendered}
    fixture_by_id = {item.generation_id: item for item in corpus.generations}
    bound_sources: dict[
        str, dict[str, LibrarianExpectedEvidenceItem]
    ] = {}
    permission_identities: dict[
        str, tuple[tuple[str, str, tuple[str, ...]], ...]
    ] = {}
    generation_sha256s: dict[str, str] = {}
    for generation_id in sorted(generation_ids):
        fixture = fixture_by_id[generation_id]
        rendered_generation = rendered_by_id[generation_id]
        compiled = compiled_generations[generation_id]
        if (
            getattr(compiled, "tenant_id", None) != tenant_id
            or not isinstance(getattr(compiled, "source_revision", None), str)
            or not isinstance(getattr(compiled, "generation_sha256", None), str)
        ):
            raise ValueError("Librarian compiled generation identity differs")
        generation_sha256s[generation_id] = _sha(
            compiled.generation_sha256, "compiled generation digest"
        )
        if compiled.source_revision != rendered_generation.source_revision:
            raise ValueError("Librarian compiled source revision differs")
        expected_paths = {
            item.relative_path: item for item in rendered_generation.sources
        }
        concepts = tuple(compiled.concepts)
        chunks = tuple(compiled.chunks)
        permissions = tuple(compiled.permissions)
        if (
            {item.source_path for item in concepts} != set(expected_paths)
            or len(concepts) != len(expected_paths)
            or {item.concept_id for item in chunks}
            != {item.concept_id for item in concepts}
            or len(chunks) != len(concepts)
        ):
            raise ValueError("Librarian compiled concept set differs")
        by_concept: dict[str, LibrarianExpectedEvidenceItem] = {}
        for concept in concepts:
            expected_source = expected_paths[concept.source_path]
            expected_fixture = next(
                item
                for item in fixture.sources
                if item.concept_id == expected_source.concept_id
            )
            if (
                concept.concept_id != expected_source.concept_id
                or concept.body != _source_markdown(expected_fixture)
                or concept.content_sha256
                != hashlib.sha256(expected_source.body).hexdigest()
                or tuple(concept.links)
                != tuple(sorted(expected_fixture.linked_concept_ids))
            ):
                raise ValueError("Librarian compiled concept projection differs")
            matches = tuple(
                chunk
                for chunk in chunks
                if chunk.concept_id == concept.concept_id
            )
            if len(matches) != 1:
                raise ValueError("Librarian compiled evidence chunk differs")
            chunk = matches[0]
            expected_chunk_text = _source_markdown(expected_fixture).rstrip("\n")
            quote_offset = chunk.text.find(expected_source.text)
            if (
                chunk.text != expected_chunk_text
                or chunk.char_start != 0
                or chunk.char_end != len(expected_chunk_text)
                or quote_offset < 0
                or chunk.text.count(expected_source.text) != 1
                or tuple(chunk.linked_concept_ids)
                != tuple(sorted(expected_fixture.linked_concept_ids))
            ):
                raise ValueError("Librarian compiled evidence span differs")
            by_concept[concept.concept_id] = LibrarianExpectedEvidenceItem(
                concept.concept_id,
                compiled.source_revision,
                concept.content_sha256,
                chunk.char_start + quote_offset,
                chunk.char_start + quote_offset + len(expected_source.text),
                expected_source.text,
            )
        bound_sources[generation_id] = by_concept
        permission_identities[generation_id] = _compiled_permission_identities(
            fixture,
            tenant_id=tenant_id,
            permissions=permissions,
        )
        by_prefix = {item.path_prefix: item for item in permissions}
        for concept in concepts:
            permission = by_prefix.get(concept.permission_path_prefix)
            chunk_permissions = {
                item.permission_sha256
                for item in chunks
                if item.concept_id == concept.concept_id
            }
            if (
                permission is None
                or chunk_permissions != {permission.permission_sha256}
            ):
                raise ValueError("Librarian compiled permission binding differs")
    if len(set(generation_sha256s.values())) != len(generation_sha256s):
        raise ValueError("Librarian compiled generation identities conflict")
    expected = _compile_bound_expected_evidence(
        corpus,
        tenant_id=tenant_id,
        generation_sha256s=generation_sha256s,
        bound_sources=bound_sources,
        permission_identities=permission_identities,
    )
    return LibrarianBoundQualificationCorpus(
        corpus,
        tenant_id,
        MappingProxyType(dict(generation_sha256s)),
        MappingProxyType(dict(expected)),
    )


def build_librarian_qualification_invocations(
    corpus: LibrarianQualificationCorpus,
    *,
    tenant_id: str | None = None,
    generation_sha256s: Mapping[str, str] | None = None,
) -> tuple[LibrarianQualificationInvocation, ...]:
    if not isinstance(corpus, LibrarianQualificationCorpus):
        raise TypeError("Librarian qualification corpus type is invalid")
    runtime_tenant = (
        corpus.tenant_id
        if tenant_id is None
        else _identity(tenant_id, "runtime tenant identity")
    )
    runtime_generation_sha256s = (
        {item.generation_id: item.generation_sha256 for item in corpus.generations}
        if generation_sha256s is None
        else _runtime_generation_sha256s(corpus, generation_sha256s)
    )
    return tuple(
        LibrarianQualificationInvocation(
            invocation_id=f"{case.case_id}:{run.run_id}",
            case_id=case.case_id,
            run_id=run.run_id,
            mode=run.mode,
            tenant_id=runtime_tenant,
            owner_id=case.owner_id,
            purpose=case.request.purpose,
            search_text=case.request.search_text,
            maximum_results=case.request.maximum_results,
            expected_generation_sha256=runtime_generation_sha256s[
                case.request.expected_generation_id
            ],
        )
        for case in corpus.cases
        for run in case.runs
    )


def evaluate_librarian_qualification(
    *,
    executor: LibrarianQualificationExecutor,
    corpus: LibrarianBoundQualificationCorpus,
    acceptance: LibrarianQualificationAcceptance,
) -> LibrarianQualificationResult:
    if not callable(executor):
        raise TypeError("Librarian qualification executor is invalid")
    if not isinstance(acceptance, LibrarianQualificationAcceptance):
        raise TypeError("Librarian qualification acceptance type is invalid")
    if not isinstance(corpus, LibrarianBoundQualificationCorpus):
        raise TypeError("Librarian qualification corpus is not compiler-bound")
    corpus_value = corpus.corpus
    expected = corpus.expected_views
    invocations = build_librarian_qualification_invocations(
        corpus_value,
        tenant_id=corpus.tenant_id,
        generation_sha256s=corpus.generation_sha256s,
    )
    primary = tuple(item for item in invocations if item.mode == "normal")
    controlled = tuple(item for item in invocations if item.mode != "normal")
    if (
        len(primary) != 8
        or len({item.owner_id for item in primary}) != 8
        or tuple((item.run_id, item.mode) for item in controlled)
        != (
            ("client-cancelled", "pre-cancelled"),
            ("deadline-exceeded", "deadline"),
        )
    ):
        raise ValueError("Librarian qualification synchronized wave differs")
    barrier = threading.Barrier(len(primary))
    cancellations = {
        item.invocation_id: threading.Event() for item in primary
    }
    pool: ThreadPoolExecutor | None = ThreadPoolExecutor(
        max_workers=len(primary),
        thread_name_prefix="librarian-qualification",
    )
    try:
        futures: list[Future[LibrarianQualificationObservation]] = [
            pool.submit(
                _run_invocation,
                executor,
                invocation,
                expected[invocation.invocation_id],
                cancellations[invocation.invocation_id],
                barrier,
            )
            for invocation in primary
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
                    "Librarian qualification cancellation was not contained"
                )
            raise TimeoutError("Librarian qualification wave exceeded its timeout")
        primary_observations = [future.result() for future in futures]
    finally:
        if pool is not None:
            pool.shutdown(wait=True, cancel_futures=True)
    observations = list(primary_observations)
    for invocation in controlled:
        controlled_cancellation = threading.Event()
        if invocation.mode == "pre-cancelled":
            controlled_cancellation.set()
        observations.append(
            _run_invocation(
                executor,
                invocation,
                expected[invocation.invocation_id],
                controlled_cancellation,
                None,
            )
        )

    by_id = {item.invocation.invocation_id: item for item in observations}
    valid_views = [item.observed for item in observations if item.observed is not None]
    request_ids = [
        item.request_id for item in observations if item.request_id is not None
    ]
    durations = sorted(item.duration_milliseconds for item in observations)
    p95_index = max(0, math.ceil(len(durations) * 0.95) - 1)
    hidden = by_id["hidden-only-unavailable:normal"]
    absent = by_id["absent-unavailable:normal"]
    hidden_indistinguishable = (
        hidden.exact_match
        and absent.exact_match
        and hidden.observed is not None
        and absent.observed is not None
        and hidden.observed.terminal_shape()
        == absent.observed.terminal_shape()
    )
    synchronized_owner_ids = {
        item.invocation.owner_id
        for item in primary_observations
        if item.exact_match
    }
    synchronized_owner_wave_count = len(synchronized_owner_ids)
    public: dict[str, int | bool] = {
        "schemaVersion": 1,
        "qualified": False,
        "caseCount": len(corpus_value.cases),
        "ownerCount": len({item.owner_id for item in corpus_value.cases}),
        "invocationCount": len(observations),
        "synchronizedOwnerWaveCount": synchronized_owner_wave_count,
        "completeCount": sum(
            item is not None and item.status == "complete" for item in valid_views
        ),
        "unavailableCount": sum(
            item is not None and item.status == "evidence-unavailable"
            for item in valid_views
        ),
        "failedCount": sum(
            item is not None and item.status == "failed" for item in valid_views
        ),
        "cancelledCount": sum(
            item is not None and item.status == "cancelled" for item in valid_views
        ),
        "nonemptyPackCount": sum(
            item is not None and bool(item.items) for item in valid_views
        ),
        "exactEvidenceMatchCount": sum(
            item.exact_match for item in observations
        ),
        "uniqueRequestIdCount": len(set(request_ids)),
        "outputBudgetExhaustedCount": sum(
            item is not None and item.output_budget_exhausted
            for item in valid_views
        ),
        "terminalMismatchCount": sum(
            not item.exact_match for item in observations
        ),
        "synchronizedOwnerWaveMet": synchronized_owner_wave_count
        == acceptance.synchronized_owner_wave_count,
        "p95WithinBound": durations[p95_index]
        <= acceptance.maximum_p95_milliseconds,
        "hiddenOnlyIndistinguishable": hidden_indistinguishable,
        "hiddenLinkSuppressed": by_id[
            "hidden-link-suppression:normal"
        ].exact_match,
        "hiddenFilteredBeforeLimit": by_id[
            "hidden-filter-before-limit:normal"
        ].exact_match,
        "staleGenerationFailedClosed": by_id[
            "expected-generation-stale:normal"
        ].exact_match,
        "successorRevocationEnforced": by_id[
            "successor-revocation:normal"
        ].exact_match,
        "cancellationFailedClosed": by_id[
            "terminal-cutover:client-cancelled"
        ].exact_match,
        "deadlineFailedClosed": by_id[
            "terminal-cutover:deadline-exceeded"
        ].exact_match,
    }
    required = acceptance.expected_public_evidence()
    public["qualified"] = all(
        public[key] == value for key, value in required.items() if key != "qualified"
    )
    return LibrarianQualificationResult(public, tuple(observations))


def _generation(value: object) -> LibrarianQualificationGeneration:
    if not isinstance(value, dict) or set(value) != {
        "generationId",
        "generationSha256",
        "sources",
    }:
        raise ValueError("Librarian qualification generation shape differs")
    generation_id = _identity(value["generationId"], "generation identity")
    generation_sha256 = _sha(value["generationSha256"], "generation digest")
    raw_sources = value["sources"]
    if not isinstance(raw_sources, list) or not 1 <= len(raw_sources) <= 64:
        raise ValueError("Librarian qualification generation sources differ")
    sources = tuple(_source(item) for item in raw_sources)
    concept_ids = {item.concept_id for item in sources}
    if len(concept_ids) != len(sources) or any(
        not set(item.linked_concept_ids) <= concept_ids for item in sources
    ):
        raise ValueError("Librarian qualification source identity differs")
    return LibrarianQualificationGeneration(
        generation_id, generation_sha256, sources
    )


def _source(value: object) -> LibrarianQualificationSource:
    if not isinstance(value, dict) or set(value) != {
        "conceptId",
        "sourceRevision",
        "body",
        "evidenceQuote",
        "visibleToOwnerIds",
        "linkedConceptIds",
        "retrievalRank",
    }:
        raise ValueError("Librarian qualification source shape differs")
    concept_id = _concept(value["conceptId"], "source concept")
    source_revision = _text(value["sourceRevision"], "source revision", 512)
    body = _text(value["body"], "source body", 4_096)
    evidence_quote = _text(value["evidenceQuote"], "evidence quote", 2_000)
    owners = value["visibleToOwnerIds"]
    links = value["linkedConceptIds"]
    if (
        not isinstance(owners, list)
        or not owners
        or len(owners) != len(set(owners))
        or not isinstance(links, list)
        or len(links) != len(set(links))
    ):
        raise ValueError("Librarian qualification source permission differs")
    visible = frozenset(_identity(item, "visible owner") for item in owners)
    linked = tuple(_concept(item, "linked concept") for item in links)
    rank = _positive_int(value["retrievalRank"], "retrieval rank")
    if body.count(evidence_quote) != 1:
        raise ValueError("Librarian qualification evidence quote differs")
    return LibrarianQualificationSource(
        concept_id,
        source_revision,
        body,
        evidence_quote,
        visible,
        linked,
        rank,
    )


def _case(value: object) -> LibrarianQualificationCase:
    if not isinstance(value, dict) or set(value) != {
        "caseId",
        "ownerId",
        "activeGenerationId",
        "request",
        "runs",
    }:
        raise ValueError("Librarian qualification case shape differs")
    raw_request = value["request"]
    raw_runs = value["runs"]
    if not isinstance(raw_request, dict) or set(raw_request) != {
        "purpose",
        "searchText",
        "maximumResults",
        "expectedGenerationId",
    }:
        raise ValueError("Librarian qualification request shape differs")
    purpose = raw_request["purpose"]
    search_text = _text(raw_request["searchText"], "search text", 1_024)
    if purpose != "knowledge.read" or not any(
        character.isalnum() for character in search_text
    ):
        raise ValueError("Librarian qualification request authority differs")
    request = LibrarianQualificationRequest(
        purpose,
        search_text,
        _bounded_int(raw_request["maximumResults"], 1, 5, "result limit"),
        _identity(
            raw_request["expectedGenerationId"],
            "expected generation identity",
        ),
    )
    if not isinstance(raw_runs, list) or not 1 <= len(raw_runs) <= 3:
        raise ValueError("Librarian qualification run count differs")
    runs = tuple(_run(item) for item in raw_runs)
    if len({item.run_id for item in runs}) != len(runs):
        raise ValueError("Librarian qualification run identity differs")
    return LibrarianQualificationCase(
        _identity(value["caseId"], "case identity"),
        _identity(value["ownerId"], "owner identity"),
        _identity(value["activeGenerationId"], "active generation identity"),
        request,
        runs,
    )


def _run(value: object) -> LibrarianQualificationRun:
    if not isinstance(value, dict) or set(value) != {
        "runId",
        "mode",
        "expectedStatus",
        "expectedReason",
        "expectedEvidence",
    }:
        raise ValueError("Librarian qualification run shape differs")
    mode = value["mode"]
    status = value["expectedStatus"]
    reason = value["expectedReason"]
    raw_evidence = value["expectedEvidence"]
    if (
        mode not in _MODES
        or status not in _STATUSES
        or reason not in _REASONS
        or not isinstance(raw_evidence, list)
        or len(raw_evidence) > 5
    ):
        raise ValueError("Librarian qualification run contract differs")
    selectors = tuple(_selector(item) for item in raw_evidence)
    if len({item.concept_id for item in selectors}) != len(selectors):
        raise ValueError("Librarian qualification evidence selector differs")
    return LibrarianQualificationRun(
        _identity(value["runId"], "run identity"),
        mode,
        status,
        reason,
        selectors,
    )


def _selector(value: object) -> LibrarianExpectedSelector:
    if not isinstance(value, dict) or set(value) != {"conceptId", "quote"}:
        raise ValueError("Librarian qualification evidence selector shape differs")
    return LibrarianExpectedSelector(
        _concept(value["conceptId"], "expected evidence concept"),
        _text(value["quote"], "expected evidence quote", 2_000),
    )


def _derived_terminal(
    mode: str,
    *,
    stale: bool,
    has_evidence: bool,
) -> tuple[str, str | None]:
    if mode == "pre-cancelled":
        return "cancelled", "client-cancelled"
    if mode == "deadline":
        return "cancelled", "deadline-exceeded"
    if stale:
        return "failed", "stale-generation"
    if not has_evidence:
        return "evidence-unavailable", "empty-result"
    return "complete", None


def _run_invocation(
    executor: LibrarianQualificationExecutor,
    invocation: LibrarianQualificationInvocation,
    expected: LibrarianExpectedView,
    cancellation: threading.Event,
    barrier: threading.Barrier | None,
) -> LibrarianQualificationObservation:
    if barrier is not None:
        try:
            barrier.wait(timeout=_PRIMARY_WAVE_TIMEOUT_SECONDS)
        except threading.BrokenBarrierError as error:
            raise RuntimeError(
                "Librarian qualification synchronization failed"
            ) from error
    started = time.monotonic()
    try:
        view = executor(invocation, cancellation)
        request_id, observed = _observed_view(view)
        exact = observed == expected
        return LibrarianQualificationObservation(
            invocation,
            expected,
            observed,
            request_id,
            _duration(started),
            exact,
            None if exact else "view-mismatch",
        )
    except Exception:
        return LibrarianQualificationObservation(
            invocation,
            expected,
            None,
            None,
            _duration(started),
            False,
            "executor-error",
        )


def _runtime_generation_sha256s(
    corpus: LibrarianQualificationCorpus,
    value: Mapping[str, str],
) -> dict[str, str]:
    expected = {item.generation_id for item in corpus.generations}
    if not isinstance(value, Mapping) or set(value) != expected:
        raise ValueError("Librarian qualification runtime generations differ")
    output = {
        generation_id: _sha(digest, "runtime generation digest")
        for generation_id, digest in value.items()
    }
    if len(set(output.values())) != len(output):
        raise ValueError("Librarian qualification runtime generations conflict")
    return output


def _source_markdown(source: LibrarianQualificationSource) -> str:
    body = source.body
    if source.linked_concept_ids:
        links = " ".join(
            f"[linked source](/{concept_id}.md)"
            for concept_id in source.linked_concept_ids
        )
        body = f"{body} {links}"
    return body + "\n"


def _permission_groups(
    generation: LibrarianQualificationGeneration,
) -> tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]:
    groups: dict[tuple[str, ...], list[str]] = {}
    for source in generation.sources:
        owners = tuple(sorted(source.visible_to_owner_ids))
        groups.setdefault(owners, []).append(source.concept_id)
    # One exact path rule per concept. The tuple key remains useful to prove
    # identical visibility sets render identical principal lists.
    return tuple(
        (owners, (concept_id,))
        for owners, concept_ids in sorted(groups.items())
        for concept_id in sorted(concept_ids)
    )


def _permission_document(
    *,
    tenant_id: str,
    path_prefix: str,
    owners: tuple[str, ...],
) -> bytes:
    lines = [f"path_prefix: {path_prefix}", "audience:", "  users:"]
    for owner in owners:
        lines.extend(
            (
                f"    - tenant_id: {tenant_id}",
                f"      subject_id: {owner}",
            )
        )
    lines.extend(
        (
            "purposes: [knowledge.read]",
            "classification: internal",
            "denials: {users: []}",
            "",
        )
    )
    return "\n".join(lines).encode("utf-8")


def _expected_permission_sha256(
    *,
    tenant_id: str,
    path_prefix: str,
    owners: tuple[str, ...],
) -> str:
    return _sha256_json(
        {
            "pathPrefix": path_prefix,
            "audience": [
                {"tenantId": tenant_id, "subjectId": owner}
                for owner in owners
            ],
            "denials": [],
            "purposes": ["knowledge.read"],
            "classification": "internal",
        }
    )


def _compiled_permission_identities(
    fixture: LibrarianQualificationGeneration,
    *,
    tenant_id: str,
    permissions: tuple[LibrarianCompiledPermission, ...],
) -> tuple[tuple[str, str, tuple[str, ...]], ...]:
    expected = {
        f"{source.concept_id}/": tuple(sorted(source.visible_to_owner_ids))
        for source in fixture.sources
    }
    observed: list[tuple[str, str, tuple[str, ...]]] = []
    for permission in permissions:
        path_prefix = _text(
            getattr(permission, "path_prefix", None),
            "compiled permission path",
            512,
        )
        digest = _sha(
            getattr(permission, "permission_sha256", None),
            "compiled permission digest",
        )
        if (
            path_prefix not in expected
            or tuple(getattr(permission, "purposes", ())) != ("knowledge.read",)
            or tuple(getattr(permission, "denials", ()))
            or getattr(permission, "classification", None) != "internal"
        ):
            raise ValueError("Librarian compiled permission authority differs")
        audience = tuple(getattr(permission, "audience", ()))
        owners: list[str] = []
        for principal in audience:
            if getattr(principal, "tenant_id", None) != tenant_id:
                raise ValueError("Librarian compiled permission crosses tenants")
            owners.append(
                _identity(
                    getattr(principal, "subject_id", None),
                    "compiled permission owner",
                )
            )
        owner_ids = tuple(sorted(owners))
        if owner_ids != expected[path_prefix]:
            raise ValueError("Librarian compiled permission visibility differs")
        if digest != _expected_permission_sha256(
            tenant_id=tenant_id,
            path_prefix=path_prefix,
            owners=owner_ids,
        ):
            raise ValueError("Librarian compiled permission digest differs")
        observed.append((path_prefix, digest, owner_ids))
    if (
        len(observed) != len(expected)
        or len({item[0] for item in observed}) != len(observed)
        or {item[0] for item in observed} != set(expected)
    ):
        raise ValueError("Librarian compiled permission set differs")
    return tuple(sorted(observed))


def _compile_bound_expected_evidence(
    corpus: LibrarianQualificationCorpus,
    *,
    tenant_id: str,
    generation_sha256s: dict[str, str],
    bound_sources: dict[str, dict[str, LibrarianExpectedEvidenceItem]],
    permission_identities: dict[
        str, tuple[tuple[str, str, tuple[str, ...]], ...]
    ],
) -> dict[str, LibrarianExpectedView]:
    generations = {item.generation_id: item for item in corpus.generations}
    expected: dict[str, LibrarianExpectedView] = {}
    for case in corpus.cases:
        active = generations[case.active_generation_id]
        active_sha256 = generation_sha256s[case.active_generation_id]
        requested_sha256 = generation_sha256s[
            case.request.expected_generation_id
        ]
        visible = {
            source.concept_id
            for source in active.sources
            if case.owner_id in source.visible_to_owner_ids
        }
        selected = tuple(
            sorted(
                (
                    source
                    for source in active.sources
                    if case.request.search_text.casefold()
                    in source.body.casefold()
                    and source.concept_id in visible
                    and set(source.linked_concept_ids) <= visible
                ),
                key=lambda item: (item.retrieval_rank, item.concept_id),
            )[: case.request.maximum_results]
        )
        permission_by_prefix = {
            path_prefix: permission_sha256
            for path_prefix, permission_sha256, _owners in permission_identities[
                case.active_generation_id
            ]
        }
        for run in case.runs:
            invocation_id = f"{case.case_id}:{run.run_id}"
            stale = requested_sha256 != active_sha256
            expected_sources = selected if run.mode == "normal" and not stale else ()
            declared = tuple(
                (item.concept_id, item.quote) for item in run.expected_evidence
            )
            compiled = tuple(
                (item.concept_id, item.evidence_quote)
                for item in expected_sources
            )
            if declared != compiled:
                raise ValueError(
                    "Librarian qualification frozen evidence map differs"
                )
            status, reason = _derived_terminal(
                run.mode,
                stale=stale,
                has_evidence=bool(expected_sources),
            )
            if run.expected_status != status or run.expected_reason != reason:
                raise ValueError(
                    "Librarian qualification terminal expectation differs"
                )
            if status != "complete":
                expected[invocation_id] = LibrarianExpectedView(
                    status, None, None, None, None, (), False, reason
                )
                continue
            items = tuple(
                bound_sources[case.active_generation_id][source.concept_id]
                for source in expected_sources
            )
            permission_hash = _sha256_json(
                {
                    "tenantId": tenant_id,
                    "subjectId": case.owner_id,
                    "purpose": case.request.purpose,
                    "generationSha256": active_sha256,
                    "permissionSha256s": sorted(
                        {
                            permission_by_prefix[f"{concept_id}/"]
                            for concept_id in visible
                        }
                    ),
                    "visibleConceptIds": sorted(visible),
                }
            )
            authorization_hash = _sha256_json(
                {
                    "permissionHash": permission_hash,
                    "requiredCapability": _REQUIRED_CAPABILITY,
                }
            )
            evidence_sha256 = _evidence_sha256(
                generation_sha256=active_sha256,
                permission_hash=permission_hash,
                authorization_hash=authorization_hash,
                items=items,
                output_budget_exhausted=False,
            )
            expected[invocation_id] = LibrarianExpectedView(
                status,
                active_sha256,
                permission_hash,
                authorization_hash,
                evidence_sha256,
                items,
                False,
                reason,
            )
    return expected


def _expected_item(
    source: LibrarianQualificationSource,
    rendered: LibrarianQualificationRenderedSource,
) -> LibrarianExpectedEvidenceItem:
    if (
        rendered.concept_id != source.concept_id
        or rendered.source_revision != source.source_revision
        or rendered.text != source.evidence_quote
    ):
        raise ValueError("Librarian qualification rendered source differs")
    return LibrarianExpectedEvidenceItem(
        source.concept_id,
        rendered.source_revision,
        rendered.content_sha256,
        rendered.char_start,
        rendered.char_end,
        rendered.text,
    )


def _authorization_identity(
    *,
    tenant_id: str,
    owner_id: str,
    purpose: str,
    generation: LibrarianQualificationGeneration,
    generation_sha256: str,
    visible_concept_ids: set[str],
) -> tuple[str, str]:
    permission_sha256s = sorted(
        {
            _expected_permission_sha256(
                tenant_id=tenant_id,
                path_prefix=f"{item.concept_id}/",
                owners=tuple(sorted(item.visible_to_owner_ids)),
            )
            for item in generation.sources
            if item.concept_id in visible_concept_ids
        }
    )
    permission_hash = _sha256_json(
        {
            "tenantId": tenant_id,
            "subjectId": owner_id,
            "purpose": purpose,
            "generationSha256": generation_sha256,
            "permissionSha256s": permission_sha256s,
            "visibleConceptIds": sorted(visible_concept_ids),
        }
    )
    authorization_hash = _sha256_json(
        {
            "permissionHash": permission_hash,
            "requiredCapability": _REQUIRED_CAPABILITY,
        }
    )
    return permission_hash, authorization_hash


def _evidence_sha256(
    *,
    generation_sha256: str,
    permission_hash: str,
    authorization_hash: str,
    items: tuple[LibrarianExpectedEvidenceItem, ...],
    output_budget_exhausted: bool,
) -> str:
    return _sha256_json(
        {
            "authorizationHash": authorization_hash,
            "generationSha256": generation_sha256,
            "items": [item.to_wire() for item in items],
            "operation": "search",
            "outputBudgetExhausted": output_budget_exhausted,
            "permissionHash": permission_hash,
        }
    )


def _observed_view(view: object) -> tuple[str, LibrarianExpectedView]:
    request_id = _text(getattr(view, "request_id", None), "request identity", 128)
    status = getattr(view, "status", None)
    reason = getattr(view, "reason", None)
    generation_sha256 = _optional_sha(
        getattr(view, "generation_sha256", None), "generation digest"
    )
    permission_hash = _optional_sha(
        getattr(view, "permission_hash", None), "permission digest"
    )
    authorization_hash = _optional_sha(
        getattr(view, "authorization_hash", None), "authorization digest"
    )
    evidence_sha256 = _optional_sha(
        getattr(view, "evidence_sha256", None), "evidence digest"
    )
    raw_items = getattr(view, "items", None)
    exhausted = getattr(view, "output_budget_exhausted", None)
    if (
        status not in _STATUSES
        or reason not in _REASONS
        or not isinstance(raw_items, tuple)
        or len(raw_items) > 5
        or not isinstance(exhausted, bool)
    ):
        raise ValueError("Librarian qualification view differs")
    items = tuple(_observed_item(item) for item in raw_items)
    return request_id, LibrarianExpectedView(
        status,
        generation_sha256,
        permission_hash,
        authorization_hash,
        evidence_sha256,
        items,
        exhausted,
        reason,
    )


def _observed_item(value: object) -> LibrarianExpectedEvidenceItem:
    concept_id = _concept(getattr(value, "concept_id", None), "observed concept")
    source_revision = _text(
        getattr(value, "source_revision", None), "observed revision", 512
    )
    content_sha256 = _sha(
        getattr(value, "content_sha256", None), "observed content digest"
    )
    char_start = _bounded_int(
        getattr(value, "char_start", None), 0, 2**63 - 1, "observed start"
    )
    char_end = _bounded_int(
        getattr(value, "char_end", None), 1, 2**63 - 1, "observed end"
    )
    text = _text(getattr(value, "text", None), "observed text", 2_000)
    if char_end <= char_start or char_end - char_start != len(text):
        raise ValueError("Librarian qualification observed span differs")
    return LibrarianExpectedEvidenceItem(
        concept_id,
        source_revision,
        content_sha256,
        char_start,
        char_end,
        text,
    )


def _identity(value: object, field: str) -> str:
    if not isinstance(value, str) or _IDENTITY.fullmatch(value) is None:
        raise ValueError(f"Librarian qualification {field} is invalid")
    return value


def _concept(value: object, field: str) -> str:
    if not isinstance(value, str) or _CONCEPT_ID.fullmatch(value) is None:
        raise ValueError(f"Librarian qualification {field} is invalid")
    return value


def _sha(value: object, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"Librarian qualification {field} is invalid")
    return value


def _optional_sha(value: object, field: str) -> str | None:
    return None if value is None else _sha(value, field)


def _text(value: object, field: str, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= maximum
        or value.strip() != value
        or "\0" in value
        or "\r" in value
    ):
        raise ValueError(f"Librarian qualification {field} is invalid")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError(f"Librarian qualification {field} is invalid") from error
    return value


def _bounded_int(value: object, minimum: int, maximum: int, field: str) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not minimum <= value <= maximum
    ):
        raise ValueError(f"Librarian qualification {field} is invalid")
    return value


def _positive_int(value: object, field: str) -> int:
    return _bounded_int(value, 1, 2**31 - 1, field)


def _count(value: object, field: str) -> int:
    return _bounded_int(value, 0, 1_000, field)


def _flag(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"Librarian qualification {field} is invalid")
    return value


def _sha256_json(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _duration(started: float) -> int:
    return max(0, round((time.monotonic() - started) * 1_000))


__all__ = [
    "LibrarianBoundQualificationCorpus",
    "LibrarianCompiledChunk",
    "LibrarianCompiledConcept",
    "LibrarianCompiledGeneration",
    "LibrarianCompiledPermission",
    "LibrarianEvidenceItemView",
    "LibrarianExpectedEvidenceItem",
    "LibrarianExpectedView",
    "LibrarianJobView",
    "LibrarianQualificationAcceptance",
    "LibrarianQualificationCase",
    "LibrarianQualificationCorpus",
    "LibrarianQualificationExecutor",
    "LibrarianQualificationInvocation",
    "LibrarianQualificationRenderedFile",
    "LibrarianQualificationRenderedGeneration",
    "LibrarianQualificationRenderedSource",
    "LibrarianQualificationResult",
    "build_librarian_qualification_invocations",
    "bind_librarian_compiled_corpus",
    "compile_librarian_expected_evidence",
    "evaluate_librarian_qualification",
    "load_librarian_qualification_acceptance",
    "load_librarian_qualification_corpus",
    "render_librarian_qualification_generations",
]
