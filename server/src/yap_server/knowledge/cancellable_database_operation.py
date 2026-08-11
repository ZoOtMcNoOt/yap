from __future__ import annotations

import threading
from typing import Callable, TypeVar

from psycopg import Connection

from .knowledge_tool_contract import (
    KnowledgeToolCancellationFailed,
    KnowledgeToolCancelled,
)


ResultT = TypeVar("ResultT")
_CANCEL_ATTEMPT_SECONDS = 1.0
_CLOSE_ACKNOWLEDGEMENT_SECONDS = 1.0


def run_cancellable_database_operation(
    connection: Connection[object],
    cancellation: threading.Event,
    operation: Callable[[], ResultT],
) -> ResultT:
    if cancellation.is_set():
        raise KnowledgeToolCancelled("knowledge operation was cancelled before dispatch")
    completed = threading.Event()
    watcher_failures: list[BaseException] = []

    def cancel_when_requested() -> None:
        try:
            while not completed.wait(0.01):
                if not cancellation.is_set():
                    continue
                try:
                    connection.cancel_safe(timeout=_CANCEL_ATTEMPT_SECONDS)
                except BaseException as error:
                    watcher_failures.append(error)
                if not completed.wait(_CLOSE_ACKNOWLEDGEMENT_SECONDS):
                    try:
                        connection.close()
                    except BaseException as error:
                        watcher_failures.append(error)
                return
        except BaseException as error:
            watcher_failures.append(error)

    watcher = threading.Thread(
        target=cancel_when_requested,
        name="yap-knowledge-database-cancellation",
        daemon=False,
    )
    watcher.start()
    try:
        result = operation()
        if cancellation.is_set():
            raise KnowledgeToolCancelled(
                "knowledge operation completed after cancellation"
            )
        return result
    finally:
        completed.set()
        watcher.join()
        if watcher_failures:
            raise KnowledgeToolCancellationFailed(
                "knowledge database cancellation could not be acknowledged"
            ) from watcher_failures[-1]


__all__ = ["run_cancellable_database_operation"]
