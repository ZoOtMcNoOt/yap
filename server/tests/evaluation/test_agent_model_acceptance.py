from __future__ import annotations

import json
from pathlib import Path
import unittest

from yap_server.evaluation.agent_model_acceptance import (
    _fixtures,
    load_agent_model_acceptance,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


class AgentModelAcceptanceTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
