from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

import jwt

from yap_server.auth.oidc_metadata import (
    SigningKeyProvider,
    SigningKeyUnavailable,
)
from yap_server.auth.principal import AuthenticatedPrincipal
from yap_server.auth.request_authentication import AuthenticationFailure


_MAX_ACCESS_TOKEN_CHARS = 16 * 1024
_MAX_KEY_ID_CHARS = 128
_MAX_ISSUER_CHARS = 2_048
_MAX_AUDIENCE_CHARS = 512
_MAX_IDENTITY_CHARS = 128
_MAX_CLAIM_NAME_CHARS = 128
_MAX_SCOPE_CLAIM_CHARS = 2_048
_MAX_AUTHORITIES = 64
_MAX_AUTHORITY_CHARS = 128
_MAX_UNIX_SECONDS = 253_402_300_799
_MAX_CLOCK_SKEW_SECONDS = 5 * 60
_SUPPORTED_ALGORITHMS = frozenset({"RS256"})
_DEFAULT_TOKEN_TYPES = frozenset({"JWT", "at+jwt"})
_VERIFIED_CLAIMS = frozenset(
    {
        "iss",
        "aud",
        "exp",
        "nbf",
        "iat",
    }
)
_REQUIRED_VERIFIED_CLAIMS = (
    "iss",
    "aud",
    "exp",
    "nbf",
    "iat",
)
_IDENTITY_FORMATS = frozenset({"bounded_text", "uuid"})


class _InsufficientScope(ValueError):
    pass


class _InsufficientRole(ValueError):
    pass


def _bounded_text(value: str, field: str, maximum_chars: int) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > maximum_chars
        or not value.isascii()
        or not value.isprintable()
        or value.strip() != value
    ):
        raise ValueError(f"{field} is invalid")
    return value


def _claim_name(value: str, field: str) -> str:
    name = _bounded_text(value, field, _MAX_CLAIM_NAME_CHARS)
    if any(character.isspace() for character in name):
        raise ValueError(f"{field} is invalid")
    return name


def _identity_value(
    value: object,
    field: str,
    identity_format: Literal["bounded_text", "uuid"],
) -> str:
    identity = _bounded_text(value, field, _MAX_IDENTITY_CHARS)
    if any(character.isspace() for character in identity):
        raise ValueError(f"{field} is invalid")
    if identity_format == "bounded_text":
        return identity
    parsed = UUID(identity)
    if str(parsed) != identity.lower():
        raise ValueError(f"{field} is not canonical")
    return str(parsed)


def _policy_identities(
    values: frozenset[str],
    field: str,
    identity_format: Literal["bounded_text", "uuid"],
) -> frozenset[str]:
    if not isinstance(values, frozenset):
        raise TypeError(f"{field} must be an immutable set")
    if not values or len(values) > _MAX_AUTHORITIES:
        raise ValueError(f"{field} is invalid")
    return frozenset(_identity_value(value, field, identity_format) for value in values)


def _policy_authorities(
    values: frozenset[str],
    field: str,
) -> frozenset[str]:
    if not isinstance(values, frozenset):
        raise TypeError(f"{field} must be an immutable set")
    if len(values) > _MAX_AUTHORITIES:
        raise ValueError(f"{field} has too many values")
    for value in values:
        _bounded_text(value, field, _MAX_AUTHORITY_CHARS)
        if any(character.isspace() for character in value):
            raise ValueError(f"{field} is invalid")
    return values


def _required_claim_value_rules(
    rules: tuple[tuple[str, str], ...],
    field: str,
) -> tuple[tuple[str, str], ...]:
    if not isinstance(rules, tuple):
        raise TypeError(f"{field} must be a tuple")
    if len(rules) > _MAX_AUTHORITIES:
        raise ValueError(f"{field} has too many values")
    result: list[tuple[str, str]] = []
    for rule in rules:
        if not isinstance(rule, tuple) or len(rule) != 2:
            raise TypeError(f"{field} entries must be pairs")
        claim_name = _claim_name(rule[0], field)
        claim_value = _bounded_text(rule[1], field, _MAX_AUTHORITY_CHARS)
        result.append((claim_name, claim_value))
    if len({claim_name for claim_name, _ in result}) != len(result):
        raise ValueError(f"{field} contains duplicate claim names")
    return tuple(sorted(result))


def _claim_value_set_rules(
    rules: tuple[tuple[str, frozenset[str]], ...],
    field: str,
) -> tuple[tuple[str, frozenset[str]], ...]:
    if not isinstance(rules, tuple):
        raise TypeError(f"{field} must be a tuple")
    if len(rules) > _MAX_AUTHORITIES:
        raise ValueError(f"{field} has too many values")
    result: list[tuple[str, frozenset[str]]] = []
    for rule in rules:
        if not isinstance(rule, tuple) or len(rule) != 2:
            raise TypeError(f"{field} entries must be pairs")
        claim_name = _claim_name(rule[0], field)
        claim_values = _policy_authorities(rule[1], field)
        if not claim_values:
            raise ValueError(f"{field} entries must not be empty")
        result.append((claim_name, claim_values))
    if len({claim_name for claim_name, _ in result}) != len(result):
        raise ValueError(f"{field} contains duplicate claim names")
    return tuple(sorted(result, key=lambda rule: rule[0]))


def _token_scopes(value: object) -> frozenset[str]:
    if not isinstance(value, str) or not value or len(value) > _MAX_SCOPE_CLAIM_CHARS:
        raise ValueError("scope claim is invalid")
    scopes = value.split(" ")
    if not scopes or len(scopes) > _MAX_AUTHORITIES or len(set(scopes)) != len(scopes):
        raise ValueError("scope claim is invalid")
    result = frozenset(scopes)
    _policy_authorities(result, "scope claim")
    return result


def _token_roles(value: object) -> frozenset[str]:
    if value is None:
        return frozenset()
    if (
        not isinstance(value, list)
        or len(value) > _MAX_AUTHORITIES
        or len(set(value)) != len(value)
    ):
        raise ValueError("roles claim is invalid")
    try:
        result = frozenset(value)
    except TypeError as error:
        raise ValueError("roles claim is invalid") from error
    _policy_authorities(result, "roles claim")
    return result


def _numeric_date(value: object, field: str) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 0 <= value <= _MAX_UNIX_SECONDS
    ):
        raise ValueError(f"{field} claim is invalid")
    return value


@dataclass(frozen=True, slots=True)
class OidcAccessTokenPolicy:
    issuer: str
    audience: str
    tenant_id_claim: str
    subject_id_claim: str
    client_id_claim: str
    scope_claim: str
    allowed_tenant_ids: frozenset[str]
    allowed_client_ids: frozenset[str]
    required_scopes: frozenset[str]
    roles_claim: str | None = None
    identity_format: Literal["bounded_text", "uuid"] = "bounded_text"
    allowed_roles: frozenset[str] = frozenset()
    required_roles: frozenset[str] = frozenset()
    required_claim_values: tuple[tuple[str, str], ...] = ()
    optional_claim_values: tuple[tuple[str, frozenset[str]], ...] = ()
    rejected_claim_values: tuple[tuple[str, frozenset[str]], ...] = ()
    allowed_algorithms: frozenset[str] = _SUPPORTED_ALGORITHMS
    allowed_token_types: frozenset[str] = _DEFAULT_TOKEN_TYPES
    clock_skew_seconds: int = 60

    def __post_init__(self) -> None:
        issuer = _bounded_text(self.issuer, "issuer", _MAX_ISSUER_CHARS)
        try:
            parsed_issuer = urlsplit(issuer)
            parsed_issuer.port
        except ValueError as error:
            raise ValueError("issuer is invalid") from error
        if (
            parsed_issuer.scheme not in {"http", "https"}
            or parsed_issuer.hostname is None
            or parsed_issuer.username is not None
            or parsed_issuer.password is not None
            or parsed_issuer.query
            or parsed_issuer.fragment
            or issuer.endswith("/")
        ):
            raise ValueError("issuer is invalid")
        object.__setattr__(
            self,
            "audience",
            _bounded_text(self.audience, "audience", _MAX_AUDIENCE_CHARS),
        )
        if self.identity_format not in _IDENTITY_FORMATS:
            raise ValueError("identity format is invalid")
        claim_names = (
            _claim_name(self.tenant_id_claim, "tenant claim name"),
            _claim_name(self.subject_id_claim, "subject claim name"),
            _claim_name(self.client_id_claim, "client claim name"),
            _claim_name(self.scope_claim, "scope claim name"),
        )
        roles_claim = (
            None
            if self.roles_claim is None
            else _claim_name(self.roles_claim, "roles claim name")
        )
        all_authority_claims = (*claim_names, roles_claim)
        configured_authority_claims = {
            claim_name for claim_name in all_authority_claims if claim_name is not None
        }
        if len(configured_authority_claims) != len(all_authority_claims) - (
            roles_claim is None
        ):
            raise ValueError("authority claim names must be distinct")
        if configured_authority_claims & _VERIFIED_CLAIMS:
            raise ValueError("authority claim names overlap verified JWT claims")
        object.__setattr__(self, "tenant_id_claim", claim_names[0])
        object.__setattr__(self, "subject_id_claim", claim_names[1])
        object.__setattr__(self, "client_id_claim", claim_names[2])
        object.__setattr__(self, "scope_claim", claim_names[3])
        object.__setattr__(self, "roles_claim", roles_claim)
        object.__setattr__(
            self,
            "allowed_tenant_ids",
            _policy_identities(
                self.allowed_tenant_ids,
                "tenant policy",
                self.identity_format,
            ),
        )
        object.__setattr__(
            self,
            "allowed_client_ids",
            _policy_identities(
                self.allowed_client_ids,
                "client policy",
                self.identity_format,
            ),
        )
        scopes = _policy_authorities(self.required_scopes, "required scopes")
        if not scopes:
            raise ValueError("at least one delegated scope is required")
        allowed_roles = _policy_authorities(self.allowed_roles, "allowed roles")
        required_roles = _policy_authorities(self.required_roles, "required roles")
        if not required_roles <= allowed_roles:
            raise ValueError("required roles must be allowed roles")
        if roles_claim is None and (allowed_roles or required_roles):
            raise ValueError("configured roles require a roles claim name")
        required_claim_values = _required_claim_value_rules(
            self.required_claim_values,
            "required claim values",
        )
        optional_claim_values = _claim_value_set_rules(
            self.optional_claim_values,
            "optional claim values",
        )
        rejected_claim_values = _claim_value_set_rules(
            self.rejected_claim_values,
            "rejected claim values",
        )
        rule_names = [
            claim_name
            for rules in (
                required_claim_values,
                optional_claim_values,
                rejected_claim_values,
            )
            for claim_name, _ in rules
        ]
        if (
            len(set(rule_names)) != len(rule_names)
            or set(rule_names) & configured_authority_claims
            or set(rule_names) & _VERIFIED_CLAIMS
        ):
            raise ValueError("claim value rules overlap other policy claims")
        object.__setattr__(
            self,
            "required_claim_values",
            required_claim_values,
        )
        object.__setattr__(
            self,
            "optional_claim_values",
            optional_claim_values,
        )
        object.__setattr__(
            self,
            "rejected_claim_values",
            rejected_claim_values,
        )
        if (
            not isinstance(self.allowed_algorithms, frozenset)
            or not self.allowed_algorithms
            or not self.allowed_algorithms <= _SUPPORTED_ALGORITHMS
        ):
            raise ValueError("allowed algorithms are not supported")
        token_types = _policy_authorities(
            self.allowed_token_types,
            "allowed token types",
        )
        if not token_types:
            raise ValueError("at least one access-token type is required")
        if (
            isinstance(self.clock_skew_seconds, bool)
            or not isinstance(self.clock_skew_seconds, int)
            or not 0 <= self.clock_skew_seconds <= _MAX_CLOCK_SKEW_SECONDS
        ):
            raise ValueError("clock skew is invalid")


class OidcAccessTokenAuthenticator:
    authentication_required = True
    principal_access_enforced = False

    def __init__(
        self,
        policy: OidcAccessTokenPolicy,
        signing_keys: SigningKeyProvider,
    ) -> None:
        self._policy = policy
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
                algorithms=sorted(self._policy.allowed_algorithms),
                audience=self._policy.audience,
                issuer=self._policy.issuer,
                leeway=self._policy.clock_skew_seconds,
                options={
                    "require": self._required_claims(),
                    "strict_aud": True,
                },
            )
            return self._principal(claims)
        except _InsufficientScope as error:
            raise AuthenticationFailure.forbidden(
                code="INSUFFICIENT_SCOPE",
                message="The access token does not grant the required Yap scope.",
            ) from error
        except _InsufficientRole as error:
            raise AuthenticationFailure.forbidden(
                code="INSUFFICIENT_ROLE",
                message="The access token does not grant the required Yap role.",
            ) from error
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

    def _key_id(self, header: Mapping[str, object]) -> str:
        algorithm = header.get("alg")
        if algorithm not in self._policy.allowed_algorithms:
            raise ValueError("access-token algorithm is not allowed")
        token_type = header.get("typ")
        if token_type not in self._policy.allowed_token_types:
            raise ValueError("access-token type is not allowed")
        if "crit" in header:
            raise ValueError("critical access-token headers are not supported")
        key_id = header.get("kid")
        if (
            not isinstance(key_id, str)
            or not key_id
            or len(key_id) > _MAX_KEY_ID_CHARS
            or not key_id.isascii()
            or not key_id.isprintable()
            or key_id.strip() != key_id
        ):
            raise ValueError("access-token key identifier is invalid")
        return key_id

    def _required_claims(self) -> list[str]:
        return [
            *_REQUIRED_VERIFIED_CLAIMS,
            self._policy.tenant_id_claim,
            self._policy.subject_id_claim,
            self._policy.client_id_claim,
            self._policy.scope_claim,
            *(claim_name for claim_name, _ in self._policy.required_claim_values),
        ]

    def _identity_claim(self, claims: Mapping[str, object], claim_name: str) -> str:
        return _identity_value(
            claims.get(claim_name),
            f"{claim_name} claim",
            self._policy.identity_format,
        )

    def _validate_claim_value_rules(self, claims: Mapping[str, object]) -> None:
        for claim_name, expected_value in self._policy.required_claim_values:
            if claims.get(claim_name) != expected_value:
                raise ValueError(f"{claim_name} claim is invalid")
        for claim_name, allowed_values in self._policy.optional_claim_values:
            if claim_name not in claims:
                continue
            claim_value = _bounded_text(
                claims.get(claim_name),
                f"{claim_name} claim",
                _MAX_AUTHORITY_CHARS,
            )
            if claim_value not in allowed_values:
                raise ValueError(f"{claim_name} claim is invalid")
        for claim_name, rejected_values in self._policy.rejected_claim_values:
            if claim_name not in claims:
                continue
            claim_value = _bounded_text(
                claims.get(claim_name),
                f"{claim_name} claim",
                _MAX_AUTHORITY_CHARS,
            )
            if claim_value in rejected_values:
                raise ValueError(f"{claim_name} claim is not allowed")

    def _principal(self, claims: Mapping[str, object]) -> AuthenticatedPrincipal:
        self._validate_claim_value_rules(claims)
        tenant_id = self._identity_claim(claims, self._policy.tenant_id_claim)
        if tenant_id not in self._policy.allowed_tenant_ids:
            raise ValueError("access-token tenant is not allowed")
        subject_id = self._identity_claim(claims, self._policy.subject_id_claim)
        client_id = self._identity_claim(claims, self._policy.client_id_claim)
        if client_id not in self._policy.allowed_client_ids:
            raise ValueError("access-token client is not allowed")
        scopes = _token_scopes(claims.get(self._policy.scope_claim))
        if not self._policy.required_scopes <= scopes:
            raise _InsufficientScope
        claimed_roles = _token_roles(
            None
            if self._policy.roles_claim is None
            else claims.get(self._policy.roles_claim)
        )
        if not self._policy.required_roles <= claimed_roles:
            raise _InsufficientRole
        roles = claimed_roles & self._policy.allowed_roles
        issued_at_unix = _numeric_date(claims.get("iat"), "iat")
        not_before_unix = _numeric_date(claims.get("nbf"), "nbf")
        expires_at_unix = _numeric_date(claims.get("exp"), "exp")
        if expires_at_unix <= issued_at_unix or expires_at_unix <= not_before_unix:
            raise ValueError("access-token time window is invalid")
        now_unix = int(datetime.now(UTC).timestamp())
        if issued_at_unix > now_unix + self._policy.clock_skew_seconds:
            raise ValueError("access-token issue time exceeds allowed skew")
        return AuthenticatedPrincipal(
            tenant_id=tenant_id,
            subject_id=subject_id,
            client_id=client_id,
            scopes=scopes,
            issued_at_unix=issued_at_unix,
            expires_at_unix=expires_at_unix,
            roles=roles,
        )


__all__ = [
    "OidcAccessTokenAuthenticator",
    "OidcAccessTokenPolicy",
]
