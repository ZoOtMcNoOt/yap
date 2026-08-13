from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from yap_server.private_postgres_connection import (
    private_postgres_connection_factory,
)

from .admission_client import AgentAdmissionClient
from .admission_protocol import UnixAgentAdmissionTransport
from .librarian import PostgresLibrarianEvidenceReader
from .librarian_query_service import LibrarianQueryService
from .librarian_result_audit import PostgresLibrarianResultAuditor
from .librarian_service import LibrarianService


LIBRARIAN_RUNTIME = "YAP_LIBRARIAN_RUNTIME"
LIBRARIAN_ADMISSION_SOCKET = "YAP_LIBRARIAN_ADMISSION_SOCKET"
LIBRARIAN_KNOWLEDGE_DSN_FILE = "YAP_LIBRARIAN_KNOWLEDGE_DSN_FILE"

_PERMISSION_SAFE_POSTGRES = "permission_safe_postgres"
_DISABLED = "disabled"
_CONFIGURATION_PATHS = (
    LIBRARIAN_ADMISSION_SOCKET,
    LIBRARIAN_KNOWLEDGE_DSN_FILE,
)


@dataclass(slots=True)
class LibrarianRuntime:
    service: LibrarianQueryService

    def close(self) -> None:
        self.service.close()


def build_librarian_runtime(
    environ: Mapping[str, str],
    *,
    authenticated_team_mode: bool,
) -> LibrarianRuntime | None:
    mode = environ.get(LIBRARIAN_RUNTIME)
    configured_paths = [name for name in _CONFIGURATION_PATHS if name in environ]
    if mode is None:
        if configured_paths:
            raise ValueError(
                "librarian configuration requires an explicit runtime mode"
            )
        return None
    if (
        not isinstance(mode, str)
        or mode.strip() != mode
        or mode not in {_DISABLED, _PERMISSION_SAFE_POSTGRES}
    ):
        raise ValueError("librarian runtime mode is invalid")
    if mode == _DISABLED:
        if configured_paths:
            raise ValueError("disabled librarian cannot include runtime paths")
        return None
    if not authenticated_team_mode:
        raise ValueError("librarian requires organization authentication")

    socket_path = _absolute_path(environ, LIBRARIAN_ADMISSION_SOCKET)
    knowledge_dsn_path = _absolute_path(
        environ,
        LIBRARIAN_KNOWLEDGE_DSN_FILE,
    )
    admission = AgentAdmissionClient(UnixAgentAdmissionTransport(socket_path))
    connection_factory = private_postgres_connection_factory(knowledge_dsn_path)
    librarian = LibrarianService(
        admission=admission,
        evidence_reader=PostgresLibrarianEvidenceReader(connection_factory),
        result_auditor=PostgresLibrarianResultAuditor(connection_factory),
    )
    return LibrarianRuntime(service=LibrarianQueryService(librarian=librarian))


def _absolute_path(environ: Mapping[str, str], variable: str) -> Path:
    value = environ.get(variable)
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError(f"{variable} is required")
    path = Path(value)
    if not path.is_absolute():
        raise ValueError(f"{variable} must be an absolute path")
    return path


__all__ = [
    "LIBRARIAN_ADMISSION_SOCKET",
    "LIBRARIAN_KNOWLEDGE_DSN_FILE",
    "LIBRARIAN_RUNTIME",
    "LibrarianRuntime",
    "build_librarian_runtime",
]
