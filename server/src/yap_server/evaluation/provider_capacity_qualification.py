from __future__ import annotations

import argparse
from concurrent.futures import Future
from dataclasses import dataclass
import json
import os
from pathlib import Path
import threading
import time
from typing import Mapping, Protocol

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
    run_concurrent_wave,
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
from yap_server.jobs.contract_values import MAX_JOB_PCM_BYTES
from yap_server.pools.batch_contract import (
    AsrRouteDecision,
    PoolBackpressure,
)
from yap_server.pools.batch_pool import BatchAsrPool, BatchPoolReservation
from yap_server.pools.model_lock import ModelPoolLock, load_model_pool_lock


_VLLM_POOL_CASES = {
    "vllm-slot-capacity": {
        "expected": "sixteen-complete-one-retryable-pool-busy-then-recovery",
        "durations": (480_000,) * 17,
        "accepted": 16,
    },
    "vllm-pcm-capacity": {
        "expected": "two-complete-one-retryable-pcm-busy-then-recovery",
        "durations": (115_200_000, 115_200_000, 16_000),
        "accepted": 2,
    },
}
_NEMO_CASE_ID = "nemo-finalized-active-capacity"
_NEMO_EXPECTED = "eight-complete-one-retryable-service-busy"
_NEMO_DURATIONS = (14_400_000,) * 9
_POLL_SECONDS = 0.01


class ActiveRequestObserver(Protocol):
    def active_requests(self) -> int: ...


@dataclass(frozen=True, slots=True)
class ProviderCapacityQualification:
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


def run_vllm_pool_capacity_case(
    pool: BatchAsrPool,
    request_factory: QualificationRequestFactory,
    plan: Mapping[str, object],
    *,
    load_case_id: str,
    timeout_seconds: float,
) -> ProviderCapacityQualification:
    """Prove Yap's slot/PCM admission before any accepted work is released."""

    if timeout_seconds <= 0:
        raise ValueError("provider capacity timeout must be positive")
    load_case = select_runtime_load_case(plan, load_case_id)
    specification = _validate_vllm_pool_case(load_case)
    requests = _create_requests(request_factory, load_case)
    accepted: list[tuple[QualificationRequest, BatchPoolReservation]] = []
    rejected: list[QualificationRequest] = []
    for request in requests:
        try:
            reservation = pool.reserve(
                request.job.job_id,
                pcm_byte_length=request.audio_samples * 2,
            )
        except PoolBackpressure:
            rejected.append(request)
        else:
            accepted.append((request, reservation))

    futures: list[tuple[QualificationRequest, Future[dict[str, object]]]] = []
    for request, reservation in accepted:
        futures.append(
            (
                request,
                reservation.start(
                    lambda _cancellation, prepared=request: prepared.job
                ),
            )
        )
    deadline = time.monotonic() + timeout_seconds
    completed = sum(
        _future_completed(future, request, deadline=deadline)
        for request, future in futures
    )
    idle_after_initial = _wait_for_pool_idle(pool, timeout_seconds=timeout_seconds)
    rejected_result_published = (
        rejected[0].job.result_path.is_file() if len(rejected) == 1 else None
    )
    recovery_outcome = "not-run"
    recovery_latency_ms: int | None = None
    recovery_published = False
    if len(rejected) == 1 and idle_after_initial:
        recovery = rejected[0]
        started = time.monotonic()
        try:
            future = pool.reserve(
                recovery.job.job_id,
                pcm_byte_length=recovery.audio_samples * 2,
            ).start(lambda _cancellation: recovery.job)
            result = future.result(timeout=timeout_seconds)
        except BaseException:
            recovery_outcome = "failed"
        else:
            recovery_outcome = (
                "completed" if _valid_completed_result(result, recovery) else "failed"
            )
        recovery_latency_ms = round((time.monotonic() - started) * 1_000)
        recovery_published = recovery.job.result_path.is_file()
    idle_after_recovery = _wait_for_pool_idle(pool, timeout_seconds=timeout_seconds)
    expected_accepted = int(specification["accepted"])
    minimum_completions_met = completed >= load_case.minimum_completions
    passed = (
        len(accepted) == expected_accepted
        and len(rejected) == 1
        and rejected_result_published is False
        and completed == expected_accepted
        and idle_after_initial
        and recovery_outcome == "completed"
        and recovery_published
        and idle_after_recovery
        and not pool.fenced
        and minimum_completions_met
    )
    return ProviderCapacityQualification(
        load_case=load_case,
        run={
            "admissionOwner": "yap-batch-pool",
            "initialRequestCount": len(requests),
            "initialAcceptedCount": len(accepted),
            "initialRetryableBusyCount": len(rejected),
            "initialCompletedCount": completed,
            "rejectedResultPublished": rejected_result_published,
            "poolIdleAfterInitial": idle_after_initial,
            "recoveryOutcome": recovery_outcome,
            "recoveryLatencyMs": recovery_latency_ms,
            "recoveryResultPublished": recovery_published,
            "poolIdleAfterRecovery": idle_after_recovery,
            "poolFenced": pool.fenced,
            "minimumCompletionsMet": minimum_completions_met,
            "passed": passed,
        },
    )


def run_nemo_service_capacity_case(
    worker: ResidentQualificationWorker,
    request_factory: QualificationRequestFactory,
    activity_observer: ActiveRequestObserver,
    plan: Mapping[str, object],
    *,
    load_case_id: str,
    timeout_seconds: float,
) -> ProviderCapacityQualification:
    """Prove the authenticated NeMo service's eight-active plus one-busy edge."""

    if timeout_seconds <= 0:
        raise ValueError("provider capacity timeout must be positive")
    load_case = select_runtime_load_case(plan, load_case_id)
    _validate_nemo_case(load_case)
    requests = _create_requests(request_factory, load_case)
    if activity_observer.active_requests() != 0:
        raise RuntimeError("NeMo capacity qualification is not isolated")
    stop_monitor = threading.Event()
    maximum_active = [0]
    monitor_error: list[BaseException] = []

    def monitor() -> None:
        try:
            while not stop_monitor.is_set():
                active = activity_observer.active_requests()
                if (
                    isinstance(active, bool)
                    or not isinstance(active, int)
                    or active < 0
                ):
                    raise RuntimeError(
                        "provider active-request observation is invalid"
                    )
                maximum_active[0] = max(maximum_active[0], active)
                stop_monitor.wait(_POLL_SECONDS)
        except BaseException as error:
            monitor_error.append(error)

    monitor_thread = threading.Thread(
        target=monitor,
        name="yap-nemo-capacity-observer",
        daemon=True,
    )
    monitor_thread.start()
    try:
        wave = run_concurrent_wave(
            worker,
            requests,
            timeout_seconds=timeout_seconds,
        )
    finally:
        stop_monitor.set()
        monitor_thread.join(timeout_seconds)
    if monitor_thread.is_alive():
        raise RuntimeError("NeMo capacity observation did not terminate safely")
    if monitor_error:
        raise RuntimeError("NeMo capacity observation failed") from monitor_error[0]
    completed_observations = [
        observation for observation in wave.observations if observation.outcome == "completed"
    ]
    busy_observations = [
        observation for observation in wave.observations if observation.outcome == "busy"
    ]
    failed_count = sum(
        observation.outcome in {"failed", "cancelled"}
        for observation in wave.observations
    )
    request_by_id = {request.job.job_id: request for request in requests}
    recovery_outcome = "not-run"
    recovery_latency_ms: int | None = None
    recovery_published = False
    if len(busy_observations) == 1:
        recovery = request_by_id[busy_observations[0].request_id]
        started = time.monotonic()
        try:
            result = worker.run(recovery.job, threading.Event())
        except BaseException:
            recovery_outcome = "failed"
        else:
            recovery_outcome = (
                "completed" if _valid_completed_result(result, recovery) else "failed"
            )
        recovery_latency_ms = round((time.monotonic() - started) * 1_000)
        recovery_published = recovery.job.result_path.is_file()
    idle_after_recovery = _wait_for_provider_idle(
        activity_observer,
        timeout_seconds=timeout_seconds,
    )
    minimum_completions_met = (
        len(completed_observations) >= load_case.minimum_completions
    )
    passed = (
        len(completed_observations) == 8
        and len(busy_observations) == 1
        and failed_count == 0
        and maximum_active[0] == 8
        and recovery_outcome == "completed"
        and recovery_published
        and idle_after_recovery
        and minimum_completions_met
    )
    return ProviderCapacityQualification(
        load_case=load_case,
        run={
            "admissionOwner": "authenticated-nemo-service",
            "initialRequestCount": len(requests),
            "initialCompletedCount": len(completed_observations),
            "initialRetryableBusyCount": len(busy_observations),
            "initialFailedOrCancelledCount": failed_count,
            "maximumActiveRequestsObserved": maximum_active[0],
            "recoveryOutcome": recovery_outcome,
            "recoveryLatencyMs": recovery_latency_ms,
            "recoveryResultPublished": recovery_published,
            "providerIdleAfterRecovery": idle_after_recovery,
            "minimumCompletionsMet": minimum_completions_met,
            "passed": passed,
        },
    )


def run_resident_provider_capacity_case(
    *,
    plan_path: Path,
    load_case_id: str,
    model_lock_path: Path,
    tracks: Mapping[int, LoadedDurationTrack],
    endpoint: str,
    catalog_language: str,
    provider_language: str,
    output_root: Path,
    timeout_seconds: float,
    environ: Mapping[str, str] = os.environ,
) -> ProviderCapacityQualification:
    """Compose one provider-specific bounded-admission qualification."""

    plan = load_runtime_evaluation_plan(plan_path)
    load_case = select_runtime_load_case(plan, load_case_id)
    provider_id, api_key_environment = resident_provider_configuration(
        load_case.system_id
    )
    api_key = environ.get(api_key_environment, "")
    if not api_key:
        raise ValueError(f"{api_key_environment} is required for qualification")
    exact_tracks = validate_exact_tracks(tracks)
    expected_durations = {item.duration_samples for item in load_case.mix}
    if set(exact_tracks) != expected_durations:
        raise ValueError("duration tracks differ from the capacity load case")
    lock = load_model_pool_lock(model_lock_path)
    validate_resident_provider_lock(load_case.system_id, lock)
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
    if load_case.identifier in _VLLM_POOL_CASES:
        worker = build_resident_worker(
            system_id=load_case.system_id,
            endpoint=endpoint,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            lock=lock,
        )
        pool = BatchAsrPool(
            worker,
            route_resolver=lambda _language: _qualification_route(
                lock,
                provider_id=provider_id,
                provider_language=provider_language,
            ),
            asr_catalog_revision="0" * 64,
            max_workers=8,
            max_queued=8,
            max_inflight_pcm_bytes=MAX_JOB_PCM_BYTES,
        )
        try:
            worker.verify_ready()
            return run_vllm_pool_capacity_case(
                pool,
                request_factory,
                plan,
                load_case_id=load_case_id,
                timeout_seconds=timeout_seconds,
            )
        finally:
            pool.shutdown()
    if load_case.identifier == _NEMO_CASE_ID:
        from yap_server.pools.nemotron_nemo_client import NemotronNemoClient
        from yap_server.pools.nemotron_nemo_worker import NemotronNemoBatchWorker

        client = NemotronNemoClient(
            endpoint=endpoint,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
        )
        worker = NemotronNemoBatchWorker(lock=lock, client=client)
        activity = _NemoActiveRequests(client, lock)
        try:
            worker.verify_ready()
            return run_nemo_service_capacity_case(
                worker,
                request_factory,
                activity,
                plan,
                load_case_id=load_case_id,
                timeout_seconds=timeout_seconds,
            )
        finally:
            worker.close()
    raise ValueError("runtime load case is not a resident capacity scenario")


class _NemoActiveRequests:
    def __init__(self, client: object, lock: ModelPoolLock) -> None:
        self._client = client
        self._lock = lock

    def active_requests(self) -> int:
        capacity = self._client.readiness_capacity(self._lock)  # type: ignore[attr-defined]
        return int(capacity["activeRequests"])


def _validate_vllm_pool_case(load_case: RuntimeLoadCase) -> Mapping[str, object]:
    specification = _VLLM_POOL_CASES.get(load_case.identifier)
    durations = tuple(
        item.duration_samples
        for item in load_case.mix
        for _index in range(item.count)
    )
    if (
        specification is None
        or load_case.system_id != "vllm-cohere-batch"
        or load_case.measurement_boundary != "yap-batch-pool-admission"
        or load_case.expected != specification["expected"]
        or durations != specification["durations"]
        or load_case.concurrencies != (len(durations),)
        or load_case.minimum_completions != specification["accepted"]
    ):
        raise ValueError("runtime load case is not a vLLM pool-capacity scenario")
    return specification


def _validate_nemo_case(load_case: RuntimeLoadCase) -> None:
    durations = tuple(
        item.duration_samples
        for item in load_case.mix
        for _index in range(item.count)
    )
    if (
        load_case.identifier != _NEMO_CASE_ID
        or load_case.system_id != "nemo-nemotron-finalized"
        or load_case.measurement_boundary != "resident-service-admission"
        or load_case.expected != _NEMO_EXPECTED
        or durations != _NEMO_DURATIONS
        or load_case.concurrencies != (9,)
        or load_case.minimum_completions != 8
    ):
        raise ValueError("runtime load case is not a NeMo service-capacity scenario")


def _create_requests(
    factory: QualificationRequestFactory,
    load_case: RuntimeLoadCase,
) -> tuple[QualificationRequest, ...]:
    requests: list[QualificationRequest] = []
    ordinal = 0
    for item in load_case.mix:
        for _index in range(item.count):
            request = factory.create(
                load_case_id=load_case.identifier,
                concurrency=load_case.concurrencies[0],
                ordinal=ordinal,
                duration_samples=item.duration_samples,
            )
            if request.audio_samples != item.duration_samples:
                raise ValueError("capacity request differs from the runtime plan")
            requests.append(request)
            ordinal += 1
    return tuple(requests)


def _future_completed(
    future: Future[dict[str, object]],
    request: QualificationRequest,
    *,
    deadline: float,
) -> bool:
    try:
        result = future.result(timeout=max(0.0, deadline - time.monotonic()))
    except BaseException:
        return False
    return _valid_completed_result(result, request)


def _valid_completed_result(result: object, request: QualificationRequest) -> bool:
    if not isinstance(result, dict) or result.get("jobId") != request.job.job_id:
        return False
    transcript = result.get("transcript")
    text = transcript.get("text") if isinstance(transcript, dict) else None
    return (
        isinstance(text, str)
        and bool(text.strip())
        and request.job.result_path.is_file()
    )


def _wait_for_pool_idle(pool: BatchAsrPool, *, timeout_seconds: float) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while pool.outstanding_count:
        if time.monotonic() >= deadline:
            return False
        time.sleep(_POLL_SECONDS)
    return True


def _wait_for_provider_idle(
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


def _qualification_route(
    lock: ModelPoolLock,
    *,
    provider_id: str,
    provider_language: str,
) -> AsrRouteDecision:
    return AsrRouteDecision(
        provider_id=provider_id,
        pool_id=lock.pool_id,
        execution_mode=(
            "dynamicBatch" if provider_language == "auto" else "fixedBatch"
        ),
        model_revision=lock.model_revision,
        provider_language=provider_language,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one private resident-provider capacity qualification",
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
    parser.add_argument("--timeout-seconds", type=float, required=True)
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
    qualification = run_resident_provider_capacity_case(
        plan_path=plan_path,
        load_case_id=arguments.load_case,
        model_lock_path=model_lock_path,
        tracks=duration_tracks.indexed_tracks(),
        endpoint=arguments.endpoint,
        catalog_language=arguments.catalog_language,
        provider_language=arguments.provider_language,
        output_root=arguments.output_root,
        timeout_seconds=arguments.timeout_seconds,
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
