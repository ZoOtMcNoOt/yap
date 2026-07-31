from __future__ import annotations

from http import HTTPStatus
import json
import logging
import os
import socket
import threading
import time
from typing import Any, Callable, Mapping, cast
from urllib.parse import urlsplit

from websockets.exceptions import ConnectionClosed
from websockets.http11 import Request, Response
from websockets.sync.server import Server, ServerConnection, serve

from yap_server.auth import (
    AuthenticatedPrincipal,
    AuthenticationFailure,
    RequestAuthenticator,
)
from yap_server.live.protocol import (
    LiveConnectionProtocol,
    LiveProtocolError,
    LiveSessionRegistry,
    MAX_BINARY_MESSAGE_BYTES,
)


PRIVATE_LIVE_HOST = "127.0.0.1"
DEFAULT_PRIVATE_LIVE_PORT = 18766
PRIVATE_LIVE_PORT_ENV = "YAP_SERVER_LIVE_PORT"
LIVE_SUBPROTOCOL = "yap.live.v1"
MAX_LIVE_CONNECTIONS = 8
MAX_LIVE_HANDLER_THREADS = MAX_LIVE_CONNECTIONS + 4
AUTHORIZATION_RECHECK_SECONDS = 0.25
MAX_QUEUED_FRAMES = (8, 2)
_ACCEPT_POLL_SECONDS = 0.1
_SHUTDOWN_TIMEOUT_SECONDS = 5.0
LIVE_CLOSE_TOKEN_EXPIRED = 4001
LIVE_CLOSE_PROTOCOL_ERROR = 4002
LIVE_CLOSE_ACCESS_REVOKED = 4003

_APPLICATION_LOGGER = logging.getLogger("yap_server.live")


def private_live_port_from_env(
    environ: Mapping[str, str] | None = None,
) -> int:
    source = os.environ if environ is None else environ
    value = source.get(PRIVATE_LIVE_PORT_ENV, str(DEFAULT_PRIVATE_LIVE_PORT)).strip()
    try:
        port = int(value, 10)
    except ValueError as error:
        raise ValueError(f"{PRIVATE_LIVE_PORT_ENV} must be an integer") from error
    if not 0 <= port <= 65_535:
        raise ValueError(f"{PRIVATE_LIVE_PORT_ENV} must be between 0 and 65535")
    return port


def _disabled_dependency_logger() -> logging.Logger:
    logger = logging.Logger("yap_server.live.websocket.internal", logging.CRITICAL + 1)
    logger.propagate = False
    return logger


class PrivateLiveWebSocketServer:
    """Lifecycle owner for the loopback WebSocket application transport."""

    def __init__(
        self,
        request_authenticator: RequestAuthenticator,
        *,
        port: int = DEFAULT_PRIVATE_LIVE_PORT,
        logger: logging.Logger | None = None,
        clock: Callable[[], float] = time.time,
        authorization_recheck_seconds: float = AUTHORIZATION_RECHECK_SECONDS,
        registry: LiveSessionRegistry | None = None,
    ) -> None:
        if not request_authenticator.authentication_required:
            raise ValueError("live WebSocket transport requires token authentication")
        if not request_authenticator.principal_access_enforced:
            raise ValueError("live WebSocket transport requires principal admission")
        if not callable(getattr(request_authenticator, "principal_is_admitted", None)):
            raise ValueError(
                "live WebSocket transport requires revocation-aware admission"
            )
        if (
            isinstance(port, bool)
            or not isinstance(port, int)
            or not 0 <= port <= 65_535
        ):
            raise ValueError("private live WebSocket port is invalid")
        if authorization_recheck_seconds <= 0:
            raise ValueError("authorization recheck interval must be positive")
        self._request_authenticator = request_authenticator
        self._port = port
        self._logger = logger or _APPLICATION_LOGGER
        self._clock = clock
        self._authorization_recheck_seconds = authorization_recheck_seconds
        self._registry = registry or LiveSessionRegistry()
        self._connection_slots = threading.BoundedSemaphore(MAX_LIVE_CONNECTIONS)
        self._handler_slots = threading.BoundedSemaphore(MAX_LIVE_HANDLER_THREADS)
        self._handler_context = threading.local()
        self._connections: set[ServerConnection] = set()
        self._handler_threads: set[threading.Thread] = set()
        self._handler_sockets: dict[threading.Thread, socket.socket] = {}
        self._connections_lock = threading.Condition()
        self._closing = threading.Event()
        self._ready = threading.Event()
        self._server: Server | None = None
        self._thread: threading.Thread | None = None
        self._startup_error: BaseException | None = None
        self._address: tuple[str, int] | None = None

    @property
    def authenticator(self) -> RequestAuthenticator:
        return self._request_authenticator

    @property
    def registry(self) -> LiveSessionRegistry:
        return self._registry

    @property
    def address(self) -> tuple[str, int]:
        if self._address is None:
            raise RuntimeError("private live WebSocket server isn't running")
        return self._address

    @property
    def url(self) -> str:
        host, port = self.address
        return f"ws://{host}:{port}/v1/live"

    @property
    def active_connection_count(self) -> int:
        with self._connections_lock:
            return len(self._connections)

    @property
    def active_handler_count(self) -> int:
        with self._connections_lock:
            return len(self._handler_threads)

    def start(self) -> PrivateLiveWebSocketServer:
        with self._connections_lock:
            if self._thread is not None:
                raise RuntimeError("private live WebSocket server already started")
            self._closing.clear()
            self._ready.clear()
            self._startup_error = None
            self._address = None
            self._thread = threading.Thread(
                target=self._serve,
                name="yap-private-live-websocket",
                daemon=True,
            )
            self._thread.start()
        if not self._ready.wait(timeout=5):
            self.close()
            raise RuntimeError("private live WebSocket server didn't become ready")
        if self._startup_error is not None:
            error = self._startup_error
            self.close()
            raise RuntimeError(
                "private live WebSocket server failed to start"
            ) from error
        return self

    def close(self) -> None:
        self._closing.set()
        with self._connections_lock:
            server = self._server
            thread = self._thread
            sockets = tuple(self._handler_sockets.values())
        if server is not None:
            server.shutdown()
        for handler_socket in sockets:
            self._close_handler_socket(handler_socket)

        deadline = time.monotonic() + _SHUTDOWN_TIMEOUT_SECONDS
        if (
            thread is not None
            and thread.is_alive()
            and thread is not threading.current_thread()
        ):
            thread.join(timeout=max(0.0, deadline - time.monotonic()))
        with self._connections_lock:
            while self._handler_threads or self._connections:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._connections_lock.wait(timeout=remaining)
            accept_stopped = thread is None or not thread.is_alive()
            handlers_stopped = not self._handler_threads and not self._connections
            if accept_stopped and handlers_stopped:
                self._registry.clear()
                self._server = None
                self._thread = None
                self._address = None
                return
        raise RuntimeError("private live WebSocket connections did not stop")

    def __enter__(self) -> PrivateLiveWebSocketServer:
        return self.start()

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _serve(self) -> None:
        try:
            with serve(
                self._handle_connection,
                PRIVATE_LIVE_HOST,
                self._port,
                origins=[None],
                subprotocols=[LIVE_SUBPROTOCOL],
                compression=None,
                process_request=self._process_request,
                process_response=self._process_response,
                server_header=None,
                open_timeout=5,
                ping_interval=20,
                ping_timeout=20,
                close_timeout=2,
                max_size=MAX_BINARY_MESSAGE_BYTES,
                max_queue=MAX_QUEUED_FRAMES,
                logger=_disabled_dependency_logger(),
            ) as server:
                self._server = server
                socket_address = server.socket.getsockname()
                self._address = (str(socket_address[0]), int(socket_address[1]))
                self._ready.set()
                self._serve_bounded(server)
        except BaseException as error:
            if not self._closing.is_set():
                self._startup_error = error
                self._safe_log("live_runtime_failure")
            self._ready.set()
        finally:
            self._ready.set()

    def _serve_bounded(self, server: Server) -> None:
        server.socket.settimeout(_ACCEPT_POLL_SECONDS)
        while not self._closing.is_set():
            try:
                handler_socket, address = server.socket.accept()
            except TimeoutError:
                continue
            except OSError:
                if self._closing.is_set():
                    return
                raise
            if not self._handler_slots.acquire(blocking=False):
                self._close_handler_socket(handler_socket)
                self._safe_log("live_handler_capacity_rejected")
                continue

            handler_thread = threading.Thread(
                target=self._run_socket_handler,
                args=(server, handler_socket, address),
                name="yap-private-live-handler",
            )
            with self._connections_lock:
                if self._closing.is_set():
                    self._handler_slots.release()
                    self._close_handler_socket(handler_socket)
                    continue
                self._handler_threads.add(handler_thread)
                self._handler_sockets[handler_thread] = handler_socket
            try:
                handler_thread.start()
            except BaseException:
                with self._connections_lock:
                    self._handler_threads.discard(handler_thread)
                    self._handler_sockets.pop(handler_thread, None)
                    self._connections_lock.notify_all()
                self._handler_slots.release()
                self._close_handler_socket(handler_socket)
                raise

    def _run_socket_handler(
        self,
        server: Server,
        handler_socket: socket.socket,
        address: Any,
    ) -> None:
        current = threading.current_thread()
        try:
            server.handler(handler_socket, address)
        finally:
            admitted_connection = cast(
                ServerConnection | None,
                getattr(self._handler_context, "admitted_connection", None),
            )
            if admitted_connection is not None:
                self._release_slot(admitted_connection)
                del self._handler_context.admitted_connection
            with self._connections_lock:
                self._handler_threads.discard(current)
                self._handler_sockets.pop(current, None)
                self._connections_lock.notify_all()
            self._handler_slots.release()

    @staticmethod
    def _close_handler_socket(handler_socket: socket.socket) -> None:
        try:
            handler_socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            handler_socket.close()
        except OSError:
            pass

    def _process_request(
        self,
        connection: ServerConnection,
        request: Request,
    ) -> Response | None:
        if self._closing.is_set():
            return self._handshake_error(
                connection,
                HTTPStatus.SERVICE_UNAVAILABLE,
                "LIVE_SERVER_CLOSING",
                retry_after=True,
            )
        try:
            target = urlsplit(request.path)
        except ValueError:
            return self._handshake_error(
                connection,
                HTTPStatus.BAD_REQUEST,
                "INVALID_REQUEST_TARGET",
            )
        if (
            target.scheme
            or target.netloc
            or target.path != "/v1/live"
            or target.query
            or target.fragment
        ):
            return self._handshake_error(
                connection,
                HTTPStatus.NOT_FOUND,
                "LIVE_ROUTE_NOT_FOUND",
            )
        subprotocol_values = request.headers.get_all("Sec-WebSocket-Protocol")
        if subprotocol_values != [LIVE_SUBPROTOCOL]:
            return self._handshake_error(
                connection,
                HTTPStatus.BAD_REQUEST,
                "LIVE_SUBPROTOCOL_REQUIRED",
            )
        authorization_values = request.headers.get_all("Authorization")
        try:
            if len(authorization_values) > 1:
                raise AuthenticationFailure.invalid()
            principal = self._request_authenticator.authenticate(
                authorization_values[0] if authorization_values else None
            )
            expires_at = getattr(principal, "expires_at_unix", None)
            if (
                isinstance(expires_at, bool)
                or not isinstance(expires_at, int)
                or expires_at <= int(self._clock())
            ):
                raise AuthenticationFailure.invalid()
        except AuthenticationFailure as error:
            response = self._handshake_error(
                connection,
                error.status,
                error.code,
            )
            if error.challenge is not None:
                response.headers["WWW-Authenticate"] = error.challenge
            return response
        finally:
            if authorization_values:
                try:
                    del request.headers["Authorization"]
                except KeyError:
                    pass
        if self._closing.is_set():
            return self._handshake_error(
                connection,
                HTTPStatus.SERVICE_UNAVAILABLE,
                "LIVE_SERVER_CLOSING",
                retry_after=True,
            )
        if not self._connection_slots.acquire(blocking=False):
            return self._handshake_error(
                connection,
                HTTPStatus.SERVICE_UNAVAILABLE,
                "LIVE_CONNECTION_LIMIT",
                retry_after=True,
            )
        setattr(connection, "_yap_slot_acquired", True)
        setattr(connection, "_yap_principal", principal)
        self._handler_context.admitted_connection = connection
        if self._closing.is_set():
            self._release_slot(connection)
            return self._handshake_error(
                connection,
                HTTPStatus.SERVICE_UNAVAILABLE,
                "LIVE_SERVER_CLOSING",
                retry_after=True,
            )
        self._safe_log("live_handshake_admitted")
        return None

    def _process_response(
        self,
        connection: ServerConnection,
        _request: Request,
        response: Response,
    ) -> Response | None:
        if response.status_code != HTTPStatus.SWITCHING_PROTOCOLS:
            self._release_slot(connection)
        return response

    def _handshake_error(
        self,
        connection: ServerConnection,
        status: HTTPStatus,
        code: str,
        *,
        retry_after: bool = False,
    ) -> Response:
        response = connection.respond(
            status,
            json.dumps(
                {"code": code, "message": "Live WebSocket admission failed."},
                ensure_ascii=True,
                separators=(",", ":"),
            )
            + "\n",
        )
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Type"] = "application/json"
        if retry_after:
            response.headers["Retry-After"] = "1"
        self._safe_log("live_handshake_rejected", status=int(status), code=code)
        return response

    def _handle_connection(self, connection: ServerConnection) -> None:
        principal = cast(
            AuthenticatedPrincipal,
            getattr(connection, "_yap_principal"),
        )
        connection_id = str(connection.id)
        request_id = f"live-{connection.id.hex}"
        protocol = LiveConnectionProtocol(
            self._registry,
            principal,
            connection_id,
        )
        with self._connections_lock:
            self._connections.add(connection)
        try:
            while True:
                if self._closing.is_set():
                    break
                remaining = self._remaining_authorized_seconds(
                    connection,
                    principal,
                )
                if remaining is None:
                    break
                try:
                    message = connection.recv(
                        timeout=min(
                            self._authorization_recheck_seconds,
                            max(remaining, 0.001),
                        )
                    )
                except TimeoutError:
                    continue
                if self._remaining_authorized_seconds(connection, principal) is None:
                    break
                try:
                    result = protocol.receive(message, request_id=request_id)
                except LiveProtocolError as error:
                    outbound = protocol.error_event(error, request_id=request_id)
                    if outbound is not None:
                        self._send_json(connection, outbound)
                    protocol.abort()
                    connection.close(LIVE_CLOSE_PROTOCOL_ERROR, error.code)
                    self._safe_log("live_protocol_rejected", code=error.code)
                    break
                for outbound in result.outbound:
                    self._send_json(connection, outbound)
                if result.close:
                    connection.close(1000, "live session complete")
                    break
        except ConnectionClosed as closed:
            close_frame = closed.rcvd or closed.sent
            if close_frame is not None and close_frame.code in {
                1002,
                1003,
                1007,
                1008,
                1009,
            }:
                protocol.abort()
        finally:
            protocol.disconnect()
            with self._connections_lock:
                self._connections.discard(connection)
                self._connections_lock.notify_all()
            self._release_slot(connection)
            self._safe_log("live_connection_closed")

    def _remaining_authorized_seconds(
        self,
        connection: ServerConnection,
        principal: AuthenticatedPrincipal,
    ) -> float | None:
        expiry = cast(int, getattr(principal, "expires_at_unix"))
        remaining = expiry - self._clock()
        if remaining <= 0:
            connection.close(
                LIVE_CLOSE_TOKEN_EXPIRED,
                "access token expired",
            )
            return None
        if not self._principal_is_admitted(principal):
            connection.close(
                LIVE_CLOSE_ACCESS_REVOKED,
                "principal access revoked",
            )
            return None
        return remaining

    def _principal_is_admitted(self, principal: AuthenticatedPrincipal) -> bool:
        checker = getattr(self._request_authenticator, "principal_is_admitted")
        try:
            return bool(checker(principal))
        except BaseException:
            return False

    @staticmethod
    def _send_json(
        connection: ServerConnection,
        event: Mapping[str, object],
    ) -> None:
        connection.send(
            json.dumps(
                event,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            )
        )

    def _release_slot(self, connection: ServerConnection) -> None:
        if getattr(connection, "_yap_slot_acquired", False):
            setattr(connection, "_yap_slot_acquired", False)
            self._connection_slots.release()

    def _safe_log(self, event: str, **fields: object) -> None:
        payload = {"event": event, **fields}
        try:
            self._logger.info(
                json.dumps(
                    payload,
                    ensure_ascii=True,
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
        except Exception:
            pass


__all__ = [
    "DEFAULT_PRIVATE_LIVE_PORT",
    "LIVE_CLOSE_ACCESS_REVOKED",
    "LIVE_CLOSE_PROTOCOL_ERROR",
    "LIVE_CLOSE_TOKEN_EXPIRED",
    "LIVE_SUBPROTOCOL",
    "MAX_LIVE_HANDLER_THREADS",
    "PRIVATE_LIVE_HOST",
    "PrivateLiveWebSocketServer",
    "private_live_port_from_env",
]
