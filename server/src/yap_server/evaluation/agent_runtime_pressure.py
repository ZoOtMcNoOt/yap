from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import threading
import time
from typing import Callable

from yap_server.knowledge.knowledge_tool_contract import KnowledgeToolCancelled

from .agent_model_acceptance import load_agent_model_acceptance


Request = Callable[[str, threading.Event], str]
MemoryBytes = Callable[[], int]


@dataclass(frozen=True, slots=True)
class RuntimePressureResult:
    cold_latency_milliseconds: int
    warm_latency_milliseconds: tuple[int, ...]
    concurrency_latency_milliseconds: dict[int, tuple[int, ...]]
    peak_memory_bytes: int
    isolation_leak_count: int
    cancelled_request_completion_count: int


def run_agent_runtime_pressure(
    repository_root,
    *,
    request: Request,
    memory_bytes: MemoryBytes,
) -> RuntimePressureResult:
    """Exercise the frozen pressure tracks without trusting server summaries."""

    tracks = load_agent_model_acceptance(repository_root).runtime_tracks
    cancel = threading.Event()
    cold = _timed(request, "Return exactly COLD-READY.", cancel)
    warm = tuple(
        _timed(request, f"Return exactly WARM-{index}.", cancel)
        for index in range(int(tracks["warmRequests"]))
    )
    peak = _memory(memory_bytes)
    concurrency: dict[int, tuple[int, ...]] = {}
    for level in tracks["concurrencyLevels"]:
        assert isinstance(level, int)
        barrier = threading.Barrier(level)

        def concurrent_call(index: int) -> int:
            barrier.wait(timeout=int(tracks["requestTimeoutSeconds"]))
            return _timed(request, f"Return exactly C{level}-{index}.", cancel)

        with ThreadPoolExecutor(max_workers=level) as executor:
            concurrency[level] = tuple(executor.map(concurrent_call, range(level)))
        peak = max(peak, _memory(memory_bytes))
    leaks = _isolation_leaks(
        request,
        repetitions=int(tracks["prefixIsolationRepetitions"]),
    )
    cancelled_completions = _cancelled_completions(
        request,
        timeout_seconds=int(tracks["requestTimeoutSeconds"]),
    )
    return RuntimePressureResult(
        cold, warm, concurrency, peak, leaks, cancelled_completions
    )


def _timed(request: Request, prompt: str, cancellation: threading.Event) -> int:
    started = time.monotonic()
    result = request(prompt, cancellation)
    if not isinstance(result, str) or not result:
        raise ValueError("agent runtime returned an invalid response")
    return max(0, round((time.monotonic() - started) * 1_000))


def _memory(memory_bytes: MemoryBytes) -> int:
    value = memory_bytes()
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("agent runtime memory observation is invalid")
    return value


def _isolation_leaks(request: Request, *, repetitions: int) -> int:
    leaks = 0
    for _ in range(repetitions):
        left = request(
            "Private marker ALPHA-7Q9. Return only ALPHA-7Q9.", threading.Event()
        )
        right = request(
            "Private marker BRAVO-2M4. Return only BRAVO-2M4.", threading.Event()
        )
        leaks += int("BRAVO-2M4" in left or "ALPHA-7Q9" in right)
    return leaks


def _cancelled_completions(request: Request, *, timeout_seconds: int) -> int:
    cancellation = threading.Event()
    entered = threading.Event()
    finished = threading.Event()
    returned = False
    failure: BaseException | None = None

    def invoke() -> None:
        nonlocal failure, returned
        try:
            entered.set()
            request("Produce a long response until cancelled.", cancellation)
            returned = True
        except BaseException as error:
            failure = error
        finally:
            finished.set()

    worker = threading.Thread(target=invoke, daemon=True)
    worker.start()
    if not entered.wait(timeout_seconds):
        raise TimeoutError("agent cancellation request did not start")
    cancellation.set()
    if not finished.wait(timeout_seconds):
        raise TimeoutError("cancelled agent request did not terminate")
    if failure is not None and not isinstance(failure, KnowledgeToolCancelled):
        raise RuntimeError("cancelled agent request failed incorrectly") from failure
    return int(returned)


__all__ = ["RuntimePressureResult", "run_agent_runtime_pressure"]
