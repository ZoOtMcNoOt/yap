from __future__ import annotations

import os
from dataclasses import dataclass
from ipaddress import ip_address
from pathlib import Path
from typing import Literal, Mapping
from uuid import UUID


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 18765
PRIVATE_BIND_OPT_IN = "YAP_SERVER_ALLOW_PRIVATE_BIND"
AUTH_MODE = "YAP_AUTH_MODE"
ENTRA_TENANT_ID = "YAP_ENTRA_TENANT_ID"
ENTRA_AUDIENCE = "YAP_ENTRA_AUDIENCE"
ENTRA_ALLOWED_CLIENT_IDS = "YAP_ENTRA_ALLOWED_CLIENT_IDS"
ENTRA_REQUIRED_SCOPE = "YAP_ENTRA_REQUIRED_SCOPE"
IDENTITY_STORAGE_DIR = "YAP_IDENTITY_STORAGE_DIR"
DEVELOPMENT_AUTH_MODE = "development_loopback"
ENTRA_AUTH_MODE = "entra"
DEFAULT_ENTRA_SCOPE = "access_as_user"


def _is_loopback(host: str) -> bool:
    if host.casefold().rstrip(".") == "localhost":
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


def ensure_bind_is_allowed(
    host: str,
    environ: Mapping[str, str] | None = None,
) -> None:
    source = os.environ if environ is None else environ
    if _is_loopback(host):
        return
    if source.get(PRIVATE_BIND_OPT_IN) == "1":
        return
    raise ValueError(f"YAP_SERVER_HOST must be loopback unless {PRIVATE_BIND_OPT_IN}=1")


def _required_uuid(value: str | None, variable: str) -> str:
    if value is None or not value.strip():
        raise ValueError(f"{variable} is required in Entra mode")
    text = value.strip().lower()
    try:
        parsed = UUID(text)
    except ValueError as error:
        raise ValueError(f"{variable} must be a valid UUID") from error
    if str(parsed) != text:
        raise ValueError(f"{variable} must be a canonical UUID")
    return text


def _required_scope(value: str | None) -> str:
    scope = DEFAULT_ENTRA_SCOPE if value is None else value.strip()
    if (
        not scope
        or len(scope) > 128
        or not scope.isascii()
        or not scope.isprintable()
        or any(character.isspace() for character in scope)
    ):
        raise ValueError(f"{ENTRA_REQUIRED_SCOPE} is invalid")
    return scope


def _allowed_client_ids(value: str | None) -> tuple[str, ...]:
    if value is None or not value.strip():
        raise ValueError(f"{ENTRA_ALLOWED_CLIENT_IDS} is required in Entra mode")
    raw_values = [entry.strip() for entry in value.split(",")]
    if not all(raw_values):
        raise ValueError(f"{ENTRA_ALLOWED_CLIENT_IDS} contains an empty entry")
    clients = tuple(
        _required_uuid(entry, ENTRA_ALLOWED_CLIENT_IDS) for entry in raw_values
    )
    if len(set(clients)) != len(clients):
        raise ValueError(f"{ENTRA_ALLOWED_CLIENT_IDS} must not contain duplicates")
    return tuple(sorted(clients))


def _identity_storage_dir(value: str | None) -> Path:
    if value is None or not value.strip():
        raise ValueError(f"{IDENTITY_STORAGE_DIR} is required in Entra mode")
    path = Path(value.strip())
    if path.name in {"", ".", ".."}:
        raise ValueError(f"{IDENTITY_STORAGE_DIR} is invalid")
    return path


@dataclass(frozen=True, slots=True)
class ServerAuthenticationSettings:
    mode: Literal["development_loopback", "entra"] = DEVELOPMENT_AUTH_MODE
    tenant_id: str | None = None
    audience: str | None = None
    required_scope: str | None = None
    allowed_client_ids: tuple[str, ...] = ()
    identity_storage_dir: Path | None = None

    def __post_init__(self) -> None:
        if self.mode not in {DEVELOPMENT_AUTH_MODE, ENTRA_AUTH_MODE}:
            raise ValueError(
                f"{AUTH_MODE} must be {DEVELOPMENT_AUTH_MODE!r} or {ENTRA_AUTH_MODE!r}"
            )
        if self.mode == DEVELOPMENT_AUTH_MODE:
            if (
                self.tenant_id is not None
                or self.audience is not None
                or self.required_scope is not None
                or self.allowed_client_ids
                or self.identity_storage_dir is not None
            ):
                raise ValueError(
                    "development authentication cannot include Entra configuration"
                )
            return
        object.__setattr__(
            self,
            "tenant_id",
            _required_uuid(self.tenant_id, ENTRA_TENANT_ID),
        )
        object.__setattr__(
            self,
            "audience",
            _required_uuid(self.audience, ENTRA_AUDIENCE),
        )
        object.__setattr__(
            self,
            "required_scope",
            _required_scope(self.required_scope),
        )
        clients = tuple(
            _required_uuid(value, ENTRA_ALLOWED_CLIENT_IDS)
            for value in self.allowed_client_ids
        )
        if not clients:
            raise ValueError(f"{ENTRA_ALLOWED_CLIENT_IDS} is required in Entra mode")
        if len(set(clients)) != len(clients):
            raise ValueError(f"{ENTRA_ALLOWED_CLIENT_IDS} must not contain duplicates")
        object.__setattr__(self, "allowed_client_ids", tuple(sorted(clients)))
        if self.identity_storage_dir is None:
            raise ValueError(f"{IDENTITY_STORAGE_DIR} is required in Entra mode")
        object.__setattr__(
            self,
            "identity_storage_dir",
            Path(self.identity_storage_dir),
        )

    @property
    def required(self) -> bool:
        return self.mode == ENTRA_AUTH_MODE

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str],
    ) -> ServerAuthenticationSettings:
        mode = environ.get(AUTH_MODE, DEVELOPMENT_AUTH_MODE).strip()
        if mode == DEVELOPMENT_AUTH_MODE:
            return cls()
        if mode != ENTRA_AUTH_MODE:
            raise ValueError(
                f"{AUTH_MODE} must be {DEVELOPMENT_AUTH_MODE!r} or {ENTRA_AUTH_MODE!r}"
            )
        return cls(
            mode=ENTRA_AUTH_MODE,
            tenant_id=_required_uuid(environ.get(ENTRA_TENANT_ID), ENTRA_TENANT_ID),
            audience=_required_uuid(environ.get(ENTRA_AUDIENCE), ENTRA_AUDIENCE),
            required_scope=_required_scope(environ.get(ENTRA_REQUIRED_SCOPE)),
            allowed_client_ids=_allowed_client_ids(
                environ.get(ENTRA_ALLOWED_CLIENT_IDS)
            ),
            identity_storage_dir=_identity_storage_dir(
                environ.get(IDENTITY_STORAGE_DIR)
            ),
        )


def ensure_authentication_bind_is_allowed(
    host: str,
    authentication: ServerAuthenticationSettings,
) -> None:
    if _is_loopback(host) or authentication.required:
        return
    raise ValueError("a non-loopback Yap server bind requires authenticated team mode")


@dataclass(frozen=True, slots=True)
class ServerSettings:
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    authentication: ServerAuthenticationSettings = ServerAuthenticationSettings()

    def __post_init__(self) -> None:
        if not isinstance(self.host, str) or not self.host.strip():
            raise ValueError("YAP_SERVER_HOST must not be empty")
        if isinstance(self.port, bool) or not isinstance(self.port, int):
            raise ValueError("YAP_SERVER_PORT must be an integer")
        if not 0 <= self.port <= 65535:
            raise ValueError("YAP_SERVER_PORT must be between 0 and 65535")

    @classmethod
    def from_env(cls) -> ServerSettings:
        host = os.environ.get("YAP_SERVER_HOST", DEFAULT_HOST).strip()
        port_text = os.environ.get("YAP_SERVER_PORT", str(DEFAULT_PORT)).strip()
        try:
            port = int(port_text, 10)
        except ValueError as error:
            raise ValueError("YAP_SERVER_PORT must be an integer") from error

        settings = cls(host=host, port=port)
        ensure_bind_is_allowed(settings.host)
        authentication = ServerAuthenticationSettings.from_env(os.environ)
        settings = cls(
            host=host,
            port=port,
            authentication=authentication,
        )
        ensure_authentication_bind_is_allowed(
            settings.host,
            settings.authentication,
        )
        return settings
