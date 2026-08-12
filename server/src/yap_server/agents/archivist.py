from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
from typing import Callable

from psycopg import Connection
import yaml

from yap_server.agents.admission_protocol import is_lower_sha256
from yap_server.auth import AuthenticatedPrincipal
from yap_server.knowledge.cancellable_database_operation import (
    run_cancellable_database_operation,
)
from yap_server.knowledge.generation_ledger import (
    KnowledgeGenerationDescriptor,
    stage_compiled_generation,
)
from yap_server.knowledge.knowledge_source_admission import (
    admit_reviewed_capture_generation,
)
from yap_server.knowledge.knowledge_tool_contract import KnowledgeToolCancelled
from yap_server.knowledge.okf_compiler import (
    CompiledKnowledgeGeneration,
    compile_okf_bundle,
)
from yap_server.knowledge.reviewed_capture_ledger import (
    ReviewedCaptureDescriptor,
    read_reviewed_capture,
)

@dataclass(frozen=True, slots=True)
class ArchivistRequest:
    capture_sha256: str

    def __post_init__(self) -> None:
        if not is_lower_sha256(self.capture_sha256):
            raise ValueError("archivist capture identity is invalid")

    @classmethod
    def from_wire(cls, value: object) -> ArchivistRequest:
        if not isinstance(value, dict) or set(value) != {
            "schemaVersion",
            "captureSha256",
        }:
            raise ValueError("archivist request fields differ from the contract")
        if isinstance(value["schemaVersion"], bool) or value["schemaVersion"] != 1:
            raise ValueError("archivist request schema is unsupported")
        return cls(capture_sha256=value["captureSha256"])


@dataclass(frozen=True, slots=True)
class ArchivistIngestion:
    capture_sha256: str
    source_admission_sha256: str
    generation: KnowledgeGenerationDescriptor


@dataclass(frozen=True, slots=True)
class ArchivistJobView:
    request_id: str
    status: str
    capture_sha256: str
    source_admission_sha256: str | None = None
    generation_sha256: str | None = None
    concept_count: int | None = None
    permission_count: int | None = None
    reason: str | None = None

    def to_wire(self) -> dict[str, object]:
        value: dict[str, object] = {
            "schemaVersion": 1,
            "requestId": self.request_id,
            "status": self.status,
            "captureSha256": self.capture_sha256,
        }
        for key, item in (
            ("sourceAdmissionSha256", self.source_admission_sha256),
            ("generationSha256", self.generation_sha256),
            ("conceptCount", self.concept_count),
            ("permissionCount", self.permission_count),
            ("reason", self.reason),
        ):
            if item is not None:
                value[key] = item
        return value


ConnectionFactory = Callable[[], AbstractContextManager[Connection[object]]]


class PostgresArchivistProcessor:
    """Compile and stage one exact durable reviewed capture without an LLM."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._connection_factory = connection_factory

    def ingest(
        self,
        request: ArchivistRequest,
        *,
        principal: AuthenticatedPrincipal,
        cancellation: threading.Event,
    ) -> ArchivistIngestion:
        if cancellation.is_set():
            raise KnowledgeToolCancelled("archivist ingestion was cancelled")
        with self._connection_factory() as connection:
            capture = read_reviewed_capture(
                connection,
                principal=principal.key,
                capture_sha256=request.capture_sha256,
            )
        generation = compile_reviewed_capture_generation(
            capture,
            principal=principal,
        )
        if cancellation.is_set():
            raise KnowledgeToolCancelled("archivist ingestion was cancelled")

        with self._connection_factory() as connection:
            def persist() -> ArchivistIngestion:
                with connection.transaction():
                    durable_capture = read_reviewed_capture(
                        connection,
                        principal=principal.key,
                        capture_sha256=request.capture_sha256,
                    )
                    if durable_capture != capture:
                        raise ValueError(
                            "reviewed capture changed during archivist ingestion"
                        )
                    admission = admit_reviewed_capture_generation(
                        connection,
                        principal=principal,
                        capture_sha256=capture.capture_sha256,
                        generation=generation,
                    )
                    staged = stage_compiled_generation(
                        connection,
                        generation,
                        source_admission_sha256=admission.admission_sha256,
                    )
                return ArchivistIngestion(
                    capture_sha256=capture.capture_sha256,
                    source_admission_sha256=admission.admission_sha256,
                    generation=staged,
                )

            return run_cancellable_database_operation(
                connection,
                cancellation,
                persist,
            )


class ArchivistContainmentError(RuntimeError):
    pass


def compile_reviewed_capture_generation(
    capture: ReviewedCaptureDescriptor,
    *,
    principal: AuthenticatedPrincipal,
) -> CompiledKnowledgeGeneration:
    if not isinstance(capture, ReviewedCaptureDescriptor):
        raise TypeError("reviewed capture type is invalid")
    if (
        capture.tenant_id != principal.tenant_id
        or capture.owner_id != principal.subject_id
    ):
        raise PermissionError("reviewed capture is not owned by the principal")
    try:
        return _compile_private_reviewed_capture(capture, principal)
    except OSError as error:
        raise ArchivistContainmentError(
            "archivist private compilation workspace was not contained"
        ) from error


def _compile_private_reviewed_capture(
    capture: ReviewedCaptureDescriptor,
    principal: AuthenticatedPrincipal,
) -> CompiledKnowledgeGeneration:
    with TemporaryDirectory(prefix="yap-archivist-") as temporary:
        root = Path(temporary)
        if os.name == "posix":
            root.chmod(0o700)
        meetings = root / "meetings"
        permissions = root / "permissions"
        meetings.mkdir(mode=0o700)
        permissions.mkdir(mode=0o700)
        _write_private_text(
            root / "index.md",
            "---\nokf_version: '0.1'\n---\n# Reviewed knowledge\n",
        )
        _write_private_text(
            meetings / f"{capture.job_id}.md",
            capture.normalized_okf,
        )
        permission = {
            "path_prefix": "meetings/",
            "audience": {
                "users": [
                    {
                        "tenant_id": principal.tenant_id,
                        "subject_id": principal.subject_id,
                    }
                ]
            },
            "purposes": ["knowledge.read"],
            "classification": "confidential",
            "denials": {"users": []},
        }
        _write_private_text(
            permissions / "meetings.yml",
            yaml.safe_dump(
                permission,
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=False,
            ),
        )
        return compile_okf_bundle(
            root,
            tenant_id=principal.tenant_id,
            source_revision=capture.capture_sha256,
        )


def _write_private_text(path: Path, value: str) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            descriptor = -1
            output.write(value)
            output.flush()
            os.fsync(output.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


__all__ = [
    "ArchivistContainmentError",
    "ArchivistIngestion",
    "ArchivistJobView",
    "ArchivistRequest",
    "PostgresArchivistProcessor",
    "compile_reviewed_capture_generation",
]
