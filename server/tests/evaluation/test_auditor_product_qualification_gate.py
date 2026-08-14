
from __future__ import annotations

from contextlib import ExitStack
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest import mock

from yap_server.agents.auditor import (
    AuditorEvidencePack,
    AuditorFinding,
    AuditorReport,
    AuditorRequest,
    auditor_request_sha256,
    auditor_work_sha256,
)
from yap_server.agents.librarian import LibrarianEvidenceItem
from yap_server.evaluation import auditor_product_qualification_gate as gate
from yap_server.evaluation.auditor_qualification import AuditorExpectedView
from yap_server.knowledge.knowledge_tool_contract import KnowledgeToolCancelled


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def _report() -> AuditorReport:
    left = LibrarianEvidenceItem(
        concept_id="auditor-product-left",
        source_revision="source-revision",
        content_sha256=hashlib.sha256(b"five").hexdigest(),
        char_start=0,
        char_end=4,
        text="five",
    )
    right = LibrarianEvidenceItem(
        concept_id="auditor-product-right",
        source_revision="source-revision",
        content_sha256=hashlib.sha256(b"ten").hexdigest(),
        char_start=0,
        char_end=3,
        text="ten",
    )
    return AuditorReport.create(
        generation_sha256="c" * 64,
        source_admission_sha256="a" * 64,
        evidence_sha256="b" * 64,
        findings=(AuditorFinding.create((left, right)),),
    )


def _request(index: int = 0) -> AuditorRequest:
    return AuditorRequest(
        focus=f"What is product fact {index}?",
        maximum_findings=3,
        expected_generation_sha256="c" * 64,
    )


class AuditorProductQualificationGateTests(unittest.TestCase):
    def test_acceptance_and_candidate_inputs_cover_the_product_boundary(self) -> None:
        acceptance = gate.load_auditor_product_acceptance(
            REPOSITORY_ROOT / "server/auditor-product-acceptance.json"
        )

        self.assertEqual(acceptance.case_count, 8)
        self.assertEqual(acceptance.query_count, 10)
        self.assertEqual(acceptance.complete_count, 4)
        self.assertEqual(acceptance.unavailable_count, 5)
        self.assertEqual(acceptance.cancelled_count, 1)
        self.assertEqual(acceptance.maximum_normal_p95_milliseconds, 85_000)

        paths = gate._candidate_input_paths(REPOSITORY_ROOT)
        relative = {path.relative_to(REPOSITORY_ROOT).as_posix() for path in paths}
        required = {
            "server/auditor-product-acceptance.json",
            "server/agent-model-route-qualification.lock.json",
            "server/src/yap_server/agents/auditor_report_service.py",
            "server/src/yap_server/agents/auditor_product_runtime.py",
            "server/src/yap_server/api/auditor_report_requests.py",
            "server/src/yap_server/evaluation/auditor_product_qualification_gate.py",
            "server/tests/evaluation/test_auditor_product_qualification_gate.py",
            "desktop/src/auditor.ts",
            "desktop/src/components/auditor/auditor-report-composer.tsx",
            "desktop/src/components/auditor/auditor-report-result.tsx",
            "desktop/src/components/auditor/use-auditor-report.ts",
            "desktop/src-tauri/src/auditor_report.rs",
            "desktop/src-tauri/src/server_connector/auditor.rs",
            "desktop/tests/unit/auditor-product.test.tsx",
            "desktop/tests/wdio/smoke.spec.js",
            "infra/yap-server-node/agent-vllm-server.sh",
            "server/openapi/examples/health.ok.json",
            ".github/workflows/ci.yml",
        }
        self.assertTrue(required <= relative)
        self.assertEqual(len(relative), len(paths))
        self.assertTrue(
            all(0 < path.stat().st_size <= 16 * 1024 * 1024 for path in paths)
        )

    def test_product_view_parser_is_strict_and_hash_bound(self) -> None:
        report = _report()
        request_id = "auditor-report-" + "1" * 32
        complete = {
            "schemaVersion": 1,
            "requestId": request_id,
            "status": "complete",
            "report": report.to_wire(),
        }

        parsed = gate._parse_product_view(complete)

        self.assertEqual(parsed.request_id, request_id)
        self.assertEqual(parsed.report, report)
        with self.assertRaisesRegex(ValueError, "fields"):
            gate._parse_product_view(dict(complete, canonical=False))
        forged = report.to_wire()
        forged["reportSha256"] = "d" * 64
        with self.assertRaisesRegex(ValueError, "auditor report"):
            gate._parse_product_view(dict(complete, report=forged))

    def test_active_and_unavailable_views_carry_no_report(self) -> None:
        request_id = "auditor-report-" + "2" * 32
        active = gate._parse_product_view(
            {
                "schemaVersion": 1,
                "requestId": request_id,
                "status": "running",
            }
        )
        unavailable = gate._parse_product_view(
            {
                "schemaVersion": 1,
                "requestId": request_id,
                "status": "evidence-unavailable",
                "reason": "empty-result",
            }
        )

        self.assertIsNone(active.report)
        self.assertIsNone(unavailable.report)
        with self.assertRaisesRegex(ValueError, "fields"):
            gate._parse_product_view(
                {
                    "schemaVersion": 1,
                    "requestId": request_id,
                    "status": "cancelled",
                    "reason": "client-cancelled",
                    "report": _report().to_wire(),
                }
            )

    def test_http_authentication_covers_post_get_and_delete(self) -> None:
        def response(_base_url, path, *, method, token, body=None):
            del body
            if path == "/v1/health":
                return 200, {
                    "auth": "required",
                    "capabilities": {"auditorReports": True},
                }
            self.assertIn(method, {"POST", "GET", "DELETE"})
            if token is None:
                return 401, {"code": "AUTHENTICATION_REQUIRED"}
            return 401, {"code": "INVALID_ACCESS_TOKEN"}

        with mock.patch.object(gate, "_http_json", side_effect=response) as call:
            checks = gate._probe_http_authentication(
                "http://127.0.0.1:1234",
                request=_request(),
            )

        self.assertEqual(call.call_count, 7)
        self.assertTrue(all(checks.values()))

    def test_foreign_owner_cannot_read_or_cancel(self) -> None:
        with mock.patch.object(
            gate,
            "_http_json",
            side_effect=(
                (404, {"code": "AUDITOR_REPORT_NOT_FOUND"}),
                (404, {"code": "AUDITOR_REPORT_NOT_FOUND"}),
            ),
        ) as call:
            exact = gate._foreign_owner_isolation_exact(
                "http://127.0.0.1:1234",
                "auditor-report-" + "3" * 32,
                foreign_token="foreign-token",
            )

        self.assertTrue(exact)
        self.assertEqual(
            [item.kwargs["method"] for item in call.call_args_list],
            ["GET", "DELETE"],
        )

    def test_product_evidence_counts_and_hidden_shape_fail_closed(self) -> None:
        acceptance = gate.load_auditor_product_acceptance(
            REPOSITORY_ROOT / "server/auditor-product-acceptance.json"
        )
        report = _report()
        observations: list[gate.AuditorProductObservation] = []
        labels = (
            "numeric-limit-conflict",
            "status-conflict",
            "multi-conflict",
            "instruction-data-conflict",
            "time-scope-difference",
            "missing-value-unavailable",
            "hidden-only-unavailable",
            "absent-unavailable",
        )
        for index, label in enumerate(labels):
            expected = (
                AuditorExpectedView("complete", None, report)
                if index < 4
                else AuditorExpectedView(
                    "evidence-unavailable",
                    "empty-result"
                    if label in {"hidden-only-unavailable", "absent-unavailable"}
                    else "model-evidence-unavailable",
                    None,
                )
            )
            view = gate.AuditorProductView(
                "auditor-report-" + f"{index:032x}",
                expected.status,
                expected.report,
                expected.reason,
            )
            observations.append(
                gate.AuditorProductObservation(
                    label,
                    f"owner-{index}",
                    _request(index),
                    expected,
                    view.request_id,
                    f"internal-{index}",
                    view,
                    10,
                    True,
                    True,
                    True,
                    True,
                    None,
                )
            )
        empty = AuditorExpectedView("evidence-unavailable", "empty-result", None)
        hidden_view = gate.AuditorProductView(
            "auditor-report-" + "a" * 32,
            empty.status,
            None,
            empty.reason,
        )
        observations.append(
            gate.AuditorProductObservation(
                "cross-owner-hidden",
                "cross-owner",
                _request(8),
                empty,
                hidden_view.request_id,
                "internal-hidden",
                hidden_view,
                10,
                True,
                True,
                True,
                False,
                None,
            )
        )
        cancelled = AuditorExpectedView("cancelled", "client-cancelled", None)
        cancelled_view = gate.AuditorProductView(
            "auditor-report-" + "b" * 32,
            cancelled.status,
            None,
            cancelled.reason,
        )
        observations.append(
            gate.AuditorProductObservation(
                "http-cancelled",
                "owner-0",
                _request(),
                cancelled,
                cancelled_view.request_id,
                "internal-cancelled",
                cancelled_view,
                10,
                True,
                True,
                True,
                False,
                None,
            )
        )

        public = gate._evaluate_product_observations(
            observations,
            acceptance=acceptance,
            authentication_probe={"exact": True},
            database_state_exact=True,
            worker_containment_met=True,
        )
        self.assertTrue(public["qualified"])
        self.assertEqual(public["exactTerminalCount"], 10)

        forged = list(observations)
        forged[0] = replace(forged[0], exact_match=False)
        self.assertFalse(
            gate._evaluate_product_observations(
                forged,
                acceptance=acceptance,
                authentication_probe={"exact": True},
                database_state_exact=True,
                worker_containment_met=True,
            )["qualified"]
        )

    def test_cancellation_model_requires_the_product_event(self) -> None:
        model = gate._CancellationModel()
        cancellation = threading.Event()
        failure: list[BaseException] = []

        def run() -> None:
            try:
                model.report(
                    mock.sentinel.request,
                    mock.sentinel.evidence,
                    cancellation=cancellation,
                )
            except BaseException as error:
                failure.append(error)

        worker = threading.Thread(target=run)
        worker.start()
        self.assertTrue(model.started.wait(1.0))
        cancellation.set()
        worker.join(1.0)

        self.assertFalse(worker.is_alive())
        self.assertTrue(model.cancelled.is_set())
        self.assertEqual(len(failure), 1)
        self.assertIsInstance(failure[0], KnowledgeToolCancelled)

    def test_database_readback_is_auditor_owned_and_exact(self) -> None:
        report = _report()
        evidence = AuditorEvidencePack.create(
            generation_sha256=report.generation_sha256,
            source_admission_sha256=report.source_admission_sha256,
            permission_hash="d" * 64,
            authorization_hash="e" * 64,
            items=tuple(
                citation
                for finding in report.findings
                for citation in finding.citations
            ),
            output_budget_exhausted=False,
        )
        report = AuditorReport.create(
            generation_sha256=evidence.generation_sha256,
            source_admission_sha256=evidence.source_admission_sha256,
            evidence_sha256=evidence.evidence_sha256,
            findings=report.findings,
        )
        request = AuditorRequest(
            focus="What is the Helios release limit?",
            maximum_findings=3,
            expected_generation_sha256=evidence.generation_sha256,
        )
        expected = AuditorExpectedView("complete", None, report)
        view = gate.AuditorProductView(
            "auditor-report-" + "c" * 32,
            "complete",
            report,
            None,
        )
        observation = gate.AuditorProductObservation(
            "numeric-limit-conflict",
            "owner-limit",
            request,
            expected,
            view.request_id,
            "internal-auditor-request",
            view,
            10,
            True,
            True,
            True,
            True,
            None,
        )
        profile = SimpleNamespace(
            candidate_id="candidate",
            expected_model="model",
            model_revision="b" * 40,
            runtime_id="runtime",
            profile_sha256="c" * 64,
            candidate_lock_sha256="f" * 64,
        )
        result_row = (
            observation.owner_id,
            observation.internal_request_id,
            auditor_request_sha256(request),
            auditor_work_sha256(request, evidence),
            evidence.evidence_sha256,
            report.report_sha256,
            report.citation_sha256,
            evidence.generation_sha256,
            evidence.source_admission_sha256,
            evidence.permission_hash,
            evidence.authorization_hash,
            "auditor",
            "knowledge-audit",
            "complex-orchestration",
            "idle-only",
            7,
            profile.candidate_id,
            profile.expected_model,
            profile.model_revision,
            profile.runtime_id,
            profile.profile_sha256,
            profile.candidate_lock_sha256,
            "succeeded",
            None,
            1,
            True,
        )
        tool_row = (
            observation.owner_id,
            "auditor",
            "search",
            "succeeded",
            len(evidence.items),
            evidence.generation_sha256,
            evidence.permission_hash,
            evidence.authorization_hash,
            True,
        )
        connection = mock.Mock()

        def execute(statement, _parameters):
            self.assertNotIn("librarian", statement.lower())
            result = mock.Mock()
            if "yap_auditor_result_audit" in statement:
                result.fetchall.return_value = [result_row]
            elif "yap_knowledge_tool_audit" in statement:
                result.fetchall.return_value = [tool_row]
            elif "yap_knowledge_proposals" in statement:
                result.fetchone.return_value = (0,)
            elif "yap_knowledge_activation_history" in statement:
                result.fetchone.return_value = (2,)
            else:
                self.fail(f"unexpected Auditor product SQL: {statement}")
            return result

        connection.execute.side_effect = execute
        context = mock.MagicMock()
        context.__enter__.return_value = connection
        initialized = SimpleNamespace(
            bound=SimpleNamespace(
                tenant_id="tenant",
                evidence_by_case={observation.label: evidence},
            )
        )
        with (
            mock.patch.object(gate, "_verify_initialized_knowledge"),
            mock.patch.object(gate.psycopg, "connect", return_value=context),
        ):
            checks = gate._verify_product_database_state(
                "postgresql://private",
                initialized,
                (observation,),
                profile=profile,
                provider_generation=7,
            )

        self.assertTrue(all(checks.values()))

    def test_private_destination_is_create_once_and_outside_repository(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            outside = Path(value).resolve() / "receipt.json"
            self.assertEqual(
                gate._new_private_evidence_destination(
                    outside,
                    repository_root=REPOSITORY_ROOT,
                ),
                outside,
            )
            outside.write_text("reserved", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "new and outside"):
                gate._new_private_evidence_destination(
                    outside,
                    repository_root=REPOSITORY_ROOT,
                )

    def test_gate_owns_two_restarts_http_runtimes_and_private_receipt(self) -> None:
        acceptance = gate.load_auditor_product_acceptance(
            REPOSITORY_ROOT / "server/auditor-product-acceptance.json"
        )
        candidate = mock.Mock()
        database = mock.Mock()
        database.start.return_value = SimpleNamespace(
            dsn="postgresql://private-initial",
            process_id=10,
        )
        database.stop.return_value = {"contained": True}
        first_restart = SimpleNamespace(
            dsn="postgresql://private-first",
            process_id=11,
        )
        second_restart = SimpleNamespace(
            dsn="postgresql://private-second",
            process_id=12,
        )
        normal_runtime = mock.Mock()
        cancel_runtime = mock.Mock()
        invocations = tuple(
            SimpleNamespace(
                owner_id=f"owner-{index}",
                focus=f"Question {index}?",
                maximum_findings=3,
                expected_generation_sha256="a" * 64,
            )
            for index in range(8)
        )
        observations = tuple(object() for _ in range(10))
        authentication = {"exact": True}
        profile = SimpleNamespace(
            maximum_sequences=8,
            batch_invariant=True,
            launch_arguments=(),
            candidate_id="candidate",
            expected_model="model",
            model_revision="b" * 40,
            runtime_id="runtime",
            profile_sha256="c" * 64,
            candidate_lock_sha256="d" * 64,
        )
        semantic_acceptance = SimpleNamespace(
            maximum_normal_p95_milliseconds=85_000,
            plan_sha256="e" * 64,
        )
        corpus = SimpleNamespace(
            cases=tuple(object() for _ in range(8)),
            corpus_sha256="f" * 64,
        )
        initialized = SimpleNamespace(bound=SimpleNamespace())
        capacity = {
            "admittedOwnerCount": 8,
            "expectedCapacityObserved": True,
            "overflowOwnerQueued": True,
            "contained": True,
            "providerIdentityUnchanged": True,
            "brokerIdentityUnchanged": True,
        }
        public = acceptance.expected_public_evidence()
        public["qualified"] = True
        written = mock.Mock()

        with tempfile.TemporaryDirectory() as value:
            private_root = Path(value).resolve()
            destination = private_root / "receipt.json"
            patches = {
                "_candidate_input_paths": {"return_value": ()},
                "admit_checked_candidate": {"return_value": candidate},
                "_require_private_arm64_host": {},
                "load_auditor_product_acceptance": {"return_value": acceptance},
                "load_auditor_qualification_acceptance": {
                    "return_value": semantic_acceptance
                },
                "load_auditor_qualification_corpus": {"return_value": corpus},
                "load_auditor_service_profile": {"return_value": profile},
                "_require_full_complex_profile": {},
                "build_checked_admission_broker": {"return_value": "1" * 64},
                "read_service_state": {"return_value": {"processGeneration": 7}},
                "validate_state_identity": {},
                "probe_exact_service": {},
                "observe_admission_broker": {"return_value": {"processId": 8}},
                "probe_agent_admission_broker_capacity": {"return_value": capacity},
                "load_knowledge_database_runtime_lock": {
                    "return_value": SimpleNamespace(lock_sha256="2" * 64)
                },
                "OwnedPostgresKnowledgeRuntime": {"return_value": database},
                "_initialize_auditor_knowledge": {"return_value": initialized},
                "_restart_database": {"side_effect": (first_restart, second_restart)},
                "_verify_initialized_knowledge": {},
                "_write_new_private_text": {},
                "_normal_invocations": {"return_value": invocations},
                "_build_product_runtime": {"return_value": normal_runtime},
                "_build_cancellation_runtime": {"return_value": cancel_runtime},
                "_start_http_server": {
                    "side_effect": (
                        (object(), mock.Mock(), "http://127.0.0.1:1"),
                        (object(), mock.Mock(), "http://127.0.0.1:2"),
                    )
                },
                "_stop_http_server": {},
                "_probe_http_authentication": {"return_value": authentication},
                "_run_normal_product_wave": {"return_value": observations[:8]},
                "_run_cross_owner_control": {"return_value": observations[8]},
                "_run_cancellation_control": {"return_value": observations[9]},
                "_provider_generation": {"return_value": 7},
                "_bind_internal_request_ids": {"return_value": observations},
                "_verify_product_database_state": {
                    "return_value": {"auditorResultAuditExact": True}
                },
                "_require_exact_teardown": {},
                "_evaluate_product_observations": {"return_value": public},
                "bind_checked_candidate_evidence": {
                    "side_effect": lambda evidence, _candidate: {
                        **evidence,
                        "candidate": {"checkedHead": "3" * 40},
                        "evidenceSha256": "4" * 64,
                    }
                },
                "_private_observations": {"return_value": [{"exactMatch": True}]},
                "write_new_private_json_evidence": {"new": written},
            }
            with ExitStack() as stack:
                active = {
                    name: stack.enter_context(mock.patch.object(gate, name, **options))
                    for name, options in patches.items()
                }
                receipt = gate.run_auditor_product_qualification_gate(
                    repository_root=REPOSITORY_ROOT,
                    checked_head="3" * 40,
                    evidence_destination=destination,
                    admission_socket_path=private_root / "admission.sock",
                    rapid_state_path=private_root / "rapid.json",
                    complex_state_path=private_root / "complex.json",
                )

        self.assertEqual(
            receipt["outcome"],
            "auditor-authenticated-product-server-boundary-qualified",
        )
        self.assertEqual(active["_restart_database"].call_count, 2)
        self.assertEqual(active["_start_http_server"].call_count, 2)
        self.assertEqual(active["_stop_http_server"].call_count, 2)
        normal_runtime.close.assert_called_once_with()
        cancel_runtime.close.assert_called_once_with()
        database.stop.assert_called_once_with(timeout_seconds=15)
        candidate.verify_unchanged.assert_called_once()
        written.assert_called_once()
        private_payload = written.call_args.args[1]
        self.assertEqual(
            private_payload["privacyScope"],
            "private-auditor-product-qualification",
        )
        serialized = json.dumps(private_payload)
        self.assertNotIn("postgresql://private", serialized)
        self.assertNotIn("Bearer ", serialized)


if __name__ == "__main__":
    unittest.main()
