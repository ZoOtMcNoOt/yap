"""Select one agent model only from complete, checked private evidence."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import sys
from typing import Mapping

from yap_server.evaluation.provider_runtime_observations import (
    canonical_evidence_sha256,
)
from yap_server.private_artifact import read_json_object_with_identity

from .agent_model_acceptance import load_agent_model_acceptance
from .agent_model_evidence import write_new_agent_model_evidence
from .agent_model_scoring import score_agent_model_results
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
    "evidenceSha256",
}
_PRESSURE_KEYS = {
    "coldLatencyMilliseconds",
    "warmLatencyMilliseconds",
    "concurrencyLatencyMilliseconds",
    "baselineUnifiedMemoryBytes",
    "peakUnifiedMemoryBytes",
    "isolationLeakCount",
    "cancelledRequestCompletionCount",
}


def evaluate_agent_model_qualification(
    *,
    candidate: CheckedCandidate,
    evidence_root: Path,
) -> dict[str, object]:
    """Recompute all candidate scores and emit a transcript-free decision."""

    acceptance = load_agent_model_acceptance(candidate.repository_root)
    models = _candidate_models(candidate.repository_root, acceptance.candidate_lock_sha256)
    candidate.verify_unchanged()
    summaries: list[dict[str, object]] = []
    missing: list[str] = []
    for candidate_id in acceptance.candidate_ids:
        path = evidence_root / "agent-model" / candidate_id / "results.json"
        if not path.exists():
            missing.append(candidate_id)
            continue
        evidence, artifact_sha256 = read_json_object_with_identity(
            path,
            maximum_bytes=16_000_000,
            field="agent model candidate evidence",
            containment_root=evidence_root,
        )
        summaries.append(
            _candidate_summary(
                candidate,
                evidence,
                artifact_sha256=artifact_sha256,
                expected=models[candidate_id],
            )
        )

    if missing:
        decision: dict[str, object] = {
            "schemaVersion": 1,
            "qualificationScope": "governed-agent-reasoning",
            "outcome": "deterministic-no-model",
            "selectedCandidateId": None,
            "reasonCodes": ["candidate-evidence-incomplete"],
            "missingCandidateIds": missing,
            "candidateSummaries": summaries,
        }
    else:
        eligible = [summary for summary in summaries if summary["eligible"]]
        if not eligible:
            outcome = "deterministic-no-model"
            selected_id = None
            reasons = ["no-candidate-met-acceptance"]
        else:
            selected = min(eligible, key=_ranking_key)
            outcome = "selected-candidate"
            selected_id = selected["candidateId"]
            reasons = ["quality-thresholds-passed", "performance-ranking-selected"]
        decision = {
            "schemaVersion": 1,
            "qualificationScope": "governed-agent-reasoning",
            "outcome": outcome,
            "selectedCandidateId": selected_id,
            "reasonCodes": reasons,
            "missingCandidateIds": [],
            "candidateSummaries": summaries,
        }
    candidate.verify_unchanged()
    return bind_checked_candidate_evidence(decision, candidate)


def _candidate_summary(
    candidate: CheckedCandidate,
    evidence: dict[str, object],
    *,
    artifact_sha256: str,
    expected: dict[str, object],
) -> dict[str, object]:
    if set(evidence) != _EVIDENCE_KEYS or evidence["schemaVersion"] != 1:
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
    results = evidence["results"]
    if not isinstance(results, list):
        raise ValueError("agent model candidate results are invalid")
    score = score_agent_model_results(candidate.repository_root, tuple(results))
    pressure = _runtime_pressure(evidence["runtimePressure"])
    eligible = (
        score.passed
        and pressure["isolationLeakCount"] == 0
        and pressure["cancelledRequestCompletionCount"] == 0
    )
    return {
        "candidateId": expected["candidateId"],
        "artifactSha256": artifact_sha256,
        "eligible": eligible,
        "toolSelectionAccuracy": score.tool_selection_accuracy,
        "structuredArgumentAccuracy": score.structured_argument_accuracy,
        "citationFidelity": score.citation_fidelity,
        "terminologyPreservation": score.terminology_preservation,
        "isolationLeakCount": score.isolation_leak_count,
        "invalidStructuredOutputCount": score.invalid_structured_output_count,
        "concurrencyC8P95LatencyMilliseconds": _p95(
            pressure["concurrencyLatencyMilliseconds"]["8"]
        ),
        "warmP95LatencyMilliseconds": _p95(pressure["warmLatencyMilliseconds"]),
        "incrementalUnifiedMemoryBytes": max(
            0,
            pressure["peakUnifiedMemoryBytes"]
            - pressure["baselineUnifiedMemoryBytes"],
        ),
    }


def _runtime_pressure(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != _PRESSURE_KEYS:
        raise ValueError("agent runtime pressure evidence differs from the contract")
    scalar_fields = (
        "coldLatencyMilliseconds",
        "baselineUnifiedMemoryBytes",
        "peakUnifiedMemoryBytes",
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
    if value["peakUnifiedMemoryBytes"] < value["baselineUnifiedMemoryBytes"]:
        raise ValueError("agent runtime memory evidence is invalid")
    return value


def _candidate_models(repository_root: Path, expected_sha256: str) -> dict[str, dict[str, object]]:
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


def _ranking_key(summary: dict[str, object]) -> tuple[int, int, int, str]:
    return (
        int(summary["concurrencyC8P95LatencyMilliseconds"]),
        int(summary["warmP95LatencyMilliseconds"]),
        int(summary["incrementalUnifiedMemoryBytes"]),
        str(summary["candidateId"]),
    )


def _p95(values: object) -> int:
    assert isinstance(values, list)
    ordered = sorted(values)
    return ordered[math.ceil(len(ordered) * 0.95) - 1]


def _latencies(value: object, count: int) -> bool:
    return isinstance(value, list) and len(value) == count and all(
        _nonnegative_int(item) for item in value
    )


def _nonnegative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _evidence_root(repository_root: Path, environ: Mapping[str, str]) -> Path:
    raw = environ.get("YAP_EVAL_CACHE", "").strip()
    if not raw:
        raise ValueError("YAP_EVAL_CACHE is required")
    root = Path(raw).resolve(strict=True)
    try:
        root.relative_to(repository_root)
    except ValueError:
        return root
    raise ValueError("agent model evidence must remain outside the repository")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Select the checked agent model")
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--checked-head", required=True)
    arguments = parser.parse_args(argv)
    repository_root = arguments.repository_root.resolve(strict=True)
    candidate = admit_checked_candidate(
        repository_root=repository_root,
        checked_head=arguments.checked_head,
        input_paths=tuple(repository_root / path for path in _INPUTS),
    )
    evidence_root = _evidence_root(repository_root, os.environ)
    decision = evaluate_agent_model_qualification(
        candidate=candidate,
        evidence_root=evidence_root,
    )
    write_new_agent_model_evidence(
        evidence_root / "agent-model" / "qualification.json", decision
    )
    print(json.dumps(decision, sort_keys=True, separators=(",", ":")))
    return 0 if decision["outcome"] == "selected-candidate" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(2) from error


__all__ = ["evaluate_agent_model_qualification"]
