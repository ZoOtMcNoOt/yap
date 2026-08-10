from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Mapping

from .okf_profile import (
    concept_links,
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
from .permission_policy import (
    CompiledPermission,
    compile_permissions,
    effective_permission,
    permission_record,
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
    permission_path_prefix: str


@dataclass(frozen=True, slots=True)
class CompiledKnowledgeGeneration:
    tenant_id: str
    source_revision: str
    okf_version: str
    concepts: tuple[CompiledConcept, ...]
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
    resources: set[str] = set()
    canonical_records: list[dict[str, object]] = []
    for path in sorted(concept_paths, key=lambda item: item.as_posix()):
        frontmatter, markdown, source = documents[path]
        validate_concept_profile(frontmatter, tenant, path, resources)
        permission = effective_permission(path, permissions)
        links = concept_links(path, markdown)
        broken_links = tuple(
            link for link in links if Path(f"{link}.md") not in concept_paths
        )
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
            "permissionPathPrefix": permission.path_prefix,
        }
        canonical_records.append(record)
        concepts.append(
            CompiledConcept(
                concept_id=record["conceptId"],
                source_path=record["sourcePath"],
                content_sha256=record["contentSha256"],
                frontmatter=freeze(canonical_frontmatter),
                body=markdown,
                links=links,
                broken_links=broken_links,
                permission_path_prefix=permission.path_prefix,
            )
        )

    generation = {
        "schemaVersion": 1,
        "okfVersion": "0.1",
        "tenantId": tenant,
        "sourceRevision": revision,
        "concepts": canonical_records,
        "permissions": [permission_record(item) for item in permissions],
    }
    generation_sha256 = hashlib.sha256(
        json.dumps(
            generation,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return CompiledKnowledgeGeneration(
        tenant_id=tenant,
        source_revision=revision,
        okf_version="0.1",
        concepts=tuple(concepts),
        permissions=permissions,
        generation_sha256=generation_sha256,
    )


__all__ = [
    "CompiledConcept",
    "CompiledKnowledgeGeneration",
    "CompiledPermission",
    "compile_okf_bundle",
]
