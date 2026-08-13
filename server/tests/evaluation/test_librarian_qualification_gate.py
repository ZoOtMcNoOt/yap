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

from yap_server.agents import (
    AgentAdmission,
    AgentAdmissionClient,
    ExecutionRoute,
)
from yap_server.evaluation import librarian_qualification_gate as gate
from yap_server.knowledge.okf_compiler import compile_okf_bundle


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


class LibrarianQualificationGateTests(unittest.TestCase):
    def test_candidate_inputs_cover_librarian_storage_and_server_io_broker(
        self,
    ) -> None:
        relative = {
            path.relative_to(REPOSITORY_ROOT).as_posix()
            for path in gate._candidate_input_paths(REPOSITORY_ROOT)
        }
        self.assertTrue(
            {
                "server/librarian-acceptance.json",
                "server/librarian-workload-fixtures.json",
                "server/src/yap_server/agents/librarian.py",
                "server/src/yap_server/agents/librarian_result_audit.py",
                "server/src/yap_server/agents/librarian_service.py",
                "server/src/yap_server/evaluation/librarian_qualification.py",
                "server/src/yap_server/evaluation/librarian_qualification_gate.py",
                "server/src/yap_server/evaluation/owned_postgres_knowledge_runtime.py",
                "server/src/yap_server/knowledge/governed_knowledge_tools.py",
                "server/src/yap_server/knowledge/postgres_knowledge_retrieval.py",
                "server/orchestrator/src/agent_admission.rs",
                "server/orchestrator/src/agent_admission_config.rs",
                "server/orchestrator/src/bin/yap-agent-admission-broker.rs",
                "server/tests/agents/test_librarian_postgres.py",
                "server/tests/evaluation/test_librarian_qualification.py",
                "server/tests/evaluation/test_librarian_qualification_gate.py",
            }.issubset(relative)
        )

    def test_server_io_capacity_holds_one_queues_second_and_acknowledges(
        self,
    ) -> None:
        client = _CapacityClient()

        evidence = gate._probe_server_io_capacity(
            client,
            tenant_id="librarian-q-1234567890abcdef",
            run_scope="run-1234567890abcdef",
            observe_broker_state=lambda: {"processId": 41, "binarySha256": "1" * 64},
        )

        self.assertEqual(evidence["admittedOwnerCount"], 1)
        self.assertTrue(evidence["expectedCapacityObserved"])
        self.assertTrue(evidence["overflowOwnerQueued"])
        self.assertTrue(evidence["queuedCancellationCompleted"])
        self.assertTrue(evidence["activeCancellationRequested"])
        self.assertTrue(evidence["activeCancellationAcknowledged"])
        self.assertTrue(evidence["contained"])
        self.assertEqual(
            client.events,
            ["submit-admitted", "submit-queued", "cancel-queued", "cancel-active", "ack-active"],
        )

    def test_server_io_over_admission_is_contained_before_failure(self) -> None:
        client = _OverCapacityClient()

        with self.assertRaisesRegex(RuntimeError, "Server-IO capacity differs"):
            gate._probe_server_io_capacity(
                client,
                tenant_id="librarian-q-1234567890abcdef",
                run_scope="run-1234567890abcdef",
                observe_broker_state=lambda: {"processId": 41},
            )

        self.assertEqual(
            client.events,
            [
                "submit-admitted",
                "submit-admitted",
                "cancel-active",
                "ack-active",
                "cancel-active",
                "ack-active",
            ],
        )

    def test_compiler_binding_rejects_source_revision_and_permission_drift(
        self,
    ) -> None:
        corpus = gate.load_librarian_qualification_corpus(
            REPOSITORY_ROOT / "server/librarian-workload-fixtures.json"
        )
        rendered = gate.render_librarian_qualification_generations(
            corpus,
            tenant_id="librarian-q-1234567890abcdef",
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
        bound = gate.bind_librarian_compiled_corpus(corpus, rendered, compiled)
        self.assertEqual(set(bound.generation_sha256s), {"predecessor", "successor"})

        changed_revision = dict(compiled)
        changed_revision["successor"] = replace(
            changed_revision["successor"],
            source_revision="changed-source-revision",
        )
        with self.assertRaisesRegex(ValueError, "source revision"):
            gate.bind_librarian_compiled_corpus(
                corpus,
                rendered,
                changed_revision,
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
            gate.bind_librarian_compiled_corpus(
                corpus,
                rendered,
                changed_permission,
            )

    def test_rendered_files_are_exact_lf_create_once_inputs(self) -> None:
        generation = mock.Mock(
            files=(
                mock.Mock(relative_path="index.md", body=b"body\n"),
                mock.Mock(relative_path="permissions/rule.yml", body=b"rule\n"),
            )
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            gate._write_rendered_generation(root, generation)
            self.assertEqual((root / "index.md").read_bytes(), b"body\n")
            with self.assertRaises(FileExistsError):
                gate._write_rendered_generation(root, generation)
        for path, body in (("../escape", b"body\n"), ("index.md", b"body\r\n")):
            with self.subTest(path=path, body=body):
                with tempfile.TemporaryDirectory() as temporary:
                    with self.assertRaisesRegex(ValueError, "rendered file"):
                        gate._write_rendered_generation(
                            Path(temporary),
                            mock.Mock(files=(mock.Mock(relative_path=path, body=body),)),
                        )

    def test_gate_restarts_twice_tears_down_and_emits_public_safe_receipt(
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
                return _teardown()

            def contain_failed_run(self):
                events.append("database-contained")
                return _teardown()

        acceptance = mock.Mock(
            plan_sha256="2" * 64,
            maximum_p95_milliseconds=16_000,
        )
        corpus = mock.Mock(corpus_sha256="3" * 64)
        initialized = mock.Mock()
        result = mock.Mock(
            public_evidence={"schemaVersion": 1, "qualified": True},
            observations=(),
        )
        profile = mock.Mock(
            candidate_lock_sha256="4" * 64,
            profile_sha256="5" * 64,
        )
        database_state = {
            "successorGenerationActive": True,
            "twoGenerationsRetainedExact": True,
            "twoSourceAdmissionsRetainedExact": True,
            "successorActivationHistoryExact": True,
            "proposalWritesAbsent": True,
            "librarianResultAuditExact": True,
            "knowledgeToolAuditExact": True,
        }
        capacity = {
            "admittedOwnerCount": 1,
            "expectedCapacityObserved": True,
            "overflowOwnerQueued": True,
            "queuedCancellationCompleted": True,
            "activeCancellationRequested": True,
            "activeCancellationAcknowledged": True,
            "contained": True,
            "brokerIdentityUnchanged": True,
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = root / "private" / "receipt.json"

            def initialize(*args, **kwargs):
                del args, kwargs
                events.append("knowledge-initialized")
                return initialized

            def evaluate(*args, **kwargs):
                del args, kwargs
                events.append("qualification-evaluated")
                return result

            def verify(*args, **kwargs):
                del args, kwargs
                events.append("database-verified")
                return database_state

            with ExitStack() as stack:
                patches = (
                    mock.patch.object(
                        gate, "admit_checked_candidate", return_value=Candidate()
                    ),
                    mock.patch.object(gate, "_candidate_input_paths", return_value=()),
                    mock.patch.object(gate, "_require_private_arm64_host"),
                    mock.patch.object(
                        gate,
                        "load_librarian_qualification_acceptance",
                        return_value=acceptance,
                    ),
                    mock.patch.object(
                        gate,
                        "load_librarian_qualification_corpus",
                        return_value=corpus,
                    ),
                    mock.patch.object(
                        gate,
                        "load_rapid_agent_vllm_service_profile",
                        return_value=profile,
                    ),
                    mock.patch.object(
                        gate,
                        "load_complex_agent_vllm_service_profile",
                        return_value=profile,
                    ),
                    mock.patch.object(
                        gate, "build_checked_admission_broker", return_value="6" * 64
                    ),
                    mock.patch.object(
                        gate, "_probe_server_io_capacity", return_value=capacity
                    ),
                    mock.patch.object(
                        gate,
                        "load_knowledge_database_runtime_lock",
                        return_value=mock.Mock(lock_sha256="7" * 64),
                    ),
                    mock.patch.object(gate, "OwnedPostgresKnowledgeRuntime", Database),
                    mock.patch.object(
                        gate, "_initialize_librarian_knowledge", side_effect=initialize
                    ),
                    mock.patch.object(
                        gate, "_build_librarian_executor", return_value=object()
                    ),
                    mock.patch.object(
                        gate, "evaluate_librarian_qualification", side_effect=evaluate
                    ),
                    mock.patch.object(
                        gate, "_verify_librarian_database_state", side_effect=verify
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
                for patcher in patches:
                    stack.enter_context(patcher)
                receipt = gate.run_librarian_qualification_gate(
                    repository_root=REPOSITORY_ROOT,
                    checked_head="a" * 40,
                    evidence_destination=evidence,
                    admission_socket_path=root / "admission.sock",
                    rapid_state_path=root / "rapid-state.json",
                    complex_state_path=root / "complex-state.json",
                )

            self.assertEqual(
                events,
                [
                    "database-started",
                    "knowledge-initialized",
                    "database-restarted-1",
                    "qualification-evaluated",
                    "database-restarted-2",
                    "database-verified",
                    "database-stopped",
                    "candidate-verified",
                ],
            )
            self.assertEqual(
                receipt["outcome"],
                "librarian-permission-safe-evidence-qualified",
            )
            self.assertEqual(receipt["workload"]["brokerActiveCapacity"], 1)
            self.assertTrue(receipt["workload"]["secondOwnerQueued"])
            self.assertTrue(
                receipt["workload"]["librarianModelRouteLeaseRequestsAbsent"]
            )
            serialized = str(receipt)
            self.assertNotIn("private-restarted", serialized)
            self.assertNotIn("librarian-q-", serialized)
            body = evidence.read_bytes()
            self.assertEqual(hashlib.sha256(body).digest_size, 32)
            self.assertIn(b"private-librarian-qualification", body)

    def test_deadline_private_destination_and_credential_fail_closed(self) -> None:
        gate._require_exact_deadline_contract(16_000)
        for value in (15_000, 16_001):
            with self.assertRaisesRegex(ValueError, "deadline contract"):
                gate._require_exact_deadline_contract(value)
        with self.assertRaisesRegex(ValueError, "outside the repository"):
            gate._new_private_evidence_destination(
                REPOSITORY_ROOT / "librarian-private.json",
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

    def test_deadline_reader_waits_for_operation_cancellation(self) -> None:
        delegate = mock.Mock()
        delegate.read.return_value = mock.sentinel.pack
        cancellation = threading.Event()
        cancellation.set()

        result = gate._DeadlineEvidenceReader(delegate).read(
            mock.sentinel.request,
            principal=mock.sentinel.principal,
            cancellation=cancellation,
        )

        self.assertIs(result, mock.sentinel.pack)
        delegate.read.assert_called_once_with(
            mock.sentinel.request,
            principal=mock.sentinel.principal,
            cancellation=cancellation,
        )
        with mock.patch.object(gate, "LIBRARIAN_WORKFLOW_DEADLINE_SECONDS", 0.0):
            with self.assertRaisesRegex(TimeoutError, "deadline did not fire"):
                gate._DeadlineEvidenceReader(delegate).read(
                    mock.sentinel.request,
                    principal=mock.sentinel.principal,
                    cancellation=threading.Event(),
                )


class _CapacityClient(AgentAdmissionClient):
    def __init__(self) -> None:
        self.events: list[str] = []
        self._states: dict[str, str] = {}

    def submit(self, ticket, **kwargs):
        del kwargs
        outcome = "admitted" if not self._states else "queued"
        self._states[ticket.request_id] = outcome
        self.events.append(f"submit-{outcome}")
        if outcome == "admitted":
            return AgentAdmission(
                ticket,
                outcome,
                route=ExecutionRoute.SERVER_IO,
                provider_generation=None,
                queue_duration_ms=0,
            )
        return AgentAdmission(ticket, outcome)

    def cancel(self, ticket):
        state = self._states[ticket.request_id]
        if state == "queued":
            self.events.append("cancel-queued")
            self._states[ticket.request_id] = "cancelled"
            return AgentAdmission(ticket, "cancelled")
        self.events.append("cancel-active")
        self._states[ticket.request_id] = "cancellation-requested"
        return AgentAdmission(
            ticket,
            "cancellation-requested",
            cancellation_reason="client-requested",
        )

    def acknowledge_cancellation(self, ticket):
        self.events.append("ack-active")
        self._states[ticket.request_id] = "cancelled"
        return AgentAdmission(ticket, "cancelled")


class _OverCapacityClient(_CapacityClient):
    def submit(self, ticket, **kwargs):
        del kwargs
        self._states[ticket.request_id] = "admitted"
        self.events.append("submit-admitted")
        return AgentAdmission(
            ticket,
            "admitted",
            route=ExecutionRoute.SERVER_IO,
            provider_generation=None,
            queue_duration_ms=0,
        )


def _teardown() -> dict[str, bool]:
    return {
        "containerAbsent": True,
        "listenerAbsent": True,
        "networkAbsent": True,
        "ownedProcessAbsent": True,
        "sameLabelOwnersAbsent": True,
        "volumeAbsent": True,
    }


if __name__ == "__main__":
    unittest.main()
