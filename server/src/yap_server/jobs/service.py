from __future__ import annotations

from collections import deque
from concurrent.futures import Future
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import threading
from typing import Callable, Mapping, Protocol, Sequence
from uuid import uuid4

from yap_server.pools.batch_contract import (
    AsrRouteDecision,
    BatchReservation,
    DurableAsrRouting,
    PoolBackpressure,
    validate_asr_catalog_revision,
)
from yap_server.pools.utterance_plan import (
    UtterancePlanSource,
    canonical_vad_evidence_sha256,
)
from .artifacts import PcmChunkSource
from .chunk_contract import (
    chunk_path as _chunk_path,
    receipt_key as _receipt_key,
    validated_single_track_chunks as _validated_single_track_chunks,
)
from .chunk_upload import ChunkUploadCoordinator, ChunkUploadPlan
from .completion import JobCompletionCoordinator
from .contract_values import (
    MAX_CLIENT_CLOCK_SKEW as _MAX_CLIENT_CLOCK_SKEW,
    TERMINAL_STATUSES as _TERMINAL_STATUSES,
    identifier as _identifier,
    mapping as _mapping,
    text as _text,
    utc_timestamp as _utc_timestamp,
)
from .errors import JobServiceError
from .intake_contract import (
    selected_batch_mode as _selected_batch_mode,
    selected_language as _selected_language,
    validate_create_request as _validate_create_request,
)
from .job_store import DurableJobState, RecordingJobStore
from .processing_input import BatchInputPreparation
from .stage_attempts import (
    StageAttemptCapacityError,
    finish_stage,
    latest_stage_projection,
    start_stage,
)


_MAX_STORED_JOBS = 512
_CANCELLATION_ACK_TIMEOUT_SECONDS = 2.0


class BatchJobProcessor(Protocol):
    @property
    def asr_catalog_revision(self) -> str: ...

    def resolve_route(self, catalog_language_bcp47: str) -> AsrRouteDecision: ...

    def reserve(
        self,
        job_id: str,
        *,
        pcm_byte_length: int,
    ) -> BatchReservation: ...

    def cancel(self, job_id: str) -> bool: ...


class RecordingJobService:
    """Owns immutable job intake and the server-side batch lifecycle."""

    def __init__(
        self,
        storage_root: Path,
        *,
        processor: BatchJobProcessor,
        supported_languages: Sequence[str],
        now: Callable[[], str],
        cancellation_timeout_seconds: float = _CANCELLATION_ACK_TIMEOUT_SECONDS,
        startup_worker_cleanup_verified: bool = False,
    ) -> None:
        if cancellation_timeout_seconds <= 0:
            raise ValueError("cancellation timeout must be positive")
        if not isinstance(startup_worker_cleanup_verified, bool):
            raise ValueError("startup cleanup verification must be boolean")
        self._processor = processor
        self._asr_catalog_revision = processor.asr_catalog_revision
        validate_asr_catalog_revision(self._asr_catalog_revision)
        self._supported_languages = frozenset(supported_languages)
        self._now = now
        self._cancellation_timeout_seconds = cancellation_timeout_seconds
        self._store = RecordingJobStore(
            storage_root,
            supported_languages=supported_languages,
            now=now,
            startup_worker_cleanup_verified=startup_worker_cleanup_verified,
            route_resolver=processor.resolve_route,
            asr_catalog_revision=self._asr_catalog_revision,
        )
        self._storage_root = self._store.root
        self._lock = threading.RLock()
        self._state: DurableJobState = self._store.load()
        self._futures: dict[str, object] = {}
        self._completion_events: dict[str, threading.Event] = {}
        self._pending_processing: deque[str] = deque()
        self._pending_pump_active = False
        self._pending_pump_requested = False
        self._stopping = False
        self._uploads = ChunkUploadCoordinator(
            storage_root=self._storage_root,
            state=self._state,
            store=self._store,
            lock=self._lock,
            now=self._now,
        )
        self._completion = JobCompletionCoordinator(
            storage_root=self._storage_root,
            state=self._state,
            store=self._store,
            futures=self._futures,
            completion_events=self._completion_events,
            lock=self._lock,
            now=self._now,
        )
        with self._lock:
            self._prune_expired_jobs_locked(
                _utc_timestamp(self._now(), "server clock")
            )
            self._recover_interrupted_stages_locked()
            self._pending_processing.extend(
                job_id
                for job_id, projection in self._state.jobs.items()
                if projection.get("status") == "server_processing"
            )
        self._pump_pending_processing()

    def create(
        self,
        request: Mapping[str, object],
        *,
        idempotency_key: str | None = None,
    ) -> dict[str, object]:
        try:
            _validate_create_request(
                request,
                self._supported_languages,
                require_supported_language=False,
            )
            if idempotency_key is not None:
                _identifier(idempotency_key, 128, "create idempotency key")
        except ValueError as error:
            raise JobServiceError(
                400,
                "INVALID_JOB",
                "Recording job declaration is invalid.",
            ) from error
        metadata = _mapping(request.get("metadata"), "metadata")
        capture_manifest = _mapping(
            request.get("captureManifest"),
            "captureManifest",
        )
        started_at = _utc_timestamp(metadata.get("startedAtUtc"), "startedAtUtc")
        retention_at = _utc_timestamp(
            metadata.get("retentionExpiresAtUtc"),
            "retentionExpiresAtUtc",
        )
        session_id = _text(metadata.get("sessionId"), "metadata.sessionId")
        if capture_manifest.get("sessionId") != session_id:
            raise ValueError("capture manifest session does not match metadata")
        display_name = _text(request.get("displayName"), "displayName")
        if request.get("route") != "server_batch":
            raise ValueError("route must be server_batch")
        with self._lock:
            self._require_runtime_admission_open_locked()
            created_at = self._now()
            server_now = _utc_timestamp(created_at, "server clock")
            if (
                retention_at <= server_now
                or started_at > server_now + _MAX_CLIENT_CLOCK_SKEW
            ):
                raise JobServiceError(
                    400,
                    "INVALID_JOB",
                    "Recording job retention or capture time is invalid.",
                )
            self._prune_expired_jobs_locked(
                server_now
            )
            if idempotency_key is not None:
                existing_job_id = self._state.created_by_key.get(idempotency_key)
                if existing_job_id is not None:
                    if self._state.requests[existing_job_id] != dict(request):
                        raise JobServiceError(
                            409,
                            "CREATE_IDEMPOTENCY_CONFLICT",
                            "The create idempotency key is already bound to different content.",
                        )
                    return deepcopy(self._state.jobs[existing_job_id])
            try:
                _validate_create_request(
                    request,
                    self._supported_languages,
                    expected_catalog_revision=self._asr_catalog_revision,
                )
            except ValueError as error:
                raise JobServiceError(
                    400,
                    "INVALID_JOB",
                    "Recording job declaration is invalid.",
                ) from error
            if len(self._state.jobs) >= _MAX_STORED_JOBS:
                raise JobServiceError(
                    429,
                    "SERVER_STORAGE_LIMIT",
                    "Private recording storage reached its configured job limit.",
                )
            selected_language = _selected_language(
                request,
                self._supported_languages,
            )
            route = self._processor.resolve_route(selected_language)
            if route.execution_mode != _selected_batch_mode(request):
                raise RuntimeError(
                    "resolved ASR route mode differs from the admitted language decision"
                )
            durable_routing = DurableAsrRouting(
                route=route,
                asr_catalog_revision=self._asr_catalog_revision,
            )
            job_id = f"job-{uuid4().hex}"
            projection: dict[str, object] = {
                "jobId": job_id,
                "sessionId": session_id,
                "displayName": display_name,
                "sessionMode": _text(metadata.get("mode"), "metadata.mode"),
                "sessionOrigin": _text(metadata.get("origin"), "metadata.origin"),
                "status": "accepted",
                "route": "server_batch",
                "captureManifest": deepcopy(capture_manifest),
                "createdAtUtc": created_at,
                "updatedAtUtc": created_at,
            }
            job_root = self._storage_root / "jobs" / job_id
            (job_root / "chunks").mkdir(parents=True, exist_ok=False)
            self._state.jobs[job_id] = projection
            self._state.requests[job_id] = deepcopy(dict(request))
            self._state.asr_routing[job_id] = durable_routing
            self._state.stage_history_complete[job_id] = True
            self._state.stage_attempts[job_id] = []
            self._state.projection_revisions[job_id] = 0
            self._state.create_keys[job_id] = idempotency_key
            if idempotency_key is not None:
                self._state.created_by_key[idempotency_key] = job_id
            try:
                self._persist_job_locked(job_id)
            except Exception:
                self._delete_job_locked(job_id)
                raise
        return deepcopy(projection)

    def get(self, job_id: str) -> dict[str, object]:
        with self._lock:
            return deepcopy(self._state.jobs[job_id])

    def get_stages(self, job_id: str) -> dict[str, object]:
        with self._lock:
            if job_id not in self._state.jobs:
                raise JobServiceError(
                    404,
                    "JOB_NOT_FOUND",
                    "The recording job does not exist.",
                )
            return {
                "schemaVersion": 1,
                "jobId": job_id,
                "projectionRevision": self._state.projection_revisions[job_id],
                "historyComplete": self._state.stage_history_complete[job_id],
                "stages": latest_stage_projection(
                    self._state.stage_attempts[job_id]
                ),
            }

    def retry_stage(
        self,
        job_id: str,
        stage: str,
        request: Mapping[str, object],
    ) -> dict[str, object]:
        if set(request) != {
            "stage",
            "attempt",
            "projectionRevision",
            "captureManifestSha256",
        } or request.get("stage") != stage:
            raise ValueError("stage retry fields differ from the contract")
        expected_attempt = request.get("attempt")
        expected_revision = request.get("projectionRevision")
        expected_capture = request.get("captureManifestSha256")
        if (
            stage != "asr"
            or isinstance(expected_attempt, bool)
            or not isinstance(expected_attempt, int)
            or expected_attempt < 1
            or isinstance(expected_revision, bool)
            or not isinstance(expected_revision, int)
            or expected_revision < 1
            or not isinstance(expected_capture, str)
        ):
            raise ValueError("stage retry identity is invalid")

        callback: tuple[
            str,
            str,
            Future[dict[str, object]],
            threading.Event,
        ] | None = None
        with self._lock:
            self._require_runtime_admission_open_locked()
            if job_id not in self._state.jobs:
                raise JobServiceError(
                    404,
                    "JOB_NOT_FOUND",
                    "The recording job does not exist.",
                )
            job = self._state.jobs[job_id]
            if job_id in self._state.cancelled:
                raise JobServiceError(
                    409,
                    "STAGE_NOT_RETRYABLE",
                    "Cancelled server work cannot be retried.",
                )
            if job_id in self._state.cleanup_unverified:
                raise JobServiceError(
                    503,
                    "STAGE_CLEANUP_UNVERIFIED",
                    "Worker cleanup must be verified before retry.",
                    retryable=True,
                )
            if self._state.projection_revisions[job_id] != expected_revision:
                raise JobServiceError(
                    409,
                    "STAGE_PROJECTION_STALE",
                    "The server stage projection changed before retry.",
                    retryable=True,
                )
            capture_manifest = _mapping(job.get("captureManifest"), "captureManifest")
            if capture_manifest.get("sha256") != expected_capture:
                raise JobServiceError(
                    409,
                    "STAGE_CAPTURE_CONFLICT",
                    "The retry capture identity differs from the admitted job.",
                )
            latest = next(
                (
                    attempt
                    for attempt in reversed(self._state.stage_attempts[job_id])
                    if attempt["stage"] == stage
                ),
                None,
            )
            job_error = job.get("error")
            if (
                job.get("status") != "failed"
                or not isinstance(job_error, Mapping)
                or job_error.get("retryable") is not True
                or latest is None
                or latest.get("attempt") != expected_attempt
                or latest.get("state") != "failed"
                or latest.get("retryable") is not True
            ):
                raise JobServiceError(
                    409,
                    "STAGE_NOT_RETRYABLE",
                    "The requested server stage cannot be retried.",
                )
            started_at = self._now()
            try:
                self._preflight_asr_stage_locked(job_id, started_at)
            except StageAttemptCapacityError as capacity_error:
                self._mark_stage_attempt_limit_locked(job_id)
                raise JobServiceError(
                    409,
                    "STAGE_ATTEMPT_LIMIT",
                    "The bounded ASR stage retry history is exhausted.",
                ) from capacity_error
            preparation = self._build_input_preparation_locked(
                job_id,
                self._state.requests[job_id],
            )
            try:
                reservation = self._processor.reserve(
                    job_id,
                    pcm_byte_length=preparation.pcm_byte_length,
                )
            except PoolBackpressure as pool_error:
                raise JobServiceError(
                    429,
                    "SERVER_BUSY",
                    "Server capacity is temporarily unavailable.",
                    retryable=True,
                ) from pool_error

            previous_status = str(job["status"])
            previous_updated_at = str(job["updatedAtUtc"])
            previous_error = deepcopy(job_error)
            previous_attempts = deepcopy(self._state.stage_attempts[job_id])
            job["status"] = "server_processing"
            job["updatedAtUtc"] = started_at
            job.pop("error", None)
            self._start_asr_stage_locked(job_id, started_at)
            try:
                self._persist_job_locked(job_id)
            except BaseException:
                job["status"] = previous_status
                job["updatedAtUtc"] = previous_updated_at
                job["error"] = previous_error
                self._state.stage_attempts[job_id] = previous_attempts
                reservation.abort()
                raise
            try:
                future = reservation.start(preparation.prepare)
            except BaseException:
                reservation.abort()
                self._mark_processing_activation_failed_locked(job_id)
                raise
            completion_event = threading.Event()
            self._futures[job_id] = future
            self._completion_events[job_id] = completion_event
            callback = (
                job_id,
                preparation.language_bcp47,
                future,
                completion_event,
            )
            projection = {
                "schemaVersion": 1,
                "jobId": job_id,
                "projectionRevision": self._state.projection_revisions[job_id],
                "historyComplete": self._state.stage_history_complete[job_id],
                "stages": latest_stage_projection(
                    self._state.stage_attempts[job_id]
                ),
            }
        assert callback is not None
        self._attach_processing_callback(*callback)
        return projection

    def prepare_chunk_upload(
        self,
        job_id: str,
        *,
        track_id: str,
        sequence_start: int,
        sequence_end: int,
        idempotency_key: str,
        content_sha256: str,
        audio_codec: str,
        sample_rate_hz: int,
        channels: int,
        content_length: int,
    ) -> ChunkUploadPlan:
        with self._lock:
            self._require_runtime_admission_open_locked()
            return self._uploads.prepare(
                job_id,
                track_id=track_id,
                sequence_start=sequence_start,
                sequence_end=sequence_end,
                idempotency_key=idempotency_key,
                content_sha256=content_sha256,
                audio_codec=audio_codec,
                sample_rate_hz=sample_rate_hz,
                channels=channels,
                content_length=content_length,
            )


    def accept_chunk(
        self,
        plan: ChunkUploadPlan,
        body: bytes,
    ) -> dict[str, object]:
        with self._lock:
            self._require_runtime_admission_open_locked()
            return self._uploads.accept(plan, body)


    def commit(
        self,
        job_id: str,
        request: Mapping[str, object],
    ) -> dict[str, object]:
        callback: tuple[
            str,
            str,
            Future[dict[str, object]],
            threading.Event,
        ] | None = None
        with self._lock:
            self._require_runtime_admission_open_locked()
            creation = self._state.requests[job_id]
            job = self._state.jobs[job_id]
            self._validate_commit_request(creation, request)
            if job["status"] in {"server_processing", "complete", "partial"}:
                return deepcopy(job)
            if job["status"] not in {"accepted", "uploading"}:
                raise JobServiceError(
                    409,
                    "JOB_NOT_COMMITTABLE",
                    "The recording job cannot be committed from its current state.",
                )
            if self._has_pending_restart_work_locked():
                raise JobServiceError(
                    429,
                    "SERVER_BUSY",
                    "Server capacity is temporarily unavailable.",
                    retryable=True,
                )
            preparation = self._build_input_preparation_locked(job_id, creation)
            started_at = self._now()
            try:
                self._preflight_asr_stage_locked(job_id, started_at)
            except StageAttemptCapacityError as capacity_error:
                self._mark_stage_attempt_limit_locked(job_id)
                raise JobServiceError(
                    409,
                    "STAGE_ATTEMPT_LIMIT",
                    "The bounded ASR stage history is exhausted.",
                ) from capacity_error
            try:
                reservation = self._processor.reserve(
                    job_id,
                    pcm_byte_length=preparation.pcm_byte_length,
                )
            except PoolBackpressure as error:
                raise JobServiceError(
                    429,
                    "SERVER_BUSY",
                    "Server capacity is temporarily unavailable.",
                    retryable=True,
                ) from error

            previous_status = str(job["status"])
            previous_updated_at = str(job["updatedAtUtc"])
            previous_attempts = deepcopy(self._state.stage_attempts[job_id])
            job["status"] = "server_processing"
            job["updatedAtUtc"] = started_at
            self._start_asr_stage_locked(job_id, started_at)
            try:
                self._persist_job_locked(job_id)
            except BaseException:
                job["status"] = previous_status
                job["updatedAtUtc"] = previous_updated_at
                self._state.stage_attempts[job_id] = previous_attempts
                reservation.abort()
                raise
            try:
                future = reservation.start(preparation.prepare)
            except BaseException:
                reservation.abort()
                failed_at = self._now()
                job["status"] = "failed"
                job["updatedAtUtc"] = failed_at
                job["error"] = {
                    "code": "SERVER_STORAGE_ERROR",
                    "message": "Private processing could not start safely.",
                    "retryable": True,
                    "requestId": f"job-{job_id}",
                }
                self._finish_running_stage_locked(
                    job_id,
                    "asr",
                    state="failed",
                    retryable=True,
                    reason="SERVER_STORAGE_ERROR",
                    completed_at_utc=failed_at,
                )
                self._persist_job_locked(job_id)
                raise
            completion_event = threading.Event()
            self._futures[job_id] = future
            self._completion_events[job_id] = completion_event
            projection = deepcopy(job)
            callback = (
                job_id,
                preparation.language_bcp47,
                future,
                completion_event,
            )
        assert callback is not None
        self._attach_processing_callback(*callback)
        return projection

    def begin_runtime_shutdown(self) -> None:
        """Keep durable processing intent resumable while verified workers stop."""

        with self._lock:
            self._stopping = True

    def _require_runtime_admission_open_locked(self) -> None:
        if self._stopping:
            raise JobServiceError(
                503,
                "SERVER_SHUTTING_DOWN",
                "The server runtime is shutting down.",
                retryable=True,
            )

    def _validate_commit_request(
        self,
        creation: Mapping[str, object],
        request: Mapping[str, object],
    ) -> None:
        if set(request) != {"captureManifest", "chunkCount"}:
            raise ValueError("commit fields differ from the contract")
        if request.get("captureManifest") != creation.get("captureManifest"):
            raise ValueError("commit manifest does not match job creation")
        chunks = creation.get("chunks")
        if not isinstance(chunks, list) or request.get("chunkCount") != len(chunks):
            raise ValueError("commit chunk count does not match job creation")

    def _build_input_preparation_locked(
        self,
        job_id: str,
        creation: Mapping[str, object],
    ) -> BatchInputPreparation:
        chunks = creation.get("chunks")
        if not isinstance(chunks, list):
            raise ValueError("job creation chunks are invalid")
        ordered_chunks = _validated_single_track_chunks(chunks)
        job_root = self._storage_root / "jobs" / job_id
        chunk_sources: list[PcmChunkSource] = []
        for chunk in ordered_chunks:
            replay = _mapping(chunk.get("replayKey"), "replayKey")
            if _receipt_key(job_id, replay) not in self._state.receipts:
                raise JobServiceError(
                    409,
                    "JOB_NOT_COMMITTABLE",
                    "The recording job cannot be committed before every chunk is uploaded.",
                )
            content = _mapping(chunk.get("contentIdentity"), "contentIdentity")
            chunk_sources.append(
                PcmChunkSource(
                    path=_chunk_path(job_root, replay),
                    byte_length=int(content["byteLength"]),
                    sha256=str(content["sha256"]),
                )
            )
        language_bcp47 = _selected_language(
            creation,
            self._supported_languages,
            require_supported_language=False,
        )
        expected_output_pcm_sha256: str | None = None
        preprocessing = creation.get("preprocessingEvidence")
        if preprocessing is not None:
            normalization = _mapping(
                _mapping(preprocessing, "preprocessingEvidence").get("normalization"),
                "preprocessingEvidence.normalization",
            )
            expected_output_pcm_sha256 = str(normalization["outputPcmSha256"])
        durable_routing = self._state.asr_routing[job_id]
        if durable_routing is None:
            raise RuntimeError("active job is missing frozen ASR routing")
        utterance_plan_source = _utterance_plan_source_for_route(
            creation,
            durable_routing.route,
        )
        return BatchInputPreparation(
            job_id=job_id,
            job_root=job_root,
            chunk_sources=tuple(chunk_sources),
            language=language_bcp47,
            language_bcp47=language_bcp47,
            route=durable_routing.route,
            expected_output_pcm_sha256=expected_output_pcm_sha256,
            utterance_plan_source=utterance_plan_source,
        )

    def _start_asr_stage_locked(
        self,
        job_id: str,
        started_at_utc: str,
        *,
        attempts: list[dict[str, object]] | None = None,
    ) -> int:
        creation = self._state.requests[job_id]
        routing = self._state.asr_routing[job_id]
        if routing is None:
            raise RuntimeError("active job is missing frozen ASR routing")
        preprocessing = creation.get("preprocessingEvidence")
        if preprocessing is None:
            capture_manifest = _mapping(
                creation.get("captureManifest"),
                "captureManifest",
            )
            input_fingerprint = str(capture_manifest["sha256"])
        else:
            normalization = _mapping(
                _mapping(preprocessing, "preprocessingEvidence").get("normalization"),
                "preprocessingEvidence.normalization",
            )
            input_fingerprint = str(normalization["outputPcmSha256"])
        utterance_plan_source = _utterance_plan_source_for_route(
            creation,
            routing.route,
        )
        if utterance_plan_source is not None:
            input_fingerprint = utterance_plan_source.input_fingerprint(
                input_fingerprint
            )
        return start_stage(
            self._state.stage_attempts[job_id] if attempts is None else attempts,
            stage="asr",
            input_fingerprint_sha256=input_fingerprint,
            component_id=routing.route.pool_id,
            component_revision=routing.route.model_revision,
            started_at_utc=started_at_utc,
        )

    def _preflight_asr_stage_locked(self, job_id: str, started_at_utc: str) -> None:
        candidate_attempts = deepcopy(self._state.stage_attempts[job_id])
        self._start_asr_stage_locked(
            job_id,
            started_at_utc,
            attempts=candidate_attempts,
        )

    def _mark_stage_attempt_limit_locked(self, job_id: str) -> None:
        failed_at = self._now()
        job = self._state.jobs[job_id]
        job["status"] = "failed"
        job["updatedAtUtc"] = failed_at
        job["error"] = {
            "code": "ASR_STAGE_ATTEMPT_LIMIT",
            "message": "The bounded ASR stage retry history is exhausted.",
            "retryable": False,
            "requestId": f"job-{job_id}",
        }
        self._purge_private_audio_locked(job_id)

    def _finish_running_stage_locked(
        self,
        job_id: str,
        stage: str,
        *,
        state: str,
        retryable: bool,
        reason: str,
        completed_at_utc: str,
    ) -> None:
        running = next(
            (
                attempt
                for attempt in reversed(self._state.stage_attempts[job_id])
                if attempt["stage"] == stage and attempt["state"] == "running"
            ),
            None,
        )
        if running is None:
            return
        finish_stage(
            self._state.stage_attempts[job_id],
            stage=stage,
            attempt=int(running["attempt"]),
            state=state,
            completed_at_utc=completed_at_utc,
            retryable=retryable,
            reason=reason,
        )

    def _recover_interrupted_stages_locked(self) -> None:
        for job_id, job in self._state.jobs.items():
            if job.get("status") != "server_processing":
                continue
            interrupted_at = self._now()
            recovered_running_stage = False
            for stage in ("asr", "alignment", "result_publication"):
                running = any(
                    attempt["stage"] == stage and attempt["state"] == "running"
                    for attempt in self._state.stage_attempts[job_id]
                )
                if not running:
                    continue
                recovered_running_stage = True
                self._finish_running_stage_locked(
                    job_id,
                    stage,
                    state="failed",
                    retryable=True,
                    reason="SERVER_RESTARTED",
                    completed_at_utc=interrupted_at,
                )
            if recovered_running_stage:
                job["updatedAtUtc"] = interrupted_at
                self._persist_job_locked(job_id)

    def _attach_processing_callback(
        self,
        job_id: str,
        language_bcp47: str,
        future: Future[dict[str, object]],
        completion_event: threading.Event,
    ) -> None:
        future.add_done_callback(
            lambda completed: self._finish_processing(
                job_id,
                language_bcp47,
                completed,
                completion_event,
            )
        )

    def _finish_processing(
        self,
        job_id: str,
        language_bcp47: str,
        future: Future[dict[str, object]],
        completion_event: threading.Event,
    ) -> None:
        with self._lock:
            if self._stopping:
                if self._futures.get(job_id) is future:
                    self._futures.pop(job_id, None)
                if self._completion_events.get(job_id) is completion_event:
                    self._completion_events.pop(job_id, None)
                completion_event.set()
            else:
                # Linearize completion against begin_runtime_shutdown. Either
                # publication finishes while this runtime still owns storage,
                # or shutdown retires the callback before it mutates anything.
                self._completion.finish_safely(
                    job_id,
                    language_bcp47,
                    future,
                    completion_event,
                )
        self._pump_pending_processing()

    def _pump_pending_processing(self) -> None:
        with self._lock:
            if self._stopping:
                return
            if self._pending_pump_active:
                self._pending_pump_requested = True
                return
            self._pending_pump_active = True
            self._pending_pump_requested = False

        try:
            while True:
                self._pump_pending_processing_pass()
                with self._lock:
                    if self._stopping:
                        self._pending_pump_requested = False
                        self._pending_pump_active = False
                        return
                    if self._pending_pump_requested:
                        self._pending_pump_requested = False
                        continue
                    # Clear ownership while holding the same lock used by a
                    # concurrent completion to request another pass. This
                    # prevents a release notification from being lost between
                    # the last queue check and owner teardown.
                    self._pending_pump_active = False
                    return
        except BaseException:
            with self._lock:
                self._pending_pump_active = False
                self._pending_pump_requested = False
            raise

    def _pump_pending_processing_pass(self) -> None:
        while True:
            callback: tuple[
                str,
                str,
                Future[dict[str, object]],
                threading.Event,
            ] | None = None
            with self._lock:
                if self._stopping:
                    return
                while self._pending_processing:
                    job_id = self._pending_processing.popleft()
                    job = self._state.jobs.get(job_id)
                    if (
                        job is not None
                        and job.get("status") == "server_processing"
                        and job_id not in self._futures
                    ):
                        break
                else:
                    return
                try:
                    started_at = self._now()
                    self._preflight_asr_stage_locked(job_id, started_at)
                    preparation = self._build_input_preparation_locked(
                        job_id,
                        self._state.requests[job_id],
                    )
                    reservation = self._processor.reserve(
                        job_id,
                        pcm_byte_length=preparation.pcm_byte_length,
                    )
                except PoolBackpressure:
                    self._pending_processing.appendleft(job_id)
                    return
                except StageAttemptCapacityError:
                    self._mark_stage_attempt_limit_locked(job_id)
                    continue
                except BaseException:
                    self._mark_processing_activation_failed_locked(job_id)
                    continue
                try:
                    self._start_asr_stage_locked(job_id, started_at)
                    self._persist_job_locked(job_id)
                except BaseException:
                    reservation.abort()
                    self._mark_processing_activation_failed_locked(job_id)
                    continue
                try:
                    future = reservation.start(preparation.prepare)
                except BaseException:
                    reservation.abort()
                    self._mark_processing_activation_failed_locked(job_id)
                    continue
                completion_event = threading.Event()
                self._futures[job_id] = future
                self._completion_events[job_id] = completion_event
                callback = (
                    job_id,
                    preparation.language_bcp47,
                    future,
                    completion_event,
                )
            assert callback is not None
            self._attach_processing_callback(*callback)

    def _has_pending_restart_work_locked(self) -> bool:
        return any(
            (job := self._state.jobs.get(pending_job_id)) is not None
            and job.get("status") == "server_processing"
            and pending_job_id not in self._futures
            for pending_job_id in self._pending_processing
        )

    def _mark_processing_activation_failed_locked(self, job_id: str) -> None:
        job = self._state.jobs[job_id]
        failed_at = self._now()
        job["status"] = "failed"
        job["updatedAtUtc"] = failed_at
        job["error"] = {
            "code": "SERVER_STORAGE_ERROR",
            "message": "Private processing could not be resumed safely.",
            "retryable": True,
            "requestId": f"job-{job_id}",
        }
        self._finish_running_stage_locked(
            job_id,
            "asr",
            state="failed",
            retryable=True,
            reason="SERVER_STORAGE_ERROR",
            completed_at_utc=failed_at,
        )
        self._persist_job_locked(job_id)

    def cancel(self, job_id: str) -> dict[str, object]:
        future: object | None = None
        completion_event: threading.Event | None = None
        with self._lock:
            self._require_runtime_admission_open_locked()
            job = self._state.jobs[job_id]
            error = job.get("error")
            if (
                job.get("status") == "failed"
                and isinstance(error, Mapping)
                and error.get("code") == "ASR_CLEANUP_UNVERIFIED"
            ):
                raise JobServiceError(
                    503,
                    "CANCELLATION_CLEANUP_UNVERIFIED",
                    "Worker cleanup could not be verified.",
                    retryable=True,
                )
            status = job["status"]
            if status == "cancelled":
                if job_id in self._futures:
                    self._persist_job_locked(job_id)
                else:
                    self._purge_private_audio_locked(job_id)
                return deepcopy(job)
            future = self._futures.get(job_id)
            self._state.cancelled.add(job_id)
            if future is not None:
                try:
                    self._persist_job_locked(job_id)
                except BaseException:
                    self._state.cancelled.discard(job_id)
                    raise
                completion_event = self._completion_events.get(job_id)
            else:
                self._finalize_cancellation_locked(job_id)
                return deepcopy(self._state.jobs[job_id])
        if future is not None:
            cancel_processor = getattr(self._processor, "cancel", None)
            if callable(cancel_processor):
                cancel_processor(job_id)
            else:
                future.cancel()
        if completion_event is None or not completion_event.wait(
            timeout=self._cancellation_timeout_seconds
        ):
            raise JobServiceError(
                503,
                "CANCELLATION_PENDING",
                "Worker cleanup is still pending.",
                retryable=True,
            )
        with self._lock:
            self._require_runtime_admission_open_locked()
            job = self._state.jobs[job_id]
            error = job.get("error")
            if (
                job.get("status") == "failed"
                and isinstance(error, Mapping)
                and error.get("code") == "ASR_CLEANUP_UNVERIFIED"
            ):
                raise JobServiceError(
                    503,
                    "CANCELLATION_CLEANUP_UNVERIFIED",
                    "Worker cleanup could not be verified.",
                    retryable=True,
                )
            self._finalize_cancellation_locked(job_id)
            return deepcopy(self._state.jobs[job_id])

    def _finalize_cancellation_locked(self, job_id: str) -> None:
        job = self._state.jobs[job_id]
        job["status"] = "cancelled"
        job["updatedAtUtc"] = self._now()
        job.pop("error", None)
        self._purge_private_audio_locked(job_id)
        completion_event = self._completion_events.pop(job_id, None)
        if completion_event is not None:
            completion_event.set()

    def get_result(self, job_id: str) -> dict[str, object]:
        with self._lock:
            if job_id not in self._state.jobs:
                raise JobServiceError(
                    404,
                    "JOB_NOT_FOUND",
                    "Recording job not found.",
                )
            if job_id not in self._state.results:
                raise JobServiceError(
                    409,
                    "RESULT_NOT_READY",
                    "The immutable transcript result is not available yet.",
                    retryable=self._state.jobs[job_id].get("status") != "failed",
                )
            return deepcopy(self._state.results[job_id])

    def _purge_private_audio_locked(self, job_id: str) -> None:
        self._store.purge_private_audio(self._state, job_id)

    def prune_expired(self) -> int:
        with self._lock:
            self._require_runtime_admission_open_locked()
            return self._prune_expired_jobs_locked(
                _utc_timestamp(self._now(), "server clock")
            )

    def _prune_expired_jobs_locked(self, now: datetime) -> int:
        expired: list[str] = []
        for job_id, job in self._state.jobs.items():
            metadata = _mapping(self._state.requests[job_id].get("metadata"), "metadata")
            retention = metadata.get("retentionExpiresAtUtc")
            if retention is not None and _utc_timestamp(
                retention,
                "retentionExpiresAtUtc",
            ) <= now:
                expired.append(job_id)
        deleted = 0
        for job_id in expired:
            job = self._state.jobs[job_id]
            if job.get("status") not in _TERMINAL_STATUSES:
                if job_id not in self._state.cancelled:
                    self._state.cancelled.add(job_id)
                    self._persist_job_locked(job_id)
                future = self._futures.get(job_id)
                if future is not None:
                    cancel_processor = getattr(self._processor, "cancel", None)
                    if callable(cancel_processor):
                        cancel_processor(job_id)
                    else:
                        future.cancel()
                if job_id in self._futures:
                    continue
                self._finalize_cancellation_locked(job_id)
            if job.get("status") == "cancelled":
                self._purge_private_audio_locked(job_id)
            self._delete_job_locked(job_id)
            deleted += 1
        return deleted

    def _delete_job_locked(self, job_id: str) -> None:
        self._store.delete(self._state, job_id)

    def _persist_job_locked(self, job_id: str) -> None:
        self._store.persist(self._state, job_id)


def _build_utterance_plan_source(
    preprocessing_value: object,
    *,
    input_sample_count: int,
) -> UtterancePlanSource:
    preprocessing = _mapping(preprocessing_value, "preprocessingEvidence")
    normalization = _mapping(
        preprocessing.get("normalization"),
        "preprocessingEvidence.normalization",
    )
    vad = _mapping(
        preprocessing.get("vad"),
        "preprocessingEvidence.vad",
    )
    raw_intervals = vad.get("intervals")
    if not isinstance(raw_intervals, list):
        raise ValueError("preprocessing VAD intervals are invalid")
    intervals: list[tuple[int, int]] = []
    for index, raw_interval in enumerate(raw_intervals):
        interval = _mapping(
            raw_interval,
            f"preprocessingEvidence.vad.intervals[{index}]",
        )
        start = interval.get("startSample")
        end = interval.get("endSampleExclusive")
        if (
            not isinstance(start, int)
            or isinstance(start, bool)
            or not isinstance(end, int)
            or isinstance(end, bool)
        ):
            raise ValueError("preprocessing VAD interval bounds are invalid")
        intervals.append((start, end))
    source_sample_count = normalization.get("sourceSampleCount")
    vad_status = vad.get("status")
    if (
        not isinstance(source_sample_count, int)
        or isinstance(source_sample_count, bool)
        or not isinstance(vad_status, str)
    ):
        raise ValueError("preprocessing evidence cannot form an utterance plan")
    return UtterancePlanSource(
        input_sample_count=input_sample_count,
        source_sample_count=source_sample_count,
        vad_status=vad_status,
        vad_evidence_sha256=canonical_vad_evidence_sha256(vad),
        vad_intervals=tuple(intervals),
    )


def _utterance_plan_source_for_route(
    creation: Mapping[str, object],
    route: AsrRouteDecision,
) -> UtterancePlanSource | None:
    if (
        route.execution_mode != "dynamicBatch"
        and route.pool_id != "nemotron-batch"
    ):
        return None
    preprocessing = creation.get("preprocessingEvidence")
    if preprocessing is None:
        raise ValueError(
            "bounded Nemotron or dynamic processing requires preprocessing evidence"
        )
    chunks = creation.get("chunks")
    if not isinstance(chunks, list):
        raise ValueError("job creation chunks are invalid")
    input_bytes = 0
    for raw_chunk in chunks:
        content = _mapping(
            _mapping(raw_chunk, "chunk").get("contentIdentity"),
            "contentIdentity",
        )
        byte_length = content.get("byteLength")
        if (
            not isinstance(byte_length, int)
            or isinstance(byte_length, bool)
            or byte_length < 2
            or byte_length % 2 != 0
        ):
            raise ValueError("job creation PCM length is invalid")
        input_bytes += byte_length
    return _build_utterance_plan_source(
        preprocessing,
        input_sample_count=input_bytes // 2,
    )
