from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import psycopg

from yap_server.knowledge import terminology_runtime as runtime


class PersonalTerminologyRuntimeTests(unittest.TestCase):
    def test_injected_service_cannot_expose_a_development_or_unauthenticated_route(
        self,
    ):
        from yap_server.api.app import create_server
        from yap_server.config import ServerSettings

        with self.assertRaisesRegex(ValueError, "requires organization authentication"):
            create_server(ServerSettings(), terminology_service=object())

    def test_disabled_and_unconfigured_modes_never_open_database(self):
        with patch.object(runtime, "private_postgres_connection_factory") as connect:
            for environment in ({}, {runtime.TERMINOLOGY_RUNTIME: "disabled"}):
                self.assertIsNone(
                    runtime.build_terminology_service(
                        environment, authenticated_team_mode=False
                    )
                )
            connect.assert_not_called()

    def test_configuration_and_authentication_fail_before_database_access(self):
        with patch.object(runtime, "private_postgres_connection_factory") as connect:
            for environment, authenticated in (
                (
                    {runtime.TERMINOLOGY_DSN_FILE: "/private/knowledge.dsn"},
                    True,
                ),
                (
                    {
                        runtime.TERMINOLOGY_RUNTIME: "disabled",
                        runtime.TERMINOLOGY_DSN_FILE: "/private/knowledge.dsn",
                    },
                    True,
                ),
                ({runtime.TERMINOLOGY_RUNTIME: " postgres"}, True),
                ({runtime.TERMINOLOGY_RUNTIME: "postgres"}, True),
                (
                    {
                        runtime.TERMINOLOGY_RUNTIME: "postgres",
                        runtime.TERMINOLOGY_DSN_FILE: "relative.dsn",
                    },
                    True,
                ),
                (
                    {
                        runtime.TERMINOLOGY_RUNTIME: "postgres",
                        runtime.TERMINOLOGY_DSN_FILE: "/private/knowledge.dsn",
                    },
                    False,
                ),
            ):
                with self.subTest(environment=environment, authenticated=authenticated):
                    with self.assertRaises(ValueError):
                        runtime.build_terminology_service(
                            environment, authenticated_team_mode=authenticated
                        )
            connect.assert_not_called()

    def test_model_independent_configuration_uses_private_bounded_connection(self):
        with tempfile.TemporaryDirectory() as temporary:
            credential = Path(temporary) / "knowledge.dsn"
            credential.write_text("dbname=yap\n")
            credential.chmod(0o600)
            with patch.object(runtime, "TerminologyService") as service:
                value = runtime.build_terminology_service(
                    {
                        runtime.TERMINOLOGY_RUNTIME: "postgres",
                        runtime.TERMINOLOGY_DSN_FILE: str(credential),
                    },
                    authenticated_team_mode=True,
                )
                self.assertIs(value, service.return_value)
                self.assertTrue(
                    callable(service.call_args.kwargs["connection_factory"])
                )

    def test_database_failure_does_not_expose_credentials(self):
        with tempfile.TemporaryDirectory() as temporary:
            credential = Path(temporary) / "knowledge.dsn"
            credential.write_text("dbname=yap password=private-test-password\n")
            credential.chmod(0o600)
            with patch.object(
                runtime,
                "TerminologyService",
                side_effect=psycopg.OperationalError("private-test-password"),
            ):
                with self.assertRaisesRegex(
                    ValueError, "database configuration is unavailable"
                ) as failure:
                    runtime.build_terminology_service(
                        {
                            runtime.TERMINOLOGY_RUNTIME: "postgres",
                            runtime.TERMINOLOGY_DSN_FILE: str(credential),
                        },
                        authenticated_team_mode=True,
                    )
                self.assertNotIn("private-test-password", str(failure.exception))
                self.assertTrue(failure.exception.__suppress_context__)
