from __future__ import annotations

import unittest

from yap_server.evaluation.agent_vllm_metrics import AgentVllmActivity
from yap_server.evaluation.vllm_runtime_metrics import parse_vllm_runtime_metrics


class _Client:
    def __init__(self, snapshots: list[object]) -> None:
        self.snapshots = snapshots
        self.running_observed = False

    def wait_for_idle(self, *, timeout_seconds: float):
        return self.snapshots.pop(0)

    def wait_for_running_requests(self, *, minimum: int, timeout_seconds: float):
        self.running_observed = minimum == 1


class AgentVllmActivityTests(unittest.TestCase):
    def test_proves_abort_without_completion_and_exact_recovery(self) -> None:
        client = _Client([_snapshot(10), _snapshot(10), _snapshot(11)])
        activity = AgentVllmActivity(client)  # type: ignore[arg-type]

        token = activity.begin_cancellation(timeout_seconds=1)
        activity.wait_until_running(timeout_seconds=1)
        recovery, cancelled = activity.after_cancellation(token, timeout_seconds=1)
        recovered = activity.after_recovery(recovery, timeout_seconds=1)

        self.assertTrue(client.running_observed)
        self.assertEqual(cancelled, _reasons())
        self.assertEqual(recovered, _reasons(stop=1))

    def test_rejects_normally_completed_cancelled_request(self) -> None:
        client = _Client([_snapshot(10), _snapshot(11)])
        activity = AgentVllmActivity(client)  # type: ignore[arg-type]

        token = activity.begin_cancellation(timeout_seconds=1)
        with self.assertRaisesRegex(RuntimeError, "completed"):
            activity.after_cancellation(token, timeout_seconds=1)


def _snapshot(total: int):
    reasons = _reasons(stop=total)
    lines = [
        "vllm:num_requests_running 0",
        "vllm:num_requests_waiting 0",
        *(
            f'vllm:request_success_total{{finished_reason="{key}"}} {value}'
            for key, value in reasons.items()
        ),
    ]
    for name in (
        "vllm:e2e_request_latency_seconds",
        "vllm:request_inference_time_seconds",
        "vllm:request_queue_time_seconds",
    ):
        lines.extend(
            (
                f'{name}_bucket{{le="1"}} {total}',
                f'{name}_bucket{{le="+Inf"}} {total}',
                f"{name}_count {total}",
                f"{name}_sum {total}",
            )
        )
    return parse_vllm_runtime_metrics("\n".join(lines) + "\n")


def _reasons(*, stop: int = 0) -> dict[str, int]:
    return {
        "stop": stop,
        "length": 0,
        "abort": 0,
        "error": 0,
        "repetition": 0,
    }


if __name__ == "__main__":
    unittest.main()
