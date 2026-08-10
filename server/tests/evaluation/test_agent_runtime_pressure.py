from __future__ import annotations

import threading
from pathlib import Path

import pytest

from yap_server.knowledge.knowledge_tool_contract import KnowledgeToolCancelled
from yap_server.evaluation.agent_runtime_pressure import run_agent_runtime_pressure

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def test_runs_every_frozen_pressure_track() -> None:
    prompts: list[str] = []

    def request(prompt: str, cancellation: threading.Event) -> str:
        prompts.append(prompt)
        if "until cancelled" in prompt:
            cancellation.wait(1)
        if cancellation.is_set():
            raise KnowledgeToolCancelled("cancelled")
        if "ALPHA-7Q9" in prompt:
            return "ALPHA-7Q9"
        if "BRAVO-2M4" in prompt:
            return "BRAVO-2M4"
        return "ok"

    result = run_agent_runtime_pressure(
        REPOSITORY_ROOT,
        request=request,
        memory_bytes=lambda: 123,
    )

    assert len(result.warm_latency_milliseconds) == 12
    assert {
        level: len(values)
        for level, values in result.concurrency_latency_milliseconds.items()
    } == {1: 1, 2: 2, 4: 4, 8: 8}
    assert result.baseline_memory_bytes == 123
    assert result.peak_memory_bytes == 123
    assert result.isolation_leak_count == 0
    assert result.cancelled_request_completion_count == 0
    assert len(prompts) == 1 + 12 + 1 + 2 + 4 + 8 + 8 + 1


def test_detects_cross_request_marker_leak() -> None:
    def request(prompt: str, cancellation: threading.Event) -> str:
        if "until cancelled" in prompt:
            cancellation.wait(1)
        if cancellation.is_set():
            raise KnowledgeToolCancelled("cancelled")
        if "ALPHA-7Q9" in prompt:
            return "ALPHA-7Q9 BRAVO-2M4"
        return "ok"

    result = run_agent_runtime_pressure(
        REPOSITORY_ROOT, request=request, memory_bytes=lambda: 0
    )

    assert result.isolation_leak_count == 4


def test_rejects_unrelated_cancellation_failure() -> None:
    def request(prompt: str, cancellation: threading.Event) -> str:
        if "until cancelled" in prompt:
            raise OSError("transport failed")
        if "ALPHA-7Q9" in prompt:
            return "ALPHA-7Q9"
        if "BRAVO-2M4" in prompt:
            return "BRAVO-2M4"
        return "ok"

    with pytest.raises(RuntimeError, match="failed incorrectly"):
        run_agent_runtime_pressure(
            REPOSITORY_ROOT,
            request=request,
            memory_bytes=lambda: 0,
        )
