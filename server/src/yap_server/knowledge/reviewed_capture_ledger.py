from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Mapping

from psycopg import Connection
from psycopg.types.json import Jsonb

from yap_server.auth.principal import PrincipalKey

from .reviewed_meeting_knowledge import (
    KnowledgeSourceReview,
    render_reviewed_meeting_concept,
    result_revision_sha256,
)


@dataclass(frozen=True, slots=True)
class ReviewedCaptureDescriptor:
    tenant_id: str
    owner_id: str
    job_id: str
    capture_sha256: str
    result_sha256: str
    review_sha256: str
    normalized_okf_sha256: str
    normalized_okf: str


def install_reviewed_capture_schema(connection: Connection[object]) -> None:
    with connection.transaction():
        connection.execute(
            """CREATE TABLE IF NOT EXISTS yap_knowledge_reviewed_captures (
                tenant_id text NOT NULL,
                capture_sha256 text NOT NULL,
                owner_id text NOT NULL,
                job_id text NOT NULL,
                result_sha256 text NOT NULL,
                review_sha256 text NOT NULL,
                normalized_okf_sha256 text NOT NULL,
                result_payload jsonb NOT NULL,
                normalized_okf text NOT NULL,
                created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
                PRIMARY KEY (tenant_id, capture_sha256),
                UNIQUE (tenant_id, job_id, result_sha256, review_sha256)
            )"""
        )


def append_reviewed_meeting_capture(
    connection: Connection[object],
    result: Mapping[str, object],
    *,
    projection: Mapping[str, object],
    job_id: str,
    owner: PrincipalKey,
    title: str,
    review: KnowledgeSourceReview,
) -> ReviewedCaptureDescriptor:
    """Append one owner-accepted result without overwriting transcript evidence."""

    normalized = render_reviewed_meeting_concept(
        result,
        projection=projection,
        job_id=job_id,
        tenant_id=owner.tenant_id,
        owner=owner,
        title=title,
        review=review,
    )
    result_sha256 = result_revision_sha256(result)
    normalized_sha256 = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    capture_sha256 = hashlib.sha256(
        (
            owner.tenant_id
            + "\0"
            + owner.subject_id
            + "\0"
            + job_id
            + "\0"
            + result_sha256
            + "\0"
            + review.review_sha256
            + "\0"
            + normalized_sha256
        ).encode("utf-8")
    ).hexdigest()
    descriptor = ReviewedCaptureDescriptor(
        tenant_id=owner.tenant_id,
        owner_id=owner.subject_id,
        job_id=job_id,
        capture_sha256=capture_sha256,
        result_sha256=result_sha256,
        review_sha256=review.review_sha256,
        normalized_okf_sha256=normalized_sha256,
        normalized_okf=normalized,
    )
    with connection.transaction():
        connection.execute(
            """INSERT INTO yap_knowledge_reviewed_captures (
                tenant_id, capture_sha256, owner_id, job_id, result_sha256,
                review_sha256, normalized_okf_sha256, result_payload,
                normalized_okf
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, capture_sha256) DO NOTHING""",
            (
                descriptor.tenant_id,
                descriptor.capture_sha256,
                descriptor.owner_id,
                descriptor.job_id,
                descriptor.result_sha256,
                descriptor.review_sha256,
                descriptor.normalized_okf_sha256,
                Jsonb(dict(result)),
                descriptor.normalized_okf,
            ),
        )
    return descriptor


def read_reviewed_capture(
    connection: Connection[object],
    *,
    principal: PrincipalKey,
    capture_sha256: str,
) -> ReviewedCaptureDescriptor:
    row = connection.execute(
        """SELECT tenant_id, owner_id, job_id, capture_sha256, result_sha256,
                  review_sha256, normalized_okf_sha256, normalized_okf
           FROM yap_knowledge_reviewed_captures
           WHERE tenant_id = %s AND owner_id = %s AND capture_sha256 = %s""",
        (principal.tenant_id, principal.subject_id, capture_sha256),
    ).fetchone()
    if row is None:
        raise LookupError("reviewed capture does not exist")
    return ReviewedCaptureDescriptor(*row)


__all__ = [
    "ReviewedCaptureDescriptor",
    "append_reviewed_meeting_capture",
    "install_reviewed_capture_schema",
    "read_reviewed_capture",
]
