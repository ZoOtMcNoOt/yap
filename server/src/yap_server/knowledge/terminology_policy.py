"""Operator-owned shared scopes; token identity never supplies team grants."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import stat
from typing import Mapping

from yap_server.auth import AuthenticatedPrincipal, PrincipalKey
from .terminology_authorization import (
    TerminologyAuthorization,
    resolve_terminology_authorization,
)

TERMINOLOGY_POLICY_FILE = "YAP_TERMINOLOGY_POLICY_FILE"
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_MAXIMUM_BYTES = 65_536


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("terminology policy fields are duplicated")
        result[key] = value
    return result


def _fields(value: object, keys: set[str]) -> dict:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError("terminology policy fields are invalid")
    return value


def _text(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 128
        or value.strip() != value
        or not value.isprintable()
    ):
        raise ValueError("terminology policy text is invalid")
    return value


def _identities(value: object, maximum: int) -> frozenset[str]:
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError("terminology policy identities are invalid")
    for identity in value:
        PrincipalKey("policy", identity)
    if len(set(value)) != len(value):
        raise ValueError("terminology policy identities are duplicated")
    return frozenset(value)


@dataclass(frozen=True, slots=True)
class TerminologyScope:
    scope_id: str
    kind: str
    owner_id: str
    label: str
    can_manage: bool

    def wire(self) -> dict[str, object]:
        return {
            "scopeId": self.scope_id,
            "kind": self.kind,
            "label": self.label,
            "canManage": self.can_manage,
        }


@dataclass(frozen=True, slots=True)
class _Team:
    team_id: str
    label: str
    members: frozenset[str]
    managers: frozenset[str]


@dataclass(frozen=True, slots=True)
class _Tenant:
    tenant_id: str
    label: str
    administrator_roles: frozenset[str]
    teams: tuple[_Team, ...]


@dataclass(frozen=True, slots=True)
class TerminologyPolicy:
    tenants: tuple[_Tenant, ...] = ()

    @classmethod
    def from_payload(cls, value: object) -> TerminologyPolicy:
        body = _fields(value, {"tenants"})
        tenants = body["tenants"]
        if not isinstance(tenants, list) or not 1 <= len(tenants) <= 32:
            raise ValueError("terminology policy tenants are invalid")
        result = []
        for tenant in tenants:
            row = _fields(tenant, {"tenantId", "label", "administratorRoles", "teams"})
            tenant_id = PrincipalKey(row["tenantId"], "policy").tenant_id
            roles = _identities(row["administratorRoles"], 32)
            if not roles or any(any(c.isspace() for c in role) for role in roles):
                raise ValueError("terminology administrator roles are invalid")
            if not isinstance(row["teams"], list) or len(row["teams"]) > 32:
                raise ValueError("terminology policy teams are invalid")
            teams = []
            for team in row["teams"]:
                item = _fields(team, {"teamId", "label", "members", "managers"})
                team_id = item["teamId"]
                if not isinstance(team_id, str) or not _ID.fullmatch(team_id):
                    raise ValueError("terminology policy team identity is invalid")
                members = _identities(item["members"], 256)
                managers = _identities(item["managers"], 256)
                if not managers.issubset(members):
                    raise ValueError("terminology management exceeds visibility")
                teams.append(_Team(team_id, _text(item["label"]), members, managers))
            if len({team.team_id for team in teams}) != len(teams):
                raise ValueError("terminology policy teams are duplicated")
            result.append(_Tenant(tenant_id, _text(row["label"]), roles, tuple(teams)))
        if len({tenant.tenant_id for tenant in result}) != len(result):
            raise ValueError("terminology policy tenants are duplicated")
        return cls(tuple(result))

    def _tenant(self, key: PrincipalKey) -> _Tenant | None:
        if not isinstance(key, PrincipalKey):
            raise TypeError("terminology principal is invalid")
        return next((t for t in self.tenants if t.tenant_id == key.tenant_id), None)

    def team_ids_for(self, principal: PrincipalKey) -> tuple[str, ...]:
        tenant = self._tenant(principal)
        return (
            tuple(t.team_id for t in tenant.teams if principal.subject_id in t.members)
            if tenant
            else ()
        )

    def managed_team_ids_for(self, principal: PrincipalKey) -> tuple[str, ...]:
        tenant = self._tenant(principal)
        return (
            tuple(t.team_id for t in tenant.teams if principal.subject_id in t.managers)
            if tenant
            else ()
        )

    def authorization(
        self, principal: AuthenticatedPrincipal
    ) -> TerminologyAuthorization:
        tenant = self._tenant(principal.key)
        if tenant is None:
            return TerminologyAuthorization(principal.key, (), (), False)
        return resolve_terminology_authorization(
            principal, memberships=self, administrator_roles=tenant.administrator_roles
        )

    def scopes(self, principal: AuthenticatedPrincipal) -> tuple[TerminologyScope, ...]:
        personal = TerminologyScope(
            "personal", "personal", principal.subject_id, "Personal", True
        )
        tenant = self._tenant(principal.key)
        if tenant is None:
            return (personal,)
        authority = self.authorization(principal)
        organization = TerminologyScope(
            "organization",
            "organization",
            principal.tenant_id,
            tenant.label,
            authority.may_manage_organization,
        )
        teams = tuple(
            TerminologyScope(
                f"team:{t.team_id}",
                "team",
                t.team_id,
                t.label,
                t.team_id in authority.managed_team_ids,
            )
            for t in tenant.teams
            if t.team_id in authority.team_ids
        )
        return (personal, organization, *teams)


def build_terminology_policy(
    environ: Mapping[str, str], *, authenticated_team_mode: bool
) -> TerminologyPolicy:
    value = environ.get(TERMINOLOGY_POLICY_FILE)
    if value is None:
        return TerminologyPolicy()
    if not authenticated_team_mode:
        raise ValueError("shared terminology requires organization authentication")
    if not value or value.strip() != value or not Path(value).is_absolute():
        raise ValueError("terminology policy path must be absolute")
    try:
        flags = (
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        )
        descriptor = os.open(value, flags)
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > _MAXIMUM_BYTES:
                raise ValueError("invalid policy file")
            if os.name == "posix" and (
                stat.S_IMODE(metadata.st_mode) != 0o600
                or metadata.st_uid != os.geteuid()
            ):
                raise ValueError("policy must be owner-private")
            with os.fdopen(descriptor, "rb", closefd=False) as source:
                data = source.read(_MAXIMUM_BYTES + 1)
            if len(data) > _MAXIMUM_BYTES:
                raise ValueError("policy is too large")
        finally:
            os.close(descriptor)
        return TerminologyPolicy.from_payload(
            json.loads(data, object_pairs_hook=_unique_object)
        )
    except (OSError, TypeError, ValueError):
        raise ValueError(
            "shared terminology policy is unavailable or invalid"
        ) from None
