from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from yap_server.agents.archivist_runtime import (
    ARCHIVIST_ADMISSION_SOCKET,
    ARCHIVIST_KNOWLEDGE_DSN_FILE,
    ARCHIVIST_RUNTIME,
    build_archivist_runtime,
)
from yap_server.jobs.service import RecordingJobService


def _environment(socket_path: Path, dsn_path: Path) -> dict[str, str]:
    return {
        ARCHIVIST_RUNTIME: "reviewed_capture_postgres",
        ARCHIVIST_ADMISSION_SOCKET: str(socket_path),
        ARCHIVIST_KNOWLEDGE_DSN_FILE: str(dsn_path),
    }


class ArchivistRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.dsn_path = Path(self.temporary.name).resolve() / "knowledge.dsn"
        self.dsn_path.write_text("dbname=yap", encoding="utf-8")
        self.socket_path = (
            Path(tempfile.gettempdir()) / "agent-admission.sock"
        ).resolve()

    def test_runtime_is_disabled_only_without_archivist_paths(self) -> None:
        jobs = object()
        self.assertIsNone(
            build_archivist_runtime(
                {},
                authenticated_team_mode=True,
                jobs=jobs,
            )
        )
        self.assertIsNone(
            build_archivist_runtime(
                {ARCHIVIST_RUNTIME: "disabled"},
                authenticated_team_mode=True,
                jobs=jobs,
            )
        )
        with self.assertRaisesRegex(ValueError, "explicit runtime mode"):
            build_archivist_runtime(
                {ARCHIVIST_ADMISSION_SOCKET: str(self.socket_path)},
                authenticated_team_mode=True,
                jobs=jobs,
            )

    def test_runtime_composes_one_job_authority_broker_and_database(self) -> None:
        jobs = object.__new__(RecordingJobService)
        admission_transport = object()
        admission = object()
        connection_factory = object()
        processor = object()
        core = object()
        runner = object()
        product = object()

        with (
            patch(
                "yap_server.agents.archivist_runtime.UnixAgentAdmissionTransport",
                return_value=admission_transport,
            ) as transport_constructor,
            patch(
                "yap_server.agents.archivist_runtime.AgentAdmissionClient",
                return_value=admission,
            ) as admission_constructor,
            patch(
                "yap_server.agents.archivist_runtime.private_postgres_connection_factory",
                return_value=connection_factory,
            ) as connection_constructor,
            patch(
                "yap_server.agents.archivist_runtime.PostgresArchivistProcessor",
                return_value=processor,
            ) as processor_constructor,
            patch(
                "yap_server.agents.archivist_runtime.ArchivistService",
                return_value=core,
            ) as core_constructor,
            patch(
                "yap_server.agents.archivist_runtime.PostgresArchivistIngestionRunner",
                return_value=runner,
            ) as runner_constructor,
            patch(
                "yap_server.agents.archivist_runtime.ArchivistIngestionService",
                return_value=product,
            ) as product_constructor,
        ):
            runtime = build_archivist_runtime(
                _environment(self.socket_path, self.dsn_path),
                authenticated_team_mode=True,
                jobs=jobs,
            )

        self.assertIsNotNone(runtime)
        assert runtime is not None
        self.assertIs(runtime.service, product)
        transport_constructor.assert_called_once_with(self.socket_path)
        admission_constructor.assert_called_once_with(admission_transport)
        connection_constructor.assert_called_once_with(self.dsn_path)
        processor_constructor.assert_called_once_with(connection_factory)
        core_constructor.assert_called_once_with(
            admission=admission,
            processor=processor,
        )
        runner_constructor.assert_called_once_with(
            jobs=jobs,
            connection_factory=connection_factory,
            archivist=core,
        )
        product_constructor.assert_called_once_with(runner=runner)

    def test_mode_paths_and_authentication_fail_closed(self) -> None:
        jobs = object.__new__(RecordingJobService)
        environment = _environment(self.socket_path, self.dsn_path)
        environment[ARCHIVIST_RUNTIME] = "warm_gemma"
        with self.assertRaisesRegex(ValueError, "runtime mode is invalid"):
            build_archivist_runtime(
                environment,
                authenticated_team_mode=True,
                jobs=jobs,
            )

        for variable in (
            ARCHIVIST_ADMISSION_SOCKET,
            ARCHIVIST_KNOWLEDGE_DSN_FILE,
        ):
            with self.subTest(variable=variable):
                environment = _environment(self.socket_path, self.dsn_path)
                environment[variable] = "relative/path"
                with self.assertRaisesRegex(ValueError, "must be an absolute path"):
                    build_archivist_runtime(
                        environment,
                        authenticated_team_mode=True,
                        jobs=jobs,
                    )

        with self.assertRaisesRegex(ValueError, "organization authentication"):
            build_archivist_runtime(
                _environment(self.socket_path, self.dsn_path),
                authenticated_team_mode=False,
                jobs=jobs,
            )


if __name__ == "__main__":
    unittest.main()
