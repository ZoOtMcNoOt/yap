from __future__ import annotations

from concurrent.futures import CancelledError
from dataclasses import dataclass
import hashlib
import json
import math
import threading
import time
from typing import Literal, Mapping, Protocol

from yap_server.evaluation.transcript_equivalence import (
    lexical_transcript_sha256,
)
from yap_server.pools.batch_contract import (
    BatchAsrJob,
    PoolBackpressure,
    ProviderCapacityUnavailable,
    WorkerCancellationAcknowledged,
)


_SAMPLE_RATE_HZ = 16_000
_SHA256_LENGTH = 64

ObservationOutcome = Literal["completed", "cancelled", "busy", "failed"]


class QualificationWorker(Protocol):
    def run(
        self,
        job: BatchAsrJob,
        cancellation: threading.Event,
    ) -> dict[str, object]: ...


@dataclass(frozen=True, slots=True)
class QualificationRequest:
    job: BatchAsrJob
    audio_samples: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.job, BatchAsrJob)
            or isinstance(self.audio_samples, bool)
            or not isinstance(self.audio_samples, int)
            or self.audio_samples < 1
        ):
            raise ValueError("runtime qualification request is invalid")


@dataclass(frozen=True, slots=True)
class ProviderMemoryObservation:
    allocated_mib: int
    reserved_mib: int
    peak_allocated_mib: int
    peak_reserved_mib: int

    def __post_init__(self) -> None:
        values = (
            self.allocated_mib,
            self.reserved_mib,
            self.peak_allocated_mib,
            self.peak_reserved_mib,
        )
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in values
        ):
            raise ValueError("provider memory observation is invalid")
        if (
            self.reserved_mib < self.allocated_mib
            or self.peak_allocated_mib < self.allocated_mib
            or self.peak_reserved_mib < self.reserved_mib
        ):
            raise ValueError("provider memory observation is inconsistent")


@dataclass(frozen=True, slots=True)
class RequestObservation:
    request_id: str
    audio_samples: int
    latency_ms: int
    outcome: ObservationOutcome
    result_published: bool
    transcript_sha256: str | None
    lexical_transcript_sha256: str | None
    queue_ms: int | None
    inference_ms: int | None
    max_batch_size: int | None
    provider_memory: ProviderMemoryObservation | None

    def __post_init__(self) -> None:
        if (
            not self.request_id
            or isinstance(self.audio_samples, bool)
            or not isinstance(self.audio_samples, int)
            or self.audio_samples < 1
            or isinstance(self.latency_ms, bool)
            or not isinstance(self.latency_ms, int)
            or self.latency_ms < 0
            or self.outcome not in {"completed", "cancelled", "busy", "failed"}
            or not isinstance(self.result_published, bool)
        ):
            raise ValueError("runtime request observation is invalid")
        if self.outcome == "completed":
            if (
                not self.result_published
                or not _valid_sha256(self.transcript_sha256)
                or not _valid_sha256(self.lexical_transcript_sha256)
            ):
                raise ValueError("completed runtime observation omitted its result identity")
        elif (
            self.result_published
            or self.transcript_sha256 is not None
            or self.lexical_transcript_sha256 is not None
        ):
            raise ValueError("unsuccessful runtime observation cannot publish a result")
        for value in (self.queue_ms, self.inference_ms, self.max_batch_size):
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 0
            ):
                raise ValueError("runtime observation metric is invalid")
        if self.max_batch_size == 0:
            raise ValueError("observed model batch size must be positive")
        if self.provider_memory is not None and not isinstance(
            self.provider_memory,
            ProviderMemoryObservation,
        ):
            raise ValueError("runtime observation provider memory is invalid")


@dataclass(frozen=True, slots=True)
class RuntimeWave:
    wall_ms: int
    observations: tuple[RequestObservation, ...]

    def __post_init__(self) -> None:
        if (
            isinstance(self.wall_ms, bool)
            or not isinstance(self.wall_ms, int)
            or self.wall_ms < 0
            or not self.observations
            or len({item.request_id for item in self.observations})
            != len(self.observations)
        ):
            raise ValueError("runtime qualification wave is invalid")


@dataclass(frozen=True, slots=True)
class RuntimeLoad:
    concurrency: int
    wall_ms: int
    waves: tuple[RuntimeWave, ...]

    def __post_init__(self) -> None:
        observations = tuple(
            observation
            for wave in self.waves
            for observation in wave.observations
        )
        if (
            isinstance(self.concurrency, bool)
            or not isinstance(self.concurrency, int)
            or self.concurrency < 1
            or isinstance(self.wall_ms, bool)
            or not isinstance(self.wall_ms, int)
            or self.wall_ms < 0
            or not self.waves
            or len({item.request_id for item in observations}) != len(observations)
        ):
            raise ValueError("runtime qualification load is invalid")

    @property
    def observations(self) -> tuple[RequestObservation, ...]:
        return tuple(
            observation
            for wave in self.waves
            for observation in wave.observations
        )


def run_concurrent_wave(
    worker: QualificationWorker,
    requests: tuple[QualificationRequest, ...],
    *,
    timeout_seconds: float,
) -> RuntimeWave:
    """Release independent requests together and retain privacy-safe observations."""

    if not requests or timeout_seconds <= 0:
        raise ValueError("runtime wave inputs are invalid")
    if len({request.job.job_id for request in requests}) != len(requests):
        raise ValueError("runtime wave request identities must be unique")
    release = threading.Barrier(len(requests) + 1)
    cancellations = [threading.Event() for _request in requests]
    observations: list[RequestObservation | None] = [None] * len(requests)

    def execute(index: int) -> None:
        request = requests[index]
        cancellation = cancellations[index]
        release.wait()
        started = time.monotonic()
        try:
            result = worker.run(request.job, cancellation)
            observations[index] = _completed_observation(
                request,
                result,
                latency_ms=_elapsed_ms(started),
            )
        except BaseException as error:
            observations[index] = RequestObservation(
                request_id=request.job.job_id,
                audio_samples=request.audio_samples,
                latency_ms=_elapsed_ms(started),
                outcome=_failure_outcome(error, cancellation),
                result_published=False,
                transcript_sha256=None,
                lexical_transcript_sha256=None,
                queue_ms=None,
                inference_ms=None,
                max_batch_size=None,
                provider_memory=None,
            )

    threads = [
        threading.Thread(
            target=execute,
            args=(index,),
            name=f"yap-runtime-observation-{index}",
            daemon=True,
        )
        for index in range(len(requests))
    ]
    for thread in threads:
        thread.start()
    release.wait()
    wave_started = time.monotonic()
    deadline = wave_started + timeout_seconds
    for thread in threads:
        thread.join(max(0.0, deadline - time.monotonic()))
    if any(thread.is_alive() for thread in threads):
        for cancellation in cancellations:
            cancellation.set()
        containment_deadline = time.monotonic() + min(5.0, timeout_seconds)
        for thread in threads:
            thread.join(max(0.0, containment_deadline - time.monotonic()))
        if any(thread.is_alive() for thread in threads):
            raise RuntimeError("runtime qualification wave did not acknowledge cancellation")
    completed = tuple(item for item in observations if item is not None)
    if len(completed) != len(requests):
        raise RuntimeError("runtime qualification wave lost an observation")
    return RuntimeWave(wall_ms=_elapsed_ms(wave_started), observations=completed)


def run_bounded_load(
    worker: QualificationWorker,
    requests: tuple[QualificationRequest, ...],
    *,
    concurrency: int,
    timeout_seconds_per_wave: float,
) -> RuntimeLoad:
    """Run every request in synchronized waves without exceeding concurrency."""

    if (
        not requests
        or isinstance(concurrency, bool)
        or not isinstance(concurrency, int)
        or concurrency < 1
        or timeout_seconds_per_wave <= 0
    ):
        raise ValueError("runtime load inputs are invalid")
    if len({request.job.job_id for request in requests}) != len(requests):
        raise ValueError("runtime load request identities must be unique")
    started = time.monotonic()
    waves = tuple(
        run_concurrent_wave(
            worker,
            requests[offset : offset + concurrency],
            timeout_seconds=timeout_seconds_per_wave,
        )
        for offset in range(0, len(requests), concurrency)
    )
    return RuntimeLoad(
        concurrency=concurrency,
        wall_ms=_elapsed_ms(started),
        waves=waves,
    )


def summarize_runtime_wave(wave: RuntimeWave) -> dict[str, object]:
    """Return aggregate evidence without paths, request IDs, or transcript hashes."""

    completed = [item for item in wave.observations if item.outcome == "completed"]
    audio_seconds = sum(item.audio_samples for item in completed) / _SAMPLE_RATE_HZ
    outcome_counts = {
        outcome: sum(item.outcome == outcome for item in wave.observations)
        for outcome in ("completed", "cancelled", "busy", "failed")
    }
    latencies = [item.latency_ms for item in completed]
    queues = [item.queue_ms for item in completed if item.queue_ms is not None]
    inference = [
        item.inference_ms for item in completed if item.inference_ms is not None
    ]
    batch_sizes = [
        item.max_batch_size
        for item in completed
        if item.max_batch_size is not None
    ]
    wall_seconds = wave.wall_ms / 1_000
    return {
        "requestCount": len(wave.observations),
        "outcomes": outcome_counts,
        "resultPublishedCount": sum(
            item.result_published for item in wave.observations
        ),
        "completedAudioSeconds": round(audio_seconds, 6),
        "wallMs": wave.wall_ms,
        "latencyMs": _distribution(latencies),
        "queueMs": _distribution(queues),
        "inferenceMs": _distribution(inference),
        "maximumObservedModelBatch": max(batch_sizes) if batch_sizes else None,
        "providerReportedMemoryMiB": _provider_memory_summary(completed),
        "transcriptIdentityCount": len(
            {item.transcript_sha256 for item in completed}
        ),
        "lexicalTranscriptIdentityCount": len(
            {item.lexical_transcript_sha256 for item in completed}
        ),
        "transcriptStabilityByAudioDuration": _transcript_stability_by_duration(
            completed
        ),
        "audioSecondsPerWallSecond": (
            round(audio_seconds / wall_seconds, 6)
            if audio_seconds > 0 and wall_seconds > 0
            else None
        ),
        "realtimeFactor": (
            round(wall_seconds / audio_seconds, 6)
            if audio_seconds > 0
            else None
        ),
    }


def summarize_runtime_load(load: RuntimeLoad) -> dict[str, object]:
    """Aggregate a bounded load without exposing raw request observations."""

    summary = summarize_runtime_wave(
        RuntimeWave(wall_ms=load.wall_ms, observations=load.observations)
    )
    return {
        "concurrency": load.concurrency,
        "waveCount": len(load.waves),
        **summary,
    }


def _completed_observation(
    request: QualificationRequest,
    result: object,
    *,
    latency_ms: int,
) -> RequestObservation:
    if not isinstance(result, dict) or result.get("jobId") != request.job.job_id:
        raise ValueError("runtime result identity is invalid")
    transcript = result.get("transcript")
    text = transcript.get("text") if isinstance(transcript, dict) else None
    if not isinstance(text, str) or not text.strip():
        raise ValueError("runtime result transcript is invalid")
    runtime = result.get("runtime")
    runtime = runtime if isinstance(runtime, dict) else {}
    return RequestObservation(
        request_id=request.job.job_id,
        audio_samples=request.audio_samples,
        latency_ms=latency_ms,
        outcome="completed",
        result_published=request.job.result_path.is_file(),
        transcript_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        lexical_transcript_sha256=lexical_transcript_sha256(text),
        queue_ms=_optional_nonnegative_int(runtime.get("queueMs")),
        inference_ms=_optional_nonnegative_int(runtime.get("inferenceMs")),
        max_batch_size=_optional_positive_int(runtime.get("batchSize")),
        provider_memory=_provider_memory_observation(runtime.get("memory")),
    )


def _transcript_stability_by_duration(
    completed: list[RequestObservation],
) -> list[dict[str, int]]:
    evidence: list[dict[str, int]] = []
    for audio_samples in sorted({item.audio_samples for item in completed}):
        matching = [
            item for item in completed if item.audio_samples == audio_samples
        ]
        evidence.append(
            {
                "audioDurationSamples": audio_samples,
                "completedCount": len(matching),
                "exactIdentityCount": len(
                    {item.transcript_sha256 for item in matching}
                ),
                "lexicalIdentityCount": len(
                    {item.lexical_transcript_sha256 for item in matching}
                ),
            }
        )
    return evidence


def _failure_outcome(error: BaseException, cancellation: threading.Event) -> ObservationOutcome:
    if cancellation.is_set() or isinstance(
        error,
        (CancelledError, WorkerCancellationAcknowledged),
    ):
        return "cancelled"
    if isinstance(error, (PoolBackpressure, ProviderCapacityUnavailable)):
        return "busy"
    return "failed"


def _provider_memory_observation(value: object) -> ProviderMemoryObservation | None:
    if not isinstance(value, Mapping):
        return None
    values = tuple(
        _optional_nonnegative_int(value.get(key))
        for key in (
            "allocatedMiB",
            "reservedMiB",
            "peakAllocatedMiB",
            "peakReservedMiB",
        )
    )
    if any(item is None for item in values):
        return None
    try:
        return ProviderMemoryObservation(
            allocated_mib=values[0],  # type: ignore[arg-type]
            reserved_mib=values[1],  # type: ignore[arg-type]
            peak_allocated_mib=values[2],  # type: ignore[arg-type]
            peak_reserved_mib=values[3],  # type: ignore[arg-type]
        )
    except ValueError:
        return None


def _provider_memory_summary(
    completed: list[RequestObservation],
) -> dict[str, object] | None:
    observations = [
        item.provider_memory
        for item in completed
        if item.provider_memory is not None
    ]
    if not observations:
        return None
    return {
        "observationCount": len(observations),
        "allocated": _distribution([item.allocated_mib for item in observations]),
        "reserved": _distribution([item.reserved_mib for item in observations]),
        "peakAllocated": _distribution(
            [item.peak_allocated_mib for item in observations]
        ),
        "peakReserved": _distribution(
            [item.peak_reserved_mib for item in observations]
        ),
    }


def _distribution(values: list[int]) -> dict[str, int] | None:
    if not values:
        return None
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "minimum": ordered[0],
        "p50": _nearest_rank(ordered, 0.50),
        "p95": _nearest_rank(ordered, 0.95),
        "p99": _nearest_rank(ordered, 0.99),
        "maximum": ordered[-1],
    }


def _nearest_rank(ordered: list[int], percentile: float) -> int:
    return ordered[max(0, math.ceil(percentile * len(ordered)) - 1)]


def _optional_nonnegative_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _optional_positive_int(value: object) -> int | None:
    parsed = _optional_nonnegative_int(value)
    return parsed if parsed is not None and parsed > 0 else None


def _elapsed_ms(started: float) -> int:
    return round((time.monotonic() - started) * 1_000)


def _valid_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == _SHA256_LENGTH
        and all(character in "0123456789abcdef" for character in value)
    )


def canonical_evidence_sha256(value: object) -> str:
    """Bind an aggregate evidence object without depending on filesystem bytes."""

    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
