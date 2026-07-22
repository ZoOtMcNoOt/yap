from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Mapping, Protocol

from yap_server.evaluation.checked_candidate import (
    admit_checked_candidate,
    bind_checked_candidate_evidence,
)
from yap_server.evaluation.duration_tracks import LoadedDurationTrack
from yap_server.evaluation.provider_duration_suite import (
    bind_provider_load_case_tracks,
    load_provider_load_case_tracks,
    verify_provider_load_case_tracks_unchanged,
)
from yap_server.evaluation.provider_qualification_requests import (
    LockedProviderRequestFactory,
)
from yap_server.evaluation.provider_runtime_observations import (
    QualificationRequest,
    QualificationWorker,
    canonical_evidence_sha256,
    run_bounded_load,
    summarize_runtime_load,
)
from yap_server.evaluation.runtime_plan import (
    RuntimeLoadCase,
    load_runtime_evaluation_plan,
    select_runtime_load_case,
)
from yap_server.evaluation.vllm_runtime_metrics import (
    VllmMetricsSnapshot,
    VllmRuntimeMetricsClient,
)
from yap_server.pools.model_lock import ModelPoolLock, load_model_pool_lock


_STANDARD_EXPECTATIONS = frozenset(
    {
        "complete",
        "complete-source-plan-continuity",
    }
)
_RESIDENT_PROVIDER_IDS = {
    "vllm-cohere-batch": "cohere",
    "nemo-nemotron-finalized": "nemotron",
}
_RESIDENT_API_KEY_ENVIRONMENTS = {
    "vllm-cohere-batch": "YAP_COHERE_VLLM_API_KEY",
    "nemo-nemotron-finalized": "YAP_NEMOTRON_NEMO_API_KEY",
}
_RESIDENT_LOCK_BOUNDARIES = {
    "vllm-cohere-batch": ("cohere-batch", "vllm", "nvcr.io/nvidia/vllm"),
    "nemo-nemotron-finalized": (
        "nemotron-batch",
        "nemo",
        "nvcr.io/nvidia/pytorch",
    ),
}


class QualificationRequestFactory(Protocol):
    def create(
        self,
        *,
        load_case_id: str,
        concurrency: int,
        ordinal: int,
        duration_samples: int,
    ) -> QualificationRequest: ...


class ResidentQualificationWorker(QualificationWorker, Protocol):
    def verify_ready(self) -> None: ...

    def close(self) -> None: ...


class ProviderMetricsObserver(Protocol):
    def before_run(self, *, concurrency: int) -> object: ...

    def after_run(
        self,
        token: object,
        *,
        completed_requests: int,
        maximum_audio_samples: int,
    ) -> dict[str, object]: ...


class VllmQualificationMetricsObserver:
    def __init__(self, client: VllmRuntimeMetricsClient) -> None:
        self._client = client

    def before_run(self, *, concurrency: int) -> VllmMetricsSnapshot:
        if concurrency < 1:
            raise ValueError("vLLM qualification concurrency is invalid")
        snapshot = self._client.snapshot()
        if snapshot.running_requests or snapshot.waiting_requests:
            raise RuntimeError("vLLM qualification did not start from an idle engine")
        return snapshot

    def after_run(
        self,
        token: object,
        *,
        completed_requests: int,
        maximum_audio_samples: int,
    ) -> dict[str, object]:
        if not isinstance(token, VllmMetricsSnapshot):
            raise TypeError("vLLM qualification metric token is invalid")
        after = self._client.snapshot()
        delta = after.delta(token)
        histogram_counts = {
            histogram.count for histogram in delta.histograms.values()
        }
        engine_request_count_acceptable = (
            completed_requests > 0
            and delta.successful_requests >= completed_requests
            and histogram_counts == {delta.successful_requests}
            and (
                maximum_audio_samples > 480_000
                or delta.successful_requests == completed_requests
            )
        )
        return {
            "idleAfter": not after.running_requests and not after.waiting_requests,
            "metricUnit": "vllm-engine-request",
            "completedApiRequests": completed_requests,
            "engineRequestCountAcceptable": engine_request_count_acceptable,
            "engineRequestsPerCompletedApiRequest": (
                round(delta.successful_requests / completed_requests, 6)
                if completed_requests
                else None
            ),
            **delta.public_evidence(),
        }


@dataclass(frozen=True, slots=True)
class ProviderLoadQualification:
    load_case: RuntimeLoadCase
    selected_concurrencies: tuple[int, ...]
    repeat_count: int
    runs: tuple[dict[str, object], ...]

    @property
    def passed(self) -> bool:
        return bool(self.runs) and all(
            run.get("minimumCompletionsMet") is True
            and run.get("expectationMet") is True
            for run in self.runs
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
            "loadCaseId": self.load_case.identifier,
            "systemId": self.load_case.system_id,
            "measurementBoundary": self.load_case.measurement_boundary,
            "expected": self.load_case.expected,
            "minimumCompletions": self.load_case.minimum_completions,
            "selectedConcurrencies": list(self.selected_concurrencies),
            "repeatCount": self.repeat_count,
            "completedRequestCount": completed_request_count,
            "passed": self.passed,
            "runs": list(self.runs),
        }
        evidence["evidenceSha256"] = canonical_evidence_sha256(evidence)
        return evidence


def run_provider_load_case(
    worker: QualificationWorker,
    request_factory: QualificationRequestFactory,
    plan: Mapping[str, object],
    *,
    load_case_id: str,
    timeout_seconds_per_wave: float,
    selected_concurrencies: tuple[int, ...] | None = None,
    repeat_count: int = 1,
    metrics_observer: ProviderMetricsObserver | None = None,
) -> ProviderLoadQualification:
    """Execute one plan cell while keeping paths and transcript identity private."""

    load_case = select_runtime_load_case(plan, load_case_id)
    if load_case.expected not in _STANDARD_EXPECTATIONS:
        raise ValueError(
            "runtime load case requires its specialized qualification runner"
        )
    concurrencies = _selected_concurrencies(load_case, selected_concurrencies)
    if (
        isinstance(repeat_count, bool)
        or not isinstance(repeat_count, int)
        or not 1 <= repeat_count <= 32
    ):
        raise ValueError("provider load repetition count is invalid")
    if repeat_count > 1 and (
        selected_concurrencies is None or len(concurrencies) != 1
    ):
        raise ValueError(
            "repeated provider load requires one explicit planned concurrency"
        )
    runs: list[dict[str, object]] = []
    for repetition in range(1, repeat_count + 1):
        request_load_case_id = (
            load_case.identifier
            if repeat_count == 1
            else f"{load_case.identifier}-repeat-{repetition}"
        )
        for concurrency in concurrencies:
            requests: list[QualificationRequest] = []
            ordinal = 0
            for item in load_case.mix:
                for _index in range(item.count):
                    request = request_factory.create(
                        load_case_id=request_load_case_id,
                        concurrency=concurrency,
                        ordinal=ordinal,
                        duration_samples=item.duration_samples,
                    )
                    if request.audio_samples != item.duration_samples:
                        raise ValueError(
                            "qualification request duration differs from the runtime plan"
                        )
                    requests.append(request)
                    ordinal += 1
            metrics_token = (
                metrics_observer.before_run(concurrency=concurrency)
                if metrics_observer is not None
                else None
            )
            load = run_bounded_load(
                worker,
                tuple(requests),
                concurrency=concurrency,
                timeout_seconds_per_wave=timeout_seconds_per_wave,
            )
            summary = summarize_runtime_load(load)
            outcomes = summary.get("outcomes")
            completed = (
                outcomes.get("completed") if isinstance(outcomes, dict) else None
            )
            if metrics_observer is not None:
                summary["providerMetrics"] = metrics_observer.after_run(
                    metrics_token,
                    completed_requests=completed if isinstance(completed, int) else 0,
                    maximum_audio_samples=max(
                        request.audio_samples for request in requests
                    ),
                )
            summary["repetition"] = repetition
            summary["minimumCompletionsMet"] = (
                isinstance(completed, int)
                and completed >= load_case.minimum_completions
            )
            summary["expectationMet"] = standard_provider_expectation_met(
                summary,
                request_count=len(requests),
            )
            runs.append(summary)
    return ProviderLoadQualification(
        load_case=load_case,
        selected_concurrencies=concurrencies,
        repeat_count=repeat_count,
        runs=tuple(runs),
    )


def run_resident_provider_load_case(
    *,
    plan_path: Path,
    load_case_id: str,
    model_lock_path: Path,
    tracks: Mapping[int, LoadedDurationTrack],
    endpoint: str,
    catalog_language: str,
    provider_language: str,
    output_root: Path,
    timeout_seconds_per_wave: float,
    selected_concurrencies: tuple[int, ...] | None = None,
    repeat_count: int = 1,
    environ: Mapping[str, str] = os.environ,
) -> ProviderLoadQualification:
    """Run one standard resident-provider plan cell from private locked tracks."""

    plan = load_runtime_evaluation_plan(plan_path)
    load_case = select_runtime_load_case(plan, load_case_id)
    provider_id, api_key_environment = resident_provider_configuration(
        load_case.system_id
    )
    if load_case.expected not in _STANDARD_EXPECTATIONS:
        raise ValueError(
            "runtime load case requires its specialized qualification runner"
        )
    exact_tracks = validate_exact_tracks(tracks)
    expected_durations = {item.duration_samples for item in load_case.mix}
    if set(exact_tracks) != expected_durations:
        raise ValueError("duration tracks differ from the selected runtime load case")
    api_key = environ.get(api_key_environment, "")
    if not api_key:
        raise ValueError(f"{api_key_environment} is required for qualification")
    lock = load_model_pool_lock(model_lock_path)
    validate_resident_provider_lock(load_case.system_id, lock)
    worker = build_resident_worker(
        system_id=load_case.system_id,
        endpoint=endpoint,
        api_key=api_key,
        timeout_seconds=timeout_seconds_per_wave,
        lock=lock,
    )
    metrics_observer = resident_metrics_observer(
        system_id=load_case.system_id,
        endpoint=endpoint,
    )
    try:
        worker.verify_ready()
        request_factory = LockedProviderRequestFactory(
            system_id=load_case.system_id,
            provider_id=provider_id,
            catalog_language=catalog_language,
            provider_language=provider_language,
            lock=lock,
            tracks=exact_tracks,
            output_root=output_root,
            environ=environ,
        )
        return run_provider_load_case(
            worker,
            request_factory,
            plan,
            load_case_id=load_case_id,
            timeout_seconds_per_wave=timeout_seconds_per_wave,
            selected_concurrencies=selected_concurrencies,
            repeat_count=repeat_count,
            metrics_observer=metrics_observer,
        )
    finally:
        worker.close()


def standard_provider_expectation_met(
    summary: Mapping[str, object],
    *,
    request_count: int,
) -> bool:
    outcomes = summary.get("outcomes")
    if not isinstance(outcomes, Mapping):
        return False
    return (
        outcomes.get("completed") == request_count
        and outcomes.get("cancelled") == 0
        and outcomes.get("busy") == 0
        and outcomes.get("failed") == 0
        and summary.get("resultPublishedCount") == request_count
        and _lexical_stability_matches(
            summary.get("transcriptStabilityByAudioDuration")
        )
        and _provider_metrics_match(summary.get("providerMetrics"))
    )


def _selected_concurrencies(
    load_case: RuntimeLoadCase,
    selected: tuple[int, ...] | None,
) -> tuple[int, ...]:
    if selected is None:
        return load_case.concurrencies
    if (
        not selected
        or len(set(selected)) != len(selected)
        or any(
            isinstance(value, bool)
            or not isinstance(value, int)
            or value not in load_case.concurrencies
            for value in selected
        )
    ):
        raise ValueError("selected provider concurrency differs from the runtime plan")
    return selected


def _lexical_stability_matches(value: object) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(
            isinstance(item, Mapping)
            and isinstance(item.get("audioDurationSamples"), int)
            and not isinstance(item.get("audioDurationSamples"), bool)
            and item.get("audioDurationSamples", 0) > 0
            and isinstance(item.get("completedCount"), int)
            and not isinstance(item.get("completedCount"), bool)
            and item.get("completedCount", 0) > 0
            and item.get("lexicalIdentityCount") == 1
            for item in value
        )
    )


def _provider_metrics_match(value: object) -> bool:
    return value is None or (
        isinstance(value, Mapping)
        and value.get("idleAfter") is True
        and value.get("engineRequestCountAcceptable") is True
    )


def resident_provider_configuration(system_id: str) -> tuple[str, str]:
    provider_id = _RESIDENT_PROVIDER_IDS.get(system_id)
    api_key_environment = _RESIDENT_API_KEY_ENVIRONMENTS.get(system_id)
    if provider_id is None or api_key_environment is None:
        raise ValueError("runtime load case is not a resident provider scenario")
    return provider_id, api_key_environment


def validate_resident_provider_lock(
    system_id: str,
    lock: ModelPoolLock,
) -> None:
    expected = _RESIDENT_LOCK_BOUNDARIES.get(system_id)
    if expected is None:
        raise ValueError("runtime load case is not a resident provider scenario")
    expected_pool, expected_engine, expected_image = expected
    if (
        lock.pool_id != expected_pool
        or lock.engine != expected_engine
        or lock.runtime_image != expected_image
        or lock.runtime_platform != "linux/arm64"
        or lock.runtime_python_version != "3.12"
    ):
        raise ValueError("qualification requires the matching provider-serving lock")


def validate_exact_tracks(
    tracks: Mapping[int, LoadedDurationTrack],
) -> dict[int, LoadedDurationTrack]:
    """Copy and validate an already admitted exact-duration track index."""

    validated: dict[int, LoadedDurationTrack] = {}
    for declared_duration, track in tracks.items():
        if not isinstance(track, LoadedDurationTrack):
            raise ValueError("qualification duration-track values are invalid")
        audio = track.manifest.get("audio")
        duration = audio.get("durationSamples") if isinstance(audio, dict) else None
        if (
            isinstance(declared_duration, bool)
            or not isinstance(declared_duration, int)
            or declared_duration < 1
            or isinstance(duration, bool)
            or not isinstance(duration, int)
            or duration < 1
            or duration != declared_duration
            or duration in validated
        ):
            raise ValueError("qualification duration-track identities are invalid")
        validated[duration] = track
    if not validated:
        raise ValueError("resident provider qualification requires duration tracks")
    return validated


def build_resident_worker(
    *,
    system_id: str,
    endpoint: str,
    api_key: str,
    timeout_seconds: float,
    lock: ModelPoolLock,
) -> ResidentQualificationWorker:
    if system_id == "vllm-cohere-batch":
        from yap_server.pools.cohere_vllm_worker import CohereVllmBatchWorker
        from yap_server.pools.vllm_transcription_client import (
            VllmTranscriptionClient,
        )

        return CohereVllmBatchWorker(
            lock=lock,
            client=VllmTranscriptionClient(
                endpoint=endpoint,
                api_key=api_key,
                timeout_seconds=timeout_seconds,
            ),
        )
    if system_id == "nemo-nemotron-finalized":
        from yap_server.pools.nemotron_nemo_client import NemotronNemoClient
        from yap_server.pools.nemotron_nemo_worker import NemotronNemoBatchWorker

        return NemotronNemoBatchWorker(
            lock=lock,
            client=NemotronNemoClient(
                endpoint=endpoint,
                api_key=api_key,
                timeout_seconds=timeout_seconds,
            ),
        )
    raise ValueError("runtime load case is not a resident provider scenario")


def resident_metrics_observer(
    *,
    system_id: str,
    endpoint: str,
) -> ProviderMetricsObserver | None:
    if system_id == "vllm-cohere-batch":
        return VllmQualificationMetricsObserver(
            VllmRuntimeMetricsClient(endpoint),
        )
    return None


def write_private_evidence(path: Path, evidence: dict[str, object]) -> None:
    payload = (
        json.dumps(
            evidence,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    with path.open("xb") as output:
        if os.name == "posix":
            os.chmod(path, 0o600)
        output.write(payload)
        output.flush()
        os.fsync(output.fileno())


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one private resident-provider load qualification",
    )
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--checked-head", required=True)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--load-case", required=True)
    parser.add_argument("--model-lock", type=Path, required=True)
    parser.add_argument("--duration-suite", type=Path, required=True)
    parser.add_argument("--duration-suite-sha256", required=True)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--catalog-language", required=True)
    parser.add_argument("--provider-language", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--timeout-seconds-per-wave", type=float, required=True)
    parser.add_argument("--concurrency", type=int, action="append")
    parser.add_argument("--repeat-count", type=int, default=1)
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
    qualification = run_resident_provider_load_case(
        plan_path=plan_path,
        load_case_id=arguments.load_case,
        model_lock_path=model_lock_path,
        tracks=duration_tracks.indexed_tracks(),
        endpoint=arguments.endpoint,
        catalog_language=arguments.catalog_language,
        provider_language=arguments.provider_language,
        output_root=arguments.output_root,
        timeout_seconds_per_wave=arguments.timeout_seconds_per_wave,
        selected_concurrencies=(
            tuple(arguments.concurrency) if arguments.concurrency is not None else None
        ),
        repeat_count=arguments.repeat_count,
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
