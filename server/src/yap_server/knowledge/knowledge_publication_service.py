"""Explicit publication of a curator's already-reviewed complete generation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import threading
import time
from typing import Mapping

import psycopg

from yap_server.auth import AuthenticatedPrincipal
from yap_server.jobs.contract_values import identifier, valid_sha256
from yap_server.private_postgres_connection import (
    PrivatePostgresConnectionFactory,
    private_postgres_connection_factory,
)
from .generation_ledger import (
    activate_complete_generation,
    validate_complete_generation,
)
from .knowledge_source_admission import (
    admit_curated_knowledge_generation,
    require_knowledge_source_admission,
)
from .generation_ledger import stage_compiled_generation
from .knowledge_tool_audit import record_knowledge_tool_audit
from .reviewed_source_snapshot import (
    ReviewedSourceSnapshot,
    load_reviewed_source_snapshot,
)


PUBLICATION_PATH = "/v1/knowledge/publications"
SOURCE_PREPARATION_PATH = "/v1/knowledge/source-preparations"


@dataclass(slots=True)
class KnowledgePublicationError(Exception):
    status: int
    code: str
    message: str
    retryable: bool = False


def _not_found() -> KnowledgePublicationError:
    return KnowledgePublicationError(
        404, "KNOWLEDGE_PUBLICATION_NOT_FOUND", "Reviewed generation is unavailable."
    )


class KnowledgePublicationService:
    def __init__(
        self,
        connection_factory: PrivatePostgresConnectionFactory,
        *,
        reviewed_source: ReviewedSourceSnapshot | None = None,
    ) -> None:
        self._connection_factory = connection_factory
        self._reviewed_source = reviewed_source
        self._requests = threading.BoundedSemaphore(2)
        with self._connection_factory() as connection:
            for table in (
                "yap_knowledge_builds",
                "yap_knowledge_source_admissions",
                "yap_knowledge_active_builds",
                "yap_knowledge_activation_history",
                "yap_knowledge_tool_audit",
            ):
                connection.execute(f"SELECT 1 FROM {table} LIMIT 0")

    def inspect(
        self, *, principal: AuthenticatedPrincipal, generation_sha256: str
    ) -> dict[str, object]:
        return self._execute(principal, generation_sha256, publish=False)

    def inspect_source(self, *, principal: AuthenticatedPrincipal) -> dict[str, object]:
        return self._execute_source_preparation(principal, prepare=False)

    def prepare_source(
        self, *, principal: AuthenticatedPrincipal, request: Mapping[str, object]
    ) -> dict[str, object]:
        if (
            not isinstance(request, dict)
            or set(request) != {"schemaVersion", "expectedGenerationSha256"}
            or type(request["schemaVersion"]) is not int
            or request["schemaVersion"] != 1
            or not valid_sha256(request["expectedGenerationSha256"])
        ):
            raise ValueError("source preparation request differs from the contract")
        return self._execute_source_preparation(
            principal,
            prepare=True,
            expected_generation=request["expectedGenerationSha256"],
        )

    def _execute_source_preparation(
        self,
        principal: AuthenticatedPrincipal,
        *,
        prepare: bool,
        expected_generation: object = None,
    ) -> dict[str, object]:
        if "knowledge.curator" not in principal.roles:
            raise KnowledgePublicationError(
                403,
                "KNOWLEDGE_SOURCE_PREPARATION_DENIED",
                "Curator review authority is required.",
            )
        source = self._reviewed_source
        if source is None:
            raise KnowledgePublicationError(
                501, "NOT_IMPLEMENTED", "Reviewed source preparation is not configured."
            )
        if principal.tenant_id != source.tenant_id:
            raise KnowledgePublicationError(
                404,
                "KNOWLEDGE_SOURCE_PREPARATION_NOT_FOUND",
                "Reviewed source is unavailable.",
            )
        if prepare and expected_generation != source.generation_sha256:
            raise KnowledgePublicationError(
                409,
                "KNOWLEDGE_SOURCE_PREPARATION_CHANGED",
                "Reviewed source changed. Inspect it before preparing again.",
            )
        if not self._requests.acquire(blocking=False):
            raise KnowledgePublicationError(
                429,
                "KNOWLEDGE_SOURCE_PREPARATION_BUSY",
                "Finish an active knowledge request.",
                True,
            )
        started = time.monotonic()
        try:
            # The deployment's fixed identity binds source reads before any SQL writes.
            generation = source.compile()
            with self._connection_factory() as connection:
                with connection.transaction():
                    connection.execute("SET LOCAL statement_timeout = 5000")
                    connection.execute("SET LOCAL lock_timeout = 1000")
                    lock = (
                        "pg_advisory_xact_lock"
                        if prepare
                        else "pg_advisory_xact_lock_shared"
                    )
                    connection.execute(
                        f"SELECT {lock}(hashtextextended(%s, 0))",
                        (principal.tenant_id,),
                    )
                    existing = connection.execute(
                        """SELECT admission_sha256, reviewer_id, source_kind, source_path
                           FROM yap_knowledge_source_admissions
                           WHERE tenant_id = %s AND generation_sha256 = %s""",
                        (principal.tenant_id, generation.generation_sha256),
                    ).fetchone()
                    if existing is not None:
                        if existing[1] != principal.subject_id:
                            raise KnowledgePublicationError(
                                404,
                                "KNOWLEDGE_SOURCE_PREPARATION_NOT_FOUND",
                                "Reviewed source is unavailable.",
                            )
                        if existing[2:] != ("curated-repository", source.source_path):
                            raise ValueError(
                                "source preparation differs from existing admission"
                            )
                        admission = require_knowledge_source_admission(
                            connection,
                            tenant_id=principal.tenant_id,
                            admission_sha256=existing[0],
                            generation_sha256=generation.generation_sha256,
                            source_revision=generation.source_revision,
                        )
                    built = (
                        connection.execute(
                            "SELECT 1 FROM yap_knowledge_builds WHERE tenant_id = %s AND generation_sha256 = %s",
                            (principal.tenant_id, generation.generation_sha256),
                        ).fetchone()
                        is not None
                    )
                    status, active_hash = _publication_state(
                        connection, principal.tenant_id, generation.generation_sha256
                    )
                    if prepare:
                        if status == "retained" and not built:
                            raise KnowledgePublicationError(
                                409,
                                "KNOWLEDGE_SOURCE_PREPARATION_RETAINED",
                                "This published generation was pruned. Use an explicit restore procedure.",
                            )
                        admission = admit_curated_knowledge_generation(
                            connection,
                            principal=principal,
                            repository_revision=source.repository_revision,
                            source_path=source.source_path,
                            generation=generation,
                        )
                        stage_compiled_generation(
                            connection,
                            generation,
                            source_admission_sha256=admission.admission_sha256,
                        )
                    elif not built and status == "staged":
                        status = "unadmitted"
                    result: dict[str, object] = {
                        "schemaVersion": 1,
                        "generationSha256": generation.generation_sha256,
                        "sourceRevision": source.repository_revision,
                        "sourcePath": source.source_path,
                        "status": status,
                        "activeGenerationSha256": active_hash,
                        "conceptCount": len(generation.concepts),
                        "chunkCount": len(generation.chunks),
                        "relationshipCount": len(generation.relationships),
                        "permissionCount": len(generation.permissions),
                    }
                    if prepare:
                        result["changed"] = not built
                    record_knowledge_tool_audit(
                        connection,
                        principal=principal.key,
                        agent_id="knowledge-publication",
                        operation="prepare-reviewed-source"
                        if prepare
                        else "inspect-reviewed-source",
                        outcome="succeeded",
                        result_count=1,
                        generation_sha256=generation.generation_sha256,
                        permission_hash=None,
                        authorization_hash=admission.review_authority_sha256
                        if existing is not None or prepare
                        else None,
                        duration_milliseconds=max(
                            0, int((time.monotonic() - started) * 1000)
                        ),
                    )
                    return result
        except (
            ValueError,
            TypeError,
            LookupError,
            PermissionError,
            OSError,
            RecursionError,
        ):
            raise KnowledgePublicationError(
                409,
                "KNOWLEDGE_SOURCE_PREPARATION_INVALID",
                "Reviewed source could not pass the configured snapshot and staging checks.",
            ) from None
        except psycopg.Error:
            raise KnowledgePublicationError(
                503,
                "KNOWLEDGE_SOURCE_PREPARATION_UNAVAILABLE",
                "Source preparation could not be confirmed. Inspect it before retrying.",
                True,
            ) from None
        finally:
            self._requests.release()

    def publish(
        self, *, principal: AuthenticatedPrincipal, request: Mapping[str, object]
    ) -> dict[str, object]:
        if (
            not isinstance(request, dict)
            or set(request)
            != {"schemaVersion", "generationSha256", "expectedActiveGenerationSha256"}
            or type(request["schemaVersion"]) is not int
            or request["schemaVersion"] != 1
            or not valid_sha256(request["generationSha256"])
            or (
                request["expectedActiveGenerationSha256"] is not None
                and not valid_sha256(request["expectedActiveGenerationSha256"])
            )
        ):
            raise ValueError("publication request differs from the contract")
        return self._execute(
            principal,
            str(request["generationSha256"]),
            publish=True,
            expected_active=request["expectedActiveGenerationSha256"],
        )

    def _execute(
        self,
        principal: AuthenticatedPrincipal,
        generation_sha256: str,
        *,
        publish: bool,
        expected_active: object = None,
    ) -> dict[str, object]:
        if "knowledge.curator" not in principal.roles:
            raise KnowledgePublicationError(
                403,
                "KNOWLEDGE_PUBLICATION_DENIED",
                "Curator review authority is required.",
            )
        if not valid_sha256(generation_sha256):
            raise ValueError("publication generation reference is invalid")
        if not self._requests.acquire(blocking=False):
            raise KnowledgePublicationError(
                429,
                "KNOWLEDGE_PUBLICATION_BUSY",
                "Finish an active publication request.",
                True,
            )
        started = time.monotonic()
        try:
            with self._connection_factory() as connection:
                with connection.transaction():
                    connection.execute("SET LOCAL statement_timeout = 5000")
                    connection.execute("SET LOCAL lock_timeout = 1000")
                    # The same owner serializes staging, vectors, reads and activation.
                    lock = (
                        "pg_advisory_xact_lock"
                        if publish
                        else "pg_advisory_xact_lock_shared"
                    )
                    connection.execute(
                        f"SELECT {lock}(hashtextextended(%s, 0))",
                        (principal.tenant_id,),
                    )
                    row = connection.execute(
                        """SELECT b.source_revision, b.concept_count, b.chunk_count,
                                  b.relationship_count, b.permission_count,
                                  b.source_admission_sha256
                           FROM yap_knowledge_builds b
                           JOIN yap_knowledge_source_admissions a
                             ON a.tenant_id = b.tenant_id
                            AND a.admission_sha256 = b.source_admission_sha256
                           WHERE b.tenant_id = %s AND b.generation_sha256 = %s
                             AND a.reviewer_id = %s
                             AND a.source_kind = 'curated-repository'""",
                        (principal.tenant_id, generation_sha256, principal.subject_id),
                    ).fetchone()
                    if row is None:
                        raise _not_found()
                    identifier(row[0], 512, "reviewed source revision")
                    if any(type(count) is not int or count < 0 for count in row[1:5]):
                        raise ValueError("reviewed generation counts are invalid")
                    admission = require_knowledge_source_admission(
                        connection,
                        tenant_id=principal.tenant_id,
                        admission_sha256=row[5],
                        generation_sha256=generation_sha256,
                        source_revision=row[0],
                    )
                    status, active_hash = _publication_state(
                        connection, principal.tenant_id, generation_sha256
                    )
                    retained = status == "retained"
                    changed = False
                    if publish:
                        if active_hash == generation_sha256:
                            validate_complete_generation(
                                connection,
                                tenant_id=principal.tenant_id,
                                generation_sha256=generation_sha256,
                            )
                        else:
                            if active_hash != expected_active:
                                raise KnowledgePublicationError(
                                    409,
                                    "KNOWLEDGE_PUBLICATION_CHANGED",
                                    "Active knowledge changed. Inspect the generation before publishing again.",
                                )
                            if retained:
                                raise KnowledgePublicationError(
                                    409,
                                    "KNOWLEDGE_PUBLICATION_RETAINED",
                                    "This generation was already published. Use an explicit rollback.",
                                )
                            activate_complete_generation(
                                connection,
                                tenant_id=principal.tenant_id,
                                generation_sha256=generation_sha256,
                            )
                            changed = True
                        status = "active"
                    result: dict[str, object] = {
                        "schemaVersion": 1,
                        "generationSha256": generation_sha256,
                        "sourceRevision": row[0],
                        "status": status,
                        "activeGenerationSha256": generation_sha256
                        if publish
                        else active_hash,
                        "conceptCount": row[1],
                        "chunkCount": row[2],
                        "relationshipCount": row[3],
                        "permissionCount": row[4],
                    }
                    if publish:
                        result.update(
                            changed=changed, previousActiveGenerationSha256=active_hash
                        )
                    record_knowledge_tool_audit(
                        connection,
                        principal=principal.key,
                        agent_id="knowledge-publication",
                        operation="publish-generation"
                        if publish
                        else "inspect-generation-publication",
                        outcome="succeeded",
                        result_count=1,
                        generation_sha256=generation_sha256,
                        permission_hash=None,
                        authorization_hash=admission.review_authority_sha256,
                        duration_milliseconds=max(
                            0, int((time.monotonic() - started) * 1000)
                        ),
                    )
                    return result
        except (TypeError, ValueError, LookupError, PermissionError):
            raise KnowledgePublicationError(
                409,
                "KNOWLEDGE_PUBLICATION_INVALID",
                "Reviewed generation could not pass the complete publication checks.",
            ) from None
        except psycopg.Error:
            # The transaction owns both activation and its success audit.
            raise KnowledgePublicationError(
                503,
                "KNOWLEDGE_PUBLICATION_UNAVAILABLE",
                "Publication could not be confirmed. Inspect the active generation before retrying.",
                True,
            ) from None
        finally:
            self._requests.release()


def build_knowledge_publication_service(
    environ: Mapping[str, str], *, authenticated_team_mode: bool
) -> KnowledgePublicationService | None:
    mode = environ.get("YAP_KNOWLEDGE_PUBLICATION_RUNTIME")
    path = environ.get("YAP_KNOWLEDGE_PUBLICATION_DSN_FILE")
    source_file = environ.get("YAP_KNOWLEDGE_REVIEWED_SOURCE_FILE")
    source_digest = environ.get("YAP_KNOWLEDGE_REVIEWED_SOURCE_SHA256")
    if (
        (mode is None or mode == "disabled")
        and path is None
        and source_file is None
        and source_digest is None
    ):
        return None
    if mode != "postgres" or not authenticated_team_mode:
        raise ValueError(
            "knowledge publication requires explicit Postgres mode and organization authentication"
        )
    if (
        not isinstance(path, str)
        or path.strip() != path
        or not Path(path).is_absolute()
    ):
        raise ValueError("knowledge publication requires an absolute private DSN file")
    reviewed_source = None
    if source_file is not None or source_digest is not None:
        try:
            reviewed_source = load_reviewed_source_snapshot(source_file, source_digest)
        except (ValueError, OSError):
            raise ValueError(
                "reviewed source deployment configuration is unavailable"
            ) from None
    try:
        return KnowledgePublicationService(
            private_postgres_connection_factory(Path(path)),
            reviewed_source=reviewed_source,
        )
    except (ValueError, psycopg.Error):
        raise ValueError(
            "knowledge publication database configuration is unavailable"
        ) from None


def _publication_state(connection, tenant_id: str, generation_sha256: str):
    active = connection.execute(
        "SELECT generation_sha256 FROM yap_knowledge_active_builds WHERE tenant_id = %s",
        (tenant_id,),
    ).fetchone()
    active_hash = None if active is None else active[0]
    retained = (
        connection.execute(
            """SELECT 1 FROM yap_knowledge_activation_history
           WHERE tenant_id = %s AND generation_sha256 = %s LIMIT 1""",
            (tenant_id, generation_sha256),
        ).fetchone()
        is not None
    )
    return (
        "active"
        if active_hash == generation_sha256
        else "retained"
        if retained
        else "staged"
    ), active_hash
