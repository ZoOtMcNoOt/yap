from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Mapping

from yap_server.limits import MAX_WORKER_RESULT_BYTES
from yap_server.pools.batch_asr_worker import MAX_AUDIO_SECONDS, SAMPLE_RATE_HZ


_MAX_PLAN_BYTES = 64 * 1024
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_SYSTEMS = {
    "local-live-nemotron": (
        "localLive",
        "executable",
        "none",
        "desktop-prepared-audio-frame-to-final",
    ),
    "transformers-cohere-reference": (
        "serverBatch",
        "reference",
        "none",
        "service-create-to-result",
    ),
    "vllm-cohere-batch": (
        "serverBatch",
        "executable",
        "none",
        "service-create-to-result",
    ),
    "transformers-nemotron-reference": (
        "serverBatch",
        "reference",
        "none",
        "service-create-to-result",
    ),
    "nemo-nemotron-finalized": (
        "serverFinalizedUtterance",
        "executable",
        "none",
        "resident-loopback-release-to-result",
    ),
}
_LADDERS = {
    "live-endpoint": (
        4_000,
        8_000,
        12_000,
        16_000,
        17_920,
        32_000,
        80_000,
        160_000,
        480_000,
    ),
    "server-finalized-utterance": (
        4_000,
        8_000,
        12_000,
        16_000,
        17_920,
        32_000,
        80_000,
        160_000,
        480_000,
    ),
    "live-session": (
        480_000,
        4_800_000,
        14_400_000,
        28_800_000,
        57_600_000,
        115_200_000,
    ),
    "batch-file": (
        480_000,
        1_920_000,
        4_800_000,
        14_400_000,
        28_800_000,
        57_600_000,
        115_200_000,
    ),
}
_LADDER_SYSTEMS = {
    "live-endpoint": ("local-live-nemotron",),
    "server-finalized-utterance": ("nemo-nemotron-finalized",),
    "live-session": ("local-live-nemotron",),
    "batch-file": (
        "transformers-cohere-reference",
        "vllm-cohere-batch",
        "transformers-nemotron-reference",
        "nemo-nemotron-finalized",
    ),
}
_LADDER_EXECUTION = {
    "live-endpoint": ("realtime", "natural"),
    "server-finalized-utterance": ("unpaced", "natural"),
    "live-session": ("realtime", "natural-and-deterministic"),
    "batch-file": ("unpaced", "natural-and-deterministic"),
}
_BOUNDARIES = {
    "batch-maximum-exact": (MAX_AUDIO_SECONDS * SAMPLE_RATE_HZ,),
    "batch-maximum-plus-one": (MAX_AUDIO_SECONDS * SAMPLE_RATE_HZ + 1,),
    "vllm-concurrent-request-admission": (1, 2, 4, 8),
    "nemo-concurrent-stream-admission": (1, 2, 4, 8),
    "worker-result-envelope": (
        MAX_WORKER_RESULT_BYTES,
        MAX_WORKER_RESULT_BYTES + 1,
    ),
}
_BOUNDARY_UNITS = {
    "batch-maximum-exact": "audioSamples",
    "batch-maximum-plus-one": "audioSamples",
    "vllm-concurrent-request-admission": "concurrentRequests",
    "nemo-concurrent-stream-admission": "concurrentRequests",
    "worker-result-envelope": "bytes",
}
_BOUNDARY_EXPECTATIONS = {
    "batch-maximum-exact": "complete",
    "batch-maximum-plus-one": "reject-before-inference",
    "vllm-concurrent-request-admission": (
        "independent-requests-use-vllm-continuous-batching"
    ),
    "nemo-concurrent-stream-admission": (
        "independent-requests-use-native-stream-batching"
    ),
    "worker-result-envelope": "accept-first-reject-second",
}
_BOUNDARY_SYSTEMS = {
    "batch-maximum-exact": "all-batch-adapters",
    "batch-maximum-plus-one": "all-batch-adapters",
    "vllm-concurrent-request-admission": "vllm-cohere-batch",
    "nemo-concurrent-stream-admission": "nemo-nemotron-finalized",
    "worker-result-envelope": "all-batch-adapters",
}
_LOAD_CASE_CONTRACTS = {
    "vllm-short-tail": (
        "vllm-cohere-batch",
        "vllm-http-release-to-result",
        ((480_000, 200),),
        (1, 2, 4, 8),
        200,
        "complete",
    ),
    "vllm-long-waves": (
        "vllm-cohere-batch",
        "service-create-to-result",
        ((14_400_000, 4),),
        (2,),
        4,
        "complete",
    ),
    "vllm-mixed-eight": (
        "vllm-cohere-batch",
        "service-create-to-result",
        ((480_000, 4), (14_400_000, 2), (28_800_000, 2)),
        (8,),
        8,
        "complete",
    ),
    "vllm-cancelled-sibling": (
        "vllm-cohere-batch",
        "vllm-http-release-to-result",
        ((524_287, 1), (262_144, 1), (16_000, 1)),
        (2,),
        2,
        "cancel-dispatched-follower-record-server-outcome-leader-and-"
        "recovery-singletons",
    ),
    "vllm-slot-capacity": (
        "vllm-cohere-batch",
        "yap-batch-pool-admission",
        ((480_000, 17),),
        (17,),
        16,
        "sixteen-complete-one-retryable-pool-busy-then-recovery",
    ),
    "transformers-reference-slot-capacity": (
        "transformers-cohere-reference",
        "service-admission",
        ((480_000, 4),),
        (4,),
        3,
        "three-complete-one-retryable-server-busy",
    ),
    "vllm-pcm-capacity": (
        "vllm-cohere-batch",
        "yap-batch-pool-admission",
        ((115_200_000, 2), (16_000, 1)),
        (3,),
        2,
        "two-complete-one-retryable-pcm-busy-then-recovery",
    ),
    "nemotron-reference-fixed-short-tail": (
        "transformers-nemotron-reference",
        "isolated-container-release-to-result",
        ((480_000, 200),),
        (1, 2, 4, 8),
        200,
        "complete",
    ),
    "nemotron-reference-dynamic-parity": (
        "transformers-nemotron-reference",
        "checked-contract-to-reference-result",
        ((480_000, 8),),
        (1, 8),
        8,
        "exact-transcript-and-language-segment-contract-parity",
    ),
    "nemotron-reference-long-windows": (
        "transformers-nemotron-reference",
        "service-create-to-result",
        ((480_000, 2), (14_400_000, 2)),
        (2,),
        4,
        "complete-source-plan-continuity",
    ),
    "nemotron-reference-cancelled-window": (
        "transformers-nemotron-reference",
        "isolated-container-release-to-result",
        ((524_287, 1), (262_144, 1), (16_000, 1)),
        (2,),
        2,
        "cancel-dispatched-follower-record-server-outcome-leader-and-"
        "recovery-singletons",
    ),
    "nemo-finalized-short-tail": (
        "nemo-nemotron-finalized",
        "resident-loopback-release-to-result",
        ((480_000, 200),),
        (1, 2, 4, 8),
        200,
        "complete",
    ),
    "nemo-finalized-fixed-auto-parity": (
        "nemo-nemotron-finalized",
        "checked-contract-to-resident-result",
        ((480_000, 8),),
        (1, 8),
        8,
        "fixed-and-auto-lexical-language-contract-parity",
    ),
    "nemo-finalized-long-windows": (
        "nemo-nemotron-finalized",
        "resident-loopback-release-to-result",
        ((480_000, 2), (14_400_000, 2)),
        (2,),
        4,
        "complete-source-plan-continuity",
    ),
    "nemo-finalized-cancelled-sibling": (
        "nemo-nemotron-finalized",
        "resident-loopback-release-to-result",
        ((524_287, 1), (262_144, 1), (16_000, 1)),
        (2,),
        2,
        "cancel-one-preserve-sibling-and-immediate-recovery",
    ),
    "nemo-finalized-active-capacity": (
        "nemo-nemotron-finalized",
        "resident-service-admission",
        ((14_400_000, 9),),
        (9,),
        8,
        "eight-complete-one-retryable-service-busy",
    ),
}
_REQUIRED_METRICS = {
    "identity",
    "accuracy",
    "sentinelIntegrity",
    "submitToResultLatency",
    "realtimeFactor",
    "queueTime",
    "throughput",
    "resourceCurrentAndPeak",
    "resourceSlope",
    "cancellationRecovery",
    "teardown",
    "rejectionAndRetry",
}
_RESOURCE_PROFILES = {
    "vllm-cohere-batch": (
        "vllm-short-tail",
        "dgx-spark-gb10",
        8,
        1_600,
        60_000,
        200,
        4 * 1024**3,
        8 * 1024**3,
        5 * 1024**3,
        64 * 1024**2,
        256,
        128,
        True,
    ),
    "nemo-nemotron-finalized": (
        "nemo-finalized-short-tail",
        "dgx-spark-gb10",
        8,
        1_600,
        60_000,
        200,
        5 * 1024**3,
        8 * 1024**3,
        14 * 1024**3,
        64 * 1024**2,
        256,
        256,
        True,
    ),
}


@dataclass(frozen=True, slots=True)
class RuntimeLoadMix:
    duration_samples: int
    count: int


@dataclass(frozen=True, slots=True)
class RuntimeLoadCase:
    identifier: str
    system_id: str
    measurement_boundary: str
    mix: tuple[RuntimeLoadMix, ...]
    concurrencies: tuple[int, ...]
    minimum_completions: int
    expected: str


@dataclass(frozen=True, slots=True)
class RuntimeResourceProfile:
    system_id: str
    load_case_id: str
    hardware_profile: str
    concurrency: int
    completed_request_count: int
    minimum_tail_duration_ms: int
    minimum_tail_sample_count: int
    maximum_memory_current_bytes: int
    maximum_memory_peak_bytes: int
    maximum_container_entrypoint_virtual_data_bytes: int
    maximum_absolute_tail_virtual_data_window_median_growth_bytes: int
    maximum_cgroup_task_count: int
    maximum_container_entrypoint_thread_count: int
    require_zero_memory_events: bool


@dataclass(frozen=True, slots=True)
class RuntimeEvaluationPlanSnapshot:
    plan: dict[str, object]
    sha256: str


def select_runtime_load_case(
    plan: Mapping[str, object],
    identifier: str,
) -> RuntimeLoadCase:
    """Select one already validated load cell without private input details."""

    validate_runtime_evaluation_plan(plan)
    if not isinstance(identifier, str) or _IDENTIFIER.fullmatch(identifier) is None:
        raise ValueError("runtime load case ID is invalid")
    loads = plan.get("loadCases")
    if not isinstance(loads, list):
        raise ValueError("runtime evaluation plan omitted load cases")
    matches = [
        item
        for item in loads
        if isinstance(item, dict) and item.get("id") == identifier
    ]
    if len(matches) != 1:
        raise ValueError("runtime load case was not found")
    load = matches[0]
    mix = load["mix"]
    concurrencies = load["concurrencies"]
    if not isinstance(mix, list) or not isinstance(concurrencies, list):
        raise RuntimeError("validated runtime load case changed shape")
    return RuntimeLoadCase(
        identifier=identifier,
        system_id=str(load["systemId"]),
        measurement_boundary=str(load["measurementBoundary"]),
        mix=tuple(
            RuntimeLoadMix(
                duration_samples=int(item["durationSamples"]),
                count=int(item["count"]),
            )
            for item in mix
            if isinstance(item, dict)
        ),
        concurrencies=tuple(int(value) for value in concurrencies),
        minimum_completions=int(load["minimumCompletions"]),
        expected=str(load["expected"]),
    )


def select_runtime_resource_profile(
    plan: Mapping[str, object],
    system_id: str,
) -> RuntimeResourceProfile:
    """Select one validated GB10 provider resource contract."""

    validate_runtime_evaluation_plan(plan)
    if not isinstance(system_id, str) or _IDENTIFIER.fullmatch(system_id) is None:
        raise ValueError("runtime resource system ID is invalid")
    profiles = plan.get("resourceProfiles")
    if not isinstance(profiles, list):
        raise ValueError("runtime evaluation plan omitted resource profiles")
    matches = [
        item
        for item in profiles
        if isinstance(item, dict) and item.get("systemId") == system_id
    ]
    if len(matches) != 1:
        raise ValueError("runtime resource profile was not found")
    profile = matches[0]
    return RuntimeResourceProfile(
        system_id=system_id,
        load_case_id=str(profile["loadCaseId"]),
        hardware_profile=str(profile["hardwareProfile"]),
        concurrency=int(profile["concurrency"]),
        completed_request_count=int(profile["completedRequestCount"]),
        minimum_tail_duration_ms=int(profile["minimumTailDurationMs"]),
        minimum_tail_sample_count=int(profile["minimumTailSampleCount"]),
        maximum_memory_current_bytes=int(profile["maximumMemoryCurrentBytes"]),
        maximum_memory_peak_bytes=int(profile["maximumMemoryPeakBytes"]),
        maximum_container_entrypoint_virtual_data_bytes=int(
            profile["maximumContainerEntrypointVirtualDataBytes"]
        ),
        maximum_absolute_tail_virtual_data_window_median_growth_bytes=int(
            profile["maximumAbsoluteTailVirtualDataWindowMedianGrowthBytes"]
        ),
        maximum_cgroup_task_count=int(profile["maximumCgroupTaskCount"]),
        maximum_container_entrypoint_thread_count=int(
            profile["maximumContainerEntrypointThreadCount"]
        ),
        require_zero_memory_events=bool(profile["requireZeroMemoryEvents"]),
    )


def load_runtime_evaluation_plan(path: Path) -> dict[str, object]:
    return load_runtime_evaluation_plan_snapshot(path).plan


def load_runtime_evaluation_plan_snapshot(
    path: Path,
) -> RuntimeEvaluationPlanSnapshot:
    """Read, validate, and hash one immutable in-memory plan snapshot."""

    resolved = path.resolve(strict=True)
    body = resolved.read_bytes()
    if not body or len(body) > _MAX_PLAN_BYTES:
        raise ValueError("runtime evaluation plan size is invalid")
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("runtime evaluation plan is not valid JSON") from error
    validate_runtime_evaluation_plan(payload)
    return RuntimeEvaluationPlanSnapshot(
        plan=dict(payload),
        sha256=hashlib.sha256(body).hexdigest(),
    )


def validate_runtime_evaluation_plan(value: object) -> None:
    root = _object(
        value,
        {
            "schemaVersion",
            "sampleRateHz",
            "privateCache",
            "systems",
            "durationLadders",
            "boundaryCases",
            "loadCases",
            "resourceProfiles",
            "requiredMetrics",
        },
        "runtime evaluation plan",
    )
    if root["schemaVersion"] != 5 or root["sampleRateHz"] != SAMPLE_RATE_HZ:
        raise ValueError("runtime evaluation plan identity is invalid")
    private_cache = _object(
        root["privateCache"],
        {"environment", "repositoryFallback"},
        "private cache",
    )
    if private_cache != {
        "environment": "YAP_EVAL_CACHE",
        "repositoryFallback": False,
    }:
        raise ValueError("runtime evaluation data must stay outside the repository")

    systems: dict[str, tuple[str, str, str, str]] = {}
    for item in _array(root["systems"], "systems"):
        system = _object(
            item,
            {
                "id",
                "mode",
                "status",
                "terminologyContextSupport",
                "measurementBoundary",
            },
            "runtime system",
        )
        identifier = _identifier(system["id"], "runtime system ID")
        if identifier in systems:
            raise ValueError("runtime system IDs must be unique")
        systems[identifier] = (
            _text(system["mode"], "runtime mode"),
            _text(system["status"], "runtime status"),
            _text(
                system["terminologyContextSupport"],
                "terminology context support",
            ),
            _text(system["measurementBoundary"], "runtime measurement boundary"),
        )
    if systems != _SYSTEMS:
        raise ValueError("runtime systems differ from the qualification contract")

    ladders: dict[str, tuple[int, ...]] = {}
    ladder_systems: dict[str, tuple[str, ...]] = {}
    ladder_execution: dict[str, tuple[str, str]] = {}
    for item in _array(root["durationLadders"], "duration ladders"):
        ladder = _object(
            item,
            {"id", "systemIds", "durationSamples", "pacing", "evidenceKind"},
            "duration ladder",
        )
        identifier = _identifier(ladder["id"], "duration ladder ID")
        if identifier in ladders:
            raise ValueError("duration ladder IDs must be unique")
        system_ids = tuple(
            _identifier(system_id, "duration ladder system ID")
            for system_id in _array(ladder["systemIds"], "duration ladder systems")
        )
        if not system_ids or any(system_id not in systems for system_id in system_ids):
            raise ValueError("duration ladder refers to an unknown runtime system")
        if len(set(system_ids)) != len(system_ids):
            raise ValueError("duration ladder runtime systems must be unique")
        ladder_execution[identifier] = (
            _text(ladder["pacing"], "duration pacing"),
            _text(ladder["evidenceKind"], "duration evidence kind"),
        )
        durations = _positive_int_tuple(ladder["durationSamples"], "duration samples")
        if tuple(sorted(set(durations))) != durations:
            raise ValueError("duration ladder must be unique and increasing")
        ladders[identifier] = durations
        ladder_systems[identifier] = system_ids
    if ladders != _LADDERS:
        raise ValueError("duration ladders differ from the qualification contract")
    if ladder_systems != _LADDER_SYSTEMS:
        raise ValueError("duration ladder systems differ from the qualification contract")
    if ladder_execution != _LADDER_EXECUTION:
        raise ValueError("duration ladder execution differs from the qualification contract")

    boundaries: dict[str, tuple[int, ...]] = {}
    boundary_expectations: dict[str, str] = {}
    boundary_systems: dict[str, str] = {}
    boundary_units: dict[str, str] = {}
    for item in _array(root["boundaryCases"], "boundary cases"):
        boundary = _object(
            item,
            {"id", "systemId", "unit", "values", "expected"},
            "boundary case",
        )
        identifier = _identifier(boundary["id"], "boundary case ID")
        if identifier in boundaries:
            raise ValueError("boundary case IDs must be unique")
        boundary_systems[identifier] = _text(
            boundary["systemId"],
            "boundary system ID",
        )
        boundary_units[identifier] = _text(boundary["unit"], "boundary unit")
        boundary_expectations[identifier] = _text(
            boundary["expected"],
            "boundary expectation",
        )
        boundaries[identifier] = _positive_int_tuple(
            boundary["values"],
            "boundary values",
        )
    if boundaries != _BOUNDARIES:
        raise ValueError("runtime boundaries differ from the qualification contract")
    if boundary_expectations != _BOUNDARY_EXPECTATIONS:
        raise ValueError(
            "runtime boundary expectations differ from the qualification contract"
        )
    if boundary_systems != _BOUNDARY_SYSTEMS:
        raise ValueError("runtime boundary systems differ from the qualification contract")
    if boundary_units != _BOUNDARY_UNITS:
        raise ValueError("runtime boundary units differ from the qualification contract")

    load_ids: set[str] = set()
    load_shapes: dict[
        str,
        tuple[
            str,
            str,
            tuple[tuple[int, int], ...],
            tuple[int, ...],
            int,
            str,
        ],
    ] = {}
    for item in _array(root["loadCases"], "load cases"):
        load = _object(
            item,
            {
                "id",
                "systemId",
                "measurementBoundary",
                "mix",
                "concurrencies",
                "minimumCompletions",
                "expected",
            },
            "load case",
        )
        identifier = _identifier(load["id"], "load case ID")
        system_id = _identifier(load["systemId"], "load case system ID")
        if identifier in load_ids or system_id not in systems:
            raise ValueError("load case identity is invalid")
        load_ids.add(identifier)
        measurement_boundary = _text(
            load["measurementBoundary"],
            "load measurement boundary",
        )
        expected = _text(load["expected"], "load expectation")
        concurrencies = _positive_int_tuple(load["concurrencies"], "concurrencies")
        if tuple(sorted(set(concurrencies))) != concurrencies:
            raise ValueError("load concurrencies must be unique and increasing")
        minimum = _positive_int(load["minimumCompletions"], "minimum completions")
        total = 0
        mix_entries: list[tuple[int, int]] = []
        for item in _array(load["mix"], "load mix"):
            mix = _object(item, {"durationSamples", "count"}, "load mix entry")
            duration = _positive_int(
                mix["durationSamples"],
                "load duration samples",
            )
            count = _positive_int(mix["count"], "load request count")
            total += count
            mix_entries.append((duration, count))
        if total < minimum:
            raise ValueError("minimum completions exceed the load request count")
        load_shapes[identifier] = (
            system_id,
            measurement_boundary,
            tuple(mix_entries),
            concurrencies,
            minimum,
            expected,
        )
    if load_shapes != _LOAD_CASE_CONTRACTS:
        raise ValueError("load cases differ from the qualification contract")

    resource_profiles: dict[str, tuple[object, ...]] = {}
    for item in _array(root["resourceProfiles"], "resource profiles"):
        profile = _object(
            item,
            {
                "systemId",
                "loadCaseId",
                "hardwareProfile",
                "concurrency",
                "completedRequestCount",
                "minimumTailDurationMs",
                "minimumTailSampleCount",
                "maximumMemoryCurrentBytes",
                "maximumMemoryPeakBytes",
                "maximumContainerEntrypointVirtualDataBytes",
                "maximumAbsoluteTailVirtualDataWindowMedianGrowthBytes",
                "maximumCgroupTaskCount",
                "maximumContainerEntrypointThreadCount",
                "requireZeroMemoryEvents",
            },
            "resource profile",
        )
        system_id = _identifier(profile["systemId"], "resource system ID")
        load_case_id = _identifier(profile["loadCaseId"], "resource load case ID")
        if (
            system_id in resource_profiles
            or system_id not in systems
            or load_case_id not in load_ids
            or load_shapes[load_case_id][0] != system_id
        ):
            raise ValueError("resource profile identity is invalid")
        require_zero = profile["requireZeroMemoryEvents"]
        if not isinstance(require_zero, bool):
            raise ValueError("resource memory-event requirement is invalid")
        resource_profiles[system_id] = (
            load_case_id,
            _identifier(profile["hardwareProfile"], "resource hardware profile"),
            _positive_int(profile["concurrency"], "resource concurrency"),
            _positive_int(
                profile["completedRequestCount"],
                "resource completed request count",
            ),
            _positive_int(
                profile["minimumTailDurationMs"],
                "resource tail duration",
            ),
            _positive_int(
                profile["minimumTailSampleCount"],
                "resource tail sample count",
            ),
            _positive_int(
                profile["maximumMemoryCurrentBytes"],
                "resource current-memory ceiling",
            ),
            _positive_int(
                profile["maximumMemoryPeakBytes"],
                "resource peak-memory ceiling",
            ),
            _positive_int(
                profile["maximumContainerEntrypointVirtualDataBytes"],
                "resource virtual-data ceiling",
            ),
            _positive_int(
                profile[
                    "maximumAbsoluteTailVirtualDataWindowMedianGrowthBytes"
                ],
                "resource allocation-extent growth ceiling",
            ),
            _positive_int(
                profile["maximumCgroupTaskCount"],
                "resource task-count ceiling",
            ),
            _positive_int(
                profile["maximumContainerEntrypointThreadCount"],
                "resource thread-count ceiling",
            ),
            require_zero,
        )
    if resource_profiles != _RESOURCE_PROFILES:
        raise ValueError("resource profiles differ from the qualification contract")

    metric_values = tuple(
        _text(metric, "required metric")
        for metric in _array(root["requiredMetrics"], "required metrics")
    )
    metrics = set(metric_values)
    if len(metrics) != len(metric_values):
        raise ValueError("required metrics must be unique")
    if metrics != _REQUIRED_METRICS:
        raise ValueError("required metrics differ from the qualification contract")


def plan_summary(path: Path) -> dict[str, object]:
    snapshot = load_runtime_evaluation_plan_snapshot(path)
    payload = snapshot.plan
    return {
        "schemaVersion": 1,
        "sha256": snapshot.sha256,
        "systemCount": len(payload["systems"]),  # type: ignore[arg-type]
        "durationLadderCount": len(
            payload["durationLadders"]  # type: ignore[arg-type]
        ),
        "boundaryCaseCount": len(payload["boundaryCases"]),  # type: ignore[arg-type]
        "loadCaseCount": len(payload["loadCases"]),  # type: ignore[arg-type]
        "resourceProfileCount": len(
            payload["resourceProfiles"]  # type: ignore[arg-type]
        ),
    }


def _object(value: object, keys: set[str], field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise ValueError(f"{field} fields differ from the contract")
    return value


def _array(value: object, field: str) -> list[object]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field} must be a non-empty array")
    return value


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be non-empty text")
    return value


def _identifier(value: object, field: str) -> str:
    parsed = _text(value, field)
    if _IDENTIFIER.fullmatch(parsed) is None:
        raise ValueError(f"{field} is invalid")
    return parsed


def _positive_int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _positive_int_tuple(value: object, field: str) -> tuple[int, ...]:
    return tuple(_positive_int(item, field) for item in _array(value, field))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate the ASR runtime qualification plan")
    parser.add_argument("--plan", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    print(
        json.dumps(
            plan_summary(arguments.plan),
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
