from __future__ import annotations

import psycopg

from yap_server.auth import AuthenticatedPrincipal, PrincipalKey
from yap_server.knowledge.terminology_authorization import (
    TerminologyMembershipResolver,
    resolve_terminology_authorization,
)
from yap_server.knowledge.terminology_ledger import (
    store_current_terminology_snapshot,
)
from yap_server.knowledge.terminology_projections import (
    compile_grammar_preservation_constraints,
)
from yap_server.private_postgres_connection import (
    PrivatePostgresConnectionFactory,
)

from .transcript_correction import TranscriptCorrectionTerminology
from .transcript_correction_service import TranscriptCorrectionTerminologyUnavailable


_TERMINOLOGY_ADMINISTRATOR_ROLES = frozenset({"knowledge.terminology.admin"})


class PersonalOrganizationTerminologyMemberships:
    """Use only personal and organization terms until trusted teams are supplied."""

    def team_ids_for(self, principal: PrincipalKey) -> tuple[str, ...]:
        if not isinstance(principal, PrincipalKey):
            raise TypeError("terminology principal type is invalid")
        return ()


class PostgresTranscriptCorrectionTerminologyResolver:
    """Freeze one canonical terminology snapshot before broker admission."""

    def __init__(
        self,
        *,
        connection_factory: PrivatePostgresConnectionFactory,
        memberships: TerminologyMembershipResolver,
    ) -> None:
        if not callable(connection_factory):
            raise TypeError("terminology connection factory is invalid")
        if not hasattr(memberships, "team_ids_for"):
            raise TypeError("terminology membership resolver is invalid")
        self._connection_factory = connection_factory
        self._memberships = memberships

    def resolve(
        self,
        *,
        principal: AuthenticatedPrincipal,
        locale: str,
    ) -> TranscriptCorrectionTerminology:
        try:
            authorization = resolve_terminology_authorization(
                principal,
                memberships=self._memberships,
                administrator_roles=_TERMINOLOGY_ADMINISTRATOR_ROLES,
            )
            with self._connection_factory() as connection:
                snapshot = store_current_terminology_snapshot(
                    connection,
                    authorization=authorization,
                    locale=locale,
                )
            constraints = compile_grammar_preservation_constraints(snapshot)
            return TranscriptCorrectionTerminology(
                snapshot_sha256=constraints.snapshot_sha256,
                exact_forms=constraints.exact_forms,
                authorized_replacements=constraints.authorized_replacements,
            )
        except (OSError, psycopg.Error, RuntimeError, TypeError, ValueError) as error:
            raise TranscriptCorrectionTerminologyUnavailable(
                "approved terminology could not be frozen"
            ) from error


__all__ = [
    "PersonalOrganizationTerminologyMemberships",
    "PostgresTranscriptCorrectionTerminologyResolver",
]
