from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Mapping, Protocol

from yap_server.evaluation.duration_tracks import (
    LoadedDurationTrack,
    load_duration_track,
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
    runs: tuple[dict[str, object], ...]

    @property
    def passed(self) -> bool:
        return bool(self.runs) and all(
            run.get("minimumCompletionsMet") is True
            and run.get("expectationMet") is True
            for run in self.runs
        )

    def public_evidence(self) -> dict[str, object]:
        evidence: dict[str, object] = {
            "schemaVersion": 1,
            "loadCaseId": self.load_case.identifier,
            "systemId": self.load_case.system_id,
            "measurementBoundary": self.load_case.measurement_boundary,
            "expected": self.load_case.expected,
            "minimumCompletions": self.load_case.minimum_completions,
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
    metrics_observer: ProviderMetricsObserver | None = None,
) -> ProviderLoadQualification:
    """Execute one plan cell while keeping paths and transcript identity private."""

    load_case = select_runtime_load_case(plan, load_case_id)
    if load_case.expected not in _STANDARD_EXPECTATIONS:
        raise ValueError(
            "runtime load case requires its specialized qualification runner"
        )
    runs: list[dict[str, object]] = []
    for concurrency in load_case.concurrencies:
        requests: list[QualificationRequest] = []
        ordinal = 0
        for item in load_case.mix:
            for _index in range(item.count):
                request = request_factory.create(
                    load_case_id=load_case.identifier,
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
        completed = outcomes.get("completed") if isinstance(outcomes, dict) else None
        if metrics_observer is not None:
            summary["providerMetrics"] = metrics_observer.after_run(
                metrics_token,
                completed_requests=completed if isinstance(completed, int) else 0,
                maximum_audio_samples=max(
                    request.audio_samples for request in requests
                ),
            )
        summary["minimumCompletionsMet"] = (
            isinstance(completed, int)
            and completed >= load_case.minimum_completions
        )
        summary["expectationMet"] = _standard_expectation_met(
            summary,
            request_count=len(requests),
        )
        runs.append(summary)
    return ProviderLoadQualification(load_case=load_case, runs=tuple(runs))


def run_resident_provider_load_case(
    *,
    plan_path: Path,
    load_case_id: str,
    model_lock_path: Path,
    track_manifest_paths: tuple[Path, ...],
    endpoint: str,
    catalog_language: str,
    provider_language: str,
    output_root: Path,
    timeout_seconds_per_wave: float,
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
    if not track_manifest_paths:
        raise ValueError("resident provider qualification requires duration tracks")
    tracks = load_exact_tracks(track_manifest_paths)
    expected_durations = {item.duration_samples for item in load_case.mix}
    if set(tracks) != expected_durations:
        raise ValueError("duration tracks differ from the selected runtime load case")
    api_key = environ.get(api_key_environment, "")
    if not api_key:
        raise ValueError(f"{api_key_environment} is required for qualification")
    lock = load_model_pool_lock(model_lock_path)
    worker = build_resident_worker(
        system_id=load_case.system_id,
        endpoint=endpoint,
        api_key=api_key,
        timeout_seconds=timeout_seconds_per_wave,
        lock=lock,
    )
    metrics_observer = _resident_metrics_observer(
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
            tracks=tracks,
            output_root=output_root,
            environ=environ,
        )
        return run_provider_load_case(
            worker,
            request_factory,
            plan,
            load_case_id=load_case_id,
            timeout_seconds_per_wave=timeout_seconds_per_wave,
            metrics_observer=metrics_observer,
        )
    finally:
        worker.close()


def _standard_expectation_met(
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


def load_exact_tracks(
    manifest_paths: tuple[Path, ...],
) -> dict[int, LoadedDurationTrack]:
    tracks: dict[int, LoadedDurationTrack] = {}
    for manifest_path in manifest_paths:
        track = load_duration_track(manifest_path)
        audio = track.manifest.get("audio")
        duration = audio.get("durationSamples") if isinstance(audio, dict) else None
        if (
            isinstance(duration, bool)
            or not isinstance(duration, int)
            or duration < 1
            or duration in tracks
        ):
            raise ValueError("qualification duration-track identities are invalid")
        tracks[duration] = track
    return tracks


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


def _resident_metrics_observer(
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
    parser.add_argument("--load-case", required=True)
    parser.add_argument("--model-lock", type=Path, required=True)
    parser.add_argument(
        "--track-manifest",
        type=Path,
        action="append",
        required=True,
    )
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--catalog-language", required=True)
    parser.add_argument("--provider-language", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--timeout-seconds-per-wave", type=float, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    qualification = run_resident_provider_load_case(
        plan_path=arguments.plan,
        load_case_id=arguments.load_case,
        model_lock_path=arguments.model_lock,
        track_manifest_paths=tuple(arguments.track_manifest),
        endpoint=arguments.endpoint,
        catalog_language=arguments.catalog_language,
        provider_language=arguments.provider_language,
        output_root=arguments.output_root,
        timeout_seconds_per_wave=arguments.timeout_seconds_per_wave,
    )
    evidence = qualification.public_evidence()
    write_private_evidence(arguments.output_root / "evidence.json", evidence)
    print(json.dumps(evidence, ensure_ascii=True, separators=(",", ":"), sort_keys=True))
    return 0 if qualification.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
