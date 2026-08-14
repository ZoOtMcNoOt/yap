from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import datetime, timezone
from typing import Callable, Mapping, Protocol
import threading

from psycopg import Connection
from psycopg import Error as PostgresError
from psycopg.errors import UniqueViolation

from yap_server.auth import AuthenticatedPrincipal
from yap_server.jobs.errors import JobServiceError
from yap_server.jobs.ownership import PrincipalRecordingJobs
from yap_server.jobs.service import RecordingJobService
from yap_server.knowledge.knowledge_tool_contract import KnowledgeToolCancelled
from yap_server.knowledge.reviewed_capture_ledger import (
    ReviewedCaptureDescriptor,
    append_reviewed_meeting_capture,
    read_reviewed_capture_for_result,
)
from yap_server.knowledge.reviewed_meeting_knowledge import (
    KnowledgeSourceReview,
    result_revision_sha256,
)

from .archivist import ArchivistJobView, ArchivistRequest
from .archivist_ingestion_service import (
    ArchivistIngestionRequest,
    ArchivistIngestionServiceError,
)
from .archivist_service import ArchivistServiceError


ConnectionFactory = Callable[[], AbstractContextManager[Connection[object]]]


class ArchivistCore(Protocol):
    def ingest(
        self,
        request: ArchivistRequest,
        *,
        principal: AuthenticatedPrincipal,
        cancellation: threading.Event,
    ) -> ArchivistJobView: ...


class PostgresArchivistIngestionRunner:
    """Bind one explicit review to an immutable owned result, then stage it."""

    def __init__(
        self,
        *,
        jobs: RecordingJobService,
        connection_factory: ConnectionFactory,
        archivist: ArchivistCore,
        now: Callable[[], str] | None = None,
    ) -> None:
        self._jobs = jobs
        self._connection_factory = connection_factory
        self._archivist = archivist
        self._now = now or _utc_now

    def validate_source(
        self,
        request: ArchivistIngestionRequest,
        *,
        principal: AuthenticatedPrincipal,
    ) -> None:
        _load_exact_source(self._jobs, request, principal)

    def stage(
        self,
        request: ArchivistIngestionRequest,
        *,
        principal: AuthenticatedPrincipal,
        cancellation: threading.Event,
    ) -> ArchivistJobView:
        if cancellation.is_set():
            return _cancelled_before_capture(request)
        jobs, projection, _ = _load_exact_source(self._jobs, request, principal)
        try:
            capture = self._ensure_capture(
                jobs,
                projection,
                request,
                principal,
            )
        except (OSError, PostgresError) as error:
            raise ArchivistIngestionServiceError(
                503,
                "ARCHIVIST_STORAGE_UNAVAILABLE",
                "Knowledge staging storage is temporarily unavailable.",
                retryable=True,
                reason="storage-unavailable",
            ) from error
        if cancellation.is_set():
            return ArchivistJobView(
                request_id="archivist-product-pre-admission",
                status="cancelled",
                capture_sha256=capture.capture_sha256,
                reason="client-cancelled",
            )
        try:
            return self._archivist.ingest(
                ArchivistRequest(capture.capture_sha256),
                principal=principal,
                cancellation=cancellation,
            )
        except ArchivistServiceError as error:
            raise ArchivistIngestionServiceError(
                error.status,
                "ARCHIVIST_INGESTION_UNAVAILABLE",
                "Knowledge staging is temporarily unavailable.",
                retryable=error.retryable,
                reason="storage-unavailable",
            ) from error
        except KnowledgeToolCancelled:
            return ArchivistJobView(
                request_id="archivist-product-cancelled",
                status="cancelled",
                capture_sha256=capture.capture_sha256,
                reason="client-cancelled",
            )

    def _ensure_capture(
        self,
        jobs: PrincipalRecordingJobs,
        projection: Mapping[str, object],
        request: ArchivistIngestionRequest,
        principal: AuthenticatedPrincipal,
    ) -> ReviewedCaptureDescriptor:
        with self._connection_factory() as connection:
            existing = read_reviewed_capture_for_result(
                connection,
                principal=principal.key,
                job_id=request.job_id,
                result_sha256=request.expected_result_sha256,
            )
            if existing is not None:
                return existing
            title = projection.get("displayName")
            if not isinstance(title, str):
                raise ValueError("archivist source title is invalid")
            review = KnowledgeSourceReview(
                reviewer=principal.key,
                job_id=request.job_id,
                title=title,
                reviewed_at_utc=self._now(),
                result_revision_sha256=request.expected_result_sha256,
                decision="accepted",
            )
            try:
                return append_reviewed_meeting_capture(
                    connection,
                    jobs,
                    review=review,
                )
            except UniqueViolation:
                existing = read_reviewed_capture_for_result(
                    connection,
                    principal=principal.key,
                    job_id=request.job_id,
                    result_sha256=request.expected_result_sha256,
                )
                if existing is None:
                    raise
                return existing


def _load_exact_source(
    service: RecordingJobService,
    request: ArchivistIngestionRequest,
    principal: AuthenticatedPrincipal,
) -> tuple[PrincipalRecordingJobs, Mapping[str, object], Mapping[str, object]]:
    jobs = service.for_principal(principal)
    try:
        projection = jobs.get(request.job_id)
        result = jobs.get_result(request.job_id)
    except JobServiceError as error:
        if error.status == 404:
            raise ArchivistIngestionServiceError(
                404,
                "ARCHIVIST_SOURCE_NOT_FOUND",
                "The server transcript does not exist.",
                retryable=False,
                reason="invalid-reviewed-source",
            ) from error
        raise ArchivistIngestionServiceError(
            409,
            "ARCHIVIST_SOURCE_NOT_READY",
            "The immutable server transcript is not ready for knowledge staging.",
            retryable=error.retryable,
            reason="invalid-reviewed-source",
        ) from error
    try:
        result_sha256 = result_revision_sha256(result)
    except ValueError as error:
        raise ArchivistIngestionServiceError(
            409,
            "ARCHIVIST_SOURCE_INVALID",
            "The immutable server transcript cannot be staged.",
            retryable=False,
            reason="invalid-reviewed-source",
        ) from error
    if result_sha256 != request.expected_result_sha256:
        raise ArchivistIngestionServiceError(
            409,
            "ARCHIVIST_SOURCE_CHANGED",
            "The reviewed server transcript changed before staging.",
            retryable=False,
            reason="source-changed",
        )
    return jobs, projection, result


def _cancelled_before_capture(request: ArchivistIngestionRequest) -> ArchivistJobView:
    return ArchivistJobView(
        request_id="archivist-product-pre-cancelled",
        status="cancelled",
        capture_sha256=request.expected_result_sha256,
        reason="client-cancelled",
    )


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace(
            "+00:00",
            "Z",
        )
    )


__all__ = [
    "ArchivistCore",
    "PostgresArchivistIngestionRunner",
]
