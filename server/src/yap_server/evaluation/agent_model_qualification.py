"""Qualify workload-specific agent routes from complete checked evidence."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import shutil
import sys
import tempfile
import re

from yap_server.evaluation.provider_runtime_observations import (
    canonical_evidence_sha256,
)
from yap_server.private_artifact import read_json_object_with_identity

from .agent_model_acceptance import load_agent_model_acceptance
from .agent_model_candidate_runner import (
    FailedAgentCandidateRun,
    OwnedAgentCandidateRun,
    agent_evidence_sha256,
    run_agent_model_candidate,
)
from .private_json_evidence import write_new_private_json_evidence
from .agent_model_scoring import score_agent_model_results
from .agent_vllm_runtime import build_agent_vllm_launch_arguments
from .checked_candidate import (
    CheckedCandidate,
    admit_checked_candidate,
    bind_checked_candidate_evidence,
)


_INPUTS = (
    Path("server/agent-model-acceptance.json"),
    Path("server/agent-reasoning-candidates.lock.json"),
    Path("server/agent-workload-fixtures.json"),
)
_EVIDENCE_KEYS = {
    "schemaVersion",
    "candidateId",
    "model",
    "revision",
    "results",
    "runtimePressure",
    "candidate",
    "runtimeReceiptSha256",
    "evidenceSha256",
}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PRESSURE_KEYS = {
    "coldLatencyMilliseconds",
    "warmLatencyMilliseconds",
    "concurrencyLatencyMilliseconds",
    "baselineCgroupMemoryBytes",
    "peakCgroupMemoryBytes",
    "isolationLeakCount",
    "cancelledRequestCompletionCount",
}


def evaluate_agent_model_qualification(
    *,
    candidate: CheckedCandidate,
    runs: tuple[OwnedAgentCandidateRun, ...],
) -> dict[str, object]:
    """Select only from model runs owned by this checked process."""

    acceptance = load_agent_model_acceptance(candidate.repository_root)
    models = _candidate_models(
        candidate.repository_root, acceptance.candidate_lock_sha256
    )
    run_by_id = {run.candidate_id: run for run in runs}
    if len(run_by_id) != len(runs) or set(run_by_id) != set(acceptance.candidate_ids):
        raise ValueError("agent model run set is incomplete")
    candidate.verify_unchanged()
    summaries = [
        _candidate_summary(
            candidate,
            run_by_id[candidate_id],
            expected=models[candidate_id],
            route_policy=acceptance.route_evidence[
                str(models[candidate_id]["workloadClass"])
            ],
        )
        for candidate_id in acceptance.candidate_ids
    ]
    summary_by_id = {str(summary["candidateId"]): summary for summary in summaries}
    admitted_candidates = {
        candidate_id
        for candidate_id in acceptance.required_routes.values()
        if summary_by_id[candidate_id]["eligible"]
    }
    if admitted_candidates != set(acceptance.required_routes.values()):
        outcome = "deterministic-no-model"
        admitted_candidates = set()
        reasons = ["required-workload-route-did-not-meet-acceptance"]
    else:
        outcome = "required-workload-routes-qualified"
        reasons = ["every-required-workload-route-passed-frozen-evidence"]
    decision = {
        "schemaVersion": 1,
        "qualificationScope": "governed-agent-reasoning",
        "outcome": outcome,
        "admittedModelCandidates": sorted(admitted_candidates),
        "reasonCodes": reasons,
        "candidateSummaries": summaries,
    }
    candidate.verify_unchanged()
    return bind_checked_candidate_evidence(decision, candidate)


def _candidate_summary(
    candidate: CheckedCandidate,
    run: OwnedAgentCandidateRun,
    *,
    expected: dict[str, object],
    route_policy: object,
) -> dict[str, object]:
    if isinstance(run, FailedAgentCandidateRun):
        return _failed_candidate_summary(candidate, run, expected=expected)
    evidence = run.evidence
    if set(evidence) != _EVIDENCE_KEYS or evidence["schemaVersion"] != 2:
        raise ValueError("agent model candidate evidence differs from the contract")
    supplied_hash = evidence["evidenceSha256"]
    unhashed = dict(evidence)
    unhashed.pop("evidenceSha256")
    if supplied_hash != canonical_evidence_sha256(unhashed):
        raise ValueError("agent model candidate evidence digest differs")
    expected_binding = {
        "checkedHead": candidate.checked_head,
        "repositoryState": "clean",
        "inputs": dict(sorted(candidate.input_sha256.items())),
    }
    if evidence["candidate"] != expected_binding:
        raise ValueError("agent model candidate binding differs")
    if (
        evidence["candidateId"] != expected["candidateId"]
        or evidence["model"] != expected["model"]
        or evidence["revision"] != expected["revision"]
    ):
        raise ValueError("agent model candidate identity differs")
    runtime_receipt_sha256 = agent_evidence_sha256(run.runtime_receipt)
    if evidence["runtimeReceiptSha256"] != runtime_receipt_sha256:
        raise ValueError("agent model runtime receipt binding differs")
    _validate_runtime_receipt(
        candidate,
        expected=expected,
        receipt=run.runtime_receipt,
        children=run.children,
    )
    results = evidence["results"]
    if not isinstance(results, list):
        raise ValueError("agent model candidate results are invalid")
    score = score_agent_model_results(
        candidate.repository_root,
        tuple(results),
        workload_class=str(expected["workloadClass"]),
    )
    pressure = _runtime_pressure(evidence["runtimePressure"])
    _verify_runtime_children(
        run.children,
        checked_head=candidate.checked_head,
        evidence_results=results,
        pressure=pressure,
    )
    warm_p95 = _p95(pressure["warmLatencyMilliseconds"])
    c8_p95 = _p95(pressure["concurrencyLatencyMilliseconds"]["8"])
    fixture_p95 = _p95(score.latency_milliseconds)
    route_evidence_passed = _route_evidence_passed(
        route_policy,
        workload_class=str(expected["workloadClass"]),
        results=results,
        fixture_p95=fixture_p95,
        warm_p95=warm_p95,
        c8_p95=c8_p95,
        route_specific_evidence_passed=score.route_specific_evidence_passed,
    )
    eligible = (
        score.passed
        and pressure["isolationLeakCount"] == 0
        and pressure["cancelledRequestCompletionCount"] == 0
        and route_evidence_passed
    )
    return {
        "candidateId": expected["candidateId"],
        "workloadClass": expected["workloadClass"],
        "artifactSha256": agent_evidence_sha256(evidence),
        "eligible": eligible,
        "routeEvidencePassed": route_evidence_passed,
        "toolSelectionAccuracy": score.tool_selection_accuracy,
        "structuredArgumentAccuracy": score.structured_argument_accuracy,
        "citationFidelity": score.citation_fidelity,
        "terminologyPreservation": score.terminology_preservation,
        "isolationLeakCount": score.isolation_leak_count,
        "invalidStructuredOutputCount": score.invalid_structured_output_count,
        "concurrencyC8P95LatencyMilliseconds": c8_p95,
        "fixtureP95LatencyMilliseconds": fixture_p95,
        "warmP95LatencyMilliseconds": warm_p95,
        "incrementalCgroupMemoryBytes": max(
            0,
            pressure["peakCgroupMemoryBytes"] - pressure["baselineCgroupMemoryBytes"],
        ),
    }


def _route_evidence_passed(
    policy: object,
    *,
    workload_class: str,
    results: list[object],
    fixture_p95: int,
    warm_p95: int,
    c8_p95: int,
    route_specific_evidence_passed: bool,
) -> bool:
    if not isinstance(policy, dict):
        raise ValueError("agent route evidence policy is invalid")
    if workload_class == "rapid-automation":
        return (
            fixture_p95 <= policy["maximumFixtureP95LatencyMilliseconds"]
            and
            warm_p95 <= policy["maximumWarmP95LatencyMilliseconds"]
            and c8_p95 <= policy["maximumC8P95LatencyMilliseconds"]
        )
    if workload_class == "complex-orchestration":
        required = policy["requiredMultiStepCaseId"]
        return route_specific_evidence_passed and any(
            isinstance(result, dict)
            and result.get("caseId") == required
            and [
                call.get("name") for call in result["toolCalls"] if isinstance(call, dict)
            ]
            == ["search_knowledge", "traverse_knowledge", "propose_knowledge"]
            for result in results
            if isinstance(result, dict)
            and isinstance(result.get("toolCalls"), list)
            and len(result["toolCalls"]) == 3
        )
    raise ValueError("agent workload class is invalid")


def _failed_candidate_summary(
    candidate: CheckedCandidate,
    run: FailedAgentCandidateRun,
    *,
    expected: dict[str, object],
) -> dict[str, object]:
    failure = run.failure
    if (
        set(failure)
        != {
            "schemaVersion",
            "candidateId",
            "model",
            "revision",
            "artifactManifestSha256",
            "stage",
            "reasonCode",
            "errorType",
            "diagnostic",
            "runtime",
            "candidate",
            "evidenceSha256",
        }
        or failure["schemaVersion"] != 1
    ):
        raise ValueError("agent candidate failure differs from the contract")
    unhashed = dict(failure)
    supplied_hash = unhashed.pop("evidenceSha256")
    if supplied_hash != canonical_evidence_sha256(unhashed):
        raise ValueError("agent candidate failure digest differs")
    if failure["candidate"] != {
        "checkedHead": candidate.checked_head,
        "repositoryState": "clean",
        "inputs": dict(sorted(candidate.input_sha256.items())),
    }:
        raise ValueError("agent candidate failure binding differs")
    if (
        run.candidate_id != expected["candidateId"]
        or failure["candidateId"] != expected["candidateId"]
        or failure["model"] != expected["model"]
        or failure["revision"] != expected["revision"]
        or failure["artifactManifestSha256"] != expected["artifactManifestSha256"]
        or (failure["stage"], failure["reasonCode"])
        not in {
            ("startup", "runtime-startup-rejected"),
            ("fixtures", "workload-contract-rejected"),
            ("pressure", "runtime-pressure-rejected"),
        }
        or failure["errorType"] not in {"RuntimeError", "TimeoutError", "ValueError"}
        or not isinstance(failure["diagnostic"], str)
        or not 1 <= len(failure["diagnostic"]) <= 1_024
    ):
        raise ValueError("agent candidate failure identity is invalid")
    runtime = failure["runtime"]
    if not isinstance(runtime, dict) or (
        runtime.get("modelArtifactManifestSha256") != expected["artifactManifestSha256"]
        or runtime.get("launchArguments")
        != build_agent_vllm_launch_arguments(expected)
        or canonical_evidence_sha256(runtime.get("launchArguments"))
        != runtime.get("launchArgumentsSha256")
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(runtime.get("imageId")))
        or runtime.get("teardown")
        != {
            "containerAbsent": True,
            "listenerAbsent": True,
            "ownedWorkersReaped": True,
            "ownedCgroupEmpty": True,
            "sameLabelOwnersAbsent": True,
        }
    ):
        raise ValueError("failed agent runtime containment differs")
    return {
        "candidateId": expected["candidateId"],
        "workloadClass": expected["workloadClass"],
        "artifactSha256": agent_evidence_sha256(failure),
        "eligible": False,
        "routeEvidencePassed": False,
        "disposition": "contained-candidate-rejection",
        "reasonCode": failure["reasonCode"],
    }


def _runtime_pressure(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != _PRESSURE_KEYS:
        raise ValueError("agent runtime pressure evidence differs from the contract")
    scalar_fields = (
        "coldLatencyMilliseconds",
        "baselineCgroupMemoryBytes",
        "peakCgroupMemoryBytes",
        "isolationLeakCount",
        "cancelledRequestCompletionCount",
    )
    if any(not _nonnegative_int(value[field]) for field in scalar_fields):
        raise ValueError("agent runtime pressure scalar is invalid")
    warm = value["warmLatencyMilliseconds"]
    concurrency = value["concurrencyLatencyMilliseconds"]
    if not _latencies(warm, 12) or not isinstance(concurrency, dict):
        raise ValueError("agent runtime pressure latency evidence is invalid")
    expected_counts = {"1": 1, "2": 2, "4": 4, "8": 8}
    if set(concurrency) != set(expected_counts) or any(
        not _latencies(concurrency[level], count)
        for level, count in expected_counts.items()
    ):
        raise ValueError("agent runtime concurrency evidence is invalid")
    if value["peakCgroupMemoryBytes"] < value["baselineCgroupMemoryBytes"]:
        raise ValueError("agent runtime memory evidence is invalid")
    return value


def _candidate_models(
    repository_root: Path, expected_sha256: str
) -> dict[str, dict[str, object]]:
    lock, _identity = read_json_object_with_identity(
        repository_root / "server" / "agent-reasoning-candidates.lock.json",
        maximum_bytes=64_000,
        field="agent reasoning candidate lock",
        expected_sha256=expected_sha256,
        containment_root=repository_root,
    )
    candidates = lock["candidates"]
    assert isinstance(candidates, list)
    return {str(value["candidateId"]): value for value in candidates}


def _validate_runtime_receipt(
    candidate: CheckedCandidate,
    *,
    expected: dict[str, object],
    receipt: dict[str, object],
    children: dict[str, dict[str, object]],
) -> None:
    value = receipt
    required = {
        "schemaVersion",
        "checkedHead",
        "candidateId",
        "model",
        "revision",
        "runtime",
        "imageId",
        "quantization",
        "modelArtifactManifestSha256",
        "launchArguments",
        "launchArgumentsSha256",
        "childEvidenceSha256",
        "teardown",
    }
    if set(value) != required or value["schemaVersion"] != 1:
        raise ValueError("agent runtime receipt differs from the contract")
    if (
        value["checkedHead"] != candidate.checked_head
        or value["candidateId"] != expected["candidateId"]
        or value["model"] != expected["model"]
        or value["revision"] != expected["revision"]
        or value["quantization"] != expected["quantization"]
        or value["runtime"]
        != {
            "engine": "vllm",
            "image": "nvcr.io/nvidia/vllm:26.06-py3",
            "digest": "sha256:bebcf9576b1720214319ee5c7ee4f7661954cbbf59ed3fcd188cd79a67f1967e",
            "platform": "linux/arm64",
            "python": "3.12",
            "vllm": "0.22.1+7b9cb5b7.dev",
        }
        or value["modelArtifactManifestSha256"] != expected["artifactManifestSha256"]
        or not isinstance(value["imageId"], str)
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", value["imageId"])
        or value["launchArguments"] != build_agent_vllm_launch_arguments(expected)
        or canonical_evidence_sha256(value["launchArguments"])
        != value["launchArgumentsSha256"]
        or not _SHA256.fullmatch(str(value["launchArgumentsSha256"]))
        or not isinstance(value["childEvidenceSha256"], dict)
        or set(value["childEvidenceSha256"])
        != {"fixtures", "pressure", "cancellation", "resources", "lifecycle"}
        or any(
            not _SHA256.fullmatch(str(item))
            for item in value["childEvidenceSha256"].values()
        )
        or value["teardown"]
        != {
            "containerAbsent": True,
            "listenerAbsent": True,
            "ownedWorkersReaped": True,
            "ownedCgroupEmpty": True,
            "sameLabelOwnersAbsent": True,
        }
    ):
        raise ValueError("agent runtime receipt identity is invalid")
    for name, digest in value["childEvidenceSha256"].items():
        if agent_evidence_sha256(children[str(name)]) != digest:
            raise ValueError("agent runtime child evidence digest differs")
    lifecycle = children["lifecycle"]
    if (
        lifecycle.get("imageId") != value["imageId"]
        or lifecycle.get("modelArtifactManifestSha256")
        != value["modelArtifactManifestSha256"]
        or lifecycle.get("launchArgumentsSha256") != value["launchArgumentsSha256"]
    ):
        raise ValueError("agent runtime lifecycle binding differs")


def _verify_runtime_children(
    children: dict[str, dict[str, object]],
    *,
    checked_head: str,
    evidence_results: object,
    pressure: dict[str, object],
) -> None:
    if any(child.get("checkedHead") != checked_head for child in children.values()):
        raise ValueError("agent runtime child checked head differs")
    fixtures = children["fixtures"]
    pressure_child = children["pressure"]
    cancellation = children["cancellation"]
    resources = children["resources"]
    lifecycle = children["lifecycle"]
    if (
        set(fixtures) != {"schemaVersion", "checkedHead", "candidateId", "results"}
        or fixtures["schemaVersion"] != 2
        or fixtures["results"] != evidence_results
        or set(pressure_child)
        != {
            "schemaVersion",
            "checkedHead",
            "coldLatencyMilliseconds",
            "warmLatencyMilliseconds",
            "concurrencyLatencyMilliseconds",
            "isolationLeakCount",
            "isolationConcurrent",
        }
        or pressure_child["schemaVersion"] != 1
        or pressure_child["isolationConcurrent"] is not True
        or pressure_child["coldLatencyMilliseconds"]
        != pressure["coldLatencyMilliseconds"]
        or pressure_child["warmLatencyMilliseconds"]
        != pressure["warmLatencyMilliseconds"]
        or pressure_child["concurrencyLatencyMilliseconds"]
        != pressure["concurrencyLatencyMilliseconds"]
        or pressure_child["isolationLeakCount"] != pressure["isolationLeakCount"]
        or cancellation
        != {
            "schemaVersion": 1,
            "checkedHead": checked_head,
            "requestDispatched": True,
            "engineActivityObserved": True,
            "engineIdleAfterCancellation": True,
            "recoverySucceeded": True,
            "engineFinishReasons": cancellation["engineFinishReasons"],
            "recoveryEngineFinishReasons": {
                "stop": 1,
                "length": 0,
                "abort": 0,
                "error": 0,
                "repetition": 0,
            },
            "cancelledRequestCompletionCount": pressure[
                "cancelledRequestCompletionCount"
            ],
        }
        or cancellation["engineFinishReasons"]
        not in (
            {
                "stop": 0,
                "length": 0,
                "abort": 0,
                "error": 0,
                "repetition": 0,
            },
            {
                "stop": 0,
                "length": 0,
                "abort": 1,
                "error": 0,
                "repetition": 0,
            },
        )
        or set(resources)
        != {
            "schemaVersion",
            "checkedHead",
            "measurementBoundary",
            "baselineMemoryBytes",
            "peakMemoryBytes",
            "sampleCount",
        }
        or resources["schemaVersion"] != 1
        or resources["measurementBoundary"] != "owned-vllm-cgroup-v2"
        or resources["baselineMemoryBytes"] != pressure["baselineCgroupMemoryBytes"]
        or resources["peakMemoryBytes"] != pressure["peakCgroupMemoryBytes"]
        or not _positive_int(resources["sampleCount"])
        or set(lifecycle)
        != {
            "schemaVersion",
            "checkedHead",
            "containerId",
            "imageId",
            "modelArtifactManifestSha256",
            "launchArgumentsSha256",
            "endpoint",
        }
        or lifecycle["schemaVersion"] != 1
        or not re.fullmatch(r"[0-9a-f]{64}", str(lifecycle["containerId"]))
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(lifecycle["imageId"]))
        or not _SHA256.fullmatch(str(lifecycle["modelArtifactManifestSha256"]))
        or not _SHA256.fullmatch(str(lifecycle["launchArgumentsSha256"]))
        or lifecycle["endpoint"] != "http://127.0.0.1:30000"
    ):
        raise ValueError("agent runtime child evidence differs from the contract")


def _positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _p95(values: object) -> int:
    if (
        not isinstance(values, (list, tuple))
        or not values
        or not all(_nonnegative_int(value) for value in values)
    ):
        raise ValueError("agent latency evidence is invalid")
    ordered = sorted(values)
    return ordered[math.ceil(len(ordered) * 0.95) - 1]


def _latencies(value: object, count: int) -> bool:
    return (
        isinstance(value, list)
        and len(value) == count
        and all(_nonnegative_int(item) for item in value)
    )


def _nonnegative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _evidence_root(repository_root: Path) -> Path:
    raw = os.environ.get("YAP_EVAL_CACHE", "").strip()
    if not raw:
        raise ValueError("YAP_EVAL_CACHE is required")
    root = Path(raw).resolve(strict=True)
    try:
        root.relative_to(repository_root)
    except ValueError:
        return root
    raise ValueError("agent model evidence must remain outside the repository")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Qualify the checked agent workload routes"
    )
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--checked-head", required=True)
    arguments = parser.parse_args(argv)
    repository_root = arguments.repository_root.resolve(strict=True)
    candidate = admit_checked_candidate(
        repository_root=repository_root,
        checked_head=arguments.checked_head,
        input_paths=tuple(repository_root / path for path in _INPUTS),
    )
    evidence_root = _evidence_root(repository_root)
    evidence_destination = evidence_root / "agent-model"
    if evidence_destination.exists() or evidence_destination.is_symlink():
        raise ValueError("agent model evidence destination must be absent")
    acceptance = load_agent_model_acceptance(repository_root)
    staging = Path(tempfile.mkdtemp(prefix=".agent-model-", dir=evidence_root)).resolve(
        strict=True
    )
    try:
        runs = tuple(
            run_agent_model_candidate(
                checked_candidate=candidate,
                candidate_id=candidate_id,
            )
            for candidate_id in acceptance.candidate_ids
        )
        decision = evaluate_agent_model_qualification(
            candidate=candidate,
            runs=runs,
        )
        for run in runs:
            directory = staging / run.candidate_id
            if isinstance(run, FailedAgentCandidateRun):
                write_new_private_json_evidence(directory / "failure.json", run.failure)
                continue
            for name, child in run.children.items():
                write_new_private_json_evidence(
                    directory / "children" / f"{name}.json", child
                )
            write_new_private_json_evidence(
                directory / "runtime-receipt.json", run.runtime_receipt
            )
            write_new_private_json_evidence(directory / "results.json", run.evidence)
        write_new_private_json_evidence(staging / "qualification.json", decision)
        _fsync_evidence_tree(staging)
        os.replace(staging, evidence_destination)
        _fsync_directory(evidence_root)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    print(json.dumps(decision, sort_keys=True, separators=(",", ":")))
    return 0 if decision["outcome"] == "required-workload-routes-qualified" else 1


def _fsync_evidence_tree(root: Path) -> None:
    directories = sorted(
        (path for path in root.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    )
    for directory in directories:
        _fsync_directory(directory)
    _fsync_directory(root)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(2) from error


__all__ = ["evaluate_agent_model_qualification"]
