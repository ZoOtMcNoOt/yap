from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from yap_server.private_artifact import read_json_object_with_identity


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REVISION = re.compile(r"^[0-9a-f]{40}$")
_PLAN_KEYS = {
    "schemaVersion",
    "candidateLock",
    "fixtureFile",
    "candidateLockSha256",
    "fixtureSha256",
    "minimumCaseCount",
    "requiredCategories",
    "thresholds",
    "runtimeTracks",
    "selectionPolicy",
    "routeEvidence",
    "permittedOutcomes",
}


@dataclass(frozen=True, slots=True)
class AgentModelAcceptance:
    plan_sha256: str
    candidate_lock_sha256: str
    fixture_sha256: str
    candidate_ids: tuple[str, ...]
    required_routes: dict[str, str]
    case_ids: tuple[str, ...]
    permitted_outcomes: tuple[str, ...]
    runtime_tracks: dict[str, object]
    selection_policy: dict[str, object]
    route_evidence: dict[str, object]


def load_agent_model_acceptance(repository_root: Path) -> AgentModelAcceptance:
    server_root = repository_root / "server"
    plan, plan_hash = read_json_object_with_identity(
        server_root / "agent-model-acceptance.json",
        maximum_bytes=64_000,
        field="agent model acceptance plan",
        containment_root=repository_root,
    )
    if set(plan) != _PLAN_KEYS or plan["schemaVersion"] != 2:
        raise ValueError("agent model acceptance plan differs from the contract")
    lock_name = _file_name(plan["candidateLock"], "candidate lock")
    fixture_name = _file_name(plan["fixtureFile"], "fixture file")
    lock_hash = _digest(plan["candidateLockSha256"], "candidate lock digest")
    fixture_hash = _digest(plan["fixtureSha256"], "fixture digest")
    lock, observed_lock_hash = read_json_object_with_identity(
        server_root / lock_name,
        maximum_bytes=64_000,
        field="agent reasoning candidate lock",
        expected_sha256=lock_hash,
        containment_root=repository_root,
    )
    fixtures, observed_fixture_hash = read_json_object_with_identity(
        server_root / fixture_name,
        maximum_bytes=256_000,
        field="agent workload fixtures",
        expected_sha256=fixture_hash,
        containment_root=repository_root,
    )
    candidate_routes = _candidate_lock(lock)
    candidate_ids = tuple(candidate_routes)
    case_ids, categories = _fixtures(fixtures)
    minimum = plan["minimumCaseCount"]
    required_categories = plan["requiredCategories"]
    if (
        isinstance(minimum, bool)
        or not isinstance(minimum, int)
        or minimum < 1
        or len(case_ids) < minimum
        or not isinstance(required_categories, list)
        or set(required_categories) != categories
    ):
        raise ValueError("agent workload coverage is incomplete")
    _thresholds(plan["thresholds"])
    runtime_tracks = _runtime_tracks(plan["runtimeTracks"])
    selection_policy = _selection_policy(plan["selectionPolicy"], candidate_routes)
    required_routes = dict(selection_policy["requiredRoutes"])
    route_evidence = _route_evidence(plan["routeEvidence"], required_routes)
    outcomes = plan["permittedOutcomes"]
    if outcomes != ["required-workload-routes-qualified", "deterministic-no-model"]:
        raise ValueError("agent model outcomes differ from the contract")
    return AgentModelAcceptance(
        plan_hash,
        observed_lock_hash,
        observed_fixture_hash,
        candidate_ids,
        required_routes,
        case_ids,
        tuple(outcomes),
        runtime_tracks,
        selection_policy,
        route_evidence,
    )


def _candidate_lock(value: dict[str, object]) -> dict[str, str]:
    if (
        set(value) != {"schemaVersion", "runtime", "candidates"}
        or value["schemaVersion"] != 2
    ):
        raise ValueError("agent reasoning candidate lock differs from the contract")
    runtime = value["runtime"]
    if not isinstance(runtime, dict) or set(runtime) != {
        "engine",
        "image",
        "digest",
        "platform",
        "python",
        "vllm",
    }:
        raise ValueError("agent runtime lock is invalid")
    if runtime != {
        "engine": "vllm",
        "image": "nvcr.io/nvidia/vllm:26.06-py3",
        "digest": "sha256:bebcf9576b1720214319ee5c7ee4f7661954cbbf59ed3fcd188cd79a67f1967e",
        "platform": "linux/arm64",
        "python": "3.12",
        "vllm": "0.22.1+7b9cb5b7.dev",
    }:
        raise ValueError("agent runtime identity is not the approved GB10 image")
    candidates = value["candidates"]
    if not isinstance(candidates, list) or len(candidates) != 2:
        raise ValueError("agent candidate set is invalid")
    identities: dict[str, str] = {}
    for candidate in candidates:
        if not isinstance(candidate, dict) or not {
            "candidateId",
            "model",
            "revision",
            "artifactManifestSha256",
            "workloadClass",
            "quantization",
            "toolCallParser",
            "license",
            "source",
        } <= set(candidate) <= {
            "candidateId",
            "model",
            "revision",
            "artifactManifestSha256",
            "workloadClass",
            "quantization",
            "toolCallParser",
            "reasoningParser",
            "license",
            "source",
        }:
            raise ValueError("agent candidate differs from the contract")
        candidate_id = candidate["candidateId"]
        if not isinstance(candidate_id, str) or not candidate_id:
            raise ValueError("agent candidate ID is invalid")
        if not isinstance(candidate["revision"], str) or not _REVISION.fullmatch(
            candidate["revision"]
        ):
            raise ValueError("agent candidate revision is invalid")
        if not isinstance(
            candidate["artifactManifestSha256"], str
        ) or not _SHA256.fullmatch(candidate["artifactManifestSha256"]):
            raise ValueError("agent candidate artifact manifest is invalid")
        if not isinstance(candidate["source"], str) or not candidate[
            "source"
        ].startswith("https://huggingface.co/"):
            raise ValueError("agent candidate provenance is invalid")
        workload_class = candidate["workloadClass"]
        if workload_class not in {"rapid-automation", "complex-orchestration"}:
            raise ValueError("agent candidate workload class is invalid")
        if candidate_id in identities or workload_class in identities.values():
            raise ValueError("agent candidate is duplicated")
        identities[candidate_id] = str(workload_class)
    if set(identities.values()) != {"rapid-automation", "complex-orchestration"}:
        raise ValueError("agent candidate is duplicated")
    return identities


def _fixtures(value: dict[str, object]) -> tuple[tuple[str, ...], set[str]]:
    if (
        set(value)
        != {"schemaVersion", "license", "provenance", "sharedSystemPrompt", "cases"}
        or value["schemaVersion"] != 1
        or value["license"] != "CC0-1.0"
    ):
        raise ValueError("agent workload fixture differs from the contract")
    cases = value["cases"]
    if not isinstance(cases, list):
        raise ValueError("agent workload cases are invalid")
    case_ids: list[str] = []
    categories: set[str] = set()
    isolation_counts: dict[str, int] = {}
    route_specific_counts = {"complex-orchestration": 0}
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("agent workload case is invalid")
        case_id = case.get("caseId")
        category = case.get("category")
        if not isinstance(case_id, str) or not case_id or not isinstance(category, str):
            raise ValueError("agent workload identity is invalid")
        if not isinstance(case.get("user"), str) or not isinstance(
            case.get("visibleContext"), list
        ):
            raise ValueError("agent workload content is invalid")
        case_ids.append(case_id)
        categories.add(category)
        pair = case.get("isolationPair")
        if pair is not None:
            if not isinstance(pair, str):
                raise ValueError("agent isolation pair is invalid")
            isolation_counts[pair] = isolation_counts.get(pair, 0) + 1
        route = case.get("requiredForWorkloadClass")
        if route is not None:
            if route not in route_specific_counts:
                raise ValueError("agent route-specific workload is invalid")
            route_specific_counts[route] += 1
        sequence = case.get("expectedToolSequence")
        if sequence is not None and (
            not isinstance(sequence, list)
            or len(sequence) < 2
            or not all(isinstance(item, str) and item for item in sequence)
            or sequence[-1] != case.get("expectedTool")
        ):
            raise ValueError("agent multi-step workload is invalid")
        expected_calls = case.get("expectedToolCalls")
        if sequence is not None and (
            not isinstance(expected_calls, list)
            or [call.get("name") for call in expected_calls if isinstance(call, dict)]
            != sequence
            or any(
                not isinstance(call, dict)
                or set(call) != {"name", "expectedArguments"}
                or not isinstance(call["expectedArguments"], dict)
                or not call["expectedArguments"]
                for call in expected_calls
            )
        ):
            raise ValueError("agent multi-step expected calls are invalid")
    if (
        len(set(case_ids)) != len(case_ids)
        or not isolation_counts
        or set(isolation_counts.values()) != {2}
        or route_specific_counts != {"complex-orchestration": 1}
    ):
        raise ValueError("agent workload identities are incomplete")
    return tuple(case_ids), categories


def _thresholds(value: object) -> None:
    expected = {
        "toolSelectionAccuracy": 1.0,
        "structuredArgumentAccuracy": 1.0,
        "citationFidelity": 1.0,
        "terminologyPreservation": 1.0,
        "isolationLeakCount": 0,
        "invalidStructuredOutputCount": 0,
        "cancelledRequestCompletionCount": 0,
    }
    if value != expected:
        raise ValueError("agent model thresholds differ from the contract")


def _runtime_tracks(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != {
        "coldRequests",
        "warmRequests",
        "concurrencyLevels",
        "prefixIsolationRepetitions",
        "maximumContextTokens",
        "maximumOutputTokens",
        "requestTimeoutSeconds",
        "startupTimeoutSeconds",
        "teardownTimeoutSeconds",
    }:
        raise ValueError("agent runtime tracks differ from the contract")
    if (
        value["concurrencyLevels"] != [1, 2, 4, 8]
        or value["prefixIsolationRepetitions"] != 4
    ):
        raise ValueError("agent runtime pressure tracks are incomplete")
    numeric = {
        "coldRequests": (1, 8),
        "warmRequests": (1, 100),
        "maximumContextTokens": (1, 131_072),
        "maximumOutputTokens": (1, 4_096),
        "requestTimeoutSeconds": (1, 300),
        "startupTimeoutSeconds": (1, 900),
        "teardownTimeoutSeconds": (1, 300),
    }
    for field, (minimum, maximum) in numeric.items():
        observed = value[field]
        if (
            isinstance(observed, bool)
            or not isinstance(observed, int)
            or not minimum <= observed <= maximum
        ):
            raise ValueError("agent runtime pressure bound is invalid")
    return dict(value)


def _selection_policy(
    value: object, candidate_routes: dict[str, str]
) -> dict[str, object]:
    expected = {
        "requireEveryCandidate": True,
        "requiredRoutes": {
            "complex-orchestration": "gemma-4-31b-it-nvfp4",
            "rapid-automation": "qwen3.6-35b-a3b-nvfp4",
        },
    }
    if value != expected:
        raise ValueError("agent model selection policy differs from the contract")
    if {
        candidate_id: workload_class
        for workload_class, candidate_id in expected["requiredRoutes"].items()
    } != candidate_routes:
        raise ValueError("agent route policy differs from candidate ownership")
    return dict(value)


def _route_evidence(
    value: object, required_routes: dict[str, str]
) -> dict[str, object]:
    expected = {
        "rapid-automation": {
            "candidateId": "qwen3.6-35b-a3b-nvfp4",
            "maximumFixtureP95LatencyMilliseconds": 3_000,
            "maximumWarmP95LatencyMilliseconds": 750,
            "maximumC8P95LatencyMilliseconds": 1_500,
        },
        "complex-orchestration": {
            "candidateId": "gemma-4-31b-it-nvfp4",
            "requestTimeoutSeconds": 60,
            "requiredMultiStepCaseId": "complex-governed-orchestration",
        },
    }
    if value != expected or {
        route: policy["candidateId"] for route, policy in expected.items()
    } != required_routes:
        raise ValueError("agent route evidence policy differs from the contract")
    return dict(value)


def _file_name(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or Path(value).name != value
        or not value.endswith(".json")
    ):
        raise ValueError(f"{field} is invalid")
    return value


def _digest(value: object, field: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ValueError(f"{field} is invalid")
    return value


__all__ = ["AgentModelAcceptance", "load_agent_model_acceptance"]
