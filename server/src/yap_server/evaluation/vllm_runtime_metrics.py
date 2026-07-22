from __future__ import annotations

from dataclasses import dataclass
import http.client
import math
import re
import time
from typing import Callable, Mapping

from yap_server.pools.authenticated_loopback_http import (
    parse_numeric_loopback_http_endpoint,
)
from yap_server.pools.batch_contract import WorkerExecutionError


_MAX_METRICS_BYTES = 2 * 1024 * 1024
_METRIC_LINE = re.compile(
    r"^(?P<identity>[A-Za-z_:][A-Za-z0-9_:]*(?:\{[^{}]*\})?)\s+"
    r"(?P<value>[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)"
    r"(?:\s+\d+)?$"
)
_LE_LABEL = re.compile(r'(?:\{|,)le="(?P<value>[^"\\]+)"(?:,|\})')
_FINISHED_REASON_LABEL = re.compile(
    r'(?:\{|,)finished_reason="(?P<value>[^"\\]+)"(?:,|\})'
)
_FINISH_REASONS = ("stop", "length", "abort", "error", "repetition")
_HISTOGRAMS = (
    "vllm:e2e_request_latency_seconds",
    "vllm:request_inference_time_seconds",
    "vllm:request_queue_time_seconds",
)
_RELEVANT_METRICS = frozenset(
    {
        "vllm:num_requests_running",
        "vllm:num_requests_waiting",
        "vllm:request_success_total",
        *(
            f"{histogram}_{suffix}"
            for histogram in _HISTOGRAMS
            for suffix in ("bucket", "count", "sum")
        ),
    }
)


@dataclass(frozen=True, slots=True)
class VllmHistogramSnapshot:
    count: int
    total_seconds: float
    cumulative_buckets: tuple[tuple[float, int], ...]

    def __post_init__(self) -> None:
        if (
            isinstance(self.count, bool)
            or not isinstance(self.count, int)
            or self.count < 0
            or not math.isfinite(self.total_seconds)
            or self.total_seconds < 0
            or not self.cumulative_buckets
        ):
            raise ValueError("vLLM histogram snapshot is invalid")
        previous_boundary = -math.inf
        previous_count = 0
        for boundary, count in self.cumulative_buckets:
            if (
                boundary <= previous_boundary
                or isinstance(count, bool)
                or not isinstance(count, int)
                or count < previous_count
            ):
                raise ValueError("vLLM histogram buckets are invalid")
            previous_boundary = boundary
            previous_count = count
        if not math.isinf(previous_boundary) or previous_count != self.count:
            raise ValueError("vLLM histogram count differs from its buckets")

    def delta(self, before: VllmHistogramSnapshot) -> VllmHistogramDelta:
        if tuple(boundary for boundary, _count in self.cumulative_buckets) != tuple(
            boundary for boundary, _count in before.cumulative_buckets
        ):
            raise ValueError("vLLM histogram bucket boundaries changed")
        count = self.count - before.count
        total_seconds = self.total_seconds - before.total_seconds
        bucket_counts = tuple(
            (boundary, after_count - before_count)
            for (boundary, after_count), (_same, before_count) in zip(
                self.cumulative_buckets,
                before.cumulative_buckets,
                strict=True,
            )
        )
        return VllmHistogramDelta(
            count=count,
            total_seconds=total_seconds,
            cumulative_buckets=bucket_counts,
        )


@dataclass(frozen=True, slots=True)
class VllmHistogramDelta:
    count: int
    total_seconds: float
    cumulative_buckets: tuple[tuple[float, int], ...]

    def __post_init__(self) -> None:
        VllmHistogramSnapshot(
            count=self.count,
            total_seconds=self.total_seconds,
            cumulative_buckets=self.cumulative_buckets,
        )

    def public_evidence(self) -> dict[str, object]:
        return {
            "count": self.count,
            "meanMs": (
                round(self.total_seconds * 1_000 / self.count, 3)
                if self.count
                else None
            ),
            "p50UpperBoundMs": self._percentile_upper_bound_ms(0.50),
            "p95UpperBoundMs": self._percentile_upper_bound_ms(0.95),
            "p99UpperBoundMs": self._percentile_upper_bound_ms(0.99),
        }

    def _percentile_upper_bound_ms(self, percentile: float) -> float | None:
        if self.count == 0:
            return None
        rank = math.ceil(self.count * percentile)
        for boundary, cumulative_count in self.cumulative_buckets:
            if cumulative_count >= rank:
                return None if math.isinf(boundary) else round(boundary * 1_000, 3)
        raise RuntimeError("vLLM histogram delta omitted its terminal bucket")


@dataclass(frozen=True, slots=True)
class VllmMetricsSnapshot:
    running_requests: int
    waiting_requests: int
    successful_requests: int
    finished_requests: Mapping[str, int]
    histograms: Mapping[str, VllmHistogramSnapshot]

    def __post_init__(self) -> None:
        for value in (
            self.running_requests,
            self.waiting_requests,
            self.successful_requests,
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError("vLLM request metric is invalid")
        if set(self.histograms) != set(_HISTOGRAMS):
            raise ValueError("vLLM runtime histograms are incomplete")
        if set(self.finished_requests) != set(_FINISH_REASONS) or any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in self.finished_requests.values()
        ):
            raise ValueError("vLLM finish-reason metrics are incomplete")
        if sum(self.finished_requests.values()) != self.successful_requests:
            raise ValueError("vLLM success total differs from its finish reasons")

    def delta(self, before: VllmMetricsSnapshot) -> VllmMetricsDelta:
        successful_requests = self.successful_requests - before.successful_requests
        if successful_requests < 0:
            raise ValueError("vLLM success counter moved backwards")
        finished_requests = {
            reason: self.finished_requests[reason] - before.finished_requests[reason]
            for reason in _FINISH_REASONS
        }
        if any(value < 0 for value in finished_requests.values()):
            raise ValueError("vLLM finish-reason counter moved backwards")
        return VllmMetricsDelta(
            successful_requests=successful_requests,
            finished_requests=finished_requests,
            histograms={
                name: self.histograms[name].delta(before.histograms[name])
                for name in _HISTOGRAMS
            },
        )


@dataclass(frozen=True, slots=True)
class VllmMetricsDelta:
    successful_requests: int
    finished_requests: Mapping[str, int]
    histograms: Mapping[str, VllmHistogramDelta]

    def __post_init__(self) -> None:
        if (
            isinstance(self.successful_requests, bool)
            or not isinstance(self.successful_requests, int)
            or self.successful_requests < 0
            or set(self.finished_requests) != set(_FINISH_REASONS)
            or any(
                isinstance(value, bool) or not isinstance(value, int) or value < 0
                for value in self.finished_requests.values()
            )
            or sum(self.finished_requests.values()) != self.successful_requests
            or set(self.histograms) != set(_HISTOGRAMS)
        ):
            raise ValueError("vLLM metric delta is invalid")

    def public_evidence(self) -> dict[str, object]:
        return {
            "successfulEngineRequests": self.successful_requests,
            "engineFinishReasons": dict(self.finished_requests),
            "endToEndLatency": self.histograms[
                "vllm:e2e_request_latency_seconds"
            ].public_evidence(),
            "inferenceTime": self.histograms[
                "vllm:request_inference_time_seconds"
            ].public_evidence(),
            "queueTime": self.histograms[
                "vllm:request_queue_time_seconds"
            ].public_evidence(),
        }


class VllmRuntimeMetricsClient:
    """Read bounded aggregate metrics from one numeric-loopback vLLM service."""

    def __init__(
        self,
        endpoint: str,
        *,
        timeout_seconds: float = 2,
        connection_factory: Callable[[str, int, float], http.client.HTTPConnection]
        | None = None,
    ) -> None:
        host, port = parse_numeric_loopback_http_endpoint(
            endpoint,
            component="vLLM metrics",
        )
        if timeout_seconds <= 0:
            raise ValueError("vLLM metrics timeout must be positive")
        self._host = host
        self._port = port
        self._timeout_seconds = timeout_seconds
        self._connection_factory = connection_factory or _open_connection

    def snapshot(self) -> VllmMetricsSnapshot:
        connection = self._connection_factory(
            self._host,
            self._port,
            self._timeout_seconds,
        )
        try:
            connection.request("GET", "/metrics")
            response = connection.getresponse()
            content_type = response.getheader("Content-Type")
            if (
                response.status != 200
                or not isinstance(content_type, str)
                or not content_type.lower().startswith("text/plain")
            ):
                raise WorkerExecutionError("vLLM metrics response is invalid")
            body = response.read(_MAX_METRICS_BYTES + 1)
            if len(body) > _MAX_METRICS_BYTES:
                raise WorkerExecutionError("vLLM metrics response exceeds its bound")
        finally:
            connection.close()
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError as error:
            raise WorkerExecutionError("vLLM metrics response is not UTF-8") from error
        return parse_vllm_runtime_metrics(text)

    def wait_for_running_requests(
        self,
        *,
        minimum: int,
        timeout_seconds: float,
    ) -> VllmMetricsSnapshot:
        if (
            isinstance(minimum, bool)
            or not isinstance(minimum, int)
            or minimum < 0
            or timeout_seconds <= 0
        ):
            raise ValueError("vLLM running-request wait is invalid")
        deadline = time.monotonic() + timeout_seconds
        while True:
            snapshot = self.snapshot()
            if snapshot.running_requests >= minimum:
                return snapshot
            if time.monotonic() >= deadline:
                raise TimeoutError("vLLM running-request observation timed out")
            time.sleep(0.02)


def parse_vllm_runtime_metrics(text: str) -> VllmMetricsSnapshot:
    if not isinstance(text, str) or not text:
        raise ValueError("vLLM metrics text is invalid")
    values: dict[str, float] = {}
    finish_reasons = {reason: 0 for reason in _FINISH_REASONS}
    buckets: dict[str, dict[float, int]] = {name: {} for name in _HISTOGRAMS}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _METRIC_LINE.fullmatch(stripped)
        if match is None:
            continue
        identity = match.group("identity")
        name = identity.split("{", 1)[0]
        if name not in _RELEVANT_METRICS:
            continue
        value = float(match.group("value"))
        if not math.isfinite(value) or value < 0:
            raise ValueError("vLLM runtime metric value is invalid")
        histogram_name = _bucket_histogram_name(name)
        if histogram_name is not None:
            boundary = _bucket_boundary(identity)
            bucket_value = _integer_metric(value)
            buckets[histogram_name][boundary] = (
                buckets[histogram_name].get(boundary, 0) + bucket_value
            )
        elif name == "vllm:request_success_total":
            reason = _finished_reason(identity)
            finish_reasons[reason] += _integer_metric(value)
            values[name] = values.get(name, 0.0) + value
        else:
            values[name] = values.get(name, 0.0) + value
    try:
        histograms = {
            name: VllmHistogramSnapshot(
                count=_integer_metric(values[f"{name}_count"]),
                total_seconds=values[f"{name}_sum"],
                cumulative_buckets=tuple(sorted(buckets[name].items())),
            )
            for name in _HISTOGRAMS
        }
        return VllmMetricsSnapshot(
            running_requests=_integer_metric(values["vllm:num_requests_running"]),
            waiting_requests=_integer_metric(values["vllm:num_requests_waiting"]),
            successful_requests=_integer_metric(values["vllm:request_success_total"]),
            finished_requests=finish_reasons,
            histograms=histograms,
        )
    except KeyError as error:
        raise ValueError("vLLM runtime metrics are incomplete") from error


def _bucket_histogram_name(name: str) -> str | None:
    return name.removesuffix("_bucket") if name.endswith("_bucket") else None


def _bucket_boundary(identity: str) -> float:
    match = _LE_LABEL.search(identity)
    if match is None:
        raise ValueError("vLLM histogram bucket omitted its boundary")
    value = match.group("value")
    if value == "+Inf":
        return math.inf
    boundary = float(value)
    if not math.isfinite(boundary) or boundary < 0:
        raise ValueError("vLLM histogram bucket boundary is invalid")
    return boundary


def _finished_reason(identity: str) -> str:
    match = _FINISHED_REASON_LABEL.search(identity)
    if match is None or match.group("value") not in _FINISH_REASONS:
        raise ValueError("vLLM success counter has an invalid finish reason")
    return match.group("value")


def _integer_metric(value: float) -> int:
    if not value.is_integer() or value < 0:
        raise ValueError("vLLM count metric is invalid")
    return int(value)


def _open_connection(
    host: str,
    port: int,
    timeout_seconds: float,
) -> http.client.HTTPConnection:
    return http.client.HTTPConnection(host, port, timeout=timeout_seconds)
