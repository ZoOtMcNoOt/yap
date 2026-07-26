from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

import jwt

from yap_server.auth.principal import AuthenticatedPrincipal
from yap_server.auth.request_authentication import AuthenticationFailure
from yap_server.auth.signing_keys import SigningKeyProvider, SigningKeyUnavailable
from yap_server.config import ServerAuthenticationSettings


_MAX_ACCESS_TOKEN_CHARS = 16 * 1024
_MAX_KEY_ID_CHARS = 128
_TOKEN_LEEWAY_SECONDS = 60
_REQUIRED_CLAIMS = (
    "iss",
    "aud",
    "exp",
    "nbf",
    "iat",
    "tid",
    "oid",
    "azp",
    "scp",
)


def _canonical_uuid(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("identity claim is not text")
    parsed = UUID(value)
    if str(parsed) != value.lower():
        raise ValueError("identity claim is not canonical")
    return str(parsed)


def _token_scopes(value: object) -> frozenset[str]:
    if not isinstance(value, str) or not value or len(value) > 2_048:
        raise ValueError("scope claim is invalid")
    scopes = value.split(" ")
    if (
        not scopes
        or len(scopes) > 64
        or any(
            not scope
            or len(scope) > 128
            or not scope.isascii()
            or not scope.isprintable()
            for scope in scopes
        )
    ):
        raise ValueError("scope claim is invalid")
    return frozenset(scopes)


class EntraAccessTokenAuthenticator:
    authentication_required = True
    principal_access_enforced = False

    def __init__(
        self,
        settings: ServerAuthenticationSettings,
        signing_keys: SigningKeyProvider,
    ) -> None:
        if not settings.required:
            raise ValueError("Entra authentication requires Entra settings")
        assert settings.tenant_id is not None
        assert settings.audience is not None
        assert settings.required_scope is not None
        self._tenant_id = settings.tenant_id
        self._audience = settings.audience
        self._required_scope = settings.required_scope
        self._allowed_client_ids = frozenset(settings.allowed_client_ids)
        self._issuer = f"https://login.microsoftonline.com/{settings.tenant_id}/v2.0"
        self._signing_keys = signing_keys

    def authenticate(self, authorization: str | None) -> AuthenticatedPrincipal:
        token = self._bearer_token(authorization)
        try:
            header = jwt.get_unverified_header(token)
            key_id = self._key_id(header)
            key = self._signing_keys.key_for(key_id)
            claims = jwt.decode(
                token,
                key=key,
                algorithms=["RS256"],
                audience=self._audience,
                issuer=self._issuer,
                leeway=_TOKEN_LEEWAY_SECONDS,
                options={"require": list(_REQUIRED_CLAIMS)},
            )
            return self._principal(claims)
        except AuthenticationFailure:
            raise
        except SigningKeyUnavailable as error:
            raise AuthenticationFailure.unavailable() from error
        except (
            KeyError,
            TypeError,
            ValueError,
            jwt.InvalidTokenError,
        ) as error:
            raise AuthenticationFailure.invalid() from error

    @staticmethod
    def _bearer_token(authorization: str | None) -> str:
        if authorization is None:
            raise AuthenticationFailure.missing()
        if (
            not isinstance(authorization, str)
            or not authorization.isascii()
            or len(authorization) > _MAX_ACCESS_TOKEN_CHARS + len("Bearer ")
        ):
            raise AuthenticationFailure.invalid()
        parts = authorization.split(" ")
        if (
            len(parts) != 2
            or parts[0].casefold() != "bearer"
            or not parts[1]
            or len(parts[1]) > _MAX_ACCESS_TOKEN_CHARS
        ):
            raise AuthenticationFailure.invalid()
        return parts[1]

    @staticmethod
    def _key_id(header: Mapping[str, object]) -> str:
        if header.get("alg") != "RS256":
            raise ValueError("access token algorithm is not allowed")
        key_id = header.get("kid")
        if (
            not isinstance(key_id, str)
            or not key_id
            or len(key_id) > _MAX_KEY_ID_CHARS
            or not key_id.isascii()
            or not key_id.isprintable()
        ):
            raise ValueError("access token key identifier is invalid")
        return key_id

    def _principal(self, claims: Mapping[str, object]) -> AuthenticatedPrincipal:
        tenant_id = _canonical_uuid(claims.get("tid"))
        if tenant_id != self._tenant_id:
            raise ValueError("access token tenant is not allowed")
        subject_id = _canonical_uuid(claims.get("oid"))
        client_id = _canonical_uuid(claims.get("azp"))
        if client_id not in self._allowed_client_ids:
            raise ValueError("access token client is not allowed")
        if claims.get("idtyp") == "app":
            raise ValueError("application-only tokens are not allowed")
        scopes = _token_scopes(claims.get("scp"))
        if self._required_scope not in scopes:
            raise ValueError("access token scope is not allowed")
        issued_at_unix = claims.get("iat")
        if (
            isinstance(issued_at_unix, bool)
            or not isinstance(issued_at_unix, int)
            or issued_at_unix < 0
        ):
            raise ValueError("access token issue time is invalid")
        return AuthenticatedPrincipal(
            tenant_id=tenant_id,
            subject_id=subject_id,
            client_id=client_id,
            scopes=scopes,
            issued_at_unix=issued_at_unix,
        )
