from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Mapping

from .okf_profile import (
    concept_links,
    concept_redirects,
    freeze,
    identity,
    json_value,
    validate_concept_profile,
)
from .okf_source import (
    MAX_OKF_BUNDLE_BYTES,
    discover_markdown,
    read_okf_document,
    real_bundle_directory,
)
from .okf_projection import (
    CompiledChunk,
    CompiledRelationship,
    compile_chunks,
    compile_relationships,
)
from .permission_policy import (
    CompiledPermission,
    compile_permissions,
    compiled_permission_sha256,
    effective_permission,
    permission_record,
    validate_compiled_permission,
)


@dataclass(frozen=True, slots=True)
class CompiledConcept:
    concept_id: str
    source_path: str
    content_sha256: str
    frontmatter: Mapping[str, object]
    body: str
    links: tuple[str, ...]
    broken_links: tuple[str, ...]
    redirect_history: tuple[str, ...]
    permission_path_prefix: str


@dataclass(frozen=True, slots=True)
class CompiledKnowledgeGeneration:
    tenant_id: str
    source_revision: str
    okf_version: str
    concepts: tuple[CompiledConcept, ...]
    chunks: tuple[CompiledChunk, ...]
    relationships: tuple[CompiledRelationship, ...]
    permissions: tuple[CompiledPermission, ...]
    generation_sha256: str


def compile_okf_bundle(
    bundle_root: Path,
    *,
    tenant_id: str,
    source_revision: str,
) -> CompiledKnowledgeGeneration:
    """Compile one bounded OKF tree into a deterministic immutable generation."""

    tenant = identity(tenant_id, "tenant_id")
    revision = identity(source_revision, "source_revision")
    root = real_bundle_directory(bundle_root)
    markdown_paths = discover_markdown(root)
    if Path("index.md") not in markdown_paths:
        raise ValueError("OKF bundle root index.md is required")

    documents: dict[Path, tuple[dict[str, object], str, bytes]] = {}
    total_bytes = 0
    for relative_path in markdown_paths:
        document = read_okf_document(root, relative_path)
        total_bytes += len(document[2])
        if total_bytes > MAX_OKF_BUNDLE_BYTES:
            raise ValueError("OKF bundle exceeds its byte limit")
        documents[relative_path] = document

    root_frontmatter, _, _ = documents[Path("index.md")]
    if root_frontmatter.get("okf_version") != "0.1":
        raise ValueError("OKF bundle must declare pinned okf_version 0.1")

    permissions = compile_permissions(root, tenant)
    concept_paths = {
        path
        for path in markdown_paths
        if path.name.casefold() not in {"index.md", "log.md"}
    }
    concepts: list[CompiledConcept] = []
    chunks: list[CompiledChunk] = []
    relationships: list[CompiledRelationship] = []
    resources: set[str] = set()
    redirect_owners: dict[str, str] = {}
    for path in sorted(concept_paths, key=lambda item: item.as_posix()):
        frontmatter, markdown, source = documents[path]
        validate_concept_profile(frontmatter, tenant, path, resources)
        permission = effective_permission(path, permissions)
        links = concept_links(path, markdown)
        broken_links = tuple(
            link for link in links if Path(f"{link}.md") not in concept_paths
        )
        redirects = concept_redirects(frontmatter, path)
        for redirect in redirects:
            owner = redirect_owners.setdefault(
                redirect, path.with_suffix("").as_posix()
            )
            if owner != path.with_suffix("").as_posix():
                raise ValueError("OKF redirect is claimed by multiple concepts")
        canonical_frontmatter = json_value(frontmatter, "frontmatter")
        assert isinstance(canonical_frontmatter, dict)
        record = {
            "conceptId": path.with_suffix("").as_posix(),
            "sourcePath": path.as_posix(),
            "contentSha256": hashlib.sha256(source).hexdigest(),
            "frontmatter": canonical_frontmatter,
            "body": markdown,
            "links": list(links),
            "brokenLinks": list(broken_links),
            "redirectHistory": list(redirects),
            "permissionPathPrefix": permission.path_prefix,
        }
        chunks.extend(
            compile_chunks(
                concept_id=record["conceptId"],
                source_path=record["sourcePath"],
                body=markdown,
                permission_sha256=permission.permission_sha256,
            )
        )
        relationships.extend(
            compile_relationships(
                concept_id=record["conceptId"],
                source_path=record["sourcePath"],
                body=markdown,
                frontmatter=canonical_frontmatter,
            )
        )
        concepts.append(
            CompiledConcept(
                concept_id=record["conceptId"],
                source_path=record["sourcePath"],
                content_sha256=record["contentSha256"],
                frontmatter=freeze(canonical_frontmatter),
                body=markdown,
                links=links,
                broken_links=broken_links,
                redirect_history=redirects,
                permission_path_prefix=permission.path_prefix,
            )
        )

    current_ids = {item.concept_id for item in concepts}
    if current_ids.intersection(redirect_owners):
        raise ValueError("OKF redirect collides with a current concept")

    generation = CompiledKnowledgeGeneration(
        tenant_id=tenant,
        source_revision=revision,
        okf_version="0.1",
        concepts=tuple(concepts),
        chunks=tuple(chunks),
        relationships=tuple(relationships),
        permissions=permissions,
        generation_sha256="",
    )
    generation = replace(
        generation,
        generation_sha256=compiled_generation_sha256(generation),
    )
    validate_compiled_generation(generation)
    return generation


def compiled_generation_record(
    value: CompiledKnowledgeGeneration,
) -> dict[str, object]:
    """Return the canonical immutable identity record for one generation."""

    return {
        "schemaVersion": 1,
        "okfVersion": value.okf_version,
        "tenantId": value.tenant_id,
        "sourceRevision": value.source_revision,
        "concepts": [concept_record(item) for item in value.concepts],
        "chunks": [chunk_record(item) for item in value.chunks],
        "relationships": [relationship_record(item) for item in value.relationships],
        "permissions": [permission_record(item) for item in value.permissions],
    }


def compiled_generation_sha256(value: CompiledKnowledgeGeneration) -> str:
    return hashlib.sha256(
        json.dumps(
            compiled_generation_record(value),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def validate_compiled_generation(value: CompiledKnowledgeGeneration) -> None:
    """Recompute every deterministic projection and the aggregate identity."""

    if not isinstance(value, CompiledKnowledgeGeneration):
        raise TypeError("compiled generation has an invalid type")
    tenant = identity(value.tenant_id, "tenant_id")
    identity(value.source_revision, "source_revision")
    if value.okf_version != "0.1":
        raise ValueError("compiled generation OKF version is invalid")
    for field, items in (
        ("concepts", value.concepts),
        ("chunks", value.chunks),
        ("relationships", value.relationships),
        ("permissions", value.permissions),
    ):
        if not isinstance(items, tuple):
            raise TypeError(f"compiled generation {field} must be immutable")

    if tuple(sorted(value.permissions, key=lambda item: item.path_prefix)) != value.permissions:
        raise ValueError("compiled generation permissions are not canonical")
    if len({item.path_prefix for item in value.permissions}) != len(value.permissions):
        raise ValueError("compiled generation permissions are duplicated")
    for permission in value.permissions:
        validate_compiled_permission(permission, tenant_id=tenant)
        if compiled_permission_sha256(permission) != permission.permission_sha256:
            raise ValueError("compiled generation permission identity differs")

    concept_ids = tuple(item.concept_id for item in value.concepts)
    if concept_ids != tuple(sorted(concept_ids)) or len(set(concept_ids)) != len(concept_ids):
        raise ValueError("compiled generation concepts are not canonical")
    concept_paths = {_compiled_source_path(item.source_path) for item in value.concepts}
    expected_chunks: list[CompiledChunk] = []
    expected_relationships: list[CompiledRelationship] = []
    redirect_owners: dict[str, str] = {}
    resources: set[str] = set()
    for concept in value.concepts:
        path = _compiled_source_path(concept.source_path)
        if (
            path.is_absolute()
            or path.suffix.casefold() != ".md"
            or path.with_suffix("").as_posix() != concept.concept_id
        ):
            raise ValueError("compiled concept path identity is invalid")
        frontmatter = _canonical_mapping(concept.frontmatter, "compiled frontmatter")
        validate_concept_profile(frontmatter, tenant, path, resources)
        if (
            not isinstance(concept.content_sha256, str)
            or len(concept.content_sha256) != 64
            or any(character not in "0123456789abcdef" for character in concept.content_sha256)
        ):
            raise ValueError("compiled concept content identity is invalid")
        permission = effective_permission(path, value.permissions)
        links = concept_links(path, concept.body)
        broken_links = tuple(
            link for link in links if PurePosixPath(f"{link}.md") not in concept_paths
        )
        redirects = concept_redirects(frontmatter, path)
        for redirect in redirects:
            owner = redirect_owners.setdefault(redirect, concept.concept_id)
            if owner != concept.concept_id:
                raise ValueError("compiled redirect is claimed by multiple concepts")
        if (
            concept.links != links
            or concept.broken_links != broken_links
            or concept.redirect_history != redirects
            or concept.permission_path_prefix != permission.path_prefix
        ):
            raise ValueError("compiled concept projection differs from its source")
        expected_chunks.extend(
            compile_chunks(
                concept_id=concept.concept_id,
                source_path=concept.source_path,
                body=concept.body,
                permission_sha256=permission.permission_sha256,
            )
        )
        expected_relationships.extend(
            compile_relationships(
                concept_id=concept.concept_id,
                source_path=concept.source_path,
                body=concept.body,
                frontmatter=frontmatter,
            )
        )
    if set(concept_ids).intersection(redirect_owners):
        raise ValueError("compiled redirect collides with a current concept")
    if tuple(expected_chunks) != value.chunks:
        raise ValueError("compiled chunk projection differs from its concepts")
    if tuple(expected_relationships) != value.relationships:
        raise ValueError("compiled relationship projection differs from its concepts")
    if compiled_generation_sha256(value) != value.generation_sha256:
        raise ValueError("compiled generation digest differs from its projections")


def _compiled_source_path(value: object) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("compiled concept path identity is invalid")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError("compiled concept path identity is invalid")
    return path


def concept_record(value: CompiledConcept) -> dict[str, object]:
    return {
        "conceptId": value.concept_id,
        "sourcePath": value.source_path,
        "contentSha256": value.content_sha256,
        "frontmatter": _canonical_mapping(value.frontmatter, "compiled frontmatter"),
        "body": value.body,
        "links": list(value.links),
        "brokenLinks": list(value.broken_links),
        "redirectHistory": list(value.redirect_history),
        "permissionPathPrefix": value.permission_path_prefix,
    }


def _canonical_mapping(value: object, field: str) -> dict[str, object]:
    materialized = _materialize_json(value, field)
    if not isinstance(materialized, dict):
        raise ValueError(f"{field} must be an object")
    return materialized


def _materialize_json(value: object, field: str) -> object:
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError(f"{field} has a non-text key")
        return {key: _materialize_json(item, field) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_materialize_json(item, field) for item in value]
    return json_value(value, field)


def chunk_record(value: CompiledChunk) -> dict[str, object]:
    return {
        "chunkId": value.chunk_id,
        "conceptId": value.concept_id,
        "permissionSha256": value.permission_sha256,
        "charStart": value.char_start,
        "charEnd": value.char_end,
        "text": value.text,
        "linkedConceptIds": list(value.linked_concept_ids),
    }


def relationship_record(value: CompiledRelationship) -> dict[str, object]:
    return {
        "relationshipId": value.relationship_id,
        "sourceConceptId": value.source_concept_id,
        "targetConceptId": value.target_concept_id,
        "type": value.relationship_type,
        "authority": value.authority,
        "sourceCharStart": value.source_char_start,
        "sourceCharEnd": value.source_char_end,
        "canonical": value.canonical,
    }


__all__ = [
    "CompiledConcept",
    "CompiledChunk",
    "CompiledKnowledgeGeneration",
    "CompiledPermission",
    "CompiledRelationship",
    "chunk_record",
    "compiled_generation_record",
    "compiled_generation_sha256",
    "compile_okf_bundle",
    "concept_record",
    "relationship_record",
    "validate_compiled_generation",
]
