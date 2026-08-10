from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

from yap_server.auth.principal import PrincipalKey
from yap_server.knowledge.okf_compiler import CompiledKnowledgeGeneration


@dataclass(frozen=True, slots=True)
class PermissionFilteredConcept:
    concept_id: str
    type: str
    title: str
    resource: str


@dataclass(frozen=True, slots=True)
class PermissionFilteredKnowledgeView:
    tenant_id: str
    generation_sha256: str
    permission_hash: str
    concepts: tuple[PermissionFilteredConcept, ...]


def build_permission_filtered_view(
    generation: CompiledKnowledgeGeneration,
    *,
    principal: PrincipalKey,
    purpose: str,
) -> PermissionFilteredKnowledgeView:
    """Return metadata only for concepts authorized by compiled policy."""

    if principal.tenant_id != generation.tenant_id:
        raise ValueError("knowledge principal crosses tenants")
    if not isinstance(purpose, str) or not purpose or purpose.strip() != purpose:
        raise ValueError("knowledge purpose is invalid")
    permissions = {item.path_prefix: item for item in generation.permissions}
    visible: list[PermissionFilteredConcept] = []
    admitted_hashes: list[str] = []
    for concept in generation.concepts:
        permission = permissions[concept.permission_path_prefix]
        if (
            principal not in permission.audience
            or principal in permission.denials
            or purpose not in permission.purposes
        ):
            continue
        admitted_hashes.append(permission.permission_sha256)
        visible.append(
            PermissionFilteredConcept(
                concept_id=concept.concept_id,
                type=str(concept.frontmatter["type"]),
                title=str(concept.frontmatter["title"]),
                resource=str(concept.frontmatter["resource"]),
            )
        )
    permission_identity = {
        "generationSha256": generation.generation_sha256,
        "tenantId": principal.tenant_id,
        "subjectId": principal.subject_id,
        "purpose": purpose,
        "permissionSha256s": sorted(set(admitted_hashes)),
        "visibleConceptIds": [item.concept_id for item in visible],
    }
    permission_hash = hashlib.sha256(
        json.dumps(permission_identity, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    return PermissionFilteredKnowledgeView(
        tenant_id=generation.tenant_id,
        generation_sha256=generation.generation_sha256,
        permission_hash=permission_hash,
        concepts=tuple(visible),
    )


__all__ = [
    "PermissionFilteredConcept",
    "PermissionFilteredKnowledgeView",
    "build_permission_filtered_view",
]
