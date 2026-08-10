from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import threading
from typing import Callable


ReasoningFunction = Callable[[str, threading.Event], str]


class AgentWorkloadClass(StrEnum):
    RAPID_AUTOMATION = "rapid-automation"
    COMPLEX_ORCHESTRATION = "complex-orchestration"


@dataclass(frozen=True, slots=True)
class AgentReasoningRoutes:
    """Select one explicit reasoning route without cross-model fallback."""

    rapid_automation: ReasoningFunction
    complex_orchestration: ReasoningFunction

    def reason(
        self,
        workload_class: AgentWorkloadClass,
        prompt: str,
        cancellation: threading.Event,
    ) -> str:
        if workload_class is AgentWorkloadClass.RAPID_AUTOMATION:
            route = self.rapid_automation
        elif workload_class is AgentWorkloadClass.COMPLEX_ORCHESTRATION:
            route = self.complex_orchestration
        else:
            raise ValueError("agent workload class is invalid")
        return route(prompt, cancellation)


__all__ = ["AgentReasoningRoutes", "AgentWorkloadClass"]
