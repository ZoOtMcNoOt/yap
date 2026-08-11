from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import PurePosixPath
from typing import Mapping

from psycopg import Connection

from yap_server.auth.principal import AuthenticatedPrincipal, PrincipalKey
from yap_server.jobs.contract_values import identifier, valid_sha256

from .okf_compiler import (
    CompiledKnowledgeGeneration,
    compiled_generation_record,
    concept_record,
    validate_compiled_generation,
)
from .okf_profile import json_value
from .okf_source import parse_okf_document
from .permission_policy import effective_permission
from .reviewed_capture_ledger import read_reviewed_capture


_CURATED_KNOWLEDGE_REVIEWER_ROLE = "knowledge.curator"


@dataclass(frozen=True, slots=True)
class KnowledgeSourceAdmission:
    tenant_id: str
    admission_sha256: str
    source_kind: str
    source_identity_sha256: str
    source_path: str
    source_revision: str
    generation_sha256: str
    reviewer_id: str
    review_authority_sha256: str


def install_knowledge_source_admission_schema(
    connection: Connection[object],
) -> None:
    with connection.transaction():
        connection.execute(
            """CREATE TABLE IF NOT EXISTS yap_knowledge_source_admissions (
                tenant_id text NOT NULL,
                admission_sha256 text NOT NULL,
                source_kind text NOT NULL
                    CHECK (source_kind IN ('reviewed-capture', 'curated-repository')),
                source_identity_sha256 text NOT NULL,
                source_path text NOT NULL,
                source_revision text NOT NULL,
                generation_sha256 text NOT NULL,
                reviewer_id text NOT NULL,
                review_authority_sha256 text NOT NULL,
                created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
                PRIMARY KEY (tenant_id, admission_sha256),
                UNIQUE (tenant_id, generation_sha256)
            )"""
        )


def admit_reviewed_capture_generation(
    connection: Connection[object],
    *,
    principal: AuthenticatedPrincipal,
    capture_sha256: str,
    generation: CompiledKnowledgeGeneration,
) -> KnowledgeSourceAdmission:
    capture = read_reviewed_capture(
        connection,
        principal=principal.key,
        capture_sha256=capture_sha256,
    )
    validate_compiled_generation(generation)
    if (
        generation.tenant_id != principal.tenant_id
        or generation.source_revision != capture.capture_sha256
        or len(generation.concepts) != 1
    ):
        raise ValueError("reviewed capture generation identity differs")
    concept = generation.concepts[0]
    expected_path = f"meetings/{capture.job_id}.md"
    expected_frontmatter, expected_body = parse_okf_document(
        PurePosixPath(expected_path), capture.normalized_okf
    )
    canonical_concept = concept_record(concept)
    provenance = concept.frontmatter.get("provenance")
    expected_owner = {
        "tenant_id": capture.tenant_id,
        "subject_id": capture.owner_id,
    }
    if (
        concept.concept_id != expected_path.removesuffix(".md")
        or concept.source_path != expected_path
        or concept.content_sha256 != capture.normalized_okf_sha256
        or canonical_concept["frontmatter"]
        != json_value(expected_frontmatter, "reviewed capture frontmatter")
        or concept.body != expected_body
        or not isinstance(provenance, Mapping)
        or provenance.get("result_sha256") != capture.result_sha256
        or provenance.get("review_sha256") != capture.review_sha256
        or provenance.get("job_id") != capture.job_id
        or provenance.get("owner") != expected_owner
    ):
        raise ValueError("reviewed capture content differs from the generation")
    permission = effective_permission(PurePosixPath(expected_path), generation.permissions)
    if (
        len(generation.permissions) != 1
        or permission.path_prefix != "meetings/"
        or permission.audience != (principal.key,)
        or permission.denials
        or permission.purposes != ("knowledge.read",)
        or permission.classification != "confidential"
    ):
        raise PermissionError("reviewed capture generation is not owner-only")
    return _record_admission(
        connection,
        principal=principal.key,
        source_kind="reviewed-capture",
        source_identity_sha256=capture.capture_sha256,
        source_path=f"meetings/{capture.job_id}.md",
        source_revision=capture.capture_sha256,
        review_authority_sha256=capture.review_sha256,
        generation=generation,
    )


def admit_curated_knowledge_generation(
    connection: Connection[object],
    *,
    principal: AuthenticatedPrincipal,
    repository_revision: str,
    source_path: str,
    generation: CompiledKnowledgeGeneration,
) -> KnowledgeSourceAdmission:
    """Authenticate one curator and durably bind one exact compiled source."""

    if _CURATED_KNOWLEDGE_REVIEWER_ROLE not in principal.roles:
        raise PermissionError("principal cannot review curated knowledge")
    revision = identifier(repository_revision, 512, "curated source revision")
    reviewed_path = _relative_source_path(source_path)
    validate_compiled_generation(generation)
    if (
        generation.tenant_id != principal.tenant_id
        or generation.source_revision != revision
    ):
        raise ValueError("curated source review differs from the generation")
    source_manifest_sha256 = _sha256(
        {
            "schemaVersion": 1,
            "repositoryRevision": revision,
            "sourcePath": reviewed_path,
            "compiledGeneration": compiled_generation_record(generation),
        }
    )
    review_authority_sha256 = _sha256(
        _curated_review_identity(
            reviewer=principal.key,
            repository_revision=revision,
            source_path=reviewed_path,
            source_manifest_sha256=source_manifest_sha256,
            generation_sha256=generation.generation_sha256,
        )
    )
    return _record_admission(
        connection,
        principal=principal.key,
        source_kind="curated-repository",
        source_identity_sha256=source_manifest_sha256,
        source_path=reviewed_path,
        source_revision=revision,
        review_authority_sha256=review_authority_sha256,
        generation=generation,
    )


def _curated_review_identity(
    *,
    reviewer: PrincipalKey,
    repository_revision: str,
    source_path: str,
    source_manifest_sha256: str,
    generation_sha256: str,
) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "reviewer": {
            "tenantId": reviewer.tenant_id,
            "subjectId": reviewer.subject_id,
        },
        "repositoryRevision": repository_revision,
        "sourcePath": source_path,
        "sourceManifestSha256": source_manifest_sha256,
        "generationSha256": generation_sha256,
    }


def require_knowledge_source_admission(
    connection: Connection[object],
    *,
    tenant_id: str,
    admission_sha256: str,
    generation_sha256: str,
    source_revision: str,
) -> KnowledgeSourceAdmission:
    row = connection.execute(
        """SELECT tenant_id, admission_sha256, source_kind,
                  source_identity_sha256, source_path, source_revision,
                  generation_sha256, reviewer_id, review_authority_sha256
           FROM yap_knowledge_source_admissions
           WHERE tenant_id = %s AND admission_sha256 = %s""",
        (tenant_id, admission_sha256),
    ).fetchone()
    if row is None:
        raise PermissionError("knowledge generation source was not reviewed")
    admission = _validated_admission_row(row)
    if (
        admission.generation_sha256 != generation_sha256
        or admission.source_revision != source_revision
    ):
        raise ValueError("knowledge source admission differs from the generation")
    return admission


def _record_admission(
    connection: Connection[object],
    *,
    principal: PrincipalKey,
    source_kind: str,
    source_identity_sha256: str,
    source_path: str,
    source_revision: str,
    review_authority_sha256: str,
    generation: CompiledKnowledgeGeneration,
) -> KnowledgeSourceAdmission:
    validate_compiled_generation(generation)
    if not valid_sha256(review_authority_sha256):
        raise ValueError("knowledge source review authority is invalid")
    identity = _admission_identity(
        principal=principal,
        source_kind=source_kind,
        source_identity_sha256=source_identity_sha256,
        source_path=source_path,
        source_revision=source_revision,
        generation_sha256=generation.generation_sha256,
        review_authority_sha256=review_authority_sha256,
    )
    admission = KnowledgeSourceAdmission(
        tenant_id=principal.tenant_id,
        admission_sha256=_sha256(identity),
        source_kind=source_kind,
        source_identity_sha256=source_identity_sha256,
        source_path=source_path,
        source_revision=source_revision,
        generation_sha256=generation.generation_sha256,
        reviewer_id=principal.subject_id,
        review_authority_sha256=review_authority_sha256,
    )
    _insert_admission(connection, admission)
    return admission


def _admission_identity(
    *,
    principal: PrincipalKey,
    source_kind: str,
    source_identity_sha256: str,
    source_path: str,
    source_revision: str,
    generation_sha256: str,
    review_authority_sha256: str,
) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "tenantId": principal.tenant_id,
        "reviewerId": principal.subject_id,
        "sourceKind": source_kind,
        "sourceIdentitySha256": source_identity_sha256,
        "sourcePath": source_path,
        "sourceRevision": source_revision,
        "generationSha256": generation_sha256,
        "reviewAuthoritySha256": review_authority_sha256,
    }


def _validated_admission_row(row: tuple[object, ...]) -> KnowledgeSourceAdmission:
    admission = KnowledgeSourceAdmission(*row)
    expected = _sha256(
        _admission_identity(
            principal=PrincipalKey(admission.tenant_id, admission.reviewer_id),
            source_kind=admission.source_kind,
            source_identity_sha256=admission.source_identity_sha256,
            source_path=admission.source_path,
            source_revision=admission.source_revision,
            generation_sha256=admission.generation_sha256,
            review_authority_sha256=admission.review_authority_sha256,
        )
    )
    if admission.admission_sha256 != expected:
        raise ValueError("knowledge source admission differs from its identity")
    return admission


def _insert_admission(
    connection: Connection[object], admission: KnowledgeSourceAdmission
) -> None:
    with connection.transaction():
        row = connection.execute(
            """INSERT INTO yap_knowledge_source_admissions (
                   tenant_id, admission_sha256, source_kind,
                   source_identity_sha256, source_path, source_revision,
                   generation_sha256, reviewer_id, review_authority_sha256
               ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (tenant_id, admission_sha256) DO NOTHING
               RETURNING tenant_id, admission_sha256, source_kind,
                         source_identity_sha256, source_path, source_revision,
                         generation_sha256, reviewer_id, review_authority_sha256""",
            (
                admission.tenant_id,
                admission.admission_sha256,
                admission.source_kind,
                admission.source_identity_sha256,
                admission.source_path,
                admission.source_revision,
                admission.generation_sha256,
                admission.reviewer_id,
                admission.review_authority_sha256,
            ),
        ).fetchone()
        if row is None:
            row = connection.execute(
                """SELECT tenant_id, admission_sha256, source_kind,
                          source_identity_sha256, source_path, source_revision,
                          generation_sha256, reviewer_id, review_authority_sha256
                   FROM yap_knowledge_source_admissions
                   WHERE tenant_id = %s AND admission_sha256 = %s""",
                (admission.tenant_id, admission.admission_sha256),
            ).fetchone()
        if row is None or _validated_admission_row(row) != admission:
            raise ValueError("knowledge source admission conflicts with stored truth")




def _relative_source_path(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 512
        or "\\" in value
    ):
        raise ValueError("curated source path is invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("curated source path is invalid")
    normalized = path.as_posix()
    if normalized != value:
        raise ValueError("curated source path is invalid")
    return normalized


def _sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


__all__ = [
    "KnowledgeSourceAdmission",
    "admit_curated_knowledge_generation",
    "admit_reviewed_capture_generation",
    "install_knowledge_source_admission_schema",
    "require_knowledge_source_admission",
]
