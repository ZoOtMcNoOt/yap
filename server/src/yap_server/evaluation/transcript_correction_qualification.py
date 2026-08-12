"""Qualify Scribe correction quality on one already-warm multi-owner route."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
import math
from pathlib import Path
import threading
import time
from typing import Callable, Mapping, Protocol

from yap_server.agents.transcript_correction_service import (
    TranscriptCorrectionJobView,
    TranscriptCorrectionServiceError,
)
from yap_server.auth import AuthenticatedPrincipal
from yap_server.evaluation.provider_runtime_observations import (
    canonical_evidence_sha256,
)
from yap_server.evaluation.transcript_scoring import (
    critical_token_set_sha256,
    score_transcript,
)
from yap_server.private_artifact import read_json_object_with_identity

from .transcript_correction_corpus import (
    TranscriptCorrectionQualificationCase,
    TranscriptCorrectionQualificationCorpus,
)


_MAXIMUM_ACCEPTANCE_BYTES = 32 * 1024
_TERMINAL = frozenset({"complete", "cancelled", "failed"})
_CASE_TIMEOUT_SECONDS = 65.0
_CONTAINMENT_TIMEOUT_SECONDS = 5.0
_POLL_SECONDS = 0.025


class TranscriptCorrectionQualificationService(Protocol):
    def submit(
        self,
        request: object,
        *,
        principal: AuthenticatedPrincipal,
    ) -> TranscriptCorrectionJobView: ...

    def get(
        self,
        request_id: str,
        *,
        principal: AuthenticatedPrincipal,
    ) -> TranscriptCorrectionJobView | None: ...

    def cancel(
        self,
        request_id: str,
        *,
        principal: AuthenticatedPrincipal,
    ) -> bool: ...


@dataclass(frozen=True, slots=True)
class TranscriptCorrectionAcceptance:
    plan_sha256: str
    minimum_case_count: int
    minimum_real_asr_case_count: int
    minimum_english_real_asr_case_count: int
    minimum_spanish_real_asr_case_count: int
    minimum_safety_probe_case_count: int
    minimum_corrected_case_count: int
    minimum_source_preserved_case_count: int
    minimum_uncertain_case_count: int
    minimum_unchanged_case_count: int
    minimum_owner_count: int
    concurrent_request_count: int
    maximum_p95_latency_milliseconds: int
    minimum_relative_word_error_reduction: float
    minimum_expected_disposition_rate: float
    maximum_uncertain_rate: float
    maximum_regressed_case_count: int
    maximum_insertion_increase_count: int
    maximum_deletion_increase_count: int
    maximum_critical_token_miss_increase_count: int
    maximum_terminal_failure_count: int


@dataclass(frozen=True, slots=True)
class TranscriptCorrectionCaseObservation:
    case: TranscriptCorrectionQualificationCase = field(repr=False)
    status: str
    applied: bool
    reason: str | None
    corrected_text: str = field(repr=False)
    latency_milliseconds: int
    source_word_errors: int
    corrected_word_errors: int
    source_insertions: int
    corrected_insertions: int
    source_deletions: int
    corrected_deletions: int
    source_critical_misses: int
    corrected_critical_misses: int
    expected_disposition_met: bool

    def private_evidence(self) -> dict[str, object]:
        return {
            "caseId": self.case.case_id,
            "sourceKind": self.case.source_kind,
            "sourceEvidenceSha256": self.case.source_evidence_sha256,
            "sourceEvidenceCaseId": self.case.source_evidence_case_id,
            "sourceAudioSha256": self.case.source_audio_sha256,
            "ownerId": self.case.owner_id,
            "expectedDisposition": self.case.expected_disposition,
            "expectedDispositionBasis": self.case.expected_disposition_basis,
            "status": self.status,
            "applied": self.applied,
            "reason": self.reason,
            "latencyMilliseconds": self.latency_milliseconds,
            "sourceText": self.case.request.source_text,
            "referenceText": self.case.reference_text,
            "correctedText": self.corrected_text,
            "quality": {
                "sourceWordErrors": self.source_word_errors,
                "correctedWordErrors": self.corrected_word_errors,
                "sourceInsertions": self.source_insertions,
                "correctedInsertions": self.corrected_insertions,
                "sourceDeletions": self.source_deletions,
                "correctedDeletions": self.corrected_deletions,
                "sourceCriticalMisses": self.source_critical_misses,
                "correctedCriticalMisses": self.corrected_critical_misses,
                "expectedDispositionMet": self.expected_disposition_met,
            },
        }


@dataclass(frozen=True, slots=True)
class TranscriptCorrectionQualificationResult:
    public_evidence: dict[str, object]
    private_evidence: dict[str, object] = field(repr=False)


def load_transcript_correction_acceptance(
    path: Path,
) -> TranscriptCorrectionAcceptance:
    value, identity = read_json_object_with_identity(
        path,
        maximum_bytes=_MAXIMUM_ACCEPTANCE_BYTES,
        field="transcript correction acceptance",
    )
    expected = {
        "schemaVersion",
        "qualificationScope",
        "minimumCaseCount",
        "minimumRealAsrCaseCount",
        "minimumEnglishRealAsrCaseCount",
        "minimumSpanishRealAsrCaseCount",
        "minimumSafetyProbeCaseCount",
        "minimumCorrectedCaseCount",
        "minimumSourcePreservedCaseCount",
        "minimumUncertainCaseCount",
        "minimumUnchangedCaseCount",
        "minimumOwnerCount",
        "concurrentRequestCount",
        "maximumP95LatencyMilliseconds",
        "minimumRelativeWordErrorReduction",
        "minimumExpectedDispositionRate",
        "maximumUncertainRate",
        "maximumRegressedCaseCount",
        "maximumInsertionIncreaseCount",
        "maximumDeletionIncreaseCount",
        "maximumCriticalTokenMissIncreaseCount",
        "maximumTerminalFailureCount",
    }
    if set(value) != expected:
        raise ValueError("transcript correction acceptance shape differs")
    if (
        value["schemaVersion"] != 3
        or isinstance(value["schemaVersion"], bool)
        or value["qualificationScope"] != "scribe-transcript-correction"
    ):
        raise ValueError("transcript correction acceptance identity differs")
    acceptance = TranscriptCorrectionAcceptance(
        plan_sha256=identity,
        minimum_case_count=_positive_int(value["minimumCaseCount"], "case count"),
        minimum_real_asr_case_count=_positive_int(
            value["minimumRealAsrCaseCount"], "real ASR case count"
        ),
        minimum_english_real_asr_case_count=_positive_int(
            value["minimumEnglishRealAsrCaseCount"],
            "English real ASR case count",
        ),
        minimum_spanish_real_asr_case_count=_positive_int(
            value["minimumSpanishRealAsrCaseCount"],
            "Spanish real ASR case count",
        ),
        minimum_safety_probe_case_count=_positive_int(
            value["minimumSafetyProbeCaseCount"], "safety case count"
        ),
        minimum_corrected_case_count=_positive_int(
            value["minimumCorrectedCaseCount"], "corrected case count"
        ),
        minimum_source_preserved_case_count=_positive_int(
            value["minimumSourcePreservedCaseCount"],
            "source-preserved case count",
        ),
        minimum_uncertain_case_count=_positive_int(
            value["minimumUncertainCaseCount"], "uncertain case count"
        ),
        minimum_unchanged_case_count=_positive_int(
            value["minimumUnchangedCaseCount"], "unchanged case count"
        ),
        minimum_owner_count=_positive_int(value["minimumOwnerCount"], "owner count"),
        concurrent_request_count=_positive_int(
            value["concurrentRequestCount"], "concurrency"
        ),
        maximum_p95_latency_milliseconds=_positive_int(
            value["maximumP95LatencyMilliseconds"], "p95 latency"
        ),
        minimum_relative_word_error_reduction=_rate(
            value["minimumRelativeWordErrorReduction"], "WER reduction"
        ),
        minimum_expected_disposition_rate=_rate(
            value["minimumExpectedDispositionRate"], "disposition rate"
        ),
        maximum_uncertain_rate=_rate(
            value["maximumUncertainRate"], "uncertain rate"
        ),
        maximum_regressed_case_count=_nonnegative_int(
            value["maximumRegressedCaseCount"], "regressed case count"
        ),
        maximum_insertion_increase_count=_nonnegative_int(
            value["maximumInsertionIncreaseCount"], "insertion increase count"
        ),
        maximum_deletion_increase_count=_nonnegative_int(
            value["maximumDeletionIncreaseCount"], "deletion increase count"
        ),
        maximum_critical_token_miss_increase_count=_nonnegative_int(
            value["maximumCriticalTokenMissIncreaseCount"],
            "critical-token miss increase count",
        ),
        maximum_terminal_failure_count=_nonnegative_int(
            value["maximumTerminalFailureCount"], "terminal failure count"
        ),
    )
    if (
        acceptance.concurrent_request_count > acceptance.minimum_case_count
        or acceptance.minimum_owner_count > acceptance.minimum_case_count
        or acceptance.minimum_real_asr_case_count
        + acceptance.minimum_safety_probe_case_count
        > acceptance.minimum_case_count
        or acceptance.minimum_english_real_asr_case_count
        + acceptance.minimum_spanish_real_asr_case_count
        > acceptance.minimum_real_asr_case_count
        or acceptance.minimum_corrected_case_count
        + acceptance.minimum_source_preserved_case_count
        + acceptance.minimum_uncertain_case_count
        + acceptance.minimum_unchanged_case_count
        > acceptance.minimum_case_count
    ):
        raise ValueError("transcript correction acceptance counts conflict")
    return acceptance


def evaluate_transcript_correction_qualification(
    *,
    service: TranscriptCorrectionQualificationService,
    corpus: TranscriptCorrectionQualificationCorpus,
    acceptance: TranscriptCorrectionAcceptance,
    observe_warm_state: Callable[[], Mapping[str, object]],
    observe_admission_state: Callable[[], Mapping[str, object]],
) -> TranscriptCorrectionQualificationResult:
    """Run every case through one existing warm service and score privately."""

    before = _warm_state(observe_warm_state())
    admission_before = _admission_state(observe_admission_state())
    observations: list[TranscriptCorrectionCaseObservation] = []
    wave_owner_counts: list[tuple[int, int]] = []
    for offset in range(0, len(corpus.cases), acceptance.concurrent_request_count):
        wave = corpus.cases[offset : offset + acceptance.concurrent_request_count]
        wave_owner_counts.append((len(wave), len({case.owner_id for case in wave})))
        barrier = threading.Barrier(len(wave))
        with ThreadPoolExecutor(
            max_workers=len(wave),
            thread_name_prefix="scribe-qualification",
        ) as executor:
            futures = [
                executor.submit(_run_case, service, case, barrier)
                for case in wave
            ]
            observations.extend(future.result() for future in futures)
    after = _warm_state(observe_warm_state())
    admission_after = _admission_state(observe_admission_state())
    warm_unchanged = _same_warm_generation(before, after)
    admission_unchanged = admission_before == admission_after
    metrics = _qualification_metrics(observations)
    full_wave_owner_counts = [
        owner_count
        for wave_count, owner_count in wave_owner_counts
        if wave_count == acceptance.concurrent_request_count
    ]
    all_wave_owners_distinct = all(
        wave_count == owner_count for wave_count, owner_count in wave_owner_counts
    )
    counts = {
        "caseCount": len(observations),
        "realAsrCaseCount": sum(
            item.case.source_kind == "real-asr" for item in observations
        ),
        "englishRealAsrCaseCount": sum(
            item.case.source_kind == "real-asr"
            and item.case.request.language_bcp47.split("-", 1)[0].lower() == "en"
            for item in observations
        ),
        "spanishRealAsrCaseCount": sum(
            item.case.source_kind == "real-asr"
            and item.case.request.language_bcp47.split("-", 1)[0].lower() == "es"
            for item in observations
        ),
        "safetyProbeCaseCount": sum(
            item.case.source_kind == "safety-probe" for item in observations
        ),
        "correctedCaseCount": sum(
            item.case.expected_disposition == "corrected" for item in observations
        ),
        "sourcePreservedCaseCount": sum(
            item.case.expected_disposition == "source-preserved"
            for item in observations
        ),
        "uncertainCaseCount": sum(
            item.case.expected_disposition == "uncertain" for item in observations
        ),
        "unchangedCaseCount": sum(
            item.case.expected_disposition == "unchanged" for item in observations
        ),
        "ownerCount": len({item.case.owner_id for item in observations}),
        "uniqueRealAsrAudioCount": len(
            {
                item.case.source_audio_sha256
                for item in observations
                if item.case.source_kind == "real-asr"
            }
        ),
        "maximumConcurrentOwnerCount": max(full_wave_owner_counts, default=0),
        "terminalFailureCount": int(metrics["terminalFailureCount"]),
    }
    checks = _acceptance_checks(
        counts=counts,
        metrics=metrics,
        acceptance=acceptance,
        warm_unchanged=warm_unchanged,
        admission_unchanged=admission_unchanged,
        all_wave_owners_distinct=all_wave_owners_distinct,
    )
    passed = all(checks.values())
    public = {
        "schemaVersion": 1,
        "qualificationScope": "scribe-transcript-correction",
        "outcome": (
            "scribe-transcript-correction-qualified"
            if passed
            else "deterministic-no-scribe"
        ),
        "corpusId": corpus.corpus_id,
        "corpusSha256": corpus.corpus_sha256,
        "acceptancePlanSha256": acceptance.plan_sha256,
        "counts": counts,
        "route": {
            "profileId": before["profileId"],
            "profileSha256": before["profileSha256"],
            "candidateLockSha256": before["candidateLockSha256"],
            "alreadyWarmGenerationUnchanged": warm_unchanged,
            "admissionBrokerProcessUnchanged": admission_unchanged,
            "concurrentRequestCount": acceptance.concurrent_request_count,
            "maximumConcurrentOwnerCount": counts["maximumConcurrentOwnerCount"],
            "allWaveOwnersDistinct": all_wave_owners_distinct,
        },
        "acceptance": checks,
    }
    public["evidenceSha256"] = canonical_evidence_sha256(public)
    private = {
        **public,
        "privacyScope": "private-transcript-correction-qualification",
        "measurements": metrics,
        "cases": [item.private_evidence() for item in observations],
        "warmState": {"before": dict(before), "after": dict(after)},
        "admissionState": {
            "before": dict(admission_before),
            "after": dict(admission_after),
        },
    }
    return TranscriptCorrectionQualificationResult(public, private)


def _run_case(
    service: TranscriptCorrectionQualificationService,
    case: TranscriptCorrectionQualificationCase,
    barrier: threading.Barrier,
) -> TranscriptCorrectionCaseObservation:
    principal = AuthenticatedPrincipal(
        tenant_id="scribe-qualification",
        subject_id=case.owner_id,
        client_id="scribe-qualification",
        scopes=frozenset({"knowledge.read"}),
    )
    barrier.wait(timeout=5.0)
    started = time.monotonic()
    status = "failed"
    applied = False
    reason: str | None = "submission-failed"
    corrected = case.request.source_text
    submitted: TranscriptCorrectionJobView | None = None
    try:
        submitted = service.submit(case.request, principal=principal)
        deadline = started + _CASE_TIMEOUT_SECONDS
        view = submitted
        while view.status not in _TERMINAL:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("transcript correction qualification timed out")
            time.sleep(min(_POLL_SECONDS, remaining))
            current = service.get(submitted.request_id, principal=principal)
            if current is None:
                raise RuntimeError("transcript correction result disappeared")
            view = current
        status = view.status
        applied = view.applied
        reason = view.reason
        if view.corrected_text is not None:
            corrected = view.corrected_text
    except (TranscriptCorrectionServiceError, TimeoutError, RuntimeError):
        if submitted is not None:
            _contain_submitted_case(
                service,
                submitted.request_id,
                principal=principal,
            )
            reason = "qualification-failed-contained"
    latency = round((time.monotonic() - started) * 1_000)
    critical_tokens = list(case.critical_tokens) or None
    critical_tokens_sha256 = (
        critical_token_set_sha256(critical_tokens)
        if critical_tokens is not None
        else None
    )
    source_score = score_transcript(
        case.reference_text,
        case.request.source_text,
        language_bcp47=case.request.language_bcp47,
        scoring_profile="word-primary-v1",
        critical_tokens=critical_tokens,
        critical_token_set_sha256=critical_tokens_sha256,
    )
    corrected_score = score_transcript(
        case.reference_text,
        corrected,
        language_bcp47=case.request.language_bcp47,
        scoring_profile="word-primary-v1",
        critical_tokens=critical_tokens,
        critical_token_set_sha256=critical_tokens_sha256,
    )
    return TranscriptCorrectionCaseObservation(
        case=case,
        status=status,
        applied=applied,
        reason=reason,
        corrected_text=corrected,
        latency_milliseconds=latency,
        source_word_errors=source_score.normalized_word.errors,
        corrected_word_errors=corrected_score.normalized_word.errors,
        source_insertions=source_score.normalized_word.insertions,
        corrected_insertions=corrected_score.normalized_word.insertions,
        source_deletions=source_score.normalized_word.deletions,
        corrected_deletions=corrected_score.normalized_word.deletions,
        source_critical_misses=_critical_misses(source_score),
        corrected_critical_misses=_critical_misses(corrected_score),
        expected_disposition_met=_disposition_met(
            case.expected_disposition,
            status=status,
            applied=applied,
            reason=reason,
            source=case.request.source_text,
            corrected=corrected,
            source_word_errors=source_score.normalized_word.errors,
            corrected_word_errors=corrected_score.normalized_word.errors,
        ),
    )


def _contain_submitted_case(
    service: TranscriptCorrectionQualificationService,
    request_id: str,
    *,
    principal: AuthenticatedPrincipal,
) -> None:
    """Cancel one submitted case and prove it reached a terminal state."""

    service.cancel(request_id, principal=principal)
    deadline = time.monotonic() + _CONTAINMENT_TIMEOUT_SECONDS
    while True:
        view = service.get(request_id, principal=principal)
        if view is None:
            raise RuntimeError(
                "transcript correction qualification containment lost job identity"
            )
        if view.status in _TERMINAL:
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError(
                "transcript correction qualification containment was not observed"
            )
        time.sleep(min(_POLL_SECONDS, remaining))


def _qualification_metrics(
    observations: list[TranscriptCorrectionCaseObservation],
) -> dict[str, object]:
    source_errors = sum(item.source_word_errors for item in observations)
    corrected_errors = sum(item.corrected_word_errors for item in observations)
    relative_reduction = (
        (source_errors - corrected_errors) / source_errors
        if source_errors
        else 0.0
    )
    latencies = sorted(item.latency_milliseconds for item in observations)
    p95_index = max(0, math.ceil(len(latencies) * 0.95) - 1)
    return {
        "sourceWordErrorCount": source_errors,
        "correctedWordErrorCount": corrected_errors,
        "relativeWordErrorReduction": relative_reduction,
        "expectedDispositionRate": sum(
            item.expected_disposition_met for item in observations
        )
        / len(observations),
        "uncertainRate": sum(item.reason == "uncertain" for item in observations)
        / len(observations),
        "regressedCaseCount": sum(
            item.corrected_word_errors > item.source_word_errors
            for item in observations
        ),
        "insertionIncreaseCount": sum(
            max(0, item.corrected_insertions - item.source_insertions)
            for item in observations
        ),
        "deletionIncreaseCount": sum(
            max(0, item.corrected_deletions - item.source_deletions)
            for item in observations
        ),
        "criticalTokenMissIncreaseCount": sum(
            max(0, item.corrected_critical_misses - item.source_critical_misses)
            for item in observations
        ),
        "terminalFailureCount": sum(
            item.status != "complete" for item in observations
        ),
        "p95LatencyMilliseconds": latencies[p95_index],
    }


def _acceptance_checks(
    *,
    counts: Mapping[str, int],
    metrics: Mapping[str, object],
    acceptance: TranscriptCorrectionAcceptance,
    warm_unchanged: bool,
    admission_unchanged: bool,
    all_wave_owners_distinct: bool,
) -> dict[str, bool]:
    return {
        "minimumCasesMet": counts["caseCount"] >= acceptance.minimum_case_count,
        "realAsrCoverageMet": counts["realAsrCaseCount"]
        >= acceptance.minimum_real_asr_case_count,
        "distinctRealAsrAudioMet": counts["uniqueRealAsrAudioCount"]
        >= acceptance.minimum_real_asr_case_count,
        "englishCoverageMet": counts["englishRealAsrCaseCount"]
        >= acceptance.minimum_english_real_asr_case_count,
        "spanishCoverageMet": counts["spanishRealAsrCaseCount"]
        >= acceptance.minimum_spanish_real_asr_case_count,
        "safetyCoverageMet": counts["safetyProbeCaseCount"]
        >= acceptance.minimum_safety_probe_case_count,
        "correctedCoverageMet": counts["correctedCaseCount"]
        >= acceptance.minimum_corrected_case_count,
        "sourcePreservedCoverageMet": counts["sourcePreservedCaseCount"]
        >= acceptance.minimum_source_preserved_case_count,
        "uncertainCoverageMet": counts["uncertainCaseCount"]
        >= acceptance.minimum_uncertain_case_count,
        "unchangedCoverageMet": counts["unchangedCaseCount"]
        >= acceptance.minimum_unchanged_case_count,
        "multiOwnerCoverageMet": counts["ownerCount"] >= acceptance.minimum_owner_count,
        "concurrentOwnersMet": all_wave_owners_distinct
        and counts["maximumConcurrentOwnerCount"]
        >= acceptance.concurrent_request_count,
        "warmGenerationStable": warm_unchanged,
        "admissionBrokerStable": admission_unchanged,
        "p95LatencyMet": _number(metrics["p95LatencyMilliseconds"])
        <= acceptance.maximum_p95_latency_milliseconds,
        "wordErrorBenefitMet": _number(metrics["relativeWordErrorReduction"])
        >= acceptance.minimum_relative_word_error_reduction,
        "expectedDispositionMet": _number(metrics["expectedDispositionRate"])
        >= acceptance.minimum_expected_disposition_rate,
        "uncertaintyBoundMet": _number(metrics["uncertainRate"])
        <= acceptance.maximum_uncertain_rate,
        "noRegressedCases": _measurement_count(metrics["regressedCaseCount"])
        <= acceptance.maximum_regressed_case_count,
        "noInsertionIncrease": _measurement_count(metrics["insertionIncreaseCount"])
        <= acceptance.maximum_insertion_increase_count,
        "noDeletionIncrease": _measurement_count(metrics["deletionIncreaseCount"])
        <= acceptance.maximum_deletion_increase_count,
        "criticalTokensPreserved": _measurement_count(
            metrics["criticalTokenMissIncreaseCount"]
        )
        <= acceptance.maximum_critical_token_miss_increase_count,
        "allRequestsTerminal": _measurement_count(metrics["terminalFailureCount"])
        <= acceptance.maximum_terminal_failure_count,
    }


def _warm_state(value: Mapping[str, object]) -> Mapping[str, object]:
    required = {
        "state",
        "profileId",
        "profileSha256",
        "candidateLockSha256",
        "processGeneration",
        "startCount",
        "restartCount",
    }
    if (
        not isinstance(value, Mapping)
        or not required.issubset(value)
        or value["state"] != "ready"
    ):
        raise ValueError("transcript correction provider is not already warm")
    for field_name in ("processGeneration", "startCount", "restartCount"):
        field_value = value[field_name]
        if isinstance(field_value, bool) or not isinstance(field_value, int) or field_value < 0:
            raise ValueError("transcript correction provider state is invalid")
    if value["processGeneration"] < 1:
        raise ValueError("transcript correction provider generation is invalid")
    for field_name in ("profileId", "profileSha256", "candidateLockSha256"):
        if not isinstance(value[field_name], str) or not value[field_name]:
            raise ValueError("transcript correction provider identity is invalid")
    return value


def _same_warm_generation(
    before: Mapping[str, object], after: Mapping[str, object]
) -> bool:
    fields = (
        "profileId",
        "profileSha256",
        "candidateLockSha256",
        "processGeneration",
        "startCount",
        "restartCount",
    )
    return all(before[field_name] == after[field_name] for field_name in fields)


def _admission_state(value: Mapping[str, object]) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != {
        "processId",
        "processStartTicks",
        "binarySha256",
        "socketDevice",
        "socketInode",
    }:
        raise ValueError("transcript correction admission state is invalid")
    for field_name in (
        "processId",
        "processStartTicks",
        "socketDevice",
        "socketInode",
    ):
        field_value = value[field_name]
        if (
            isinstance(field_value, bool)
            or not isinstance(field_value, int)
            or field_value < 1
        ):
            raise ValueError("transcript correction admission state is invalid")
    digest = value["binarySha256"]
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise ValueError("transcript correction admission state is invalid")
    return value


def _critical_misses(score: object) -> int:
    critical = getattr(score, "critical_tokens")
    return 0 if critical is None else int(critical.missed_occurrences)


def _disposition_met(
    expected: str,
    *,
    status: str,
    applied: bool,
    reason: str | None,
    source: str,
    corrected: str,
    source_word_errors: int,
    corrected_word_errors: int,
) -> bool:
    if status != "complete":
        return False
    if expected == "corrected":
        return (
            applied
            and corrected != source
            and corrected_word_errors < source_word_errors
        )
    if expected == "source-preserved":
        return (
            not applied
            and reason in {"unchanged", "uncertain"}
            and corrected == source
        )
    if expected == "uncertain":
        return not applied and reason == "uncertain" and corrected == source
    return not applied and reason == "unchanged" and corrected == source


def _positive_int(value: object, field_name: str) -> int:
    result = _nonnegative_int(value, field_name)
    if result < 1:
        raise ValueError(f"transcript correction {field_name} must be positive")
    return result


def _nonnegative_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"transcript correction {field_name} is invalid")
    return value


def _rate(value: object, field_name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0 <= value <= 1
    ):
        raise ValueError(f"transcript correction {field_name} is invalid")
    return float(value)


def _number(value: object) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise RuntimeError("transcript correction measurement is invalid")
    return float(value)


def _measurement_count(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RuntimeError("transcript correction count measurement is invalid")
    return value


__all__ = [
    "TranscriptCorrectionAcceptance",
    "TranscriptCorrectionCaseObservation",
    "TranscriptCorrectionQualificationResult",
    "TranscriptCorrectionQualificationService",
    "evaluate_transcript_correction_qualification",
    "load_transcript_correction_acceptance",
]
