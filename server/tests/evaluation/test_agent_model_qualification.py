from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

from yap_server.evaluation.agent_model_qualification import (
    evaluate_agent_model_qualification,
)
from yap_server.evaluation.checked_candidate import (
    CheckedCandidate,
    bind_checked_candidate_evidence,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
INPUTS = tuple(
    REPOSITORY_ROOT / "server" / name
    for name in (
        "agent-model-acceptance.json",
        "agent-reasoning-candidates.lock.json",
        "agent-workload-fixtures.json",
    )
)


def test_selects_fastest_candidate_after_recomputing_every_threshold() -> None:
    candidate = _checked_candidate()
    with tempfile.TemporaryDirectory() as temporary:
        evidence_root = Path(temporary)
        _write_candidate(evidence_root, candidate, "qwen3.6-35b-a3b-nvfp4", 10)
        _write_candidate(
            evidence_root,
            candidate,
            "nemotron-3-nano-30b-a3b-nvfp4",
            20,
        )

        with patch.object(CheckedCandidate, "verify_unchanged"):
            decision = evaluate_agent_model_qualification(
                candidate=candidate,
                evidence_root=evidence_root,
            )

    assert decision["outcome"] == "selected-candidate"
    assert decision["selectedCandidateId"] == "qwen3.6-35b-a3b-nvfp4"
    assert "results" not in json.dumps(decision)


def test_keeps_deterministic_route_when_candidate_evidence_is_missing() -> None:
    candidate = _checked_candidate()
    with tempfile.TemporaryDirectory() as temporary:
        evidence_root = Path(temporary)
        _write_candidate(evidence_root, candidate, "qwen3.6-35b-a3b-nvfp4", 10)

        with patch.object(CheckedCandidate, "verify_unchanged"):
            decision = evaluate_agent_model_qualification(
                candidate=candidate,
                evidence_root=evidence_root,
            )

    assert decision["outcome"] == "deterministic-no-model"
    assert decision["missingCandidateIds"] == [
        "nemotron-3-nano-30b-a3b-nvfp4"
    ]


def _checked_candidate() -> CheckedCandidate:
    identities = {
        path.relative_to(REPOSITORY_ROOT).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in INPUTS
    }
    return CheckedCandidate(
        repository_root=REPOSITORY_ROOT,
        checked_head="a" * 40,
        input_sha256=identities,
        _input_paths=INPUTS,
    )


def _write_candidate(
    evidence_root: Path,
    candidate: CheckedCandidate,
    candidate_id: str,
    latency: int,
) -> None:
    lock = json.loads(
        (REPOSITORY_ROOT / "server" / "agent-reasoning-candidates.lock.json").read_text(
            encoding="utf-8"
        )
    )
    model = next(
        item for item in lock["candidates"] if item["candidateId"] == candidate_id
    )
    evidence = bind_checked_candidate_evidence(
        {
            "schemaVersion": 1,
            "candidateId": candidate_id,
            "model": model["model"],
            "revision": model["revision"],
            "results": list(_perfect_results()),
            "runtimePressure": {
                "coldLatencyMilliseconds": latency,
                "warmLatencyMilliseconds": [latency] * 12,
                "concurrencyLatencyMilliseconds": {
                    "1": [latency],
                    "2": [latency] * 2,
                    "4": [latency] * 4,
                    "8": [latency] * 8,
                },
                "baselineUnifiedMemoryBytes": 100,
                "peakUnifiedMemoryBytes": 200,
                "isolationLeakCount": 0,
                "cancelledRequestCompletionCount": 0,
            },
        },
        candidate,
    )
    destination = evidence_root / "agent-model" / candidate_id / "results.json"
    destination.parent.mkdir(parents=True)
    destination.write_text(json.dumps(evidence), encoding="utf-8")


def _perfect_results() -> tuple[dict[str, object], ...]:
    fixture = json.loads(
        (REPOSITORY_ROOT / "server" / "agent-workload-fixtures.json").read_text(
            encoding="utf-8"
        )
    )
    results: list[dict[str, object]] = []
    for case in fixture["cases"]:
        arguments = dict(case.get("expectedArguments", {}))
        arguments["purpose"] = "knowledge.read"
        if "expectedProposalType" in case:
            arguments.update(
                proposal_type=case["expectedProposalType"],
                proposed_content=" ".join(case.get("requiredTerms", [])),
                source_citations=[
                    {"concept_id": value}
                    for value in case.get("requiredCitationConceptIds", [])
                ],
            )
        results.append(
            {
                "caseId": case["caseId"],
                "toolName": case["expectedTool"],
                "arguments": arguments,
                "answer": " ".join(case.get("requiredTerms", [])),
                "citationConceptIds": case.get("requiredCitationConceptIds", []),
                "latencyMilliseconds": 10,
            }
        )
    return tuple(results)
