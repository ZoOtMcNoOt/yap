from __future__ import annotations

import unittest

from yap_server.evaluation.vllm_runtime_metrics import (
    VllmRuntimeMetricsClient,
    parse_vllm_runtime_metrics,
)
from yap_server.pools.batch_contract import WorkerExecutionError


def _metrics(*, offset: int = 0, running: int = 0) -> str:
    lines = [
        f'vllm:num_requests_running{{model_name="test"}} {running}',
        'vllm:num_requests_waiting{model_name="test"} 0',
        f'vllm:request_success_total{{finished_reason="stop"}} {10 + offset}',
        'vllm:request_success_total{finished_reason="length"} 0',
        'vllm:request_success_total{finished_reason="abort"} 0',
        'vllm:request_success_total{finished_reason="error"} 0',
        'vllm:request_success_total{finished_reason="repetition"} 0',
    ]
    for name, total in (
        ("vllm:e2e_request_latency_seconds", 3.0),
        ("vllm:request_inference_time_seconds", 2.0),
        ("vllm:request_queue_time_seconds", 1.0),
    ):
        count = 10 + offset
        lines.extend(
            (
                f'{name}_bucket{{le="0.1",model_name="test"}} {4 + offset}',
                f'{name}_bucket{{le="0.5",model_name="test"}} {9 + offset}',
                f'{name}_bucket{{le="+Inf",model_name="test"}} {count}',
                f'{name}_count{{model_name="test"}} {count}',
                f'{name}_sum{{model_name="test"}} {total + offset * 0.2}',
            )
        )
    return "\n".join(lines) + "\n"


class _Response:
    def __init__(self, body: bytes, *, status: int = 200) -> None:
        self.status = status
        self._body = body

    def getheader(self, name: str) -> str | None:
        return "text/plain; version=0.0.4" if name == "Content-Type" else None

    def read(self, amount: int = -1) -> bytes:
        return self._body[:amount]


class _Connection:
    def __init__(self, response: _Response) -> None:
        self.response = response
        self.requested: tuple[str, str] | None = None
        self.closed = False

    def request(self, method: str, path: str) -> None:
        self.requested = (method, path)

    def getresponse(self) -> _Response:
        return self.response

    def close(self) -> None:
        self.closed = True


class VllmRuntimeMetricsTests(unittest.TestCase):
    def test_parses_aggregate_gauges_histograms_and_safe_deltas(self) -> None:
        before = parse_vllm_runtime_metrics(_metrics())
        after = parse_vllm_runtime_metrics(_metrics(offset=2))

        delta = after.delta(before).public_evidence()

        self.assertEqual(delta["successfulEngineRequests"], 2)
        self.assertEqual(delta["engineFinishReasons"]["stop"], 2)  # type: ignore[index]
        self.assertEqual(delta["engineFinishReasons"]["abort"], 0)  # type: ignore[index]
        self.assertEqual(delta["queueTime"]["count"], 2)  # type: ignore[index]
        self.assertEqual(delta["queueTime"]["meanMs"], 200.0)  # type: ignore[index]
        self.assertEqual(
            delta["queueTime"]["p99UpperBoundMs"],  # type: ignore[index]
            100.0,
        )

    def test_sums_metric_label_sets_without_exposing_labels(self) -> None:
        duplicated = _metrics() + _metrics()
        snapshot = parse_vllm_runtime_metrics(duplicated)

        self.assertEqual(snapshot.successful_requests, 20)
        self.assertEqual(snapshot.histograms["vllm:request_queue_time_seconds"].count, 20)

    def test_rejects_incomplete_or_reversed_metrics(self) -> None:
        with self.assertRaisesRegex(ValueError, "incomplete"):
            parse_vllm_runtime_metrics("vllm:num_requests_running 0\n")
        before = parse_vllm_runtime_metrics(_metrics(offset=2))
        after = parse_vllm_runtime_metrics(_metrics())
        with self.assertRaisesRegex(ValueError, "backwards"):
            after.delta(before)

    def test_client_requires_numeric_loopback_and_bounded_plain_text(self) -> None:
        with self.assertRaisesRegex(ValueError, "numeric"):
            VllmRuntimeMetricsClient("http://localhost:8000")

        connection = _Connection(_Response(_metrics(running=1).encode("utf-8")))
        client = VllmRuntimeMetricsClient(
            "http://127.0.0.1:8000",
            connection_factory=lambda _host, _port, _timeout: connection,  # type: ignore[arg-type]
        )
        snapshot = client.snapshot()
        self.assertEqual(snapshot.running_requests, 1)
        self.assertEqual(connection.requested, ("GET", "/metrics"))
        self.assertTrue(connection.closed)

        failed = _Connection(_Response(b"nope", status=503))
        client = VllmRuntimeMetricsClient(
            "http://127.0.0.1:8000",
            connection_factory=lambda _host, _port, _timeout: failed,  # type: ignore[arg-type]
        )
        with self.assertRaises(WorkerExecutionError):
            client.snapshot()


if __name__ == "__main__":
    unittest.main()
