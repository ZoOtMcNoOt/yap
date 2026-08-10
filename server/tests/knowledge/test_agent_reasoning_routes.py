from __future__ import annotations

import threading
import unittest

from yap_server.knowledge.agent_reasoning_routes import (
    AgentReasoningRoutes,
    AgentWorkloadClass,
)


class AgentReasoningRoutesTests(unittest.TestCase):
    def test_selects_only_the_explicit_workload_route(self) -> None:
        calls: list[str] = []
        routes = AgentReasoningRoutes(
            rapid_automation=lambda _prompt, _cancel: calls.append("rapid") or "qwen",
            complex_orchestration=lambda _prompt, _cancel: calls.append("complex")
            or "gemma",
        )

        result = routes.reason(
            AgentWorkloadClass.COMPLEX_ORCHESTRATION,
            "plan",
            threading.Event(),
        )

        self.assertEqual(result, "gemma")
        self.assertEqual(calls, ["complex"])

    def test_route_failure_does_not_invoke_the_other_model(self) -> None:
        calls: list[str] = []

        def fail(_prompt: str, _cancel: threading.Event) -> str:
            calls.append("rapid")
            raise RuntimeError("qwen unavailable")

        routes = AgentReasoningRoutes(
            rapid_automation=fail,
            complex_orchestration=lambda _prompt, _cancel: calls.append("complex")
            or "gemma",
        )

        with self.assertRaisesRegex(RuntimeError, "qwen unavailable"):
            routes.reason(
                AgentWorkloadClass.RAPID_AUTOMATION,
                "automate",
                threading.Event(),
            )
        self.assertEqual(calls, ["rapid"])


if __name__ == "__main__":
    unittest.main()
