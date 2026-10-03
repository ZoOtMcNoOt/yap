from __future__ import annotations

from dataclasses import dataclass
import json
import threading

import psycopg
from psycopg import Connection
import time
from pathlib import Path
from typing import Mapping

from yap_server.auth import AuthenticatedPrincipal
from yap_server.jobs.contract_values import valid_sha256
from yap_server.private_postgres_connection import (
    PrivatePostgresConnectionFactory,
    private_postgres_connection_factory,
)

from .knowledge_tool_contract import (
    KnowledgeGenerationStale,
    validate_bounded_text,
    validate_expected_generation,
)
from .okf_source import MAX_OKF_DOCUMENT_BYTES
from .knowledge_tool_audit import record_knowledge_tool_audit
from .knowledge_proposals import read_connection_proposal_in_transaction
from .postgres_relationship_retrieval import (
    KnowledgeConnectionNode,
    KnowledgeRelationshipResult,
    browse_postgres_knowledge_concepts,
    read_postgres_knowledge_neighborhood,
)

MAXIMUM_CONNECTION_RESPONSE_BYTES = 65_536
_CAPABILITIES = frozenset({"knowledge.tree", "knowledge.relationship.traverse"})


@dataclass(slots=True)
class KnowledgeConnectionsError(Exception):
    status: int
    code: str
    message: str
    retryable: bool = False


class KnowledgeConnectionsService:
    """Read reviewed relationships without invoking a reasoning/embedding model."""

    def __init__(self, connection_factory: PrivatePostgresConnectionFactory) -> None:
        self._connection_factory = connection_factory
        self._requests = threading.BoundedSemaphore(2)
        # Fail startup when the explicit database or required schema is absent.
        # Provisioning and reviewed generation admission remain operator actions.
        with self._connection_factory() as connection:
            for table in (
                "yap_knowledge_active_builds",
                "yap_knowledge_builds",
                "yap_knowledge_concepts",
                "yap_knowledge_relationships",
                "yap_knowledge_tool_audit",
                "yap_knowledge_proposals",
            ):
                connection.execute(f"SELECT 1 FROM {table} LIMIT 0")

    def browse(
        self, *, principal: AuthenticatedPrincipal, search_text: str
    ) -> dict[str, object]:
        if (
            not isinstance(search_text, str)
            or len(search_text) > 128
            or search_text.strip() != search_text
            or any(
                (ord(character) < 32 or 127 <= ord(character) <= 159)
                for character in search_text
            )
        ):
            raise KnowledgeConnectionsError(
                400, "INVALID_KNOWLEDGE_CONNECTIONS", "Topic search is invalid."
            )
        return self._query(principal, search_text=search_text)

    def read(
        self,
        *,
        principal: AuthenticatedPrincipal,
        concept_id: str,
        expected_generation_sha256: str,
    ) -> dict[str, object]:
        try:
            validate_bounded_text(concept_id, field="connection concept", maximum=512)
            if any(
                (ord(character) < 32 or 127 <= ord(character) <= 159)
                for character in concept_id
            ):
                raise ValueError("concept is invalid")
            if expected_generation_sha256 is None:
                raise ValueError("generation is required")
            validate_expected_generation(expected_generation_sha256)
        except (TypeError, ValueError):
            raise KnowledgeConnectionsError(
                400, "INVALID_KNOWLEDGE_CONNECTIONS", "Connection request is invalid."
            ) from None
        return self._query(
            principal,
            concept_id=concept_id,
            expected_generation_sha256=expected_generation_sha256,
        )

    def proposal(
        self, *, principal: AuthenticatedPrincipal, proposal_id: str
    ) -> dict[str, object]:
        if not valid_sha256(proposal_id):
            raise KnowledgeConnectionsError(
                400,
                "INVALID_KNOWLEDGE_CONNECTIONS",
                "Connection proposal reference is invalid.",
            )
        return self._query(principal, proposal_id=proposal_id)

    def _query(
        self,
        principal: AuthenticatedPrincipal,
        *,
        search_text: str | None = None,
        concept_id: str | None = None,
        expected_generation_sha256: str | None = None,
        proposal_id: str | None = None,
    ) -> dict[str, object]:
        if not self._requests.acquire(blocking=False):
            raise KnowledgeConnectionsError(
                429,
                "KNOWLEDGE_CONNECTIONS_BUSY",
                "Knowledge connections are busy. Try again.",
                True,
            )
        started = time.monotonic()
        try:
            with self._connection_factory() as connection:
                try:
                    return self._read_in_transaction(
                        connection,
                        principal=principal,
                        search_text=search_text,
                        concept_id=concept_id,
                        expected_generation_sha256=expected_generation_sha256,
                        started=started,
                        proposal_id=proposal_id,
                    )
                except Exception:
                    with connection.transaction():
                        record_knowledge_tool_audit(
                            connection,
                            principal=principal.key,
                            agent_id="knowledge-explorer",
                            operation="read-connection-proposal"
                            if proposal_id is not None
                            else "browse-connections"
                            if concept_id is None
                            else "read-connections",
                            outcome="failed",
                            result_count=0,
                            generation_sha256=None,
                            permission_hash=None,
                            authorization_hash=None,
                            duration_milliseconds=max(
                                0, int((time.monotonic() - started) * 1_000)
                            ),
                        )
                    raise
        except KnowledgeConnectionsError:
            raise
        except KnowledgeGenerationStale:
            raise KnowledgeConnectionsError(
                409,
                "KNOWLEDGE_GENERATION_STALE",
                "Knowledge changed. Refresh topics before exploring connections.",
            ) from None
        except PermissionError:
            raise KnowledgeConnectionsError(
                403,
                "KNOWLEDGE_CONNECTIONS_DENIED",
                "Knowledge connections are not permitted.",
            ) from None
        except LookupError:
            raise KnowledgeConnectionsError(
                503,
                "KNOWLEDGE_CONNECTIONS_UNAVAILABLE",
                "Reviewed knowledge is not available yet.",
            ) from None
        except Exception:
            raise KnowledgeConnectionsError(
                503,
                "KNOWLEDGE_CONNECTIONS_UNAVAILABLE",
                "Knowledge connections could not be read. Try again.",
                True,
            ) from None
        finally:
            self._requests.release()

    def _read_in_transaction(
        self,
        connection: Connection[object],
        *,
        principal: AuthenticatedPrincipal,
        search_text: str | None,
        concept_id: str | None,
        expected_generation_sha256: str | None,
        started: float,
        proposal_id: str | None,
    ) -> dict[str, object]:
        with connection.transaction():
            connection.execute("SET LOCAL statement_timeout = '5s'")
            connection.execute("SET LOCAL lock_timeout = '1s'")
            common = dict(
                principal=principal.key,
                purpose="knowledge.read",
                agent_capabilities=_CAPABILITIES,
            )
            if proposal_id is not None:
                wire = read_connection_proposal_in_transaction(
                    connection, proposal_id=proposal_id, **common
                )
                if wire is None:
                    raise KnowledgeConnectionsError(
                        404,
                        "KNOWLEDGE_PROPOSAL_UNAVAILABLE",
                        "This connection proposal is unavailable in the current knowledge view.",
                    )
                candidate = wire["candidate"]
                wire["candidate"] = {
                    "schemaVersion": candidate["schema_version"],
                    "sourceConceptId": candidate["source_concept_id"],
                    "targetConceptId": candidate["target_concept_id"],
                    "relationshipType": candidate["relationship_type"],
                    "rationale": candidate["rationale"],
                }
                for source in wire["sources"]:
                    node = source["node"]
                    source["node"] = _node(
                        KnowledgeConnectionNode(
                            concept_id=node["conceptId"],
                            type=node["type"],
                            title=node["title"],
                            source_path=node["sourcePath"],
                            source_revision=node["sourceRevision"],
                            content_sha256=node["contentSha256"],
                        )
                    )
                record_knowledge_tool_audit(
                    connection,
                    principal=principal.key,
                    agent_id="knowledge-explorer",
                    operation="read-connection-proposal",
                    outcome="succeeded",
                    result_count=1,
                    generation_sha256=str(wire["generationSha256"]),
                    permission_hash=str(wire["permissionHash"]),
                    authorization_hash=str(wire["authorizationHash"]),
                    duration_milliseconds=max(
                        0, int((time.monotonic() - started) * 1_000)
                    ),
                )
                if (
                    len(
                        json.dumps(
                            wire, ensure_ascii=True, separators=(",", ":")
                        ).encode("utf-8")
                    )
                    > MAXIMUM_CONNECTION_RESPONSE_BYTES
                ):
                    raise ValueError("connection proposal exceeds its response budget")
                return wire
            if concept_id is None:
                result = browse_postgres_knowledge_concepts(
                    connection, search_text=search_text, **common
                )
            else:
                result = read_postgres_knowledge_neighborhood(
                    connection,
                    concept_id=concept_id,
                    expected_generation_sha256=expected_generation_sha256,
                    **common,
                )
                if not result.nodes:
                    raise KnowledgeConnectionsError(
                        404,
                        "KNOWLEDGE_TOPIC_UNAVAILABLE",
                        "This topic is unavailable in the current knowledge view.",
                    )
            wire = {
                "schemaVersion": 1,
                "generationSha256": _hash(result.generation_sha256),
                "permissionHash": _hash(result.permission_hash),
                "authorizationHash": _hash(result.authorization_hash),
                "nodes": [_node(node) for node in result.nodes],
                "hasMore": result.has_more,
            }
            if concept_id is not None:
                wire["conceptId"] = concept_id
                wire["relationships"] = [_edge(edge) for edge in result.relationships]
            if (
                len(
                    json.dumps(wire, ensure_ascii=True, separators=(",", ":")).encode(
                        "utf-8"
                    )
                )
                > MAXIMUM_CONNECTION_RESPONSE_BYTES
            ):
                raise ValueError("knowledge response exceeds its budget")
            record_knowledge_tool_audit(
                connection,
                principal=principal.key,
                agent_id="knowledge-explorer",
                operation="browse-connections"
                if concept_id is None
                else "read-connections",
                outcome="succeeded",
                result_count=len(result.nodes)
                if concept_id is None
                else len(result.relationships),
                generation_sha256=result.generation_sha256,
                permission_hash=result.permission_hash,
                authorization_hash=result.authorization_hash,
                duration_milliseconds=max(0, int((time.monotonic() - started) * 1_000)),
            )
            return wire


def build_knowledge_connections_service(
    environ: Mapping[str, str], *, authenticated_team_mode: bool
) -> KnowledgeConnectionsService | None:
    mode = environ.get("YAP_KNOWLEDGE_CONNECTIONS_RUNTIME")
    path = environ.get("YAP_KNOWLEDGE_CONNECTIONS_DSN_FILE")
    if mode is None and path is None:
        return None
    if mode == "disabled" and path is None:
        return None
    if mode != "postgres" or not authenticated_team_mode:
        raise ValueError(
            "knowledge connections require explicit Postgres mode and organization authentication"
        )
    if (
        not isinstance(path, str)
        or path.strip() != path
        or not Path(path).is_absolute()
    ):
        raise ValueError("knowledge connections require an absolute private DSN file")
    try:
        return KnowledgeConnectionsService(
            private_postgres_connection_factory(Path(path))
        )
    except (ValueError, psycopg.Error):
        raise ValueError(
            "knowledge connections database configuration is unavailable"
        ) from None


def _text(value: str, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or len(value) > maximum
        or any(
            (ord(character) < 32 or 127 <= ord(character) <= 159) for character in value
        )
    ):
        raise ValueError("knowledge metadata is invalid")
    return value


def _hash(value: str) -> str:
    if not valid_sha256(value):
        raise ValueError("knowledge identity is invalid")
    return value


def _node(node: KnowledgeConnectionNode) -> dict[str, object]:
    return {
        "conceptId": _text(node.concept_id, 512),
        "type": _text(node.type, 128),
        "title": _text(node.title, 1_024),
        "sourcePath": _text(node.source_path, 512),
        "sourceRevision": _text(node.source_revision, 512),
        "contentSha256": _hash(node.content_sha256),
    }


def _edge(edge: KnowledgeRelationshipResult) -> dict[str, object]:
    if edge.authority not in {"asserted", "human_confirmed", "derived"}:
        raise ValueError("relationship authority is invalid")
    start, end = edge.source_char_start, edge.source_char_end
    if not (start is None and end is None) and not (
        type(start) is int
        and type(end) is int
        and 0 <= start < end <= MAX_OKF_DOCUMENT_BYTES
    ):
        raise ValueError("relationship citation is invalid")
    return {
        "relationshipId": _hash(edge.relationship_id),
        "sourceConceptId": _text(edge.source_concept_id, 512),
        "targetConceptId": _text(edge.target_concept_id, 512),
        "type": _text(edge.relationship_type, 128),
        "authority": edge.authority,
        "citation": {
            "sourcePath": _text(edge.source_path, 512),
            "sourceRevision": _text(edge.source_revision, 512),
            "contentSha256": _hash(edge.content_sha256),
            "charStart": start,
            "charEnd": end,
        },
    }
