from __future__ import annotations

from dataclasses import dataclass


_MAX_IDENTITY_CHARS = 128
_MAX_SCOPE_CHARS = 128
_MAX_SCOPES = 32
_MAX_ROLE_CHARS = 128
_MAX_ROLES = 32
_MAX_UNIX_SECONDS = 253_402_300_799


def _identity_value(value: str, field: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be text")
    if (
        not value
        or len(value) > _MAX_IDENTITY_CHARS
        or not value.isascii()
        or not value.isprintable()
        or value.strip() != value
    ):
        raise ValueError(f"{field} is invalid")
    return value


def _validated_scopes(scopes: frozenset[str]) -> frozenset[str]:
    if not isinstance(scopes, frozenset):
        raise TypeError("scopes must be an immutable set")
    if len(scopes) > _MAX_SCOPES:
        raise ValueError("too many scopes")
    for scope in scopes:
        if (
            not isinstance(scope, str)
            or not scope
            or len(scope) > _MAX_SCOPE_CHARS
            or not scope.isascii()
            or not scope.isprintable()
            or scope.strip() != scope
            or any(character.isspace() for character in scope)
        ):
            raise ValueError("scope is invalid")
    return scopes


def _validated_roles(roles: frozenset[str]) -> frozenset[str]:
    if not isinstance(roles, frozenset):
        raise TypeError("roles must be an immutable set")
    if len(roles) > _MAX_ROLES:
        raise ValueError("too many roles")
    for role in roles:
        if (
            not isinstance(role, str)
            or not role
            or len(role) > _MAX_ROLE_CHARS
            or not role.isascii()
            or not role.isprintable()
            or role.strip() != role
            or any(character.isspace() for character in role)
        ):
            raise ValueError("role is invalid")
    return roles


def _validated_unix_time(value: int | None, field: str) -> int | None:
    if value is not None and (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 0 <= value <= _MAX_UNIX_SECONDS
    ):
        raise ValueError(f"{field} is invalid")
    return value


@dataclass(frozen=True, slots=True)
class PrincipalKey:
    tenant_id: str
    subject_id: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "tenant_id",
            _identity_value(self.tenant_id, "tenant_id"),
        )
        object.__setattr__(
            self,
            "subject_id",
            _identity_value(self.subject_id, "subject_id"),
        )


@dataclass(frozen=True, slots=True)
class AuthenticatedPrincipal:
    tenant_id: str
    subject_id: str
    client_id: str
    scopes: frozenset[str]
    issued_at_unix: int | None = None
    expires_at_unix: int | None = None
    roles: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "tenant_id",
            _identity_value(self.tenant_id, "tenant_id"),
        )
        object.__setattr__(
            self,
            "subject_id",
            _identity_value(self.subject_id, "subject_id"),
        )
        object.__setattr__(
            self,
            "client_id",
            _identity_value(self.client_id, "client_id"),
        )
        object.__setattr__(self, "scopes", _validated_scopes(self.scopes))
        object.__setattr__(self, "roles", _validated_roles(self.roles))
        object.__setattr__(
            self,
            "issued_at_unix",
            _validated_unix_time(self.issued_at_unix, "issued_at_unix"),
        )
        object.__setattr__(
            self,
            "expires_at_unix",
            _validated_unix_time(self.expires_at_unix, "expires_at_unix"),
        )
        if (
            self.issued_at_unix is not None
            and self.expires_at_unix is not None
            and self.expires_at_unix <= self.issued_at_unix
        ):
            raise ValueError("expires_at_unix must follow issued_at_unix")

    @property
    def key(self) -> PrincipalKey:
        return PrincipalKey(self.tenant_id, self.subject_id)
