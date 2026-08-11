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
    _validate_runtime_receipt,
    _verify_runtime_children,
    evaluate_agent_model_qualification,
)
from yap_server.evaluation.agent_vllm_runtime import (
    build_agent_vllm_launch_arguments,
)
from yap_server.evaluation.checked_candidate import (
    CheckedCandidate,
    bind_checked_candidate_evidence,
)
from yap_server.evaluation.provider_runtime_observations import (
    canonical_evidence_sha256,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PROPOSAL_CASE_IDS = {
    "cited-summary-proposal",
    "terminology-preservation-en",
    "terminology-preservation-es",
}
INPUTS = tuple(
    REPOSITORY_ROOT / relative
    for relative in (
        "server/agent-model-acceptance.json",
        "server/agent-reasoning-candidates.lock.json",
        "server/agent-service-profiles/rapid-automation.json",
        "server/agent-service-profiles/complex-orchestration.json",
        "server/agent-workload-fixtures.json",
        "server/runtime/agent-vllm/Dockerfile",
        "server/runtime/agent-vllm/build-qwen-vllm-runtime.sh",
        "server/runtime/agent-vllm/THIRD_PARTY_NOTICES.md",
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

    def test_qualifies_only_after_recomputing_every_required_route(self) -> None:
        candidate = _checked_candidate()
        runs = (
            _candidate_run(candidate, "qwen3.6-35b-a3b-nvfp4", 20),
            _candidate_run(candidate, "gemma-4-31b-it-nvfp4", 10),
        )

        with patch.object(CheckedCandidate, "verify_unchanged"):
            decision = evaluate_agent_model_qualification(
                candidate=candidate, runs=runs
            )

        self.assertEqual(
            decision["outcome"], "required-workload-routes-qualified"
        )
        self.assertEqual(decision["schemaVersion"], 2)
        self.assertEqual(
            decision["admittedModelCandidates"],
            ["gemma-4-31b-it-nvfp4", "qwen3.6-35b-a3b-nvfp4"],
        )
        self.assertNotIn("results", json.dumps(decision))

    def test_keeps_deterministic_route_when_no_candidate_passes(self) -> None:
        candidate = _checked_candidate()
        runs = (
            _candidate_run(candidate, "qwen3.6-35b-a3b-nvfp4", 20, passing=False),
            _candidate_run(
                candidate, "gemma-4-31b-it-nvfp4", 20, passing=False
            ),
        )

        with patch.object(CheckedCandidate, "verify_unchanged"):
            decision = evaluate_agent_model_qualification(
                candidate=candidate, runs=runs
            )

        self.assertEqual(decision["outcome"], "deterministic-no-model")
        self.assertEqual(
            decision["reasonCodes"],
            ["required-workload-route-did-not-meet-acceptance"],
        )
        self.assertEqual(decision["admittedModelCandidates"], [])

    def test_rejects_rapid_route_above_its_latency_bounds(self) -> None:
        candidate = _checked_candidate()
        runs = (
            _candidate_run(candidate, "qwen3.6-35b-a3b-nvfp4", 2_000),
            _candidate_run(candidate, "gemma-4-31b-it-nvfp4", 10),
        )

        with patch.object(CheckedCandidate, "verify_unchanged"):
            decision = evaluate_agent_model_qualification(
                candidate=candidate, runs=runs
            )

        self.assertEqual(decision["outcome"], "deterministic-no-model")
        qwen = next(
            summary
            for summary in decision["candidateSummaries"]
            if summary["candidateId"] == "qwen3.6-35b-a3b-nvfp4"
        )
        self.assertFalse(qwen["routeEvidencePassed"])

    def test_rejects_slow_rapid_fixture_when_marker_pressure_is_fast(self) -> None:
        candidate = _checked_candidate()
        runs = (
            _candidate_run(
                candidate,
                "qwen3.6-35b-a3b-nvfp4",
                20,
                fixture_latency_overrides={"lexical-cited-answer": 4_000},
            ),
            _candidate_run(candidate, "gemma-4-31b-it-nvfp4", 10),
        )

        with patch.object(CheckedCandidate, "verify_unchanged"):
            decision = evaluate_agent_model_qualification(
                candidate=candidate, runs=runs
            )

        self.assertEqual(decision["outcome"], "deterministic-no-model")
        qwen = next(
            summary
            for summary in decision["candidateSummaries"]
            if summary["candidateId"] == "qwen3.6-35b-a3b-nvfp4"
        )
        self.assertEqual(qwen["warmP95LatencyMilliseconds"], 20)
        self.assertEqual(qwen["commonFixtureP95LatencyMilliseconds"], 4_000)
        self.assertEqual(qwen["proposalFixtureP95LatencyMilliseconds"], 10)
        self.assertFalse(qwen["routeEvidencePassed"])

    def test_applies_a_distinct_bounded_proposal_workflow_latency(self) -> None:
        candidate = _checked_candidate()
        passing_runs = (
            _candidate_run(
                candidate,
                "qwen3.6-35b-a3b-nvfp4",
                20,
                fixture_latency_overrides={
                    case_id: 10_000 for case_id in PROPOSAL_CASE_IDS
                },
            ),
            _candidate_run(candidate, "gemma-4-31b-it-nvfp4", 10),
        )

        with patch.object(CheckedCandidate, "verify_unchanged"):
            passing = evaluate_agent_model_qualification(
                candidate=candidate, runs=passing_runs
            )

        self.assertEqual(passing["outcome"], "required-workload-routes-qualified")
        qwen = next(
            summary
            for summary in passing["candidateSummaries"]
            if summary["candidateId"] == "qwen3.6-35b-a3b-nvfp4"
        )
        self.assertEqual(qwen["commonFixtureP95LatencyMilliseconds"], 10)
        self.assertEqual(qwen["proposalFixtureP95LatencyMilliseconds"], 10_000)
        self.assertTrue(qwen["routeEvidencePassed"])

        failing_runs = (
            _candidate_run(
                candidate,
                "qwen3.6-35b-a3b-nvfp4",
                20,
                fixture_latency_overrides={
                    case_id: 10_001 for case_id in PROPOSAL_CASE_IDS
                },
            ),
            passing_runs[1],
        )
        with patch.object(CheckedCandidate, "verify_unchanged"):
            failing = evaluate_agent_model_qualification(
                candidate=candidate, runs=failing_runs
            )
        self.assertEqual(failing["outcome"], "deterministic-no-model")

    def test_rejects_incomplete_complex_orchestration_sequence(self) -> None:
        candidate = _checked_candidate()
        qwen = _candidate_run(candidate, "qwen3.6-35b-a3b-nvfp4", 20)
        gemma = _candidate_run(
            candidate,
            "gemma-4-31b-it-nvfp4",
            10,
            incomplete_complex_sequence=True,
        )

        with patch.object(CheckedCandidate, "verify_unchanged"):
            decision = evaluate_agent_model_qualification(
                candidate=candidate, runs=(qwen, gemma)
            )

        self.assertEqual(decision["outcome"], "deterministic-no-model")
        summary = next(
            item
            for item in decision["candidateSummaries"]
            if item["candidateId"] == "gemma-4-31b-it-nvfp4"
        )
        self.assertFalse(summary["routeEvidencePassed"])

    def test_rejects_semantically_wrong_complex_intermediate_call(self) -> None:
        candidate = _checked_candidate()
        qwen = _candidate_run(candidate, "qwen3.6-35b-a3b-nvfp4", 20)
        gemma = _candidate_run(
            candidate,
            "gemma-4-31b-it-nvfp4",
            10,
            wrong_complex_traversal=True,
        )

        with patch.object(CheckedCandidate, "verify_unchanged"):
            decision = evaluate_agent_model_qualification(
                candidate=candidate, runs=(qwen, gemma)
            )

        self.assertEqual(decision["outcome"], "deterministic-no-model")
        summary = next(
            item
            for item in decision["candidateSummaries"]
            if item["candidateId"] == "gemma-4-31b-it-nvfp4"
        )
        self.assertFalse(summary["routeEvidencePassed"])

        extra_controls = (
            (0, "expected_generation_sha256", "e" * 64),
            (0, "maximum_results", 1),
            (1, "expected_generation_sha256", "e" * 64),
            (1, "maximum_results", 1),
            (2, "expected_generation_sha256", "e" * 64),
        )
        for step_index, field, value in extra_controls:
            with self.subTest(step=step_index, extra=field):
                gemma = _candidate_run(
                    candidate,
                    "gemma-4-31b-it-nvfp4",
                    10,
                    complex_extra_control=(step_index, field, value),
                )
                with patch.object(CheckedCandidate, "verify_unchanged"):
                    decision = evaluate_agent_model_qualification(
                        candidate=candidate, runs=(qwen, gemma)
                    )
                summary = next(
                    item
                    for item in decision["candidateSummaries"]
                    if item["candidateId"] == "gemma-4-31b-it-nvfp4"
                )
                self.assertEqual(decision["outcome"], "deterministic-no-model")
                self.assertFalse(summary["routeEvidencePassed"])

    def test_rejects_correct_answers_backing_unrelated_proposals(self) -> None:
        candidate = _checked_candidate()
        runs = (
            _candidate_run(
                candidate,
                "qwen3.6-35b-a3b-nvfp4",
                20,
                wrong_proposal_case="terminology-preservation-en",
            ),
            _candidate_run(
                candidate,
                "gemma-4-31b-it-nvfp4",
                10,
                wrong_proposal_case="complex-governed-orchestration",
            ),
        )

        with patch.object(CheckedCandidate, "verify_unchanged"):
            decision = evaluate_agent_model_qualification(
                candidate=candidate, runs=runs
            )

        self.assertEqual(decision["outcome"], "deterministic-no-model")
        self.assertEqual(decision["admittedModelCandidates"], [])
        self.assertTrue(
            all(
                summary["terminologyPreservation"] < 1.0
                for summary in decision["candidateSummaries"]
            )
        )

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
        other = _candidate_run(candidate, "gemma-4-31b-it-nvfp4", 10)
        with (
            patch.object(CheckedCandidate, "verify_unchanged"),
            self.assertRaisesRegex(ValueError, "digest"),
        ):
            evaluate_agent_model_qualification(
                candidate=candidate, runs=(tampered, other)
            )

    def test_rejects_runtime_with_disabled_structural_guidance_override(self) -> None:
        candidate = _checked_candidate()
        run = _candidate_run(candidate, "qwen3.6-35b-a3b-nvfp4", 20)
        lock = json.loads(
            (
                REPOSITORY_ROOT
                / "server"
                / "agent-reasoning-candidates.lock.json"
            ).read_text(encoding="utf-8")
        )
        candidate_lock = next(
            item
            for item in lock["candidates"]
            if item["candidateId"] == run.candidate_id
        )
        expected = {
            **candidate_lock,
            "_runtime": lock["runtimes"][candidate_lock["runtimeId"]],
        }
        receipt = {
            **run.runtime_receipt,
            "toolCallStructuralGuidanceEnabled": False,
        }

        with self.assertRaisesRegex(ValueError, "runtime receipt"):
            _validate_runtime_receipt(
                candidate,
                expected=expected,
                receipt=receipt,
                children=run.children,
            )

    def test_contained_failure_prevents_partial_route_qualification(self) -> None:
        candidate = _checked_candidate()
        failed = _failed_run(candidate, "qwen3.6-35b-a3b-nvfp4")
        completed = _candidate_run(candidate, "gemma-4-31b-it-nvfp4", 10)

        with patch.object(CheckedCandidate, "verify_unchanged"):
            decision = evaluate_agent_model_qualification(
                candidate=candidate, runs=(failed, completed)
            )

        self.assertEqual(decision["outcome"], "deterministic-no-model")
        self.assertEqual(
            decision["candidateSummaries"][0]["disposition"],
            "contained-candidate-rejection",
        )

    def test_rejects_obsolete_success_and_fixture_evidence_schemas(self) -> None:
        candidate = _checked_candidate()
        run = _candidate_run(candidate, "qwen3.6-35b-a3b-nvfp4", 20)
        other = _candidate_run(candidate, "gemma-4-31b-it-nvfp4", 10)
        obsolete_evidence = dict(run.evidence)
        obsolete_evidence.pop("evidenceSha256")
        obsolete_evidence["schemaVersion"] = 1
        obsolete_evidence["evidenceSha256"] = canonical_evidence_sha256(
            obsolete_evidence
        )
        obsolete = AgentCandidateRun(
            run.candidate_id,
            obsolete_evidence,
            run.runtime_receipt,
            run.children,
        )
        with (
            patch.object(CheckedCandidate, "verify_unchanged"),
            self.assertRaisesRegex(ValueError, "candidate evidence"),
        ):
            evaluate_agent_model_qualification(candidate=candidate, runs=(obsolete, other))

        children = {
            **run.children,
            "fixtures": {**run.children["fixtures"], "schemaVersion": 1},
        }
        with self.assertRaisesRegex(ValueError, "child evidence"):
            _verify_runtime_children(
                children,
                checked_head=candidate.checked_head,
                evidence_results=run.evidence["results"],
                pressure=run.evidence["runtimePressure"],
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
    incomplete_complex_sequence: bool = False,
    wrong_complex_traversal: bool = False,
    complex_extra_control: tuple[int, str, object] | None = None,
    wrong_proposal_case: str | None = None,
    fixture_latency: int = 10,
    fixture_latency_overrides: dict[str, int] | None = None,
) -> AgentCandidateRun:
    lock = json.loads(
        (REPOSITORY_ROOT / "server" / "agent-reasoning-candidates.lock.json").read_text(
            encoding="utf-8"
        )
    )
    model = next(
        item for item in lock["candidates"] if item["candidateId"] == candidate_id
    )
    runtime = lock["runtimes"][model["runtimeId"]]
    results = list(_perfect_results(str(model["workloadClass"])))
    if not passing:
        results[0]["toolName"] = "wrong_tool"
        results[0]["toolCalls"][0]["name"] = "wrong_tool"  # type: ignore[index]
    if incomplete_complex_sequence:
        complex_result = next(
            result
            for result in results
            if result["caseId"] == "complex-governed-orchestration"
        )
        complex_result["toolCalls"] = complex_result["toolCalls"][:-1]  # type: ignore[index]
    if wrong_complex_traversal:
        complex_result = next(
            result
            for result in results
            if result["caseId"] == "complex-governed-orchestration"
        )
        traversal = complex_result["toolCalls"][1]["arguments"]  # type: ignore[index]
        traversal["start_concept_id"] = "unrelated/concept"
    if complex_extra_control is not None:
        complex_result = next(
            result
            for result in results
            if result["caseId"] == "complex-governed-orchestration"
        )
        step_index, field, value = complex_extra_control
        arguments = complex_result["toolCalls"][step_index]["arguments"]  # type: ignore[index]
        arguments[field] = value
    if wrong_proposal_case is not None:
        proposal_result = next(
            result for result in results if result["caseId"] == wrong_proposal_case
        )
        proposal_result["arguments"]["proposed_content"] = (  # type: ignore[index]
            "Unrelated cafeteria menu."
        )
    for result in results:
        result["latencyMilliseconds"] = (fixture_latency_overrides or {}).get(
            str(result["caseId"]), fixture_latency
        )
    launch_arguments = _launch_arguments(model)
    launch_sha256 = canonical_evidence_sha256(launch_arguments)
    children = _children(
        candidate,
        model,
        results,
        latency,
        launch_sha256,
        runtime["observedImageId"],
    )
    receipt = {
        "schemaVersion": 1,
        "checkedHead": candidate.checked_head,
        "candidateId": candidate_id,
        "model": model["model"],
        "revision": model["revision"],
        "runtime": runtime,
        "imageId": runtime["observedImageId"],
        "quantization": model["quantization"],
        "modelArtifactManifestSha256": model["artifactManifestSha256"],
        "launchArguments": launch_arguments,
        "launchArgumentsSha256": launch_sha256,
        "toolCallStructuralGuidanceEnabled": True,
        "childEvidenceSha256": {
            name: agent_evidence_sha256(value) for name, value in children.items()
        },
        "teardown": {
            "containerAbsent": True,
            "listenerAbsent": True,
            "ownedWorkersReaped": True,
            "ownedCgroupEmpty": True,
            "sameLabelOwnersAbsent": True,
        },
    }
    evidence = bind_checked_candidate_evidence(
        {
            "schemaVersion": 2,
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
    runtime = lock["runtimes"][model["runtimeId"]]
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
                "imageId": runtime["observedImageId"],
                "modelArtifactManifestSha256": model["artifactManifestSha256"],
                "launchArguments": launch_arguments,
                "launchArgumentsSha256": canonical_evidence_sha256(launch_arguments),
                "teardown": {
                    "containerAbsent": True,
                    "listenerAbsent": True,
                    "ownedWorkersReaped": True,
                    "ownedCgroupEmpty": True,
                    "sameLabelOwnersAbsent": True,
                },
            },
        },
        candidate,
    )
    return FailedAgentCandidateRun(candidate_id, failure)


def _children(candidate, model, results, latency, launch_sha256, image_id):
    return {
        "fixtures": {
            "schemaVersion": 2,
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
            "imageId": image_id,
            "modelArtifactManifestSha256": model["artifactManifestSha256"],
            "launchArgumentsSha256": launch_sha256,
            "endpoint": "http://127.0.0.1:30000",
        },
    }


def _perfect_results(workload_class: str) -> tuple[dict[str, object], ...]:
    fixture = json.loads(
        (REPOSITORY_ROOT / "server" / "agent-workload-fixtures.json").read_text(
            encoding="utf-8"
        )
    )
    results: list[dict[str, object]] = []
    for case in fixture["cases"]:
        if case.get("requiredForWorkloadClass") not in {None, workload_class}:
            continue
        arguments = dict(case.get("expectedArguments", {}))
        arguments["purpose"] = "knowledge.read"
        if case["expectedTool"] == "search_knowledge":
            arguments.setdefault("search_text", case["user"])
        if "expectedProposalType" in case and "expectedArguments" not in case:
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
                "answer": case.get(
                    "expectedAnswer", " ".join(case.get("requiredTerms", []))
                ),
                "citationConceptIds": case.get("requiredCitationConceptIds", []),
                "latencyMilliseconds": 10,
                "modelRequestCount": len(
                    case.get("expectedToolSequence", [case["expectedTool"]])
                )
                + 1,
                "toolCalls": _perfect_tool_calls(case, arguments),
            }
        )
    return tuple(results)


def _perfect_tool_calls(
    case: dict[str, object], final_arguments: dict[str, object]
) -> list[dict[str, object]]:
    sequence = case.get("expectedToolSequence", [case["expectedTool"]])
    assert isinstance(sequence, list)
    calls: list[dict[str, object]] = []
    expected_calls = case.get("expectedToolCalls")
    for index, name in enumerate(sequence):
        if name == case["expectedTool"]:
            arguments = final_arguments
        elif isinstance(expected_calls, list):
            arguments = dict(expected_calls[index]["expectedArguments"])
        elif name == "search_knowledge":
            arguments = {
                "purpose": "knowledge.read",
                "search_text": str(case["user"]),
            }
        else:
            arguments = {
                "purpose": "knowledge.read",
                "start_concept_id": "project/voiceos",
                "maximum_depth": 2,
            }
        calls.append({"name": name, "arguments": arguments})
    return calls


def _launch_arguments(model: dict[str, object]) -> list[str]:
    return build_agent_vllm_launch_arguments(model)


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
