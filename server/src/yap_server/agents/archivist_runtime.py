from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from yap_server.jobs.service import RecordingJobService
from yap_server.private_postgres_connection import (
    private_postgres_connection_factory,
)

from .admission_client import AgentAdmissionClient
from .admission_protocol import UnixAgentAdmissionTransport
from .archivist import PostgresArchivistProcessor
from .archivist_ingestion_runner import PostgresArchivistIngestionRunner
from .archivist_ingestion_service import ArchivistIngestionService
from .archivist_service import ArchivistService


ARCHIVIST_RUNTIME = "YAP_ARCHIVIST_RUNTIME"
ARCHIVIST_ADMISSION_SOCKET = "YAP_ARCHIVIST_ADMISSION_SOCKET"
ARCHIVIST_KNOWLEDGE_DSN_FILE = "YAP_ARCHIVIST_KNOWLEDGE_DSN_FILE"

_REVIEWED_CAPTURE_POSTGRES = "reviewed_capture_postgres"
_DISABLED = "disabled"
_CONFIGURATION_PATHS = (
    ARCHIVIST_ADMISSION_SOCKET,
    ARCHIVIST_KNOWLEDGE_DSN_FILE,
)


@dataclass(slots=True)
class ArchivistRuntime:
    service: ArchivistIngestionService

    def close(self) -> None:
        self.service.close()


def build_archivist_runtime(
    environ: Mapping[str, str],
    *,
    authenticated_team_mode: bool,
    jobs: RecordingJobService,
) -> ArchivistRuntime | None:
    mode = environ.get(ARCHIVIST_RUNTIME)
    configured_paths = [name for name in _CONFIGURATION_PATHS if name in environ]
    if mode is None:
        if configured_paths:
            raise ValueError(
                "archivist configuration requires an explicit runtime mode"
            )
        return None
    if (
        not isinstance(mode, str)
        or mode.strip() != mode
        or mode not in {_DISABLED, _REVIEWED_CAPTURE_POSTGRES}
    ):
        raise ValueError("archivist runtime mode is invalid")
    if mode == _DISABLED:
        if configured_paths:
            raise ValueError("disabled archivist cannot include runtime paths")
        return None
    if not authenticated_team_mode:
        raise ValueError("archivist requires organization authentication")
    if not isinstance(jobs, RecordingJobService):
        raise TypeError("archivist requires the authoritative recording job service")

    socket_path = _absolute_path(environ, ARCHIVIST_ADMISSION_SOCKET)
    knowledge_dsn_path = _absolute_path(
        environ,
        ARCHIVIST_KNOWLEDGE_DSN_FILE,
    )
    admission = AgentAdmissionClient(UnixAgentAdmissionTransport(socket_path))
    connection_factory = private_postgres_connection_factory(knowledge_dsn_path)
    archivist = ArchivistService(
        admission=admission,
        processor=PostgresArchivistProcessor(connection_factory),
    )
    runner = PostgresArchivistIngestionRunner(
        jobs=jobs,
        connection_factory=connection_factory,
        archivist=archivist,
    )
    return ArchivistRuntime(service=ArchivistIngestionService(runner=runner))


def _absolute_path(environ: Mapping[str, str], variable: str) -> Path:
    value = environ.get(variable)
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError(f"{variable} is required")
    path = Path(value)
    if not path.is_absolute():
        raise ValueError(f"{variable} must be an absolute path")
    return path


__all__ = [
    "ARCHIVIST_ADMISSION_SOCKET",
    "ARCHIVIST_KNOWLEDGE_DSN_FILE",
    "ARCHIVIST_RUNTIME",
    "ArchivistRuntime",
    "build_archivist_runtime",
]
