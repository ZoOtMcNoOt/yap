from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from yap_server.pools.batch_contract import WorkerContainmentError
from yap_server.pools.cleanup_deadline import run_cleanup_before_deadline


EXECUTOR_SHUTDOWN_TIMEOUT_SECONDS = 15.0


def shutdown_executor_or_raise(
    executor: ThreadPoolExecutor,
    *,
    timeout_seconds: float,
    component: str,
) -> None:
    """Stop admission and prove executor-thread exit before returning."""

    if not component:
        raise ValueError("executor component must be non-empty")
    try:
        executor.shutdown(wait=False, cancel_futures=True)
        run_cleanup_before_deadline(
            lambda: executor.shutdown(wait=True, cancel_futures=True),
            timeout_seconds=timeout_seconds,
            thread_name=f"{component}-executor-cleanup",
        )
    except BaseException as error:
        raise WorkerContainmentError(
            f"{component} executor cleanup could not be verified"
        ) from error
