from __future__ import annotations

from contextlib import AbstractContextManager, contextmanager
import os
from pathlib import Path
import stat
from typing import Callable, Iterator

import psycopg
from psycopg import Connection
from psycopg.conninfo import conninfo_to_dict

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

from .transcript_correction import TranscriptCorrectionTerminology
from .transcript_correction_service import TranscriptCorrectionTerminologyUnavailable


_MAXIMUM_DSN_BYTES = 4_096
_CONNECT_TIMEOUT_SECONDS = 3
_STATEMENT_TIMEOUT_MILLISECONDS = 3_000
_TERMINOLOGY_ADMINISTRATOR_ROLES = frozenset({"knowledge.terminology.admin"})

ConnectionFactory = Callable[
    [], AbstractContextManager[Connection[object]]
]


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
        connection_factory: ConnectionFactory,
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
            )
        except (OSError, psycopg.Error, RuntimeError, TypeError, ValueError) as error:
            raise TranscriptCorrectionTerminologyUnavailable(
                "approved terminology could not be frozen"
            ) from error


def postgres_connection_factory_from_private_dsn(
    path: Path,
) -> ConnectionFactory:
    dsn = read_private_postgres_dsn(path)
    conninfo_to_dict(dsn)

    @contextmanager
    def connect() -> Iterator[Connection[object]]:
        with psycopg.connect(
            dsn,
            connect_timeout=_CONNECT_TIMEOUT_SECONDS,
            options=(
                f"-c statement_timeout={_STATEMENT_TIMEOUT_MILLISECONDS} "
                f"-c lock_timeout={_STATEMENT_TIMEOUT_MILLISECONDS}"
            ),
        ) as connection:
            yield connection

    return connect


def read_private_postgres_dsn(path: Path) -> str:
    requested = Path(path)
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(requested, flags)
    except OSError as error:
        raise ValueError("terminology database credential file is unavailable") from error
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("terminology database credential must be a regular file")
        if metadata.st_size > _MAXIMUM_DSN_BYTES:
            raise ValueError("terminology database credential is too large")
        if os.name == "posix" and (
            stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_uid != os.geteuid()
        ):
            raise ValueError("terminology database credential is not owner-private")
        chunks: list[bytes] = []
        remaining = _MAXIMUM_DSN_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        if len(data) > _MAXIMUM_DSN_BYTES:
            raise ValueError("terminology database credential is too large")
    finally:
        os.close(descriptor)
    try:
        value = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("terminology database credential is invalid") from error
    dsn = value.removesuffix("\n")
    if (
        not dsn
        or dsn.strip() != dsn
        or "\0" in dsn
        or "\r" in dsn
        or "\n" in dsn
    ):
        raise ValueError("terminology database credential is invalid")
    return dsn


__all__ = [
    "PersonalOrganizationTerminologyMemberships",
    "PostgresTranscriptCorrectionTerminologyResolver",
    "postgres_connection_factory_from_private_dsn",
    "read_private_postgres_dsn",
]
