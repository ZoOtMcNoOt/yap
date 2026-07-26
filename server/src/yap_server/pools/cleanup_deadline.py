from __future__ import annotations

from collections.abc import Callable
from queue import Empty, SimpleQueue
import threading


class CleanupDeadlineExceeded(RuntimeError):
    """Cleanup could not prove completion before its process boundary."""


def run_cleanup_before_deadline(
    cleanup: Callable[[], None],
    *,
    timeout_seconds: float,
    thread_name: str,
) -> None:
    if timeout_seconds <= 0:
        raise ValueError("cleanup timeout must be positive")
    if not thread_name:
        raise ValueError("cleanup thread name must be non-empty")

    completed = threading.Event()
    errors: SimpleQueue[BaseException] = SimpleQueue()

    def run_cleanup() -> None:
        try:
            cleanup()
        except BaseException as error:
            errors.put(error)
        finally:
            completed.set()

    try:
        cleanup_thread = threading.Thread(
            target=run_cleanup,
            name=thread_name,
            daemon=True,
        )
        cleanup_thread.start()
        cleanup_completed = completed.wait(timeout_seconds)
    except BaseException as error:
        raise CleanupDeadlineExceeded(
            "cleanup supervision failed before completion"
        ) from error

    if not cleanup_completed:
        raise CleanupDeadlineExceeded("cleanup exceeded its deadline")
    try:
        error = errors.get_nowait()
    except Empty:
        return
    raise error
