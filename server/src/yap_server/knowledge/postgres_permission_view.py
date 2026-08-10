from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

from psycopg import Connection

from yap_server.auth.principal import PrincipalKey


@dataclass(frozen=True, slots=True)
class AuthorizedKnowledgeQuery:
    tenant_id: str
    subject_id: str
    purpose: str
    generation_sha256: str
    permission_hash: str
    authorization_hash: str
    required_capability: str
    visible_concept_ids: frozenset[str]


def authorize_knowledge_query(
    connection: Connection[object],
    *,
    principal: PrincipalKey,
    purpose: str,
    agent_capabilities: frozenset[str],
    required_capability: str,
    expected_generation_sha256: str | None = None,
) -> AuthorizedKnowledgeQuery:
    """Bind one query to the active compiled allowlist before retrieval."""

    if required_capability not in agent_capabilities:
        raise PermissionError("agent capability does not authorize knowledge query")
    if not purpose or purpose.strip() != purpose or len(purpose) > 128:
        raise ValueError("knowledge purpose is invalid")
    active = connection.execute(
        """SELECT generation_sha256 FROM yap_knowledge_active_builds
           WHERE tenant_id = %s""",
        (principal.tenant_id,),
    ).fetchone()
    if active is None:
        raise LookupError("tenant has no active knowledge generation")
    generation_sha256 = active[0]
    if (
        expected_generation_sha256 is not None
        and expected_generation_sha256 != generation_sha256
    ):
        raise ValueError("knowledge generation is stale")
    rows = connection.execute(
        """SELECT c.concept_id, p.permission_sha256
           FROM yap_knowledge_concepts c
           JOIN yap_knowledge_permissions p
             ON p.tenant_id = c.tenant_id
            AND p.generation_sha256 = c.generation_sha256
            AND p.path_prefix = c.permission_path_prefix
           JOIN yap_knowledge_permission_audience a
             ON a.tenant_id = p.tenant_id
            AND a.generation_sha256 = p.generation_sha256
            AND a.path_prefix = p.path_prefix
            AND a.subject_id = %s
           JOIN yap_knowledge_permission_purposes u
             ON u.tenant_id = p.tenant_id
            AND u.generation_sha256 = p.generation_sha256
            AND u.path_prefix = p.path_prefix
            AND u.purpose = %s
           WHERE c.tenant_id = %s AND c.generation_sha256 = %s
             AND NOT EXISTS (
                SELECT 1 FROM yap_knowledge_permission_denials d
                WHERE d.tenant_id = p.tenant_id
                  AND d.generation_sha256 = p.generation_sha256
                  AND d.path_prefix = p.path_prefix
                  AND d.subject_id = %s
             )
           ORDER BY c.concept_id""",
        (
            principal.subject_id,
            purpose,
            principal.tenant_id,
            generation_sha256,
            principal.subject_id,
        ),
    ).fetchall()
    visible_ids = frozenset(row[0] for row in rows)
    identity = {
        "tenantId": principal.tenant_id,
        "subjectId": principal.subject_id,
        "purpose": purpose,
        "generationSha256": generation_sha256,
        "permissionSha256s": sorted({row[1] for row in rows}),
        "visibleConceptIds": sorted(visible_ids),
    }
    permission_hash = hashlib.sha256(
        json.dumps(identity, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    authorization_hash = hashlib.sha256(
        json.dumps(
            {
                "permissionHash": permission_hash,
                "requiredCapability": required_capability,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return AuthorizedKnowledgeQuery(
        tenant_id=principal.tenant_id,
        subject_id=principal.subject_id,
        purpose=purpose,
        generation_sha256=generation_sha256,
        permission_hash=permission_hash,
        authorization_hash=authorization_hash,
        required_capability=required_capability,
        visible_concept_ids=visible_ids,
    )


__all__ = ["AuthorizedKnowledgeQuery", "authorize_knowledge_query"]
