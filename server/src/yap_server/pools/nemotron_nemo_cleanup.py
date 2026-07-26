from __future__ import annotations

from collections.abc import Callable
import os
import sys
from typing import Never

from yap_server.pools.cleanup_deadline import run_cleanup_before_deadline


NATIVE_RUNTIME_CLEANUP_TIMEOUT_SECONDS = 15.0
_SHUTDOWN_FAILURE_EXIT_CODE = 70


def fail_stop_native_runtime() -> Never:
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
    try:
        run_cleanup_before_deadline(
            close_runtime,
            timeout_seconds=timeout_seconds,
            thread_name="yap-nemotron-nemo-cleanup",
        )
    except BaseException:
        fail_stop_native_runtime()
