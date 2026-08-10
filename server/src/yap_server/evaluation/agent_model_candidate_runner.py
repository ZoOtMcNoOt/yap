from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import urllib.error
import urllib.request

from yap_server.knowledge.vllm_reasoning_client import VllmReasoningClient
from yap_server.private_artifact import read_json_object_with_identity

from .agent_model_acceptance import load_agent_model_acceptance
from .agent_model_fixture_runner import run_agent_model_fixtures
from .agent_runtime_pressure import run_agent_runtime_pressure
from .agent_vllm_metrics import AgentVllmActivity
from .agent_vllm_runtime import OwnedAgentVllmRuntime
from .checked_candidate import CheckedCandidate, bind_checked_candidate_evidence
from .vllm_runtime_metrics import VllmRuntimeMetricsClient


@dataclass(frozen=True, slots=True)
class AgentCandidateRun:
    candidate_id: str
    evidence: dict[str, object]
    runtime_receipt: dict[str, object]
    children: dict[str, dict[str, object]]


def run_agent_model_candidate(
    *, checked_candidate: CheckedCandidate, candidate_id: str
) -> AgentCandidateRun:
    """Own one model lifecycle and return evidence without an importable file seam."""

    checked_candidate.verify_unchanged()
    repository_root = checked_candidate.repository_root
    acceptance = load_agent_model_acceptance(repository_root)
    runtime_lock, model_candidate = _candidate_lock(repository_root, candidate_id)
    owned_runtime = OwnedAgentVllmRuntime(
        checked_head=checked_candidate.checked_head,
        runtime=runtime_lock,
        candidate=model_candidate,
    )
    started = owned_runtime.start(
        timeout_seconds=int(acceptance.runtime_tracks["startupTimeoutSeconds"])
    )
    endpoint = started.endpoint

    def request_json(payload: dict[str, object]) -> dict[str, object]:
        request = urllib.request.Request(
            endpoint + "/v1/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = response.read(4_000_001)
        except (urllib.error.URLError, TimeoutError) as error:
            raise RuntimeError("agent model endpoint request failed") from error
        if len(body) > 4_000_000:
            raise ValueError("agent model response exceeds its byte bound")
        try:
            value = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("agent model response is not valid JSON") from error
        if not isinstance(value, dict):
            raise ValueError("agent model response must be an object")
        return value

    try:
        records = tuple(
            item.record()
            for item in run_agent_model_fixtures(
                repository_root,
                model=str(model_candidate["model"]),
                request_json=request_json,
            )
        )
        tracks = acceptance.runtime_tracks
        reasoning_client = VllmReasoningClient(
            endpoint=endpoint,
            model=str(model_candidate["model"]),
            timeout_seconds=int(tracks["requestTimeoutSeconds"]),
            maximum_response_bytes=4_000_000,
            maximum_output_tokens=int(tracks["maximumOutputTokens"]),
        )
        pressure = run_agent_runtime_pressure(
            repository_root,
            request=reasoning_client,
            dispatched_request=reasoning_client.request,
            memory_bytes=started.memory_bytes,
            runtime_activity=AgentVllmActivity(VllmRuntimeMetricsClient(endpoint)),
        )
        children = _children(
            checked_head=checked_candidate.checked_head,
            candidate_id=candidate_id,
            records=records,
            pressure=pressure,
            started=started,
        )
        receipt = owned_runtime.stop(
            timeout_seconds=int(tracks["teardownTimeoutSeconds"]),
            child_evidence_sha256={
                name: agent_evidence_sha256(value) for name, value in children.items()
            },
        )
    except BaseException:
        owned_runtime.abort()
        raise
    checked_candidate.verify_unchanged()
    evidence = bind_checked_candidate_evidence(
        {
            "schemaVersion": 1,
            "candidateId": candidate_id,
            "model": model_candidate["model"],
            "revision": model_candidate["revision"],
            "runtimeReceiptSha256": agent_evidence_sha256(receipt),
            "results": list(records),
            "runtimePressure": {
                "coldLatencyMilliseconds": pressure.cold_latency_milliseconds,
                "warmLatencyMilliseconds": list(pressure.warm_latency_milliseconds),
                "concurrencyLatencyMilliseconds": {
                    str(level): list(values)
                    for level, values in pressure.concurrency_latency_milliseconds.items()
                },
                "baselineCgroupMemoryBytes": pressure.baseline_memory_bytes,
                "peakCgroupMemoryBytes": pressure.peak_memory_bytes,
                "isolationLeakCount": pressure.isolation_leak_count,
                "cancelledRequestCompletionCount": pressure.cancelled_request_completion_count,
            },
        },
        checked_candidate,
    )
    return AgentCandidateRun(candidate_id, evidence, receipt, children)


def agent_evidence_sha256(value: object) -> str:
    body = json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def _children(*, checked_head, candidate_id, records, pressure, started):
    return {
        "fixtures": {
            "schemaVersion": 1,
            "checkedHead": checked_head,
            "candidateId": candidate_id,
            "results": list(records),
        },
        "pressure": {
            "schemaVersion": 1,
            "checkedHead": checked_head,
            "coldLatencyMilliseconds": pressure.cold_latency_milliseconds,
            "warmLatencyMilliseconds": list(pressure.warm_latency_milliseconds),
            "concurrencyLatencyMilliseconds": {
                str(level): list(values)
                for level, values in pressure.concurrency_latency_milliseconds.items()
            },
            "isolationLeakCount": pressure.isolation_leak_count,
            "isolationConcurrent": pressure.isolation_concurrent,
        },
        "cancellation": {
            "schemaVersion": 1,
            "checkedHead": checked_head,
            "requestDispatched": pressure.cancellation_dispatched,
            "engineActivityObserved": pressure.engine_activity_observed,
            "engineIdleAfterCancellation": pressure.engine_idle_after_cancellation,
            "recoverySucceeded": pressure.recovery_succeeded,
            "engineFinishReasons": dict(pressure.cancellation_engine_finish_reasons),
            "recoveryEngineFinishReasons": dict(
                pressure.recovery_engine_finish_reasons
            ),
            "cancelledRequestCompletionCount": pressure.cancelled_request_completion_count,
        },
        "resources": {
            "schemaVersion": 1,
            "checkedHead": checked_head,
            "measurementBoundary": "owned-vllm-cgroup-v2",
            "baselineMemoryBytes": pressure.baseline_memory_bytes,
            "peakMemoryBytes": pressure.peak_memory_bytes,
            "sampleCount": pressure.memory_sample_count,
        },
        "lifecycle": {
            "schemaVersion": 1,
            "checkedHead": checked_head,
            "containerId": started.container_id,
            "imageId": started.image_id,
            "modelArtifactManifestSha256": started.model_artifact_manifest_sha256,
            "launchArgumentsSha256": started.launch_arguments_sha256,
            "endpoint": started.endpoint,
        },
    }


def _candidate_lock(
    repository_root: Path, candidate_id: str
) -> tuple[dict[str, object], dict[str, object]]:
    acceptance = load_agent_model_acceptance(repository_root)
    lock, _identity = read_json_object_with_identity(
        repository_root / "server" / "agent-reasoning-candidates.lock.json",
        maximum_bytes=64_000,
        field="agent reasoning candidate lock",
        expected_sha256=acceptance.candidate_lock_sha256,
        containment_root=repository_root,
    )
    candidates = lock["candidates"]
    assert isinstance(candidates, list)
    matches = [item for item in candidates if item["candidateId"] == candidate_id]
    if len(matches) != 1:
        raise ValueError("agent model candidate is not admitted")
    runtime = lock["runtime"]
    if not isinstance(runtime, dict):
        raise ValueError("agent runtime lock is invalid")
    return runtime, matches[0]


__all__ = [
    "AgentCandidateRun",
    "agent_evidence_sha256",
    "run_agent_model_candidate",
]
