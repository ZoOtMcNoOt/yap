from __future__ import annotations

from contextlib import AbstractContextManager
import unittest

from yap_server.agents.librarian_result_audit import (
    PostgresLibrarianResultAuditor,
    install_librarian_result_audit_schema,
)
from yap_server.auth import AuthenticatedPrincipal


class _Cursor:
    def __init__(self, row: tuple[object, ...] | None = None) -> None:
        self._row = row

    def fetchone(self) -> tuple[object, ...] | None:
        return self._row


class _Transaction(AbstractContextManager[None]):
    def __init__(self, connection: _Connection) -> None:
        self._connection = connection

    def __enter__(self) -> None:
        self._connection.transaction_entries += 1

    def __exit__(self, *unused: object) -> None:
        self._connection.transaction_exits += 1


class _Connection(AbstractContextManager["_Connection"]):
    def __init__(self) -> None:
        self.schema_sql: str | None = None
        self.rows: dict[tuple[object, object], tuple[object, ...]] = {}
        self.executions: list[tuple[str, tuple[object, ...]]] = []
        self.transaction_entries = 0
        self.transaction_exits = 0

    def __enter__(self) -> _Connection:
        return self

    def __exit__(self, *unused: object) -> None:
        return None

    def transaction(self) -> _Transaction:
        return _Transaction(self)

    def execute(
        self,
        statement: str,
        values: tuple[object, ...] = (),
    ) -> _Cursor:
        normalized = " ".join(statement.split())
        self.executions.append((normalized, values))
        if normalized.startswith("CREATE TABLE"):
            self.schema_sql = normalized
            return _Cursor()
        if normalized.startswith("INSERT INTO yap_librarian_result_audit"):
            key = (values[0], values[2])
            if key in self.rows:
                return _Cursor()
            self.rows[key] = values
            return _Cursor((1,))
        if normalized.startswith("SELECT tenant_id"):
            return _Cursor(self.rows.get((values[0], values[1])))
        raise AssertionError(f"unexpected SQL: {normalized}")


def _principal(subject_id: str = "owner-1") -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        tenant_id="tenant-1",
        subject_id=subject_id,
        client_id="librarian-tests",
        scopes=frozenset({"knowledge.read"}),
    )


def _success_values() -> dict[str, object]:
    return {
        "principal": _principal(),
        "request_id": "librarian-request-1",
        "request_sha256": "a" * 64,
        "work_sha256": "b" * 64,
        "evidence_sha256": "c" * 64,
        "generation_sha256": "d" * 64,
        "permission_hash": "e" * 64,
        "authorization_hash": "f" * 64,
        "outcome": "succeeded",
        "reason": None,
        "result_count": 5,
        "duration_milliseconds": 17,
    }


class LibrarianResultAuditTests(unittest.TestCase):
    def test_schema_is_bounded_content_free_and_fixed_to_librarian(self) -> None:
        connection = _Connection()

        install_librarian_result_audit_schema(connection)  # type: ignore[arg-type]

        self.assertEqual(connection.transaction_entries, 1)
        self.assertEqual(connection.transaction_exits, 1)
        sql = connection.schema_sql
        self.assertIsNotNone(sql)
        assert sql is not None
        for contract in (
            "UNIQUE (tenant_id, request_id)",
            "agent_role = 'librarian'",
            "purpose = 'knowledge-read'",
            "route = 'server-io'",
            "scheduling_class = 'interactive'",
            "result_count BETWEEN 1 AND 5",
            "duration_milliseconds BETWEEN 0 AND 300000",
            "'empty-result'",
            "'evidence-unavailable'",
            "'stale-generation'",
            "'unauthorized'",
            "'client-cancelled'",
            "'deadline-exceeded'",
            "'admission-failed'",
            "'capacity-unavailable'",
            "'storage-timeout'",
            "'storage-unavailable'",
        ):
            with self.subTest(contract=contract):
                self.assertIn(contract, sql)
        for forbidden in ("query_body", "evidence_body", "content", "source_text"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, sql)

    def test_success_is_content_free_idempotent_and_exactly_bound(self) -> None:
        connection = _Connection()
        auditor = PostgresLibrarianResultAuditor(lambda: connection)
        values = _success_values()

        auditor.record(**values)  # type: ignore[arg-type]
        auditor.record(**values)  # type: ignore[arg-type]

        self.assertEqual(len(connection.rows), 1)
        stored = next(iter(connection.rows.values()))
        self.assertEqual(
            stored,
            (
                "tenant-1",
                "owner-1",
                "librarian-request-1",
                "a" * 64,
                "b" * 64,
                "c" * 64,
                "d" * 64,
                "e" * 64,
                "f" * 64,
                "librarian",
                "knowledge-read",
                "server-io",
                "interactive",
                "succeeded",
                None,
                5,
                17,
            ),
        )
        insert_sql = connection.executions[0][0]
        for forbidden in ("query_body", "evidence_body", "content", "source_text"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, insert_sql)

    def test_same_tenant_request_with_different_identity_conflicts(self) -> None:
        connection = _Connection()
        auditor = PostgresLibrarianResultAuditor(lambda: connection)
        values = _success_values()
        auditor.record(**values)  # type: ignore[arg-type]

        changed = {**values, "principal": _principal("owner-2")}
        with self.assertRaisesRegex(
            ValueError,
            "librarian result audit identity conflicts",
        ):
            auditor.record(**changed)  # type: ignore[arg-type]

    def test_non_success_outcomes_are_zero_result_and_content_free(self) -> None:
        cases = (
            ("unavailable", "empty-result"),
            ("unavailable", "evidence-unavailable"),
            ("unavailable", "stale-generation"),
            ("unauthorized", "unauthorized"),
            ("cancelled", "client-cancelled"),
            ("cancelled", "deadline-exceeded"),
            ("failed", "admission-failed"),
            ("failed", "capacity-unavailable"),
            ("failed", "storage-timeout"),
            ("failed", "storage-unavailable"),
        )
        for index, (outcome, reason) in enumerate(cases):
            with self.subTest(outcome=outcome, reason=reason):
                connection = _Connection()
                auditor = PostgresLibrarianResultAuditor(lambda: connection)
                auditor.record(
                    principal=_principal(),
                    request_id=f"failed-{index}",
                    request_sha256="a" * 64,
                    work_sha256=None,
                    evidence_sha256=None,
                    generation_sha256=("d" * 64 if reason == "stale-generation" else None),
                    permission_hash=None,
                    authorization_hash=None,
                    outcome=outcome,
                    reason=reason,
                    result_count=0,
                    duration_milliseconds=3,
                )
                stored = next(iter(connection.rows.values()))
                self.assertEqual(stored[4:6], (None, None))
                self.assertEqual(stored[7:9], (None, None))
                self.assertEqual(stored[15], 0)

    def test_invalid_shapes_fail_before_opening_database(self) -> None:
        auditor = PostgresLibrarianResultAuditor(
            lambda: (_ for _ in ()).throw(AssertionError("database opened"))
        )
        base = _success_values()
        invalid = (
            {"request_id": "bad request"},
            {"request_sha256": "A" * 64},
            {"work_sha256": None},
            {"authorization_hash": None},
            {"generation_sha256": None},
            {"reason": "empty-result"},
            {"result_count": 0},
            {"result_count": 6},
            {"result_count": True},
            {"duration_milliseconds": -1},
            {"duration_milliseconds": 300_001},
            {"duration_milliseconds": True},
            {
                "outcome": "unavailable",
                "reason": "storage-unavailable",
                "result_count": 0,
            },
            {
                "outcome": "failed",
                "reason": "storage-unavailable",
                "result_count": 1,
            },
        )
        for changes in invalid:
            with self.subTest(changes=changes), self.assertRaisesRegex(
                ValueError,
                "librarian result audit is invalid",
            ):
                auditor.record(**{**base, **changes})  # type: ignore[arg-type]

    def test_non_success_rejects_partial_evidence_binding(self) -> None:
        auditor = PostgresLibrarianResultAuditor(
            lambda: (_ for _ in ()).throw(AssertionError("database opened"))
        )
        with self.assertRaisesRegex(ValueError, "result audit is invalid"):
            auditor.record(
                principal=_principal(),
                request_id="partial-binding",
                request_sha256="a" * 64,
                work_sha256=None,
                evidence_sha256="c" * 64,
                generation_sha256="d" * 64,
                permission_hash="e" * 64,
                authorization_hash="f" * 64,
                outcome="failed",
                reason="storage-unavailable",
                result_count=0,
                duration_milliseconds=1,
            )


if __name__ == "__main__":
    unittest.main()
