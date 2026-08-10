from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

from yap_server.evaluation.agent_model_candidate_runner import (
    AgentCandidateRun,
    FailedAgentCandidateRun,
    _contained_failure,
    agent_evidence_sha256,
)
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


class AgentModelQualificationTests(unittest.TestCase):
    def test_unexpected_candidate_error_is_contained_then_reraised(self) -> None:
        candidate = _checked_candidate()
        runtime = MagicMock()
        error = OSError("unexpected evaluation failure")

        with self.assertRaises(OSError) as raised:
            _contained_failure(
                runtime,
                checked_candidate=candidate,
                model_candidate={
                    "candidateId": "qwen3.6-35b-a3b-nvfp4",
                    "model": "model",
                    "revision": "b" * 40,
                    "artifactManifestSha256": "c" * 64,
                },
                stage="fixtures",
                error=error,
                teardown_timeout_seconds=7,
            )

        self.assertIs(raised.exception, error)
        runtime.contain_failed_run.assert_called_once_with(timeout_seconds=7)

    def test_selects_only_after_recomputing_every_candidate(self) -> None:
        candidate = _checked_candidate()
        runs = (
            _candidate_run(candidate, "qwen3.6-35b-a3b-nvfp4", 20),
            _candidate_run(candidate, "nemotron-3-nano-30b-a3b-nvfp4", 10),
        )

        with patch.object(CheckedCandidate, "verify_unchanged"):
            decision = evaluate_agent_model_qualification(
                candidate=candidate, runs=runs
            )

        self.assertEqual(decision["outcome"], "selected-candidate")
        self.assertEqual(
            decision["selectedCandidateId"], "nemotron-3-nano-30b-a3b-nvfp4"
        )
        self.assertNotIn("results", json.dumps(decision))

    def test_keeps_deterministic_route_when_no_candidate_passes(self) -> None:
        candidate = _checked_candidate()
        runs = (
            _candidate_run(candidate, "qwen3.6-35b-a3b-nvfp4", 20, passing=False),
            _candidate_run(
                candidate, "nemotron-3-nano-30b-a3b-nvfp4", 20, passing=False
            ),
        )

        with patch.object(CheckedCandidate, "verify_unchanged"):
            decision = evaluate_agent_model_qualification(
                candidate=candidate, runs=runs
            )

        self.assertEqual(decision["outcome"], "deterministic-no-model")
        self.assertEqual(decision["reasonCodes"], ["no-candidate-met-acceptance"])

    def test_rejects_incomplete_or_tampered_owned_run_set(self) -> None:
        candidate = _checked_candidate()
        run = _candidate_run(candidate, "qwen3.6-35b-a3b-nvfp4", 20)
        with (
            patch.object(CheckedCandidate, "verify_unchanged"),
            self.assertRaisesRegex(ValueError, "incomplete"),
        ):
            evaluate_agent_model_qualification(candidate=candidate, runs=(run,))

        tampered = AgentCandidateRun(
            run.candidate_id,
            {**run.evidence, "revision": "0" * 40},
            run.runtime_receipt,
            run.children,
        )
        other = _candidate_run(candidate, "nemotron-3-nano-30b-a3b-nvfp4", 10)
        with (
            patch.object(CheckedCandidate, "verify_unchanged"),
            self.assertRaisesRegex(ValueError, "digest"),
        ):
            evaluate_agent_model_qualification(
                candidate=candidate, runs=(tampered, other)
            )

    def test_records_contained_failure_and_can_select_other_candidate(self) -> None:
        candidate = _checked_candidate()
        failed = _failed_run(candidate, "qwen3.6-35b-a3b-nvfp4")
        completed = _candidate_run(candidate, "nemotron-3-nano-30b-a3b-nvfp4", 10)

        with patch.object(CheckedCandidate, "verify_unchanged"):
            decision = evaluate_agent_model_qualification(
                candidate=candidate, runs=(failed, completed)
            )

        self.assertEqual(decision["outcome"], "selected-candidate")
        self.assertEqual(
            decision["candidateSummaries"][0]["disposition"],
            "contained-candidate-rejection",
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


def _candidate_run(
    candidate: CheckedCandidate,
    candidate_id: str,
    latency: int,
    *,
    passing: bool = True,
) -> AgentCandidateRun:
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
    launch_arguments = _launch_arguments(model)
    launch_sha256 = canonical_evidence_sha256(launch_arguments)
    children = _children(candidate, model, results, latency, launch_sha256)
    receipt = {
        "schemaVersion": 1,
        "checkedHead": candidate.checked_head,
        "candidateId": candidate_id,
        "model": model["model"],
        "revision": model["revision"],
        "runtime": lock["runtime"],
        "imageId": "sha256:" + "9" * 64,
        "quantization": model["quantization"],
        "modelArtifactManifestSha256": model["artifactManifestSha256"],
        "launchArguments": launch_arguments,
        "launchArgumentsSha256": launch_sha256,
        "childEvidenceSha256": {
            name: agent_evidence_sha256(value) for name, value in children.items()
        },
        "teardown": {
            "containerAbsent": True,
            "listenerAbsent": True,
            "ownedWorkersReaped": True,
            "ownedCgroupEmpty": True,
        },
    }
    evidence = bind_checked_candidate_evidence(
        {
            "schemaVersion": 1,
            "candidateId": candidate_id,
            "model": model["model"],
            "revision": model["revision"],
            "runtimeReceiptSha256": agent_evidence_sha256(receipt),
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
                "baselineCgroupMemoryBytes": 100,
                "peakCgroupMemoryBytes": 200,
                "isolationLeakCount": 0,
                "cancelledRequestCompletionCount": 0,
            },
        },
        candidate,
    )
    return AgentCandidateRun(candidate_id, evidence, receipt, children)


def _failed_run(
    candidate: CheckedCandidate, candidate_id: str
) -> FailedAgentCandidateRun:
    lock = json.loads(
        (REPOSITORY_ROOT / "server" / "agent-reasoning-candidates.lock.json").read_text(
            encoding="utf-8"
        )
    )
    model = next(
        item for item in lock["candidates"] if item["candidateId"] == candidate_id
    )
    launch_arguments = _launch_arguments(model)
    failure = bind_checked_candidate_evidence(
        {
            "schemaVersion": 1,
            "candidateId": candidate_id,
            "model": model["model"],
            "revision": model["revision"],
            "artifactManifestSha256": model["artifactManifestSha256"],
            "stage": "pressure",
            "reasonCode": "runtime-pressure-rejected",
            "errorType": "ValueError",
            "diagnostic": "synthetic pressure rejection",
            "runtime": {
                "imageId": "sha256:" + "9" * 64,
                "modelArtifactManifestSha256": model["artifactManifestSha256"],
                "launchArguments": launch_arguments,
                "launchArgumentsSha256": canonical_evidence_sha256(launch_arguments),
                "teardown": {
                    "containerAbsent": True,
                    "listenerAbsent": True,
                    "ownedWorkersReaped": True,
                    "ownedCgroupEmpty": True,
                },
            },
        },
        candidate,
    )
    return FailedAgentCandidateRun(candidate_id, failure)


def _children(candidate, model, results, latency, launch_sha256):
    return {
        "fixtures": {
            "schemaVersion": 1,
            "checkedHead": candidate.checked_head,
            "candidateId": model["candidateId"],
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
            "engineFinishReasons": _finish_reasons(abort=1),
            "recoveryEngineFinishReasons": _finish_reasons(stop=1),
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
            "modelArtifactManifestSha256": model["artifactManifestSha256"],
            "launchArgumentsSha256": launch_sha256,
            "endpoint": "http://127.0.0.1:30000",
        },
    }


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


def _finish_reasons(*, stop: int = 0, abort: int = 0) -> dict[str, int]:
    return {
        "stop": stop,
        "length": 0,
        "abort": abort,
        "error": 0,
        "repetition": 0,
    }


if __name__ == "__main__":
    unittest.main()
