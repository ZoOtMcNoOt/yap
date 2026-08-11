from __future__ import annotations

import json
from pathlib import Path
import unittest

from yap_server.evaluation.agent_model_acceptance import (
    _fixtures,
    _runtime_tracks,
    load_agent_model_acceptance,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


class AgentModelAcceptanceTests(unittest.TestCase):
    def test_freezes_nvidia_vllm_2607_arm64_runtime(self) -> None:
        candidate_lock = json.loads(
            (
                REPOSITORY_ROOT
                / "server"
                / "agent-reasoning-candidates.lock.json"
            ).read_text(encoding="utf-8")
        )

        self.assertEqual(
            candidate_lock["runtime"],
            {
                "engine": "vllm",
                "image": "nvcr.io/nvidia/vllm:26.07-py3",
                "digest": "sha256:1de8e6bfdb4c81c1f31a806cc9b13b5c6352714a7cec87f4d24964bcc91159b2",
                "platform": "linux/arm64",
                "python": "3.12",
                "vllm": "0.24.0+092c4842.nv26.7.59534043",
            },
        )

    def test_loads_frozen_candidate_runtime_and_workload_identity(self) -> None:
        plan = load_agent_model_acceptance(REPOSITORY_ROOT)

        self.assertEqual(
            plan.candidate_ids,
            (
                "qwen3.6-35b-a3b-nvfp4",
                "gemma-4-31b-it-nvfp4",
            ),
        )
        self.assertEqual(
            plan.required_routes,
            {
                "complex-orchestration": "gemma-4-31b-it-nvfp4",
                "rapid-automation": "qwen3.6-35b-a3b-nvfp4",
            },
        )
        self.assertEqual(len(plan.case_ids), 13)
        self.assertEqual(
            plan.permitted_outcomes,
            ("required-workload-routes-qualified", "deterministic-no-model"),
        )
        self.assertEqual(plan.runtime_tracks["requestTimeoutSeconds"], 30)
        self.assertEqual(plan.runtime_tracks["maximumFinalResponseAttempts"], 2)
        self.assertEqual(
            plan.route_evidence["complex-orchestration"]["requestTimeoutSeconds"],
            60,
        )
        self.assertEqual(
            plan.route_evidence["rapid-automation"]["maximumOutputTokens"], 256
        )
        self.assertEqual(
            plan.route_evidence["complex-orchestration"]["maximumOutputTokens"],
            512,
        )

        fixtures = json.loads(
            (REPOSITORY_ROOT / "server" / "agent-workload-fixtures.json").read_text(
                encoding="utf-8"
            )
        )
        visible_case = next(case for case in fixtures["cases"] if case["visibleContext"])
        visible_case["visibleContext"][0]["charEnd"] -= 1
        with self.assertRaisesRegex(ValueError, "visible context span"):
            _fixtures(fixtures)
        visible_case["visibleContext"][0]["charEnd"] += 1
        digest = visible_case["visibleContext"][0]["contentSha256"]
        visible_case["visibleContext"][0]["contentSha256"] = int("1" * 64)
        with self.assertRaisesRegex(ValueError, "visible context identity"):
            _fixtures(fixtures)
        visible_case["visibleContext"][0]["contentSha256"] = digest

        empty_case = next(
            case for case in fixtures["cases"] if case["visibleContext"] == []
        )
        empty_case.pop("expectedAnswer")
        with self.assertRaisesRegex(ValueError, "empty agent evidence"):
            _fixtures(fixtures)

        empty_case["expectedAnswer"] = "Evidence is unavailable."
        empty_case["maximumOutputTokens"] = True
        with self.assertRaisesRegex(ValueError, "case output bound"):
            _fixtures(fixtures)

        empty_case["maximumOutputTokens"] = 128
        proposal_case = next(
            case
            for case in fixtures["cases"]
            if case["caseId"] == "cited-summary-proposal"
        )
        source_citations = proposal_case["expectedArguments"].pop("source_citations")
        with self.assertRaisesRegex(ValueError, "expected arguments"):
            _fixtures(fixtures)
        proposal_case["expectedArguments"]["source_citations"] = source_citations
        proposal_case["expectedArguments"]["proposal_type"] = "relationship"
        with self.assertRaisesRegex(ValueError, "cited proposal"):
            _fixtures(fixtures)

    def test_freezes_two_final_response_attempts(self) -> None:
        tracks = load_agent_model_acceptance(REPOSITORY_ROOT).runtime_tracks

        for invalid in (True, 1, 2.0, 3):
            with self.subTest(invalid=invalid):
                changed = {**tracks, "maximumFinalResponseAttempts": invalid}
                with self.assertRaisesRegex(ValueError, "final response attempts"):
                    _runtime_tracks(changed)


if __name__ == "__main__":
    unittest.main()
