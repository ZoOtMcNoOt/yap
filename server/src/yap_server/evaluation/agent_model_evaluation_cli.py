from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import urllib.error
import urllib.request
import hashlib

from yap_server.knowledge.vllm_reasoning_client import VllmReasoningClient
from yap_server.private_artifact import read_json_object_with_identity

from .agent_model_acceptance import load_agent_model_acceptance
from .agent_model_evidence import write_new_agent_model_evidence
from .checked_candidate import (
    admit_checked_candidate,
    bind_checked_candidate_evidence,
)
from .agent_model_fixture_runner import run_agent_model_fixtures
from .agent_model_scoring import score_agent_model_results
from .agent_runtime_pressure import run_agent_runtime_pressure
from .agent_vllm_runtime import OwnedAgentVllmRuntime


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--checked-head", required=True)
    parser.add_argument("--candidate-id", required=True)
    arguments = parser.parse_args()
    repository_root = arguments.repository_root.resolve(strict=True)
    evidence_root = _evidence_root(repository_root)
    server_root = repository_root / "server"
    checked_candidate = admit_checked_candidate(
        repository_root=repository_root,
        checked_head=arguments.checked_head,
        input_paths=(
            server_root / "agent-model-acceptance.json",
            server_root / "agent-reasoning-candidates.lock.json",
            server_root / "agent-workload-fixtures.json",
        ),
    )
    acceptance = load_agent_model_acceptance(repository_root)
    runtime_lock, candidate = _candidate_lock(repository_root, arguments.candidate_id)
    owned_runtime = OwnedAgentVllmRuntime(
        checked_head=arguments.checked_head,
        runtime=runtime_lock,
        candidate=candidate,
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
        results = run_agent_model_fixtures(
            repository_root,
            model=str(candidate["model"]),
            request_json=request_json,
        )
        records = tuple(item.record() for item in results)
        score = score_agent_model_results(repository_root, records)
        tracks = acceptance.runtime_tracks
        reasoning_client = VllmReasoningClient(
            endpoint=endpoint,
            model=str(candidate["model"]),
            timeout_seconds=int(tracks["requestTimeoutSeconds"]),
            maximum_response_bytes=4_000_000,
            maximum_output_tokens=int(tracks["maximumOutputTokens"]),
        )
        pressure = run_agent_runtime_pressure(
            repository_root,
            request=reasoning_client,
            dispatched_request=reasoning_client.request,
            memory_bytes=started.memory_bytes,
        )
        child_root = (
            evidence_root / "agent-model" / arguments.candidate_id / "children"
        )
        children = {
            "fixtures": {
                "schemaVersion": 1,
                "checkedHead": arguments.checked_head,
                "candidateId": arguments.candidate_id,
                "results": list(records),
            },
            "pressure": {
                "schemaVersion": 1,
                "checkedHead": arguments.checked_head,
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
                "checkedHead": arguments.checked_head,
                "requestDispatched": pressure.cancellation_dispatched,
                "cancelledRequestCompletionCount": pressure.cancelled_request_completion_count,
            },
            "resources": {
                "schemaVersion": 1,
                "checkedHead": arguments.checked_head,
                "measurementBoundary": "owned-vllm-cgroup-v2",
                "baselineMemoryBytes": pressure.baseline_memory_bytes,
                "peakMemoryBytes": pressure.peak_memory_bytes,
                "sampleCount": pressure.memory_sample_count,
            },
            "lifecycle": {
                "schemaVersion": 1,
                "checkedHead": arguments.checked_head,
                "containerId": started.container_id,
                "imageId": started.image_id,
                "modelArtifactManifestSha256": started.model_artifact_manifest_sha256,
                "launchArgumentsSha256": started.launch_arguments_sha256,
                "endpoint": endpoint,
            },
        }
        child_hashes: dict[str, str] = {}
        for name, value in children.items():
            path = child_root / f"{name}.json"
            write_new_agent_model_evidence(path, value)
            child_hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        receipt = owned_runtime.stop(
            timeout_seconds=int(tracks["teardownTimeoutSeconds"]),
            child_evidence_sha256=child_hashes,
        )
    except BaseException:
        owned_runtime.abort()
        raise
    receipt_path = (
        evidence_root
        / "agent-model"
        / arguments.candidate_id
        / "runtime-receipt.json"
    )
    write_new_agent_model_evidence(receipt_path, receipt)
    runtime_receipt_sha256 = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    destination = (
        evidence_root / "agent-model" / arguments.candidate_id / "results.json"
    )
    checked_candidate.verify_unchanged()
    evidence = bind_checked_candidate_evidence(
        {
            "schemaVersion": 1,
            "candidateId": arguments.candidate_id,
            "model": candidate["model"],
            "revision": candidate["revision"],
            "runtimeReceiptSha256": runtime_receipt_sha256,
            "results": list(records),
            "runtimePressure": {
                "coldLatencyMilliseconds": pressure.cold_latency_milliseconds,
                "warmLatencyMilliseconds": list(pressure.warm_latency_milliseconds),
                "concurrencyLatencyMilliseconds": {
                    str(level): list(values)
                    for level, values in pressure.concurrency_latency_milliseconds.items()
                },
                "baselineUnifiedMemoryBytes": pressure.baseline_memory_bytes,
                "peakUnifiedMemoryBytes": pressure.peak_memory_bytes,
                "isolationLeakCount": pressure.isolation_leak_count,
                "cancelledRequestCompletionCount": pressure.cancelled_request_completion_count,
            },
        },
        checked_candidate,
    )
    write_new_agent_model_evidence(
        destination,
        evidence,
    )
    print(
        json.dumps(
            {
                "candidateId": arguments.candidate_id,
                "caseCount": score.case_count,
                "passed": score.passed,
                "runtimePassed": pressure.isolation_leak_count == 0
                and pressure.cancelled_request_completion_count == 0,
                "privateEvidenceWritten": True,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return (
        0
        if score.passed
        and pressure.isolation_leak_count == 0
        and pressure.cancelled_request_completion_count == 0
        else 1
    )


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


def _evidence_root(repository_root: Path) -> Path:
    value = os.environ.get("YAP_EVAL_CACHE")
    if not value:
        raise ValueError("YAP_EVAL_CACHE is required")
    root = Path(value).resolve(strict=True)
    try:
        root.relative_to(repository_root)
    except ValueError:
        return root
    raise ValueError("agent model evidence must remain outside the repository")


if __name__ == "__main__":
    raise SystemExit(main())
