from __future__ import annotations

from contextlib import AbstractContextManager
import hashlib
import threading
import time
import unittest
from unittest.mock import patch

from psycopg import OperationalError

from yap_server.agents.analyst import (
    AnalystAnswer,
    AnalystRequest,
    analyst_citation_sha256,
)
from yap_server.agents.analyst_result_audit import (
    AnalystRuntimeAuditIdentity,
    PostgresAnalystResultAuditor,
    install_analyst_result_audit_schema,
)
from yap_server.agents.librarian import (
    LibrarianEvidenceItem,
    LibrarianEvidencePack,
    LibrarianRequest,
    librarian_request_sha256,
    librarian_work_sha256,
)
from yap_server.auth import AuthenticatedPrincipal
from yap_server.knowledge.knowledge_tool_contract import (
    KnowledgeToolCancelled,
    KnowledgeToolTimedOut,
)


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
        self._rows_before = dict(self._connection.rows)

    def __exit__(self, exception_type, *unused: object) -> None:
        self._connection.transaction_exits += 1
        if exception_type is not None:
            self._connection.rows = self._rows_before
        elif self._connection.cancel_after_commit is not None:
            self._connection.cancel_after_commit.set()
            time.sleep(0.02)
        if exception_type is None and self._connection.commit_error is not None:
            raise self._connection.commit_error


class _Connection(AbstractContextManager["_Connection"]):
    def __init__(
        self,
        *,
        cancel_after_insert: threading.Event | None = None,
        cancel_after_commit: threading.Event | None = None,
        commit_error: BaseException | None = None,
    ) -> None:
        self.schema_sql: str | None = None
        self.rows: dict[tuple[object, object], tuple[object, ...]] = {}
        self.librarian_rows: dict[tuple[object, object], tuple[object, ...]] = {}
        self.executions: list[tuple[str, tuple[object, ...]]] = []
        self.transaction_entries = 0
        self.transaction_exits = 0
        self.cancel_after_insert = cancel_after_insert
        self.cancel_after_commit = cancel_after_commit
        self.commit_error = commit_error

    def __enter__(self) -> _Connection:
        return self

    def __exit__(self, *unused: object) -> None:
        return None

    def transaction(self) -> _Transaction:
        return _Transaction(self)

    def cancel_safe(self, *, timeout: float) -> None:
        del timeout

    def close(self) -> None:
        return None

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
        if normalized.startswith("SELECT set_config"):
            return _Cursor((values[0],))
        if normalized.startswith("SELECT subject_id"):
            return _Cursor(self.librarian_rows.get((values[0], values[1])))
        if normalized.startswith("INSERT INTO yap_analyst_result_audit"):
            key = (values[0], values[2])
            if key in self.rows:
                return _Cursor()
            self.rows[key] = values
            if self.cancel_after_insert is not None:
                self.cancel_after_insert.set()
                time.sleep(0.02)
            return _Cursor((1,))
        if normalized.startswith("SELECT tenant_id"):
            return _Cursor(self.rows.get((values[0], values[1])))
        if normalized.startswith("SELECT request_id"):
            stored = self.rows.get((values[0], values[2]))
            if stored is None or stored[1] != values[1]:
                return _Cursor()
            return _Cursor(
                (
                    stored[2],
                    stored[3],
                    stored[4],
                    stored[5],
                    stored[6],
                    stored[7],
                    stored[8],
                    stored[9],
                    stored[10],
                    stored[11],
                    stored[16],
                    stored[17],
                    stored[18],
                    stored[19],
                    stored[20],
                    stored[21],
                    stored[22],
                    stored[23],
                    stored[24],
                    stored[25],
                    stored[26],
                )
            )
        raise AssertionError(f"unexpected SQL: {normalized}")


def _principal(subject_id: str = "owner-1") -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        tenant_id="tenant-1",
        subject_id=subject_id,
        client_id="analyst-tests",
        scopes=frozenset({"knowledge.read"}),
    )


def _runtime_identity() -> AnalystRuntimeAuditIdentity:
    return AnalystRuntimeAuditIdentity(
        candidate_id="gemma-4-31b-it-nvfp4",
        model="nvidia/Gemma-4-31B-IT-NVFP4",
        model_revision="1" * 40,
        runtime_id="gemma-vllm-26.06",
        profile_sha256="2" * 64,
        candidate_lock_sha256="3" * 64,
    )


def _request() -> AnalystRequest:
    return AnalystRequest(
        question="What does the source establish?",
        maximum_results=5,
        expected_generation_sha256="4" * 64,
    )


def _evidence() -> LibrarianEvidencePack:
    text = "The source establishes exact bounded evidence."
    return LibrarianEvidencePack.create(
        generation_sha256="4" * 64,
        permission_hash="5" * 64,
        authorization_hash="6" * 64,
        items=(
            LibrarianEvidenceItem(
                concept_id="concept-1",
                source_revision="revision-1",
                content_sha256="7" * 64,
                char_start=0,
                char_end=len(text),
                text=text,
            ),
        ),
        output_budget_exhausted=False,
    )


def _answer(evidence: LibrarianEvidencePack) -> AnalystAnswer:
    citations = evidence.items
    answer = "\n\n".join(item.text for item in citations)
    return AnalystAnswer(
        answer=answer,
        citations=citations,
        answer_sha256=hashlib.sha256(answer.encode("utf-8")).hexdigest(),
        citation_sha256=analyst_citation_sha256(citations),
        evidence_sha256=evidence.evidence_sha256,
    )


def _install_librarian_success(
    connection: _Connection,
    *,
    principal: AuthenticatedPrincipal,
    librarian_request_id: str,
    request: AnalystRequest,
    evidence: LibrarianEvidencePack,
) -> None:
    librarian_request = LibrarianRequest(
        search_text=request.question,
        maximum_results=request.maximum_results,
        expected_generation_sha256=request.expected_generation_sha256,
    )
    connection.librarian_rows[(principal.tenant_id, librarian_request_id)] = (
        principal.subject_id,
        librarian_request_sha256(librarian_request),
        librarian_work_sha256(librarian_request, evidence),
        evidence.evidence_sha256,
        evidence.generation_sha256,
        evidence.permission_hash,
        evidence.authorization_hash,
        "librarian",
        "knowledge-read",
        "server-io",
        "interactive",
        "succeeded",
        None,
        len(evidence.items),
    )


def _success_values(connection: _Connection) -> dict[str, object]:
    principal = _principal()
    request = _request()
    evidence = _evidence()
    librarian_request_id = "librarian-request-1"
    _install_librarian_success(
        connection,
        principal=principal,
        librarian_request_id=librarian_request_id,
        request=request,
        evidence=evidence,
    )
    return {
        "principal": principal,
        "request_id": "analyst-request-1",
        "librarian_request_id": librarian_request_id,
        "request": request,
        "provider_generation": 11,
        "status": "complete",
        "reason": None,
        "evidence": evidence,
        "answer": _answer(evidence),
        "duration_milliseconds": 17,
        "cancellation": threading.Event(),
        "deadline": time.monotonic() + 5,
    }


class AnalystResultAuditTests(unittest.TestCase):
    def test_schema_is_bounded_content_free_and_fixed_to_complex_analyst(self) -> None:
        connection = _Connection()

        install_analyst_result_audit_schema(connection)  # type: ignore[arg-type]

        self.assertEqual(connection.transaction_entries, 1)
        self.assertEqual(connection.transaction_exits, 1)
        sql = connection.schema_sql
        self.assertIsNotNone(sql)
        assert sql is not None
        for contract in (
            "UNIQUE (tenant_id, request_id)",
            "agent_role = 'analyst'",
            "purpose = 'knowledge-answer'",
            "route = 'complex-orchestration'",
            "scheduling_class = 'interactive'",
            "provider_generation IS NOT NULL",
            "librarian_request_id IS NOT NULL",
            "answer_sha256 IS NOT NULL",
            "citation_sha256 IS NOT NULL",
            "duration_milliseconds BETWEEN 0 AND 300000",
            "'model-evidence-unavailable'",
            "'invalid-output'",
            "'provider-unavailable'",
            "reason NOT IN ( 'invalid-output', 'runtime-unavailable', 'model-evidence-unavailable' )",
        ):
            with self.subTest(contract=contract):
                self.assertIn(contract, sql)
        for forbidden in (
            "question_body",
            "evidence_body",
            "answer_body",
            "citation_body",
            "source_text",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, sql)

    def test_success_reauthorizes_and_requires_exact_librarian_lineage(self) -> None:
        connection = _Connection()
        auditor = PostgresAnalystResultAuditor(
            connection.__enter__, _runtime_identity()
        )
        values = _success_values(connection)

        with patch(
            "yap_server.agents.analyst_result_audit.read_analyst_evidence_in_transaction",
            return_value=values["evidence"],
        ) as read_current:
            auditor.record(**values)  # type: ignore[arg-type]
            auditor.record(**values)  # type: ignore[arg-type]

        self.assertEqual(len(connection.rows), 1)
        self.assertEqual(read_current.call_count, 2)
        read_current.assert_called_with(
            connection,
            values["request"],
            principal=values["principal"],
        )
        stored = next(iter(connection.rows.values()))
        self.assertEqual(
            stored[0:4],
            (
                "tenant-1",
                "owner-1",
                "analyst-request-1",
                "librarian-request-1",
            ),
        )
        answer = values["answer"]
        assert isinstance(answer, AnalystAnswer)
        self.assertEqual(
            stored[7:9],
            (answer.answer_sha256, answer.citation_sha256),
        )
        self.assertEqual(
            stored[12:17],
            (
                "analyst",
                "knowledge-answer",
                "complex-orchestration",
                "interactive",
                11,
            ),
        )
        self.assertEqual(stored[23:27], ("succeeded", None, 1, 17))

    def test_success_fails_closed_on_missing_lineage_or_changed_current_pack(
        self,
    ) -> None:
        connection = _Connection()
        auditor = PostgresAnalystResultAuditor(
            connection.__enter__, _runtime_identity()
        )
        values = _success_values(connection)
        connection.librarian_rows.clear()
        with self.assertRaisesRegex(ValueError, "Librarian success lineage"):
            auditor.record(**values)  # type: ignore[arg-type]
        self.assertEqual(connection.rows, {})

        _success_values(connection)
        key = ("tenant-1", "librarian-request-1")
        lineage = connection.librarian_rows[key]
        connection.librarian_rows[key] = (*lineage[:7], "curator", *lineage[8:])
        with self.assertRaisesRegex(ValueError, "Librarian success lineage"):
            auditor.record(**values)  # type: ignore[arg-type]
        self.assertEqual(connection.rows, {})

        _success_values(connection)
        changed = LibrarianEvidencePack.create(
            generation_sha256="4" * 64,
            permission_hash="a" * 64,
            authorization_hash="b" * 64,
            items=_evidence().items,
            output_budget_exhausted=False,
        )
        with (
            patch(
                "yap_server.agents.analyst_result_audit.read_analyst_evidence_in_transaction",
                return_value=changed,
            ),
            self.assertRaisesRegex(ValueError, "evidence changed"),
        ):
            auditor.record(**values)  # type: ignore[arg-type]
        self.assertEqual(connection.rows, {})

    def test_exact_duplicate_is_accepted_and_changed_identity_conflicts(self) -> None:
        connection = _Connection()
        auditor = PostgresAnalystResultAuditor(
            connection.__enter__, _runtime_identity()
        )
        values = _success_values(connection)
        with patch(
            "yap_server.agents.analyst_result_audit.read_analyst_evidence_in_transaction",
            return_value=values["evidence"],
        ):
            auditor.record(**values)  # type: ignore[arg-type]
            with self.assertRaisesRegex(ValueError, "identity conflicts"):
                auditor.record(
                    **{**values, "duration_milliseconds": 18}  # type: ignore[arg-type]
                )

    def test_read_is_subject_scoped_and_returns_only_content_free_identity(
        self,
    ) -> None:
        connection = _Connection()
        auditor = PostgresAnalystResultAuditor(
            connection.__enter__, _runtime_identity()
        )
        values = _success_values(connection)
        with patch(
            "yap_server.agents.analyst_result_audit.read_analyst_evidence_in_transaction",
            return_value=values["evidence"],
        ):
            auditor.record(**values)  # type: ignore[arg-type]

        stored = auditor.read(principal=_principal(), request_id="analyst-request-1")
        hidden = auditor.read(
            principal=_principal("owner-2"),
            request_id="analyst-request-1",
        )

        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(stored.status, "complete")
        answer = values["answer"]
        assert isinstance(answer, AnalystAnswer)
        self.assertEqual(stored.answer_sha256, answer.answer_sha256)
        self.assertEqual(stored.citation_sha256, answer.citation_sha256)
        self.assertEqual(stored.candidate_id, "gemma-4-31b-it-nvfp4")
        self.assertEqual(stored.model_revision, "1" * 40)
        self.assertEqual(stored.profile_sha256, "2" * 64)
        self.assertEqual(stored.duration_milliseconds, 17)
        self.assertIsNone(hidden)
        self.assertFalse(hasattr(stored, "answer"))
        self.assertFalse(hasattr(stored, "evidence"))

    def test_non_success_vocabulary_is_zero_result_and_answer_free(self) -> None:
        cases = (
            ("evidence-unavailable", "empty-result"),
            ("evidence-unavailable", "evidence-unavailable"),
            ("evidence-unavailable", "stale-generation"),
            ("evidence-unavailable", "incomplete-evidence"),
            ("evidence-unavailable", "model-evidence-unavailable"),
            ("cancelled", "client-cancelled"),
            ("cancelled", "deadline-exceeded"),
            ("failed", "unauthorized"),
            ("failed", "admission-failed"),
            ("failed", "capacity-unavailable"),
            ("failed", "invalid-output"),
            ("failed", "provider-unavailable"),
            ("failed", "runtime-unavailable"),
            ("failed", "storage-timeout"),
            ("failed", "storage-unavailable"),
        )
        for index, (status, reason) in enumerate(cases):
            with self.subTest(status=status, reason=reason):
                connection = _Connection()
                auditor = PostgresAnalystResultAuditor(
                    connection.__enter__,
                    _runtime_identity(),
                )
                evidence = None
                librarian_request_id = None
                provider_generation = None
                if reason in {
                    "invalid-output",
                    "runtime-unavailable",
                    "model-evidence-unavailable",
                }:
                    request = _request()
                    evidence = _evidence()
                    librarian_request_id = "librarian-request-1"
                    provider_generation = 11
                    _install_librarian_success(
                        connection,
                        principal=_principal(),
                        librarian_request_id=librarian_request_id,
                        request=request,
                        evidence=evidence,
                    )
                else:
                    request = _request()
                auditor.record(
                    principal=_principal(),
                    request_id=f"terminal-{index}",
                    librarian_request_id=librarian_request_id,
                    request=request,
                    provider_generation=provider_generation,
                    status=status,
                    reason=reason,
                    evidence=evidence,
                    answer=None,
                    duration_milliseconds=3,
                    cancellation=threading.Event(),
                    deadline=time.monotonic() + 5,
                )
                stored = next(iter(connection.rows.values()))
                self.assertIsNone(stored[7])
                self.assertIsNone(stored[8])
                self.assertEqual(stored[25], 0)

    def test_deadline_and_precommit_cancellation_leave_no_terminal_row(self) -> None:
        connection = _Connection()
        auditor = PostgresAnalystResultAuditor(
            connection.__enter__, _runtime_identity()
        )
        values = _success_values(connection)
        with self.assertRaises(KnowledgeToolTimedOut):
            auditor.record(**{**values, "deadline": time.monotonic() - 1})

        cancellation = threading.Event()
        connection = _Connection(cancel_after_insert=cancellation)
        auditor = PostgresAnalystResultAuditor(
            connection.__enter__, _runtime_identity()
        )
        values = _success_values(connection)
        with (
            patch(
                "yap_server.agents.analyst_result_audit.read_analyst_evidence_in_transaction",
                return_value=values["evidence"],
            ),
            self.assertRaises(KnowledgeToolCancelled),
        ):
            auditor.record(
                **{
                    **values,
                    "cancellation": cancellation,
                    "deadline": time.monotonic() + 5,
                }
            )
        self.assertEqual(connection.rows, {})

    def test_commit_ambiguity_recovers_only_the_exact_terminal_row(self) -> None:
        connection = _Connection(
            commit_error=OperationalError("commit response was lost")
        )
        auditor = PostgresAnalystResultAuditor(
            connection.__enter__, _runtime_identity()
        )
        values = _success_values(connection)

        with patch(
            "yap_server.agents.analyst_result_audit.read_analyst_evidence_in_transaction",
            return_value=values["evidence"],
        ):
            auditor.record(**values)  # type: ignore[arg-type]

        self.assertEqual(len(connection.rows), 1)

    def test_cancellation_after_commit_keeps_the_linearized_terminal_row(self) -> None:
        cancellation = threading.Event()
        connection = _Connection(cancel_after_commit=cancellation)
        auditor = PostgresAnalystResultAuditor(
            connection.__enter__, _runtime_identity()
        )
        values = _success_values(connection)

        with patch(
            "yap_server.agents.analyst_result_audit.read_analyst_evidence_in_transaction",
            return_value=values["evidence"],
        ):
            auditor.record(
                **{
                    **values,
                    "cancellation": cancellation,
                    "deadline": time.monotonic() + 5,
                }
            )

        self.assertTrue(cancellation.is_set())
        self.assertEqual(len(connection.rows), 1)

    def test_recovery_read_is_bound_to_the_same_absolute_deadline(self) -> None:
        connection = _Connection()
        auditor = PostgresAnalystResultAuditor(
            connection.__enter__, _runtime_identity()
        )
        values = _success_values(connection)
        with patch(
            "yap_server.agents.analyst_result_audit.read_analyst_evidence_in_transaction",
            return_value=values["evidence"],
        ):
            auditor.record(**values)  # type: ignore[arg-type]
        stored = next(iter(connection.rows.values()))
        connection.executions.clear()

        recovered = auditor._recover_exact(  # noqa: SLF001
            stored,
            values["principal"],  # type: ignore[arg-type]
            values["request_id"],  # type: ignore[arg-type]
            deadline=time.monotonic() + 5,
        )

        self.assertTrue(recovered)
        timeout_statements = [
            statement
            for statement, _ in connection.executions
            if statement.startswith("SELECT set_config")
        ]
        self.assertEqual(len(timeout_statements), 2)

    def test_invalid_shapes_fail_before_database_acquisition(self) -> None:
        auditor = PostgresAnalystResultAuditor(
            lambda: (_ for _ in ()).throw(AssertionError("database opened")),
            _runtime_identity(),
        )
        connection = _Connection()
        base = _success_values(connection)
        invalid = (
            {"request_id": "bad request"},
            {"librarian_request_id": None},
            {"provider_generation": 0},
            {"provider_generation": True},
            {"status": "complete", "reason": "invalid-output"},
            {"status": "failed", "reason": "not-a-reason", "answer": None},
            {"status": "failed", "reason": "invalid-output"},
            {
                "status": "failed",
                "reason": "invalid-output",
                "librarian_request_id": None,
                "provider_generation": None,
                "evidence": None,
                "answer": None,
            },
            {"duration_milliseconds": -1},
            {"duration_milliseconds": 300_001},
            {"duration_milliseconds": True},
        )
        for changes in invalid:
            with (
                self.subTest(changes=changes),
                self.assertRaisesRegex(
                    ValueError,
                    "analyst result audit is invalid",
                ),
            ):
                auditor.record(**{**base, **changes})  # type: ignore[arg-type]

    def test_success_rejects_citations_outside_the_bound_evidence(self) -> None:
        connection = _Connection()
        values = _success_values(connection)
        evidence = values["evidence"]
        assert isinstance(evidence, LibrarianEvidencePack)
        text = "This valid item was never present in the bound evidence pack."
        foreign = LibrarianEvidenceItem(
            concept_id="foreign-concept",
            source_revision="foreign-revision",
            content_sha256="a" * 64,
            char_start=0,
            char_end=len(text),
            text=text,
        )
        forged_answer = AnalystAnswer(
            answer=text,
            citations=(foreign,),
            answer_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            citation_sha256=analyst_citation_sha256((foreign,)),
            evidence_sha256=evidence.evidence_sha256,
        )
        auditor = PostgresAnalystResultAuditor(
            lambda: (_ for _ in ()).throw(AssertionError("database opened")),
            _runtime_identity(),
        )

        with self.assertRaisesRegex(ValueError, "answer differs from its evidence"):
            auditor.record(**{**values, "answer": forged_answer})  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
