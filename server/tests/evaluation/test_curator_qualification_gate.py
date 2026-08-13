from __future__ import annotations

from contextlib import ExitStack
from dataclasses import replace
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from yap_server.agents.curator import CuratorEvidence, CuratorEvidenceItem
from yap_server.agents.curator_service import CuratorJobView
from yap_server.evaluation import curator_qualification_gate as gate
from yap_server.evaluation.curator_qualification import (
    CuratorExpectedEvidence,
    build_curator_qualification_requests,
    load_curator_qualification_corpus,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SERVER_ROOT = REPOSITORY_ROOT / "server"


class CuratorQualificationGateTests(unittest.TestCase):
    def test_candidate_inputs_cover_curator_runtime_storage_and_capacity_broker(
        self,
    ) -> None:
        relative = {
            path.relative_to(REPOSITORY_ROOT).as_posix()
            for path in gate._candidate_input_paths(REPOSITORY_ROOT)
        }
        self.assertTrue(
            {
                "server/curator-acceptance.json",
                "server/curator-workload-fixtures.json",
                "server/src/yap_server/agents/curator.py",
                "server/src/yap_server/agents/curator_model.py",
                "server/src/yap_server/agents/curator_publisher.py",
                "server/src/yap_server/agents/curator_result_audit.py",
                "server/src/yap_server/agents/curator_runtime.py",
                "server/src/yap_server/agents/curator_service.py",
                "server/src/yap_server/evaluation/agent_admission_broker_observation.py",
                "server/src/yap_server/evaluation/curator_qualification.py",
                "server/src/yap_server/evaluation/curator_qualification_gate.py",
                "server/src/yap_server/knowledge/knowledge_proposals.py",
                "server/orchestrator/src/agent_admission.rs",
                "server/orchestrator/src/agent_admission_config.rs",
                "server/orchestrator/src/service_profile.rs",
                "server/orchestrator/tests/agent_admission_contract.rs",
                "server/orchestrator/tests/supervised_service.rs",
                "server/orchestrator/tests/support/mod.rs",
                "server/tests/agents/test_curator_postgres.py",
                "server/tests/evaluation/test_agent_admission_broker_observation.py",
                "server/tests/evaluation/test_curator_qualification.py",
                "server/tests/evaluation/test_curator_qualification_gate.py",
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

    def test_exact_compiled_body_builds_one_source_bound_evidence_item(self) -> None:
        corpus = load_curator_qualification_corpus(
            SERVER_ROOT / "curator-workload-fixtures.json"
        )
        case = corpus.cases[0]
        prefix = "# Release review\n\n"
        concept = mock.Mock(
            concept_id=case.concept_id,
            body=prefix + case.body,
            content_sha256="b" * 64,
        )
        chunk = mock.Mock(
            concept_id=case.concept_id,
            char_start=len(prefix),
            char_end=len(prefix) + len(case.body),
            text=case.body,
        )
        generation = mock.Mock(
            concepts=(concept,),
            chunks=(chunk,),
            source_revision="a" * 64,
        )
        one_case = replace(corpus, cases=(case,))

        expected = gate._expected_curator_evidence(generation, one_case)

        self.assertEqual(expected[case.case_id][0].text, case.body)
        self.assertEqual(expected[case.case_id][0].char_start, len(prefix))

    def test_preflight_rejects_any_preexisting_curator_tenant_state(self) -> None:
        gate._assert_empty_curator_state(
            _CountConnection([(0,)] * 6),
            tenant_id="curator-q-12345678",
        )
        with self.assertRaisesRegex(RuntimeError, "tenant is not fresh"):
            gate._assert_empty_curator_state(
                _CountConnection([(0,), (0,), (0,), (1,), (0,), (0,)]),
                tenant_id="curator-q-12345678",
            )

    def test_gate_restarts_twice_tears_down_and_emits_public_safe_receipt(self) -> None:
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

        corpus = load_curator_qualification_corpus(
            SERVER_ROOT / "curator-workload-fixtures.json"
        )
        generation = mock.Mock(
            generation_sha256="5" * 64,
            source_revision=corpus.corpus_sha256,
        )
        expected = {
            case.case_id: (
                CuratorExpectedEvidence(
                    case.concept_id,
                    corpus.corpus_sha256,
                    "6" * 64,
                    7,
                    7 + len(case.body),
                    case.body,
                ),
            )
            for case in corpus.cases
        }
        requests = build_curator_qualification_requests(
            corpus,
            qualification_run_id="run-2222222222222222",
            generation_sha256=generation.generation_sha256,
            expected_evidence=expected,
        )
        packs = {
            case.case_id: CuratorEvidence.create(
                generation_sha256=generation.generation_sha256,
                permission_hash="7" * 64,
                authorization_hash="8" * 64,
                items=(
                    CuratorEvidenceItem(
                        expected[case.case_id][0].citation,
                        case.body,
                    ),
                ),
            )
            for case in corpus.cases
        }
        acceptance = mock.Mock(
            maximum_output_tokens=512,
            maximum_input_tokens=7_680,
            broker_active_capacity=8,
        )
        profile = mock.Mock(
            candidate_id="gemma-4-31b-it-nvfp4",
            expected_model="nvidia/Gemma-4-31B-IT-NVFP4",
            model_revision="4" * 40,
            runtime_id="gemma-vllm-26.06",
            candidate_lock_sha256="3" * 64,
            profile_sha256="4" * 64,
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
        cross_request = replace(
            requests[corpus.cases[0].case_id],
            submission_id="run-2222222222222222-cross-owner",
        )
        cross_view = CuratorJobView(
            "cross-request",
            cross_request.submission_id,
            "failed",
            generation.generation_sha256,
            reason="evidence-unavailable",
        )
        result = mock.Mock(
            public_evidence={
                "schemaVersion": 1,
                "qualificationScope": "curator-knowledge-proposals",
                "outcome": "curator-knowledge-proposals-qualified",
                "evidenceSha256": "9" * 64,
            },
            private_evidence={
                "schemaVersion": 1,
                "evidenceSha256": "9" * 64,
                "cases": [{"reviewedContent": "private reviewed content"}],
            },
        )
        database_state = {
            "activeGenerationUnchanged": True,
            "singleGenerationRetained": True,
            "singleSourceAdmissionRetained": True,
            "proposalRowsExact": True,
            "genericReadAndProposeAuditsExact": True,
            "curatorResultAuditIdentitiesExact": True,
            "rejectedProposalAndSuccessRowsAbsent": True,
        }
        replay = {
            "exactStoredReplayObserved": True,
            "conflictingReplayRejected": True,
            "crossOwnerEvidenceRejected": True,
            "crossOwnerStoredResultHidden": True,
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

        with tempfile.TemporaryDirectory() as temporary:
            evidence_path = Path(temporary) / "private" / "receipt.json"
            patches = (
                mock.patch.object(gate.secrets, "token_hex", side_effect=["1" * 16, "2" * 16]),
                mock.patch.object(gate, "admit_checked_candidate", return_value=Candidate()),
                mock.patch.object(gate, "_candidate_input_paths", return_value=()),
                mock.patch.object(gate, "_require_private_arm64_host"),
                mock.patch.object(gate, "load_curator_qualification_acceptance", return_value=acceptance),
                mock.patch.object(gate, "load_curator_qualification_corpus", return_value=corpus),
                mock.patch.object(gate, "load_curator_service_profile", return_value=profile),
                mock.patch.object(gate, "build_checked_admission_broker", return_value="a" * 64),
                mock.patch.object(
                    gate,
                    "probe_agent_admission_broker_capacity",
                    return_value=capacity,
                ),
                mock.patch.object(gate, "load_knowledge_database_runtime_lock", return_value=mock.Mock(lock_sha256="b" * 64)),
                mock.patch.object(gate, "OwnedPostgresKnowledgeRuntime", Database),
                mock.patch.object(gate, "_initialize_curator_knowledge", return_value=generation),
                mock.patch.object(gate, "_expected_curator_evidence", return_value=expected),
                mock.patch.object(gate, "_read_back_compiled_evidence", return_value=(requests, packs)),
                mock.patch.object(gate, "_build_runtime", return_value=runtime),
                mock.patch.object(gate, "_run_cross_owner_hidden", return_value=(cross_request, cross_view)),
                mock.patch.object(gate, "evaluate_curator_qualification", return_value=result),
                mock.patch.object(gate, "_curator_persistence_snapshot", return_value=((1,), (2,), (3,))),
                mock.patch.object(gate, "_verify_replay_conflict_and_owner_isolation", return_value=replay),
                mock.patch.object(gate, "_verify_curator_database_state", return_value=database_state),
                mock.patch.object(
                    gate,
                    "bind_checked_candidate_evidence",
                    side_effect=lambda value, candidate: {
                        **value,
                        "candidate": candidate.input_sha256,
                        "evidenceSha256": "c" * 64,
                    },
                ),
            )
            with ExitStack() as stack:
                for patcher in patches:
                    stack.enter_context(patcher)
                receipt = gate.run_curator_qualification_gate(
                    repository_root=REPOSITORY_ROOT,
                    checked_head="d" * 40,
                    evidence_destination=evidence_path,
                    admission_socket_path=Path(temporary) / "admission.sock",
                    rapid_state_path=Path(temporary) / "rapid.json",
                    complex_state_path=Path(temporary) / "complex.json",
                )

            self.assertEqual(
                events,
                [
                    "database-started",
                    "database-restarted-1",
                    "database-restarted-2",
                    "database-stopped",
                    "candidate-verified",
                ],
            )
            self.assertEqual(receipt["workload"]["maximumInputTokens"], 7_680)
            self.assertEqual(receipt["workload"]["brokerActiveCapacity"], 8)
            self.assertTrue(receipt["knowledge"]["resultRestartReadBackObserved"])
            serialized = str(receipt)
            self.assertNotIn("curator-q-", serialized)
            self.assertNotIn("run-2222222222222222", serialized)
            self.assertNotIn("private reviewed content", serialized)
            self.assertNotIn("postgresql://", serialized)
            self.assertIn(b"private reviewed content", evidence_path.read_bytes())

    def test_private_destination_and_credential_are_create_once(self) -> None:
        with self.assertRaisesRegex(ValueError, "outside the repository"):
            gate._new_private_evidence_destination(
                REPOSITORY_ROOT / "curator-private.json",
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


class _CountConnection:
    def __init__(self, rows: list[tuple[int]]) -> None:
        self.rows = iter(rows)

    def execute(self, query, parameters):
        del query, parameters
        return self

    def fetchone(self):
        return next(self.rows)

if __name__ == "__main__":
    unittest.main()
