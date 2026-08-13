"""Qualify Curator proposal review on one already-warm complex route."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass, field
import hashlib
import math
from pathlib import Path
import re
import threading
import time
from typing import Callable, Mapping, Protocol

from yap_server.agents.curator import (
    CuratorEvidence,
    CuratorEvidenceItem,
    CuratorRequest,
    CuratorReviewedStudentQuestion,
)
from yap_server.agents.curator_service import CuratorJobView, CuratorServiceError
from yap_server.agents.student_model import student_question_text
from yap_server.auth import AuthenticatedPrincipal
from yap_server.evaluation.provider_runtime_observations import (
    canonical_evidence_sha256,
)
from yap_server.private_artifact import read_json_object_with_identity
from yap_server.knowledge.knowledge_tool_contract import ProposalCitation


_MAXIMUM_ACCEPTANCE_BYTES = 32 * 1024
_MAXIMUM_FIXTURE_BYTES = 256 * 1024
_IDENTITY = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_RUN_ID = re.compile(r"^[a-z0-9][a-z0-9-]{7,31}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CASE_TIMEOUT_SECONDS = 65.0


class CuratorQualificationService(Protocol):
    def propose(
        self,
        request: CuratorRequest,
        *,
        principal: AuthenticatedPrincipal,
        cancellation: threading.Event,
    ) -> CuratorJobView: ...


@dataclass(frozen=True, slots=True)
class CuratorQualificationAcceptance:
    plan_sha256: str
    minimum_case_count: int
    minimum_owner_count: int
    concurrent_request_count: int
    minimum_proposed_case_count: int
    minimum_rejected_case_count: int
    maximum_terminal_failure_count: int
    maximum_p95_latency_milliseconds: int
    maximum_output_tokens: int
    maximum_input_tokens: int
    broker_active_capacity: int


@dataclass(frozen=True, slots=True)
class CuratorQualificationCase:
    case_id: str
    owner_id: str
    title: str
    trigger: str
    body: str
    reviewed_content: str
    expected_decision: str
    source_subject: str | None

    @property
    def concept_id(self) -> str:
        return f"meetings/{self.case_id}"


@dataclass(frozen=True, slots=True)
class CuratorQualificationCorpus:
    corpus_id: str
    corpus_sha256: str
    cases: tuple[CuratorQualificationCase, ...]


@dataclass(frozen=True, slots=True)
class CuratorExpectedEvidence:
    concept_id: str
    source_revision: str
    content_sha256: str
    char_start: int
    char_end: int
    text: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.concept_id, str)
            or not self.concept_id
            or not isinstance(self.source_revision, str)
            or _SHA256.fullmatch(self.source_revision) is None
            or not isinstance(self.content_sha256, str)
            or _SHA256.fullmatch(self.content_sha256) is None
            or isinstance(self.char_start, bool)
            or not isinstance(self.char_start, int)
            or isinstance(self.char_end, bool)
            or not isinstance(self.char_end, int)
            or self.char_start < 0
            or self.char_end <= self.char_start
            or not isinstance(self.text, str)
            or not self.text
            or self.char_end - self.char_start != len(self.text)
        ):
            raise ValueError("Curator expected evidence is invalid")

    @property
    def citation(self) -> ProposalCitation:
        return ProposalCitation(
            concept_id=self.concept_id,
            source_revision=self.source_revision,
            content_sha256=self.content_sha256,
            char_start=self.char_start,
            char_end=self.char_end,
        )


@dataclass(frozen=True, slots=True)
class CuratorExpectedEvidencePack:
    generation_sha256: str
    permission_hash: str
    authorization_hash: str
    items: tuple[CuratorExpectedEvidence, ...]

    def __post_init__(self) -> None:
        if (
            any(
                not isinstance(value, str) or _SHA256.fullmatch(value) is None
                for value in (
                    self.generation_sha256,
                    self.permission_hash,
                    self.authorization_hash,
                )
            )
            or not isinstance(self.items, tuple)
            or not 1 <= len(self.items) <= 8
            or any(
                not isinstance(item, CuratorExpectedEvidence)
                for item in self.items
            )
        ):
            raise ValueError("Curator expected evidence pack is invalid")

    @property
    def evidence(self) -> CuratorEvidence:
        return CuratorEvidence.create(
            generation_sha256=self.generation_sha256,
            permission_hash=self.permission_hash,
            authorization_hash=self.authorization_hash,
            items=tuple(
                CuratorEvidenceItem(item.citation, item.text)
                for item in self.items
            ),
        )


@dataclass(frozen=True, slots=True)
class CuratorCaseObservation:
    case: CuratorQualificationCase = field(repr=False)
    status: str
    reason: str | None
    request_id: str | None
    evidence_sha256: str | None
    proposal_id: str | None
    latency_milliseconds: int
    matched_expected_decision: bool

    def private_evidence(self) -> dict[str, object]:
        return {
            "caseId": self.case.case_id,
            "ownerId": self.case.owner_id,
            "trigger": self.case.trigger,
            "body": self.case.body,
            "reviewedContent": self.case.reviewed_content,
            "expectedDecision": self.case.expected_decision,
            "status": self.status,
            "reason": self.reason,
            "requestId": self.request_id,
            "evidenceSha256": self.evidence_sha256,
            "proposalId": self.proposal_id,
            "latencyMilliseconds": self.latency_milliseconds,
            "matchedExpectedDecision": self.matched_expected_decision,
        }


@dataclass(frozen=True, slots=True)
class CuratorQualificationResult:
    public_evidence: dict[str, object]
    private_evidence: dict[str, object] = field(repr=False)


def load_curator_qualification_acceptance(
    path: Path,
) -> CuratorQualificationAcceptance:
    value, identity = read_json_object_with_identity(
        path,
        maximum_bytes=_MAXIMUM_ACCEPTANCE_BYTES,
        field="Curator qualification acceptance",
    )
    expected = {
        "schemaVersion",
        "qualificationScope",
        "minimumCaseCount",
        "minimumOwnerCount",
        "concurrentRequestCount",
        "minimumProposedCaseCount",
        "minimumRejectedCaseCount",
        "maximumTerminalFailureCount",
        "maximumP95LatencyMilliseconds",
        "maximumOutputTokens",
        "maximumInputTokens",
        "brokerActiveCapacity",
    }
    if set(value) != expected:
        raise ValueError("Curator qualification acceptance shape differs")
    if (
        type(value["schemaVersion"]) is not int
        or value["schemaVersion"] != 1
        or value["qualificationScope"] != "curator-knowledge-proposals"
    ):
        raise ValueError("Curator qualification acceptance identity differs")
    acceptance = CuratorQualificationAcceptance(
        identity,
        _positive_int(value["minimumCaseCount"], "case count"),
        _positive_int(value["minimumOwnerCount"], "owner count"),
        _positive_int(value["concurrentRequestCount"], "concurrency"),
        _positive_int(value["minimumProposedCaseCount"], "proposed case count"),
        _positive_int(value["minimumRejectedCaseCount"], "rejected case count"),
        _nonnegative_int(
            value["maximumTerminalFailureCount"],
            "terminal failure count",
        ),
        _positive_int(value["maximumP95LatencyMilliseconds"], "p95 latency"),
        _positive_int(value["maximumOutputTokens"], "output tokens"),
        _positive_int(value["maximumInputTokens"], "input tokens"),
        _positive_int(value["brokerActiveCapacity"], "broker capacity"),
    )
    if (
        acceptance.minimum_owner_count > acceptance.minimum_case_count
        or acceptance.concurrent_request_count > acceptance.minimum_case_count
        or acceptance.minimum_proposed_case_count
        + acceptance.minimum_rejected_case_count
        > acceptance.minimum_case_count
        or acceptance.maximum_p95_latency_milliseconds > 60_000
        or acceptance.maximum_output_tokens != 512
        or acceptance.maximum_input_tokens != 7_680
        or acceptance.broker_active_capacity != 8
        or acceptance.concurrent_request_count
        != acceptance.broker_active_capacity
    ):
        raise ValueError("Curator qualification acceptance values conflict")
    return acceptance


def load_curator_qualification_corpus(path: Path) -> CuratorQualificationCorpus:
    value, identity = read_json_object_with_identity(
        path,
        maximum_bytes=_MAXIMUM_FIXTURE_BYTES,
        field="Curator qualification fixtures",
    )
    if set(value) != {"schemaVersion", "qualificationScope", "corpusId", "cases"}:
        raise ValueError("Curator qualification fixture shape differs")
    if (
        type(value["schemaVersion"]) is not int
        or value["schemaVersion"] != 1
        or value["qualificationScope"] != "curator-knowledge-proposals"
        or not isinstance(value["corpusId"], str)
        or _IDENTITY.fullmatch(value["corpusId"]) is None
        or not isinstance(value["cases"], list)
        or not 1 <= len(value["cases"]) <= 64
    ):
        raise ValueError("Curator qualification fixture identity is invalid")
    cases = tuple(_case(item) for item in value["cases"])
    if (
        len({case.case_id for case in cases}) != len(cases)
        or len({case.owner_id for case in cases}) != len(cases)
    ):
        raise ValueError("Curator qualification cases must have distinct owners")
    return CuratorQualificationCorpus(str(value["corpusId"]), identity, cases)


def evaluate_curator_qualification(
    *,
    service: CuratorQualificationService,
    corpus: CuratorQualificationCorpus,
    acceptance: CuratorQualificationAcceptance,
    tenant_id: str,
    qualification_run_id: str,
    generation_sha256: str,
    expected_evidence: Mapping[str, CuratorExpectedEvidencePack],
    observe_warm_state: Callable[[], Mapping[str, object]],
    observe_admission_state: Callable[[], Mapping[str, object]],
) -> CuratorQualificationResult:
    if _IDENTITY.fullmatch(tenant_id) is None:
        raise ValueError("Curator qualification tenant identity differs")
    if (
        not isinstance(qualification_run_id, str)
        or _RUN_ID.fullmatch(qualification_run_id) is None
    ):
        raise ValueError("Curator qualification run identity differs")
    if (
        set(expected_evidence) != {case.case_id for case in corpus.cases}
        or any(
            not isinstance(pack, CuratorExpectedEvidencePack)
            or pack.generation_sha256 != generation_sha256
            for pack in expected_evidence.values()
        )
    ):
        raise ValueError("Curator qualification evidence identities differ")
    requests = build_curator_qualification_requests(
        corpus,
        qualification_run_id=qualification_run_id,
        generation_sha256=generation_sha256,
        expected_evidence={
            case_id: pack.items for case_id, pack in expected_evidence.items()
        },
    )
    expected_evidence_sha256 = {
        case_id: pack.evidence.evidence_sha256
        for case_id, pack in expected_evidence.items()
    }

    before = _warm_state(observe_warm_state())
    admission_before = _admission_state(observe_admission_state())
    observations: list[CuratorCaseObservation] = []
    wave_owner_counts: list[tuple[int, int]] = []
    for offset in range(0, len(corpus.cases), acceptance.concurrent_request_count):
        wave = corpus.cases[offset : offset + acceptance.concurrent_request_count]
        wave_owner_counts.append((len(wave), len({case.owner_id for case in wave})))
        barrier = threading.Barrier(len(wave))
        cancellations = {case.case_id: threading.Event() for case in wave}
        executor: ThreadPoolExecutor | None = ThreadPoolExecutor(
            max_workers=len(wave),
            thread_name_prefix="curator-qualification",
        )
        try:
            futures = [
                executor.submit(
                    _run_case,
                    service,
                    case,
                    tenant_id,
                    requests[case.case_id],
                    expected_evidence_sha256[case.case_id],
                    barrier,
                    cancellations[case.case_id],
                )
                for case in wave
            ]
            _, incomplete = wait(futures, timeout=_CASE_TIMEOUT_SECONDS)
            if incomplete:
                for cancellation in cancellations.values():
                    cancellation.set()
                _, uncontained = wait(incomplete, timeout=5.0)
                if uncontained:
                    executor.shutdown(wait=False, cancel_futures=True)
                    executor = None
                    raise RuntimeError(
                        "Curator qualification cancellation was not contained"
                    )
                raise TimeoutError("Curator qualification wave exceeded its timeout")
            observations.extend(future.result() for future in futures)
        finally:
            if executor is not None:
                executor.shutdown(wait=True, cancel_futures=True)
    after = _warm_state(observe_warm_state())
    admission_after = _admission_state(observe_admission_state())

    latencies = sorted(item.latency_milliseconds for item in observations)
    p95_index = max(0, math.ceil(len(latencies) * 0.95) - 1)
    counts = {
        "caseCount": len(observations),
        "ownerCount": len({item.case.owner_id for item in observations}),
        "proposedCaseCount": sum(item.status == "proposed" for item in observations),
        "rejectedCaseCount": sum(item.status == "rejected" for item in observations),
        "terminalFailureCount": sum(
            item.status not in {"proposed", "rejected"} for item in observations
        ),
        "synchronizedOwnerWaveCount": max(
            (
                owners
                for cases, owners in wave_owner_counts
                if cases == acceptance.concurrent_request_count
            ),
            default=0,
        ),
    }
    warm_unchanged = before == after
    admission_unchanged = admission_before == admission_after
    checks = {
        "caseCountMet": counts["caseCount"] >= acceptance.minimum_case_count,
        "ownerCountMet": counts["ownerCount"] >= acceptance.minimum_owner_count,
        "synchronizedOwnerWaveMet": counts["synchronizedOwnerWaveCount"]
        >= acceptance.concurrent_request_count,
        "allWaveOwnersDistinct": all(
            cases == owners for cases, owners in wave_owner_counts
        ),
        "expectedDecisionsExact": all(
            item.matched_expected_decision for item in observations
        ),
        "proposedCaseCountMet": counts["proposedCaseCount"]
        >= acceptance.minimum_proposed_case_count,
        "rejectedCaseCountMet": counts["rejectedCaseCount"]
        >= acceptance.minimum_rejected_case_count,
        "terminalFailuresMet": counts["terminalFailureCount"]
        <= acceptance.maximum_terminal_failure_count,
        "p95LatencyMet": latencies[p95_index]
        <= acceptance.maximum_p95_latency_milliseconds,
        "alreadyWarmGenerationUnchanged": warm_unchanged,
        "admissionBrokerProcessUnchanged": admission_unchanged,
    }
    passed = all(checks.values())
    public: dict[str, object] = {
        "schemaVersion": 1,
        "qualificationScope": "curator-knowledge-proposals",
        "outcome": (
            "curator-knowledge-proposals-qualified"
            if passed
            else "deterministic-no-curator"
        ),
        "corpusId": corpus.corpus_id,
        "corpusSha256": corpus.corpus_sha256,
        "acceptancePlanSha256": acceptance.plan_sha256,
        "qualificationRunSha256": hashlib.sha256(
            qualification_run_id.encode("utf-8")
        ).hexdigest(),
        "counts": counts,
        "route": {
            "profileId": before["profileId"],
            "profileSha256": before["profileSha256"],
            "candidateLockSha256": before["candidateLockSha256"],
            "concurrentRequestCount": acceptance.concurrent_request_count,
            "synchronizedOwnerWaveCount": counts["synchronizedOwnerWaveCount"],
            "maximumOutputTokens": acceptance.maximum_output_tokens,
            "maximumInputTokens": acceptance.maximum_input_tokens,
            "alreadyWarmGenerationUnchanged": warm_unchanged,
            "admissionBrokerProcessUnchanged": admission_unchanged,
        },
        "acceptance": checks,
    }
    public["evidenceSha256"] = canonical_evidence_sha256(public)
    private = {
        **public,
        "privacyScope": "private-curator-qualification",
        "qualificationRunId": qualification_run_id,
        "measurements": {
            "latenciesMilliseconds": latencies,
            "p95LatencyMilliseconds": latencies[p95_index],
        },
        "cases": [item.private_evidence() for item in observations],
        "warmState": {"before": dict(before), "after": dict(after)},
        "admissionState": {
            "before": dict(admission_before),
            "after": dict(admission_after),
        },
    }
    return CuratorQualificationResult(public, private)


def build_curator_qualification_requests(
    corpus: CuratorQualificationCorpus,
    *,
    qualification_run_id: str,
    generation_sha256: str,
    expected_evidence: Mapping[str, tuple[CuratorExpectedEvidence, ...]],
) -> dict[str, CuratorRequest]:
    if (
        not isinstance(qualification_run_id, str)
        or _RUN_ID.fullmatch(qualification_run_id) is None
        or not isinstance(generation_sha256, str)
        or _SHA256.fullmatch(generation_sha256) is None
        or set(expected_evidence) != {case.case_id for case in corpus.cases}
    ):
        raise ValueError("Curator qualification expected evidence differs")
    requests: dict[str, CuratorRequest] = {}
    for case in corpus.cases:
        items = expected_evidence[case.case_id]
        if (
            not isinstance(items, tuple)
            or len(items) != 1
            or any(
                not isinstance(item, CuratorExpectedEvidence)
                or item.concept_id != case.concept_id
                for item in items
            )
            or items[0].text != case.body
        ):
            raise ValueError("Curator qualification expected evidence is invalid")
        student_question = None
        citations = tuple(item.citation for item in items)
        if case.source_subject is not None:
            if len(items) != 1 or items[0].text.count(case.source_subject) != 1:
                raise ValueError("Curator Student source evidence differs")
            item = items[0]
            relative_start = item.text.index(case.source_subject)
            student_question = CuratorReviewedStudentQuestion(
                source_subject=case.source_subject,
                question=student_question_text(case.source_subject),
                source_citation=item.citation,
                support_quote=case.source_subject,
                support_char_start=item.char_start + relative_start,
                support_char_end=(
                    item.char_start + relative_start + len(case.source_subject)
                ),
            )
        requests[case.case_id] = CuratorRequest(
            submission_id=f"{qualification_run_id}-{case.case_id}",
            trigger=case.trigger,
            expected_generation_sha256=generation_sha256,
            reviewed_content=case.reviewed_content,
            source_citations=citations,
            student_question=student_question,
        )
    return requests


def _case(value: object) -> CuratorQualificationCase:
    if not isinstance(value, dict):
        raise ValueError("Curator qualification case shape differs")
    trigger = value.get("trigger")
    expected = {
        "caseId",
        "ownerId",
        "title",
        "trigger",
        "body",
        "reviewedContent",
        "expectedDecision",
    }
    if trigger == "reviewed-student-answer":
        expected.add("sourceSubject")
    if set(value) != expected:
        raise ValueError("Curator qualification case shape differs")
    if (
        not isinstance(value["caseId"], str)
        or _IDENTITY.fullmatch(value["caseId"]) is None
        or not isinstance(value["ownerId"], str)
        or _IDENTITY.fullmatch(value["ownerId"]) is None
        or not isinstance(trigger, str)
        or trigger not in {"explicit-proposal", "reviewed-student-answer"}
        or value["expectedDecision"] not in {"propose", "reject"}
    ):
        raise ValueError("Curator qualification case identity is invalid")
    source_subject = (
        _text(value["sourceSubject"], "source subject", 256)
        if trigger == "reviewed-student-answer"
        else None
    )
    body = _text(value["body"], "body", 4_096, multiline=True)
    if source_subject is not None and body.count(source_subject) != 1:
        raise ValueError("Curator Student subject is not exact source text")
    return CuratorQualificationCase(
        str(value["caseId"]),
        str(value["ownerId"]),
        _text(value["title"], "title", 128),
        str(trigger),
        body,
        _text(value["reviewedContent"], "reviewed content", 2_048),
        str(value["expectedDecision"]),
        source_subject,
    )


def _run_case(
    service: CuratorQualificationService,
    case: CuratorQualificationCase,
    tenant_id: str,
    request: CuratorRequest,
    expected_evidence_sha256: str,
    barrier: threading.Barrier,
    cancellation: threading.Event,
) -> CuratorCaseObservation:
    principal = AuthenticatedPrincipal(
        tenant_id=tenant_id,
        subject_id=case.owner_id,
        client_id="curator-qualification",
        scopes=frozenset({"knowledge.read", "knowledge.propose"}),
    )
    barrier.wait(timeout=5.0)
    started = time.monotonic()
    try:
        view = service.propose(
            request,
            principal=principal,
            cancellation=cancellation,
        )
    except CuratorServiceError as error:
        return CuratorCaseObservation(
            case,
            "failed",
            error.code,
            None,
            None,
            None,
            _duration(started),
            False,
        )
    elapsed = _duration(started)
    if elapsed > round(_CASE_TIMEOUT_SECONDS * 1_000):
        raise TimeoutError("Curator qualification exceeded its case timeout")
    matched = (
        case.expected_decision == "propose"
        and view.status == "proposed"
        and view.reason is None
        and isinstance(view.proposal_id, str)
        and _SHA256.fullmatch(view.proposal_id) is not None
    ) or (
        case.expected_decision == "reject"
        and view.status == "rejected"
        and view.reason == "model-rejected"
        and view.proposal_id is None
    )
    matched = bool(
        matched
        and isinstance(view.request_id, str)
        and 1 <= len(view.request_id) <= 128
        and view.submission_id == request.submission_id
        and view.generation_sha256 == request.expected_generation_sha256
        and view.evidence_sha256 == expected_evidence_sha256
    )
    return CuratorCaseObservation(
        case,
        view.status,
        view.reason,
        view.request_id,
        view.evidence_sha256,
        view.proposal_id,
        elapsed,
        matched,
    )


def _warm_state(value: Mapping[str, object]) -> dict[str, object]:
    keys = {
        "profileId",
        "profileSha256",
        "candidateLockSha256",
        "processGeneration",
        "startCount",
        "restartCount",
        "state",
    }
    if not isinstance(value, Mapping) or not keys.issubset(value):
        raise ValueError("Curator warm service state is incomplete")
    if (
        value["state"] != "ready"
        or value["profileId"] != "complex-orchestration"
        or any(
            not isinstance(value[key], str) or not value[key]
            for key in ("profileSha256", "candidateLockSha256")
        )
        or any(
            isinstance(value[key], bool)
            or not isinstance(value[key], int)
            or value[key] < 0
            for key in ("startCount", "restartCount")
        )
        or value["startCount"] < 1
        or isinstance(value["processGeneration"], bool)
        or not isinstance(value["processGeneration"], int)
        or value["processGeneration"] < 1
    ):
        raise ValueError("Curator warm service state is invalid")
    return {key: value[key] for key in sorted(keys)}


def _admission_state(value: Mapping[str, object]) -> dict[str, object]:
    keys = {
        "processId",
        "processStartTicks",
        "binarySha256",
        "socketDevice",
        "socketInode",
    }
    if not isinstance(value, Mapping) or set(value) != keys:
        raise ValueError("Curator admission broker state differs")
    if (
        not isinstance(value["binarySha256"], str)
        or _SHA256.fullmatch(value["binarySha256"]) is None
        or any(
            isinstance(value[key], bool)
            or not isinstance(value[key], int)
            or value[key] < 1
            for key in keys - {"binarySha256"}
        )
    ):
        raise ValueError("Curator admission broker state is invalid")
    return {key: value[key] for key in sorted(keys)}


def _text(value: object, field: str, maximum: int, *, multiline: bool = False) -> str:
    valid = (
        isinstance(value, str)
        and 1 <= len(value) <= maximum
        and value.strip() == value
        and "\r" not in value
        and all(character == "\n" or character.isprintable() for character in value)
    )
    if not valid or (not multiline and "\n" in value):
        raise ValueError(f"Curator qualification {field} is invalid")
    return value


def _positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"Curator qualification {field} is invalid")
    return value


def _nonnegative_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"Curator qualification {field} is invalid")
    return value


def _duration(started: float) -> int:
    return max(0, round((time.monotonic() - started) * 1_000))


__all__ = [
    "CuratorQualificationAcceptance",
    "CuratorQualificationCase",
    "CuratorQualificationCorpus",
    "CuratorExpectedEvidence",
    "CuratorExpectedEvidencePack",
    "CuratorQualificationResult",
    "build_curator_qualification_requests",
    "evaluate_curator_qualification",
    "load_curator_qualification_acceptance",
    "load_curator_qualification_corpus",
]
