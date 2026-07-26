from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import stat

from yap_server.auth.identity_repository import SqliteIdentityRepository
from yap_server.auth.principal_admission import (
    PrincipalAdmissionRepository,
    PrincipalAdmissionUnavailable,
)
from yap_server.auth.principal import AuthenticatedPrincipal
from yap_server.auth.request_authentication import (
    AuthenticationFailure,
    RequestAuthenticator,
)
from yap_server.config import ServerAuthenticationSettings


class RepositoryBackedRequestAuthenticator:
    """Composes token validation with durable principal access policy."""

    authentication_required = True
    principal_access_enforced = True

    def __init__(
        self,
        token_authenticator: RequestAuthenticator,
        identity_repository: PrincipalAdmissionRepository,
    ) -> None:
        if not token_authenticator.authentication_required:
            raise ValueError("repository authorization requires token authentication")
        self._token_authenticator = token_authenticator
        self._identity_repository = identity_repository

    def authenticate(self, authorization: str | None) -> AuthenticatedPrincipal:
        principal = self._token_authenticator.authenticate(authorization)
        try:
            admitted = self._identity_repository.admit_principal(principal)
        except PrincipalAdmissionUnavailable as error:
            raise AuthenticationFailure.unavailable() from error
        if not admitted:
            raise AuthenticationFailure.forbidden(
                code="PRINCIPAL_ACCESS_REVOKED",
                message="The authenticated principal is not authorized.",
            )
        return principal


@dataclass(slots=True)
class RequestAuthorizationRuntime:
    authenticator: RequestAuthenticator
    identity_repository: SqliteIdentityRepository | None = None

    def close(self) -> None:
        if self.identity_repository is not None:
            self.identity_repository.close()


def build_request_authorization_runtime(
    settings: ServerAuthenticationSettings,
    token_authenticator: RequestAuthenticator,
) -> RequestAuthorizationRuntime:
    if not settings.required:
        return RequestAuthorizationRuntime(token_authenticator)
    assert settings.identity_storage_dir is not None
    database_path = _private_identity_database_path(settings.identity_storage_dir)
    repository = SqliteIdentityRepository(database_path)
    try:
        authenticator = RepositoryBackedRequestAuthenticator(
            token_authenticator,
            repository,
        )
    except BaseException:
        repository.close()
        raise
    return RequestAuthorizationRuntime(authenticator, repository)


def _private_identity_database_path(storage_dir: Path) -> Path:
    requested = Path(storage_dir)
    requested.mkdir(parents=True, mode=0o700, exist_ok=True)
    metadata = requested.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("identity storage must be a real directory")
    if os.name == "posix" and stat.S_IMODE(metadata.st_mode) & 0o077:
        raise ValueError("identity storage must not grant group or other permissions")
    return requested.resolve(strict=True) / "identity.sqlite3"


__all__ = [
    "RepositoryBackedRequestAuthenticator",
    "RequestAuthorizationRuntime",
    "build_request_authorization_runtime",
]
