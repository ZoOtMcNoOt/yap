from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import stat
from typing import Mapping, Sequence

from yap_server.evaluation.provider_runtime_qualification import (
    write_private_evidence,
)
from yap_server.evaluation.provider_runtime_observations import (
    canonical_evidence_sha256,
)
from yap_server.evaluation.runtime_plan import (
    RuntimeResourceProfile,
    load_runtime_evaluation_plan,
    select_runtime_resource_profile,
)


_MAX_SAMPLE_FILE_BYTES = 16 * 1024 * 1024
_MAX_SAMPLES = 100_000
_MAX_COUNTER_VALUE = (1 << 63) - 1
_TAIL_FRACTION = 0.5


@dataclass(frozen=True, slots=True)
class ProviderResourceSample:
    elapsed_ms: int
    memory_current_bytes: int
    memory_peak_bytes: int
    cgroup_anon_bytes: int
    cgroup_file_bytes: int
    cgroup_kernel_bytes: int
    process_resident_bytes: int
    process_resident_anon_bytes: int
    process_resident_file_bytes: int
    process_resident_shared_bytes: int
    process_virtual_data_bytes: int
    process_thread_count: int
    memory_high_events: int
    memory_max_events: int
    memory_oom_events: int
    memory_oom_kill_events: int
    cpu_usage_usec: int
    task_count: int

    def __post_init__(self) -> None:
        for value in (
            self.elapsed_ms,
            self.memory_current_bytes,
            self.memory_peak_bytes,
            self.cgroup_anon_bytes,
            self.cgroup_file_bytes,
            self.cgroup_kernel_bytes,
            self.process_resident_bytes,
            self.process_resident_anon_bytes,
            self.process_resident_file_bytes,
            self.process_resident_shared_bytes,
            self.process_virtual_data_bytes,
            self.process_thread_count,
            self.memory_high_events,
            self.memory_max_events,
            self.memory_oom_events,
            self.memory_oom_kill_events,
            self.cpu_usage_usec,
            self.task_count,
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not 0 <= value <= _MAX_COUNTER_VALUE
            ):
                raise ValueError("provider resource sample is invalid")
        if self.memory_peak_bytes < self.memory_current_bytes:
            raise ValueError("provider resource peak is below current memory")
        if self.task_count < 1:
            raise ValueError("provider resource task count must be positive")
        if self.process_thread_count < 1:
            raise ValueError("provider resource thread count must be positive")
        if (
            self.process_resident_anon_bytes
            + self.process_resident_file_bytes
            + self.process_resident_shared_bytes
            != self.process_resident_bytes
        ):
            raise ValueError("provider process resident-memory components differ")


def load_private_resource_samples(
    path: Path,
    *,
    environ: Mapping[str, str] = os.environ,
) -> tuple[ProviderResourceSample, ...]:
    cache_root = _private_cache_root(environ)
    source = _private_existing_file(path, cache_root=cache_root)
    metadata = source.lstat()
    if not 1 <= metadata.st_size <= _MAX_SAMPLE_FILE_BYTES:
        raise ValueError("provider resource sample file size is invalid")
    samples: list[ProviderResourceSample] = []
    with source.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if line_number > _MAX_SAMPLES:
                raise ValueError("provider resource sample count exceeds its bound")
            try:
                value = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError("provider resource sample is not valid JSON") from error
            samples.append(_parse_sample(value))
    _validate_sample_order(samples)
    return tuple(samples)


def summarize_provider_resources(
    samples: Sequence[ProviderResourceSample],
    *,
    workload_start_ms: int,
    workload_end_ms: int,
) -> dict[str, object]:
    if (
        isinstance(workload_start_ms, bool)
        or not isinstance(workload_start_ms, int)
        or isinstance(workload_end_ms, bool)
        or not isinstance(workload_end_ms, int)
        or workload_start_ms < 0
        or workload_end_ms <= workload_start_ms
    ):
        raise ValueError("provider resource workload interval is invalid")
    checked = tuple(samples)
    _validate_sample_order(checked)
    before = tuple(sample for sample in checked if sample.elapsed_ms <= workload_start_ms)
    after = tuple(sample for sample in checked if sample.elapsed_ms >= workload_end_ms)
    during = tuple(
        sample
        for sample in checked
        if workload_start_ms <= sample.elapsed_ms <= workload_end_ms
    )
    if not before or not after or len(during) < 5:
        raise ValueError("provider resource samples do not cover the workload")
    baseline = before[-1]
    completed = after[0]
    tail_start_ms = workload_start_ms + round(
        (workload_end_ms - workload_start_ms) * _TAIL_FRACTION
    )
    tail = tuple(sample for sample in during if sample.elapsed_ms >= tail_start_ms)
    if len(tail) < 3:
        raise ValueError("provider resource samples do not cover the workload tail")
    memory_values = [sample.memory_current_bytes for sample in during]
    tail_memory = [sample.memory_current_bytes for sample in tail]
    cpu_elapsed_ms = completed.elapsed_ms - baseline.elapsed_ms
    cpu_usage_delta = completed.cpu_usage_usec - baseline.cpu_usage_usec
    if cpu_elapsed_ms <= 0 or cpu_usage_delta < 0:
        raise ValueError("provider resource CPU interval is invalid")
    return {
        "schemaVersion": 1,
        "observationBoundary": "container-cgroup-v2",
        "sampleCount": len(checked),
        "workloadSampleCount": len(during),
        "observationDurationMs": checked[-1].elapsed_ms - checked[0].elapsed_ms,
        "workloadDurationMs": workload_end_ms - workload_start_ms,
        "memoryCurrentBytes": {
            "beforeWorkload": baseline.memory_current_bytes,
            "minimumDuringWorkload": min(memory_values),
            "maximumDuringWorkload": max(memory_values),
            "afterWorkload": completed.memory_current_bytes,
        },
        "memoryPeakBytes": max(sample.memory_peak_bytes for sample in checked),
        "memoryEventsDuringWorkload": {
            "high": completed.memory_high_events - baseline.memory_high_events,
            "max": completed.memory_max_events - baseline.memory_max_events,
            "oom": completed.memory_oom_events - baseline.memory_oom_events,
            "oomKill": (
                completed.memory_oom_kill_events
                - baseline.memory_oom_kill_events
            ),
        },
        "memoryGrowthBytesDuringWorkload": (
            completed.memory_current_bytes - baseline.memory_current_bytes
        ),
        "memoryCompositionBytes": {
            "cgroupAnon": _dimension_summary(
                before=baseline.cgroup_anon_bytes,
                during=[sample.cgroup_anon_bytes for sample in during],
                after=completed.cgroup_anon_bytes,
                tail=[sample.cgroup_anon_bytes for sample in tail],
            ),
            "cgroupFile": _dimension_summary(
                before=baseline.cgroup_file_bytes,
                during=[sample.cgroup_file_bytes for sample in during],
                after=completed.cgroup_file_bytes,
                tail=[sample.cgroup_file_bytes for sample in tail],
            ),
            "cgroupKernel": _dimension_summary(
                before=baseline.cgroup_kernel_bytes,
                during=[sample.cgroup_kernel_bytes for sample in during],
                after=completed.cgroup_kernel_bytes,
                tail=[sample.cgroup_kernel_bytes for sample in tail],
            ),
        },
        "containerEntrypointProcess": {
            "residentBytes": _dimension_summary(
                before=baseline.process_resident_bytes,
                during=[sample.process_resident_bytes for sample in during],
                after=completed.process_resident_bytes,
                tail=[sample.process_resident_bytes for sample in tail],
            ),
            "residentAnonBytes": _dimension_summary(
                before=baseline.process_resident_anon_bytes,
                during=[sample.process_resident_anon_bytes for sample in during],
                after=completed.process_resident_anon_bytes,
                tail=[sample.process_resident_anon_bytes for sample in tail],
            ),
            "residentFileBytes": _dimension_summary(
                before=baseline.process_resident_file_bytes,
                during=[sample.process_resident_file_bytes for sample in during],
                after=completed.process_resident_file_bytes,
                tail=[sample.process_resident_file_bytes for sample in tail],
            ),
            "residentSharedBytes": _dimension_summary(
                before=baseline.process_resident_shared_bytes,
                during=[sample.process_resident_shared_bytes for sample in during],
                after=completed.process_resident_shared_bytes,
                tail=[sample.process_resident_shared_bytes for sample in tail],
            ),
            "virtualDataBytes": _dimension_summary(
                before=baseline.process_virtual_data_bytes,
                during=[sample.process_virtual_data_bytes for sample in during],
                after=completed.process_virtual_data_bytes,
                tail=[sample.process_virtual_data_bytes for sample in tail],
            ),
            "maximumThreadCount": max(
                sample.process_thread_count for sample in during
            ),
        },
        "tailMemoryTrend": {
            "method": "last-half-window-median-and-linear-regression-v2",
            "sampleCount": len(tail),
            "durationMs": tail[-1].elapsed_ms - tail[0].elapsed_ms,
            "linearRegressionSlopeBytesPerMinute": _linear_memory_slope(tail),
            "endpointGrowthBytes": (
                tail[-1].memory_current_bytes
                - tail[0].memory_current_bytes
            ),
            **_window_median_growth(tail_memory),
            "rangeBytes": max(tail_memory) - min(tail_memory),
        },
        "cpu": {
            "usageUsecDuringWorkload": cpu_usage_delta,
            "averageCoreUtilization": round(
                cpu_usage_delta / (cpu_elapsed_ms * 1_000),
                6,
            ),
        },
        "maximumCgroupTaskCount": max(sample.task_count for sample in during),
    }


def qualify_provider_resources(
    summary: Mapping[str, object],
    *,
    profile: RuntimeResourceProfile,
    completed_request_count: int,
    concurrency: int,
) -> dict[str, object]:
    """Apply one predeclared GB10 resource contract to aggregate observations."""

    if not isinstance(profile, RuntimeResourceProfile):
        raise TypeError("provider resource profile is invalid")
    for value, label in (
        (completed_request_count, "completed request count"),
        (concurrency, "concurrency"),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"provider resource {label} is invalid")
    if summary.get("schemaVersion") != 1 or summary.get(
        "observationBoundary"
    ) != "container-cgroup-v2":
        raise ValueError("provider resource summary identity is invalid")

    current = _required_mapping(summary, "memoryCurrentBytes")
    events = _required_mapping(summary, "memoryEventsDuringWorkload")
    tail = _required_mapping(summary, "tailMemoryTrend")
    entrypoint = _required_mapping(summary, "containerEntrypointProcess")
    virtual_data = _required_mapping(entrypoint, "virtualDataBytes")
    zero_events = all(
        _required_int(events, key) == 0
        for key in ("high", "max", "oom", "oomKill")
    )
    checks = {
        "completedRequestCount": (
            completed_request_count == profile.completed_request_count
        ),
        "concurrency": concurrency == profile.concurrency,
        "tailDuration": (
            _required_int(tail, "durationMs") >= profile.minimum_tail_duration_ms
        ),
        "tailSampleCount": (
            _required_int(tail, "sampleCount") >= profile.minimum_tail_sample_count
        ),
        "memoryCurrentCeiling": (
            _required_int(current, "maximumDuringWorkload")
            <= profile.maximum_memory_current_bytes
        ),
        "memoryPeakCeiling": (
            _required_int(summary, "memoryPeakBytes")
            <= profile.maximum_memory_peak_bytes
        ),
        "containerEntrypointVirtualDataCeiling": (
            _required_int(virtual_data, "maximumDuringWorkload")
            <= profile.maximum_container_entrypoint_virtual_data_bytes
        ),
        "allocationExtentPlateau": (
            abs(_required_int(virtual_data, "windowMedianGrowthBytes"))
            <= profile.maximum_absolute_tail_virtual_data_window_median_growth_bytes
        ),
        "cgroupTaskCountCeiling": (
            _required_int(summary, "maximumCgroupTaskCount")
            <= profile.maximum_cgroup_task_count
        ),
        "containerEntrypointThreadCountCeiling": (
            _required_int(entrypoint, "maximumThreadCount")
            <= profile.maximum_container_entrypoint_thread_count
        ),
        "memoryEvents": zero_events if profile.require_zero_memory_events else True,
    }
    evidence: dict[str, object] = {
        "schemaVersion": 1,
        "systemId": profile.system_id,
        "loadCaseId": profile.load_case_id,
        "hardwareProfile": profile.hardware_profile,
        "completedRequestCount": completed_request_count,
        "concurrency": concurrency,
        "thresholds": _resource_thresholds(profile),
        "observed": dict(summary),
        "checks": checks,
        "passed": all(checks.values()),
    }
    evidence["evidenceSha256"] = canonical_evidence_sha256(evidence)
    return evidence


def _parse_sample(value: object) -> ProviderResourceSample:
    if not isinstance(value, dict) or set(value) != {
        "elapsedMs",
        "memoryCurrentBytes",
        "memoryPeakBytes",
        "cgroupAnonBytes",
        "cgroupFileBytes",
        "cgroupKernelBytes",
        "processResidentBytes",
        "processResidentAnonBytes",
        "processResidentFileBytes",
        "processResidentSharedBytes",
        "processVirtualDataBytes",
        "processThreadCount",
        "memoryHighEvents",
        "memoryMaxEvents",
        "memoryOomEvents",
        "memoryOomKillEvents",
        "cpuUsageUsec",
        "taskCount",
    }:
        raise ValueError("provider resource sample shape is invalid")
    return ProviderResourceSample(
        elapsed_ms=value["elapsedMs"],
        memory_current_bytes=value["memoryCurrentBytes"],
        memory_peak_bytes=value["memoryPeakBytes"],
        cgroup_anon_bytes=value["cgroupAnonBytes"],
        cgroup_file_bytes=value["cgroupFileBytes"],
        cgroup_kernel_bytes=value["cgroupKernelBytes"],
        process_resident_bytes=value["processResidentBytes"],
        process_resident_anon_bytes=value["processResidentAnonBytes"],
        process_resident_file_bytes=value["processResidentFileBytes"],
        process_resident_shared_bytes=value["processResidentSharedBytes"],
        process_virtual_data_bytes=value["processVirtualDataBytes"],
        process_thread_count=value["processThreadCount"],
        memory_high_events=value["memoryHighEvents"],
        memory_max_events=value["memoryMaxEvents"],
        memory_oom_events=value["memoryOomEvents"],
        memory_oom_kill_events=value["memoryOomKillEvents"],
        cpu_usage_usec=value["cpuUsageUsec"],
        task_count=value["taskCount"],
    )


def _resource_thresholds(profile: RuntimeResourceProfile) -> dict[str, object]:
    return {
        "completedRequestCount": profile.completed_request_count,
        "concurrency": profile.concurrency,
        "minimumTailDurationMs": profile.minimum_tail_duration_ms,
        "minimumTailSampleCount": profile.minimum_tail_sample_count,
        "maximumMemoryCurrentBytes": profile.maximum_memory_current_bytes,
        "maximumMemoryPeakBytes": profile.maximum_memory_peak_bytes,
        "maximumContainerEntrypointVirtualDataBytes": (
            profile.maximum_container_entrypoint_virtual_data_bytes
        ),
        "maximumAbsoluteTailVirtualDataWindowMedianGrowthBytes": (
            profile.maximum_absolute_tail_virtual_data_window_median_growth_bytes
        ),
        "maximumCgroupTaskCount": profile.maximum_cgroup_task_count,
        "maximumContainerEntrypointThreadCount": (
            profile.maximum_container_entrypoint_thread_count
        ),
        "requireZeroMemoryEvents": profile.require_zero_memory_events,
    }


def _required_mapping(value: Mapping[str, object], key: str) -> Mapping[str, object]:
    selected = value.get(key)
    if not isinstance(selected, Mapping):
        raise ValueError(f"provider resource summary omitted {key}")
    return selected


def _required_int(value: Mapping[str, object], key: str) -> int:
    selected = value.get(key)
    if isinstance(selected, bool) or not isinstance(selected, int):
        raise ValueError(f"provider resource summary omitted {key}")
    return selected


def _dimension_summary(
    *,
    before: int,
    during: list[int],
    after: int,
    tail: list[int],
) -> dict[str, int]:
    return {
        "beforeWorkload": before,
        "minimumDuringWorkload": min(during),
        "maximumDuringWorkload": max(during),
        "afterWorkload": after,
        "growthDuringWorkload": after - before,
        **_window_median_growth(tail),
    }


def _window_median_growth(values: Sequence[int]) -> dict[str, int]:
    window_count = max(1, (len(values) + 9) // 10)
    first = sorted(values[:window_count])
    last = sorted(values[-window_count:])
    return {
        "windowSampleCount": window_count,
        "firstWindowMedianBytes": _integer_median(first),
        "lastWindowMedianBytes": _integer_median(last),
        "windowMedianGrowthBytes": _integer_median(last) - _integer_median(first),
    }


def _integer_median(ordered: Sequence[int]) -> int:
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return round((ordered[middle - 1] + ordered[middle]) / 2)


def _validate_sample_order(samples: Sequence[ProviderResourceSample]) -> None:
    if len(samples) < 5:
        raise ValueError("provider resource series requires at least five samples")
    previous: ProviderResourceSample | None = None
    for sample in samples:
        if not isinstance(sample, ProviderResourceSample):
            raise TypeError("provider resource series contains an invalid sample")
        if previous is not None and (
            sample.elapsed_ms <= previous.elapsed_ms
            or sample.memory_peak_bytes < previous.memory_peak_bytes
            or sample.memory_high_events < previous.memory_high_events
            or sample.memory_max_events < previous.memory_max_events
            or sample.memory_oom_events < previous.memory_oom_events
            or sample.memory_oom_kill_events < previous.memory_oom_kill_events
            or sample.cpu_usage_usec < previous.cpu_usage_usec
        ):
            raise ValueError("provider resource counters are not monotonic")
        previous = sample


def _linear_memory_slope(samples: Sequence[ProviderResourceSample]) -> int:
    origin_ms = samples[0].elapsed_ms
    elapsed_minutes = [
        (sample.elapsed_ms - origin_ms) / 60_000 for sample in samples
    ]
    memory = [sample.memory_current_bytes for sample in samples]
    mean_time = sum(elapsed_minutes) / len(elapsed_minutes)
    mean_memory = sum(memory) / len(memory)
    denominator = sum((value - mean_time) ** 2 for value in elapsed_minutes)
    if denominator <= 0:
        raise ValueError("provider resource tail interval is too short")
    numerator = sum(
        (elapsed - mean_time) * (current - mean_memory)
        for elapsed, current in zip(elapsed_minutes, memory, strict=True)
    )
    return round(numerator / denominator)


def _private_cache_root(environ: Mapping[str, str]) -> Path:
    raw = environ.get("YAP_EVAL_CACHE", "").strip()
    if not raw:
        raise ValueError("YAP_EVAL_CACHE is required for provider resources")
    requested = Path(raw)
    if not requested.is_absolute() or requested.is_symlink():
        raise ValueError("YAP_EVAL_CACHE must be an absolute real directory")
    repository = Path(__file__).resolve().parents[4]
    resolved = requested.resolve(strict=True)
    if resolved == repository or repository in resolved.parents:
        raise ValueError("YAP_EVAL_CACHE must remain outside the repository")
    metadata = resolved.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("YAP_EVAL_CACHE must be a real directory")
    if os.name == "posix" and stat.S_IMODE(metadata.st_mode) & 0o077:
        raise ValueError("YAP_EVAL_CACHE must use private permissions")
    return resolved


def _private_existing_file(path: Path, *, cache_root: Path) -> Path:
    if not path.is_absolute() or path.is_symlink():
        raise ValueError("provider resource samples must be an absolute real file")
    resolved = path.resolve(strict=True)
    if cache_root not in resolved.parents:
        raise ValueError("provider resource samples must remain inside YAP_EVAL_CACHE")
    metadata = resolved.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ValueError("provider resource samples must be a real file")
    if os.name == "posix" and stat.S_IMODE(metadata.st_mode) & 0o077:
        raise ValueError("provider resource samples must use private permissions")
    return resolved


def _private_output(path: Path, *, cache_root: Path) -> Path:
    if not path.is_absolute() or path.exists() or path.is_symlink():
        raise ValueError("provider resource evidence must be a new absolute file")
    prospective = path.resolve(strict=False)
    if cache_root not in prospective.parents:
        raise ValueError("provider resource evidence must remain inside YAP_EVAL_CACHE")
    parent = prospective.parent.resolve(strict=True)
    metadata = parent.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("provider resource evidence parent must be a real directory")
    if os.name == "posix" and stat.S_IMODE(metadata.st_mode) & 0o077:
        raise ValueError("provider resource evidence parent must use private permissions")
    return prospective


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Summarize private resident-provider cgroup observations",
    )
    parser.add_argument("--samples", type=Path, required=True)
    parser.add_argument("--workload-start-ms", type=int, required=True)
    parser.add_argument("--workload-end-ms", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--system-id")
    parser.add_argument("--completed-request-count", type=int)
    parser.add_argument("--concurrency", type=int)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    cache_root = _private_cache_root(os.environ)
    evidence: dict[str, object] = summarize_provider_resources(
        load_private_resource_samples(arguments.samples),
        workload_start_ms=arguments.workload_start_ms,
        workload_end_ms=arguments.workload_end_ms,
    )
    qualification_arguments = (
        arguments.plan,
        arguments.system_id,
        arguments.completed_request_count,
        arguments.concurrency,
    )
    if any(value is not None for value in qualification_arguments):
        if any(value is None for value in qualification_arguments):
            raise ValueError(
                "provider resource qualification arguments must be provided together"
            )
        plan = load_runtime_evaluation_plan(arguments.plan)
        profile = select_runtime_resource_profile(plan, arguments.system_id)
        evidence = qualify_provider_resources(
            evidence,
            profile=profile,
            completed_request_count=arguments.completed_request_count,
            concurrency=arguments.concurrency,
        )
    output = _private_output(arguments.output, cache_root=cache_root)
    write_private_evidence(output, evidence)
    print(json.dumps(evidence, ensure_ascii=True, separators=(",", ":"), sort_keys=True))
    return 0 if evidence.get("passed", True) is not False else 1


if __name__ == "__main__":
    raise SystemExit(main())
