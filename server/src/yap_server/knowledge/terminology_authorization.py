from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from yap_server.auth.principal import AuthenticatedPrincipal, PrincipalKey


class TerminologyMembershipResolver(Protocol):
    """Resolve trusted tenant-scoped visibility and management outside requests."""

    def team_ids_for(self, principal: PrincipalKey) -> tuple[str, ...]: ...

    def managed_team_ids_for(self, principal: PrincipalKey) -> tuple[str, ...]: ...


@dataclass(frozen=True, slots=True)
class TerminologyAuthorization:
    principal: PrincipalKey
    team_ids: tuple[str, ...]
    managed_team_ids: tuple[str, ...]
    may_manage_organization: bool

    def __post_init__(self) -> None:
        _validated_teams(self.team_ids, "memberships")
        _validated_teams(self.managed_team_ids, "management grants")
        if not set(self.managed_team_ids).issubset(self.team_ids):
            raise ValueError("terminology management grants exceed visible teams")
        if (
            not isinstance(self.principal, PrincipalKey)
            or type(self.may_manage_organization) is not bool
        ):
            raise TypeError("terminology authorization identity or policy is invalid")


def _validated_teams(team_ids: tuple[str, ...], field: str) -> tuple[str, ...]:
    if not isinstance(team_ids, tuple):
        raise TypeError(f"terminology {field} must be immutable")
    if any(
        not isinstance(item, str) or not item or len(item) > 128 for item in team_ids
    ):
        raise ValueError(f"terminology {field} are invalid")
    if len(set(team_ids)) != len(team_ids):
        raise ValueError(f"terminology {field} are duplicated")
    return tuple(sorted(team_ids))


def resolve_terminology_authorization(
    principal: AuthenticatedPrincipal,
    *,
    memberships: TerminologyMembershipResolver,
    administrator_roles: frozenset[str],
) -> TerminologyAuthorization:
    """Derive terminology authority from authenticated identity and trusted policy."""

    if not isinstance(administrator_roles, frozenset) or not administrator_roles:
        raise ValueError("terminology administrator role policy is invalid")
    teams = _validated_teams(memberships.team_ids_for(principal.key), "memberships")
    managed_teams = _validated_teams(
        memberships.managed_team_ids_for(principal.key), "management grants"
    )
    return TerminologyAuthorization(
        principal=principal.key,
        team_ids=teams,
        managed_team_ids=managed_teams,
        may_manage_organization=bool(principal.roles & administrator_roles),
    )


__all__ = [
    "TerminologyAuthorization",
    "TerminologyMembershipResolver",
    "resolve_terminology_authorization",
]
