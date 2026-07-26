from __future__ import annotations

from dataclasses import dataclass


_MAX_IDENTITY_CHARS = 128
_MAX_SCOPE_CHARS = 128
_MAX_SCOPES = 32


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
        if self.issued_at_unix is not None and (
            isinstance(self.issued_at_unix, bool)
            or not isinstance(self.issued_at_unix, int)
            or self.issued_at_unix < 0
        ):
            raise ValueError("issued_at_unix is invalid")

    @property
    def key(self) -> PrincipalKey:
        return PrincipalKey(self.tenant_id, self.subject_id)
