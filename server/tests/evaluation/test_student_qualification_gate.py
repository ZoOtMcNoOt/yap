from __future__ import annotations

import hashlib
import os
from contextlib import ExitStack
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from yap_server.evaluation import student_qualification_gate as gate


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


class StudentQualificationGateTests(unittest.TestCase):
    def test_candidate_inputs_cover_student_runtime_storage_and_broker(self) -> None:
        relative = {
            path.relative_to(REPOSITORY_ROOT).as_posix()
            for path in gate._candidate_input_paths(REPOSITORY_ROOT)
        }
        self.assertTrue(
            {
                "server/student-acceptance.json",
                "server/student-workload-fixtures.json",
                "server/src/yap_server/agents/student.py",
                "server/src/yap_server/agents/student_model.py",
                "server/src/yap_server/agents/student_runtime.py",
                "server/src/yap_server/agents/student_result_audit.py",
                "server/src/yap_server/agents/student_service.py",
                "server/src/yap_server/evaluation/agent_admission_broker_observation.py",
                "server/src/yap_server/evaluation/student_qualification.py",
                "server/src/yap_server/evaluation/student_qualification_gate.py",
                "server/src/yap_server/knowledge/generation_ledger.py",
                "server/src/yap_server/knowledge/postgres_knowledge_retrieval.py",
                "server/orchestrator/src/agent_admission.rs",
                "server/orchestrator/src/agent_admission_config.rs",
                "server/orchestrator/src/bin/yap-agent-admission-broker.rs",
                "server/orchestrator/src/service_profile.rs",
                "server/orchestrator/tests/supervised_service.rs",
                "server/orchestrator/tests/support/mod.rs",
                "server/tests/agents/test_student_postgres.py",
                "server/tests/evaluation/test_student_qualification.py",
                "server/tests/evaluation/test_student_qualification_gate.py",
            }.issubset(relative)
        )

    def test_full_rapid_profile_cannot_be_throttled(self) -> None:
        exact = (
            "vllm",
            "serve",
            "model",
            "--gpu-memory-utilization",
            "0.40",
            "--max-num-seqs",
            "4",
            "--max-num-batched-tokens",
            "8192",
        )
        gate._require_full_rapid_profile(4, exact)
        for sequences, arguments in (
            (3, exact),
            (4, tuple("0.30" if item == "0.40" else item for item in exact)),
            (4, tuple("2" if item == "4" else item for item in exact)),
        ):
            with self.subTest(sequences=sequences, arguments=arguments):
                with self.assertRaisesRegex(ValueError, "full rapid profile"):
                    gate._require_full_rapid_profile(sequences, arguments)

    def test_multi_chunk_evidence_read_audit_uses_exact_item_count(self) -> None:
        corpus = gate.load_student_qualification_corpus(
            REPOSITORY_ROOT / "server/student-workload-fixtures.json"
        )
        expected = {
            case.case_id: tuple(
                mock.Mock(spec=gate.StudentExpectedEvidence)
                for _ in (
                    range(2)
                    if case.case_id in {"instruction-is-data", "librarian-boundary"}
                    else range(1)
                )
            )
            for case in corpus.cases
        }

        audits = gate._expected_evidence_read_audits(corpus, expected)

        self.assertIn(
            ("owner-06", "conversation-evidence", "succeeded", 2),
            audits,
        )
        self.assertIn(
            ("owner-08", "conversation-evidence", "succeeded", 2),
            audits,
        )

    def test_qualification_documents_bind_the_explicit_fresh_tenant(self) -> None:
        corpus = gate.load_student_qualification_corpus(
            REPOSITORY_ROOT / "server/student-workload-fixtures.json"
        )
        case = corpus.cases[0]
        tenant_id = "student-product-fresh-tenant"

        concept = gate._concept_document(
            case,
            corpus.corpus_sha256,
            tenant_id=tenant_id,
        )
        permission = gate._permission_document(
            case.case_id,
            case.owner_id,
            tenant_id=tenant_id,
        )

        self.assertIn(f"yap://tenant/{tenant_id}/meeting/{case.case_id}", concept)
        self.assertIn(f"tenant_id: {tenant_id}", permission)
        self.assertNotIn(gate._TENANT_ID, concept + permission)

    def test_gate_restarts_database_tears_down_and_keeps_public_safe(self) -> None:
        events: list[str] = []

        class Candidate:
            input_sha256 = {"server/input": "1" * 64}

            def verify_unchanged(self, *, runner) -> None:
                del runner
                events.append("candidate-verified")

        class Database:
            def __init__(self, **kwargs) -> None:
                del kwargs

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
                events.append("database-restarted")
                return mock.Mock(
                    container_id="a" * 64,
                    process_id=11,
                    dsn="postgresql://private-restarted",
                )

            def stop(self, *, timeout_seconds):
                del timeout_seconds
                events.append("database-stopped")
                return {
                    "containerAbsent": True,
                    "listenerAbsent": True,
                    "networkAbsent": True,
                    "ownedProcessAbsent": True,
                    "sameLabelOwnersAbsent": True,
                    "volumeAbsent": True,
                }

            def contain_failed_run(self):
                events.append("database-contained")
                return {}

        result = mock.Mock(
            public_evidence={
                "schemaVersion": 3,
                "qualificationScope": "student-learning-questions",
                "outcome": "student-learning-questions-qualified",
                "evidenceSha256": "2" * 64,
            },
            private_evidence={
                "schemaVersion": 3,
                "evidenceSha256": "2" * 64,
                "cases": [{"questions": ["private question"]}],
            },
        )
        profile = mock.Mock(
            expected_model="nvidia/Qwen3.6-35B-A3B-NVFP4",
            candidate_lock_sha256="3" * 64,
            profile_sha256="4" * 64,
            maximum_sequences=4,
            launch_arguments=(
                "vllm",
                "serve",
                "model",
                "--gpu-memory-utilization",
                "0.40",
                "--max-num-seqs",
                "4",
                "--max-num-batched-tokens",
                "8192",
            ),
        )
        runtime = mock.Mock(maximum_output_tokens=512, service=object())
        generation = mock.Mock(generation_sha256="5" * 64)
        database_state = {
            "activeGenerationUnchanged": True,
            "singleGenerationRetained": True,
            "singleSourceAdmissionRetained": True,
            "proposalWritesAbsent": True,
            "evidenceReadAuditExact": True,
            "terminalOutcomeAuditExact": True,
            "workflowIdentityAuditExact": True,
        }
        capacity = {
            "admittedOwnerCount": 4,
            "expectedCapacityObserved": True,
            "expectedRouteObserved": True,
            "overflowOwnerQueued": True,
            "contained": True,
            "providerIdentityUnchanged": True,
            "brokerIdentityUnchanged": True,
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = root / "private" / "receipt.json"
            with ExitStack() as stack:
                patches = (
                    mock.patch.object(
                        gate, "admit_checked_candidate", return_value=Candidate()
                    ),
                    mock.patch.object(gate, "_candidate_input_paths", return_value=()),
                    mock.patch.object(gate, "_require_private_arm64_host"),
                    mock.patch.object(
                        gate,
                        "load_student_qualification_acceptance",
                        return_value=object(),
                    ),
                    mock.patch.object(
                        gate,
                        "load_student_qualification_corpus",
                        return_value=mock.Mock(cases=(mock.Mock(),)),
                    ),
                    mock.patch.object(
                        gate, "load_student_service_profile", return_value=profile
                    ),
                    mock.patch.object(
                        gate, "build_checked_admission_broker", return_value="6" * 64
                    ),
                    mock.patch.object(gate, "read_service_state", return_value={}),
                    mock.patch.object(gate, "validate_state_identity"),
                    mock.patch.object(gate, "probe_exact_service"),
                    mock.patch.object(
                        gate, "observe_admission_broker", return_value={}
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
                        gate, "_initialize_student_knowledge", return_value=generation
                    ),
                    mock.patch.object(
                        gate, "_expected_student_evidence", return_value={}
                    ),
                    mock.patch.object(
                        gate, "build_student_runtime", return_value=runtime
                    ),
                    mock.patch.object(
                        gate,
                        "_run_cross_owner_hidden",
                        return_value=mock.Mock(
                            status="evidence-unavailable",
                            reason="evidence-unavailable",
                            questions=(),
                        ),
                    ),
                    mock.patch.object(
                        gate, "evaluate_student_qualification", return_value=result
                    ),
                    mock.patch.object(
                        gate,
                        "_verify_student_database_state",
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
                for patcher in patches:
                    stack.enter_context(patcher)
                receipt = gate.run_student_qualification_gate(
                    repository_root=REPOSITORY_ROOT,
                    checked_head="a" * 40,
                    evidence_destination=evidence,
                    admission_socket_path=root / "admission.sock",
                    rapid_state_path=root / "rapid-state.json",
                )
            self.assertEqual(
                events,
                [
                    "database-started",
                    "database-restarted",
                    "database-stopped",
                    "candidate-verified",
                ],
            )
            self.assertEqual(receipt["workload"]["maximumOutputTokens"], 512)
            self.assertEqual(receipt["workload"]["brokerActiveCapacity"], 4)
            self.assertTrue(receipt["workload"]["fifthOwnerQueued"])
            self.assertTrue(receipt["workload"]["capacityProbeContained"])
            self.assertEqual(receipt["workload"]["gpuMemoryUtilization"], "0.40")
            self.assertNotIn("private-restarted", str(receipt))
            self.assertNotIn("private question", str(receipt))
            body = evidence.read_bytes()
            self.assertEqual(hashlib.sha256(body).digest_size, 32)
            self.assertIn(b"private question", body)

    def test_private_destination_and_credential_are_create_once(self) -> None:
        with self.assertRaisesRegex(ValueError, "outside the repository"):
            gate._new_private_evidence_destination(
                REPOSITORY_ROOT / "student-private.json",
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


if __name__ == "__main__":
    unittest.main()
