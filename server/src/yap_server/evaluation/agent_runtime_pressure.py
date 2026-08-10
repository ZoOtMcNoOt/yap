from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import json
import threading
import time
from typing import Callable, Mapping, Protocol

from yap_server.knowledge.knowledge_tool_contract import KnowledgeToolCancelled

from .agent_model_acceptance import load_agent_model_acceptance


Request = Callable[[str, threading.Event], str]
DispatchedRequest = Callable[[str, threading.Event, threading.Event], str]
MemoryBytes = Callable[[], int]


class RuntimeActivity(Protocol):
    def begin_cancellation(self, *, timeout_seconds: float) -> object: ...

    def wait_until_running(self, *, timeout_seconds: float) -> None: ...

    def after_cancellation(
        self, token: object, *, timeout_seconds: float
    ) -> tuple[object, Mapping[str, int]]: ...

    def after_recovery(
        self, token: object, *, timeout_seconds: float
    ) -> Mapping[str, int]: ...


@dataclass(frozen=True, slots=True)
class RuntimePressureResult:
    cold_latency_milliseconds: int
    warm_latency_milliseconds: tuple[int, ...]
    concurrency_latency_milliseconds: dict[int, tuple[int, ...]]
    baseline_memory_bytes: int
    peak_memory_bytes: int
    isolation_leak_count: int
    cancelled_request_completion_count: int
    memory_sample_count: int
    cancellation_dispatched: bool
    engine_activity_observed: bool
    engine_idle_after_cancellation: bool
    recovery_succeeded: bool
    cancellation_engine_finish_reasons: Mapping[str, int]
    recovery_engine_finish_reasons: Mapping[str, int]
    isolation_concurrent: bool


def run_agent_runtime_pressure(
    repository_root,
    *,
    request: Request,
    dispatched_request: DispatchedRequest,
    memory_bytes: MemoryBytes,
    runtime_activity: RuntimeActivity,
) -> RuntimePressureResult:
    """Exercise the frozen pressure tracks without trusting server summaries."""

    tracks = load_agent_model_acceptance(repository_root).runtime_tracks
    samples = [_memory(memory_bytes)]
    sampling_stop = threading.Event()
    sampling_failure: list[BaseException] = []

    def sample() -> None:
        try:
            while not sampling_stop.wait(0.02):
                samples.append(_memory(memory_bytes))
        except BaseException as error:
            sampling_failure.append(error)

    sampler = threading.Thread(
        target=sample, name="yap-agent-memory-sampler", daemon=True
    )
    sampler.start()
    try:
        cancel = threading.Event()
        cold = _timed(request, _marker_prompt("COLD-READY"), "COLD-READY", cancel)
        warm = tuple(
            _timed(
                request,
                _marker_prompt(f"WARM-{index}"),
                f"WARM-{index}",
                cancel,
            )
            for index in range(int(tracks["warmRequests"]))
        )
        concurrency: dict[int, tuple[int, ...]] = {}
        for level in tracks["concurrencyLevels"]:
            assert isinstance(level, int)
            barrier = threading.Barrier(level)

            def concurrent_call(index: int) -> int:
                marker = f"C{level}-{index}"
                barrier.wait(timeout=int(tracks["requestTimeoutSeconds"]))
                return _timed(request, _marker_prompt(marker), marker, cancel)

            with ThreadPoolExecutor(max_workers=level) as executor:
                concurrency[level] = tuple(executor.map(concurrent_call, range(level)))
        leaks = _isolation_leaks(
            request,
            repetitions=int(tracks["prefixIsolationRepetitions"]),
            timeout_seconds=int(tracks["requestTimeoutSeconds"]),
        )
        (
            cancelled_completions,
            cancellation_finish_reasons,
            recovery_finish_reasons,
        ) = _cancelled_completions(
            request,
            dispatched_request,
            runtime_activity=runtime_activity,
            timeout_seconds=int(tracks["requestTimeoutSeconds"]),
        )
    finally:
        sampling_stop.set()
        sampler.join(timeout=1)
    if sampler.is_alive() or sampling_failure:
        raise RuntimeError("agent runtime memory sampling lost containment")
    baseline = samples[0]
    peak = max(samples)
    return RuntimePressureResult(
        cold,
        warm,
        concurrency,
        baseline,
        peak,
        leaks,
        cancelled_completions,
        len(samples),
        True,
        True,
        True,
        True,
        cancellation_finish_reasons,
        recovery_finish_reasons,
        True,
    )


def _timed(
    request: Request,
    prompt: str,
    expected: str,
    cancellation: threading.Event,
) -> int:
    started = time.monotonic()
    result = request(prompt, cancellation)
    observed = _answer(result)
    if observed != expected:
        raise ValueError(
            f"agent runtime marker mismatch: expected {expected!r}, got {observed!r}"
        )
    return max(0, round((time.monotonic() - started) * 1_000))


def _memory(memory_bytes: MemoryBytes) -> int:
    value = memory_bytes()
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("agent runtime memory observation is invalid")
    return value


def _isolation_leaks(
    request: Request, *, repetitions: int, timeout_seconds: int
) -> int:
    leaks = 0
    for _ in range(repetitions):
        shared = "Shared governed prefix " * 256
        barrier = threading.Barrier(2)

        def invoke(marker: str) -> str:
            barrier.wait(timeout=timeout_seconds)
            return _answer(
                request(
                    _marker_prompt(marker, prefix=shared),
                    threading.Event(),
                )
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            left = executor.submit(invoke, "ALPHA-7Q9")
            right = executor.submit(invoke, "BRAVO-2M4")
            leaks += int(
                left.result(timeout=timeout_seconds) != "ALPHA-7Q9"
                or right.result(timeout=timeout_seconds) != "BRAVO-2M4"
            )
    return leaks


def _cancelled_completions(
    recovery_request: Request,
    request: DispatchedRequest,
    *,
    runtime_activity: RuntimeActivity,
    timeout_seconds: int,
) -> tuple[int, Mapping[str, int], Mapping[str, int]]:
    metrics_token = runtime_activity.begin_cancellation(timeout_seconds=timeout_seconds)
    cancellation = threading.Event()
    dispatched = threading.Event()
    finished = threading.Event()
    returned = False
    failure: BaseException | None = None

    def invoke() -> None:
        nonlocal failure, returned
        try:
            request(
                "Produce a long response until cancelled.",
                cancellation,
                dispatched,
            )
            returned = True
        except BaseException as error:
            failure = error
        finally:
            finished.set()

    worker = threading.Thread(target=invoke, daemon=True)
    worker.start()
    if not dispatched.wait(timeout_seconds):
        raise TimeoutError("agent cancellation request was not dispatched")
    runtime_activity.wait_until_running(timeout_seconds=timeout_seconds)
    cancellation.set()
    if not finished.wait(timeout_seconds):
        raise TimeoutError("cancelled agent request did not terminate")
    if failure is not None and not isinstance(failure, KnowledgeToolCancelled):
        raise RuntimeError("cancelled agent request failed incorrectly") from failure
    recovery_token, cancellation_finish_reasons = runtime_activity.after_cancellation(
        metrics_token, timeout_seconds=timeout_seconds
    )
    recovery = _answer(
        recovery_request(
            _marker_prompt("CANCEL-RECOVERED"),
            threading.Event(),
        )
    )
    if recovery != "CANCEL-RECOVERED":
        raise RuntimeError("agent runtime did not recover after cancellation")
    recovery_finish_reasons = runtime_activity.after_recovery(
        recovery_token, timeout_seconds=timeout_seconds
    )
    return int(returned), cancellation_finish_reasons, recovery_finish_reasons


def _answer(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("agent runtime returned an invalid response")
    try:
        parsed = json.loads(value)
    except (ValueError, TypeError) as error:
        raise ValueError("agent runtime response is not structured JSON") from error
    if (
        not isinstance(parsed, dict)
        or set(parsed) != {"answer", "citationConceptIds"}
        or not isinstance(parsed.get("answer"), str)
        or parsed.get("citationConceptIds") != []
    ):
        observed = repr(parsed)
        raise ValueError(
            "agent runtime marker response differs from the contract: " + observed[:512]
        )
    return parsed["answer"]


def _marker_prompt(marker: str, *, prefix: str = "") -> str:
    instruction = (
        "Return one JSON object. Set answer to the exact string "
        f"{json.dumps(marker)} with no added punctuation. Set citationConceptIds "
        "to an empty array because no governed sources were supplied."
    )
    return f"{prefix}\n{instruction}" if prefix else instruction


__all__ = ["RuntimePressureResult", "run_agent_runtime_pressure"]
