"""Qualify Student question generation on one already-warm rapid route."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
import math
from pathlib import Path
import re
import threading
import time
from typing import Callable, Mapping, Protocol

from yap_server.agents.student import StudentRequest
from yap_server.agents.student_model import (
    StudentQuestion,
    validate_student_question_grounding,
)
from yap_server.agents.student_service import StudentJobView, StudentServiceError
from yap_server.auth import AuthenticatedPrincipal
from yap_server.evaluation.provider_runtime_observations import (
    canonical_evidence_sha256,
)
from yap_server.private_artifact import read_json_object_with_identity


_MAXIMUM_ACCEPTANCE_BYTES = 32 * 1024
_MAXIMUM_FIXTURE_BYTES = 256 * 1024
_IDENTITY = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CASE_TIMEOUT_SECONDS = 65.0


class StudentQualificationService(Protocol):
    def create_questions(
        self,
        request: StudentRequest,
        *,
        principal: AuthenticatedPrincipal,
        cancellation: threading.Event,
    ) -> StudentJobView: ...


@dataclass(frozen=True, slots=True)
class StudentQualificationAcceptance:
    plan_sha256: str
    minimum_case_count: int
    minimum_owner_count: int
    concurrent_request_count: int
    minimum_questions_per_case: int
    maximum_questions_per_case: int
    minimum_required_term_coverage_rate: float
    maximum_forbidden_term_hit_count: int
    maximum_output_budget_exhausted_count: int
    maximum_terminal_failure_count: int
    maximum_p95_latency_milliseconds: int


@dataclass(frozen=True, slots=True)
class StudentQualificationCase:
    case_id: str
    owner_id: str
    title: str
    topic: str
    body: str
    required_question_terms: tuple[str, ...]
    forbidden_question_terms: tuple[str, ...]

    @property
    def concept_id(self) -> str:
        return f"meetings/{self.case_id}"


@dataclass(frozen=True, slots=True)
class StudentQualificationCorpus:
    corpus_id: str
    corpus_sha256: str
    cases: tuple[StudentQualificationCase, ...]


@dataclass(frozen=True, slots=True)
class StudentExpectedEvidence:
    concept_id: str
    source_revision: str
    content_sha256: str
    char_start: int
    char_end: int
    text: str


@dataclass(frozen=True, slots=True)
class StudentCaseObservation:
    case: StudentQualificationCase = field(repr=False)
    status: str
    reason: str | None
    request_id: str | None
    evidence_sha256: str | None
    questions: tuple[StudentQuestion, ...] = field(repr=False)
    latency_milliseconds: int
    required_term_count: int
    covered_required_term_count: int
    forbidden_term_hit_count: int
    supports_exact: bool
    output_budget_exhausted: bool

    def private_evidence(self) -> dict[str, object]:
        return {
            "caseId": self.case.case_id,
            "ownerId": self.case.owner_id,
            "topic": self.case.topic,
            "body": self.case.body,
            "status": self.status,
            "reason": self.reason,
            "requestId": self.request_id,
            "evidenceSha256": self.evidence_sha256,
            "latencyMilliseconds": self.latency_milliseconds,
            "requiredQuestionTerms": list(self.case.required_question_terms),
            "forbiddenQuestionTerms": list(self.case.forbidden_question_terms),
            "questions": [question.to_wire() for question in self.questions],
            "quality": {
                "requiredTermCount": self.required_term_count,
                "coveredRequiredTermCount": self.covered_required_term_count,
                "forbiddenTermHitCount": self.forbidden_term_hit_count,
                "supportsExact": self.supports_exact,
                "outputBudgetExhausted": self.output_budget_exhausted,
            },
        }


@dataclass(frozen=True, slots=True)
class StudentQualificationResult:
    public_evidence: dict[str, object]
    private_evidence: dict[str, object] = field(repr=False)


def load_student_qualification_acceptance(
    path: Path,
) -> StudentQualificationAcceptance:
    value, identity = read_json_object_with_identity(
        path,
        maximum_bytes=_MAXIMUM_ACCEPTANCE_BYTES,
        field="Student qualification acceptance",
    )
    expected = {
        "schemaVersion",
        "qualificationScope",
        "minimumCaseCount",
        "minimumOwnerCount",
        "concurrentRequestCount",
        "minimumQuestionsPerCase",
        "maximumQuestionsPerCase",
        "minimumRequiredTermCoverageRate",
        "maximumForbiddenTermHitCount",
        "maximumOutputBudgetExhaustedCount",
        "maximumTerminalFailureCount",
        "maximumP95LatencyMilliseconds",
    }
    if set(value) != expected:
        raise ValueError("Student qualification acceptance shape differs")
    if (
        isinstance(value["schemaVersion"], bool)
        or value["schemaVersion"] != 1
        or value["qualificationScope"] != "student-learning-questions"
    ):
        raise ValueError("Student qualification acceptance identity differs")
    acceptance = StudentQualificationAcceptance(
        plan_sha256=identity,
        minimum_case_count=_positive_int(value["minimumCaseCount"], "case count"),
        minimum_owner_count=_positive_int(
            value["minimumOwnerCount"], "owner count"
        ),
        concurrent_request_count=_positive_int(
            value["concurrentRequestCount"], "concurrency"
        ),
        minimum_questions_per_case=_positive_int(
            value["minimumQuestionsPerCase"], "minimum question count"
        ),
        maximum_questions_per_case=_positive_int(
            value["maximumQuestionsPerCase"], "maximum question count"
        ),
        minimum_required_term_coverage_rate=_rate(
            value["minimumRequiredTermCoverageRate"], "term coverage"
        ),
        maximum_forbidden_term_hit_count=_nonnegative_int(
            value["maximumForbiddenTermHitCount"], "forbidden-term hit count"
        ),
        maximum_output_budget_exhausted_count=_nonnegative_int(
            value["maximumOutputBudgetExhaustedCount"],
            "output-budget exhausted count",
        ),
        maximum_terminal_failure_count=_nonnegative_int(
            value["maximumTerminalFailureCount"], "terminal failure count"
        ),
        maximum_p95_latency_milliseconds=_positive_int(
            value["maximumP95LatencyMilliseconds"], "p95 latency"
        ),
    )
    if (
        acceptance.minimum_owner_count > acceptance.minimum_case_count
        or acceptance.concurrent_request_count > acceptance.minimum_case_count
        or acceptance.minimum_questions_per_case
        > acceptance.maximum_questions_per_case
        or acceptance.minimum_questions_per_case != 1
        or acceptance.maximum_questions_per_case != 1
        or acceptance.maximum_p95_latency_milliseconds > 60_000
    ):
        raise ValueError("Student qualification acceptance values conflict")
    return acceptance


def load_student_qualification_corpus(path: Path) -> StudentQualificationCorpus:
    value, identity = read_json_object_with_identity(
        path,
        maximum_bytes=_MAXIMUM_FIXTURE_BYTES,
        field="Student qualification fixtures",
    )
    if set(value) != {"schemaVersion", "qualificationScope", "corpusId", "cases"}:
        raise ValueError("Student qualification fixture shape differs")
    if (
        isinstance(value["schemaVersion"], bool)
        or value["schemaVersion"] != 2
        or value["qualificationScope"] != "student-learning-questions"
        or _IDENTITY.fullmatch(value["corpusId"])
        is None
        or not isinstance(value["cases"], list)
        or not value["cases"]
        or len(value["cases"]) > 64
    ):
        raise ValueError("Student qualification fixture identity is invalid")
    cases = tuple(_case(item) for item in value["cases"])
    if (
        len({item.case_id for item in cases}) != len(cases)
        or len({item.owner_id for item in cases}) != len(cases)
    ):
        raise ValueError("Student qualification cases must have distinct owners")
    return StudentQualificationCorpus(value["corpusId"], identity, cases)


def evaluate_student_qualification(
    *,
    service: StudentQualificationService,
    corpus: StudentQualificationCorpus,
    acceptance: StudentQualificationAcceptance,
    tenant_id: str,
    generation_sha256: str,
    expected_evidence: Mapping[str, tuple[StudentExpectedEvidence, ...]],
    observe_warm_state: Callable[[], Mapping[str, object]],
    observe_admission_state: Callable[[], Mapping[str, object]],
) -> StudentQualificationResult:
    """Run the public synthetic cases through one existing warm Qwen service."""

    if _IDENTITY.fullmatch(tenant_id) is None or _SHA256.fullmatch(
        generation_sha256
    ) is None:
        raise ValueError("Student qualification knowledge identity is invalid")
    if (
        set(expected_evidence) != {case.case_id for case in corpus.cases}
        or any(
            not isinstance(items, tuple)
            or not 1 <= len(items) <= 8
            or any(not isinstance(item, StudentExpectedEvidence) for item in items)
            for items in expected_evidence.values()
        )
    ):
        raise ValueError("Student qualification expected evidence differs")
    before = _warm_state(observe_warm_state())
    admission_before = _admission_state(observe_admission_state())
    observations: list[StudentCaseObservation] = []
    wave_owner_counts: list[tuple[int, int]] = []
    for offset in range(0, len(corpus.cases), acceptance.concurrent_request_count):
        wave = corpus.cases[offset : offset + acceptance.concurrent_request_count]
        wave_owner_counts.append((len(wave), len({case.owner_id for case in wave})))
        barrier = threading.Barrier(len(wave))
        with ThreadPoolExecutor(
            max_workers=len(wave),
            thread_name_prefix="student-qualification",
        ) as executor:
            futures = [
                executor.submit(
                    _run_case,
                    service,
                    case,
                    tenant_id,
                    generation_sha256,
                    expected_evidence[case.case_id],
                    barrier,
                )
                for case in wave
            ]
            observations.extend(future.result() for future in futures)
    after = _warm_state(observe_warm_state())
    admission_after = _admission_state(observe_admission_state())
    warm_unchanged = before == after
    admission_unchanged = admission_before == admission_after
    all_wave_owners_distinct = all(
        wave_count == owner_count for wave_count, owner_count in wave_owner_counts
    )
    latencies = sorted(item.latency_milliseconds for item in observations)
    p95_index = max(0, math.ceil(len(latencies) * 0.95) - 1)
    required_count = sum(item.required_term_count for item in observations)
    covered_count = sum(item.covered_required_term_count for item in observations)
    coverage_rate = covered_count / required_count if required_count else 0.0
    counts = {
        "caseCount": len(observations),
        "ownerCount": len({item.case.owner_id for item in observations}),
        "completeCaseCount": sum(item.status == "complete" for item in observations),
        "questionCount": sum(len(item.questions) for item in observations),
        "terminalFailureCount": sum(item.status != "complete" for item in observations),
        "forbiddenTermHitCount": sum(
            item.forbidden_term_hit_count for item in observations
        ),
        "outputBudgetExhaustedCount": sum(
            item.output_budget_exhausted for item in observations
        ),
        "maximumConcurrentOwnerCount": max(
            (
                owner_count
                for wave_count, owner_count in wave_owner_counts
                if wave_count == acceptance.concurrent_request_count
            ),
            default=0,
        ),
    }
    checks = {
        "caseCountMet": counts["caseCount"] >= acceptance.minimum_case_count,
        "ownerCountMet": counts["ownerCount"] >= acceptance.minimum_owner_count,
        "concurrentOwnersMet": counts["maximumConcurrentOwnerCount"]
        >= acceptance.concurrent_request_count,
        "allWaveOwnersDistinct": all_wave_owners_distinct,
        "allCasesComplete": counts["completeCaseCount"] == counts["caseCount"],
        "questionCountsMet": all(
            acceptance.minimum_questions_per_case
            <= len(item.questions)
            <= acceptance.maximum_questions_per_case
            for item in observations
        ),
        "questionsSourceGrounded": all(
            _questions_are_grounded(item.questions) for item in observations
        ),
        "requiredTermCoverageMet": coverage_rate
        >= acceptance.minimum_required_term_coverage_rate,
        "forbiddenTermsAbsent": counts["forbiddenTermHitCount"]
        <= acceptance.maximum_forbidden_term_hit_count,
        "sourceSupportsExact": all(item.supports_exact for item in observations),
        "outputBudgetMet": counts["outputBudgetExhaustedCount"]
        <= acceptance.maximum_output_budget_exhausted_count,
        "terminalFailuresMet": counts["terminalFailureCount"]
        <= acceptance.maximum_terminal_failure_count,
        "p95LatencyMet": latencies[p95_index]
        <= acceptance.maximum_p95_latency_milliseconds,
        "alreadyWarmGenerationUnchanged": warm_unchanged,
        "admissionBrokerProcessUnchanged": admission_unchanged,
    }
    passed = all(checks.values())
    public = {
        "schemaVersion": 3,
        "qualificationScope": "student-learning-questions",
        "outcome": (
            "student-learning-questions-qualified"
            if passed
            else "deterministic-no-student"
        ),
        "corpusId": corpus.corpus_id,
        "corpusSha256": corpus.corpus_sha256,
        "acceptancePlanSha256": acceptance.plan_sha256,
        "counts": counts,
        "route": {
            "profileId": before["profileId"],
            "profileSha256": before["profileSha256"],
            "candidateLockSha256": before["candidateLockSha256"],
            "concurrentRequestCount": acceptance.concurrent_request_count,
            "maximumConcurrentOwnerCount": counts["maximumConcurrentOwnerCount"],
            "alreadyWarmGenerationUnchanged": warm_unchanged,
            "admissionBrokerProcessUnchanged": admission_unchanged,
        },
        "acceptance": checks,
    }
    public["evidenceSha256"] = canonical_evidence_sha256(public)
    private = {
        **public,
        "privacyScope": "private-student-qualification",
        "measurements": {
            "latenciesMilliseconds": latencies,
            "p95LatencyMilliseconds": latencies[p95_index],
            "requiredTermCount": required_count,
            "coveredRequiredTermCount": covered_count,
            "requiredTermCoverageRate": coverage_rate,
        },
        "cases": [item.private_evidence() for item in observations],
        "warmState": {"before": dict(before), "after": dict(after)},
        "admissionState": {
            "before": dict(admission_before),
            "after": dict(admission_after),
        },
    }
    return StudentQualificationResult(public, private)


def _case(value: object) -> StudentQualificationCase:
    expected = {
        "caseId",
        "ownerId",
        "title",
        "topic",
        "body",
        "requiredQuestionTerms",
        "forbiddenQuestionTerms",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError("Student qualification case shape differs")
    if _IDENTITY.fullmatch(value["caseId"]) is None or _IDENTITY.fullmatch(
        value["ownerId"]
    ) is None:
        raise ValueError("Student qualification case identity is invalid")
    title = _text(value["title"], "title", 128)
    topic = _text(value["topic"], "topic", 128)
    body = _text(value["body"], "body", 4_096, multiline=True)
    if any(character in topic for character in "?\r\n"):
        raise ValueError("Student qualification topic is not topic-only")
    required = _terms(value["requiredQuestionTerms"], "required terms", required=True)
    forbidden = _terms(
        value["forbiddenQuestionTerms"], "forbidden terms", required=False
    )
    body_folded = body.casefold()
    if any(term.casefold() not in body_folded for term in required):
        raise ValueError("Student qualification required term is not sourced")
    return StudentQualificationCase(
        value["caseId"],
        value["ownerId"],
        title,
        topic,
        body,
        required,
        forbidden,
    )


def _run_case(
    service: StudentQualificationService,
    case: StudentQualificationCase,
    tenant_id: str,
    generation_sha256: str,
    expected_evidence: tuple[StudentExpectedEvidence, ...],
    barrier: threading.Barrier,
) -> StudentCaseObservation:
    principal = AuthenticatedPrincipal(
        tenant_id=tenant_id,
        subject_id=case.owner_id,
        client_id="student-qualification",
        scopes=frozenset({"knowledge.read"}),
    )
    request = StudentRequest(
        conversation_concept_id=case.concept_id,
        expected_generation_sha256=generation_sha256,
        topic=case.topic,
    )
    barrier.wait(timeout=5.0)
    started = time.monotonic()
    try:
        view = service.create_questions(
            request,
            principal=principal,
            cancellation=threading.Event(),
        )
    except StudentServiceError as error:
        return StudentCaseObservation(
            case,
            "failed",
            error.code,
            None,
            None,
            (),
            _duration(started),
            len(case.required_question_terms),
            0,
            0,
            False,
            False,
        )
    elapsed = _duration(started)
    if elapsed > round(_CASE_TIMEOUT_SECONDS * 1_000):
        raise TimeoutError("Student qualification exceeded its case timeout")
    questions = view.questions
    combined = "\n".join(question.question for question in questions).casefold()
    covered = sum(
        term.casefold() in combined for term in case.required_question_terms
    )
    forbidden = sum(
        term.casefold() in combined for term in case.forbidden_question_terms
    )
    supports_exact = bool(questions) and all(
        _question_supports_are_exact(question, expected_evidence)
        for question in questions
    )
    return StudentCaseObservation(
        case,
        view.status,
        view.reason,
        view.request_id,
        view.evidence_sha256,
        questions,
        elapsed,
        len(case.required_question_terms),
        covered,
        forbidden,
        supports_exact,
        view.output_budget_exhausted,
    )


def _questions_are_grounded(questions: tuple[StudentQuestion, ...]) -> bool:
    try:
        for question in questions:
            validate_student_question_grounding(question)
    except (TypeError, ValueError):
        return False
    return bool(questions)


def _question_supports_are_exact(
    question: StudentQuestion,
    expected: tuple[StudentExpectedEvidence, ...],
) -> bool:
    try:
        validate_student_question_grounding(question)
    except (TypeError, ValueError):
        return False
    return bool(question.supports) and all(
        any(
            support.evidence.concept_id == item.concept_id
            and support.evidence.source_revision == item.source_revision
            and support.evidence.content_sha256 == item.content_sha256
            and support.evidence.char_start == item.char_start
            and support.evidence.char_end == item.char_end
            and support.evidence.text == item.text
            and support.quote in item.text
            for item in expected
        )
        for support in question.supports
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
        raise ValueError("Student warm service state is incomplete")
    if (
        value["state"] != "ready"
        or value["profileId"] != "rapid-automation"
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
    ):
        raise ValueError("Student warm service state is invalid")
    if value["processGeneration"] < 1:
        raise ValueError("Student warm service generation is invalid")
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
        raise ValueError("Student admission broker state differs")
    if _SHA256.fullmatch(value["binarySha256"]) is None or any(
        isinstance(value[key], bool)
        or not isinstance(value[key], int)
        or value[key] < 1
        for key in keys - {"binarySha256"}
    ):
        raise ValueError("Student admission broker state is invalid")
    return {key: value[key] for key in sorted(keys)}


def _terms(value: object, field: str, *, required: bool) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > 8 or (required and not value):
        raise ValueError(f"Student qualification {field} are invalid")
    terms = tuple(_text(item, field, 128) for item in value)
    if len({item.casefold() for item in terms}) != len(terms):
        raise ValueError(f"Student qualification {field} are duplicated")
    return terms


def _text(value: object, field: str, maximum: int, *, multiline: bool = False) -> str:
    allowed = (
        isinstance(value, str)
        and 1 <= len(value) <= maximum
        and value.strip() == value
        and "\r" not in value
        and all(character == "\n" or character.isprintable() for character in value)
    )
    if not allowed or (not multiline and "\n" in value):
        raise ValueError(f"Student qualification {field} is invalid")
    return value


def _positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"Student qualification {field} is invalid")
    return value


def _nonnegative_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"Student qualification {field} is invalid")
    return value


def _rate(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Student qualification {field} is invalid")
    result = float(value)
    if not 0.0 <= result <= 1.0:
        raise ValueError(f"Student qualification {field} is invalid")
    return result


def _duration(started: float) -> int:
    return max(0, round((time.monotonic() - started) * 1_000))


__all__ = [
    "StudentQualificationAcceptance",
    "StudentQualificationCase",
    "StudentQualificationCorpus",
    "StudentExpectedEvidence",
    "StudentQualificationResult",
    "evaluate_student_qualification",
    "load_student_qualification_acceptance",
    "load_student_qualification_corpus",
]
