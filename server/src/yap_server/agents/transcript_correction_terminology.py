from __future__ import annotations

import psycopg

from yap_server.auth import AuthenticatedPrincipal
from yap_server.knowledge.terminology_policy import TerminologyPolicy
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


class PostgresTranscriptCorrectionTerminologyResolver:
    """Freeze one canonical terminology snapshot before broker admission."""

    def __init__(
        self,
        *,
        connection_factory: PrivatePostgresConnectionFactory,
        policy: TerminologyPolicy,
    ) -> None:
        if not callable(connection_factory):
            raise TypeError("terminology connection factory is invalid")
        if not isinstance(policy, TerminologyPolicy):
            raise TypeError("terminology policy is invalid")
        self._connection_factory = connection_factory
        self._policy = policy

    def resolve(
        self,
        *,
        principal: AuthenticatedPrincipal,
        locale: str,
    ) -> TranscriptCorrectionTerminology:
        try:
            authorization = self._policy.authorization(principal)
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
    "PostgresTranscriptCorrectionTerminologyResolver",
]
