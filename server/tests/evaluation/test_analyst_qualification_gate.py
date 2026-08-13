from __future__ import annotations

from contextlib import ExitStack
from dataclasses import replace
import hashlib
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

from yap_server.evaluation import analyst_qualification_gate as gate
from yap_server.knowledge.okf_compiler import compile_okf_bundle
from yap_server.knowledge.knowledge_tool_contract import KnowledgeToolCancelled


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


class AnalystQualificationGateTests(unittest.TestCase):
    def test_candidate_inputs_cover_the_full_analyst_stack_and_oracle(self) -> None:
        relative = {
            path.relative_to(REPOSITORY_ROOT).as_posix()
            for path in gate._candidate_input_paths(REPOSITORY_ROOT)
        }
        required = {
            "server/analyst-acceptance.json",
            "server/analyst-workload-fixtures.json",
            "server/src/yap_server/agents/analyst.py",
            "server/src/yap_server/agents/analyst_model.py",
            "server/src/yap_server/agents/analyst_result_audit.py",
            "server/src/yap_server/agents/analyst_runtime.py",
            "server/src/yap_server/agents/analyst_service.py",
            "server/src/yap_server/agents/librarian.py",
            "server/src/yap_server/agents/librarian_result_audit.py",
            "server/src/yap_server/agents/librarian_service.py",
            "server/src/yap_server/evaluation/agent_admission_broker_observation.py",
            "server/src/yap_server/evaluation/agent_service_lifecycle_observation.py",
            "server/src/yap_server/evaluation/analyst_qualification.py",
            "server/src/yap_server/evaluation/analyst_qualification_gate.py",
            "server/src/yap_server/evaluation/librarian_qualification.py",
            "server/src/yap_server/evaluation/provider_runtime_observations.py",
            "server/src/yap_server/knowledge/agent_reasoning_routes.py",
            "server/src/yap_server/knowledge/governed_answer_protocol.py",
            "server/src/yap_server/knowledge/vllm_reasoning_client.py",
            "server/orchestrator/src/agent_admission.rs",
            "server/orchestrator/src/bin/yap-agent-admission-broker.rs",
            "server/tests/agents/test_analyst_model.py",
            "server/tests/agents/test_analyst_runtime.py",
            "server/tests/agents/test_analyst_service.py",
            "server/tests/evaluation/test_analyst_qualification.py",
            "server/tests/evaluation/test_librarian_qualification.py",
            "server/tests/evaluation/test_provider_runtime_observations.py",
            "server/tests/knowledge/test_agent_reasoning_routes.py",
            "server/tests/knowledge/test_governed_answer_protocol.py",
            "server/tests/knowledge/test_vllm_reasoning_client.py",
        }
        self.assertTrue(required.issubset(relative))

    def test_full_complex_profile_cannot_be_throttled(self) -> None:
        exact = (
            "vllm",
            "serve",
            "model",
            "--max-model-len",
            "8192",
            "--gpu-memory-utilization",
            "0.70",
            "--max-num-seqs",
            "8",
            "--max-num-batched-tokens",
            "8192",
        )
        gate._require_full_complex_profile(8, exact)
        for sequences, arguments in (
            (7, exact),
            (8, tuple("0.60" if item == "0.70" else item for item in exact)),
            (8, tuple("7" if item == "8" else item for item in exact)),
            (8, tuple("4096" if item == "8192" else item for item in exact)),
        ):
            with self.subTest(sequences=sequences, arguments=arguments):
                with self.assertRaisesRegex(ValueError, "full complex profile"):
                    gate._require_full_complex_profile(sequences, arguments)

    def test_compiler_binding_rejects_source_revision_and_permission_drift(
        self,
    ) -> None:
        corpus = gate.load_analyst_qualification_corpus(
            REPOSITORY_ROOT / "server/analyst-workload-fixtures.json"
        )
        rendered = gate.render_analyst_qualification_generations(
            corpus,
            tenant_id="analyst-q-1234567890abcdef",
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            compiled = {}
            for generation in rendered:
                bundle = root / generation.generation_id
                bundle.mkdir()
                gate._write_rendered_generation(bundle, generation)
                compiled[generation.generation_id] = compile_okf_bundle(
                    bundle,
                    tenant_id=generation.tenant_id,
                    source_revision=generation.source_revision,
                )
        bound = gate.bind_analyst_compiled_corpus(corpus, rendered, compiled)
        self.assertEqual(set(bound.generation_sha256s), {"predecessor", "successor"})

        changed_revision = dict(compiled)
        changed_revision["successor"] = replace(
            changed_revision["successor"],
            source_revision="changed-source-revision",
        )
        with self.assertRaisesRegex(ValueError, "source revision"):
            gate.bind_analyst_compiled_corpus(corpus, rendered, changed_revision)

        changed_permission = dict(compiled)
        successor = changed_permission["successor"]
        permissions = list(successor.permissions)
        permissions[0] = replace(permissions[0], permission_sha256="f" * 64)
        changed_permission["successor"] = replace(
            successor,
            permissions=tuple(permissions),
        )
        with self.assertRaisesRegex(ValueError, "permission"):
            gate.bind_analyst_compiled_corpus(corpus, rendered, changed_permission)

    def test_preflight_includes_librarian_and_analyst_audits(self) -> None:
        connection = _CountConnection([(0,)] * 8)
        gate._assert_empty_analyst_state(connection, tenant_id="analyst-q-1234")
        self.assertTrue(
            any("yap_librarian_result_audit" in query for query in connection.queries)
        )
        self.assertTrue(
            any("yap_analyst_result_audit" in query for query in connection.queries)
        )
        with self.assertRaisesRegex(RuntimeError, "tenant is not fresh"):
            gate._assert_empty_analyst_state(
                _CountConnection([(0,)] * 6 + [(1,), (0,)]),
                tenant_id="analyst-q-1234",
            )

    def test_audit_derivation_rejects_missing_librarian_lineage(self) -> None:
        corpus = gate.load_analyst_qualification_corpus(
            REPOSITORY_ROOT / "server/analyst-workload-fixtures.json"
        )
        rendered = gate.render_analyst_qualification_generations(
            corpus,
            tenant_id="analyst-q-1234567890abcdef",
        )
        with tempfile.TemporaryDirectory() as temporary:
            compiled = {}
            for generation in rendered:
                bundle = Path(temporary) / generation.generation_id
                bundle.mkdir()
                gate._write_rendered_generation(bundle, generation)
                compiled[generation.generation_id] = compile_okf_bundle(
                    bundle,
                    tenant_id=generation.tenant_id,
                    source_revision=generation.source_revision,
                )
        initialized = gate._InitializedKnowledge(
            rendered,
            compiled,
            gate.bind_analyst_compiled_corpus(corpus, rendered, compiled),
        )
        invocations = gate.build_analyst_qualification_invocations(
            initialized.bound.corpus,
            tenant_id=initialized.bound.tenant_id,
            generation_sha256s=initialized.bound.generation_sha256s,
        )
        observations = tuple(
            mock.Mock(
                invocation=invocation,
                request_id=f"request-{index}",
                exact_match=True,
            )
            for index, invocation in enumerate(invocations)
        )
        rows = [
            (
                invocation.owner_id,
                f"request-{index}",
                None,
                *([None] * 23),
            )
            for index, invocation in enumerate(invocations)
        ]
        with self.assertRaisesRegex(RuntimeError, "Librarian audit identity"):
            gate._expected_audit_rows(
                initialized,
                mock.Mock(observations=observations),
                profile=mock.Mock(),
                provider_generation=7,
                actual_result_rows=rows,
            )

    def test_controlled_models_fire_only_after_service_calls_them(self) -> None:
        evidence = gate._ControlledModeEvidence()
        client = threading.Event()
        worker = threading.Event()
        forwarding = threading.Thread(target=lambda: (client.wait(), worker.set()))
        forwarding.start()
        model = gate._ClientCancelledModel(client, evidence)
        try:
            with self.assertRaises(KnowledgeToolCancelled):
                model.answer(
                    mock.sentinel.request,
                    mock.sentinel.evidence,
                    cancellation=worker,
                )
        finally:
            forwarding.join()
        self.assertTrue(client.is_set())
        self.assertTrue(evidence.client_cancelled_after_admission)

        invalid = gate._InvalidOutputModel(evidence)
        with self.assertRaisesRegex(ValueError, "invalid output"):
            invalid.answer(
                mock.sentinel.request,
                mock.sentinel.evidence,
                cancellation=threading.Event(),
            )
        self.assertTrue(evidence.invalid_output_after_admission)

    def test_deadline_contract_and_private_create_once_paths(self) -> None:
        gate._require_exact_deadline_contract(85_000)
        for value in (84_999, 85_001):
            with self.assertRaisesRegex(ValueError, "deadline contract"):
                gate._require_exact_deadline_contract(value)
        with self.assertRaisesRegex(ValueError, "outside the repository"):
            gate._new_private_evidence_destination(
                REPOSITORY_ROOT / "analyst-private.json",
                repository_root=REPOSITORY_ROOT,
            )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "knowledge.dsn"
            gate._write_new_private_text(path, "postgresql://private")
            self.assertEqual(path.read_text(encoding="utf-8"), "postgresql://private\n")
            if os.name == "posix":
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaisesRegex(ValueError, "credential is invalid"):
                gate._write_new_private_text(path, "postgresql://changed")

    def test_gate_restarts_twice_rechecks_identity_and_emits_public_safe_receipt(
        self,
    ) -> None:
        events: list[str] = []

        class Candidate:
            input_sha256 = {"server/input": "1" * 64}

            def verify_unchanged(self, *, runner) -> None:
                del runner
                events.append("candidate-verified")

        class Database:
            def __init__(self, **kwargs) -> None:
                del kwargs
                self.restart_count = 0

            def start(self, *, timeout_seconds):
                del timeout_seconds
                events.append("database-started")
                return mock.Mock(
                    container_id="a" * 64,
                    process_id=10,
                    dsn="postgresql://private-initial",
                )

            def restart(self, *, timeout_seconds):
                del timeout_seconds
                self.restart_count += 1
                events.append(f"database-restarted-{self.restart_count}")
                return mock.Mock(
                    container_id="a" * 64,
                    process_id=10 + self.restart_count,
                    dsn=f"postgresql://private-restarted-{self.restart_count}",
                )

            def stop(self, *, timeout_seconds):
                del timeout_seconds
                events.append("database-stopped")
                return {name: True for name in gate._TEARDOWN_KEYS}

            def contain_failed_run(self):
                events.append("database-contained")
                return {}

        acceptance = mock.Mock(plan_sha256="2" * 64, maximum_p95_milliseconds=85_000)
        corpus = mock.Mock(corpus_sha256="3" * 64)
        initialized = mock.Mock()
        result = mock.Mock(
            public_evidence={"schemaVersion": 1, "qualified": True}, observations=()
        )
        profile = mock.Mock(
            candidate_id="gemma",
            expected_model="model",
            model_revision="4" * 40,
            runtime_id="runtime",
            candidate_lock_sha256="4" * 64,
            profile_sha256="5" * 64,
            maximum_sequences=8,
            launch_arguments=(
                "vllm",
                "serve",
                "model",
                "--max-model-len",
                "8192",
                "--gpu-memory-utilization",
                "0.70",
                "--max-num-seqs",
                "8",
                "--max-num-batched-tokens",
                "8192",
            ),
        )
        runtime = mock.Mock(maximum_output_tokens=512, maximum_input_tokens=7_680)
        controlled = mock.Mock()
        database_state = {
            "successorGenerationActive": True,
            "twoGenerationsRetainedExact": True,
            "twoSourceAdmissionsRetainedExact": True,
            "successorActivationHistoryExact": True,
            "proposalWritesAbsent": True,
            "analystResultAuditExact": True,
            "librarianResultAuditExact": True,
            "knowledgeToolAuditExact": True,
        }
        capacity = {
            "admittedOwnerCount": 8,
            "expectedCapacityObserved": True,
            "expectedRouteObserved": True,
            "overflowOwnerQueued": True,
            "contained": True,
            "providerIdentityUnchanged": True,
            "brokerIdentityUnchanged": True,
        }
        provider_state = {"processGeneration": 7}
        broker_state = {"processId": 41}

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence_path = root / "private" / "receipt.json"

            def observe_provider(*args, **kwargs):
                del args, kwargs
                events.append("provider-observed")
                return dict(provider_state)

            def observe_broker(*args, **kwargs):
                del args, kwargs
                events.append("broker-observed")
                return dict(broker_state)

            patches = (
                mock.patch.object(
                    gate, "admit_checked_candidate", return_value=Candidate()
                ),
                mock.patch.object(gate, "_candidate_input_paths", return_value=()),
                mock.patch.object(gate, "_require_private_arm64_host"),
                mock.patch.object(
                    gate,
                    "load_analyst_qualification_acceptance",
                    return_value=acceptance,
                ),
                mock.patch.object(
                    gate, "load_analyst_qualification_corpus", return_value=corpus
                ),
                mock.patch.object(
                    gate, "load_analyst_service_profile", return_value=profile
                ),
                mock.patch.object(
                    gate, "build_checked_admission_broker", return_value="6" * 64
                ),
                mock.patch.object(
                    gate, "read_service_state", side_effect=observe_provider
                ),
                mock.patch.object(gate, "validate_state_identity"),
                mock.patch.object(gate, "probe_exact_service"),
                mock.patch.object(
                    gate, "observe_admission_broker", side_effect=observe_broker
                ),
                mock.patch.object(
                    gate, "probe_agent_admission_broker_capacity", return_value=capacity
                ),
                mock.patch.object(
                    gate,
                    "load_knowledge_database_runtime_lock",
                    return_value=mock.Mock(lock_sha256="7" * 64),
                ),
                mock.patch.object(gate, "OwnedPostgresKnowledgeRuntime", Database),
                mock.patch.object(
                    gate, "_initialize_analyst_knowledge", return_value=initialized
                ),
                mock.patch.object(gate, "_verify_initialized_knowledge"),
                mock.patch.object(gate, "_build_runtime", return_value=runtime),
                mock.patch.object(
                    gate, "_build_analyst_executor", return_value=(object(), controlled)
                ),
                mock.patch.object(
                    gate, "evaluate_analyst_qualification", return_value=result
                ),
                mock.patch.object(
                    gate, "_verify_analyst_database_state", return_value=database_state
                ),
                mock.patch.object(
                    gate,
                    "bind_checked_candidate_evidence",
                    side_effect=lambda value, candidate: {
                        **value,
                        "candidate": candidate.input_sha256,
                        "evidenceSha256": "8" * 64,
                    },
                ),
            )
            with ExitStack() as stack:
                for patcher in patches:
                    stack.enter_context(patcher)
                receipt = gate.run_analyst_qualification_gate(
                    repository_root=REPOSITORY_ROOT,
                    checked_head="a" * 40,
                    evidence_destination=evidence_path,
                    admission_socket_path=root / "admission.sock",
                    rapid_state_path=root / "rapid-state.json",
                    complex_state_path=root / "complex-state.json",
                )

            controlled.require_complete.assert_called_once_with()
            self.assertEqual(events.count("provider-observed"), 2)
            self.assertEqual(events.count("broker-observed"), 2)
            self.assertEqual(
                receipt["outcome"], "analyst-grounded-cited-answers-qualified"
            )
            self.assertEqual(receipt["workload"]["brokerActiveCapacity"], 8)
            self.assertTrue(receipt["workload"]["ninthOwnerQueued"])
            self.assertTrue(receipt["knowledge"]["resultRestartReadBackObserved"])
            serialized = str(receipt)
            self.assertNotIn("private-restarted", serialized)
            self.assertNotIn("analyst-q-", serialized)
            body = evidence_path.read_bytes()
            self.assertEqual(hashlib.sha256(body).digest_size, 32)
            self.assertIn(b"private-analyst-qualification", body)


class _CountConnection:
    def __init__(self, rows: list[tuple[int]]) -> None:
        self.rows = iter(rows)
        self.queries: list[str] = []

    def execute(self, query, parameters):
        del parameters
        self.queries.append(query)
        return self

    def fetchone(self):
        return next(self.rows)


if __name__ == "__main__":
    unittest.main()
