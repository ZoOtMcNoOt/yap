from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from yap_server.agents.librarian_runtime import (
    LIBRARIAN_ADMISSION_SOCKET,
    LIBRARIAN_KNOWLEDGE_DSN_FILE,
    LIBRARIAN_RUNTIME,
    build_librarian_runtime,
)


def _environment(socket_path: Path, dsn_path: Path) -> dict[str, str]:
    return {
        LIBRARIAN_RUNTIME: "permission_safe_postgres",
        LIBRARIAN_ADMISSION_SOCKET: str(socket_path),
        LIBRARIAN_KNOWLEDGE_DSN_FILE: str(dsn_path),
    }


class LibrarianRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.dsn_path = Path(self.temporary.name).resolve() / "knowledge.dsn"
        self.dsn_path.write_text("dbname=yap", encoding="utf-8")
        self.dsn_path.chmod(0o600)
        self.socket_path = (
            Path(tempfile.gettempdir()) / "agent-admission.sock"
        ).resolve()

    def test_runtime_is_disabled_only_without_librarian_paths(self) -> None:
        self.assertIsNone(build_librarian_runtime({}, authenticated_team_mode=True))
        self.assertIsNone(
            build_librarian_runtime(
                {LIBRARIAN_RUNTIME: "disabled"},
                authenticated_team_mode=True,
            )
        )
        with self.assertRaisesRegex(ValueError, "explicit runtime mode"):
            build_librarian_runtime(
                {LIBRARIAN_ADMISSION_SOCKET: str(self.socket_path)},
                authenticated_team_mode=True,
            )

        environment = _environment(self.socket_path, self.dsn_path)
        environment[LIBRARIAN_RUNTIME] = "disabled"
        with self.assertRaisesRegex(ValueError, "disabled librarian"):
            build_librarian_runtime(
                environment,
                authenticated_team_mode=True,
            )

    def test_runtime_composes_one_shared_broker_and_database_factory(self) -> None:
        admission_transport = object()
        admission = object()
        connection_factory = object()
        evidence_reader = object()
        result_auditor = object()
        librarian = object()
        product_service = object()

        with (
            patch(
                "yap_server.agents.librarian_runtime.UnixAgentAdmissionTransport",
                return_value=admission_transport,
            ) as transport_constructor,
            patch(
                "yap_server.agents.librarian_runtime.AgentAdmissionClient",
                return_value=admission,
            ) as admission_constructor,
            patch(
                "yap_server.agents.librarian_runtime.private_postgres_connection_factory",
                return_value=connection_factory,
            ) as connection_constructor,
            patch(
                "yap_server.agents.librarian_runtime.PostgresLibrarianEvidenceReader",
                return_value=evidence_reader,
            ) as reader_constructor,
            patch(
                "yap_server.agents.librarian_runtime.PostgresLibrarianResultAuditor",
                return_value=result_auditor,
            ) as auditor_constructor,
            patch(
                "yap_server.agents.librarian_runtime.LibrarianService",
                return_value=librarian,
            ) as librarian_constructor,
            patch(
                "yap_server.agents.librarian_runtime.LibrarianQueryService",
                return_value=product_service,
            ) as product_constructor,
        ):
            runtime = build_librarian_runtime(
                _environment(self.socket_path, self.dsn_path),
                authenticated_team_mode=True,
            )

        self.assertIsNotNone(runtime)
        assert runtime is not None
        self.assertIs(runtime.service, product_service)
        transport_constructor.assert_called_once_with(self.socket_path)
        admission_constructor.assert_called_once_with(admission_transport)
        connection_constructor.assert_called_once_with(self.dsn_path)
        reader_constructor.assert_called_once_with(connection_factory)
        auditor_constructor.assert_called_once_with(connection_factory)
        librarian_constructor.assert_called_once_with(
            admission=admission,
            evidence_reader=evidence_reader,
            result_auditor=result_auditor,
        )
        product_constructor.assert_called_once_with(librarian=librarian)

    def test_mode_paths_and_authentication_fail_closed(self) -> None:
        environment = _environment(self.socket_path, self.dsn_path)
        environment[LIBRARIAN_RUNTIME] = "warm_gemma"
        with self.assertRaisesRegex(ValueError, "runtime mode is invalid"):
            build_librarian_runtime(
                environment,
                authenticated_team_mode=True,
            )

        for variable in (
            LIBRARIAN_ADMISSION_SOCKET,
            LIBRARIAN_KNOWLEDGE_DSN_FILE,
        ):
            with self.subTest(variable=variable):
                environment = _environment(self.socket_path, self.dsn_path)
                environment[variable] = "relative/path"
                with self.assertRaisesRegex(ValueError, "must be an absolute path"):
                    build_librarian_runtime(
                        environment,
                        authenticated_team_mode=True,
                    )

        with self.assertRaisesRegex(ValueError, "organization authentication"):
            build_librarian_runtime(
                _environment(self.socket_path, self.dsn_path),
                authenticated_team_mode=False,
            )


if __name__ == "__main__":
    unittest.main()
