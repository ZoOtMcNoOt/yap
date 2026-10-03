from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch

import psycopg

from yap_server.knowledge import knowledge_connections_service as runtime
from yap_server.private_postgres_connection import read_private_postgres_dsn


class KnowledgeConnectionsRuntimeTests(unittest.TestCase):
    def test_unconfigured_and_disabled_never_open_database(self):
        with patch.object(runtime, "private_postgres_connection_factory") as connect:
            for environment in ({}, {"YAP_KNOWLEDGE_CONNECTIONS_RUNTIME": "disabled"}):
                self.assertIsNone(
                    runtime.build_knowledge_connections_service(
                        environment, authenticated_team_mode=False
                    )
                )
            connect.assert_not_called()

    def test_invalid_configuration_and_untrusted_runtime_are_refused(self):
        with patch.object(runtime, "private_postgres_connection_factory") as connect:
            for mode, path, authenticated in [
                (None, "/private/db", True),
                ("disabled", "/private/db", True),
                ("postgres", None, True),
                ("postgres", "relative", True),
                ("postgres", "/private/db", False),
                (" postgres", "/private/db", True),
            ]:
                environment = {
                    key: value
                    for key, value in {
                        "YAP_KNOWLEDGE_CONNECTIONS_RUNTIME": mode,
                        "YAP_KNOWLEDGE_CONNECTIONS_DSN_FILE": path,
                    }.items()
                    if value is not None
                }
                with (
                    self.subTest(mode=mode, path=path, authenticated=authenticated),
                    self.assertRaises(ValueError),
                ):
                    runtime.build_knowledge_connections_service(
                        environment, authenticated_team_mode=authenticated
                    )
            connect.assert_not_called()
        from yap_server.api.app import create_server
        from yap_server.config import ServerSettings

        with self.assertRaisesRegex(ValueError, "require organization authentication"):
            create_server(ServerSettings(), knowledge_connections_service=object())

    def test_startup_failures_do_not_expose_private_database_details(self):
        with tempfile.TemporaryDirectory() as temporary:
            credential = Path(temporary) / "private.dsn"
            credential.write_text("dbname=yap password=private-test-secret\n")
            credential.chmod(0o600)
            with patch.object(
                runtime,
                "KnowledgeConnectionsService",
                side_effect=psycopg.OperationalError("private-test-secret"),
            ):
                with self.assertRaisesRegex(
                    ValueError, "configuration is unavailable"
                ) as error:
                    runtime.build_knowledge_connections_service(
                        {
                            "YAP_KNOWLEDGE_CONNECTIONS_RUNTIME": "postgres",
                            "YAP_KNOWLEDGE_CONNECTIONS_DSN_FILE": str(credential),
                        },
                        authenticated_team_mode=True,
                    )
                self.assertNotIn("private-test-secret", str(error.exception))
                self.assertTrue(error.exception.__suppress_context__)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "requires POSIX FIFO")
    def test_nonregular_credentials_are_refused_without_waiting_for_a_writer(self):
        with tempfile.TemporaryDirectory() as temporary:
            fifo = Path(temporary) / "credential.fifo"
            os.mkfifo(fifo, 0o600)
            with self.assertRaisesRegex(ValueError, "regular file"):
                read_private_postgres_dsn(fifo)
