from __future__ import annotations

import threading
from pathlib import Path
import json
import re
import unittest

from yap_server.knowledge.knowledge_tool_contract import KnowledgeToolCancelled
from yap_server.evaluation.agent_runtime_pressure import run_agent_runtime_pressure

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


class _RuntimeActivity:
    def begin_cancellation(self, *, timeout_seconds: float):
        return object()

    def wait_until_running(self, *, timeout_seconds: float):
        return None

    def after_cancellation(self, token: object, *, timeout_seconds: float):
        return object(), {
            "stop": 0,
            "length": 0,
            "abort": 1,
            "error": 0,
            "repetition": 0,
        }

    def after_recovery(self, token: object, *, timeout_seconds: float):
        return {
            "stop": 1,
            "length": 0,
            "abort": 0,
            "error": 0,
            "repetition": 0,
        }


def _runs_every_frozen_pressure_track() -> None:
    prompts: list[str] = []

    def request(prompt: str, cancellation: threading.Event) -> str:
        prompts.append(prompt)
        if "until cancelled" in prompt:
            cancellation.wait(1)
        if cancellation.is_set():
            raise KnowledgeToolCancelled("cancelled")
        if "ALPHA-7Q9" in prompt:
            return _answer("ALPHA-7Q9")
        if "BRAVO-2M4" in prompt:
            return _answer("BRAVO-2M4")
        return _answer(_expected_marker(prompt))

    def dispatched_request(
        prompt: str, cancellation: threading.Event, dispatched: threading.Event
    ) -> str:
        dispatched.set()
        return request(prompt, cancellation)

    result = run_agent_runtime_pressure(
        REPOSITORY_ROOT,
        request=request,
        dispatched_request=dispatched_request,
        memory_bytes=lambda: 123,
        runtime_activity=_RuntimeActivity(),
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
    assert len(prompts) == 1 + 12 + 1 + 2 + 4 + 8 + 8 + 1 + 1


def _detects_cross_request_marker_leak() -> None:
    def request(prompt: str, cancellation: threading.Event) -> str:
        if "until cancelled" in prompt:
            cancellation.wait(1)
        if cancellation.is_set():
            raise KnowledgeToolCancelled("cancelled")
        if "ALPHA-7Q9" in prompt:
            return _answer("ALPHA-7Q9 BRAVO-2M4")
        if "BRAVO-2M4" in prompt:
            return _answer("BRAVO-2M4")
        return _answer(_expected_marker(prompt))

    result = run_agent_runtime_pressure(
        REPOSITORY_ROOT,
        request=request,
        dispatched_request=lambda prompt, cancellation, dispatched: (
            dispatched.set() or request(prompt, cancellation)
        ),
        memory_bytes=lambda: 0,
        runtime_activity=_RuntimeActivity(),
    )

    assert result.isolation_leak_count == 4


def _rejects_unrelated_cancellation_failure() -> None:
    def request(prompt: str, cancellation: threading.Event) -> str:
        if "until cancelled" in prompt:
            raise OSError("transport failed")
        if "ALPHA-7Q9" in prompt:
            return _answer("ALPHA-7Q9")
        if "BRAVO-2M4" in prompt:
            return _answer("BRAVO-2M4")
        return _answer(_expected_marker(prompt))

    def dispatched_request(
        prompt: str, cancellation: threading.Event, dispatched: threading.Event
    ) -> str:
        dispatched.set()
        return request(prompt, cancellation)

    with unittest.TestCase().assertRaisesRegex(RuntimeError, "failed incorrectly"):
        run_agent_runtime_pressure(
            REPOSITORY_ROOT,
            request=request,
            dispatched_request=dispatched_request,
            memory_bytes=lambda: 0,
            runtime_activity=_RuntimeActivity(),
        )


def _requires_observed_engine_activity_before_cancellation() -> None:
    class MissingActivity(_RuntimeActivity):
        def wait_until_running(self, *, timeout_seconds: float):
            raise TimeoutError("no engine activity")

    def request(prompt: str, cancellation: threading.Event) -> str:
        if "until cancelled" in prompt:
            cancellation.wait(1)
        if cancellation.is_set():
            raise KnowledgeToolCancelled("cancelled")
        if "ALPHA-7Q9" in prompt:
            return _answer("ALPHA-7Q9")
        if "BRAVO-2M4" in prompt:
            return _answer("BRAVO-2M4")
        return _answer(_expected_marker(prompt))

    with unittest.TestCase().assertRaisesRegex(TimeoutError, "no engine activity"):
        run_agent_runtime_pressure(
            REPOSITORY_ROOT,
            request=request,
            dispatched_request=lambda prompt, cancellation, dispatched: (
                dispatched.set() or request(prompt, cancellation)
            ),
            memory_bytes=lambda: 0,
            runtime_activity=MissingActivity(),
        )


class AgentRuntimePressureTests(unittest.TestCase):
    def test_runs_every_frozen_pressure_track(self) -> None:
        _runs_every_frozen_pressure_track()

    def test_detects_cross_request_marker_leak(self) -> None:
        _detects_cross_request_marker_leak()

    def test_rejects_unrelated_cancellation_failure(self) -> None:
        _rejects_unrelated_cancellation_failure()

    def test_requires_observed_engine_activity_before_cancellation(self) -> None:
        _requires_observed_engine_activity_before_cancellation()


def _answer(value: str) -> str:
    return json.dumps({"answer": value, "citationConceptIds": []})


def _expected_marker(prompt: str) -> str:
    match = re.search(r"Return exactly ([A-Z0-9-]+)\.?", prompt)
    assert match is not None
    return match.group(1)
