from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import os
from pathlib import Path
import re
import stat
from typing import Callable, Mapping, Sequence

from yap_server.auth import PrincipalKey
from yap_server.pools.batch_contract import DurableAsrRouting

from .artifacts import (
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
from .intake_contract import validate_create_request
from .ownership import idempotency_owner_key
from .result_bundle import (
    ResultBundleAdapterRegistry,
    result_bundle_fingerprint,
)
from .result_contract import (
    capture_duration_ms,
    validate_persisted_projection,
    validate_result_revision,
)
from .state_schema import PERSISTED_JOB_STATE_SCHEMA_VERSION, persisted_state_metadata
from .stage_attempts import canonical_json_sha256, finish_stage, validate_stage_attempts


_JOB_DIRECTORY = re.compile(r"^job-[0-9a-f]{32}$")
_DELETION_TOMBSTONE = re.compile(r"^\.deleting-(job-[0-9a-f]{32})$")
_MAX_PENDING_DELETION_TOMBSTONES_PER_PASS = 8
_MAX_PENDING_DELETION_ENTRIES_PER_PASS = 256
_MAX_PENDING_DELETION_DEPTH = 64
_MAX_UNPERSISTED_CREATE_DELETION_ENTRIES = 8
_MAX_JOB_STORAGE_ENTRIES = MAX_STORED_JOBS * 2


@dataclass(slots=True)
class DurableJobState:
    jobs: dict[str, dict[str, object]] = field(default_factory=dict)
    requests: dict[str, dict[str, object]] = field(default_factory=dict)
    results: dict[str, dict[str, object]] = field(default_factory=dict)
    speaker_results: dict[str, dict[str, object]] = field(default_factory=dict)
    receipts: dict[tuple[object, ...], dict[str, object]] = field(default_factory=dict)
    cancelled: set[str] = field(default_factory=set)
    owners: dict[str, PrincipalKey] = field(default_factory=dict)
    create_keys: dict[str, str | None] = field(default_factory=dict)
    created_by_key: dict[tuple[str, str, str], str] = field(default_factory=dict)
    asr_routing: dict[str, DurableAsrRouting | None] = field(default_factory=dict)
    stage_history_complete: dict[str, bool] = field(default_factory=dict)
    stage_attempts: dict[str, list[dict[str, object]]] = field(default_factory=dict)
    projection_revisions: dict[str, int] = field(default_factory=dict)
    cleanup_unverified: set[str] = field(default_factory=set)
    pending_deletions: dict[str, None] = field(default_factory=dict)


@dataclass(slots=True)
class _DeletionWorkBudget:
    remaining_entries: int

    def consume_entry(self) -> bool:
        if self.remaining_entries == 0:
            return False
        self.remaining_entries -= 1
        return True


def _metadata_is_link_or_reparse(metadata: os.stat_result) -> bool:
    reparse_attribute = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    file_attributes = getattr(metadata, "st_file_attributes", 0)
    return stat.S_ISLNK(metadata.st_mode) or bool(
        reparse_attribute and file_attributes & reparse_attribute
    )


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
        result_bundle_adapters: ResultBundleAdapterRegistry | None = None,
    ) -> None:
        self.root = storage_root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._supported_languages = frozenset(supported_languages)
        self._now = now
        self._startup_worker_cleanup_verified = startup_worker_cleanup_verified
        self._result_bundle_adapters = (
            result_bundle_adapters or ResultBundleAdapterRegistry()
        )

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
        self.reconcile_pending_deletions(state)
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
        max_tombstones: int | None = None,
        max_entries: int | None = None,
    ) -> int:
        if max_tombstones is None:
            max_tombstones = _MAX_PENDING_DELETION_TOMBSTONES_PER_PASS
        if max_entries is None:
            max_entries = _MAX_PENDING_DELETION_ENTRIES_PER_PASS
        if (
            not isinstance(max_tombstones, int)
            or isinstance(max_tombstones, bool)
            or max_tombstones < 0
            or not isinstance(max_entries, int)
            or isinstance(max_entries, bool)
            or max_entries < 0
        ):
            raise ValueError("pending deletion reconciliation limits are invalid")
        jobs_root = self.root / "jobs"
        if not jobs_root.exists():
            state.pending_deletions.clear()
            return 0
        if jobs_root.is_symlink() or not jobs_root.is_dir():
            raise ValueError("job storage root must be a real directory")
        removed = 0
        budget = _DeletionWorkBudget(max_entries)
        candidates = tuple(state.pending_deletions)[:max_tombstones]
        for tombstone_name in candidates:
            if budget.remaining_entries == 0:
                break
            tombstone_root = jobs_root / tombstone_name
            try:
                self._validate_pending_deletion(tombstone_root)
                complete = self._delete_directory_incrementally(
                    tombstone_root,
                    tombstone_root=tombstone_root,
                    budget=budget,
                    depth=0,
                )
            except FileNotFoundError:
                state.pending_deletions.pop(tombstone_name, None)
            except OSError:
                self._rotate_pending_deletion(state, tombstone_name)
                continue
            else:
                if not complete:
                    self._rotate_pending_deletion(state, tombstone_name)
                    continue
                state.pending_deletions.pop(tombstone_name, None)
            removed += 1
        return removed

    def _delete_directory_incrementally(
        self,
        directory: Path,
        *,
        tombstone_root: Path,
        budget: _DeletionWorkBudget,
        depth: int,
    ) -> bool:
        if depth > _MAX_PENDING_DELETION_DEPTH:
            raise ValueError("pending job deletion nesting is unsafe")
        self._validate_deletion_descendant(directory, tombstone_root)
        try:
            iterator = os.scandir(directory)
        except FileNotFoundError:
            return True
        with iterator:
            for entry in iterator:
                child = self._deletion_child_path(
                    directory,
                    entry.name,
                    tombstone_root=tombstone_root,
                )
                try:
                    metadata = entry.stat(follow_symlinks=False)
                except FileNotFoundError:
                    continue
                if stat.S_ISDIR(metadata.st_mode) and not _metadata_is_link_or_reparse(
                    metadata
                ):
                    if not self._delete_directory_incrementally(
                        child,
                        tombstone_root=tombstone_root,
                        budget=budget,
                        depth=depth + 1,
                    ):
                        return False
                    continue
                if not budget.consume_entry():
                    return False
                try:
                    if stat.S_ISDIR(metadata.st_mode):
                        os.rmdir(child)
                    else:
                        os.unlink(child)
                except FileNotFoundError:
                    continue
        if not budget.consume_entry():
            return False
        try:
            os.rmdir(directory)
        except FileNotFoundError:
            return True
        return True

    @staticmethod
    def _validate_deletion_descendant(path: Path, tombstone_root: Path) -> None:
        try:
            path.relative_to(tombstone_root)
            metadata = path.lstat()
        except FileNotFoundError:
            return
        except ValueError as error:
            raise ValueError("pending job deletion escaped its tombstone") from error
        if _metadata_is_link_or_reparse(metadata) or not stat.S_ISDIR(metadata.st_mode):
            raise ValueError("pending job deletion contains an unsafe directory")

    @staticmethod
    def _deletion_child_path(
        directory: Path,
        name: str,
        *,
        tombstone_root: Path,
    ) -> Path:
        if not name or Path(name).name != name or name in {".", ".."}:
            raise ValueError("pending job deletion entry identity is unsafe")
        child = directory / name
        try:
            child.relative_to(tombstone_root)
        except ValueError as error:
            raise ValueError("pending job deletion escaped its tombstone") from error
        return child

    @staticmethod
    def _rotate_pending_deletion(
        state: DurableJobState,
        tombstone_name: str,
    ) -> None:
        if tombstone_name in state.pending_deletions:
            state.pending_deletions.pop(tombstone_name)
            state.pending_deletions[tombstone_name] = None

    @staticmethod
    def _validate_pending_deletion(tombstone_root: Path) -> None:
        if _DELETION_TOMBSTONE.fullmatch(tombstone_root.name) is None:
            raise ValueError("pending job deletion identity is invalid")
        metadata = tombstone_root.lstat()
        if _metadata_is_link_or_reparse(metadata) or not stat.S_ISDIR(metadata.st_mode):
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
                "schemaVersion": PERSISTED_JOB_STATE_SCHEMA_VERSION,
                "owner": {
                    "tenantId": state.owners[job_id].tenant_id,
                    "subjectId": state.owners[job_id].subject_id,
                },
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
        state.speaker_results.pop(job_id, None)
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
            "speaker-result-revision.json",
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
        state.speaker_results.pop(job_id, None)
        state.cancelled.discard(job_id)
        state.asr_routing.pop(job_id, None)
        state.stage_history_complete.pop(job_id, None)
        state.stage_attempts.pop(job_id, None)
        state.projection_revisions.pop(job_id, None)
        state.cleanup_unverified.discard(job_id)
        owner = state.owners.pop(job_id, None)
        create_key = state.create_keys.pop(job_id, None)
        if create_key is not None and owner is not None:
            owner_key = idempotency_owner_key(owner, create_key)
            if state.created_by_key.get(owner_key) == job_id:
                state.created_by_key.pop(owner_key, None)
        for stored_receipt_key in tuple(state.receipts):
            if stored_receipt_key[0] == job_id:
                state.receipts.pop(stored_receipt_key, None)

    def rollback_unpersisted_create(
        self,
        state: DurableJobState,
        job_id: str,
    ) -> None:
        self.delete(state, job_id)
        tombstone_name = f".deleting-{job_id}"
        tombstone_root = self.root / "jobs" / tombstone_name
        budget = _DeletionWorkBudget(_MAX_UNPERSISTED_CREATE_DELETION_ENTRIES)
        try:
            self._validate_pending_deletion(tombstone_root)
            complete = self._delete_directory_incrementally(
                tombstone_root,
                tombstone_root=tombstone_root,
                budget=budget,
                depth=0,
            )
        except FileNotFoundError:
            complete = True
        except OSError:
            return
        if complete:
            state.pending_deletions.pop(tombstone_name, None)

    def _load_job(self, state: DurableJobState, job_root: Path) -> None:
        if job_root.is_symlink() or not job_root.is_dir():
            raise ValueError("job storage contains an unsafe entry")
        job_id = job_root.name
        if _JOB_DIRECTORY.fullmatch(job_id) is None:
            raise ValueError("job storage contains an invalid job directory")
        persisted = read_json_file(job_root / "state.json")
        metadata = persisted_state_metadata(persisted)
        creation = mapping(persisted.get("creation"), "persisted creation")
        validate_create_request(
            creation,
            self._supported_languages,
            require_supported_language=False,
        )
        projection = dict(mapping(persisted.get("projection"), "persisted projection"))
        validate_persisted_projection(job_id, creation, projection)
        status = projection.get("status")
        asr_routing = (
            None
            if metadata.asr_routing is None
            else DurableAsrRouting.from_persisted(metadata.asr_routing)
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
                and declared_catalog_revision != asr_routing.asr_catalog_revision
            ):
                raise ValueError(
                    "persisted creation catalog revision differs from frozen routing"
                )
        chunks_root = job_root / "chunks"
        if chunks_root.is_symlink() or not chunks_root.is_dir():
            raise ValueError("persisted chunk storage is unsafe")
        receipts = persisted.get("receipts")
        if not isinstance(receipts, list):
            raise ValueError("persisted receipts must be an array")
        state.requests[job_id] = deepcopy(dict(creation))
        state.jobs[job_id] = projection
        state.owners[job_id] = metadata.owner
        state.asr_routing[job_id] = asr_routing
        state.stage_history_complete[job_id] = metadata.stage_history_complete
        state.stage_attempts[job_id] = metadata.stage_attempts
        state.projection_revisions[job_id] = metadata.projection_revision
        state.create_keys[job_id] = metadata.create_idempotency_key
        if metadata.create_idempotency_key is not None:
            owner_key = idempotency_owner_key(
                metadata.owner,
                metadata.create_idempotency_key,
            )
            if owner_key in state.created_by_key:
                raise ValueError("persisted create idempotency key is duplicated")
            state.created_by_key[owner_key] = job_id
        for raw_receipt in receipts:
            self._load_receipt(state, job_id, job_root, creation, raw_receipt)
        self._reconcile_projection(
            state,
            job_id,
            job_root,
            projection,
            metadata.cancellation_requested,
        )

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
        if len(body) != content.get("byteLength") or hashlib.sha256(
            body
        ).hexdigest() != content.get("sha256"):
            raise ValueError("persisted chunk differs from its receipt")
        state.receipts[key] = receipt

    def _reconcile_projection(
        self,
        state: DurableJobState,
        job_id: str,
        job_root: Path,
        projection: dict[str, object],
        cancellation_requested: bool,
    ) -> None:
        status = projection.get("status")
        if status not in JOB_STATUSES:
            raise ValueError("persisted job status is invalid")
        retention_expired = self._retention_expired(state, job_id)
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
        ) and not self._startup_worker_cleanup_verified:
            raise ValueError("persisted worker state requires verified startup cleanup")
        if cancellation_requested and status != "cancelled":
            state.cancelled.add(job_id)
            projection["status"] = "cancelled"
            projection["updatedAtUtc"] = self._now()
            projection.pop("error", None)
            if retention_expired:
                self.persist(state, job_id)
            else:
                self.purge_private_audio(state, job_id)
            return
        status = self._load_result(state, job_id, job_root, projection, status)
        if status == "cancelled":
            state.cancelled.add(job_id)
            if not retention_expired:
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
            if not retains_retry_input and not retention_expired:
                self.purge_private_audio(state, job_id)
        if status in {"complete", "partial"} and job_id not in state.results:
            raise ValueError("completed persisted job has no result")
        # A verified startup cleanup proves that no worker from the previous
        # process is still live. Keep durable processing intent so the service
        # can safely re-admit it with at-least-once inference semantics.

    def _retention_expired(
        self,
        state: DurableJobState,
        job_id: str,
    ) -> bool:
        metadata = mapping(
            state.requests[job_id].get("metadata"),
            "persisted metadata",
        )
        retention = metadata.get("retentionExpiresAtUtc")
        return retention is not None and utc_timestamp(
            retention,
            "persisted retentionExpiresAtUtc",
        ) <= utc_timestamp(self._now(), "server clock")

    def _load_result(
        self,
        state: DurableJobState,
        job_id: str,
        job_root: Path,
        projection: dict[str, object],
        status: object,
    ) -> object:
        result_path = job_root / "result-revision.json"
        speaker_result_path = job_root / "speaker-result-revision.json"
        routing = state.asr_routing[job_id]
        adapter = (
            None
            if routing is None
            else self._result_bundle_adapters.for_route(routing.route)
        )
        requires_speaker_result = (
            adapter is not None and adapter.requires_speaker_result
        )
        if not result_path.exists():
            if speaker_result_path.exists():
                if requires_speaker_result and status in {
                    "server_processing",
                    "failed",
                    "cancelled",
                }:
                    unlink_private_regular_file(
                        speaker_result_path,
                        "uncommitted speaker result",
                    )
                else:
                    raise ValueError("job has an unexpected speaker result")
            return status
        if status in {"cancelled", "failed"}:
            unlink_private_regular_file(result_path, "private transcript result")
            unlink_private_regular_file(
                speaker_result_path,
                "private speaker result",
            )
            return status
        if status not in {"server_processing", "complete", "partial"}:
            raise ValueError("non-processing job has an unexpected result")
        result = dict(read_json_file(result_path))
        validate_result_revision(
            result,
            projection,
            maximum_end_ms=capture_duration_ms(state.requests[job_id]),
        )
        declares_speaker_result = "speakerResultSha256" in result
        has_speaker_result = speaker_result_path.exists()
        if declares_speaker_result != has_speaker_result:
            raise ValueError("persisted joint result aggregate is incomplete")
        if declares_speaker_result != requires_speaker_result:
            raise ValueError("persisted speaker result differs from the frozen route")
        if status in {"complete", "partial"} and result.get("status") != status:
            raise ValueError("persisted result status differs")
        speaker_result: dict[str, object] | None = None
        if has_speaker_result:
            speaker_result = dict(read_json_file(speaker_result_path))
        if adapter is not None:
            if routing is None:
                raise ValueError("adapted result has no frozen route")
            adapter.validate_persisted_result_bundle(
                result,
                speaker_result,
                projection=projection,
                creation=state.requests[job_id],
                route=routing.route,
                maximum_end_ms=capture_duration_ms(state.requests[job_id]),
            )
        if speaker_result is not None:
            state.speaker_results[job_id] = speaker_result
        state.results[job_id] = result
        if status == "server_processing":
            self._reconcile_published_result_stage(
                state,
                job_id,
                result,
                speaker_result,
            )
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
        speaker_result: Mapping[str, object] | None,
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
            output_fingerprint_sha256=canonical_json_sha256(
                result_bundle_fingerprint(result, speaker_result)
            ),
            evidence={
                "resultRevision": result["revision"],
                "speakerResultRevision": (
                    None if speaker_result is None else speaker_result["revision"]
                ),
                "status": result["status"],
            },
        )
