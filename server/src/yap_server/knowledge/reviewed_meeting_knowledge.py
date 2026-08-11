from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Mapping

import yaml

from yap_server.auth.principal import PrincipalKey
from yap_server.jobs.contract_values import identifier, utc_timestamp, valid_sha256
from yap_server.jobs.result_contract import validate_result_revision
from yap_server.transcript_text import canonical_transcript


@dataclass(frozen=True, slots=True)
class KnowledgeSourceReview:
    reviewer: PrincipalKey
    job_id: str
    title: str
    reviewed_at_utc: str
    result_revision_sha256: str
    decision: str

    def __post_init__(self) -> None:
        identifier(self.job_id, 128, "knowledge meeting job ID")
        if (
            not isinstance(self.title, str)
            or not self.title.strip()
            or self.title != self.title.strip()
            or len(self.title) > 256
        ):
            raise ValueError("knowledge meeting title is invalid")
        utc_timestamp(self.reviewed_at_utc, "knowledge review time")
        if not valid_sha256(self.result_revision_sha256):
            raise ValueError("knowledge review result identity is invalid")
        if self.decision != "accepted":
            raise ValueError("knowledge source was not accepted")

    @property
    def review_sha256(self) -> str:
        return _sha256(
            {
                "schemaVersion": 2,
                "reviewer": {
                    "tenantId": self.reviewer.tenant_id,
                    "subjectId": self.reviewer.subject_id,
                },
                "reviewedAtUtc": self.reviewed_at_utc,
                "jobId": self.job_id,
                "title": self.title,
                "resultRevisionSha256": self.result_revision_sha256,
                "decision": self.decision,
            }
        )


def result_revision_sha256(result: Mapping[str, object]) -> str:
    return _sha256(dict(result))


def render_reviewed_meeting_concept(
    result: Mapping[str, object],
    *,
    projection: Mapping[str, object],
    tenant_id: str,
    owner: PrincipalKey,
    review: KnowledgeSourceReview,
) -> str:
    """Render one review-bound authoritative result as a canonical OKF concept."""

    identifier(tenant_id, 128, "knowledge meeting tenant ID")
    if owner.tenant_id != tenant_id or review.reviewer.tenant_id != tenant_id:
        raise ValueError("knowledge meeting authority crosses tenants")
    if review.reviewer != owner:
        raise PermissionError("meeting result review requires the owning principal")
    validate_result_revision(result, projection)
    result_identity = result_revision_sha256(result)
    if review.result_revision_sha256 != result_identity:
        raise ValueError("knowledge review differs from the result revision")
    transcript = canonical_transcript(
        result.get("transcript"),
        "knowledge meeting transcript",
    )
    frontmatter = {
        "type": "Meeting",
        "title": review.title,
        "resource": f"yap://tenant/{tenant_id}/meeting/{review.job_id}",
        "timestamp": review.reviewed_at_utc,
        "yap_schema": 1,
        "provenance": {
            "source": "server-authoritative-meeting-result",
            "source_revision": result_identity,
            "result_sha256": result_identity,
            "review_sha256": review.review_sha256,
            "job_id": review.job_id,
            "session_id": result["sessionId"],
            "owner": {
                "tenant_id": owner.tenant_id,
                "subject_id": owner.subject_id,
            },
            "reviewer": {
                "tenant_id": review.reviewer.tenant_id,
                "subject_id": review.reviewer.subject_id,
            },
        },
    }
    encoded = yaml.safe_dump(
        frontmatter,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    ).strip()
    return f"---\n{encoded}\n---\n# Transcript\n\n{transcript}\n"


def _sha256(value: object) -> str:
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ValueError("knowledge source is not canonical JSON") from error
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "KnowledgeSourceReview",
    "render_reviewed_meeting_concept",
    "result_revision_sha256",
]
