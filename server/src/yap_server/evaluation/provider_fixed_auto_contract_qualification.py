from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Mapping

from yap_server.evaluation.checked_candidate import (
    admit_checked_candidate,
    bind_checked_candidate_evidence,
)
from yap_server.evaluation.duration_tracks import LoadedDurationTrack
from yap_server.evaluation.provider_qualification_requests import (
    LockedProviderRequestFactory,
)
from yap_server.evaluation.provider_duration_suite import (
    bind_provider_load_case_tracks,
    load_provider_load_case_tracks,
    verify_provider_load_case_tracks_unchanged,
)
from yap_server.evaluation.provider_runtime_observations import (
    QualificationRequest,
    canonical_evidence_sha256,
    run_bounded_load,
    summarize_runtime_load,
)
from yap_server.evaluation.provider_runtime_qualification import (
    QualificationRequestFactory,
    ResidentQualificationWorker,
    build_resident_worker,
    resident_provider_configuration,
    validate_exact_tracks,
    validate_resident_provider_lock,
    write_private_evidence,
)
from yap_server.evaluation.runtime_plan import (
    RuntimeLoadCase,
    load_runtime_evaluation_plan,
    select_runtime_load_case,
)
from yap_server.evaluation.transcript_equivalence import (
    transcripts_match_lexically,
)
from yap_server.language_span_contract import validate_language_span_evidence
from yap_server.limits import MAX_WORKER_RESULT_BYTES
from yap_server.pools.model_lock import ModelPoolLock, load_model_pool_lock


_LOAD_CASE_ID = "nemo-finalized-fixed-auto-contract"
_EXPECTED = "fixed-and-auto-language-contract"
_QUALIFICATION_SCOPE = "request-lifecycle"
_DURATION_SAMPLES = 480_000
_REQUESTS_PER_MODE = 8


@dataclass(frozen=True, slots=True)
class ProviderFixedAutoContractQualification:
    load_case: RuntimeLoadCase
    runs: tuple[Mapping[str, object], ...]

    @property
    def passed(self) -> bool:
        return bool(self.runs) and all(run.get("passed") is True for run in self.runs)

    def public_evidence(self) -> dict[str, object]:
        evidence: dict[str, object] = {
            "schemaVersion": 1,
            "loadCaseId": self.load_case.identifier,
            "systemId": self.load_case.system_id,
            "measurementBoundary": self.load_case.measurement_boundary,
            "qualificationScope": _QUALIFICATION_SCOPE,
            "expected": self.load_case.expected,
            "minimumCompletions": self.load_case.minimum_completions,
            "passed": self.passed,
            "runs": list(self.runs),
        }
        evidence["evidenceSha256"] = canonical_evidence_sha256(evidence)
        return evidence


def run_provider_fixed_auto_contract_case(
    worker: ResidentQualificationWorker,
    fixed_factory: QualificationRequestFactory,
    automatic_factory: QualificationRequestFactory,
    plan: Mapping[str, object],
    *,
    load_case_id: str,
    fixed_provider_language: str,
    lock: ModelPoolLock,
    timeout_seconds_per_wave: float,
) -> ProviderFixedAutoContractQualification:
    """Compare the same source through fixed and automatic NeMo contracts."""

    if timeout_seconds_per_wave <= 0 or fixed_provider_language == "auto":
        raise ValueError("provider fixed/automatic contract inputs are invalid")
    load_case = select_runtime_load_case(plan, load_case_id)
    _validate_contract_case(load_case)
    runs: list[Mapping[str, object]] = []
    for concurrency in load_case.concurrencies:
        fixed_requests = _create_requests(
            fixed_factory,
            load_case,
            concurrency=concurrency,
        )
        automatic_requests = _create_requests(
            automatic_factory,
            load_case,
            concurrency=concurrency,
        )
        fixed_load = run_bounded_load(
            worker,
            fixed_requests,
            concurrency=concurrency,
            timeout_seconds_per_wave=timeout_seconds_per_wave,
        )
        automatic_load = run_bounded_load(
            worker,
            automatic_requests,
            concurrency=concurrency,
            timeout_seconds_per_wave=timeout_seconds_per_wave,
        )
        fixed_summary = summarize_runtime_load(fixed_load)
        automatic_summary = summarize_runtime_load(automatic_load)
        fixed_results = tuple(_read_result(request) for request in fixed_requests)
        automatic_results = tuple(
            _read_result(request) for request in automatic_requests
        )
        exact_text_parity_count = 0
        lexical_parity_count = 0
        contract_conformance_count = 0
        for fixed_request, automatic_request, fixed_result, automatic_result in zip(
            fixed_requests,
            automatic_requests,
            fixed_results,
            automatic_results,
            strict=True,
        ):
            fixed_text = _transcript_text(fixed_result)
            automatic_text = _transcript_text(automatic_result)
            if fixed_text is not None and fixed_text == automatic_text:
                exact_text_parity_count += 1
            if transcripts_match_lexically(fixed_text, automatic_text):
                lexical_parity_count += 1
            if _language_contracts_conform(
                fixed_result,
                automatic_result,
                fixed_request=fixed_request,
                automatic_request=automatic_request,
                fixed_provider_language=fixed_provider_language,
                lock=lock,
            ):
                contract_conformance_count += 1
        fixed_complete = _all_completed(fixed_summary, _REQUESTS_PER_MODE)
        automatic_complete = _all_completed(
            automatic_summary,
            _REQUESTS_PER_MODE,
        )
        minimum_completions_met = (
            fixed_summary["outcomes"]["completed"]  # type: ignore[index]
            >= load_case.minimum_completions
            and automatic_summary["outcomes"]["completed"]  # type: ignore[index]
            >= load_case.minimum_completions
        )
        passed = (
            fixed_complete
            and automatic_complete
            and contract_conformance_count == _REQUESTS_PER_MODE
            and minimum_completions_met
        )
        runs.append(
            {
                "concurrency": concurrency,
                "fixed": fixed_summary,
                "automatic": automatic_summary,
                "exactTextParityCount": exact_text_parity_count,
                "lexicalParityCount": lexical_parity_count,
                "lexicalParityRequired": False,
                "languageContractConformanceCount": contract_conformance_count,
                "minimumCompletionsMet": minimum_completions_met,
                "passed": passed,
            }
        )
    return ProviderFixedAutoContractQualification(
        load_case=load_case,
        runs=tuple(runs),
    )


def run_resident_provider_fixed_auto_contract_case(
    *,
    plan_path: Path,
    load_case_id: str,
    model_lock_path: Path,
    tracks: Mapping[int, LoadedDurationTrack],
    endpoint: str,
    fixed_catalog_language: str,
    fixed_provider_language: str,
    automatic_catalog_language: str,
    output_root: Path,
    timeout_seconds_per_wave: float,
    environ: Mapping[str, str] = os.environ,
) -> ProviderFixedAutoContractQualification:
    """Compose the fixed/automatic contract gate from one locked private track."""

    plan = load_runtime_evaluation_plan(plan_path)
    load_case = select_runtime_load_case(plan, load_case_id)
    _validate_contract_case(load_case)
    provider_id, api_key_environment = resident_provider_configuration(
        load_case.system_id
    )
    api_key = environ.get(api_key_environment, "")
    if not api_key:
        raise ValueError(f"{api_key_environment} is required for qualification")
    exact_tracks = validate_exact_tracks(tracks)
    if set(exact_tracks) != {_DURATION_SAMPLES}:
        raise ValueError("duration tracks differ from the contract load case")
    lock = load_model_pool_lock(model_lock_path)
    validate_resident_provider_lock(load_case.system_id, lock)
    worker = build_resident_worker(
        system_id=load_case.system_id,
        endpoint=endpoint,
        api_key=api_key,
        timeout_seconds=timeout_seconds_per_wave,
        lock=lock,
    )
    try:
        worker.verify_ready()
        fixed_factory = LockedProviderRequestFactory(
            system_id=load_case.system_id,
            provider_id=provider_id,
            catalog_language=fixed_catalog_language,
            provider_language=fixed_provider_language,
            lock=lock,
            tracks=exact_tracks,
            output_root=output_root,
            environ=environ,
        )
        automatic_factory = LockedProviderRequestFactory(
            system_id=load_case.system_id,
            provider_id=provider_id,
            catalog_language=automatic_catalog_language,
            provider_language="auto",
            lock=lock,
            tracks=exact_tracks,
            output_root=output_root / "automatic",
            environ=environ,
        )
        return run_provider_fixed_auto_contract_case(
            worker,
            fixed_factory,
            automatic_factory,
            plan,
            load_case_id=load_case_id,
            fixed_provider_language=fixed_provider_language,
            lock=lock,
            timeout_seconds_per_wave=timeout_seconds_per_wave,
        )
    finally:
        worker.close()


def _validate_contract_case(load_case: RuntimeLoadCase) -> None:
    if (
        load_case.identifier != _LOAD_CASE_ID
        or load_case.system_id != "nemo-nemotron-finalized"
        or load_case.measurement_boundary
        != "checked-contract-to-resident-result"
        or load_case.expected != _EXPECTED
        or len(load_case.mix) != 1
        or load_case.mix[0].duration_samples != _DURATION_SAMPLES
        or load_case.mix[0].count != _REQUESTS_PER_MODE
        or load_case.concurrencies != (1, 8)
        or load_case.minimum_completions != _REQUESTS_PER_MODE
    ):
        raise ValueError(
            "runtime load case is not a NeMo fixed/automatic contract scenario"
        )


def _create_requests(
    factory: QualificationRequestFactory,
    load_case: RuntimeLoadCase,
    *,
    concurrency: int,
) -> tuple[QualificationRequest, ...]:
    requests = tuple(
        factory.create(
            load_case_id=load_case.identifier,
            concurrency=concurrency,
            ordinal=ordinal,
            duration_samples=_DURATION_SAMPLES,
        )
        for ordinal in range(_REQUESTS_PER_MODE)
    )
    if any(request.audio_samples != _DURATION_SAMPLES for request in requests):
        raise ValueError("language contract request differs from the runtime plan")
    return requests


def _read_result(request: QualificationRequest) -> Mapping[str, object] | None:
    try:
        body = request.job.result_path.read_bytes()
    except OSError:
        return None
    if not body or len(body) > MAX_WORKER_RESULT_BYTES:
        return None
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _language_contracts_conform(
    fixed_result: Mapping[str, object] | None,
    automatic_result: Mapping[str, object] | None,
    *,
    fixed_request: QualificationRequest,
    automatic_request: QualificationRequest,
    fixed_provider_language: str,
    lock: ModelPoolLock,
) -> bool:
    if fixed_result is None or automatic_result is None:
        return False
    expected_model = {
        "poolId": lock.pool_id,
        "id": lock.model_id,
        "revision": lock.model_revision,
    }
    fixed_transcript = fixed_result.get("transcript")
    automatic_transcript = automatic_result.get("transcript")
    fixed_text = _transcript_text(fixed_result)
    automatic_text = _transcript_text(automatic_result)
    if (
        fixed_result.get("jobId") != fixed_request.job.job_id
        or automatic_result.get("jobId") != automatic_request.job.job_id
        or fixed_result.get("model") != expected_model
        or automatic_result.get("model") != expected_model
        or not _audio_matches(fixed_result.get("audio"), fixed_request)
        or not _audio_matches(automatic_result.get("audio"), automatic_request)
        or not isinstance(fixed_transcript, dict)
        or fixed_text is None
        or set(fixed_transcript) != {"text", "language", "punctuation"}
        or fixed_transcript.get("language") != fixed_provider_language
        or fixed_transcript.get("punctuation") is not True
        or not isinstance(automatic_transcript, dict)
        or automatic_text is None
        or set(automatic_transcript)
        != {
            "text",
            "language",
            "punctuation",
            "languageSegments",
            "languageSpanEvidence",
        }
        or automatic_transcript.get("language") != "auto"
        or automatic_transcript.get("punctuation") is not True
        or fixed_result.get("audio") != automatic_result.get("audio")
    ):
        return False
    segments = automatic_transcript.get("languageSegments")
    if not isinstance(segments, list) or not segments:
        return False
    if any(
        not isinstance(segment, dict)
        or segment.get("status") != "detected"
        or segment.get("languageBcp47") != fixed_provider_language
        for segment in segments
    ):
        return False
    plan_sha256 = automatic_request.job.utterance_plan_sha256
    if plan_sha256 is None:
        return False
    try:
        evidence = validate_language_span_evidence(
            automatic_transcript.get("languageSpanEvidence"),
            expected_source_end_sample=automatic_request.audio_samples,
            expected_provider_id=automatic_request.job.route.provider_id,
            expected_pool_id=lock.pool_id,
            expected_model_id=lock.model_id,
            expected_model_revision=lock.model_revision,
            expected_utterance_plan_sha256=plan_sha256,
        )
    except ValueError:
        return False
    spans = evidence.get("spans")
    return isinstance(spans, list) and all(
        isinstance(span, dict)
        and span.get("languageBcp47") == fixed_provider_language
        and span.get("disposition") == "serverDetected"
        for span in spans
    )


def _transcript_text(result: Mapping[str, object] | None) -> str | None:
    transcript = result.get("transcript") if isinstance(result, Mapping) else None
    text = transcript.get("text") if isinstance(transcript, dict) else None
    return text if isinstance(text, str) and text.strip() else None


def _audio_matches(value: object, request: QualificationRequest) -> bool:
    return value == {
        "sha256": request.job.input_sha256,
        "durationMs": round(request.audio_samples * 1_000 / 16_000),
        "sampleRateHz": 16_000,
    }


def _all_completed(summary: Mapping[str, object], request_count: int) -> bool:
    outcomes = summary.get("outcomes")
    return (
        isinstance(outcomes, Mapping)
        and outcomes.get("completed") == request_count
        and outcomes.get("cancelled") == 0
        and outcomes.get("busy") == 0
        and outcomes.get("failed") == 0
        and summary.get("resultPublishedCount") == request_count
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run private resident-NeMo fixed/automatic contract qualification",
    )
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--checked-head", required=True)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--load-case", required=True)
    parser.add_argument("--model-lock", type=Path, required=True)
    parser.add_argument("--duration-suite", type=Path, required=True)
    parser.add_argument("--duration-suite-sha256", required=True)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--fixed-catalog-language", required=True)
    parser.add_argument("--fixed-provider-language", required=True)
    parser.add_argument("--automatic-catalog-language", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--timeout-seconds-per-wave", type=float, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    plan_path = arguments.plan.resolve(strict=True)
    model_lock_path = arguments.model_lock.resolve(strict=True)
    candidate = admit_checked_candidate(
        repository_root=arguments.repository_root,
        checked_head=arguments.checked_head,
        input_paths=(plan_path, model_lock_path),
    )
    duration_tracks = load_provider_load_case_tracks(
        suite_path=arguments.duration_suite,
        expected_suite_sha256=arguments.duration_suite_sha256,
        plan_path=plan_path,
        load_case_id=arguments.load_case,
    )
    qualification = run_resident_provider_fixed_auto_contract_case(
        plan_path=plan_path,
        load_case_id=arguments.load_case,
        model_lock_path=model_lock_path,
        tracks=duration_tracks.indexed_tracks(),
        endpoint=arguments.endpoint,
        fixed_catalog_language=arguments.fixed_catalog_language,
        fixed_provider_language=arguments.fixed_provider_language,
        automatic_catalog_language=arguments.automatic_catalog_language,
        output_root=arguments.output_root,
        timeout_seconds_per_wave=arguments.timeout_seconds_per_wave,
    )
    verify_provider_load_case_tracks_unchanged(
        duration_tracks,
        plan_path=plan_path,
    )
    candidate.verify_unchanged()
    evidence = bind_checked_candidate_evidence(
        bind_provider_load_case_tracks(
            qualification.public_evidence(),
            duration_tracks,
        ),
        candidate,
    )
    write_private_evidence(arguments.output_root / "evidence.json", evidence)
    print(json.dumps(evidence, ensure_ascii=True, separators=(",", ":"), sort_keys=True))
    return 0 if qualification.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
