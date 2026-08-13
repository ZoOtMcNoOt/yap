from __future__ import annotations

from contextlib import AbstractContextManager
import hashlib
import threading
import time
import unittest
from unittest.mock import patch

from psycopg import OperationalError

from yap_server.agents.coordinator import (
    CoordinatorEvidencePack,
    CoordinatorProposalBundle,
    CoordinatorProposalCandidate,
    CoordinatorRequest,
)
from yap_server.agents.coordinator_result_audit import (
    CoordinatorRuntimeAuditIdentity,
    PostgresCoordinatorResultAuditor,
    install_coordinator_result_audit_schema,
)
from yap_server.agents.librarian import LibrarianEvidenceItem
from yap_server.auth import AuthenticatedPrincipal
from yap_server.knowledge.knowledge_proposals import CoordinatorEvidenceChanged
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
        self._rows_before = dict(self._connection.rows)

    def __exit__(self, exception_type, *unused: object) -> None:
        if exception_type is not None:
            self._connection.rows.clear()
            self._connection.rows.update(self._rows_before)
        if exception_type is None and self._connection.commit_error is not None:
            raise self._connection.commit_error


class _Connection(AbstractContextManager["_Connection"]):
    def __init__(
        self,
        rows: dict[tuple[object, object], tuple[object, ...]] | None = None,
        *,
        commit_error: BaseException | None = None,
    ) -> None:
        self.rows = rows if rows is not None else {}
        self.commit_error = commit_error
        self.schema_sql: str | None = None
        self.executions: list[tuple[str, tuple[object, ...]]] = []

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
        if normalized.startswith("INSERT INTO yap_coordinator_result_audit"):
            key = (values[0], values[2])
            if key in self.rows:
                return _Cursor()
            self.rows[key] = values
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
                    stored[15],
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
                )
            )
        raise AssertionError(f"unexpected SQL: {normalized}")


def _principal(subject_id: str = "owner-1") -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        tenant_id="tenant-1",
        subject_id=subject_id,
        client_id="coordinator-tests",
        scopes=frozenset({"knowledge.read"}),
    )


def _runtime_identity() -> CoordinatorRuntimeAuditIdentity:
    return CoordinatorRuntimeAuditIdentity(
        candidate_id="gemma-4-31b-it-nvfp4",
        model="nvidia/Gemma-4-31B-IT-NVFP4",
        model_revision="1" * 40,
        runtime_id="gemma-vllm-26.06",
        profile_sha256="2" * 64,
        candidate_lock_sha256="3" * 64,
    )


def _request() -> CoordinatorRequest:
    return CoordinatorRequest(
        objective="Coordinate the reviewed release proposals.",
        maximum_items=3,
        expected_generation_sha256="4" * 64,
    )


def _candidate(index: int) -> CoordinatorProposalCandidate:
    text = f"Source evidence for proposal {index}."
    return CoordinatorProposalCandidate.create(
        proposal_id=hashlib.sha256(f"proposal-{index}".encode()).hexdigest(),
        curator_request_id=f"curator-request-{index}",
        curator_submission_id=f"curator-submission-{index}",
        curator_request_sha256="5" * 64,
        curator_work_sha256="6" * 64,
        curator_evidence_sha256="7" * 64,
        generation_sha256="4" * 64,
        proposal_type="summary",
        proposed_content=f"Coordinate reviewed proposal {index}.",
        inherited_permission_sha256="8" * 64,
        proposal_permission_hash="9" * 64,
        proposal_authorization_hash="a" * 64,
        citations=(
            LibrarianEvidenceItem(
                concept_id=f"concept-{index}",
                source_revision=f"revision-{index}",
                content_sha256=hashlib.sha256(text.encode()).hexdigest(),
                char_start=0,
                char_end=len(text),
                text=text,
            ),
        ),
    )


def _evidence() -> CoordinatorEvidencePack:
    return CoordinatorEvidencePack.create(
        generation_sha256="4" * 64,
        permission_hash="b" * 64,
        authorization_hash="c" * 64,
        candidates=(_candidate(1), _candidate(2)),
        output_budget_exhausted=False,
    )


def _bundle(evidence: CoordinatorEvidencePack) -> CoordinatorProposalBundle:
    return CoordinatorProposalBundle.create(
        generation_sha256=evidence.generation_sha256,
        evidence_sha256=evidence.evidence_sha256,
        items=(evidence.candidates[1], evidence.candidates[0]),
    )


def _record(
    auditor: PostgresCoordinatorResultAuditor,
    *,
    evidence: CoordinatorEvidencePack | None = None,
    bundle: CoordinatorProposalBundle | None = None,
    status: str = "complete",
    reason: str | None = None,
    duration_milliseconds: int = 12,
) -> None:
    auditor.record(
        principal=_principal(),
        request_id="coordinator-request-1",
        request=_request(),
        provider_generation=7 if evidence is not None else None,
        status=status,
        reason=reason,
        evidence=evidence,
        bundle=bundle,
        duration_milliseconds=duration_milliseconds,
        cancellation=threading.Event(),
        deadline=time.monotonic() + 10,
    )


class CoordinatorResultAuditTests(unittest.TestCase):
    def test_schema_is_content_free_and_role_bound(self) -> None:
        connection = _Connection()
        install_coordinator_result_audit_schema(connection)  # type: ignore[arg-type]

        assert connection.schema_sql is not None
        self.assertIn("agent_role = 'coordinator'", connection.schema_sql)
        self.assertIn("purpose = 'conversation-coordinate'", connection.schema_sql)
        self.assertIn("scheduling_class = 'background-llm'", connection.schema_sql)
        for forbidden in ("objective", "proposed_content", "citation_text"):
            self.assertNotIn(forbidden, connection.schema_sql)

    def test_success_reauthorizes_and_persists_only_exact_hash_identity(self) -> None:
        connection = _Connection()
        evidence = _evidence()
        bundle = _bundle(evidence)
        auditor = PostgresCoordinatorResultAuditor(
            connection.__enter__,
            _runtime_identity(),
        )
        with patch(
            "yap_server.agents.coordinator_result_audit."
            "read_coordinator_evidence_in_transaction",
            return_value=evidence,
        ) as current_read:
            _record(auditor, evidence=evidence, bundle=bundle)

        current_read.assert_called_once()
        stored = auditor.read(
            principal=_principal(),
            request_id="coordinator-request-1",
        )
        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(stored.status, "complete")
        self.assertEqual(stored.bundle_sha256, bundle.bundle_sha256)
        self.assertEqual(stored.citation_sha256, bundle.citation_sha256)
        self.assertEqual(stored.result_count, 2)
        flattened = repr(next(iter(connection.rows.values())))
        self.assertNotIn(_request().objective, flattened)
        self.assertNotIn(bundle.items[0].proposed_content, flattened)
        self.assertIsNone(
            auditor.read(
                principal=_principal("owner-2"),
                request_id="coordinator-request-1",
            )
        )

    def test_exact_replay_succeeds_and_conflicting_identity_fails(self) -> None:
        connection = _Connection()
        evidence = _evidence()
        bundle = _bundle(evidence)
        auditor = PostgresCoordinatorResultAuditor(
            connection.__enter__,
            _runtime_identity(),
        )
        with patch(
            "yap_server.agents.coordinator_result_audit."
            "read_coordinator_evidence_in_transaction",
            return_value=evidence,
        ):
            _record(auditor, evidence=evidence, bundle=bundle)
            _record(auditor, evidence=evidence, bundle=bundle)
            with self.assertRaisesRegex(ValueError, "identity conflicts"):
                _record(
                    auditor,
                    evidence=evidence,
                    bundle=bundle,
                    duration_milliseconds=13,
                )

    def test_success_rejects_forged_bundle_before_database_acquisition(self) -> None:
        evidence = _evidence()
        outside = _candidate(9)
        forged = CoordinatorProposalBundle.create(
            generation_sha256=evidence.generation_sha256,
            evidence_sha256=evidence.evidence_sha256,
            items=(outside,),
        )
        acquisitions = 0

        def connection_factory() -> _Connection:
            nonlocal acquisitions
            acquisitions += 1
            return _Connection()

        auditor = PostgresCoordinatorResultAuditor(
            connection_factory,  # type: ignore[arg-type]
            _runtime_identity(),
        )
        with self.assertRaisesRegex(ValueError, "differs from its evidence"):
            _record(auditor, evidence=evidence, bundle=forged)
        self.assertEqual(acquisitions, 0)

    def test_success_rolls_back_when_current_authority_differs(self) -> None:
        connection = _Connection()
        evidence = _evidence()
        auditor = PostgresCoordinatorResultAuditor(
            connection.__enter__,
            _runtime_identity(),
        )
        with (
            patch(
                "yap_server.agents.coordinator_result_audit."
                "read_coordinator_evidence_in_transaction",
                return_value=CoordinatorEvidencePack.create(
                    generation_sha256="4" * 64,
                    permission_hash="b" * 64,
                    authorization_hash="c" * 64,
                    candidates=(),
                    output_budget_exhausted=False,
                ),
            ),
            self.assertRaises(CoordinatorEvidenceChanged),
        ):
            _record(auditor, evidence=evidence, bundle=_bundle(evidence))
        self.assertEqual(connection.rows, {})

    def test_precommit_cancellation_rolls_back_and_is_typed(self) -> None:
        connection = _Connection()
        auditor = PostgresCoordinatorResultAuditor(
            connection.__enter__,
            _runtime_identity(),
        )
        cancellation = threading.Event()
        cancellation.set()
        with self.assertRaises(KnowledgeToolCancelled):
            auditor.record(
                principal=_principal(),
                request_id="coordinator-request-1",
                request=_request(),
                provider_generation=None,
                status="cancelled",
                reason="client-cancelled",
                evidence=None,
                bundle=None,
                duration_milliseconds=1,
                cancellation=cancellation,
                deadline=time.monotonic() + 10,
            )
        self.assertEqual(connection.rows, {})

    def test_ambiguous_commit_recovers_only_the_exact_row(self) -> None:
        rows: dict[tuple[object, object], tuple[object, ...]] = {}
        connections = [
            _Connection(rows, commit_error=OperationalError("lost commit response")),
            _Connection(rows),
        ]

        def connection_factory() -> _Connection:
            return connections.pop(0)

        auditor = PostgresCoordinatorResultAuditor(
            connection_factory,  # type: ignore[arg-type]
            _runtime_identity(),
        )
        evidence = _evidence()
        with patch(
            "yap_server.agents.coordinator_result_audit."
            "read_coordinator_evidence_in_transaction",
            return_value=evidence,
        ):
            _record(auditor, evidence=evidence, bundle=_bundle(evidence))
        self.assertEqual(len(rows), 1)
        self.assertEqual(connections, [])

    def test_invalid_terminal_shapes_and_connection_window_fail_closed(self) -> None:
        auditor = PostgresCoordinatorResultAuditor(
            _Connection().__enter__,
            _runtime_identity(),
        )
        evidence = _evidence()
        with self.assertRaisesRegex(ValueError, "result audit is invalid"):
            _record(
                auditor,
                evidence=evidence,
                bundle=_bundle(evidence),
                status="failed",
                reason="invalid-output",
            )
        with self.assertRaisesRegex(ValueError, "result audit is invalid"):
            auditor.record(
                principal=_principal(),
                request_id="coordinator-request-1",
                request=_request(),
                provider_generation=None,
                status="evidence-unavailable",
                reason="empty-result",
                evidence=evidence,
                bundle=None,
                duration_milliseconds=1,
                cancellation=threading.Event(),
                deadline=time.monotonic() + 10,
            )
        with self.assertRaises(KnowledgeToolTimedOut):
            auditor.record(
                principal=_principal(),
                request_id="coordinator-request-1",
                request=_request(),
                provider_generation=None,
                status="cancelled",
                reason="deadline-exceeded",
                evidence=None,
                bundle=None,
                duration_milliseconds=1,
                cancellation=threading.Event(),
                deadline=time.monotonic() + 1,
            )


if __name__ == "__main__":
    unittest.main()
