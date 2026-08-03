from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Mapping

from yap_server.auth import AuthenticatedPrincipal, PrincipalKey

if TYPE_CHECKING:
    from yap_server.jobs.chunk_upload import ChunkUploadPlan
    from yap_server.jobs.service import RecordingJobService


DEVELOPMENT_JOB_OWNER = PrincipalKey(
    tenant_id="development-loopback",
    subject_id="local-server",
)


def idempotency_owner_key(
    owner: PrincipalKey,
    idempotency_key: str,
) -> tuple[str, str, str]:
    return owner.tenant_id, owner.subject_id, idempotency_key


@dataclass(frozen=True, slots=True)
class PrincipalRecordingJobs:
    """Binds every caller-visible job operation to one immutable principal."""

    service: RecordingJobService
    owner: PrincipalKey

    def create(
        self,
        request: Mapping[str, object],
        *,
        idempotency_key: str | None = None,
    ) -> dict[str, object]:
        return self.service.create(
            request,
            idempotency_key=idempotency_key,
            owner=self.owner,
        )

    def get(self, job_id: str) -> dict[str, object]:
        return self.service.get(job_id, owner=self.owner)

    def get_stages(self, job_id: str) -> dict[str, object]:
        return self.service.get_stages(job_id, owner=self.owner)

    def retry_stage(
        self,
        job_id: str,
        stage: str,
        request: Mapping[str, object],
    ) -> dict[str, object]:
        return self.service.retry_stage(
            job_id,
            stage,
            request,
            owner=self.owner,
        )

    def prepare_chunk_upload(
        self,
        job_id: str,
        **kwargs: object,
    ) -> ChunkUploadPlan:
        return self.service.prepare_chunk_upload(
            job_id,
            owner=self.owner,
            **kwargs,
        )

    def accept_chunk(
        self,
        plan: ChunkUploadPlan,
        body: bytes,
    ) -> dict[str, object]:
        return self.service.accept_chunk(
            plan,
            body,
            owner=self.owner,
        )

    def commit(
        self,
        job_id: str,
        request: Mapping[str, object],
    ) -> dict[str, object]:
        return self.service.commit(job_id, request, owner=self.owner)

    def cancel(self, job_id: str) -> dict[str, object]:
        return self.service.cancel(job_id, owner=self.owner)

    def get_result(self, job_id: str) -> dict[str, object]:
        return self.service.get_result(job_id, owner=self.owner)

    def get_speaker_result(self, job_id: str) -> dict[str, object]:
        return self.service.get_speaker_result(job_id, owner=self.owner)


def principal_key(
    principal: AuthenticatedPrincipal | PrincipalKey,
) -> PrincipalKey:
    return principal.key if isinstance(principal, AuthenticatedPrincipal) else principal
