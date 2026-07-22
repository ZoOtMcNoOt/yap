from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import threading
import time
from typing import Mapping, Protocol

from yap_server.evaluation.provider_qualification_requests import (
    LockedProviderRequestFactory,
)
from yap_server.evaluation.provider_runtime_observations import (
    QualificationRequest,
    canonical_evidence_sha256,
)
from yap_server.evaluation.provider_runtime_qualification import (
    QualificationRequestFactory,
    ResidentQualificationWorker,
    load_exact_tracks,
    resident_provider_configuration,
    write_private_evidence,
)
from yap_server.evaluation.runtime_plan import (
    RuntimeLoadCase,
    load_runtime_evaluation_plan,
    select_runtime_load_case,
)
from yap_server.evaluation.vllm_runtime_metrics import (
    VllmMetricsDelta,
    VllmMetricsSnapshot,
    VllmRuntimeMetricsClient,
)
from yap_server.pools.batch_contract import WorkerCancellationAcknowledged
from yap_server.pools.model_lock import ModelPoolLock, load_model_pool_lock


_SUPPORTED_EXPECTATIONS = {
    "vllm-cohere-batch": (
        "cancel-dispatched-follower-record-server-outcome-leader-and-"
        "recovery-singletons"
    ),
    "nemo-nemotron-finalized": (
        "cancel-one-preserve-sibling-and-immediate-recovery"
    ),
}
_EXPECTED_DURATIONS = (524_287, 262_144, 16_000)
_POLL_SECONDS = 0.02


class RequestDispatchObserver(Protocol):
    def wait_until_dispatched(
        self,
        job_id: str,
        *,
        timeout_seconds: float,
    ) -> bool: ...


class ActiveRequestObserver(Protocol):
    def active_requests(self) -> int: ...


class CancellationMetricsObserver(Protocol):
    def begin(self) -> object: ...

    def after_cancelled_pair(
        self,
        token: object,
    ) -> tuple[object, dict[str, object]]: ...

    def after_recovery(self, token: object) -> dict[str, object]: ...


@dataclass(slots=True)
class _Execution:
    result: dict[str, object] | None = None
    error: BaseException | None = None
    elapsed_ms: int | None = None
    finished_at: float | None = None


@dataclass(frozen=True, slots=True)
class ProviderCancellationQualification:
    load_case: RuntimeLoadCase
    run: Mapping[str, object]

    @property
    def passed(self) -> bool:
        return self.run.get("passed") is True

    def public_evidence(self) -> dict[str, object]:
        evidence: dict[str, object] = {
            "schemaVersion": 1,
            "loadCaseId": self.load_case.identifier,
            "systemId": self.load_case.system_id,
            "measurementBoundary": self.load_case.measurement_boundary,
            "expected": self.load_case.expected,
            "minimumCompletions": self.load_case.minimum_completions,
            **self.run,
        }
        evidence["evidenceSha256"] = canonical_evidence_sha256(evidence)
        return evidence


class VllmCancellationMetricsObserver:
    """Record whether the dispatched target aborted or finished in vLLM."""

    def __init__(self, client: VllmRuntimeMetricsClient) -> None:
        self._client = client

    def begin(self) -> VllmMetricsSnapshot:
        snapshot = self._client.snapshot()
        if snapshot.running_requests or snapshot.waiting_requests:
            raise RuntimeError("vLLM cancellation qualification is not isolated")
        return snapshot

    def after_cancelled_pair(
        self,
        token: object,
    ) -> tuple[VllmMetricsSnapshot, dict[str, object]]:
        if not isinstance(token, VllmMetricsSnapshot):
            raise TypeError("vLLM cancellation metric token is invalid")
        after = self._client.snapshot()
        delta = after.delta(token)
        histogram_counts = {
            histogram.count for histogram in delta.histograms.values()
        }
        target_outcome = _vllm_cancelled_target_outcome(delta)
        consistent = (
            not after.running_requests
            and not after.waiting_requests
            and histogram_counts == {delta.successful_requests}
            and target_outcome != "ambiguous-provider-accounting"
        )
        return after, {
            "metricUnit": "vllm-engine-request",
            "targetProviderOutcome": target_outcome,
            "metricsConsistent": consistent,
            **delta.public_evidence(),
        }

    def after_recovery(self, token: object) -> dict[str, object]:
        if not isinstance(token, VllmMetricsSnapshot):
            raise TypeError("vLLM recovery metric token is invalid")
        after = self._client.snapshot()
        delta = after.delta(token)
        histogram_counts = {
            histogram.count for histogram in delta.histograms.values()
        }
        consistent = (
            not after.running_requests
            and not after.waiting_requests
            and delta.successful_requests == 1
            and delta.finished_requests
            == {
                "stop": 1,
                "length": 0,
                "abort": 0,
                "error": 0,
                "repetition": 0,
            }
            and histogram_counts == {1}
        )
        return {
            "metricUnit": "vllm-engine-request",
            "metricsConsistent": consistent,
            **delta.public_evidence(),
        }


def _vllm_cancelled_target_outcome(delta: VllmMetricsDelta) -> str:
    successful_requests = delta.successful_requests
    finished_requests = delta.finished_requests
    # Both exact inputs are shorter than the pinned model's 35-second clip
    # boundary, so each produces one engine request. In pinned vLLM, an
    # external engine_client.abort() frees the request without appending it to
    # finished-request metrics. One completed stop therefore means the sibling
    # finished and the disconnected target was externally aborted.
    if successful_requests == 1 and finished_requests == {
        "stop": 1,
        "length": 0,
        "abort": 0,
        "error": 0,
        "repetition": 0,
    }:
        return "aborted-on-client-disconnect"
    if successful_requests == 2 and finished_requests == {
        "stop": 1,
        "length": 0,
        "abort": 1,
        "error": 0,
        "repetition": 0,
    }:
        return "aborted-with-engine-finish-reason"
    if successful_requests == 2 and finished_requests == {
        "stop": 2,
        "length": 0,
        "abort": 0,
        "error": 0,
        "repetition": 0,
    }:
        return "completed-after-client-cancellation"
    return "ambiguous-provider-accounting"


def run_provider_cancellation_case(
    worker: ResidentQualificationWorker,
    request_factory: QualificationRequestFactory,
    dispatch_observer: RequestDispatchObserver,
    activity_observer: ActiveRequestObserver,
    plan: Mapping[str, object],
    *,
    load_case_id: str,
    timeout_seconds: float,
    metrics_observer: CancellationMetricsObserver | None = None,
) -> ProviderCancellationQualification:
    """Cancel one dispatched request without accepting a generic failure."""

    if timeout_seconds <= 0:
        raise ValueError("provider cancellation timeout must be positive")
    load_case = select_runtime_load_case(plan, load_case_id)
    _validate_cancellation_case(load_case)
    requests = tuple(
        request_factory.create(
            load_case_id=load_case.identifier,
            concurrency=2,
            ordinal=ordinal,
            duration_samples=duration_samples,
        )
        for ordinal, duration_samples in enumerate(_EXPECTED_DURATIONS)
    )
    if tuple(request.audio_samples for request in requests) != _EXPECTED_DURATIONS:
        raise ValueError("cancellation requests differ from the runtime plan")
    leader, target, recovery = requests
    if activity_observer.active_requests() != 0:
        raise RuntimeError("provider cancellation qualification is not isolated")
    metric_token = metrics_observer.begin() if metrics_observer is not None else None

    cancellations = (threading.Event(), threading.Event())
    executions = (_Execution(), _Execution())
    release = threading.Barrier(3)
    threads = tuple(
        threading.Thread(
            target=_execute_after_release,
            args=(worker, request, cancellation, release, execution),
            name=f"yap-provider-cancellation-{role}",
            daemon=True,
        )
        for request, cancellation, execution, role in zip(
            (leader, target),
            cancellations,
            executions,
            ("leader", "target"),
            strict=True,
        )
    )
    for thread in threads:
        thread.start()
    try:
        release.wait(timeout=timeout_seconds)
        target_dispatched = dispatch_observer.wait_until_dispatched(
            target.job.job_id,
            timeout_seconds=timeout_seconds,
        )
        activity_observed, maximum_active = _wait_for_activity(
            activity_observer,
            minimum=2,
            timeout_seconds=timeout_seconds,
        )
        cancellation_started = time.monotonic()
        cancellations[1].set()
        threads[1].join(timeout_seconds)
        cancellation_ack_ms = (
            round((executions[1].finished_at - cancellation_started) * 1_000)
            if isinstance(
                executions[1].error,
                WorkerCancellationAcknowledged,
            )
            and executions[1].finished_at is not None
            else None
        )
        threads[0].join(timeout_seconds)
    finally:
        _contain_threads(threads, cancellations, timeout_seconds=timeout_seconds)

    target_outcome = _execution_outcome(executions[1], target)
    leader_outcome = _execution_outcome(executions[0], leader)
    idle_before_recovery = _wait_until_idle(
        activity_observer,
        timeout_seconds=timeout_seconds,
    )
    pair_metrics: dict[str, object]
    recovery_metric_token = metric_token
    if metrics_observer is not None:
        recovery_metric_token, pair_metrics = metrics_observer.after_cancelled_pair(
            metric_token
        )
    else:
        pair_metrics = {
            "metricUnit": "authenticated-service-request",
            "targetProviderOutcome": "cancellation-acknowledged",
            "metricsConsistent": True,
        }

    recovery_execution = _Execution()
    if idle_before_recovery:
        recovery_cancellation = threading.Event()
        recovery_thread = threading.Thread(
            target=_execute_immediately,
            args=(worker, recovery, recovery_cancellation, recovery_execution),
            name="yap-provider-cancellation-recovery",
            daemon=True,
        )
        recovery_thread.start()
        recovery_thread.join(timeout_seconds)
        _contain_threads(
            (recovery_thread,),
            (recovery_cancellation,),
            timeout_seconds=timeout_seconds,
        )
    recovery_outcome = _execution_outcome(recovery_execution, recovery)
    idle_after_recovery = _wait_until_idle(
        activity_observer,
        timeout_seconds=timeout_seconds,
    )
    if metrics_observer is not None and recovery_metric_token is not None:
        recovery_metrics = metrics_observer.after_recovery(recovery_metric_token)
    else:
        recovery_metrics = {
            "metricUnit": "authenticated-service-request",
            "metricsConsistent": recovery_outcome == "completed",
        }

    completed = sum(
        outcome == "completed" for outcome in (leader_outcome, recovery_outcome)
    )
    minimum_completions_met = completed >= load_case.minimum_completions
    passed = (
        target_dispatched
        and activity_observed
        and target_outcome == "cancelled"
        and not target.job.result_path.exists()
        and leader_outcome == "completed"
        and leader.job.result_path.is_file()
        and idle_before_recovery
        and recovery_outcome == "completed"
        and recovery.job.result_path.is_file()
        and idle_after_recovery
        and pair_metrics.get("metricsConsistent") is True
        and recovery_metrics.get("metricsConsistent") is True
        and minimum_completions_met
    )
    run: dict[str, object] = {
        "concurrency": 2,
        "targetDispatchedBeforeCancellation": target_dispatched,
        "providerActivityObservedBeforeCancellation": activity_observed,
        "maximumActiveRequestsObserved": maximum_active,
        "outcomes": {
            "leader": leader_outcome,
            "target": target_outcome,
            "recovery": recovery_outcome,
        },
        "resultPublished": {
            "leader": leader.job.result_path.is_file(),
            "target": target.job.result_path.is_file(),
            "recovery": recovery.job.result_path.is_file(),
        },
        "cancellationIntentToAcknowledgementMs": cancellation_ack_ms,
        "recoveryLatencyMs": recovery_execution.elapsed_ms,
        "providerIdleBeforeRecovery": idle_before_recovery,
        "providerIdleAfterRecovery": idle_after_recovery,
        "providerOutcomeAfterCancellation": pair_metrics,
        "providerRecoveryOutcome": recovery_metrics,
        "minimumCompletionsMet": minimum_completions_met,
        "passed": passed,
    }
    return ProviderCancellationQualification(load_case=load_case, run=run)


def run_resident_provider_cancellation_case(
    *,
    plan_path: Path,
    load_case_id: str,
    model_lock_path: Path,
    track_manifest_paths: tuple[Path, ...],
    endpoint: str,
    catalog_language: str,
    provider_language: str,
    output_root: Path,
    timeout_seconds: float,
    environ: Mapping[str, str] = os.environ,
) -> ProviderCancellationQualification:
    """Compose the cancellation gate for one resident provider."""

    plan = load_runtime_evaluation_plan(plan_path)
    load_case = select_runtime_load_case(plan, load_case_id)
    _validate_cancellation_case(load_case)
    provider_id, api_key_environment = resident_provider_configuration(
        load_case.system_id
    )
    api_key = environ.get(api_key_environment, "")
    if not api_key:
        raise ValueError(f"{api_key_environment} is required for qualification")
    tracks = load_exact_tracks(track_manifest_paths)
    if set(tracks) != set(_EXPECTED_DURATIONS):
        raise ValueError("duration tracks differ from the cancellation load case")
    lock = load_model_pool_lock(model_lock_path)
    runtime = _build_resident_cancellation_runtime(
        system_id=load_case.system_id,
        endpoint=endpoint,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
        lock=lock,
    )
    try:
        runtime.worker.verify_ready()
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
        return run_provider_cancellation_case(
            runtime.worker,
            request_factory,
            runtime.dispatch_observer,
            runtime.activity_observer,
            plan,
            load_case_id=load_case_id,
            timeout_seconds=timeout_seconds,
            metrics_observer=runtime.metrics_observer,
        )
    finally:
        runtime.worker.close()


@dataclass(frozen=True, slots=True)
class _ResidentCancellationRuntime:
    worker: ResidentQualificationWorker
    dispatch_observer: RequestDispatchObserver
    activity_observer: ActiveRequestObserver
    metrics_observer: CancellationMetricsObserver | None


class _VllmActiveRequests:
    def __init__(self, client: VllmRuntimeMetricsClient) -> None:
        self._client = client

    def active_requests(self) -> int:
        snapshot = self._client.snapshot()
        return snapshot.running_requests + snapshot.waiting_requests


class _NemoActiveRequests:
    def __init__(self, client: object, lock: ModelPoolLock) -> None:
        self._client = client
        self._lock = lock

    def active_requests(self) -> int:
        capacity = self._client.readiness_capacity(self._lock)  # type: ignore[attr-defined]
        return int(capacity["activeRequests"])


def _build_resident_cancellation_runtime(
    *,
    system_id: str,
    endpoint: str,
    api_key: str,
    timeout_seconds: float,
    lock: ModelPoolLock,
) -> _ResidentCancellationRuntime:
    if system_id == "vllm-cohere-batch":
        from yap_server.pools.cohere_vllm_worker import CohereVllmBatchWorker
        from yap_server.pools.vllm_transcription_client import (
            VllmTranscriptionClient,
        )

        client = VllmTranscriptionClient(
            endpoint=endpoint,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
        )
        metrics = VllmRuntimeMetricsClient(endpoint)
        return _ResidentCancellationRuntime(
            worker=CohereVllmBatchWorker(lock=lock, client=client),
            dispatch_observer=client,
            activity_observer=_VllmActiveRequests(metrics),
            metrics_observer=VllmCancellationMetricsObserver(metrics),
        )
    if system_id == "nemo-nemotron-finalized":
        from yap_server.pools.nemotron_nemo_client import NemotronNemoClient
        from yap_server.pools.nemotron_nemo_worker import NemotronNemoBatchWorker

        client = NemotronNemoClient(
            endpoint=endpoint,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
        )
        return _ResidentCancellationRuntime(
            worker=NemotronNemoBatchWorker(lock=lock, client=client),
            dispatch_observer=client,
            activity_observer=_NemoActiveRequests(client, lock),
            metrics_observer=None,
        )
    raise ValueError("runtime load case is not a resident provider scenario")


def _validate_cancellation_case(load_case: RuntimeLoadCase) -> None:
    expected = _SUPPORTED_EXPECTATIONS.get(load_case.system_id)
    durations = tuple(
        item.duration_samples
        for item in load_case.mix
        for _index in range(item.count)
    )
    if (
        expected is None
        or load_case.expected != expected
        or durations != _EXPECTED_DURATIONS
        or load_case.concurrencies != (2,)
        or load_case.minimum_completions != 2
    ):
        raise ValueError("runtime load case is not a resident cancellation scenario")


def _execute_after_release(
    worker: ResidentQualificationWorker,
    request: QualificationRequest,
    cancellation: threading.Event,
    release: threading.Barrier,
    execution: _Execution,
) -> None:
    try:
        release.wait()
    except threading.BrokenBarrierError as error:
        execution.error = error
        execution.finished_at = time.monotonic()
        return
    _execute_immediately(worker, request, cancellation, execution)


def _execute_immediately(
    worker: ResidentQualificationWorker,
    request: QualificationRequest,
    cancellation: threading.Event,
    execution: _Execution,
) -> None:
    started = time.monotonic()
    try:
        execution.result = worker.run(request.job, cancellation)
    except BaseException as error:
        execution.error = error
    finally:
        execution.elapsed_ms = round((time.monotonic() - started) * 1_000)
        execution.finished_at = time.monotonic()


def _contain_threads(
    threads: tuple[threading.Thread, ...],
    cancellations: tuple[threading.Event, ...],
    *,
    timeout_seconds: float,
) -> None:
    if not any(thread.is_alive() for thread in threads):
        return
    for cancellation in cancellations:
        cancellation.set()
    deadline = time.monotonic() + min(5.0, timeout_seconds)
    for thread in threads:
        thread.join(max(0.0, deadline - time.monotonic()))
    if any(thread.is_alive() for thread in threads):
        raise RuntimeError("provider cancellation qualification lost containment")


def _execution_outcome(
    execution: _Execution,
    request: QualificationRequest,
) -> str:
    if isinstance(execution.error, WorkerCancellationAcknowledged):
        return "cancelled"
    if execution.error is not None or not _valid_completed_result(execution.result, request):
        return "failed"
    return "completed"


def _valid_completed_result(
    result: object,
    request: QualificationRequest,
) -> bool:
    if not isinstance(result, dict) or result.get("jobId") != request.job.job_id:
        return False
    transcript = result.get("transcript")
    text = transcript.get("text") if isinstance(transcript, dict) else None
    return (
        isinstance(text, str)
        and bool(text.strip())
        and request.job.result_path.is_file()
    )


def _wait_for_activity(
    observer: ActiveRequestObserver,
    *,
    minimum: int,
    timeout_seconds: float,
) -> tuple[bool, int]:
    deadline = time.monotonic() + timeout_seconds
    maximum = 0
    while True:
        active = observer.active_requests()
        if isinstance(active, bool) or not isinstance(active, int) or active < 0:
            raise RuntimeError("provider active-request observation is invalid")
        maximum = max(maximum, active)
        if active >= minimum:
            return True, maximum
        if time.monotonic() >= deadline:
            return False, maximum
        time.sleep(_POLL_SECONDS)


def _wait_until_idle(
    observer: ActiveRequestObserver,
    *,
    timeout_seconds: float,
) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while True:
        active = observer.active_requests()
        if isinstance(active, bool) or not isinstance(active, int) or active < 0:
            raise RuntimeError("provider active-request observation is invalid")
        if active == 0:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(_POLL_SECONDS)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one private resident-provider cancellation qualification",
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
    parser.add_argument("--timeout-seconds", type=float, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    qualification = run_resident_provider_cancellation_case(
        plan_path=arguments.plan,
        load_case_id=arguments.load_case,
        model_lock_path=arguments.model_lock,
        track_manifest_paths=tuple(arguments.track_manifest),
        endpoint=arguments.endpoint,
        catalog_language=arguments.catalog_language,
        provider_language=arguments.provider_language,
        output_root=arguments.output_root,
        timeout_seconds=arguments.timeout_seconds,
    )
    evidence = qualification.public_evidence()
    write_private_evidence(arguments.output_root / "evidence.json", evidence)
    print(json.dumps(evidence, ensure_ascii=True, separators=(",", ":"), sort_keys=True))
    return 0 if qualification.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
