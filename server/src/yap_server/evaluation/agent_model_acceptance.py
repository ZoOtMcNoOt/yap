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
    "permittedOutcomes",
}


@dataclass(frozen=True, slots=True)
class AgentModelAcceptance:
    plan_sha256: str
    candidate_lock_sha256: str
    fixture_sha256: str
    candidate_ids: tuple[str, ...]
    rejected_candidate_ids: tuple[str, ...]
    case_ids: tuple[str, ...]
    permitted_outcomes: tuple[str, ...]
    runtime_tracks: dict[str, object]
    selection_policy: dict[str, object]


def load_agent_model_acceptance(repository_root: Path) -> AgentModelAcceptance:
    server_root = repository_root / "server"
    plan, plan_hash = read_json_object_with_identity(
        server_root / "agent-model-acceptance.json",
        maximum_bytes=64_000,
        field="agent model acceptance plan",
        containment_root=repository_root,
    )
    if set(plan) != _PLAN_KEYS or plan["schemaVersion"] != 1:
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
    candidate_ids, rejected_candidate_ids = _candidate_lock(lock)
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
    selection_policy = _selection_policy(plan["selectionPolicy"])
    outcomes = plan["permittedOutcomes"]
    if outcomes != ["selected-candidate", "deterministic-no-model"]:
        raise ValueError("agent model outcomes differ from the contract")
    return AgentModelAcceptance(
        plan_hash,
        observed_lock_hash,
        observed_fixture_hash,
        candidate_ids,
        rejected_candidate_ids,
        case_ids,
        tuple(outcomes),
        runtime_tracks,
        selection_policy,
    )


def _candidate_lock(value: dict[str, object]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if (
        set(value) != {"schemaVersion", "runtime", "candidates"}
        or value["schemaVersion"] != 1
    ):
        raise ValueError("agent reasoning candidate lock differs from the contract")
    runtime = value["runtime"]
    if not isinstance(runtime, dict) or set(runtime) != {
        "image",
        "manifestDigest",
        "platformDigest",
        "platform",
        "python",
        "sglang",
    }:
        raise ValueError("agent runtime lock is invalid")
    if runtime != {
        "image": "nvcr.io/nvidia/sglang:26.06-py3",
        "manifestDigest": "sha256:f1e23b1c96d7e04d061c76b179f81aa32fcef367590a90f6079a0bf899dc4300",
        "platformDigest": "sha256:8689bc346a5f92309c3887f3431f6d29747be10a6d5dbb871f4d4ae431d3309b",
        "platform": "linux/arm64",
        "python": "3.12",
        "sglang": "0.5.12.post1",
    }:
        raise ValueError("agent runtime identity is not the approved GB10 image")
    candidates = value["candidates"]
    if not isinstance(candidates, list) or len(candidates) != 2:
        raise ValueError("agent candidate set is invalid")
    identities: list[str] = []
    admitted: list[str] = []
    rejected: list[str] = []
    for candidate in candidates:
        if not isinstance(candidate, dict) or not {
            "candidateId",
            "model",
            "revision",
            "quantization",
            "toolCallParser",
            "evaluationStatus",
            "license",
            "source",
        } <= set(candidate) <= {
            "candidateId",
            "model",
            "revision",
            "quantization",
            "toolCallParser",
            "reasoningParser",
            "evaluationStatus",
            "reasonCode",
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
        if not isinstance(candidate["source"], str) or not candidate[
            "source"
        ].startswith("https://huggingface.co/"):
            raise ValueError("agent candidate provenance is invalid")
        identities.append(candidate_id)
        status = candidate["evaluationStatus"]
        if status == "workload-candidate" and "reasonCode" not in candidate:
            admitted.append(candidate_id)
        elif (
            status == "runtime-incompatible"
            and candidate.get("reasonCode")
            == "sglang-w4afp8-block-shape-unsupported"
        ):
            rejected.append(candidate_id)
        else:
            raise ValueError("agent candidate evaluation status is invalid")
    if len(set(identities)) != len(identities):
        raise ValueError("agent candidate is duplicated")
    if not admitted or not rejected:
        raise ValueError("agent candidate comparison is incomplete")
    return tuple(admitted), tuple(rejected)


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
    if (
        len(set(case_ids)) != len(case_ids)
        or not isolation_counts
        or set(isolation_counts.values()) != {2}
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


def _selection_policy(value: object) -> dict[str, object]:
    expected = {
        "requireEveryCandidate": True,
        "ranking": [
            "concurrencyC8P95LatencyMilliseconds",
            "warmP95LatencyMilliseconds",
            "incrementalUnifiedMemoryBytes",
            "candidateId",
        ],
    }
    if value != expected:
        raise ValueError("agent model selection policy differs from the contract")
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
