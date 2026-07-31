from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

import yap_server.__main__ as server_main
from yap_server.config import ServerAuthenticationSettings, ServerSettings


TENANT_ID = "11111111-1111-4111-8111-111111111111"
AUDIENCE = "44444444-4444-4444-8444-444444444444"
CLIENT_ID = "33333333-3333-4333-8333-333333333333"


class LiveRuntimeWiringTests(unittest.TestCase):
    def test_cleanup_continues_after_live_listener_failure(self) -> None:
        live_error = RuntimeError("live teardown failed")
        live_transport = SimpleNamespace(close=Mock(side_effect=live_error))
        runtime = Mock()
        authorization_runtime = SimpleNamespace(close=Mock())
        with patch.object(server_main, "_close_runtime_or_fail_stop") as close_runtime:
            cleanup_error = server_main._close_owned_resources(
                live_transport,
                runtime,
                authorization_runtime,
            )

        self.assertIs(cleanup_error, live_error)
        close_runtime.assert_called_once_with(runtime)
        authorization_runtime.close.assert_called_once_with()

    def test_main_keeps_authenticated_application_transport_on_loopback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            settings = ServerSettings(
                host="192.168.50.1",
                authentication=ServerAuthenticationSettings(
                    mode="entra",
                    tenant_id=TENANT_ID,
                    audience=AUDIENCE,
                    required_scope="access_as_user",
                    allowed_client_ids=(CLIENT_ID,),
                    allowed_roles=("Yap.IdentityAdministrator",),
                    identity_storage_dir=Path(temporary),
                ),
            )
            with (
                patch.object(server_main.signal, "signal"),
                patch.object(
                    server_main.ServerSettings,
                    "from_env",
                    return_value=settings,
                ),
                patch.object(
                    server_main,
                    "build_request_authenticator",
                ) as build_authenticator,
                patch.object(
                    server_main,
                    "PrivateLiveWebSocketServer",
                ) as live_server,
            ):
                with self.assertRaisesRegex(SystemExit, "secure edge"):
                    server_main.main()

        build_authenticator.assert_not_called()
        live_server.assert_not_called()

    def test_entra_runtime_owns_same_authenticator_and_live_listener_lifecycle(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            settings = ServerSettings(
                authentication=ServerAuthenticationSettings(
                    mode="entra",
                    tenant_id=TENANT_ID,
                    audience=AUDIENCE,
                    required_scope="access_as_user",
                    allowed_client_ids=(CLIENT_ID,),
                    allowed_roles=("Yap.IdentityAdministrator",),
                    identity_storage_dir=Path(temporary),
                )
            )
            token_authenticator = Mock()
            admitted_authenticator = Mock()
            authorization_runtime = SimpleNamespace(
                authenticator=admitted_authenticator,
                close=Mock(),
            )
            live_transport = Mock()
            live_transport.start.return_value = live_transport

            with (
                patch.object(server_main.signal, "signal"),
                patch.object(
                    server_main.ServerSettings,
                    "from_env",
                    return_value=settings,
                ),
                patch.object(
                    server_main,
                    "build_request_authenticator",
                    return_value=token_authenticator,
                ),
                patch.object(
                    server_main,
                    "build_request_authorization_runtime",
                    return_value=authorization_runtime,
                ),
                patch.object(
                    server_main,
                    "build_batch_runtime",
                    return_value=None,
                ),
                patch.object(
                    server_main,
                    "private_live_port_from_env",
                    return_value=19_001,
                ),
                patch.object(
                    server_main,
                    "PrivateLiveWebSocketServer",
                    return_value=live_transport,
                ) as live_server,
                patch.object(
                    server_main,
                    "serve",
                    side_effect=KeyboardInterrupt,
                ) as serve,
            ):
                server_main.main()

        live_server.assert_called_once_with(
            admitted_authenticator,
            port=19_001,
        )
        live_transport.start.assert_called_once_with()
        live_transport.close.assert_called_once_with()
        authorization_runtime.close.assert_called_once_with()
        serve.assert_called_once_with(
            settings,
            request_authenticator=admitted_authenticator,
            job_service=None,
            lid_preflight_service=None,
            asr_capabilities=None,
        )

    def test_non_entra_runtime_does_not_start_private_live_listener(self) -> None:
        settings = ServerSettings()
        authorization_runtime = SimpleNamespace(
            authenticator=Mock(),
            close=Mock(),
        )
        with (
            patch.object(server_main.signal, "signal"),
            patch.object(
                server_main.ServerSettings,
                "from_env",
                return_value=settings,
            ),
            patch.object(server_main, "build_request_authenticator"),
            patch.object(
                server_main,
                "build_request_authorization_runtime",
                return_value=authorization_runtime,
            ),
            patch.object(server_main, "build_batch_runtime", return_value=None),
            patch.object(server_main, "PrivateLiveWebSocketServer") as live_server,
            patch.object(server_main, "serve", side_effect=KeyboardInterrupt),
        ):
            server_main.main()

        live_server.assert_not_called()
        authorization_runtime.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
