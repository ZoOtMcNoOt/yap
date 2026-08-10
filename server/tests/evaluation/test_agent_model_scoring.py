from __future__ import annotations

import json
from pathlib import Path
import unittest

from yap_server.evaluation.agent_model_scoring import score_agent_model_results


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


class AgentModelScoringTests(unittest.TestCase):
    def test_derives_perfect_score_without_trusting_aggregate_flags(self) -> None:
        results = _perfect_results()

        score = score_agent_model_results(REPOSITORY_ROOT, results)

        self.assertTrue(score.passed)
        self.assertEqual(score.tool_selection_accuracy, 1.0)
        self.assertEqual(score.citation_fidelity, 1.0)

    def test_detects_cross_tenant_marker_and_invalid_output(self) -> None:
        results = list(_perfect_results())
        target = next(
            index
            for index, result in enumerate(results)
            if result["caseId"] == "tenant-a-cache-marker"
        )
        results[target] = {
            **results[target],
            "answer": results[target]["answer"] + " BRAVO-2M4",
            "callerPassed": True,
        }

        score = score_agent_model_results(REPOSITORY_ROOT, tuple(results))

        self.assertFalse(score.passed)
        self.assertEqual(score.isolation_leak_count, 1)
        self.assertEqual(score.invalid_structured_output_count, 1)

    def test_counts_forbidden_claims_and_tools_as_leaks(self) -> None:
        results = list(_perfect_results())
        results[6]["answer"] = "The acquisition price is hidden value."
        results[7]["answer"] = "Use the filesystem."

        score = score_agent_model_results(REPOSITORY_ROOT, tuple(results))

        self.assertEqual(score.isolation_leak_count, 3)
        self.assertFalse(score.passed)


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
            arguments["proposal_type"] = case["expectedProposalType"]
            arguments["proposed_content"] = " ".join(case.get("requiredTerms", []))
            arguments["source_citations"] = [
                {"concept_id": concept_id}
                for concept_id in case.get("requiredCitationConceptIds", [])
            ]
        answer = " ".join(case.get("requiredTerms", []))
        results.append(
            {
                "caseId": case["caseId"],
                "toolName": case["expectedTool"],
                "arguments": arguments,
                "answer": answer,
                "citationConceptIds": case.get("requiredCitationConceptIds", []),
                "latencyMilliseconds": 10,
            }
        )
    return tuple(results)


if __name__ == "__main__":
    unittest.main()
