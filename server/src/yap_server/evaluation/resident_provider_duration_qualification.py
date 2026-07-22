"""Exact-duration qualification for resident vLLM and NeMo ASR providers."""

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
from yap_server.evaluation.provider_duration_suite import (
    bind_provider_duration_suite,
    load_provider_duration_suite,
    verify_provider_duration_suite_unchanged,
)
from yap_server.evaluation.provider_qualification_requests import (
    LockedProviderRequestFactory,
)
from yap_server.evaluation.provider_runtime_observations import (
    QualificationRequest,
    canonical_evidence_sha256,
    run_bounded_load,
    summarize_runtime_load,
)
from yap_server.evaluation.provider_runtime_qualification import (
    ProviderMetricsObserver,
    QualificationRequestFactory,
    ResidentQualificationWorker,
    build_resident_worker,
    resident_metrics_observer,
    resident_provider_configuration,
    standard_provider_expectation_met,
    validate_exact_tracks,
    validate_resident_provider_lock,
    write_private_evidence,
)
from yap_server.evaluation.runtime_plan import (
    load_runtime_evaluation_plan,
    validate_runtime_evaluation_plan,
)
from yap_server.pools.model_lock import load_model_pool_lock


_RESIDENT_SYSTEM_IDS = frozenset(
    {
        "vllm-cohere-batch",
        "nemo-nemotron-finalized",
    }
)
_BATCH_LADDER_ID = "batch-file"
_EXACT_MAXIMUM_BOUNDARY_ID = "batch-maximum-exact"


@dataclass(frozen=True, slots=True)
class ProviderDurationPlan:
    system_id: str
    ladder_id: str
    measurement_boundary: str
    pacing: str
    source_evidence_kind: str
    duration_samples: tuple[int, ...]
    exact_maximum_included: bool


@dataclass(frozen=True, slots=True)
class ProviderDurationQualification:
    plan: ProviderDurationPlan
    runs: tuple[dict[str, object], ...]

    @property
    def passed(self) -> bool:
        return bool(self.runs) and all(
            run.get("expectationMet") is True for run in self.runs
        )

    def public_evidence(self) -> dict[str, object]:
        completed_request_count = 0
        for run in self.runs:
            outcomes = run.get("outcomes")
            completed = outcomes.get("completed") if isinstance(outcomes, Mapping) else 0
            if isinstance(completed, int) and not isinstance(completed, bool):
                completed_request_count += completed
        evidence: dict[str, object] = {
            "schemaVersion": 1,
            "systemId": self.plan.system_id,
            "durationLadderId": self.plan.ladder_id,
            "measurementBoundary": self.plan.measurement_boundary,
            "pacing": self.plan.pacing,
            "sourceEvidenceKind": self.plan.source_evidence_kind,
            "qualificationScope": "duration-transport-and-lifecycle",
            "representativeAccuracyClaim": False,
            "selectedDurationSamples": list(self.plan.duration_samples),
            "exactMaximumIncluded": self.plan.exact_maximum_included,
            "completedRequestCount": completed_request_count,
            "passed": self.passed,
            "runs": list(self.runs),
        }
        evidence["evidenceSha256"] = canonical_evidence_sha256(evidence)
        return evidence


def select_provider_duration_plan(
    plan: Mapping[str, object],
    *,
    system_id: str,
    ladder_id: str,
    include_exact_maximum: bool,
) -> ProviderDurationPlan:
    """Select one unpaced plan ladder for one resident provider."""

    validate_runtime_evaluation_plan(plan)
    if system_id not in _RESIDENT_SYSTEM_IDS:
        raise ValueError("duration qualification requires a resident provider")
    systems = plan["systems"]
    if not isinstance(systems, list):
        raise RuntimeError("validated runtime systems changed shape")
    system = next(
        (
            item
            for item in systems
            if isinstance(item, Mapping) and item.get("id") == system_id
        ),
        None,
    )
    ladders = plan["durationLadders"]
    if not isinstance(ladders, list):
        raise RuntimeError("validated duration ladders changed shape")
    ladder = next(
        (
            item
            for item in ladders
            if isinstance(item, Mapping) and item.get("id") == ladder_id
        ),
        None,
    )
    if system is None or ladder is None:
        raise ValueError("provider duration plan identity is unknown")
    system_ids = ladder["systemIds"]
    if not isinstance(system_ids, list) or system_id not in system_ids:
        raise ValueError("duration ladder does not include the resident provider")
    if ladder["pacing"] != "unpaced":
        raise ValueError("resident provider duration qualification requires unpaced audio")
    durations = tuple(
        _positive_int(value, "duration ladder")
        for value in ladder["durationSamples"]
    )
    if include_exact_maximum:
        if ladder_id != _BATCH_LADDER_ID:
            raise ValueError("exact maximum requires the batch ladder")
        exact_maximum = _exact_maximum_samples(plan)
        if exact_maximum not in durations:
            durations = (*durations, exact_maximum)
    measurement_boundary = system["measurementBoundary"]
    source_evidence_kind = ladder["evidenceKind"]
    if not isinstance(measurement_boundary, str) or not isinstance(
        source_evidence_kind,
        str,
    ):
        raise RuntimeError("validated provider duration metadata changed shape")
    return ProviderDurationPlan(
        system_id=system_id,
        ladder_id=ladder_id,
        measurement_boundary=measurement_boundary,
        pacing="unpaced",
        source_evidence_kind=source_evidence_kind,
        duration_samples=durations,
        exact_maximum_included=include_exact_maximum,
    )


def run_provider_duration_plan(
    worker: ResidentQualificationWorker,
    request_factory: QualificationRequestFactory,
    plan: ProviderDurationPlan,
    *,
    timeout_seconds_per_duration: float,
    metrics_observer: ProviderMetricsObserver | None = None,
) -> ProviderDurationQualification:
    """Execute each selected exact duration once without publishing content."""

    if timeout_seconds_per_duration <= 0:
        raise ValueError("provider duration timeout must be positive")
    runs: list[dict[str, object]] = []
    for ordinal, duration_samples in enumerate(plan.duration_samples):
        request: QualificationRequest = request_factory.create(
            load_case_id=f"{plan.ladder_id}-duration",
            concurrency=1,
            ordinal=ordinal,
            duration_samples=duration_samples,
        )
        if request.audio_samples != duration_samples:
            raise ValueError("duration qualification request differs from the plan")
        metrics_token = (
            metrics_observer.before_run(concurrency=1)
            if metrics_observer is not None
            else None
        )
        load = run_bounded_load(
            worker,
            (request,),
            concurrency=1,
            timeout_seconds_per_wave=timeout_seconds_per_duration,
        )
        summary = summarize_runtime_load(load)
        outcomes = summary.get("outcomes")
        completed = outcomes.get("completed") if isinstance(outcomes, Mapping) else 0
        if metrics_observer is not None:
            summary["providerMetrics"] = metrics_observer.after_run(
                metrics_token,
                completed_requests=(
                    completed
                    if isinstance(completed, int) and not isinstance(completed, bool)
                    else 0
                ),
                maximum_audio_samples=duration_samples,
            )
        summary["durationSamples"] = duration_samples
        summary["expectationMet"] = standard_provider_expectation_met(
            summary,
            request_count=1,
        )
        runs.append(summary)
    return ProviderDurationQualification(plan=plan, runs=tuple(runs))


def run_resident_provider_duration_plan(
    *,
    selected_plan: ProviderDurationPlan,
    model_lock_path: Path,
    tracks: Mapping[int, LoadedDurationTrack],
    endpoint: str,
    catalog_language: str,
    provider_language: str,
    output_root: Path,
    timeout_seconds_per_duration: float,
    environ: Mapping[str, str] = os.environ,
) -> ProviderDurationQualification:
    """Compose exact-duration qualification through one resident provider."""

    exact_tracks = validate_exact_tracks(tracks)
    if set(exact_tracks) != set(selected_plan.duration_samples):
        raise ValueError("duration tracks differ from the selected duration plan")
    provider_id, api_key_environment = resident_provider_configuration(
        selected_plan.system_id
    )
    api_key = environ.get(api_key_environment, "")
    if not api_key:
        raise ValueError(f"{api_key_environment} is required for qualification")
    lock = load_model_pool_lock(model_lock_path)
    validate_resident_provider_lock(selected_plan.system_id, lock)
    worker = build_resident_worker(
        system_id=selected_plan.system_id,
        endpoint=endpoint,
        api_key=api_key,
        timeout_seconds=timeout_seconds_per_duration,
        lock=lock,
    )
    metrics_observer = resident_metrics_observer(
        system_id=selected_plan.system_id,
        endpoint=endpoint,
    )
    try:
        worker.verify_ready()
        request_factory = LockedProviderRequestFactory(
            system_id=selected_plan.system_id,
            provider_id=provider_id,
            catalog_language=catalog_language,
            provider_language=provider_language,
            lock=lock,
            tracks=exact_tracks,
            output_root=output_root,
            environ=environ,
        )
        return run_provider_duration_plan(
            worker,
            request_factory,
            selected_plan,
            timeout_seconds_per_duration=timeout_seconds_per_duration,
            metrics_observer=metrics_observer,
        )
    finally:
        worker.close()


def _exact_maximum_samples(plan: Mapping[str, object]) -> int:
    boundaries = plan["boundaryCases"]
    if not isinstance(boundaries, list):
        raise RuntimeError("validated boundary cases changed shape")
    boundary = next(
        (
            item
            for item in boundaries
            if isinstance(item, Mapping)
            and item.get("id") == _EXACT_MAXIMUM_BOUNDARY_ID
        ),
        None,
    )
    if boundary is None:
        raise RuntimeError("validated exact maximum boundary disappeared")
    values = boundary["values"]
    if not isinstance(values, list) or len(values) != 1:
        raise RuntimeError("validated exact maximum boundary changed shape")
    return _positive_int(values[0], "exact maximum")


def _positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise RuntimeError(f"validated {field} changed shape")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one checked resident-provider exact-duration plan",
    )
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--checked-head", required=True)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--system-id", required=True)
    parser.add_argument("--duration-ladder", required=True)
    parser.add_argument("--include-exact-maximum", action="store_true")
    parser.add_argument("--model-lock", type=Path, required=True)
    parser.add_argument("--duration-suite", type=Path, required=True)
    parser.add_argument("--duration-suite-sha256", required=True)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--catalog-language", required=True)
    parser.add_argument("--provider-language", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--timeout-seconds-per-duration", type=float, required=True)
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
    selected_plan = select_provider_duration_plan(
        load_runtime_evaluation_plan(plan_path),
        system_id=arguments.system_id,
        ladder_id=arguments.duration_ladder,
        include_exact_maximum=arguments.include_exact_maximum,
    )
    suite = load_provider_duration_suite(
        suite_path=arguments.duration_suite,
        expected_sha256=arguments.duration_suite_sha256,
        plan_path=plan_path,
        required_duration_samples=selected_plan.duration_samples,
    )
    qualification = run_resident_provider_duration_plan(
        selected_plan=selected_plan,
        model_lock_path=model_lock_path,
        tracks=suite.indexed_tracks_for(selected_plan.duration_samples),
        endpoint=arguments.endpoint,
        catalog_language=arguments.catalog_language,
        provider_language=arguments.provider_language,
        output_root=arguments.output_root,
        timeout_seconds_per_duration=arguments.timeout_seconds_per_duration,
    )
    verify_provider_duration_suite_unchanged(
        suite,
        duration_samples=selected_plan.duration_samples,
        plan_path=plan_path,
    )
    candidate.verify_unchanged()
    evidence = bind_checked_candidate_evidence(
        bind_provider_duration_suite(
            qualification.public_evidence(),
            suite=suite,
            duration_samples=selected_plan.duration_samples,
        ),
        candidate,
    )
    write_private_evidence(arguments.output_root / "evidence.json", evidence)
    print(json.dumps(evidence, ensure_ascii=True, separators=(",", ":"), sort_keys=True))
    return 0 if qualification.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
