from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
import queue
import threading
import time
from typing import Protocol


class NemoStreamCancelled(RuntimeError):
    """One admitted stream was cancelled without affecting its siblings."""


class NemoStreamCapacityExceeded(RuntimeError):
    """The bounded runtime has no admission slot for another stream."""


class NemoStreamProtocolError(RuntimeError):
    """One stream violated the framing contract without poisoning its siblings."""


class NemoStreamRuntimeFenced(RuntimeError):
    """The shared pipeline cannot safely admit more streams until restart."""


class StreamingFrame(Protocol):
    stream_id: int
    is_last: bool


class StreamingStepOutput(Protocol):
    stream_id: int
    final_transcript: str


class CacheAwarePipeline(Protocol):
    def transcribe_step(
        self,
        requests: list[StreamingFrame],
    ) -> Sequence[StreamingStepOutput]: ...


StreamFactory = Callable[[bytes, str, int], Iterator[list[StreamingFrame]]]
ReleaseStream = Callable[[int], None]


@dataclass(frozen=True, slots=True)
class ScheduledTranscript:
    raw_transcript: str
    inference_ms: int
    inference_steps: int
    max_batch_size: int
    queue_ms: int
    total_ms: int


@dataclass(slots=True)
class _StreamTask:
    stream_id: int
    frames: Iterator[list[StreamingFrame]]
    cancelled: Callable[[], bool]
    admitted_at: float
    done: threading.Event = field(default_factory=threading.Event)
    transcript_parts: list[str] = field(default_factory=list)
    inference_ms: float = 0.0
    inference_steps: int = 0
    max_batch_size: int = 0
    started_at: float | None = None
    completed_at: float | None = None
    result: ScheduledTranscript | None = None
    error: BaseException | None = None


class NemoStreamScheduler:
    """Single-owner scheduler for bounded cache-aware NeMo streams.

    All pipeline mutation and GPU dispatch happens on one thread. Callers may
    submit concurrently, but they never touch another stream's decoder state,
    feature buffer, or encoder-cache slot.
    """

    def __init__(
        self,
        *,
        pipeline: CacheAwarePipeline,
        stream_factory: StreamFactory,
        release_stream: ReleaseStream,
        max_streams: int,
        batch_window_seconds: float = 0.002,
        shutdown_timeout_seconds: float = 10.0,
    ) -> None:
        if not 1 <= max_streams <= 64:
            raise ValueError("NeMo stream capacity must be between 1 and 64")
        if not 0 <= batch_window_seconds <= 0.1:
            raise ValueError("NeMo batch window is outside the bounded range")
        if shutdown_timeout_seconds <= 0:
            raise ValueError("NeMo shutdown timeout must be positive")
        self._pipeline = pipeline
        self._stream_factory = stream_factory
        self._release_stream = release_stream
        self._max_streams = max_streams
        self._batch_window_seconds = batch_window_seconds
        self._shutdown_timeout_seconds = shutdown_timeout_seconds
        self._admission = threading.BoundedSemaphore(max_streams)
        self._pending: queue.Queue[_StreamTask] = queue.Queue(maxsize=max_streams)
        self._shutdown = threading.Event()
        self._closed = threading.Event()
        self._close_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._next_stream_id = 1
        self._fatal_error: BaseException | None = None
        self._thread = threading.Thread(
            target=self._run,
            name="yap-nemo-stream-scheduler",
            daemon=True,
        )
        self._thread.start()

    def transcribe(
        self,
        *,
        pcm_bytes: bytes,
        language: str,
        cancelled: Callable[[], bool] | None = None,
    ) -> ScheduledTranscript:
        cancellation = cancelled or (lambda: False)
        if not self._admission.acquire(blocking=False):
            raise NemoStreamCapacityExceeded("NeMo stream admission is full")
        admitted_at = time.monotonic()
        try:
            with self._state_lock:
                self._raise_if_unavailable_locked()
                stream_id = self._next_stream_id
                self._next_stream_id += 1
            if self._cancellation_requested(cancellation):
                raise NemoStreamCancelled("NeMo stream was cancelled before admission")
            try:
                frames = self._stream_factory(pcm_bytes, language, stream_id)
            except Exception as error:
                raise NemoStreamProtocolError(
                    "NeMo stream framing could not be initialized"
                ) from error
            task = _StreamTask(
                stream_id=stream_id,
                frames=frames,
                cancelled=cancellation,
                admitted_at=admitted_at,
            )
            with self._state_lock:
                # Closing and enqueueing share this lock, so a caller cannot
                # submit after the owner thread has decided to exit.
                self._raise_if_unavailable_locked()
                try:
                    self._pending.put_nowait(task)
                except queue.Full as error:
                    raise NemoStreamCapacityExceeded(
                        "NeMo stream admission queue is full"
                    ) from error
            task.done.wait()
            if task.error is not None:
                raise task.error
            if task.result is None:
                raise NemoStreamRuntimeFenced(
                    "NeMo stream completed without a result"
                )
            return task.result
        finally:
            self._admission.release()

    def close(self) -> None:
        with self._close_lock:
            if self._closed.is_set():
                return
            with self._state_lock:
                self._shutdown.set()
            self._thread.join(timeout=self._shutdown_timeout_seconds)
            if self._thread.is_alive():
                raise NemoStreamRuntimeFenced(
                    "NeMo scheduler did not acknowledge shutdown in time"
                )
            self._closed.set()

    def _raise_if_unavailable_locked(self) -> None:
        if self._fatal_error is not None:
            raise NemoStreamRuntimeFenced(
                "NeMo stream runtime is fenced after a pipeline failure"
            ) from self._fatal_error
        if self._shutdown.is_set():
            raise NemoStreamRuntimeFenced("NeMo stream runtime is closed")

    @staticmethod
    def _cancellation_requested(cancelled: Callable[[], bool]) -> bool:
        try:
            return bool(cancelled())
        except BaseException:
            return True

    @staticmethod
    def _fenced_error(message: str, cause: BaseException) -> NemoStreamRuntimeFenced:
        error = NemoStreamRuntimeFenced(message)
        error.__cause__ = cause
        return error

    @staticmethod
    def _protocol_error(message: str, cause: BaseException) -> NemoStreamProtocolError:
        error = NemoStreamProtocolError(message)
        error.__cause__ = cause
        return error

    def _record_fatal_error(self, error: BaseException) -> None:
        with self._state_lock:
            if self._fatal_error is None:
                self._fatal_error = error
            self._shutdown.set()

    def _run(self) -> None:
        active: dict[int, _StreamTask] = {}
        try:
            while active or not self._shutdown.is_set():
                self._admit_tasks(active)
                if not active:
                    continue
                requests: list[StreamingFrame] = []
                dispatched: list[_StreamTask] = []
                for task in tuple(active.values()):
                    if self._shutdown.is_set() or self._is_cancelled(task):
                        self._cancel_task(task, active)
                        continue
                    try:
                        frame_group = next(task.frames)
                    except StopIteration:
                        self._fail_task(
                            task,
                            NemoStreamProtocolError(
                                "NeMo stream ended without a terminal frame"
                            ),
                            active,
                        )
                        continue
                    except BaseException as error:
                        self._fail_task(
                            task,
                            self._protocol_error(
                                "NeMo stream framing failed",
                                error,
                            ),
                            active,
                        )
                        continue
                    if (
                        len(frame_group) != 1
                        or frame_group[0].stream_id != task.stream_id
                    ):
                        self._fail_task(
                            task,
                            NemoStreamProtocolError(
                                "NeMo stream factory returned an invalid frame"
                            ),
                            active,
                        )
                        continue
                    if task.started_at is None:
                        task.started_at = time.monotonic()
                    requests.append(frame_group[0])
                    dispatched.append(task)
                if not requests:
                    continue
                started = time.monotonic()
                outputs = self._pipeline.transcribe_step(requests)
                elapsed_ms = (time.monotonic() - started) * 1_000
                output_by_stream = {output.stream_id: output for output in outputs}
                if len(output_by_stream) != len(dispatched) or set(output_by_stream) != {
                    task.stream_id for task in dispatched
                }:
                    raise NemoStreamRuntimeFenced(
                        "NeMo pipeline returned mismatched stream identities"
                    )
                observed_batch = len(dispatched)
                for task, request in zip(dispatched, requests):
                    task.inference_ms += elapsed_ms
                    task.inference_steps += 1
                    task.max_batch_size = max(task.max_batch_size, observed_batch)
                    output = output_by_stream[task.stream_id]
                    if output.final_transcript:
                        task.transcript_parts.append(output.final_transcript)
                    if self._shutdown.is_set() or self._is_cancelled(task):
                        self._cancel_task(task, active)
                    elif request.is_last:
                        self._complete_task(task, active)
        except BaseException as error:
            self._fence_runtime(error, active)
        finally:
            self._drain_pending()

    def _admit_tasks(self, active: dict[int, _StreamTask]) -> None:
        available = self._max_streams - len(active)
        if available <= 0:
            return
        opened_batch_window = False
        if not active:
            try:
                first = self._pending.get(timeout=0.05)
            except queue.Empty:
                return
            active[first.stream_id] = first
            available -= 1
            opened_batch_window = True
        deadline = time.monotonic() + self._batch_window_seconds
        while available > 0:
            timeout = (
                max(0.0, deadline - time.monotonic())
                if opened_batch_window
                else 0.0
            )
            try:
                task = self._pending.get(timeout=timeout)
            except queue.Empty:
                break
            active[task.stream_id] = task
            available -= 1

    @staticmethod
    def _is_cancelled(task: _StreamTask) -> bool:
        return NemoStreamScheduler._cancellation_requested(task.cancelled)

    def _complete_task(
        self,
        task: _StreamTask,
        active: dict[int, _StreamTask],
    ) -> None:
        try:
            self._release_stream(task.stream_id)
        except BaseException as cleanup_error:
            error = self._fenced_error(
                "NeMo stream cleanup failed; runtime fenced",
                cleanup_error,
            )
            self._record_fatal_error(cleanup_error)
            task.error = error
            task.completed_at = time.monotonic()
            active.pop(task.stream_id, None)
            task.done.set()
            raise error
        task.completed_at = time.monotonic()
        started_at = task.started_at or task.admitted_at
        task.result = ScheduledTranscript(
            raw_transcript="".join(task.transcript_parts),
            inference_ms=round(task.inference_ms),
            inference_steps=task.inference_steps,
            max_batch_size=task.max_batch_size,
            queue_ms=round((started_at - task.admitted_at) * 1_000),
            total_ms=round((task.completed_at - task.admitted_at) * 1_000),
        )
        active.pop(task.stream_id, None)
        task.done.set()

    def _cancel_task(
        self,
        task: _StreamTask,
        active: dict[int, _StreamTask],
    ) -> None:
        self._fail_task(
            task,
            NemoStreamCancelled("NeMo stream was cancelled"),
            active,
        )

    def _fail_task(
        self,
        task: _StreamTask,
        error: BaseException,
        active: dict[int, _StreamTask],
    ) -> None:
        cleanup_error = self._finalize_failed_task(task, error, active)
        if cleanup_error is not None:
            self._record_fatal_error(cleanup_error)
            raise self._fenced_error(
                "NeMo stream cleanup failed; runtime fenced",
                cleanup_error,
            )

    def _finalize_failed_task(
        self,
        task: _StreamTask,
        error: BaseException,
        active: dict[int, _StreamTask],
    ) -> BaseException | None:
        cleanup_error: BaseException | None = None
        try:
            self._release_stream(task.stream_id)
        except BaseException as caught_cleanup_error:
            cleanup_error = caught_cleanup_error
            error = self._fenced_error(
                "NeMo stream cleanup failed; runtime fenced",
                caught_cleanup_error,
            )
        task.error = error
        task.completed_at = time.monotonic()
        active.pop(task.stream_id, None)
        task.done.set()
        return cleanup_error

    def _fence_runtime(
        self,
        error: BaseException,
        active: dict[int, _StreamTask],
    ) -> None:
        self._record_fatal_error(error)
        for task in tuple(active.values()):
            task_error = self._fenced_error(
                "NeMo stream pipeline failed; runtime fenced",
                error,
            )
            cleanup_error = self._finalize_failed_task(task, task_error, active)
            if cleanup_error is not None:
                self._record_fatal_error(cleanup_error)

    def _drain_pending(self) -> None:
        while True:
            try:
                task = self._pending.get_nowait()
            except queue.Empty:
                return
            task.error = NemoStreamRuntimeFenced("NeMo stream runtime stopped")
            task.completed_at = time.monotonic()
            task.done.set()
