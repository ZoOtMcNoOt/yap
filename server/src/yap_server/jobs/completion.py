from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import threading
from typing import Callable

from yap_server.alignment_contract import (
    COHERE_ATTENTION_ALIGNMENT_CANDIDATE_REVISION,
    AlignmentUnavailableReason,
    unavailable_alignment,
    validate_alignment_payload,
)
from yap_server.pools.batch_contract import (
    ProviderCapacityUnavailable,
    WorkerContainmentError,
)
from yap_server.transcript_text import canonical_transcript

from .artifacts import publish_json
from .contract_values import (
    MAX_MODEL_PROVENANCE_CHARS,
    mapping,
    text,
)
from .job_store import DurableJobState, RecordingJobStore
from .processing_input import BatchInputIntegrityError, BatchInputStorageError
from .result_contract import capture_duration_ms, validate_result_revision
from .stage_attempts import canonical_json_sha256, finish_stage, start_stage


_RESULT_COMPONENT_REVISION = "result-schema-1-alignment-v1"


class JobCompletionCoordinator:
    """Converges one worker future into a durable result or safe tombstone."""

    def __init__(
        self,
        *,
        storage_root: Path,
        state: DurableJobState,
        store: RecordingJobStore,
        futures: dict[str, object],
        completion_events: dict[str, threading.Event],
        lock: threading.RLock,
        now: Callable[[], str],
    ) -> None:
        self._storage_root = storage_root
        self._state = state
        self._store = store
        self._futures = futures
        self._completion_events = completion_events
        self._lock = lock
        self._now = now

    def finish_safely(
        self,
        job_id: str,
        language_bcp47: str,
        future: object,
        completion_event: threading.Event,
    ) -> None:
        try:
            self._finish(job_id, language_bcp47, future)
        except Exception:
            # Future callbacks are an outer trust boundary. Never let a storage
            # exception reach concurrent.futures' default callback logger,
            # which would print filesystem details. Preserve an already
            # published complete result for restart reconciliation; otherwise
            # converge to the existing generic retryable failure tombstone.
            try:
                with self._lock:
                    self._discard_future(job_id, future)
                    job = self._state.jobs.get(job_id)
                    if job is None or job.get("status") in {"complete", "partial"}:
                        return
                    if job_id not in self._state.cancelled and job.get("status") != "failed":
                        failed_at = self._now()
                        job["status"] = "failed"
                        job["updatedAtUtc"] = failed_at
                        job["error"] = {
                            "code": "SERVER_STORAGE_ERROR",
                            "message": "Private result storage did not complete safely.",
                            "retryable": True,
                            "requestId": f"job-{job_id}",
                        }
                        self._finish_latest_running_stage(
                            job_id,
                            state="failed",
                            retryable=True,
                            reason="SERVER_STORAGE_ERROR",
                            completed_at_utc=failed_at,
                        )
                    self._store.persist(self._state, job_id)
            except Exception:
                pass
        finally:
            completion_event.set()
            with self._lock:
                if self._completion_events.get(job_id) is completion_event:
                    self._completion_events.pop(job_id, None)

    def _finish(self, job_id: str, language_bcp47: str, future: object) -> None:
        try:
            payload = future.result()
        except WorkerContainmentError:
            self._mark_containment_unverified(job_id, future)
            return
        except ProviderCapacityUnavailable:
            self._mark_failed_unless_cancelled(
                job_id,
                future,
                code="SERVER_BUSY",
                message="Server capacity is temporarily unavailable.",
            )
            return
        except BatchInputIntegrityError:
            self._mark_failed_unless_cancelled(
                job_id,
                future,
                code="ASR_INPUT_INTEGRITY_FAILED",
                message="The admitted audio no longer matches its immutable evidence.",
                retryable=False,
            )
            return
        except BatchInputStorageError:
            self._mark_failed_unless_cancelled(
                job_id,
                future,
                code="SERVER_STORAGE_ERROR",
                message="Private input storage did not complete safely.",
            )
            return
        except Exception:
            self._mark_failed_unless_cancelled(
                job_id,
                future,
                code="ASR_WORKER_FAILED",
                message="The private ASR worker did not complete the job.",
            )
            return
        try:
            result, created_at, asr_output_sha256 = self._result_from_worker(
                job_id,
                language_bcp47,
                payload,
                future,
            )
        except (KeyError, TypeError, ValueError):
            self._mark_failed_unless_cancelled(
                job_id,
                future,
                code="ASR_RESULT_INVALID",
                message="The private ASR worker returned an invalid result.",
            )
            return
        if result is None:
            return
        if not self._record_publication_intent(
            job_id,
            result,
            created_at,
            asr_output_sha256,
        ):
            return
        result_path = self._storage_root / "jobs" / job_id / "result-revision.json"
        try:
            publish_json(result_path, result)
        except OSError:
            self._mark_failed_unless_cancelled(
                job_id,
                future,
                code="ASR_RESULT_PUBLISH_FAILED",
                message="The private ASR result could not be stored safely.",
                stage="result_publication",
                retryable=False,
            )
            return
        with self._lock:
            if job_id in self._state.cancelled:
                self._discard_future(job_id, future)
                self._cancel_running_stages(job_id, created_at)
                self._store.purge_private_audio(self._state, job_id)
                return
            self._state.results[job_id] = result
            job = self._state.jobs[job_id]
            job["status"] = "complete"
            job["updatedAtUtc"] = created_at
            self._finish_running_stage(
                job_id,
                "result_publication",
                state="succeeded",
                retryable=False,
                reason=None,
                completed_at_utc=created_at,
                output_fingerprint_sha256=canonical_json_sha256(result),
                evidence={"resultRevision": 1, "status": result["status"]},
            )
            self._discard_future(job_id, future)
            self._store.persist(self._state, job_id)

    def _result_from_worker(
        self,
        job_id: str,
        language_bcp47: str,
        payload: object,
        future: object,
    ) -> tuple[dict[str, object] | None, str, str]:
        worker_payload = mapping(payload, "worker result")
        transcript = mapping(worker_payload.get("transcript"), "worker transcript")
        model = mapping(worker_payload.get("model"), "worker model")
        transcript_text = canonical_transcript(
            transcript.get("text"),
            "worker transcript.text",
        )
        raw_alignment = worker_payload.get("alignment")
        alignment = mapping(
            (
                unavailable_alignment(
                    AlignmentUnavailableReason.RUNTIME_FAILED,
                    component_revision=COHERE_ATTENTION_ALIGNMENT_CANDIDATE_REVISION,
                )
                if raw_alignment is None
                else raw_alignment
            ),
            "worker alignment",
        )
        has_language_segments = "languageSegments" in transcript
        language_segments = transcript.get("languageSegments")
        has_language_span_evidence = "languageSpanEvidence" in transcript
        language_span_evidence = transcript.get("languageSpanEvidence")
        model_id = text(model.get("id"), "worker model.id")
        model_revision = text(model.get("revision"), "worker model.revision")
        if (
            len(model_id) > MAX_MODEL_PROVENANCE_CHARS
            or len(model_revision) > MAX_MODEL_PROVENANCE_CHARS
        ):
            raise ValueError("worker model identity is oversized")
        created_at = self._now()
        with self._lock:
            if job_id in self._state.cancelled:
                self._discard_future(job_id, future)
                self._cancel_running_stages(job_id, created_at)
                self._store.purge_private_audio(self._state, job_id)
                return None, created_at, canonical_json_sha256({"cancelled": True})
            job = self._state.jobs[job_id]
            creation = self._state.requests[job_id]
            maximum_end_ms = capture_duration_ms(creation)
            validate_alignment_payload(
                alignment,
                transcript=transcript_text,
                maximum_end_ms=maximum_end_ms,
            )
            aligned_words = deepcopy(alignment["alignedWords"])
            alignment_summary = {
                "status": alignment["status"],
                "reason": alignment["reason"],
                "componentRevision": alignment["componentRevision"],
            }
            routing = self._state.asr_routing[job_id]
            if routing is None:
                raise RuntimeError("active worker result has no frozen ASR route")
            dynamic_result = routing.route.execution_mode == "dynamicBatch"
            if (
                dynamic_result
                and (
                    language_bcp47 != "und"
                    or not has_language_segments
                    or not has_language_span_evidence
                )
            ) or (
                not dynamic_result
                and (
                    language_bcp47 == "und"
                    or has_language_segments
                    or has_language_span_evidence
                )
            ):
                raise ValueError("worker language evidence differs from its frozen route")
            capture_manifest = mapping(job["captureManifest"], "captureManifest")
            result: dict[str, object] = {
                "sessionId": job["sessionId"],
                "revision": 1,
                "authority": "server_authoritative",
                "createdAtUtc": created_at,
                "captureManifestSha256": capture_manifest["sha256"],
                "previousResultSha256": None,
                "status": "complete",
                "language": {
                    "languageBcp47": language_bcp47,
                    "confidence": None,
                },
                "transcript": transcript_text,
                "alignment": alignment_summary,
                "alignedWords": aligned_words,
                "modelProvenance": [
                    {
                        "modelId": model_id,
                        "revision": model_revision,
                        "calibrationRevision": "asr-not-applicable",
                    }
                ],
            }
            if dynamic_result:
                result["languageSegments"] = deepcopy(language_segments)
                result["languageSpanEvidence"] = deepcopy(language_span_evidence)
            validate_result_revision(
                result,
                job,
                maximum_end_ms=maximum_end_ms,
            )
        asr_output_sha256 = canonical_json_sha256(
            {
                "languageBcp47": language_bcp47,
                "transcript": transcript_text,
                "modelId": model_id,
                "modelRevision": model_revision,
                "languageSegments": (
                    deepcopy(language_segments) if dynamic_result else None
                ),
                "languageSpanEvidence": (
                    deepcopy(language_span_evidence) if dynamic_result else None
                ),
            }
        )
        return result, created_at, asr_output_sha256

    def _record_publication_intent(
        self,
        job_id: str,
        result: dict[str, object],
        created_at: str,
        asr_output_sha256: str,
    ) -> bool:
        with self._lock:
            if job_id in self._state.cancelled:
                self._cancel_running_stages(job_id, created_at)
                self._store.purge_private_audio(self._state, job_id)
                return False
            routing = self._state.asr_routing[job_id]
            if routing is None:
                raise RuntimeError("active publication has no frozen ASR route")
            previous_attempts = deepcopy(self._state.stage_attempts[job_id])
            try:
                self._finish_running_stage(
                    job_id,
                    "asr",
                    state="succeeded",
                    retryable=False,
                    reason=None,
                    completed_at_utc=created_at,
                    output_fingerprint_sha256=asr_output_sha256,
                    evidence={
                        "resultShape": (
                            "dynamic_language_spans_v1"
                            if "languageSpanEvidence" in result
                            else "raw_transcript_v1"
                        ),
                        "executionMode": routing.route.execution_mode,
                    },
                )
                alignment = mapping(result["alignment"], "result alignment")
                component_revision = text(
                    alignment["componentRevision"],
                    "result alignment component revision",
                )
                alignment_fingerprint = canonical_json_sha256(
                    {
                        "alignment": alignment,
                        "alignedWords": result["alignedWords"],
                    }
                )
                alignment_attempt = start_stage(
                    self._state.stage_attempts[job_id],
                    stage="alignment",
                    input_fingerprint_sha256=asr_output_sha256,
                    component_id=(
                        "cohere-attention-alignment"
                        if component_revision.startswith("cohere-attention-")
                        else "alignment-gate"
                    ),
                    component_revision=component_revision,
                    started_at_utc=created_at,
                )
                if alignment["status"] == "available":
                    finish_stage(
                        self._state.stage_attempts[job_id],
                        stage="alignment",
                        attempt=alignment_attempt,
                        state="succeeded",
                        completed_at_utc=created_at,
                        retryable=False,
                        output_fingerprint_sha256=alignment_fingerprint,
                        evidence={
                            "alignedWords": len(result["alignedWords"]),
                            "componentRevision": component_revision,
                        },
                    )
                else:
                    finish_stage(
                        self._state.stage_attempts[job_id],
                        stage="alignment",
                        attempt=alignment_attempt,
                        state="unavailable",
                        completed_at_utc=created_at,
                        retryable=False,
                        output_fingerprint_sha256=alignment_fingerprint,
                        reason=text(
                            alignment["reason"],
                            "result alignment unavailable reason",
                        ),
                        evidence={
                            "alignedWords": 0,
                            "componentRevision": component_revision,
                        },
                    )
                capture_manifest = self._state.jobs[job_id]["captureManifest"]
                publication_input = canonical_json_sha256(
                    {
                        "asrOutputSha256": asr_output_sha256,
                        "captureManifest": capture_manifest,
                        "alignmentSha256": alignment_fingerprint,
                        "resultSchemaVersion": 1,
                    }
                )
                start_stage(
                    self._state.stage_attempts[job_id],
                    stage="result_publication",
                    input_fingerprint_sha256=publication_input,
                    component_id="yap-result-contract",
                    component_revision=_RESULT_COMPONENT_REVISION,
                    started_at_utc=created_at,
                )
                self._store.persist(self._state, job_id)
            except BaseException:
                self._state.stage_attempts[job_id] = previous_attempts
                raise
            return True

    def _mark_containment_unverified(self, job_id: str, future: object) -> None:
        failed_at = self._now()
        with self._lock:
            self._discard_future(job_id, future)
            self._state.cleanup_unverified.add(job_id)
            job = self._state.jobs[job_id]
            job["status"] = "failed"
            job["updatedAtUtc"] = failed_at
            job["error"] = {
                "code": "ASR_CLEANUP_UNVERIFIED",
                "message": "The private ASR worker cleanup could not be verified.",
                "retryable": True,
                "requestId": f"job-{job_id}",
            }
            self._finish_running_stage(
                job_id,
                "asr",
                state="failed",
                retryable=True,
                reason="ASR_CLEANUP_UNVERIFIED",
                completed_at_utc=failed_at,
            )
            self._store.persist(self._state, job_id)

    def _mark_failed_unless_cancelled(
        self,
        job_id: str,
        future: object,
        *,
        code: str,
        message: str,
        stage: str = "asr",
        retryable: bool = True,
    ) -> None:
        failed_at = self._now()
        with self._lock:
            self._discard_future(job_id, future)
            if job_id in self._state.cancelled:
                self._cancel_running_stages(job_id, failed_at)
                self._store.purge_private_audio(self._state, job_id)
                return
            job = self._state.jobs[job_id]
            job["status"] = "failed"
            job["updatedAtUtc"] = failed_at
            job["error"] = {
                "code": code,
                "message": message,
                "retryable": retryable,
                "requestId": f"job-{job_id}",
            }
            self._finish_running_stage(
                job_id,
                stage,
                state="failed",
                retryable=retryable,
                reason=code,
                completed_at_utc=failed_at,
            )
            if retryable:
                self._store.persist(self._state, job_id)
            else:
                self._store.purge_private_audio(self._state, job_id)

    def _finish_latest_running_stage(
        self,
        job_id: str,
        *,
        state: str,
        retryable: bool,
        reason: str | None,
        completed_at_utc: str,
    ) -> None:
        running = next(
            (
                attempt
                for attempt in reversed(self._state.stage_attempts[job_id])
                if attempt["state"] == "running"
            ),
            None,
        )
        if running is not None:
            self._finish_running_stage(
                job_id,
                str(running["stage"]),
                state=state,
                retryable=retryable,
                reason=reason,
                completed_at_utc=completed_at_utc,
            )

    def _finish_running_stage(
        self,
        job_id: str,
        stage: str,
        *,
        state: str,
        retryable: bool,
        reason: str | None,
        completed_at_utc: str,
        output_fingerprint_sha256: str | None = None,
        evidence: object | None = None,
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
            output_fingerprint_sha256=output_fingerprint_sha256,
            reason=reason,
            evidence=evidence,
        )

    def _cancel_running_stages(self, job_id: str, cancelled_at: str) -> None:
        for stage in ("asr", "alignment", "result_publication"):
            self._finish_running_stage(
                job_id,
                stage,
                state="cancelled",
                retryable=False,
                reason="JOB_CANCELLED",
                completed_at_utc=cancelled_at,
            )

    def _discard_future(self, job_id: str, future: object) -> None:
        if self._futures.get(job_id) is future:
            self._futures.pop(job_id, None)
