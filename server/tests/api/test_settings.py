import os
from pathlib import Path
import unittest
from unittest.mock import patch

from yap_server.config import ServerAuthenticationSettings, ServerSettings


class ServerSettingsTests(unittest.TestCase):
    def test_environment_defaults_to_the_loopback_service_address(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                ServerSettings.from_env(),
                ServerSettings(host="127.0.0.1", port=18765),
            )

    def test_environment_reads_an_explicit_loopback_host_and_port(self) -> None:
        with patch.dict(
            os.environ,
            {"YAP_SERVER_HOST": "::1", "YAP_SERVER_PORT": "28765"},
            clear=True,
        ):
            self.assertEqual(
                ServerSettings.from_env(),
                ServerSettings(host="::1", port=28765),
            )

    def test_non_loopback_bind_rejects_the_retired_plaintext_opt_in(self) -> None:
        for host in ("localhost", "0.0.0.0", "192.168.50.1", "yap.internal"):
            environment = {
                "YAP_SERVER_HOST": host,
                "YAP_SERVER_ALLOW_PRIVATE_BIND": "1",
            }
            with self.subTest(host=host):
                with patch.dict(os.environ, environment, clear=True):
                    with self.assertRaisesRegex(ValueError, "numeric loopback"):
                        ServerSettings.from_env()

    def test_authenticated_team_mode_cannot_bind_the_application_to_lan(
        self,
    ) -> None:
        environment = {
            "YAP_SERVER_HOST": "192.168.50.1",
            "YAP_SERVER_ALLOW_PRIVATE_BIND": "1",
            "YAP_AUTH_MODE": "entra",
            "YAP_ENTRA_TENANT_ID": "11111111-1111-4111-8111-111111111111",
            "YAP_ENTRA_AUDIENCE": "22222222-2222-4222-8222-222222222222",
            "YAP_ENTRA_ALLOWED_CLIENT_IDS": "33333333-3333-4333-8333-333333333333",
            "YAP_IDENTITY_STORAGE_DIR": "private-identity",
        }
        with patch.dict(os.environ, environment, clear=True):
            with self.assertRaisesRegex(ValueError, "approved secure edge"):
                ServerSettings.from_env()

    def test_non_loopback_bind_is_rejected_without_legacy_opt_in(self) -> None:
        for allow_value in (None, "0", "true"):
            environment = {"YAP_SERVER_HOST": "192.168.50.1"}
            if allow_value is not None:
                environment["YAP_SERVER_ALLOW_PRIVATE_BIND"] = allow_value
            with self.subTest(allow_value=allow_value):
                with patch.dict(os.environ, environment, clear=True):
                    with self.assertRaisesRegex(ValueError, "numeric loopback"):
                        ServerSettings.from_env()

    def test_entra_mode_parses_fixed_audience_scope_and_allowed_clients(self) -> None:
        tenant = "11111111-1111-4111-8111-111111111111"
        audience = "22222222-2222-4222-8222-222222222222"
        clients = (
            "33333333-3333-4333-8333-333333333333",
            "44444444-4444-4444-8444-444444444444",
        )
        with patch.dict(
            os.environ,
            {
                "YAP_AUTH_MODE": "entra",
                "YAP_ENTRA_TENANT_ID": tenant,
                "YAP_ENTRA_AUDIENCE": audience,
                "YAP_ENTRA_ALLOWED_CLIENT_IDS": ",".join(reversed(clients)),
                "YAP_ENTRA_REQUIRED_SCOPE": "access_as_user",
                "YAP_ENTRA_ALLOWED_ROLES": (
                    "Yap.IdentityAdministrator,Yap.TranscriptReviewer"
                ),
                "YAP_IDENTITY_STORAGE_DIR": "private-identity",
            },
            clear=True,
        ):
            settings = ServerSettings.from_env()

        self.assertEqual(
            settings.authentication,
            ServerAuthenticationSettings(
                mode="entra",
                tenant_id=tenant,
                audience=audience,
                required_scope="access_as_user",
                allowed_client_ids=clients,
                allowed_roles=(
                    "Yap.IdentityAdministrator",
                    "Yap.TranscriptReviewer",
                ),
                identity_storage_dir=Path("private-identity"),
            ),
        )

    def test_entra_mode_requires_complete_single_tenant_configuration(self) -> None:
        with patch.dict(
            os.environ,
            {"YAP_AUTH_MODE": "entra"},
            clear=True,
        ):
            with self.assertRaisesRegex(ValueError, "YAP_ENTRA_TENANT_ID"):
                ServerSettings.from_env()

        complete_except_storage = {
            "YAP_AUTH_MODE": "entra",
            "YAP_ENTRA_TENANT_ID": "11111111-1111-4111-8111-111111111111",
            "YAP_ENTRA_AUDIENCE": "22222222-2222-4222-8222-222222222222",
            "YAP_ENTRA_ALLOWED_CLIENT_IDS": ("33333333-3333-4333-8333-333333333333"),
        }
        with patch.dict(os.environ, complete_except_storage, clear=True):
            with self.assertRaisesRegex(ValueError, "YAP_IDENTITY_STORAGE_DIR"):
                ServerSettings.from_env()

    def test_entra_mode_rejects_duplicate_or_invalid_client_identifiers(self) -> None:
        environment = {
            "YAP_AUTH_MODE": "entra",
            "YAP_ENTRA_TENANT_ID": "11111111-1111-4111-8111-111111111111",
            "YAP_ENTRA_AUDIENCE": "22222222-2222-4222-8222-222222222222",
            "YAP_ENTRA_ALLOWED_CLIENT_IDS": (
                "33333333-3333-4333-8333-333333333333,"
                "33333333-3333-4333-8333-333333333333"
            ),
            "YAP_IDENTITY_STORAGE_DIR": "private-identity",
        }
        with patch.dict(os.environ, environment, clear=True):
            with self.assertRaisesRegex(ValueError, "must not contain duplicates"):
                ServerSettings.from_env()

        environment["YAP_ENTRA_ALLOWED_CLIENT_IDS"] = "not-a-guid"
        with patch.dict(os.environ, environment, clear=True):
            with self.assertRaisesRegex(ValueError, "valid UUID"):
                ServerSettings.from_env()

    def test_authentication_mode_is_explicit(self) -> None:
        with patch.dict(os.environ, {"YAP_AUTH_MODE": "magic"}, clear=True):
            with self.assertRaisesRegex(ValueError, "YAP_AUTH_MODE"):
                ServerSettings.from_env()

    def test_development_principal_requires_explicit_nonrelease_configuration(
        self,
    ) -> None:
        with patch.dict(
            os.environ,
            {"YAP_AUTH_MODE": "development_loopback"},
            clear=True,
        ):
            with self.assertRaisesRegex(ValueError, "release"):
                ServerSettings.from_env()

        with patch.dict(
            os.environ,
            {
                "YAP_SERVER_CONFIGURATION": "development",
                "YAP_AUTH_MODE": "development_loopback",
            },
            clear=True,
        ):
            settings = ServerSettings.from_env()
        self.assertTrue(settings.authentication.development_enabled)
        self.assertFalse(settings.authentication.authentication_required)

    def test_mock_or_arbitrary_oidc_issuer_cannot_enter_ordinary_config(self) -> None:
        for environment in (
            {"YAP_AUTH_MODE": "mock_oidc"},
            {"YAP_OIDC_ISSUER": "http://127.0.0.1:18767/yap"},
            {"YAP_MOCK_OIDC_ISSUER": "http://127.0.0.1:18767/yap"},
        ):
            with self.subTest(environment=environment):
                with patch.dict(os.environ, environment, clear=True):
                    with self.assertRaisesRegex(
                        ValueError,
                        "mock|OIDC|YAP_AUTH_MODE",
                    ):
                        ServerSettings.from_env()

    def test_entra_roles_are_bounded_and_have_one_canonical_default(self) -> None:
        base = {
            "YAP_AUTH_MODE": "entra",
            "YAP_ENTRA_TENANT_ID": "11111111-1111-4111-8111-111111111111",
            "YAP_ENTRA_AUDIENCE": "22222222-2222-4222-8222-222222222222",
            "YAP_ENTRA_ALLOWED_CLIENT_IDS": "33333333-3333-4333-8333-333333333333",
            "YAP_IDENTITY_STORAGE_DIR": "private-identity",
        }
        with patch.dict(os.environ, base, clear=True):
            settings = ServerSettings.from_env()
        self.assertEqual(
            settings.authentication.allowed_roles,
            ("Yap.IdentityAdministrator",),
        )

        for roles in ("role with spaces", "duplicate,duplicate"):
            with self.subTest(roles=roles):
                with patch.dict(
                    os.environ,
                    {**base, "YAP_ENTRA_ALLOWED_ROLES": roles},
                    clear=True,
                ):
                    with self.assertRaisesRegex(ValueError, "YAP_ENTRA_ALLOWED_ROLES"):
                        ServerSettings.from_env()

    def test_wildcard_bind_is_rejected_without_opt_in(self) -> None:
        with patch.dict(
            os.environ,
            {"YAP_SERVER_HOST": "0.0.0.0"},
            clear=True,
        ):
            with self.assertRaisesRegex(ValueError, "numeric loopback"):
                ServerSettings.from_env()

    def test_invalid_environment_port_is_rejected(self) -> None:
        for port in ("not-a-port", "-1", "65536"):
            with self.subTest(port=port):
                with patch.dict(
                    os.environ,
                    {"YAP_SERVER_PORT": port},
                    clear=True,
                ):
                    with self.assertRaisesRegex(ValueError, "YAP_SERVER_PORT"):
                        ServerSettings.from_env()
