from __future__ import annotations

from contextlib import AbstractContextManager
import threading
import time
import unittest
from unittest.mock import patch

from yap_server.agents.auditor import (
    AuditorEvidenceChanged,
    AuditorEvidencePack,
    AuditorFinding,
    AuditorReport,
    AuditorRequest,
)
from yap_server.agents.auditor_result_audit import (
    AuditorRuntimeAuditIdentity,
    PostgresAuditorResultAuditor,
    install_auditor_result_audit_schema,
)
from yap_server.agents.librarian import LibrarianEvidenceItem
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
        self._before = dict(self._connection.rows)

    def __exit__(self, exception_type, *unused: object) -> None:
        if exception_type is not None:
            self._connection.rows.clear()
            self._connection.rows.update(self._before)


class _Connection(AbstractContextManager["_Connection"]):
    def __init__(
        self,
        rows: dict[tuple[object, object], tuple[object, ...]] | None = None,
    ) -> None:
        self.rows = rows if rows is not None else {}
        self.schema_sql: str | None = None

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
        if normalized.startswith("CREATE TABLE"):
            self.schema_sql = normalized
            return _Cursor()
        if normalized.startswith("SELECT set_config"):
            return _Cursor((values[0],))
        if normalized.startswith("INSERT INTO yap_auditor_result_audit"):
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
        client_id="auditor-tests",
        scopes=frozenset({"knowledge.read"}),
    )


def _runtime_identity() -> AuditorRuntimeAuditIdentity:
    return AuditorRuntimeAuditIdentity(
        candidate_id="gemma-4-31b-it-nvfp4",
        model="nvidia/Gemma-4-31B-IT-NVFP4",
        model_revision="1" * 40,
        runtime_id="gemma-vllm-26.06",
        profile_sha256="2" * 64,
        candidate_lock_sha256="3" * 64,
    )


def _request() -> AuditorRequest:
    return AuditorRequest("release limit conflict", 3, "4" * 64)


def _item(index: int) -> LibrarianEvidenceItem:
    text = f"Reviewed statement {index}."
    return LibrarianEvidenceItem(
        concept_id=f"concept-{index}",
        source_revision="revision-1",
        content_sha256=f"{index + 1:064x}",
        char_start=0,
        char_end=len(text),
        text=text,
    )


def _evidence() -> AuditorEvidencePack:
    return AuditorEvidencePack.create(
        generation_sha256="4" * 64,
        source_admission_sha256="5" * 64,
        permission_hash="6" * 64,
        authorization_hash="7" * 64,
        items=(_item(0), _item(1), _item(2)),
        output_budget_exhausted=False,
    )


def _report(evidence: AuditorEvidencePack) -> AuditorReport:
    return AuditorReport.create(
        generation_sha256=evidence.generation_sha256,
        source_admission_sha256=evidence.source_admission_sha256,
        evidence_sha256=evidence.evidence_sha256,
        findings=(AuditorFinding.create((evidence.items[0], evidence.items[1])),),
    )


def _record(
    auditor: PostgresAuditorResultAuditor,
    *,
    status: str = "complete",
    reason: str | None = None,
    evidence: AuditorEvidencePack | None = None,
    report: AuditorReport | None = None,
) -> None:
    auditor.record(
        principal=_principal(),
        request_id="auditor-request-1",
        request=_request(),
        provider_generation=(9 if evidence is not None else None),
        status=status,
        reason=reason,
        evidence=evidence,
        report=report,
        duration_milliseconds=120,
        cancellation=threading.Event(),
        deadline=time.monotonic() + 10.0,
    )


class AuditorResultAuditTests(unittest.TestCase):
    def test_schema_is_content_free_and_fixes_idle_only_identity(self) -> None:
        connection = _Connection()
        install_auditor_result_audit_schema(connection)
        assert connection.schema_sql is not None
        self.assertIn("purpose = 'knowledge-audit'", connection.schema_sql)
        self.assertIn("scheduling_class = 'idle-only'", connection.schema_sql)
        self.assertIn("source_admission_sha256", connection.schema_sql)
        for forbidden in ("focus text", "evidence text", "source_path", "prompt"):
            self.assertNotIn(forbidden, connection.schema_sql.lower())

    def test_success_is_exact_idempotent_and_readable_without_content(self) -> None:
        rows: dict[tuple[object, object], tuple[object, ...]] = {}
        auditor = PostgresAuditorResultAuditor(
            lambda: _Connection(rows), _runtime_identity()
        )
        evidence = _evidence()
        report = _report(evidence)
        with patch(
            "yap_server.agents.auditor_result_audit.read_auditor_evidence_in_transaction",
            return_value=evidence,
        ):
            _record(auditor, evidence=evidence, report=report)
            _record(auditor, evidence=evidence, report=report)
        stored = auditor.read(principal=_principal(), request_id="auditor-request-1")
        assert stored is not None
        self.assertEqual(stored.report_sha256, report.report_sha256)
        self.assertEqual(stored.source_admission_sha256, "5" * 64)
        self.assertEqual(stored.status, "complete")
        self.assertEqual(stored.result_count, 1)
        flattened = repr(rows)
        self.assertNotIn(_request().focus, flattened)
        self.assertNotIn(evidence.items[0].text, flattened)

    def test_conflict_and_cross_subject_read_fail_closed(self) -> None:
        rows: dict[tuple[object, object], tuple[object, ...]] = {}
        auditor = PostgresAuditorResultAuditor(
            lambda: _Connection(rows), _runtime_identity()
        )
        _record(auditor, status="evidence-unavailable", reason="empty-result")
        with self.assertRaises(ValueError):
            _record(auditor, status="failed", reason="admission-failed")
        self.assertIsNone(
            auditor.read(
                principal=_principal("owner-2"), request_id="auditor-request-1"
            )
        )

    def test_success_rejects_forged_report_before_database_acquisition(self) -> None:
        evidence = _evidence()
        forged = object()

        def fail_factory() -> _Connection:
            raise AssertionError("database must not be acquired")

        auditor = PostgresAuditorResultAuditor(fail_factory, _runtime_identity())
        with self.assertRaises(ValueError):
            _record(auditor, evidence=evidence, report=forged)  # type: ignore[arg-type]

    def test_success_reauthorizes_exact_current_evidence_in_transaction(self) -> None:
        evidence = _evidence()
        auditor = PostgresAuditorResultAuditor(
            lambda: _Connection(), _runtime_identity()
        )
        with (
            patch(
                "yap_server.agents.auditor_result_audit.read_auditor_evidence_in_transaction",
                return_value=AuditorEvidencePack.create(
                    generation_sha256=evidence.generation_sha256,
                    source_admission_sha256=evidence.source_admission_sha256,
                    permission_hash=evidence.permission_hash,
                    authorization_hash=evidence.authorization_hash,
                    items=(evidence.items[0], evidence.items[2]),
                    output_budget_exhausted=False,
                ),
            ),
            self.assertRaises(AuditorEvidenceChanged),
        ):
            _record(auditor, evidence=evidence, report=_report(evidence))


if __name__ == "__main__":
    unittest.main()
