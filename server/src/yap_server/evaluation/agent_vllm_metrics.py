from __future__ import annotations

from typing import Mapping

from .vllm_runtime_metrics import VllmMetricsSnapshot, VllmRuntimeMetricsClient


_ZERO_FINISH_REASONS = {
    "stop": 0,
    "length": 0,
    "abort": 0,
    "error": 0,
    "repetition": 0,
}


class AgentVllmActivity:
    """Prove cancellation and recovery from vLLM engine counters."""

    def __init__(self, client: VllmRuntimeMetricsClient) -> None:
        self._client = client

    def begin_cancellation(self, *, timeout_seconds: float) -> VllmMetricsSnapshot:
        return self._client.wait_for_idle(timeout_seconds=timeout_seconds)

    def wait_until_running(self, *, timeout_seconds: float) -> None:
        self._client.wait_for_running_requests(
            minimum=1, timeout_seconds=timeout_seconds
        )

    def after_cancellation(
        self, token: object, *, timeout_seconds: float
    ) -> tuple[VllmMetricsSnapshot, Mapping[str, int]]:
        before = _snapshot(token)
        after = self._client.wait_for_idle(timeout_seconds=timeout_seconds)
        delta = after.delta(before)
        finish_reasons = dict(delta.finished_requests)
        aborted_without_completion = (
            delta.successful_requests == 0 and finish_reasons == _ZERO_FINISH_REASONS
        )
        aborted_with_reason = delta.successful_requests == 1 and finish_reasons == {
            **_ZERO_FINISH_REASONS,
            "abort": 1,
        }
        if not (aborted_without_completion or aborted_with_reason):
            raise RuntimeError("cancelled agent request completed in the vLLM engine")
        return after, finish_reasons

    def after_recovery(
        self, token: object, *, timeout_seconds: float
    ) -> Mapping[str, int]:
        before = _snapshot(token)
        after = self._client.wait_for_idle(timeout_seconds=timeout_seconds)
        delta = after.delta(before)
        finish_reasons = dict(delta.finished_requests)
        if delta.successful_requests != 1 or finish_reasons != {
            **_ZERO_FINISH_REASONS,
            "stop": 1,
        }:
            raise RuntimeError("agent runtime recovery was not engine-observed")
        return finish_reasons


def _snapshot(value: object) -> VllmMetricsSnapshot:
    if not isinstance(value, VllmMetricsSnapshot):
        raise TypeError("agent vLLM metrics token is invalid")
    return value


__all__ = ["AgentVllmActivity"]
