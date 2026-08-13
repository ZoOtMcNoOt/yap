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

from yap_server.evaluation import auditor_qualification_gate as gate
from yap_server.knowledge.okf_compiler import compile_okf_bundle
from yap_server.knowledge.knowledge_tool_contract import KnowledgeToolCancelled


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


class AuditorQualificationGateTests(unittest.TestCase):
    def test_candidate_inputs_cover_the_full_auditor_stack_and_oracle(self) -> None:
        relative = {
            path.relative_to(REPOSITORY_ROOT).as_posix()
            for path in gate._candidate_input_paths(REPOSITORY_ROOT)
        }
        required = {
            "server/auditor-acceptance.json",
            "server/auditor-workload-fixtures.json",
            "server/src/yap_server/agents/auditor.py",
            "server/src/yap_server/agents/auditor_model.py",
            "server/src/yap_server/agents/auditor_result_audit.py",
            "server/src/yap_server/agents/auditor_runtime.py",
            "server/src/yap_server/agents/auditor_service.py",
            "server/src/yap_server/evaluation/agent_admission_broker_observation.py",
            "server/src/yap_server/evaluation/agent_service_lifecycle_observation.py",
            "server/src/yap_server/evaluation/auditor_qualification.py",
            "server/src/yap_server/evaluation/auditor_qualification_gate.py",
            "server/src/yap_server/evaluation/librarian_qualification.py",
            "server/src/yap_server/evaluation/provider_runtime_observations.py",
            "server/src/yap_server/knowledge/agent_reasoning_routes.py",
            "server/src/yap_server/knowledge/vllm_reasoning_client.py",
            "server/orchestrator/src/agent_admission.rs",
            "server/orchestrator/src/bin/yap-agent-admission-broker.rs",
            "server/tests/agents/test_auditor_model.py",
            "server/tests/agents/test_auditor_runtime.py",
            "server/tests/agents/test_auditor_service.py",
            "server/tests/evaluation/test_auditor_qualification.py",
            "server/tests/evaluation/test_provider_runtime_observations.py",
        }
        self.assertTrue(required.issubset(relative))
        self.assertTrue(
            {
                path.relative_to(REPOSITORY_ROOT).as_posix()
                for path in (REPOSITORY_ROOT / "server/src/yap_server").glob("**/*.py")
            }.issubset(relative)
        )
        self.assertTrue(
            {
                path.relative_to(REPOSITORY_ROOT).as_posix()
                for root in (
                    REPOSITORY_ROOT / "server/orchestrator/src",
                    REPOSITORY_ROOT / "server/orchestrator/tests",
                )
                for path in root.glob("**/*.rs")
            }.issubset(relative)
        )

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
                        sequences, batch_invariant, arguments
                    )

    def test_idle_only_probe_observes_active_and_pending_non_idle_exclusion(
        self,
    ) -> None:
        client = _IdleOnlyProbeClient()
        provider = {"processGeneration": 7}
        broker = {"processId": 41}

        evidence = gate._probe_idle_only_admission(
            client,  # type: ignore[arg-type]
            tenant_id="auditor-q-1234567890abcdef",
            run_scope="run-1234567890abcdef",
            observe_provider_state=lambda: provider,
            observe_broker_state=lambda: broker,
        )

        self.assertEqual(
            evidence,
            {
                "nonIdleActiveBlocksIdleOnlyObserved": True,
                "nonIdlePendingBlocksIdleOnlyObserved": True,
                "idleOnlyAdmissionResumesAfterNonIdleTerminal": True,
                "idleOnlyProbeContained": True,
                "idleOnlyProbeProviderIdentityUnchanged": True,
                "idleOnlyProbeBrokerIdentityUnchanged": True,
            },
        )
        self.assertEqual(
            tuple(client.status(ticket).outcome for ticket in client.tickets),
            ("completed", "cancelled", "completed", "cancelled", "cancelled"),
        )

    def test_workload_admission_lifecycle_proves_one_idle_lease_per_call(
        self,
    ) -> None:
        delegate = _LifecycleClient()
        observed = gate._ObservedAuditorAdmission(delegate)  # type: ignore[arg-type]
        modes = ["normal"] * 24 + [
            "client-cancelled",
            "deadline",
            "invalid-output",
            "stale-generation",
            "pre-cancelled",
        ]
        invocation_modes: dict[str, str] = {}
        work = gate.AgentWorkSpec(
            role=gate.AgentRole.AUDITOR,
            purpose=gate.AgentPurpose.KNOWLEDGE_AUDIT,
            route=gate.ExecutionRoute.COMPLEX_ORCHESTRATION,
            scheduling_class=gate.SchedulingClass.IDLE_ONLY,
        )
        for index, mode in enumerate(modes):
            ticket = observed.new_ticket()
            delegate.modes[ticket.request_id] = mode
            invocation_modes[ticket.request_id] = mode
            if mode == "pre-cancelled":
                continue
            admission = observed.submit(
                ticket,
                principal=gate._probe_principal("tenant", f"owner-{index}"),
                work=work,
                source_sha256=f"{index:064x}",
                remaining_deadline_ms=60_000,
            )
            self.assertEqual(admission.outcome, "admitted")
            if mode in {"client-cancelled", "deadline"}:
                self.assertEqual(
                    observed.cancel(ticket).outcome, "cancellation-requested"
                )
                observed.acknowledge_cancellation(ticket)
            else:
                observed.complete(ticket)

        evidence = observed.require_exact_lifecycle(invocation_modes=invocation_modes)

        self.assertEqual(evidence["ticketCount"], 29)
        self.assertEqual(evidence["submittedTicketCount"], 28)
        self.assertEqual(evidence["completedTicketCount"], 26)
        self.assertTrue(evidence["singleLeasePerInvocationExact"])

        observed.new_ticket()
        with self.assertRaisesRegex(RuntimeError, "lifecycle evidence differs"):
            observed.require_exact_lifecycle(invocation_modes=invocation_modes)

    def test_compiler_binding_rejects_source_revision_and_permission_drift(
        self,
    ) -> None:
        corpus = gate.load_auditor_qualification_corpus(
            REPOSITORY_ROOT / "server/auditor-workload-fixtures.json"
        )
        rendered = gate.render_auditor_qualification_generations(
            corpus,
            tenant_id="auditor-q-1234567890abcdef",
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
        source_admissions = {"predecessor": "d" * 64, "successor": "e" * 64}
        bound = gate.bind_auditor_compiled_corpus(
            corpus,
            rendered,
            compiled,
            source_admission_sha256s=source_admissions,
        )
        self.assertEqual(set(bound.generation_sha256s), {"predecessor", "successor"})

        changed_revision = dict(compiled)
        changed_revision["successor"] = replace(
            changed_revision["successor"],
            source_revision="changed-source-revision",
        )
        with self.assertRaisesRegex(ValueError, "source revision"):
            gate.bind_auditor_compiled_corpus(
                corpus,
                rendered,
                changed_revision,
                source_admission_sha256s=source_admissions,
            )

        changed_permission = dict(compiled)
        successor = changed_permission["successor"]
        permissions = list(successor.permissions)
        permissions[0] = replace(permissions[0], permission_sha256="f" * 64)
        changed_permission["successor"] = replace(
            successor,
            permissions=tuple(permissions),
        )
        with self.assertRaisesRegex(ValueError, "permission"):
            gate.bind_auditor_compiled_corpus(
                corpus,
                rendered,
                changed_permission,
                source_admission_sha256s=source_admissions,
            )

    def test_preflight_includes_auditor_audit_and_no_prior_state(self) -> None:
        connection = _CountConnection([(0,)] * 7)
        gate._assert_empty_auditor_state(connection, tenant_id="auditor-q-1234")
        self.assertTrue(
            any("yap_auditor_result_audit" in query for query in connection.queries)
        )
        with self.assertRaisesRegex(RuntimeError, "tenant is not fresh"):
            gate._assert_empty_auditor_state(
                _CountConnection([(0,)] * 6 + [(1,)]),
                tenant_id="auditor-q-1234",
            )

    def test_audit_derivation_rejects_missing_result_identity(self) -> None:
        corpus = gate.load_auditor_qualification_corpus(
            REPOSITORY_ROOT / "server/auditor-workload-fixtures.json"
        )
        acceptance = gate.load_auditor_qualification_acceptance(
            REPOSITORY_ROOT / "server/auditor-acceptance.json"
        )
        rendered = gate.render_auditor_qualification_generations(
            corpus,
            tenant_id="auditor-q-1234567890abcdef",
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
            gate.bind_auditor_compiled_corpus(
                corpus,
                rendered,
                compiled,
                source_admission_sha256s={
                    "predecessor": "d" * 64,
                    "successor": "e" * 64,
                },
            ),
        )
        invocations = gate.build_auditor_qualification_invocations(
            initialized.bound.corpus,
            acceptance,
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
        rows = []
        with self.assertRaisesRegex(RuntimeError, "request audit identity"):
            gate._expected_audit_rows(
                initialized,
                mock.Mock(observations=observations),
                acceptance=acceptance,
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
                model.review(
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
            invalid.review(
                mock.sentinel.request,
                mock.sentinel.evidence,
                cancellation=threading.Event(),
            )
        self.assertTrue(evidence.invalid_output_after_admission)

        stale = gate._StaleGenerationModel()
        self.assertEqual(
            stale.review(
                mock.sentinel.request,
                mock.Mock(items=(mock.sentinel.left, mock.sentinel.right)),
                cancellation=threading.Event(),
            ),
            gate.AuditorDecision("report", ((0, 1),)),
        )
        cancelled = threading.Event()
        cancelled.set()
        with self.assertRaisesRegex(RuntimeError, "evidence is incomplete"):
            stale.review(
                mock.sentinel.request,
                mock.Mock(items=(mock.sentinel.left, mock.sentinel.right)),
                cancellation=cancelled,
            )

    def test_deadline_contract_and_private_create_once_paths(self) -> None:
        gate._require_exact_deadline_contract(85_000)
        for value in (84_999, 85_001):
            with self.assertRaisesRegex(ValueError, "deadline contract"):
                gate._require_exact_deadline_contract(value)
        with self.assertRaisesRegex(ValueError, "outside the repository"):
            gate._new_private_evidence_destination(
                REPOSITORY_ROOT / "auditor-private.json",
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

    def test_stale_control_changes_generation_only_at_success_publication(self) -> None:
        activations: list[str] = []
        delegate = mock.Mock()
        delegate.record.side_effect = gate.KnowledgeGenerationStale("changed")
        evidence = gate._ControlledModeEvidence()

        class Harness(gate._StaleGenerationAuditor):
            def _activate(self, generation_sha256: str) -> None:
                activations.append(generation_sha256)

        auditor = Harness(
            delegate,
            mock.sentinel.connection_factory,
            tenant_id="auditor-q-1234",
            predecessor_sha256="a" * 64,
            successor_sha256="b" * 64,
            evidence=evidence,
        )
        with self.assertRaises(gate.KnowledgeGenerationStale):
            auditor.record(status="complete")
        self.assertEqual(activations, ["a" * 64, "b" * 64])
        self.assertTrue(evidence.stale_generation_reauthorization)
        delegate.record.assert_called_once_with(status="complete")

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

        acceptance = mock.Mock(
            plan_sha256="2" * 64,
            maximum_normal_p95_milliseconds=85_000,
            synchronized_invocation_count=24,
        )
        corpus = mock.Mock(corpus_sha256="3" * 64)
        initialized = mock.Mock()
        result = mock.Mock(
            public_evidence={"schemaVersion": 2, "qualified": True}, observations=()
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
        controlled = mock.Mock()
        observed_admission = mock.Mock()
        observed_admission.require_exact_lifecycle.return_value = {
            "ticketCount": 29,
            "submittedTicketCount": 28,
            "completedTicketCount": 26,
            "cancelledTicketCount": 2,
            "clientCancelledTicketCount": 1,
            "deadlineExpiredTicketCount": 1,
            "preCancelledUnsubmittedTicketCount": 1,
            "singleLeasePerInvocationExact": True,
            "allSubmittedTicketsTerminal": True,
        }
        database_state = {
            "successorGenerationActive": True,
            "twoGenerationsRetainedExact": True,
            "twoSourceAdmissionsRetainedExact": True,
            "successorActivationHistoryExact": True,
            "proposalWritesAbsent": True,
            "auditorResultAuditExact": True,
            "knowledgeToolAuditExact": True,
        }
        idle_only = {
            "nonIdleActiveBlocksIdleOnlyObserved": True,
            "nonIdlePendingBlocksIdleOnlyObserved": True,
            "idleOnlyAdmissionResumesAfterNonIdleTerminal": True,
            "idleOnlyProbeContained": True,
            "idleOnlyProbeProviderIdentityUnchanged": True,
            "idleOnlyProbeBrokerIdentityUnchanged": True,
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
                    "load_auditor_qualification_acceptance",
                    return_value=acceptance,
                ),
                mock.patch.object(
                    gate, "load_auditor_qualification_corpus", return_value=corpus
                ),
                mock.patch.object(
                    gate, "load_auditor_service_profile", return_value=profile
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
                    gate, "_probe_idle_only_admission", return_value=idle_only
                ),
                mock.patch.object(
                    gate,
                    "load_knowledge_database_runtime_lock",
                    return_value=mock.Mock(lock_sha256="7" * 64),
                ),
                mock.patch.object(gate, "OwnedPostgresKnowledgeRuntime", Database),
                mock.patch.object(
                    gate, "_initialize_auditor_knowledge", return_value=initialized
                ),
                mock.patch.object(gate, "_verify_initialized_knowledge"),
                mock.patch.object(
                    gate,
                    "_build_runtime",
                    return_value=(runtime, observed_admission),
                ),
                mock.patch.object(
                    gate, "_build_auditor_executor", return_value=(object(), controlled)
                ),
                mock.patch.object(
                    gate, "evaluate_auditor_qualification", return_value=result
                ),
                mock.patch.object(
                    gate, "_verify_auditor_database_state", return_value=database_state
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
                receipt = gate.run_auditor_qualification_gate(
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
            observed_admission.require_exact_lifecycle.assert_called_once_with(
                invocation_modes={}
            )
            self.assertEqual(events.count("provider-observed"), 2)
            self.assertEqual(events.count("broker-observed"), 2)
            self.assertEqual(
                receipt["outcome"], "auditor-source-cited-review-findings-qualified"
            )
            self.assertEqual(receipt["workload"]["brokerActiveCapacity"], 8)
            self.assertTrue(receipt["workload"]["ninthOwnerQueued"])
            self.assertTrue(receipt["workload"]["nonIdlePendingBlocksIdleOnlyObserved"])
            self.assertTrue(receipt["workload"]["singleLeasePerInvocationExact"])
            self.assertTrue(receipt["knowledge"]["resultRestartReadBackObserved"])
            serialized = str(receipt)
            self.assertNotIn("private-restarted", serialized)
            self.assertNotIn("auditor-q-", serialized)
            body = evidence_path.read_bytes()
            self.assertEqual(hashlib.sha256(body).digest_size, 32)
            self.assertIn(b"private-auditor-qualification", body)


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


class _IdleOnlyProbeClient:
    def __init__(self) -> None:
        self.tickets: list[mock.Mock] = []
        self._terminal: dict[str, str] = {}
        self._submit_outcomes = iter(
            ("admitted", "queued", "admitted", "queued", "queued")
        )

    def new_ticket(self):
        ticket = mock.Mock(request_id=f"probe-{len(self.tickets) + 1}")
        self.tickets.append(ticket)
        return ticket

    def submit(self, ticket, **kwargs):
        del kwargs
        outcome = next(self._submit_outcomes)
        self._terminal[ticket.request_id] = outcome
        return mock.Mock(outcome=outcome)

    def cancel(self, ticket):
        self._terminal[ticket.request_id] = "cancelled"
        return mock.Mock(outcome="cancelled")

    def acknowledge_cancellation(self, ticket):
        self._terminal[ticket.request_id] = "cancelled"
        return mock.Mock(outcome="cancelled")

    def complete(self, ticket):
        self._terminal[ticket.request_id] = "completed"
        return mock.Mock(outcome="completed")

    def status(self, ticket):
        return mock.Mock(outcome=self._terminal.get(ticket.request_id, "not-found"))


class _LifecycleClient:
    def __init__(self) -> None:
        self.count = 0
        self.modes: dict[str, str] = {}
        self.terminal: dict[str, str] = {}

    def new_ticket(self):
        self.count += 1
        return mock.Mock(request_id=f"auditor-request-{self.count}")

    def submit(self, ticket, **kwargs):
        del kwargs
        self.terminal[ticket.request_id] = "admitted"
        return mock.Mock(outcome="admitted", cancellation_reason=None)

    def status(self, ticket):
        return mock.Mock(outcome=self.terminal[ticket.request_id])

    def complete(self, ticket):
        self.terminal[ticket.request_id] = "completed"
        return mock.Mock(outcome="completed", cancellation_reason=None)

    def cancel(self, ticket):
        reason = (
            "deadline-exceeded"
            if self.modes[ticket.request_id] == "deadline"
            else "client-requested"
        )
        return mock.Mock(
            outcome="cancellation-requested",
            cancellation_reason=reason,
        )

    def acknowledge_cancellation(self, ticket):
        outcome = (
            "deadline-exceeded"
            if self.modes[ticket.request_id] == "deadline"
            else "cancelled"
        )
        self.terminal[ticket.request_id] = outcome
        return mock.Mock(outcome=outcome, cancellation_reason=None)


if __name__ == "__main__":
    unittest.main()
