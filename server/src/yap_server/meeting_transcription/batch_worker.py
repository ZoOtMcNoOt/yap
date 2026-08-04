from __future__ import annotations

import threading
from typing import Protocol

from yap_server.pools.batch_contract import BatchAsrJob

from .container_worker import MeetingTranscriptionJob
from .contract import validate_meeting_transcription_route
from .result_revisions import MeetingResultAuthority


class MeetingTranscriptionWorker(Protocol):
    def run(
        self,
        job: MeetingTranscriptionJob,
        cancellation: threading.Event,
    ) -> dict[str, object]: ...

    def close(self) -> None: ...


class MeetingTranscriptionBatchWorker:
    """Adapts Yap's owned batch seam to the pinned whole-meeting runtime."""

    def __init__(
        self,
        *,
        worker: MeetingTranscriptionWorker,
        authority: MeetingResultAuthority,
    ) -> None:
        self._worker = worker
        self._authority = authority

    def run(
        self,
        job: BatchAsrJob,
        cancellation: threading.Event,
    ) -> dict[str, object]:
        route = job.route
        validate_meeting_transcription_route(
            route,
            model_revision=self._authority.provenance.model.revision,
            has_utterance_plan=job.utterance_plan_path is not None,
        )
        if job.capture_manifest_sha256 is None or job.source_frame_count is None:
            raise ValueError("meeting transcription requires immutable source identity")
        return self._worker.run(
            MeetingTranscriptionJob(
                job_id=job.job_id,
                input_path=job.input_path,
                result_path=job.result_path,
                input_sha256=job.input_sha256,
                capture_manifest_sha256=job.capture_manifest_sha256,
                language=route.provider_language,
                frame_count=job.source_frame_count,
            ),
            cancellation,
        )

    def close(self) -> None:
        self._worker.close()
