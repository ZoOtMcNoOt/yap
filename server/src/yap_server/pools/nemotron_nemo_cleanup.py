from __future__ import annotations

from collections.abc import Callable
import os
import sys
import threading


NATIVE_RUNTIME_CLEANUP_TIMEOUT_SECONDS = 15.0
_SHUTDOWN_FAILURE_EXIT_CODE = 70


def fail_stop_native_runtime() -> None:
    print(
        "resident Nemotron NeMo shutdown exceeded its safe cleanup boundary; "
        "fail-stopping the service process",
        file=sys.stderr,
    )
    os._exit(_SHUTDOWN_FAILURE_EXIT_CODE)


def close_native_runtime_or_fail_stop(
    close_runtime: Callable[[], None],
    *,
    timeout_seconds: float,
) -> None:
    if timeout_seconds <= 0:
        raise ValueError("shutdown cleanup timeout must be positive")
    completed = threading.Event()
    errors: list[BaseException] = []

    def close_in_background() -> None:
        try:
            close_runtime()
        except BaseException as error:
            errors.append(error)
        finally:
            completed.set()

    try:
        cleanup_thread = threading.Thread(
            target=close_in_background,
            name="yap-nemotron-nemo-cleanup",
            daemon=True,
        )
        cleanup_thread.start()
        cleanup_completed = completed.wait(timeout_seconds)
    except BaseException:
        fail_stop_native_runtime()
        return
    if not cleanup_completed or errors:
        fail_stop_native_runtime()
