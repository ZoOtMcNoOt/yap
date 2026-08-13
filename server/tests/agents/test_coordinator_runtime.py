from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from yap_server.agents.coordinator_runtime import (
    COORDINATOR_ADMISSION_SOCKET,
    COORDINATOR_CANDIDATE_LOCK,
    COORDINATOR_KNOWLEDGE_DSN_FILE,
    COORDINATOR_PROFILE,
    COORDINATOR_RUNTIME,
    build_coordinator_runtime,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PROFILE = (
    REPOSITORY_ROOT / "server" / "agent-service-profiles" / "complex-orchestration.json"
)
CANDIDATE_LOCK = REPOSITORY_ROOT / "server" / "agent-reasoning-candidates.lock.json"


def _environment(socket_path: Path, dsn_path: Path) -> dict[str, str]:
    return {
        COORDINATOR_RUNTIME: "warm_gemma",
        COORDINATOR_ADMISSION_SOCKET: str(socket_path),
        COORDINATOR_PROFILE: str(PROFILE),
        COORDINATOR_CANDIDATE_LOCK: str(CANDIDATE_LOCK),
        COORDINATOR_KNOWLEDGE_DSN_FILE: str(dsn_path),
    }


class CoordinatorRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.dsn_path = Path(self.temporary.name).resolve() / "knowledge.dsn"
        self.dsn_path.write_text("dbname=yap", encoding="utf-8")
        self.dsn_path.chmod(0o600)

    def _environment(self, socket_path: Path) -> dict[str, str]:
        return _environment(socket_path, self.dsn_path)

    def test_runtime_is_disabled_only_without_coordinator_paths(self) -> None:
        self.assertIsNone(build_coordinator_runtime({}, authenticated_team_mode=True))
        self.assertIsNone(
            build_coordinator_runtime(
                {COORDINATOR_RUNTIME: "disabled"},
                authenticated_team_mode=True,
            )
        )
        with self.assertRaisesRegex(ValueError, "explicit runtime mode"):
            build_coordinator_runtime(
                {COORDINATOR_PROFILE: str(PROFILE)},
                authenticated_team_mode=True,
            )

        environment = self._environment(
            (Path(tempfile.gettempdir()) / "agent-admission.sock").resolve()
        )
        environment[COORDINATOR_RUNTIME] = "disabled"
        with self.assertRaisesRegex(ValueError, "disabled coordinator"):
            build_coordinator_runtime(environment, authenticated_team_mode=True)

    def test_warm_gemma_runtime_binds_exact_full_route_and_team_identity(self) -> None:
        socket_path = (Path(tempfile.gettempdir()) / "agent-admission.sock").resolve()
        runtime = build_coordinator_runtime(
            self._environment(socket_path),
            authenticated_team_mode=True,
        )

        self.assertIsNotNone(runtime)
        assert runtime is not None
        self.assertEqual(runtime.profile_id, "complex-orchestration")
        self.assertEqual(runtime.model, "nvidia/Gemma-4-31B-IT-NVFP4")
        self.assertEqual(
            runtime.profile_sha256,
            "4c5e5da836355e57ec43c6f1270eb9eb5839c6fd91e6dbf73389e37ce4cdf6a8",
        )
        self.assertEqual(
            runtime.candidate_lock_sha256,
            "3e9218c8245863c5f1bda8166a629361b51ed23cec259d7c69f11b1dee83d013",
        )
        self.assertEqual(runtime.maximum_output_tokens, 512)
        self.assertEqual(runtime.maximum_input_tokens, 7_680)

        with self.assertRaisesRegex(ValueError, "organization authentication"):
            build_coordinator_runtime(
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
        model = object()
        result_auditor = object()
        service = object()

        with (
            patch(
                "yap_server.agents.coordinator_runtime.UnixAgentAdmissionTransport",
                return_value=admission_transport,
            ) as admission_transport_constructor,
            patch(
                "yap_server.agents.coordinator_runtime.AgentAdmissionClient",
                return_value=admission,
            ) as admission_constructor,
            patch(
                "yap_server.agents.coordinator_runtime.BoundedVllmJsonClient",
                return_value=transport,
            ) as transport_constructor,
            patch(
                "yap_server.agents.coordinator_runtime.private_postgres_connection_factory",
                return_value=connection_factory,
            ) as connection_factory_constructor,
            patch(
                "yap_server.agents.coordinator_runtime.PostgresCoordinatorEvidenceReader",
                return_value=evidence_reader,
            ) as reader_constructor,
            patch(
                "yap_server.agents.coordinator_runtime.CoordinatorEvidenceModel",
                return_value=model,
            ) as model_constructor,
            patch(
                "yap_server.agents.coordinator_runtime.PostgresCoordinatorResultAuditor",
                return_value=result_auditor,
            ) as result_auditor_constructor,
            patch(
                "yap_server.agents.coordinator_runtime.CoordinatorService",
                return_value=service,
            ) as service_constructor,
        ):
            runtime = build_coordinator_runtime(
                self._environment(socket_path),
                authenticated_team_mode=True,
            )

        self.assertIsNotNone(runtime)
        assert runtime is not None
        self.assertIs(runtime.service, service)
        admission_transport_constructor.assert_called_once_with(socket_path)
        admission_constructor.assert_called_once_with(admission_transport)
        transport_constructor.assert_called_once_with(
            endpoint="http://127.0.0.1:18101",
            timeout_seconds=55,
            maximum_response_bytes=1_048_576,
        )
        connection_factory_constructor.assert_called_once_with(self.dsn_path)
        reader_constructor.assert_called_once_with(connection_factory)
        model_constructor.assert_called_once_with(
            transport=transport,
            model="nvidia/Gemma-4-31B-IT-NVFP4",
            maximum_output_tokens=512,
        )
        result_auditor_constructor.assert_called_once()
        result_auditor_call = result_auditor_constructor.call_args
        self.assertIs(result_auditor_call.args[0], connection_factory)
        runtime_identity = result_auditor_call.args[1]
        self.assertEqual(runtime_identity.candidate_id, "gemma-4-31b-it-nvfp4")
        self.assertEqual(runtime_identity.model, "nvidia/Gemma-4-31B-IT-NVFP4")
        self.assertEqual(
            runtime_identity.model_revision,
            "4135a98a9b728a548947683219633b25682223ac",
        )
        self.assertEqual(runtime_identity.runtime_id, "gemma-vllm-26.06")
        self.assertEqual(
            runtime_identity.profile_sha256,
            "4c5e5da836355e57ec43c6f1270eb9eb5839c6fd91e6dbf73389e37ce4cdf6a8",
        )
        self.assertEqual(
            runtime_identity.candidate_lock_sha256,
            "3e9218c8245863c5f1bda8166a629361b51ed23cec259d7c69f11b1dee83d013",
        )
        service_constructor.assert_called_once_with(
            admission=admission,
            evidence_reader=evidence_reader,
            model=model,
            result_auditor=result_auditor,
        )

    def test_runtime_accepts_one_explicit_observed_admission_owner(self) -> None:
        socket_path = (Path(tempfile.gettempdir()) / "agent-admission.sock").resolve()
        admission = object()
        service = object()
        with (
            patch(
                "yap_server.agents.coordinator_runtime.AgentAdmissionClient"
            ) as admission_constructor,
            patch(
                "yap_server.agents.coordinator_runtime.CoordinatorService",
                return_value=service,
            ) as service_constructor,
        ):
            runtime = build_coordinator_runtime(
                self._environment(socket_path),
                authenticated_team_mode=True,
                admission=admission,
            )

        self.assertIsNotNone(runtime)
        admission_constructor.assert_not_called()
        self.assertIs(service_constructor.call_args.kwargs["admission"], admission)

    def test_mode_paths_and_profile_bytes_fail_closed(self) -> None:
        socket_path = (Path(tempfile.gettempdir()) / "agent-admission.sock").resolve()
        environment = self._environment(socket_path)
        environment[COORDINATOR_RUNTIME] = "warm_qwen"
        with self.assertRaisesRegex(ValueError, "runtime mode is invalid"):
            build_coordinator_runtime(environment, authenticated_team_mode=True)

        for variable in (
            COORDINATOR_ADMISSION_SOCKET,
            COORDINATOR_PROFILE,
            COORDINATOR_CANDIDATE_LOCK,
            COORDINATOR_KNOWLEDGE_DSN_FILE,
        ):
            with self.subTest(variable=variable):
                environment = self._environment(socket_path)
                environment[variable] = "relative/path"
                with self.assertRaisesRegex(ValueError, "must be an absolute path"):
                    build_coordinator_runtime(
                        environment,
                        authenticated_team_mode=True,
                    )

        with tempfile.TemporaryDirectory() as temporary:
            changed_profile = Path(temporary).resolve() / "complex.json"
            changed_profile.write_bytes(PROFILE.read_bytes() + b"\n")
            environment = self._environment(socket_path)
            environment[COORDINATOR_PROFILE] = str(changed_profile)
            with self.assertRaisesRegex(ValueError, "profile bytes differ"):
                build_coordinator_runtime(environment, authenticated_team_mode=True)

            changed_lock = Path(temporary).resolve() / "candidates.json"
            changed_lock.write_bytes(CANDIDATE_LOCK.read_bytes() + b"\n")
            environment = self._environment(socket_path)
            environment[COORDINATOR_CANDIDATE_LOCK] = str(changed_lock)
            with self.assertRaisesRegex(ValueError, "candidate lock bytes differ"):
                build_coordinator_runtime(environment, authenticated_team_mode=True)


if __name__ == "__main__":
    unittest.main()
