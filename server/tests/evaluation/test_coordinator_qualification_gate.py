from __future__ import annotations

from contextlib import ExitStack
import hashlib
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

from yap_server.evaluation import coordinator_qualification_gate as gate
from yap_server.knowledge.knowledge_tool_contract import KnowledgeToolCancelled


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


class CoordinatorQualificationGateTests(unittest.TestCase):
    def test_candidate_inputs_cover_full_coordinator_curator_and_gate_stack(
        self,
    ) -> None:
        relative = {
            path.relative_to(REPOSITORY_ROOT).as_posix()
            for path in gate._candidate_input_paths(REPOSITORY_ROOT)
        }
        required = {
            "server/coordinator-acceptance.json",
            "server/coordinator-workload-fixtures.json",
            "server/src/yap_server/agents/coordinator.py",
            "server/src/yap_server/agents/coordinator_model.py",
            "server/src/yap_server/agents/coordinator_result_audit.py",
            "server/src/yap_server/agents/coordinator_runtime.py",
            "server/src/yap_server/agents/coordinator_service.py",
            "server/src/yap_server/agents/curator.py",
            "server/src/yap_server/agents/curator_publisher.py",
            "server/src/yap_server/agents/curator_result_audit.py",
            "server/src/yap_server/agents/librarian.py",
            "server/src/yap_server/evaluation/coordinator_qualification.py",
            "server/src/yap_server/evaluation/coordinator_qualification_gate.py",
            "server/src/yap_server/evaluation/librarian_qualification.py",
            "server/src/yap_server/knowledge/governed_knowledge_tools.py",
            "server/src/yap_server/knowledge/knowledge_agent_authority.py",
            "server/src/yap_server/knowledge/knowledge_proposals.py",
            "server/src/yap_server/knowledge/postgres_relationship_retrieval.py",
            "server/tests/agents/test_coordinator.py",
            "server/tests/agents/test_coordinator_postgres.py",
            "server/tests/agents/test_coordinator_result_audit.py",
            "server/tests/agents/test_coordinator_runtime.py",
            "server/tests/agents/test_coordinator_service.py",
            "server/tests/agents/test_curator_postgres.py",
            "server/tests/agents/test_librarian.py",
            "server/tests/evaluation/test_coordinator_qualification.py",
            "server/tests/evaluation/test_coordinator_qualification_gate.py",
            "server/tests/evaluation/test_librarian_qualification.py",
            "server/tests/knowledge/test_knowledge_proposals.py",
            "server/orchestrator/src/agent_admission.rs",
            "server/orchestrator/src/bin/yap-agent-admission-broker.rs",
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
            "--no-enable-prefix-caching",
        )
        gate._require_full_complex_profile(8, True, exact)
        for sequences, batch_invariant, arguments in (
            (7, True, exact),
            (8, False, exact),
            (8, True, tuple("0.60" if item == "0.70" else item for item in exact)),
            (8, True, tuple("7" if item == "8" else item for item in exact)),
            (8, True, tuple("4096" if item == "8192" else item for item in exact)),
            (
                8,
                True,
                tuple(item for item in exact if item != "--no-enable-prefix-caching"),
            ),
        ):
            with self.subTest(
                sequences=sequences,
                batch_invariant=batch_invariant,
                arguments=arguments,
            ):
                with self.assertRaisesRegex(ValueError, "full complex profile"):
                    gate._require_full_complex_profile(
                        sequences,
                        batch_invariant,
                        arguments,
                    )

    def test_preflight_includes_coordinator_curator_and_tool_audits(self) -> None:
        connection = _CountConnection([(0,)] * 8)
        gate._assert_empty_coordinator_state(
            connection,
            tenant_id="coordinator-q-1234",
        )
        self.assertTrue(
            any("yap_coordinator_result_audit" in query for query in connection.queries)
        )
        self.assertTrue(
            any("yap_curator_result_audit" in query for query in connection.queries)
        )
        self.assertTrue(
            any("yap_knowledge_tool_audit" in query for query in connection.queries)
        )
        with self.assertRaisesRegex(RuntimeError, "tenant is not fresh"):
            gate._assert_empty_coordinator_state(
                _CountConnection([(0,)] * 7 + [(1,)]),
                tenant_id="coordinator-q-1234",
            )

    def test_production_compile_derives_exact_durable_audit_oracle(self) -> None:
        corpus = gate.load_coordinator_qualification_corpus(
            REPOSITORY_ROOT / "server/coordinator-workload-fixtures.json"
        )
        acceptance = gate.load_coordinator_qualification_acceptance(
            REPOSITORY_ROOT / "server/coordinator-acceptance.json"
        )
        rendered = gate.render_coordinator_qualification_generations(
            corpus,
            tenant_id="coordinator-q-1234567890abcdef",
        )
        with tempfile.TemporaryDirectory() as temporary:
            compiled = {}
            for generation in rendered:
                bundle = Path(temporary) / generation.generation_id
                bundle.mkdir()
                gate._write_rendered_generation(bundle, generation)
                compiled[generation.generation_id] = gate.compile_okf_bundle(
                    bundle,
                    tenant_id=generation.tenant_id,
                    source_revision=generation.source_revision,
                )
        compiled_corpus = gate.bind_coordinator_compiled_corpus(
            corpus,
            rendered,
            compiled,
        )
        curator_request_ids = {
            key: f"curator-request-{index}"
            for index, key in enumerate(compiled_corpus.proposal_seeds_by_key, start=1)
        }
        bound = gate.bind_coordinator_curator_lineage(
            compiled_corpus,
            curator_request_ids,
        )
        invocations = gate.build_coordinator_qualification_invocations(
            corpus,
            acceptance,
            tenant_id=bound.tenant_id,
            generation_sha256s=bound.generation_sha256s,
        )
        request_ids = {
            invocation.invocation_id: f"coordinator-request-{index}"
            for index, invocation in enumerate(invocations, start=1)
        }

        def executor(invocation, cancellation):
            del cancellation
            expected = bound.expected_views[invocation.expected_view_id]
            return gate.CoordinatorJobView(
                request_id=request_ids[invocation.invocation_id],
                status=expected.status,
                reason=expected.reason,
                bundle=expected.bundle,
            )

        result = gate.evaluate_coordinator_qualification(
            executor=executor,
            corpus=bound,
            acceptance=acceptance,
        )
        profile = mock.Mock(
            candidate_id="gemma",
            expected_model="model",
            model_revision="1" * 40,
            runtime_id="runtime",
            profile_sha256="2" * 64,
            candidate_lock_sha256="3" * 64,
        )
        proposal_rows = gate._expected_proposal_rows(bound)
        curator_rows = gate._expected_curator_rows(
            bound,
            profile=profile,
            provider_generation=7,
            curator_request_ids=curator_request_ids,
        )
        coordinator_rows, tool_rows = gate._expected_coordinator_rows(
            bound,
            result,
            acceptance=acceptance,
            profile=profile,
            provider_generation=7,
        )

        self.assertEqual(
            (
                len(proposal_rows),
                len(curator_rows),
                len(coordinator_rows),
                len(tool_rows),
            ),
            (8, 8, 29, 28),
        )
        hidden = bound.proposal_seeds_by_key["obsidian-private"]
        hidden_row = next(row for row in proposal_rows if row[1] == hidden.proposal_id)
        self.assertEqual(hidden_row[7], hidden.inherited_permission_sha256)
        self.assertEqual(
            sum(row[3] == "failed" and row[4] == 0 for row in tool_rows),
            1,
        )

    def test_private_create_once_paths_reject_repository_destination(self) -> None:
        with self.assertRaisesRegex(ValueError, "outside the repository"):
            gate._new_private_evidence_destination(
                REPOSITORY_ROOT / "coordinator-private.json",
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

    def test_restart_and_teardown_contracts_are_exact(self) -> None:
        class Database:
            def restart(self, *, timeout_seconds):
                self.timeout_seconds = timeout_seconds
                return _Started("a" * 64, 12, "postgresql://restarted")

        database = Database()
        current = _Started("a" * 64, 11, "postgresql://initial")
        restarted = gate._restart_database(database, current)
        self.assertEqual(database.timeout_seconds, 120)
        self.assertEqual(restarted.process_id, 12)
        gate._require_exact_teardown({name: True for name in gate._TEARDOWN_KEYS})
        with self.assertRaisesRegex(RuntimeError, "teardown differs"):
            gate._require_exact_teardown(
                {name: name != "volumeAbsent" for name in gate._TEARDOWN_KEYS}
            )

    def test_deadline_contract_is_exact(self) -> None:
        gate._require_exact_deadline_contract(85_000)
        for value in (84_999, 85_001):
            with self.assertRaisesRegex(ValueError, "deadline contract"):
                gate._require_exact_deadline_contract(value)

    def test_controlled_models_fire_only_after_service_calls_them(self) -> None:
        evidence = gate._ControlledModeEvidence()
        client = threading.Event()
        worker = threading.Event()
        forwarding = threading.Thread(target=lambda: (client.wait(), worker.set()))
        forwarding.start()
        model = gate._ClientCancelledModel(client, evidence)
        try:
            with self.assertRaises(KnowledgeToolCancelled):
                model.select(
                    mock.sentinel.request,
                    mock.sentinel.evidence,
                    cancellation=worker,
                )
        finally:
            forwarding.join()
        self.assertTrue(client.is_set())
        self.assertTrue(evidence.client_cancelled_after_service_call)

        invalid = gate._InvalidOutputModel(evidence)
        with self.assertRaisesRegex(ValueError, "invalid output"):
            invalid.select(
                mock.sentinel.request,
                mock.sentinel.evidence,
                cancellation=threading.Event(),
            )
        self.assertTrue(evidence.invalid_output_after_service_call)
        evidence.deadline_after_service_call = True
        evidence.stale_generation_reauthorization = True
        evidence.record_synchronized_service_call()
        evidence.require_complete(expected_synchronized_service_calls=1)
        with self.assertRaisesRegex(RuntimeError, "evidence is incomplete"):
            evidence.require_complete(expected_synchronized_service_calls=2)

    def test_stale_generation_reader_fails_closed_and_restores_successor(self) -> None:
        evidence = gate._ControlledModeEvidence()
        delegate = mock.Mock()
        reader = gate._StaleGenerationReader(
            delegate,
            mock.Mock(),
            tenant_id="coordinator-q-1234",
            predecessor_sha256="1" * 64,
            successor_sha256="2" * 64,
            evidence=evidence,
        )
        reader._activate = mock.Mock()

        delegate.read.return_value = mock.sentinel.evidence
        with self.assertRaisesRegex(RuntimeError, "remained admissible"):
            reader.read(
                mock.sentinel.request,
                principal=mock.sentinel.principal,
                cancellation=threading.Event(),
            )
        reader._activate.assert_has_calls([mock.call("1" * 64), mock.call("2" * 64)])
        self.assertFalse(evidence.stale_generation_reauthorization)

        reader._activate.reset_mock()
        delegate.read.side_effect = gate.KnowledgeGenerationStale("stale")
        with self.assertRaises(gate.KnowledgeGenerationStale):
            reader.read(
                mock.sentinel.request,
                principal=mock.sentinel.principal,
                cancellation=threading.Event(),
            )
        reader._activate.assert_has_calls([mock.call("1" * 64), mock.call("2" * 64)])
        self.assertTrue(evidence.stale_generation_reauthorization)

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
                return _Started("a" * 64, 10, "postgresql://private-initial")

            def restart(self, *, timeout_seconds):
                del timeout_seconds
                self.restart_count += 1
                events.append(f"database-restarted-{self.restart_count}")
                return _Started(
                    "a" * 64,
                    10 + self.restart_count,
                    f"postgresql://private-restarted-{self.restart_count}",
                )

            def stop(self, *, timeout_seconds):
                del timeout_seconds
                events.append("database-stopped")
                return {name: True for name in gate._TEARDOWN_KEYS}

            def contain_failed_run(self):
                events.append("database-contained")
                return {}

        acceptance = mock.Mock(
            plan_sha256="2" * 64,
            maximum_normal_p95_milliseconds=85_000,
            owner_count=8,
            owners_per_synchronized_wave=8,
            synchronized_invocation_count=24,
        )
        corpus = mock.Mock(corpus_sha256="3" * 64)
        initialized = mock.Mock()
        bound = mock.Mock()
        result = mock.Mock(
            public_evidence={"schemaVersion": 2, "qualified": True},
            observations=(),
        )
        profile = mock.Mock(
            candidate_id="gemma",
            expected_model="model",
            model_revision="4" * 40,
            runtime_id="runtime",
            candidate_lock_sha256="4" * 64,
            profile_sha256="5" * 64,
            maximum_sequences=8,
            batch_invariant=True,
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
                "--no-enable-prefix-caching",
            ),
        )
        runtime = mock.Mock(maximum_output_tokens=512, maximum_input_tokens=7_680)
        controlled = mock.Mock(synchronized_service_calls=24)
        database_state = {
            "successorGenerationActive": True,
            "twoGenerationsRetainedExact": True,
            "twoSourceAdmissionsRetainedExact": True,
            "staleControlActivationHistoryExact": True,
            "curatorProposalRowsExact": True,
            "curatorResultAuditExact": True,
            "coordinatorResultAuditExact": True,
            "knowledgeToolAuditExact": True,
            "auditCardinalityExact": True,
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
                    "load_coordinator_qualification_acceptance",
                    return_value=acceptance,
                ),
                mock.patch.object(
                    gate,
                    "load_coordinator_qualification_corpus",
                    return_value=corpus,
                ),
                mock.patch.object(
                    gate,
                    "load_coordinator_service_profile",
                    return_value=profile,
                ),
                mock.patch.object(
                    gate,
                    "build_checked_admission_broker",
                    return_value="6" * 64,
                ),
                mock.patch.object(
                    gate, "read_service_state", side_effect=observe_provider
                ),
                mock.patch.object(gate, "validate_state_identity"),
                mock.patch.object(gate, "probe_exact_service"),
                mock.patch.object(
                    gate,
                    "observe_admission_broker",
                    side_effect=observe_broker,
                ),
                mock.patch.object(
                    gate,
                    "probe_agent_admission_broker_capacity",
                    return_value=capacity,
                ),
                mock.patch.object(
                    gate,
                    "load_knowledge_database_runtime_lock",
                    return_value=mock.Mock(lock_sha256="7" * 64),
                ),
                mock.patch.object(gate, "OwnedPostgresKnowledgeRuntime", Database),
                mock.patch.object(
                    gate,
                    "_initialize_coordinator_knowledge",
                    return_value=initialized,
                ),
                mock.patch.object(gate, "_verify_initialized_knowledge"),
                mock.patch.object(
                    gate,
                    "_publish_curator_proposals",
                    return_value={"proposal": "request"},
                ),
                mock.patch.object(
                    gate,
                    "bind_coordinator_curator_lineage",
                    return_value=bound,
                ),
                mock.patch.object(gate, "_build_runtime", return_value=runtime),
                mock.patch.object(
                    gate,
                    "_build_coordinator_executor",
                    return_value=(object(), controlled),
                ),
                mock.patch.object(
                    gate,
                    "evaluate_coordinator_qualification",
                    return_value=result,
                ),
                mock.patch.object(
                    gate,
                    "_persistence_snapshot",
                    return_value=(("same",),),
                ),
                mock.patch.object(
                    gate,
                    "_verify_coordinator_database_state",
                    return_value=database_state,
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
                receipt = gate.run_coordinator_qualification_gate(
                    repository_root=REPOSITORY_ROOT,
                    checked_head="a" * 40,
                    evidence_destination=evidence_path,
                    admission_socket_path=root / "admission.sock",
                    rapid_state_path=root / "rapid-state.json",
                    complex_state_path=root / "complex-state.json",
                )

            controlled.require_complete.assert_called_once_with(
                expected_synchronized_service_calls=24
            )
            self.assertEqual(events.count("provider-observed"), 2)
            self.assertEqual(events.count("broker-observed"), 2)
            self.assertEqual(
                receipt["outcome"],
                "coordinator-proposal-bundle-selection-qualified",
            )
            self.assertEqual(receipt["workload"]["brokerActiveCapacity"], 8)
            self.assertTrue(receipt["workload"]["ninthOwnerQueued"])
            self.assertTrue(receipt["knowledge"]["resultRestartReadBackObserved"])
            serialized = str(receipt)
            self.assertNotIn("private-restarted", serialized)
            self.assertNotIn("coordinator-q-", serialized)
            body = evidence_path.read_bytes()
            self.assertEqual(hashlib.sha256(body).digest_size, 32)
            self.assertIn(b"private-coordinator-qualification", body)


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


class _Started:
    def __init__(self, container_id: str, process_id: int, dsn: str) -> None:
        self.container_id = container_id
        self.process_id = process_id
        self.dsn = dsn


if __name__ == "__main__":
    unittest.main()
