from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from typing import Protocol

from yap_server.auth.principal import AuthenticatedPrincipal


_DEVELOPMENT_PRINCIPAL = AuthenticatedPrincipal(
    tenant_id="development-loopback",
    subject_id="local-server",
    client_id="yap-development-client",
    scopes=frozenset({"access_as_user"}),
)


@dataclass(frozen=True, slots=True)
class AuthenticationFailure(Exception):
    status: HTTPStatus
    code: str
    message: str
    challenge: str | None = None
    retryable: bool = False

    @classmethod
    def missing(cls) -> AuthenticationFailure:
        return cls(
            HTTPStatus.UNAUTHORIZED,
            "AUTHENTICATION_REQUIRED",
            "A Yap API access token is required.",
            "Bearer",
        )

    @classmethod
    def invalid(cls) -> AuthenticationFailure:
        return cls(
            HTTPStatus.UNAUTHORIZED,
            "INVALID_ACCESS_TOKEN",
            "The Yap API access token is invalid.",
            "Bearer",
        )

    @classmethod
    def forbidden(
        cls,
        *,
        code: str = "ACCESS_DENIED",
        message: str = "The authenticated principal is not authorized.",
    ) -> AuthenticationFailure:
        return cls(HTTPStatus.FORBIDDEN, code, message)

    @classmethod
    def unavailable(cls) -> AuthenticationFailure:
        return cls(
            HTTPStatus.SERVICE_UNAVAILABLE,
            "AUTHENTICATION_UNAVAILABLE",
            "Yap could not validate the access token.",
            retryable=True,
        )


class RequestAuthenticator(Protocol):
    authentication_required: bool
    principal_access_enforced: bool

    def authenticate(self, authorization: str | None) -> AuthenticatedPrincipal:
        """Validate one Authorization value and return immutable authority."""


class DevelopmentLoopbackAuthenticator:
    authentication_required = False
    principal_access_enforced = False

    def authenticate(self, authorization: str | None) -> AuthenticatedPrincipal:
        del authorization
        return _DEVELOPMENT_PRINCIPAL


class AuthenticationDisabledAuthenticator:
    """Fail-closed default without approved identity configuration."""

    authentication_required = True
    principal_access_enforced = True

    def authenticate(self, authorization: str | None) -> AuthenticatedPrincipal:
        del authorization
        raise AuthenticationFailure.unavailable()
