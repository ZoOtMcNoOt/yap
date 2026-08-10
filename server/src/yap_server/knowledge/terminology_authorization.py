from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from yap_server.auth.principal import AuthenticatedPrincipal, PrincipalKey


class TerminologyMembershipResolver(Protocol):
    """Resolve trusted tenant-scoped memberships outside request payloads."""

    def team_ids_for(self, principal: PrincipalKey) -> tuple[str, ...]: ...


@dataclass(frozen=True, slots=True)
class TerminologyAuthorization:
    principal: PrincipalKey
    team_ids: tuple[str, ...]
    may_manage_organization: bool


def resolve_terminology_authorization(
    principal: AuthenticatedPrincipal,
    *,
    memberships: TerminologyMembershipResolver,
    administrator_roles: frozenset[str],
) -> TerminologyAuthorization:
    """Derive terminology authority from authenticated identity and trusted policy."""

    if not isinstance(administrator_roles, frozenset) or not administrator_roles:
        raise ValueError("terminology administrator role policy is invalid")
    team_ids = memberships.team_ids_for(principal.key)
    if not isinstance(team_ids, tuple):
        raise TypeError("terminology memberships must be immutable")
    ordered = tuple(sorted(team_ids))
    if len(set(ordered)) != len(ordered):
        raise ValueError("terminology memberships are duplicated")
    return TerminologyAuthorization(
        principal=principal.key,
        team_ids=ordered,
        may_manage_organization=bool(principal.roles & administrator_roles),
    )


__all__ = [
    "TerminologyAuthorization",
    "TerminologyMembershipResolver",
    "resolve_terminology_authorization",
]
