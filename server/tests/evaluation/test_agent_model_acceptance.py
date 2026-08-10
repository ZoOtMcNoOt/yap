from __future__ import annotations

from pathlib import Path
import unittest

from yap_server.evaluation.agent_model_acceptance import load_agent_model_acceptance


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


if __name__ == "__main__":
    unittest.main()
