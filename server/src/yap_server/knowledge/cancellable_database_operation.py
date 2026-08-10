from __future__ import annotations

import threading
from typing import Callable, TypeVar

from psycopg import Connection


ResultT = TypeVar("ResultT")


def run_cancellable_database_operation(
    connection: Connection[object],
    cancellation: threading.Event,
    operation: Callable[[], ResultT],
) -> ResultT:
    completed = threading.Event()

    def cancel_when_requested() -> None:
        while not completed.wait(0.01):
            if cancellation.is_set():
                connection.cancel_safe(timeout=1.0)
                return

    watcher = threading.Thread(target=cancel_when_requested, daemon=True)
    watcher.start()
    try:
        return operation()
    finally:
        completed.set()
        watcher.join(timeout=1.0)


__all__ = ["run_cancellable_database_operation"]
