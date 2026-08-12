from __future__ import annotations

import hashlib
import os
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from unittest import mock

from yap_server.evaluation import transcript_correction_qualification_gate as gate


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


class TranscriptCorrectionQualificationGateTests(unittest.TestCase):
    def test_candidate_inputs_cover_runtime_concurrency_and_contract_owners(self) -> None:
        relative = {
            path.relative_to(REPOSITORY_ROOT).as_posix()
            for path in gate._candidate_input_paths(REPOSITORY_ROOT)
        }
        self.assertTrue(
            {
                "server/transcript-correction-acceptance.json",
                "server/fleurs-en-us-test.lock.json",
                "server/fleurs-en-us-cohere-comparator.plan.json",
                "server/src/yap_server/agents/transcript_correction_service.py",
                "server/src/yap_server/evaluation/transcript_correction_corpus.py",
                "server/src/yap_server/evaluation/transcript_correction_source_evidence.py",
                "server/src/yap_server/evaluation/transcript_correction_qualification.py",
                "server/src/yap_server/evaluation/transcript_correction_qualification_gate.py",
                "server/src/yap_server/knowledge/terminology_ledger.py",
                "server/orchestrator/src/agent_admission.rs",
                "server/orchestrator/src/agent_admission/dispatch.rs",
                "server/orchestrator/src/bin/yap-agent-admission-broker.rs",
                "server/tests/evaluation/test_transcript_correction_qualification.py",
                "server/tests/evaluation/test_transcript_correction_qualification_gate.py",
            }.issubset(relative)
        )

    def test_private_runtime_credential_is_create_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "knowledge.dsn"
            gate._write_new_private_text(path, "postgresql://private")
            self.assertEqual(path.read_text(encoding="utf-8"), "postgresql://private\n")
            if os.name == "posix":
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaisesRegex(ValueError, "credential is invalid"):
                gate._write_new_private_text(path, "postgresql://changed")

    def test_private_evidence_destination_rejects_the_repository(self) -> None:
        with self.assertRaisesRegex(ValueError, "outside the repository"):
            gate._new_private_evidence_destination(
                REPOSITORY_ROOT / "scribe-private.json",
                repository_root=REPOSITORY_ROOT,
            )

    @unittest.skipUnless(os.name == "posix", "Unix peer credentials are POSIX-only")
    def test_admission_observation_binds_socket_process_and_binary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            root.chmod(0o700)
            path = root / "admission.sock"
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server.bind(str(path))
            path.chmod(0o600)
            server.listen(1)

            def accept_once() -> None:
                connection, _address = server.accept()
                connection.close()

            thread = threading.Thread(target=accept_once)
            thread.start()
            try:
                expected = gate._process_binary_sha256(os.getpid())
                with mock.patch.object(gate, "_validate_broker_command_line"):
                    observed = gate.observe_admission_broker(
                        path,
                        expected_binary_sha256=expected,
                        expected_candidate_lock_sha256="a" * 64,
                        expected_rapid_profile_sha256="b" * 64,
                        expected_rapid_state_path=root,
                    )
            finally:
                thread.join(timeout=2)
                server.close()
            self.assertFalse(thread.is_alive())
            self.assertEqual(observed["processId"], os.getpid())
            self.assertEqual(observed["binarySha256"], expected)
            self.assertGreater(observed["processStartTicks"], 0)

    def test_gate_closes_services_tears_down_database_and_keeps_public_safe(self) -> None:
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
                return mock.Mock(dsn="postgresql://private-password")

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

        class Runtime:
            service = object()

            def close(self) -> None:
                events.append("service-closed")

        result = mock.Mock(
            public_evidence={
                "schemaVersion": 1,
                "qualificationScope": "scribe-transcript-correction",
                "outcome": "scribe-transcript-correction-qualified",
                "evidenceSha256": "2" * 64,
            },
            private_evidence={
                "schemaVersion": 1,
                "evidenceSha256": "2" * 64,
                "cases": [{"sourceText": "private transcript"}],
            },
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = root / "private" / "receipt.json"
            corpus = mock.Mock(terminology=())
            database_lock = mock.Mock(lock_sha256="3" * 64)
            with (
                mock.patch.object(gate, "admit_checked_candidate", return_value=Candidate()),
                mock.patch.object(gate, "_candidate_input_paths", return_value=()),
                mock.patch.object(gate, "_require_private_arm64_host"),
                mock.patch.object(gate, "load_transcript_correction_acceptance", return_value=object()),
                mock.patch.object(gate, "load_private_transcript_correction_corpus", return_value=corpus),
                mock.patch.object(
                    gate,
                    "load_transcript_correction_service_profile",
                    return_value=mock.Mock(
                        candidate_lock_sha256="6" * 64,
                        profile_sha256="7" * 64,
                    ),
                ),
                mock.patch.object(gate, "_build_admission_broker", return_value="4" * 64),
                mock.patch.object(gate, "read_service_state", return_value={}),
                mock.patch.object(gate, "validate_state_identity"),
                mock.patch.object(gate, "probe_exact_service"),
                mock.patch.object(gate, "observe_admission_broker", return_value={}),
                mock.patch.object(gate, "load_knowledge_database_runtime_lock", return_value=database_lock),
                mock.patch.object(gate, "OwnedPostgresKnowledgeRuntime", Database),
                mock.patch.object(gate, "_initialize_terminology"),
                mock.patch.object(gate, "build_transcript_correction_runtime", return_value=Runtime()),
                mock.patch.object(gate, "evaluate_transcript_correction_qualification", return_value=result),
                mock.patch.object(gate, "_require_no_durable_job_bindings"),
                mock.patch.object(
                    gate,
                    "bind_checked_candidate_evidence",
                    side_effect=lambda value, candidate: {
                        **value,
                        "candidate": candidate.input_sha256,
                        "evidenceSha256": "5" * 64,
                    },
                ),
            ):
                receipt = gate.run_transcript_correction_qualification_gate(
                    repository_root=REPOSITORY_ROOT,
                    checked_head="a" * 40,
                    corpus_path=root / "corpus.json",
                    corpus_sha256="b" * 64,
                    source_evidence_paths=(),
                    evidence_destination=evidence,
                    admission_socket_path=root / "admission.sock",
                    rapid_state_path=root / "rapid-state.json",
                )
            self.assertEqual(
                events,
                [
                    "database-started",
                    "service-closed",
                    "database-stopped",
                    "candidate-verified",
                ],
            )
            self.assertNotIn("private-password", str(receipt))
            self.assertNotIn("private transcript", str(receipt))
            body = evidence.read_bytes()
            self.assertEqual(hashlib.sha256(body).digest_size, 32)
            self.assertIn(b"private transcript", body)


if __name__ == "__main__":
    unittest.main()
