from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import psycopg

from yap_server.api.app import create_server
from yap_server.config import ServerAuthenticationSettings, ServerSettings
from yap_server.knowledge.knowledge_publication_service import (
    build_knowledge_publication_service,
)
from tests.api import test_knowledge_publication_api as publication_fixtures
from tests.api import test_terminology_api as terminology_fixtures
from tests.api.api_fixtures import HealthServerTestCase


class PublicationConfigurationTests(unittest.TestCase):
    def test_absent_or_disabled_configuration_opens_no_database(self):
        with patch(
            "yap_server.knowledge.knowledge_publication_service.private_postgres_connection_factory",
            side_effect=AssertionError("unexpected database access"),
        ):
            for environ in ({}, {"YAP_KNOWLEDGE_PUBLICATION_RUNTIME": "disabled"}):
                self.assertIsNone(
                    build_knowledge_publication_service(
                        environ, authenticated_team_mode=False
                    )
                )

    def test_mode_and_organization_authentication_are_explicit(self):
        for environ, team in (
            ({"YAP_KNOWLEDGE_PUBLICATION_DSN_FILE": "/private/database.dsn"}, True),
            (
                {
                    "YAP_KNOWLEDGE_PUBLICATION_RUNTIME": "disabled",
                    "YAP_KNOWLEDGE_PUBLICATION_DSN_FILE": "/private/database.dsn",
                },
                True,
            ),
            (
                {
                    "YAP_KNOWLEDGE_PUBLICATION_RUNTIME": "postgres",
                    "YAP_KNOWLEDGE_PUBLICATION_DSN_FILE": "/private/database.dsn",
                },
                False,
            ),
            ({"YAP_KNOWLEDGE_PUBLICATION_RUNTIME": "automatic"}, True),
        ):
            with self.assertRaises(ValueError):
                build_knowledge_publication_service(
                    environ, authenticated_team_mode=team
                )

    def test_postgres_requires_one_absolute_unpadded_credential_path(self):
        for path in (None, "", "relative.dsn", " /private/database.dsn "):
            environ = {"YAP_KNOWLEDGE_PUBLICATION_RUNTIME": "postgres"}
            if path is not None:
                environ["YAP_KNOWLEDGE_PUBLICATION_DSN_FILE"] = path
            with self.assertRaises(ValueError):
                build_knowledge_publication_service(
                    environ, authenticated_team_mode=True
                )

    def test_unavailable_or_nonprivate_credential_file_is_refused_without_details(self):
        with TemporaryDirectory() as directory:
            credential = Path(directory) / "private-source.dsn"
            # Invalid credentials cannot reach a database on any platform.
            credential.write_text("private secret invalid dsn\n\0", encoding="utf-8")
            if os.name == "posix":
                credential.chmod(0o644)
            for path in (credential, Path(directory) / "missing-private.dsn"):
                with self.assertRaises(ValueError) as captured:
                    build_knowledge_publication_service(
                        {
                            "YAP_KNOWLEDGE_PUBLICATION_RUNTIME": "postgres",
                            "YAP_KNOWLEDGE_PUBLICATION_DSN_FILE": str(path),
                        },
                        authenticated_team_mode=True,
                    )
                self.assertEqual(
                    str(captured.exception),
                    "knowledge publication database configuration is unavailable",
                )
                self.assertNotIn("private-source", str(captured.exception))

    def test_database_startup_failure_is_content_free(self):
        with patch(
            "yap_server.knowledge.knowledge_publication_service.private_postgres_connection_factory",
            side_effect=psycopg.OperationalError("private password and address"),
        ):
            with self.assertRaisesRegex(
                ValueError,
                "^knowledge publication database configuration is unavailable$",
            ):
                build_knowledge_publication_service(
                    {
                        "YAP_KNOWLEDGE_PUBLICATION_RUNTIME": "postgres",
                        "YAP_KNOWLEDGE_PUBLICATION_DSN_FILE": str(
                            Path.cwd() / "private.dsn"
                        ),
                    },
                    authenticated_team_mode=True,
                )

    def test_http_service_cannot_be_enabled_in_local_development_authentication(self):
        settings = ServerSettings(
            host="127.0.0.1",
            port=0,
            authentication=ServerAuthenticationSettings(mode="development_loopback"),
        )
        with self.assertRaisesRegex(
            ValueError, "knowledge publication requires organization authentication"
        ):
            create_server(settings, knowledge_publication_service=object())


class DisabledPublicationApiTests(HealthServerTestCase):
    server_settings = terminology_fixtures.TerminologyApiTests.server_settings
    request_authenticator = publication_fixtures._Authentication("publication-disabled")

    def test_disabled_route_authenticates_and_advertises_its_supported_methods(self):
        for method in ("GET", "POST"):
            self.assertEqual(
                self._request("/v1/knowledge/publications", method=method)[0], 401
            )
            status, _, body = self._request(
                "/v1/knowledge/publications",
                method=method,
                headers={"Authorization": "Bearer alice"},
            )
            self.assertEqual(status, 501)
            self.assertEqual(json.loads(body)["code"], "NOT_IMPLEMENTED")
        self.assertEqual(
            self._request("/v1/knowledge/publications", method="DELETE")[0], 405
        )
