from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
from pathlib import Path
import re
import shutil
import stat
from typing import Callable, Mapping, Sequence

from yap_server.pools.batch_contract import (
    AsrRouteResolver,
    DurableAsrRouting,
    validate_asr_catalog_revision,
)

from .artifacts import (
    MAX_STATE_BYTES,
    publish_json,
    read_json_file,
    read_regular_file,
    unlink_private_regular_file,
    unlink_owned_artifact_temporaries,
)
from .chunk_contract import chunk_path, find_chunk, receipt_key
from .contract_values import (
    JOB_STATUSES,
    MAX_CHUNK_BYTES,
    MAX_STORED_JOBS,
    exact_keys,
    mapping,
    utc_timestamp,
)
from .intake_contract import (
    selected_batch_mode,
    selected_language,
    validate_create_request,
)
from .result_contract import (
    capture_duration_ms,
    validate_persisted_projection,
    validate_result_revision,
)
from .state_schema import persisted_state_metadata
from .stage_attempts import canonical_json_sha256, finish_stage, validate_stage_attempts


_JOB_DIRECTORY = re.compile(r"^job-[0-9a-f]{32}$")
_DELETION_TOMBSTONE = re.compile(r"^\.deleting-(job-[0-9a-f]{32})$")
_MAX_PENDING_DELETION_RECONCILIATIONS = 8
_MAX_JOB_STORAGE_ENTRIES = MAX_STORED_JOBS * 2


@dataclass(slots=True)
class DurableJobState:
    jobs: dict[str, dict[str, object]] = field(default_factory=dict)
    requests: dict[str, dict[str, object]] = field(default_factory=dict)
    results: dict[str, dict[str, object]] = field(default_factory=dict)
    receipts: dict[tuple[object, ...], dict[str, object]] = field(default_factory=dict)
    cancelled: set[str] = field(default_factory=set)
    create_keys: dict[str, str | None] = field(default_factory=dict)
    created_by_key: dict[str, str] = field(default_factory=dict)
    asr_routing: dict[str, DurableAsrRouting | None] = field(default_factory=dict)
    stage_history_complete: dict[str, bool] = field(default_factory=dict)
    stage_attempts: dict[str, list[dict[str, object]]] = field(default_factory=dict)
    projection_revisions: dict[str, int] = field(default_factory=dict)
    cleanup_unverified: set[str] = field(default_factory=set)
    pending_deletions: dict[str, None] = field(default_factory=dict)


class RecordingJobStore:
    """Persists and recovers the durable half of the recording-job aggregate.

    The lifecycle service serializes mutations before calling this adapter. Runtime
    worker futures and commit coordination intentionally remain outside this state.
    """

    def __init__(
        self,
        storage_root: Path,
        *,
        supported_languages: Sequence[str],
        now: Callable[[], str],
        startup_worker_cleanup_verified: bool,
        route_resolver: AsrRouteResolver,
        asr_catalog_revision: str,
    ) -> None:
        self.root = storage_root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._supported_languages = frozenset(supported_languages)
        self._now = now
        self._startup_worker_cleanup_verified = startup_worker_cleanup_verified
        self._route_resolver = route_resolver
        validate_asr_catalog_revision(asr_catalog_revision)
        self._asr_catalog_revision = asr_catalog_revision

    def load(self) -> DurableJobState:
        state = DurableJobState()
        jobs_root = self.root / "jobs"
        if not jobs_root.exists():
            return state
        if jobs_root.is_symlink() or not jobs_root.is_dir():
            raise ValueError("job storage root must be a real directory")
        entries: list[Path] = []
        for job_root in jobs_root.iterdir():
            entries.append(job_root)
            if len(entries) > _MAX_JOB_STORAGE_ENTRIES:
                raise ValueError("job storage entry capacity is exceeded")
        entries.sort(key=lambda path: path.name)
        for job_root in entries:
            if _DELETION_TOMBSTONE.fullmatch(job_root.name) is not None:
                self._validate_pending_deletion(job_root)
                state.pending_deletions[job_root.name] = None
                continue
        self.reconcile_pending_deletions(
            state,
            max_attempts=MAX_STORED_JOBS,
        )
        for job_root in entries:
            if _DELETION_TOMBSTONE.fullmatch(job_root.name) is not None:
                continue
            self._load_job(state, job_root)
        if len(state.jobs) + len(state.pending_deletions) > MAX_STORED_JOBS:
            raise ValueError("job storage capacity is exceeded")
        return state

    def reconcile_pending_deletions(
        self,
        state: DurableJobState,
        *,
        max_attempts: int | None = None,
    ) -> int:
        if max_attempts is None:
            max_attempts = _MAX_PENDING_DELETION_RECONCILIATIONS
        if max_attempts < 0:
            raise ValueError("pending deletion reconciliation limit is invalid")
        jobs_root = self.root / "jobs"
        if not jobs_root.exists():
            state.pending_deletions.clear()
            return 0
        if jobs_root.is_symlink() or not jobs_root.is_dir():
            raise ValueError("job storage root must be a real directory")
        removed = 0
        candidates = tuple(state.pending_deletions)[:max_attempts]
        for tombstone_name in candidates:
            tombstone_root = jobs_root / tombstone_name
            try:
                self._validate_pending_deletion(tombstone_root)
                shutil.rmtree(tombstone_root)
            except FileNotFoundError:
                state.pending_deletions.pop(tombstone_name, None)
            except OSError:
                # Rotate persistent debt so later bounded passes remain fair.
                state.pending_deletions.pop(tombstone_name, None)
                state.pending_deletions[tombstone_name] = None
                continue
            state.pending_deletions.pop(tombstone_name, None)
            removed += 1
        return removed

    @staticmethod
    def _validate_pending_deletion(tombstone_root: Path) -> None:
        if _DELETION_TOMBSTONE.fullmatch(tombstone_root.name) is None:
            raise ValueError("pending job deletion identity is invalid")
        metadata = tombstone_root.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise ValueError("pending job deletion is unsafe")

    def persist(self, state: DurableJobState, job_id: str) -> None:
        receipts = [
            deepcopy(receipt)
            for key, receipt in state.receipts.items()
            if key[0] == job_id
        ]
        receipts.sort(
            key=lambda receipt: (
                receipt["replayKey"]["trackId"],
                receipt["replayKey"]["sequenceStart"],
                receipt["replayKey"]["sequenceEnd"],
            )
        )
        routing = state.asr_routing[job_id]
        if routing is None and state.jobs[job_id].get("status") not in {
            "cancelled",
            "complete",
            "failed",
            "partial",
        }:
            raise ValueError("active persisted job is missing frozen ASR routing")
        attempts = validate_stage_attempts(state.stage_attempts[job_id])
        projection_revision = state.projection_revisions[job_id] + 1
        publish_json(
            self.root / "jobs" / job_id / "state.json",
            {
                "schemaVersion": 5,
                "createIdempotencyKey": state.create_keys[job_id],
                "cancellationRequested": job_id in state.cancelled,
                "asrRouting": None if routing is None else routing.to_persisted(),
                "stageHistoryComplete": state.stage_history_complete[job_id],
                "stageAttempts": attempts,
                "projectionRevision": projection_revision,
                "creation": state.requests[job_id],
                "projection": state.jobs[job_id],
                "receipts": receipts,
            },
        )
        state.projection_revisions[job_id] = projection_revision

    def purge_private_audio(self, state: DurableJobState, job_id: str) -> None:
        job_root = self.root / "jobs" / job_id
        chunks_root = job_root / "chunks"
        chunk_metadata = chunks_root.lstat()
        if stat.S_ISLNK(chunk_metadata.st_mode) or not stat.S_ISDIR(
            chunk_metadata.st_mode
        ):
            raise ValueError("private chunk storage is unsafe")
        for stored_receipt_key in tuple(state.receipts):
            if stored_receipt_key[0] == job_id:
                state.receipts.pop(stored_receipt_key, None)
        state.results.pop(job_id, None)
        self.persist(state, job_id)
        for entry in chunks_root.iterdir():
            unlink_private_regular_file(entry, "private recording chunk")
        unlink_owned_artifact_temporaries(job_root)
        for name in (
            "input.wav",
            "input.wav.part",
            "utterance-plan.json",
            "worker-result.json",
            "result-revision.json",
        ):
            unlink_private_regular_file(job_root / name, "private recording artifact")

    def delete(self, state: DurableJobState, job_id: str) -> None:
        job_root = self.root / "jobs" / job_id
        metadata = job_root.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise ValueError("expired job storage is unsafe")
        tombstone_root = job_root.with_name(f".deleting-{job_id}")
        if tombstone_root.exists() or tombstone_root.is_symlink():
            raise ValueError("pending deletion already exists for expired job")
        job_root.rename(tombstone_root)
        state.pending_deletions[tombstone_root.name] = None
        state.jobs.pop(job_id, None)
        state.requests.pop(job_id, None)
        state.results.pop(job_id, None)
        state.cancelled.discard(job_id)
        state.asr_routing.pop(job_id, None)
        state.stage_history_complete.pop(job_id, None)
        state.stage_attempts.pop(job_id, None)
        state.projection_revisions.pop(job_id, None)
        state.cleanup_unverified.discard(job_id)
        create_key = state.create_keys.pop(job_id, None)
        if create_key is not None and state.created_by_key.get(create_key) == job_id:
            state.created_by_key.pop(create_key, None)
        for stored_receipt_key in tuple(state.receipts):
            if stored_receipt_key[0] == job_id:
                state.receipts.pop(stored_receipt_key, None)
        try:
            shutil.rmtree(tombstone_root)
        except OSError:
            # The atomic rename committed logical deletion. A later maintenance
            # pass or restart resumes removal without reloading partial state.
            pass
        else:
            state.pending_deletions.pop(tombstone_root.name, None)

    def _load_job(self, state: DurableJobState, job_root: Path) -> None:
        if job_root.is_symlink() or not job_root.is_dir():
            raise ValueError("job storage contains an unsafe entry")
        job_id = job_root.name
        if _JOB_DIRECTORY.fullmatch(job_id) is None:
            raise ValueError("job storage contains an invalid job directory")
        persisted = read_json_file(job_root / "state.json")
        (
            schema_version,
            create_idempotency_key,
            cancellation_requested,
            persisted_asr_routing,
            stage_history_complete,
            stage_attempts,
            projection_revision,
        ) = persisted_state_metadata(persisted)
        creation = mapping(persisted.get("creation"), "persisted creation")
        validate_create_request(
            creation,
            self._supported_languages,
            require_supported_language=False,
        )
        projection = dict(mapping(persisted.get("projection"), "persisted projection"))
        validate_persisted_projection(job_id, creation, projection)
        status = projection.get("status")
        migration_needed = schema_version < 5
        requires_worker_cleanup = False
        legacy_processing_without_route = False
        if schema_version in {4, 5}:
            asr_routing = (
                None
                if persisted_asr_routing is None
                else DurableAsrRouting.from_persisted(persisted_asr_routing)
            )
            if asr_routing is None and status not in {
                "cancelled",
                "complete",
                "failed",
                "partial",
            }:
                raise ValueError("active persisted job is missing frozen ASR routing")
            if asr_routing is not None:
                declared_catalog_revision = creation.get("asrCatalogRevision")
                if (
                    declared_catalog_revision is not None
                    and declared_catalog_revision
                    != asr_routing.asr_catalog_revision
                ):
                    raise ValueError(
                        "persisted creation catalog revision differs from frozen routing"
                    )
        elif status in {"accepted", "uploading"}:
            try:
                asr_routing = self._freeze_legacy_routing(creation)
            except (RuntimeError, ValueError):
                asr_routing = None
                self._quarantine_legacy_route(job_id, projection)
        elif status == "server_processing":
            asr_routing = None
            requires_worker_cleanup = True
            legacy_processing_without_route = True
        else:
            asr_routing = None
        chunks_root = job_root / "chunks"
        if chunks_root.is_symlink() or not chunks_root.is_dir():
            raise ValueError("persisted chunk storage is unsafe")
        receipts = persisted.get("receipts")
        if not isinstance(receipts, list):
            raise ValueError("persisted receipts must be an array")
        state.requests[job_id] = deepcopy(dict(creation))
        state.jobs[job_id] = projection
        state.asr_routing[job_id] = asr_routing
        state.stage_history_complete[job_id] = stage_history_complete
        state.stage_attempts[job_id] = stage_attempts
        state.projection_revisions[job_id] = projection_revision
        state.create_keys[job_id] = create_idempotency_key
        if create_idempotency_key is not None:
            if create_idempotency_key in state.created_by_key:
                raise ValueError("persisted create idempotency key is duplicated")
            state.created_by_key[create_idempotency_key] = job_id
        for raw_receipt in receipts:
            self._load_receipt(state, job_id, job_root, creation, raw_receipt)
        self._reconcile_projection(
            state,
            job_id,
            job_root,
            projection,
            cancellation_requested,
            requires_worker_cleanup=requires_worker_cleanup,
            legacy_processing_without_route=legacy_processing_without_route,
        )
        if migration_needed:
            self.persist(state, job_id)

    def _freeze_legacy_routing(
        self,
        creation: Mapping[str, object],
    ) -> DurableAsrRouting:
        declared_catalog_revision = creation.get("asrCatalogRevision")
        if (
            declared_catalog_revision is not None
            and declared_catalog_revision != self._asr_catalog_revision
        ):
            raise ValueError("legacy job declared a different ASR catalog revision")
        language_bcp47 = selected_language(
            creation,
            self._supported_languages,
        )
        route = self._route_resolver(language_bcp47)
        if route.execution_mode != selected_batch_mode(creation):
            raise ValueError("legacy ASR route mode differs from its language decision")
        return DurableAsrRouting(
            route=route,
            asr_catalog_revision=self._asr_catalog_revision,
        )

    def _quarantine_legacy_route(
        self,
        job_id: str,
        projection: dict[str, object],
    ) -> None:
        projection["status"] = "failed"
        projection["updatedAtUtc"] = self._now()
        projection["error"] = {
            "code": "ASR_ROUTE_UNRECOVERABLE",
            "message": "The persisted ASR route could not be recovered safely.",
            "retryable": False,
            "requestId": f"job-{job_id}",
        }

    def _load_receipt(
        self,
        state: DurableJobState,
        job_id: str,
        job_root: Path,
        creation: Mapping[str, object],
        raw_receipt: object,
    ) -> None:
        receipt = dict(mapping(raw_receipt, "persisted receipt"))
        exact_keys(
            receipt,
            {"replayKey", "contentIdentity", "disposition", "acceptedAtUtc"},
            "persisted receipt",
        )
        replay = mapping(receipt.get("replayKey"), "persisted replay key")
        exact_keys(
            replay,
            {"schemaVersion", "sessionId", "trackId", "sequenceStart", "sequenceEnd"},
            "persisted replay key",
        )
        content = mapping(receipt.get("contentIdentity"), "persisted content identity")
        exact_keys(content, {"sha256", "byteLength"}, "persisted content identity")
        if receipt.get("disposition") != "accepted":
            raise ValueError("persisted receipt disposition is invalid")
        utc_timestamp(receipt.get("acceptedAtUtc"), "persisted acceptedAtUtc")
        try:
            declared_chunk = find_chunk(
                creation,
                track_id=replay.get("trackId"),
                sequence_start=replay.get("sequenceStart"),
                sequence_end=replay.get("sequenceEnd"),
            )
        except KeyError as error:
            raise ValueError("persisted receipt is not declared") from error
        if replay != mapping(
            declared_chunk.get("replayKey"),
            "declared replay key",
        ) or content != mapping(
            declared_chunk.get("contentIdentity"),
            "declared content identity",
        ):
            raise ValueError("persisted receipt differs from its declaration")
        key = receipt_key(job_id, replay)
        if key in state.receipts:
            raise ValueError("persisted receipt is duplicated")
        body = read_regular_file(chunk_path(job_root, replay), MAX_CHUNK_BYTES)
        if (
            len(body) != content.get("byteLength")
            or hashlib.sha256(body).hexdigest() != content.get("sha256")
        ):
            raise ValueError("persisted chunk differs from its receipt")
        state.receipts[key] = receipt

    def _reconcile_projection(
        self,
        state: DurableJobState,
        job_id: str,
        job_root: Path,
        projection: dict[str, object],
        cancellation_requested: bool,
        *,
        requires_worker_cleanup: bool = False,
        legacy_processing_without_route: bool = False,
    ) -> None:
        status = projection.get("status")
        if status not in JOB_STATUSES:
            raise ValueError("persisted job status is invalid")
        error = projection.get("error")
        cleanup_was_unverified = (
            status == "failed"
            and isinstance(error, Mapping)
            and error.get("code") == "ASR_CLEANUP_UNVERIFIED"
        )
        if (
            cancellation_requested
            or status == "server_processing"
            or cleanup_was_unverified
            or requires_worker_cleanup
        ) and not self._startup_worker_cleanup_verified:
            raise ValueError("persisted worker state requires verified startup cleanup")
        if cancellation_requested and status != "cancelled":
            state.cancelled.add(job_id)
            projection["status"] = "cancelled"
            projection["updatedAtUtc"] = self._now()
            projection.pop("error", None)
            self.purge_private_audio(state, job_id)
            return
        result_path = job_root / "result-revision.json"
        if legacy_processing_without_route and result_path.exists():
            result_metadata = result_path.lstat()
            if stat.S_ISLNK(result_metadata.st_mode) or not stat.S_ISREG(
                result_metadata.st_mode
            ):
                raise ValueError("persisted result artifact is unsafe")
        try:
            status = self._load_result(state, job_id, job_root, projection, status)
        except ValueError:
            if not legacy_processing_without_route:
                raise
            self._quarantine_legacy_route(job_id, projection)
            status = "failed"
        if legacy_processing_without_route and status == "server_processing":
            self._quarantine_legacy_route(job_id, projection)
            status = "failed"
        if status == "cancelled":
            state.cancelled.add(job_id)
            self.purge_private_audio(state, job_id)
        elif status == "failed":
            error = projection.get("error")
            retryable = isinstance(error, Mapping) and error.get("retryable") is True
            latest_failed_stage = next(
                (
                    attempt
                    for attempt in reversed(state.stage_attempts[job_id])
                    if attempt.get("state") == "failed"
                ),
                None,
            )
            retains_retry_input = (
                retryable
                and latest_failed_stage is not None
                and latest_failed_stage.get("retryable") is True
                and latest_failed_stage.get("reason") == error.get("code")
            )
            if not retains_retry_input:
                self.purge_private_audio(state, job_id)
        if status in {"complete", "partial"} and job_id not in state.results:
            raise ValueError("completed persisted job has no result")
        # A verified startup cleanup proves that no worker from the previous
        # process is still live. Keep durable processing intent so the service
        # can safely re-admit it with at-least-once inference semantics.

    def _load_result(
        self,
        state: DurableJobState,
        job_id: str,
        job_root: Path,
        projection: dict[str, object],
        status: object,
    ) -> object:
        result_path = job_root / "result-revision.json"
        if not result_path.exists():
            return status
        if status in {"cancelled", "failed"}:
            read_regular_file(result_path, MAX_STATE_BYTES)
            result_path.unlink()
            return status
        if status not in {"server_processing", "complete", "partial"}:
            raise ValueError("non-processing job has an unexpected result")
        result = dict(read_json_file(result_path))
        validate_result_revision(
            result,
            projection,
            maximum_end_ms=capture_duration_ms(state.requests[job_id]),
        )
        if status in {"complete", "partial"} and result.get("status") != status:
            raise ValueError("persisted result status differs")
        state.results[job_id] = result
        if status == "server_processing":
            self._reconcile_published_result_stage(state, job_id, result)
            projection["status"] = result["status"]
            projection["updatedAtUtc"] = result["createdAtUtc"]
            projection.pop("error", None)
            status = projection["status"]
            self.persist(state, job_id)
        return status

    def _reconcile_published_result_stage(
        self,
        state: DurableJobState,
        job_id: str,
        result: Mapping[str, object],
    ) -> None:
        running = next(
            (
                attempt
                for attempt in reversed(state.stage_attempts[job_id])
                if attempt["stage"] == "result_publication"
                and attempt["state"] == "running"
            ),
            None,
        )
        if running is None:
            return
        finish_stage(
            state.stage_attempts[job_id],
            stage="result_publication",
            attempt=int(running["attempt"]),
            state="succeeded",
            completed_at_utc=str(result["createdAtUtc"]),
            retryable=False,
            output_fingerprint_sha256=canonical_json_sha256(result),
            evidence={"resultRevision": result["revision"], "status": result["status"]},
        )
