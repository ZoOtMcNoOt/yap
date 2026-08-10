from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

import pytest

from yap_server.evaluation.agent_model_qualification import (
    evaluate_agent_model_qualification,
)
from yap_server.evaluation.checked_candidate import (
    CheckedCandidate,
    bind_checked_candidate_evidence,
)
from yap_server.evaluation.provider_runtime_observations import (
    canonical_evidence_sha256,
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


def test_selects_admitted_candidate_after_recomputing_every_threshold() -> None:
    candidate = _checked_candidate()
    with tempfile.TemporaryDirectory() as temporary:
        evidence_root = Path(temporary)
        paths = {}
        paths["qwen3.6-35b-a3b-nvfp4"] = _write_candidate(
            evidence_root,
            candidate,
            "qwen3.6-35b-a3b-nvfp4",
            20,
        )
        paths["nemotron-3-nano-30b-a3b-nvfp4"] = _write_candidate(
            evidence_root,
            candidate,
            "nemotron-3-nano-30b-a3b-nvfp4",
            10,
        )
        registry_sha256 = _write_registry(evidence_root, candidate, paths)

        with patch.object(CheckedCandidate, "verify_unchanged"):
            decision = evaluate_agent_model_qualification(
                candidate=candidate,
                evidence_root=evidence_root,
                evidence_registry_sha256=registry_sha256,
            )

    assert decision["outcome"] == "selected-candidate"
    assert decision["selectedCandidateId"] == "nemotron-3-nano-30b-a3b-nvfp4"
    assert len(decision["candidateSummaries"]) == 2
    assert "results" not in json.dumps(decision)


def test_keeps_deterministic_route_when_candidate_evidence_is_missing() -> None:
    candidate = _checked_candidate()
    with tempfile.TemporaryDirectory() as temporary:
        evidence_root = Path(temporary)
        registry_sha256 = _write_registry(evidence_root, candidate, {})
        with patch.object(CheckedCandidate, "verify_unchanged"):
            decision = evaluate_agent_model_qualification(
                candidate=candidate,
                evidence_root=evidence_root,
                evidence_registry_sha256=registry_sha256,
            )

    assert decision["outcome"] == "deterministic-no-model"
    assert decision["missingCandidateIds"] == [
        "qwen3.6-35b-a3b-nvfp4",
        "nemotron-3-nano-30b-a3b-nvfp4",
    ]


def test_keeps_deterministic_route_when_no_candidate_passes() -> None:
    candidate = _checked_candidate()
    with tempfile.TemporaryDirectory() as temporary:
        evidence_root = Path(temporary)
        paths = {}
        paths["qwen3.6-35b-a3b-nvfp4"] = _write_candidate(
            evidence_root,
            candidate,
            "qwen3.6-35b-a3b-nvfp4",
            20,
            passing=False,
        )
        paths["nemotron-3-nano-30b-a3b-nvfp4"] = _write_candidate(
            evidence_root,
            candidate,
            "nemotron-3-nano-30b-a3b-nvfp4",
            20,
            passing=False,
        )
        registry_sha256 = _write_registry(evidence_root, candidate, paths)

        with patch.object(CheckedCandidate, "verify_unchanged"):
            decision = evaluate_agent_model_qualification(
                candidate=candidate,
                evidence_root=evidence_root,
                evidence_registry_sha256=registry_sha256,
            )

    assert decision["outcome"] == "deterministic-no-model"
    assert decision["reasonCodes"] == ["no-candidate-met-acceptance"]


def test_rejects_tampered_candidate_evidence() -> None:
    candidate = _checked_candidate()
    with tempfile.TemporaryDirectory() as temporary:
        evidence_root = Path(temporary)
        paths = {}
        path = _write_candidate(
            evidence_root, candidate, "nemotron-3-nano-30b-a3b-nvfp4", 10
        )
        paths["nemotron-3-nano-30b-a3b-nvfp4"] = path
        paths["qwen3.6-35b-a3b-nvfp4"] = _write_candidate(
            evidence_root, candidate, "qwen3.6-35b-a3b-nvfp4", 20
        )
        registry_sha256 = _write_registry(evidence_root, candidate, paths)
        value = json.loads(path.read_text(encoding="utf-8"))
        value["revision"] = "0" * 40
        path.write_text(json.dumps(value), encoding="utf-8")

        with (
            patch.object(CheckedCandidate, "verify_unchanged"),
            pytest.raises(ValueError, match="out-of-band digest"),
        ):
            evaluate_agent_model_qualification(
                candidate=candidate,
                evidence_root=evidence_root,
                evidence_registry_sha256=registry_sha256,
            )


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
    *,
    passing: bool = True,
) -> Path:
    lock = json.loads(
        (REPOSITORY_ROOT / "server" / "agent-reasoning-candidates.lock.json").read_text(
            encoding="utf-8"
        )
    )
    model = next(
        item for item in lock["candidates"] if item["candidateId"] == candidate_id
    )
    results = list(_perfect_results())
    if not passing:
        results[0]["toolName"] = "wrong_tool"
    launch_arguments_sha256 = canonical_evidence_sha256(_launch_arguments(model))
    child_values = {
        "fixtures": {
            "schemaVersion": 1,
            "checkedHead": candidate.checked_head,
            "candidateId": candidate_id,
            "results": results,
        },
        "pressure": {
            "schemaVersion": 1,
            "checkedHead": candidate.checked_head,
            "coldLatencyMilliseconds": latency,
            "warmLatencyMilliseconds": [latency] * 12,
            "concurrencyLatencyMilliseconds": {
                "1": [latency],
                "2": [latency] * 2,
                "4": [latency] * 4,
                "8": [latency] * 8,
            },
            "isolationLeakCount": 0,
            "isolationConcurrent": True,
        },
        "cancellation": {
            "schemaVersion": 1,
            "checkedHead": candidate.checked_head,
            "requestDispatched": True,
            "engineActivityObserved": True,
            "engineIdleAfterCancellation": True,
            "recoverySucceeded": True,
            "cancelledRequestCompletionCount": 0,
        },
        "resources": {
            "schemaVersion": 1,
            "checkedHead": candidate.checked_head,
            "measurementBoundary": "owned-vllm-cgroup-v2",
            "baselineMemoryBytes": 100,
            "peakMemoryBytes": 200,
            "sampleCount": 10,
        },
        "lifecycle": {
            "schemaVersion": 1,
            "checkedHead": candidate.checked_head,
            "containerId": "8" * 64,
            "imageId": "sha256:" + "9" * 64,
            "modelArtifactManifestSha256": "b" * 64,
            "launchArgumentsSha256": launch_arguments_sha256,
            "endpoint": "http://127.0.0.1:30000",
        },
    }
    child_hashes = {}
    for name, value in child_values.items():
        path = (
            evidence_root / "agent-model" / candidate_id / "children" / f"{name}.json"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")
        child_hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    runtime_receipt = {
        "schemaVersion": 1,
        "checkedHead": candidate.checked_head,
        "candidateId": candidate_id,
        "model": model["model"],
        "revision": model["revision"],
        "runtime": lock["runtime"],
        "imageId": "sha256:" + "9" * 64,
        "quantization": model["quantization"],
        "modelArtifactManifestSha256": "b" * 64,
        "launchArguments": _launch_arguments(model),
        "launchArgumentsSha256": launch_arguments_sha256,
        "childEvidenceSha256": child_hashes,
        "teardown": {
            "containerAbsent": True,
            "listenerAbsent": True,
            "ownedWorkersReaped": True,
        },
    }
    runtime_path = evidence_root / "agent-model" / candidate_id / "runtime-receipt.json"
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    runtime_path.write_text(json.dumps(runtime_receipt), encoding="utf-8")
    runtime_sha256 = hashlib.sha256(runtime_path.read_bytes()).hexdigest()
    evidence = bind_checked_candidate_evidence(
        {
            "schemaVersion": 1,
            "candidateId": candidate_id,
            "model": model["model"],
            "revision": model["revision"],
            "runtimeReceiptSha256": runtime_sha256,
            "results": results,
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
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(evidence), encoding="utf-8")
    return destination


def _write_registry(
    evidence_root: Path,
    candidate: CheckedCandidate,
    result_paths: dict[str, Path],
) -> str:
    candidate_ids = (
        "qwen3.6-35b-a3b-nvfp4",
        "nemotron-3-nano-30b-a3b-nvfp4",
    )
    entries = []
    for candidate_id in candidate_ids:
        result_path = result_paths.get(candidate_id)
        runtime_path = (
            evidence_root / "agent-model" / candidate_id / "runtime-receipt.json"
        )
        entries.append(
            {
                "candidateId": candidate_id,
                "resultSha256": (
                    hashlib.sha256(result_path.read_bytes()).hexdigest()
                    if result_path is not None
                    else "0" * 64
                ),
                "runtimeReceiptSha256": (
                    hashlib.sha256(runtime_path.read_bytes()).hexdigest()
                    if runtime_path.exists()
                    else "f" * 64
                ),
            }
        )
    value = {
        "schemaVersion": 1,
        "checkedHead": candidate.checked_head,
        "inputs": dict(sorted(candidate.input_sha256.items())),
        "candidates": entries,
    }
    destination = evidence_root / "agent-model" / "evidence-registry.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(value), encoding="utf-8")
    return hashlib.sha256(destination.read_bytes()).hexdigest()


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
        if case["expectedTool"] == "search_knowledge":
            arguments["search_text"] = case["user"]
        if "expectedProposalType" in case:
            arguments.update(
                proposal_type=case["expectedProposalType"],
                proposed_content=" ".join(case.get("requiredTerms", [])),
                source_citations=[
                    {
                        "concept_id": item["conceptId"],
                        "source_revision": item["sourceRevision"],
                        "content_sha256": item["contentSha256"],
                        "char_start": item["charStart"],
                        "char_end": item["charEnd"],
                    }
                    for item in case["visibleContext"]
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


def _launch_arguments(model: dict[str, object]) -> list[str]:
    arguments = [
        "vllm",
        "serve",
        f"/model-cache/snapshots/{model['revision']}",
        "--host",
        "127.0.0.1",
        "--port",
        "30000",
        "--served-model-name",
        str(model["model"]),
        "--reasoning-parser",
        str(model["reasoningParser"]),
        "--enable-auto-tool-choice",
        "--tool-call-parser",
        str(model["toolCallParser"]),
        "--max-model-len",
        "8192",
        "--gpu-memory-utilization",
        "0.70",
        "--enable-prefix-caching",
        "--generation-config",
        "vllm",
    ]
    if str(model["candidateId"]).startswith("qwen3.6-"):
        arguments.append("--language-model-only")
    return arguments
