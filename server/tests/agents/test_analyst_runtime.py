from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from yap_server.agents.analyst_runtime import (
    ANALYST_ADMISSION_SOCKET,
    ANALYST_CANDIDATE_LOCK,
    ANALYST_KNOWLEDGE_DSN_FILE,
    ANALYST_PROFILE,
    ANALYST_RUNTIME,
    build_analyst_runtime,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PROFILE = (
    REPOSITORY_ROOT / "server" / "agent-service-profiles" / "complex-orchestration.json"
)
CANDIDATE_LOCK = REPOSITORY_ROOT / "server" / "agent-reasoning-candidates.lock.json"


def _environment(socket_path: Path, dsn_path: Path) -> dict[str, str]:
    return {
        ANALYST_RUNTIME: "warm_gemma",
        ANALYST_ADMISSION_SOCKET: str(socket_path),
        ANALYST_PROFILE: str(PROFILE),
        ANALYST_CANDIDATE_LOCK: str(CANDIDATE_LOCK),
        ANALYST_KNOWLEDGE_DSN_FILE: str(dsn_path),
    }


class AnalystRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.dsn_path = Path(self.temporary.name).resolve() / "knowledge.dsn"
        self.dsn_path.write_text("dbname=yap", encoding="utf-8")
        self.dsn_path.chmod(0o600)

    def _environment(self, socket_path: Path) -> dict[str, str]:
        return _environment(socket_path, self.dsn_path)

    def test_runtime_is_disabled_only_without_analyst_paths(self) -> None:
        self.assertIsNone(build_analyst_runtime({}, authenticated_team_mode=True))
        self.assertIsNone(
            build_analyst_runtime(
                {ANALYST_RUNTIME: "disabled"},
                authenticated_team_mode=True,
            )
        )
        with self.assertRaisesRegex(ValueError, "explicit runtime mode"):
            build_analyst_runtime(
                {ANALYST_PROFILE: str(PROFILE)},
                authenticated_team_mode=True,
            )

        environment = self._environment(
            (Path(tempfile.gettempdir()) / "agent-admission.sock").resolve()
        )
        environment[ANALYST_RUNTIME] = "disabled"
        with self.assertRaisesRegex(ValueError, "disabled analyst"):
            build_analyst_runtime(environment, authenticated_team_mode=True)

    def test_warm_gemma_runtime_binds_exact_full_route_and_team_identity(self) -> None:
        socket_path = (Path(tempfile.gettempdir()) / "agent-admission.sock").resolve()
        runtime = build_analyst_runtime(
            self._environment(socket_path),
            authenticated_team_mode=True,
        )

        self.assertIsNotNone(runtime)
        assert runtime is not None
        self.assertEqual(runtime.profile_id, "complex-orchestration")
        self.assertEqual(runtime.model, "nvidia/Gemma-4-31B-IT-NVFP4")
        self.assertEqual(
            runtime.profile_sha256,
            "cccc330793d1fb32989cf5822da00f96a02dd198dbb4229cd9f5d1c4ca0c3d1c",
        )
        self.assertEqual(
            runtime.candidate_lock_sha256,
            "3e9218c8245863c5f1bda8166a629361b51ed23cec259d7c69f11b1dee83d013",
        )
        self.assertEqual(runtime.maximum_output_tokens, 512)
        self.assertEqual(runtime.maximum_input_tokens, 7_680)

        with self.assertRaisesRegex(ValueError, "organization authentication"):
            build_analyst_runtime(
                self._environment(socket_path),
                authenticated_team_mode=False,
            )

    def test_runtime_shares_admission_and_database_factory_without_lifecycle(
        self,
    ) -> None:
        socket_path = (Path(tempfile.gettempdir()) / "agent-admission.sock").resolve()
        admission_transport = object()
        admission = object()
        transport = object()
        connection_factory = object()
        evidence_reader = object()
        librarian_auditor = object()
        librarian = object()
        evidence_verifier = object()
        answerer = object()
        analyst_auditor = object()
        analyst_service = object()

        with (
            patch(
                "yap_server.agents.analyst_runtime.UnixAgentAdmissionTransport",
                return_value=admission_transport,
            ) as admission_transport_constructor,
            patch(
                "yap_server.agents.analyst_runtime.AgentAdmissionClient",
                return_value=admission,
            ) as admission_constructor,
            patch(
                "yap_server.agents.analyst_runtime.BoundedVllmJsonClient",
                return_value=transport,
            ) as transport_constructor,
            patch(
                "yap_server.agents.analyst_runtime.private_postgres_connection_factory",
                return_value=connection_factory,
            ) as connection_factory_constructor,
            patch(
                "yap_server.agents.analyst_runtime.PostgresLibrarianEvidenceReader",
                return_value=evidence_reader,
            ) as reader_constructor,
            patch(
                "yap_server.agents.analyst_runtime.PostgresLibrarianResultAuditor",
                return_value=librarian_auditor,
            ) as librarian_auditor_constructor,
            patch(
                "yap_server.agents.analyst_runtime.LibrarianService",
                return_value=librarian,
            ) as librarian_constructor,
            patch(
                "yap_server.agents.analyst_runtime.PostgresAnalystEvidenceVerifier",
                return_value=evidence_verifier,
            ) as evidence_verifier_constructor,
            patch(
                "yap_server.agents.analyst_runtime.AnalystEvidenceModel",
                return_value=answerer,
            ) as model_constructor,
            patch(
                "yap_server.agents.analyst_runtime.PostgresAnalystResultAuditor",
                return_value=analyst_auditor,
            ) as analyst_auditor_constructor,
            patch(
                "yap_server.agents.analyst_runtime.AnalystService",
                return_value=analyst_service,
            ) as service_constructor,
        ):
            runtime = build_analyst_runtime(
                self._environment(socket_path),
                authenticated_team_mode=True,
            )

        self.assertIsNotNone(runtime)
        assert runtime is not None
        self.assertIs(runtime.service, analyst_service)
        admission_transport_constructor.assert_called_once_with(socket_path)
        admission_constructor.assert_called_once_with(admission_transport)
        transport_constructor.assert_called_once_with(
            endpoint="http://127.0.0.1:18101",
            timeout_seconds=55,
            maximum_response_bytes=1_048_576,
        )
        connection_factory_constructor.assert_called_once_with(self.dsn_path)
        reader_constructor.assert_called_once_with(connection_factory)
        librarian_auditor_constructor.assert_called_once_with(connection_factory)
        librarian_constructor.assert_called_once_with(
            admission=admission,
            evidence_reader=evidence_reader,
            result_auditor=librarian_auditor,
        )
        evidence_verifier_constructor.assert_called_once_with(connection_factory)
        model_constructor.assert_called_once_with(
            transport=transport,
            model="nvidia/Gemma-4-31B-IT-NVFP4",
            maximum_output_tokens=512,
        )
        analyst_auditor_constructor.assert_called_once()
        analyst_auditor_call = analyst_auditor_constructor.call_args
        self.assertIs(analyst_auditor_call.args[0], connection_factory)
        runtime_identity = analyst_auditor_call.args[1]
        self.assertEqual(runtime_identity.candidate_id, "gemma-4-31b-it-nvfp4")
        self.assertEqual(runtime_identity.model, "nvidia/Gemma-4-31B-IT-NVFP4")
        self.assertEqual(
            runtime_identity.model_revision,
            "4135a98a9b728a548947683219633b25682223ac",
        )
        self.assertEqual(runtime_identity.runtime_id, "gemma-vllm-26.06")
        self.assertEqual(
            runtime_identity.profile_sha256,
            "cccc330793d1fb32989cf5822da00f96a02dd198dbb4229cd9f5d1c4ca0c3d1c",
        )
        self.assertEqual(
            runtime_identity.candidate_lock_sha256,
            "3e9218c8245863c5f1bda8166a629361b51ed23cec259d7c69f11b1dee83d013",
        )
        service_constructor.assert_called_once_with(
            admission=admission,
            librarian=librarian,
            evidence_verifier=evidence_verifier,
            model=answerer,
            result_auditor=analyst_auditor,
        )

    def test_mode_paths_and_profile_bytes_fail_closed(self) -> None:
        socket_path = (Path(tempfile.gettempdir()) / "agent-admission.sock").resolve()
        environment = self._environment(socket_path)
        environment[ANALYST_RUNTIME] = "warm_qwen"
        with self.assertRaisesRegex(ValueError, "runtime mode is invalid"):
            build_analyst_runtime(environment, authenticated_team_mode=True)

        for variable in (
            ANALYST_ADMISSION_SOCKET,
            ANALYST_PROFILE,
            ANALYST_CANDIDATE_LOCK,
            ANALYST_KNOWLEDGE_DSN_FILE,
        ):
            with self.subTest(variable=variable):
                environment = self._environment(socket_path)
                environment[variable] = "relative/path"
                with self.assertRaisesRegex(ValueError, "must be an absolute path"):
                    build_analyst_runtime(
                        environment,
                        authenticated_team_mode=True,
                    )

        with tempfile.TemporaryDirectory() as temporary:
            changed_profile = Path(temporary).resolve() / "complex.json"
            changed_profile.write_bytes(PROFILE.read_bytes() + b"\n")
            environment = self._environment(socket_path)
            environment[ANALYST_PROFILE] = str(changed_profile)
            with self.assertRaisesRegex(ValueError, "profile bytes differ"):
                build_analyst_runtime(environment, authenticated_team_mode=True)

            changed_lock = Path(temporary).resolve() / "candidates.json"
            changed_lock.write_bytes(CANDIDATE_LOCK.read_bytes() + b"\n")
            environment = self._environment(socket_path)
            environment[ANALYST_CANDIDATE_LOCK] = str(changed_lock)
            with self.assertRaisesRegex(ValueError, "candidate lock bytes differ"):
                build_analyst_runtime(environment, authenticated_team_mode=True)


if __name__ == "__main__":
    unittest.main()
