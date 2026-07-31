from __future__ import annotations

from collections.abc import Sequence
from http import HTTPStatus
import hashlib
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from websockets.datastructures import Headers
from websockets.exceptions import ConnectionClosed, InvalidStatus
from websockets.sync.client import ClientConnection, connect

from yap_server.api.app import create_server
from yap_server.auth import AuthenticatedPrincipal, AuthenticationFailure
from yap_server.config import ServerAuthenticationSettings, ServerSettings
from yap_server.live import LIVE_SUBPROTOCOL
from yap_server.live.websocket_server import (
    LIVE_CLOSE_ACCESS_REVOKED,
    LIVE_CLOSE_PROTOCOL_ERROR,
    LIVE_CLOSE_TOKEN_EXPIRED,
    MAX_LIVE_CONNECTIONS,
    MAX_LIVE_HANDLER_THREADS,
    PrivateLiveWebSocketServer,
    private_live_port_from_env,
)
from yap_server.live.protocol import (
    MAX_BINARY_MESSAGE_BYTES,
    MAX_JSON_MESSAGE_BYTES,
)


TENANT_ID = "11111111-1111-4111-8111-111111111111"
SUBJECT_ID = "22222222-2222-4222-8222-222222222222"
OTHER_SUBJECT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
CLIENT_ID = "33333333-3333-4333-8333-333333333333"
AUDIENCE = "44444444-4444-4444-8444-444444444444"


class _CapturingLogger:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def info(self, message: str) -> None:
        self.messages.append(message)


class _MutableAuthenticator:
    authentication_required = True
    principal_access_enforced = True

    def __init__(self) -> None:
        self.tokens: dict[str, AuthenticatedPrincipal] = {}
        self.revoked: set[object] = set()
        self.authenticate_calls: list[str | None] = []
        self.block_next_admission_check = False
        self.admission_check_entered = threading.Event()
        self.admission_check_release = threading.Event()

    def authenticate(self, authorization: str | None) -> AuthenticatedPrincipal:
        self.authenticate_calls.append(authorization)
        if authorization is None or not authorization.startswith("Bearer "):
            raise AuthenticationFailure.missing()
        principal = self.tokens.get(authorization.removeprefix("Bearer "))
        if principal is None:
            raise AuthenticationFailure.invalid()
        if principal.key in self.revoked:
            raise AuthenticationFailure.forbidden()
        return principal

    def principal_is_admitted(self, principal: AuthenticatedPrincipal) -> bool:
        admitted = principal.key not in self.revoked
        if self.block_next_admission_check:
            self.block_next_admission_check = False
            self.admission_check_entered.set()
            if not self.admission_check_release.wait(timeout=2):
                return False
        return admitted

    def block_one_admission_check(self) -> None:
        self.admission_check_entered.clear()
        self.admission_check_release.clear()
        self.block_next_admission_check = True


def _principal(
    *,
    subject_id: str = SUBJECT_ID,
    expires_at_unix: int,
) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        tenant_id=TENANT_ID,
        subject_id=subject_id,
        client_id=CLIENT_ID,
        scopes=frozenset({"access_as_user"}),
        issued_at_unix=expires_at_unix - 3_600,
        expires_at_unix=expires_at_unix,
    )


def _start_event(session_id: str = "session-1") -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "sessionId": session_id,
        "eventSequence": 0,
        "eventType": "session.start",
        "metadata": {
            "sessionId": session_id,
            "mode": "dictation",
            "origin": "live_capture",
            "triggerMode": "toggle",
            "startedAtUtc": "2026-07-26T12:00:00Z",
            "utcOffsetMinutesAtStart": 0,
            "localeHintBcp47": "en-US",
            "countryCodeHint": "US",
            "preferredLanguagesBcp47": ["en-US"],
            "appVersion": "test",
            "platform": "test",
            "privacyPolicyVersion": "test-v1",
            "retentionExpiresAtUtc": "2026-07-27T12:00:00Z",
        },
        "tracks": [
            {
                "trackId": "track-1",
                "source": {"kind": "captured", "source": "microphone"},
                "deviceId": None,
                "originalSampleRateHz": 16_000,
                "originalChannels": 1,
            }
        ],
        "route": "server_live",
    }


def _chunk_event(
    payload: bytes,
    *,
    event_sequence: int = 1,
    session_id: str = "session-1",
    sequence_start: int = 0,
    sequence_end: int = 319,
) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "sessionId": session_id,
        "eventSequence": event_sequence,
        "eventType": "audio.chunk",
        "replayKey": {
            "schemaVersion": 1,
            "sessionId": session_id,
            "trackId": "track-1",
            "sequenceStart": sequence_start,
            "sequenceEnd": sequence_end,
        },
        "contentIdentity": {
            "sha256": hashlib.sha256(payload).hexdigest(),
            "byteLength": len(payload),
        },
        "audioCodec": "pcm_s16le",
        "sampleRateHz": 16_000,
        "channels": 1,
        "binaryFollows": True,
    }


def _ping_event(
    sequence: int,
    *,
    nonce: str = "ping-1",
    session_id: str = "session-1",
) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "sessionId": session_id,
        "eventSequence": sequence,
        "eventType": "ping",
        "nonce": nonce,
    }


def _gap_event(
    sequence: int,
    *,
    track_id: str = "track-1",
    session_id: str = "session-1",
) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "sessionId": session_id,
        "eventSequence": sequence,
        "eventType": "audio.gap",
        "gap": {
            "sessionId": session_id,
            "trackId": track_id,
            "startMs": 10,
            "durationMs": 20,
            "sourcePositionFrames": 160,
            "droppedFrames": 320,
            "cause": "device_discontinuity",
            "generation": 0,
        },
    }


def _send_json(connection: ClientConnection, event: dict[str, object]) -> None:
    connection.send(json.dumps(event, separators=(",", ":"), sort_keys=True))


def _recv_json(
    connection: ClientConnection,
    *,
    timeout: float = 2,
) -> dict[str, object]:
    message = connection.recv(timeout=timeout)
    if not isinstance(message, str):
        raise AssertionError("expected a JSON text message")
    value = json.loads(message)
    if not isinstance(value, dict):
        raise AssertionError("expected a JSON object")
    return value


class PrivateLiveWebSocketTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = int(time.time())
        self.logger = _CapturingLogger()
        self.authenticator = _MutableAuthenticator()
        self.authenticator.tokens["valid-token"] = _principal(
            expires_at_unix=self.now + 3_600
        )
        self.server = PrivateLiveWebSocketServer(
            self.authenticator,
            port=0,
            logger=self.logger,
            clock=lambda: self.now,
            authorization_recheck_seconds=0.02,
        ).start()

    def tearDown(self) -> None:
        self.server.close()
        self.assertEqual(self.server.active_connection_count, 0)
        self.assertEqual(self.server.registry.active_session_count, 0)
        self.assertEqual(self.server.registry.terminal_tombstone_count, 0)

    def _connect(
        self,
        token: str = "valid-token",
        *,
        path: str = "",
        subprotocols: Sequence[str] | None = (LIVE_SUBPROTOCOL,),
    ) -> ClientConnection:
        return connect(
            self.server.url + path,
            additional_headers={"Authorization": f"Bearer {token}"},
            subprotocols=subprotocols,
            proxy=None,
            open_timeout=2,
            close_timeout=1,
        )

    def test_connect_reconnect_replay_order_and_conflict_rejection(self) -> None:
        payload = b"\x01\x00" * 160
        start = _start_event()
        chunk = _chunk_event(payload)
        with self._connect() as connection:
            _send_json(connection, start)
            accepted = _recv_json(connection)
            self.assertEqual(
                (accepted["eventType"], accepted["eventSequence"]),
                ("session.accepted", 0),
            )
            self.assertEqual(connection.subprotocol, LIVE_SUBPROTOCOL)
            _send_json(connection, chunk)
            connection.send(payload)
            ping = _ping_event(2)
            _send_json(connection, ping)
            pong = _recv_json(connection)
            self.assertEqual(
                (pong["eventType"], pong["eventSequence"], pong["nonce"]),
                ("pong", 1, "ping-1"),
            )
            _send_json(connection, ping)
            with self.assertRaises(TimeoutError):
                connection.recv(timeout=0.05)

        with self._connect() as connection:
            _send_json(connection, start)
            accepted = _recv_json(connection)
            self.assertEqual(accepted["eventSequence"], 2)
            _send_json(connection, chunk)
            connection.send(payload)
            _send_json(connection, _ping_event(3, nonce="reconnected"))
            pong = _recv_json(connection)
            self.assertEqual(
                (pong["eventSequence"], pong["nonce"]),
                (3, "reconnected"),
            )

            conflicting_payload = b"\x02\x00" * 160
            conflicting = _chunk_event(
                conflicting_payload,
                event_sequence=4,
            )
            _send_json(connection, conflicting)
            error = _recv_json(connection)
            self.assertEqual(
                error["error"]["code"],
                "CONFLICTING_CHUNK_REPLAY",
            )
            with self.assertRaises(ConnectionClosed) as closed:
                connection.recv(timeout=1)
            self.assertEqual(closed.exception.rcvd.code, LIVE_CLOSE_PROTOCOL_ERROR)
        self.assertEqual(self.server.registry.active_session_count, 0)

    def test_stale_chunk_is_consumed_as_a_noop(self) -> None:
        payload = b"\x01\x00" * 160
        with self._connect() as connection:
            _send_json(connection, _start_event("session-stale"))
            _recv_json(connection)
            _send_json(
                connection,
                _ping_event(3, nonce="advance", session_id="session-stale"),
            )
            self.assertEqual(_recv_json(connection)["nonce"], "advance")

            stale = _chunk_event(
                payload,
                event_sequence=2,
                session_id="session-stale",
                sequence_start=320,
                sequence_end=479,
            )
            _send_json(connection, stale)
            connection.send(payload)
            _send_json(
                connection,
                _ping_event(4, nonce="after-stale", session_id="session-stale"),
            )
            self.assertEqual(_recv_json(connection)["nonce"], "after-stale")

            _send_json(
                connection,
                {
                    "schemaVersion": 1,
                    "sessionId": "session-stale",
                    "eventSequence": 5,
                    "eventType": "session.finish",
                    "lastAudioEventSequence": 0,
                },
            )
            self.assertEqual(
                _recv_json(connection)["error"]["code"],
                "LIVE_ASR_UNAVAILABLE",
            )
            self.assertEqual(_recv_json(connection)["status"], "failed")

    def test_same_chunk_identity_replay_does_not_advance_audio_state(self) -> None:
        payload = b"\x01\x00" * 160
        with self._connect() as connection:
            _send_json(connection, _start_event("session-idempotent"))
            _recv_json(connection)
            first = _chunk_event(
                payload,
                event_sequence=1,
                session_id="session-idempotent",
            )
            duplicate = _chunk_event(
                payload,
                event_sequence=2,
                session_id="session-idempotent",
            )
            _send_json(connection, first)
            connection.send(payload)
            _send_json(connection, duplicate)
            connection.send(payload)
            _send_json(
                connection,
                {
                    "schemaVersion": 1,
                    "sessionId": "session-idempotent",
                    "eventSequence": 3,
                    "eventType": "session.finish",
                    "lastAudioEventSequence": 1,
                },
            )
            self.assertEqual(
                _recv_json(connection)["error"]["code"],
                "LIVE_ASR_UNAVAILABLE",
            )
            self.assertEqual(_recv_json(connection)["status"], "failed")

    def test_gap_membership_cancellation_and_final_dedupe(self) -> None:
        start = _start_event("session-cancel")
        with self._connect() as connection:
            _send_json(connection, start)
            _recv_json(connection)
            _send_json(
                connection,
                _gap_event(1, session_id="session-cancel"),
            )
            _send_json(
                connection,
                {
                    "schemaVersion": 1,
                    "sessionId": "session-cancel",
                    "eventSequence": 2,
                    "eventType": "session.cancel",
                    "reason": "test cancellation",
                },
            )
            final = _recv_json(connection)
            self.assertEqual(
                (final["eventType"], final["status"]),
                ("session.finished", "cancelled"),
            )
        self.assertEqual(self.server.registry.active_session_count, 0)
        self.assertEqual(self.server.registry.terminal_tombstone_count, 1)

        with self._connect() as connection:
            _send_json(connection, start)
            replayed_final = _recv_json(connection)
            self.assertEqual(replayed_final, final)

        with self._connect() as connection:
            _send_json(connection, _start_event("session-gap"))
            _recv_json(connection)
            _send_json(
                connection,
                _gap_event(
                    1,
                    track_id="other-track",
                    session_id="session-gap",
                ),
            )
            error = _recv_json(connection)
            self.assertEqual(error["error"]["code"], "TRACK_NOT_IN_SESSION")

    def test_active_session_and_reconnect_are_bound_to_one_principal(self) -> None:
        self.authenticator.tokens["other-token"] = _principal(
            subject_id=OTHER_SUBJECT_ID,
            expires_at_unix=self.now + 3_600,
        )
        start = _start_event("session-owned")
        with self._connect() as owner:
            _send_json(owner, start)
            _recv_json(owner)

            with self._connect() as duplicate:
                _send_json(duplicate, start)
                with self.assertRaises(ConnectionClosed) as closed:
                    duplicate.recv(timeout=1)
                self.assertEqual(
                    closed.exception.rcvd.reason,
                    "SESSION_ALREADY_CONNECTED",
                )

            with self._connect("other-token") as other:
                _send_json(other, start)
                with self.assertRaises(ConnectionClosed) as closed:
                    other.recv(timeout=1)
                self.assertEqual(
                    closed.exception.rcvd.reason,
                    "LIVE_SESSION_NOT_FOUND",
                )

        with self._connect("other-token") as other:
            _send_json(other, start)
            with self.assertRaises(ConnectionClosed) as closed:
                other.recv(timeout=1)
            self.assertEqual(
                closed.exception.rcvd.reason,
                "LIVE_SESSION_NOT_FOUND",
            )

    def test_expiry_reauthentication_and_revocation_close_live_sessions(self) -> None:
        self.authenticator.tokens["missing-expiry-token"] = AuthenticatedPrincipal(
            tenant_id=TENANT_ID,
            subject_id=SUBJECT_ID,
            client_id=CLIENT_ID,
            scopes=frozenset({"access_as_user"}),
            issued_at_unix=self.now,
        )
        with self.assertRaises(InvalidStatus) as missing_expiry:
            self._connect("missing-expiry-token")
        self.assertEqual(
            missing_expiry.exception.response.status_code,
            HTTPStatus.UNAUTHORIZED,
        )

        expiring = _principal(expires_at_unix=self.now + 1)
        self.authenticator.tokens["expiring-token"] = expiring
        start = _start_event("session-expiry")
        with self._connect("expiring-token") as connection:
            _send_json(connection, start)
            _recv_json(connection)
            self.now += 2
            with self.assertRaises(ConnectionClosed) as closed:
                connection.recv(timeout=1)
            self.assertEqual(closed.exception.rcvd.code, LIVE_CLOSE_TOKEN_EXPIRED)

        renewed = _principal(expires_at_unix=self.now + 3_600)
        self.authenticator.tokens["renewed-token"] = renewed
        with self._connect("renewed-token") as connection:
            _send_json(connection, start)
            self.assertEqual(_recv_json(connection)["eventType"], "session.accepted")
            self.authenticator.revoked.add(renewed.key)
            with self.assertRaises(ConnectionClosed) as closed:
                connection.recv(timeout=1)
            self.assertEqual(closed.exception.rcvd.code, LIVE_CLOSE_ACCESS_REVOKED)

    def test_authority_is_rechecked_after_receive_before_protocol_mutation(
        self,
    ) -> None:
        principal = self.authenticator.tokens["valid-token"]
        self.authenticator.block_one_admission_check()
        with self._connect() as connection:
            self.assertTrue(self.authenticator.admission_check_entered.wait(timeout=1))
            self.authenticator.revoked.add(principal.key)
            self.authenticator.admission_check_release.set()
            _send_json(connection, _start_event("session-revoked-race"))
            with self.assertRaises(ConnectionClosed) as closed:
                connection.recv(timeout=1)
            self.assertEqual(closed.exception.rcvd.code, LIVE_CLOSE_ACCESS_REVOKED)
        self.authenticator.revoked.remove(principal.key)
        self.assertEqual(self.server.registry.active_session_count, 0)

        expiring = _principal(expires_at_unix=self.now + 1)
        self.authenticator.tokens["expiring-race-token"] = expiring
        self.authenticator.block_one_admission_check()
        with self._connect("expiring-race-token") as connection:
            self.assertTrue(self.authenticator.admission_check_entered.wait(timeout=1))
            self.now += 2
            self.authenticator.admission_check_release.set()
            _send_json(connection, _start_event("session-expired-race"))
            with self.assertRaises(ConnectionClosed) as closed:
                connection.recv(timeout=1)
            self.assertEqual(closed.exception.rcvd.code, LIVE_CLOSE_TOKEN_EXPIRED)
        self.assertEqual(self.server.registry.active_session_count, 0)

    def test_finish_is_truthful_about_transport_without_live_asr(self) -> None:
        with self._connect() as connection:
            _send_json(connection, _start_event("session-finish"))
            _recv_json(connection)
            _send_json(
                connection,
                {
                    "schemaVersion": 1,
                    "sessionId": "session-finish",
                    "eventSequence": 1,
                    "eventType": "session.finish",
                    "lastAudioEventSequence": 0,
                },
            )
            error = _recv_json(connection)
            final = _recv_json(connection)
            self.assertEqual(error["error"]["code"], "LIVE_ASR_UNAVAILABLE")
            self.assertEqual(final["status"], "failed")

    def test_header_only_auth_rejects_url_tokens_without_logging_them(self) -> None:
        secret = "url-secret-that-must-not-be-logged"
        with self.assertRaises(InvalidStatus) as invalid:
            self._connect(path=f"?access_token={secret}")
        self.assertEqual(invalid.exception.response.status_code, HTTPStatus.NOT_FOUND)

        with self.assertRaises(InvalidStatus) as invalid:
            connect(
                self.server.url,
                subprotocols=[LIVE_SUBPROTOCOL],
                proxy=None,
                open_timeout=2,
                close_timeout=1,
            )
        self.assertEqual(
            invalid.exception.response.status_code,
            HTTPStatus.UNAUTHORIZED,
        )
        serialized = "\n".join(self.logger.messages)
        self.assertNotIn(secret, serialized)
        self.assertNotIn("valid-token", serialized)
        self.assertNotIn("Authorization", serialized)

    def test_exact_live_subprotocol_is_required_and_negotiated(self) -> None:
        secret = "valid-subprotocol-secret"
        self.authenticator.tokens[secret] = _principal(expires_at_unix=self.now + 3_600)
        with self._connect(secret) as connection:
            self.assertEqual(connection.subprotocol, LIVE_SUBPROTOCOL)
        calls_after_valid_connection = len(self.authenticator.authenticate_calls)

        invalid_offers: tuple[Sequence[str] | None, ...] = (
            None,
            ("other.live.v1",),
            ("YAP.LIVE.V1",),
            (LIVE_SUBPROTOCOL, "other.live.v1"),
            ("other.live.v1", "another.live.v1"),
            (LIVE_SUBPROTOCOL, LIVE_SUBPROTOCOL),
        )
        for offered in invalid_offers:
            with self.subTest(offered=offered):
                with self.assertRaises(InvalidStatus) as invalid:
                    self._connect(secret, subprotocols=offered)
                self.assertEqual(
                    invalid.exception.response.status_code,
                    HTTPStatus.BAD_REQUEST,
                )
                self.assertNotIn(
                    secret,
                    str(invalid.exception.response.body),
                )

        self.assertEqual(
            len(self.authenticator.authenticate_calls),
            calls_after_valid_connection,
        )
        serialized = "\n".join(self.logger.messages)
        self.assertNotIn(secret, serialized)

    def test_rest_and_websocket_share_token_admission_semantics(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        settings = ServerSettings(
            host="127.0.0.1",
            port=0,
            authentication=ServerAuthenticationSettings(
                mode="entra",
                tenant_id=TENANT_ID,
                audience=AUDIENCE,
                required_scope="access_as_user",
                allowed_client_ids=(CLIENT_ID,),
                allowed_roles=("Yap.IdentityAdministrator",),
                identity_storage_dir=Path(temporary.name),
            ),
        )
        http_server = create_server(
            settings,
            request_authenticator=self.authenticator,
            asr_capabilities={"schemaVersion": 1},
        )
        http_thread = threading.Thread(
            target=http_server.serve_forever,
            kwargs={"poll_interval": 0.01},
            daemon=True,
        )
        http_thread.start()
        try:
            host, port = http_server.server_address[:2]
            endpoint = f"http://{host}:{port}/v1/asr/capabilities"
            with urlopen(
                Request(
                    endpoint,
                    headers={"Authorization": "Bearer valid-token"},
                ),
                timeout=2,
            ) as response:
                self.assertEqual(response.status, HTTPStatus.OK)
            with self.assertRaises(HTTPError) as invalid_rest:
                urlopen(
                    Request(
                        endpoint,
                        headers={"Authorization": "Bearer invalid-token"},
                    ),
                    timeout=2,
                )
            self.assertEqual(invalid_rest.exception.code, HTTPStatus.UNAUTHORIZED)
            with self.assertRaises(InvalidStatus) as invalid_ws:
                self._connect("invalid-token")
            self.assertEqual(
                invalid_ws.exception.response.status_code,
                HTTPStatus.UNAUTHORIZED,
            )
            with self._connect() as connection:
                _send_json(connection, _start_event("session-parity"))
                self.assertEqual(
                    _recv_json(connection)["eventType"],
                    "session.accepted",
                )
        finally:
            http_server.shutdown()
            http_server.server_close()
            http_thread.join(timeout=2)
            temporary.cleanup()

    def test_message_limits_abort_invalid_sessions_without_retention(self) -> None:
        with self._connect() as connection:
            _send_json(connection, _start_event("session-json-limit"))
            _recv_json(connection)
            oversized = {
                "schemaVersion": 1,
                "sessionId": "session-json-limit",
                "eventSequence": 1,
                "eventType": "ping",
                "nonce": "x" * MAX_JSON_MESSAGE_BYTES,
            }
            _send_json(connection, oversized)
            error = _recv_json(connection)
            self.assertEqual(error["error"]["code"], "JSON_MESSAGE_TOO_LARGE")
            with self.assertRaises(ConnectionClosed) as closed:
                connection.recv(timeout=1)
            self.assertEqual(closed.exception.rcvd.code, LIVE_CLOSE_PROTOCOL_ERROR)
        self.assertEqual(self.server.registry.active_session_count, 0)

        with self._connect() as connection:
            _send_json(connection, _start_event("session-binary-limit"))
            _recv_json(connection)
            connection.send(b"x" * (MAX_BINARY_MESSAGE_BYTES + 1))
            with self.assertRaises(ConnectionClosed) as closed:
                connection.recv(timeout=1)
            self.assertEqual(closed.exception.rcvd.code, 1009)
        deadline = time.monotonic() + 1
        while (
            self.server.registry.active_session_count != 0
            and time.monotonic() < deadline
        ):
            time.sleep(0.01)
        self.assertEqual(self.server.registry.active_session_count, 0)

    def test_connection_capacity_applies_handshake_backpressure(self) -> None:
        connections: list[ClientConnection] = []
        try:
            for _ in range(MAX_LIVE_CONNECTIONS):
                connections.append(self._connect())
            with self.assertRaises(InvalidStatus) as at_capacity:
                self._connect()
            self.assertEqual(
                at_capacity.exception.response.status_code,
                HTTPStatus.SERVICE_UNAVAILABLE,
            )
            self.assertEqual(
                at_capacity.exception.response.headers["Retry-After"],
                "1",
            )
        finally:
            for connection in connections:
                connection.close()

        deadline = time.monotonic() + 1
        while self.server.active_connection_count and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(self.server.active_connection_count, 0)
        with self._connect():
            pass

    def test_post_admission_pre_handler_disconnect_returns_permit_once(
        self,
    ) -> None:
        server = PrivateLiveWebSocketServer(
            self.authenticator,
            port=0,
            clock=lambda: self.now,
        )
        connection = SimpleNamespace()
        request = SimpleNamespace(
            path="/v1/live",
            headers=Headers(
                [
                    ("Sec-WebSocket-Protocol", LIVE_SUBPROTOCOL),
                    ("Authorization", "Bearer valid-token"),
                ]
            ),
        )
        switching_response = SimpleNamespace(status_code=HTTPStatus.SWITCHING_PROTOCOLS)
        admitted = threading.Event()
        handler_socket = Mock(spec=socket.socket)
        errors: list[BaseException] = []

        def dependency_handler(_socket: socket.socket, _address: object) -> None:
            self.assertIsNone(server._process_request(connection, request))
            self.assertIs(
                server._process_response(
                    connection,
                    request,
                    switching_response,
                ),
                switching_response,
            )
            admitted.set()
            # Model the transport returning after the 101 response fails,
            # before the application connection handler is invoked.

        dependency_server = SimpleNamespace(handler=dependency_handler)

        def run_handler() -> None:
            try:
                server._run_socket_handler(
                    dependency_server,
                    handler_socket,
                    ("127.0.0.1", 1),
                )
            except BaseException as error:
                errors.append(error)

        handler_thread = threading.Thread(target=run_handler)
        self.assertTrue(server._handler_slots.acquire(blocking=False))
        with server._connections_lock:
            server._handler_threads.add(handler_thread)
            server._handler_sockets[handler_thread] = handler_socket
        handler_thread.start()
        handler_thread.join(timeout=1)

        self.assertFalse(handler_thread.is_alive())
        self.assertTrue(admitted.is_set())
        self.assertEqual(errors, [])

        acquired_permits = 0
        try:
            for _ in range(MAX_LIVE_CONNECTIONS):
                self.assertTrue(server._connection_slots.acquire(blocking=False))
                acquired_permits += 1
            self.assertFalse(server._connection_slots.acquire(blocking=False))
        finally:
            for _ in range(acquired_permits):
                server._connection_slots.release()
            server.close()

    def test_incomplete_handshakes_are_bounded_and_owned_through_shutdown(
        self,
    ) -> None:
        sockets: list[socket.socket] = []
        try:
            for _ in range(MAX_LIVE_HANDLER_THREADS + 8):
                sockets.append(socket.create_connection(self.server.address, timeout=1))
            deadline = time.monotonic() + 1
            while (
                self.server.active_handler_count < MAX_LIVE_HANDLER_THREADS
                and time.monotonic() < deadline
            ):
                time.sleep(0.01)
            self.assertEqual(
                self.server.active_handler_count,
                MAX_LIVE_HANDLER_THREADS,
            )

            self.server.close()
            self.assertEqual(self.server.active_handler_count, 0)
            self.assertEqual(self.server.active_connection_count, 0)
        finally:
            for raw_socket in sockets:
                raw_socket.close()

    def test_failed_shutdown_retains_registry_and_handler_ownership(self) -> None:
        registry = Mock()
        server = PrivateLiveWebSocketServer(
            self.authenticator,
            port=0,
            registry=registry,
        )
        release = threading.Event()
        handler = threading.Thread(target=release.wait, daemon=True)
        handler.start()
        with server._connections_lock:
            server._handler_threads.add(handler)
        try:
            with (
                patch(
                    "yap_server.live.websocket_server._SHUTDOWN_TIMEOUT_SECONDS",
                    0.01,
                ),
                self.assertRaisesRegex(RuntimeError, "did not stop"),
            ):
                server.close()
            registry.clear.assert_not_called()
            self.assertIn(handler, server._handler_threads)
        finally:
            release.set()
            handler.join(timeout=1)
            with server._connections_lock:
                server._handler_threads.discard(handler)
            server.close()
        registry.clear.assert_called_once_with()

    def test_start_rejects_properties_outside_the_bounded_contract(self) -> None:
        invalid = _start_event("session-invalid-start")
        metadata = invalid["metadata"]
        assert isinstance(metadata, dict)
        metadata["unexpectedAuthority"] = "must-not-be-accepted"

        with self._connect() as connection:
            _send_json(connection, invalid)
            with self.assertRaises(ConnectionClosed) as closed:
                connection.recv(timeout=1)
            self.assertEqual(closed.exception.rcvd.code, LIVE_CLOSE_PROTOCOL_ERROR)
            self.assertEqual(closed.exception.rcvd.reason, "INVALID_LIVE_EVENT")
        self.assertEqual(self.server.registry.active_session_count, 0)

    def test_private_port_configuration_is_bounded(self) -> None:
        self.assertEqual(private_live_port_from_env({}), 18_766)
        self.assertEqual(
            private_live_port_from_env({"YAP_SERVER_LIVE_PORT": "0"}),
            0,
        )
        for value in ("invalid", "-1", "65536"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    private_live_port_from_env({"YAP_SERVER_LIVE_PORT": value})


if __name__ == "__main__":
    unittest.main()
