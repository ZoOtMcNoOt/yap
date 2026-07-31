from __future__ import annotations

from typing import Protocol

from yap_server.auth.principal import AuthenticatedPrincipal


class PrincipalAdmissionUnavailable(RuntimeError):
    """The durable principal policy could not establish an authorization result."""


class PrincipalAdmissionRepository(Protocol):
    def admit_principal(self, principal: AuthenticatedPrincipal) -> bool:
        """Create a first-seen principal or read its durable access decision."""


__all__ = [
    "PrincipalAdmissionRepository",
    "PrincipalAdmissionUnavailable",
]
