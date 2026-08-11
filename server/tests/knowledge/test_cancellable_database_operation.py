from __future__ import annotations

import threading
import unittest
from unittest.mock import patch

from yap_server.knowledge.cancellable_database_operation import (
    run_cancellable_database_operation,
)
from yap_server.knowledge.knowledge_tool_contract import (
    KnowledgeToolCancellationFailed,
    KnowledgeToolCancelled,
)


class CancellableDatabaseOperationTests(unittest.TestCase):
    def test_rejects_cancellation_before_database_dispatch(self) -> None:
        cancellation = threading.Event()
        cancellation.set()
        called = False

        def operation() -> None:
            nonlocal called
            called = True

        with self.assertRaisesRegex(KnowledgeToolCancelled, "before dispatch"):
            run_cancellable_database_operation(
                _CancellationConnection(), cancellation, operation
            )
        self.assertFalse(called)

    def test_rejects_a_result_completed_after_cancellation(self) -> None:
        cancellation = threading.Event()
        started = threading.Event()
        connection = _CancellationConnection()
        outcome: list[BaseException] = []

        def operation() -> str:
            started.set()
            cancellation.wait()
            return "late-success"

        def invoke() -> None:
            try:
                run_cancellable_database_operation(
                    connection, cancellation, operation
                )
            except BaseException as error:
                outcome.append(error)

        worker = threading.Thread(target=invoke)
        worker.start()
        self.assertTrue(started.wait(1))
        cancellation.set()
        worker.join(2)

        self.assertFalse(worker.is_alive())
        self.assertEqual(len(outcome), 1)
        self.assertIsInstance(outcome[0], KnowledgeToolCancelled)
        self.assertFalse(_cancellation_watchers())

    def test_cancel_failure_closes_connection_and_is_reported(self) -> None:
        cancellation = threading.Event()
        started = threading.Event()
        connection = _CancellationConnection(cancel_error=OSError("cancel failed"))
        outcome: list[BaseException] = []

        def operation() -> None:
            started.set()
            connection.closed.wait()
            raise RuntimeError("database connection closed")

        def invoke() -> None:
            try:
                run_cancellable_database_operation(
                    connection, cancellation, operation
                )
            except BaseException as error:
                outcome.append(error)

        with patch(
            "yap_server.knowledge.cancellable_database_operation."
            "_CLOSE_ACKNOWLEDGEMENT_SECONDS",
            0.01,
        ):
            worker = threading.Thread(target=invoke)
            worker.start()
            self.assertTrue(started.wait(1))
            cancellation.set()
            worker.join(2)

        self.assertFalse(worker.is_alive())
        self.assertTrue(connection.closed.is_set())
        self.assertEqual(len(outcome), 1)
        self.assertIsInstance(outcome[0], KnowledgeToolCancellationFailed)
        self.assertFalse(_cancellation_watchers())

    def test_operation_ignoring_cancel_is_closed_before_return(self) -> None:
        cancellation = threading.Event()
        started = threading.Event()
        connection = _CancellationConnection()
        outcome: list[BaseException] = []

        def operation() -> str:
            started.set()
            connection.closed.wait()
            return "late-success"

        def invoke() -> None:
            try:
                run_cancellable_database_operation(
                    connection, cancellation, operation
                )
            except BaseException as error:
                outcome.append(error)

        with patch(
            "yap_server.knowledge.cancellable_database_operation."
            "_CLOSE_ACKNOWLEDGEMENT_SECONDS",
            0.01,
        ):
            worker = threading.Thread(target=invoke)
            worker.start()
            self.assertTrue(started.wait(1))
            cancellation.set()
            worker.join(2)

        self.assertFalse(worker.is_alive())
        self.assertTrue(connection.closed.is_set())
        self.assertEqual(len(outcome), 1)
        self.assertIsInstance(outcome[0], KnowledgeToolCancelled)
        self.assertFalse(_cancellation_watchers())

    def test_blocked_close_cannot_be_reported_as_completed(self) -> None:
        cancellation = threading.Event()
        operation_started = threading.Event()
        close_started = threading.Event()
        close_release = threading.Event()
        connection = _CancellationConnection(
            close_started=close_started,
            close_release=close_release,
        )
        outcome: list[BaseException] = []

        def operation() -> None:
            operation_started.set()
            connection.closed.wait()

        def invoke() -> None:
            try:
                run_cancellable_database_operation(connection, cancellation, operation)
            except BaseException as error:
                outcome.append(error)

        worker = threading.Thread(target=invoke)
        worker.start()
        self.assertTrue(operation_started.wait(1))
        cancellation.set()
        self.assertTrue(close_started.wait(2))
        self.assertTrue(worker.is_alive())
        close_release.set()
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(len(outcome), 1)
        self.assertIsInstance(outcome[0], KnowledgeToolCancelled)
        self.assertFalse(_cancellation_watchers())


class _CancellationConnection:
    def __init__(
        self,
        *,
        cancel_error: BaseException | None = None,
        close_started: threading.Event | None = None,
        close_release: threading.Event | None = None,
    ) -> None:
        self.cancel_error = cancel_error
        self.closed = threading.Event()
        self.cancel_calls = 0
        self.close_started = close_started
        self.close_release = close_release

    def cancel_safe(self, *, timeout: float) -> None:
        self.cancel_calls += 1
        if timeout != 1.0:
            raise AssertionError("unexpected cancellation timeout")
        if self.cancel_error is not None:
            raise self.cancel_error

    def close(self) -> None:
        if self.close_started is not None:
            self.close_started.set()
        if self.close_release is not None:
            self.close_release.wait()
        self.closed.set()


def _cancellation_watchers() -> list[threading.Thread]:
    return [
        thread
        for thread in threading.enumerate()
        if thread.name == "yap-knowledge-database-cancellation"
    ]


if __name__ == "__main__":
    unittest.main()
