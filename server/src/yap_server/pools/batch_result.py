from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

from yap_server.alignment_contract import validate_alignment_payload
from yap_server.language_tags import canonical_bcp47
from yap_server.language_span_contract import (
    validate_language_segment_source_links,
    validate_language_span_evidence,
)
from yap_server.pools.batch_contract import BatchAsrJob, WorkerExecutionError
from yap_server.pools.model_lock import ModelPoolLock
from yap_server.transcript_text import canonical_transcript


_MAX_LANGUAGE_SEGMENTS = 4_096
_UNKNOWN_LANGUAGE_REASONS = frozenset(
    {
        "DISABLED_LANGUAGE_TAG",
        "EMPTY_TAGGED_TRANSCRIPT",
        "MISSING_LANGUAGE_TAG",
    }
)


def validate_result(
    payload: object,
    job: BatchAsrJob,
    lock: ModelPoolLock,
) -> None:
    if not isinstance(payload, dict):
        raise WorkerExecutionError("isolated ASR worker result must be an object")
    if set(payload) != {
        "schemaVersion",
        "jobId",
        "model",
        "audio",
        "transcript",
        "alignment",
        "runtime",
    }:
        raise WorkerExecutionError("isolated ASR worker result shape is invalid")
    if payload.get("schemaVersion") != 1 or payload.get("jobId") != job.job_id:
        raise WorkerExecutionError("isolated ASR worker result identity is invalid")
    model = payload.get("model")
    if not isinstance(model, dict) or (
        model.get("poolId") != lock.pool_id
        or model.get("id") != lock.model_id
        or model.get("revision") != lock.model_revision
    ):
        raise WorkerExecutionError("isolated ASR worker model identity is invalid")
    audio = payload.get("audio")
    duration_ms = audio.get("durationMs") if isinstance(audio, dict) else None
    if (
        not isinstance(audio, dict)
        or audio.get("sha256") != job.input_sha256
        or audio.get("sampleRateHz") != 16000
        or not isinstance(duration_ms, int)
        or isinstance(duration_ms, bool)
        or duration_ms <= 0
    ):
        raise WorkerExecutionError("isolated ASR worker audio identity is invalid")
    transcript = payload.get("transcript")
    if not isinstance(transcript, dict):
        raise WorkerExecutionError("isolated ASR worker transcript is invalid")
    expected_transcript_fields = {"text", "language", "punctuation"}
    if job.route.execution_mode == "dynamicBatch":
        expected_transcript_fields.update(
            {"languageSegments", "languageSpanEvidence"}
        )
    if set(transcript) != expected_transcript_fields:
        raise WorkerExecutionError("isolated ASR worker transcript is invalid")
    try:
        transcript_text = canonical_transcript(
            transcript.get("text"),
            "isolated ASR worker transcript.text",
        )
    except ValueError as error:
        raise WorkerExecutionError(
            "isolated ASR worker transcript is invalid"
        ) from error
    if (
        transcript.get("language") != job.route.provider_language
        or transcript.get("punctuation") is not job.punctuation
    ):
        raise WorkerExecutionError("isolated ASR worker transcript is invalid")
    if job.route.execution_mode == "dynamicBatch":
        if job.utterance_plan_sha256 is None:
            raise WorkerExecutionError(
                "dynamic ASR worker result has no utterance plan identity"
            )
        try:
            language_span_evidence = validate_language_span_evidence(
                transcript.get("languageSpanEvidence"),
                expected_provider_id=job.route.provider_id,
                expected_pool_id=lock.pool_id,
                expected_model_id=lock.model_id,
                expected_model_revision=lock.model_revision,
                expected_utterance_plan_sha256=job.utterance_plan_sha256,
            )
        except ValueError as error:
            raise WorkerExecutionError(
                "dynamic ASR language span evidence is invalid"
            ) from error
        source_end_sample = language_span_evidence["sourceEndSample"]
        if max(1, round(source_end_sample * 1_000 / 16_000)) != duration_ms:
            raise WorkerExecutionError(
                "dynamic ASR language span evidence differs from the input"
            )
        _validate_dynamic_segments(
            transcript.get("languageSegments"),
            transcript_text=transcript_text,
            lock=lock,
            language_spans=language_span_evidence["spans"],
        )
    elif "languageSegments" in transcript or "languageSpanEvidence" in transcript:
        raise WorkerExecutionError(
            "fixed ASR worker result cannot contain dynamic language evidence"
        )
    alignment = payload.get("alignment")
    try:
        validate_alignment_payload(
            alignment,
            transcript=transcript_text,
            maximum_end_ms=duration_ms,
        )
    except ValueError as error:
        raise WorkerExecutionError(
            "isolated ASR worker alignment is invalid"
        ) from error
    if (
        isinstance(alignment, dict)
        and alignment.get("status") == "available"
        and (lock.pool_id != "cohere-batch" or job.route.provider_language != "en")
    ):
        raise WorkerExecutionError(
            "isolated ASR worker advertised unsupported alignment"
        )
    runtime = payload.get("runtime")
    python_version = runtime.get("pythonVersion") if isinstance(runtime, dict) else None
    if (
        not isinstance(runtime, dict)
        or runtime.get("device") != "cuda"
        or runtime.get("torchVersion") != lock.runtime_torch_version
        or runtime.get("torchCudaVersion") != lock.runtime_torch_cuda_version
        or runtime.get("overlayPackages") != dict(lock.runtime_overlay_packages)
        or (
            lock.pool_id == "nemotron-batch"
            and runtime.get("dtype") != "bfloat16"
        )
        or not isinstance(python_version, str)
        or python_version.split(".")[:2] != lock.runtime_python_version.split(".")
    ):
        raise WorkerExecutionError("isolated ASR worker runtime identity is invalid")


def _validate_dynamic_segments(
    value: object,
    *,
    transcript_text: str,
    lock: ModelPoolLock,
    language_spans: object,
) -> None:
    if (
        not isinstance(value, list)
        or not 1 <= len(value) <= _MAX_LANGUAGE_SEGMENTS
    ):
        raise WorkerExecutionError("dynamic ASR language segments are invalid")
    if not isinstance(language_spans, list):
        raise WorkerExecutionError("dynamic ASR language spans are invalid")
    rendered: list[str] = []
    for index, raw_segment in enumerate(value):
        if not isinstance(raw_segment, dict) or set(raw_segment) != {
            "index",
            "sourceSpanIndex",
            "text",
            "status",
            "languageBcp47",
            "rawLanguageTag",
            "reason",
        }:
            raise WorkerExecutionError("dynamic ASR language segments are invalid")
        try:
            segment_text = canonical_transcript(
                raw_segment.get("text"),
                "dynamic ASR segment text",
            )
        except ValueError as error:
            raise WorkerExecutionError(
                "dynamic ASR language segments are invalid"
            ) from error
        if raw_segment.get("index") != index:
            raise WorkerExecutionError("dynamic ASR language segments are invalid")
        status = raw_segment.get("status")
        language = raw_segment.get("languageBcp47")
        raw_tag = raw_segment.get("rawLanguageTag")
        reason = raw_segment.get("reason")
        if status == "detected":
            if (
                not segment_text
                or not isinstance(language, str)
                or language != raw_tag
                or language not in lock.supported_languages
                or language == "auto"
                or reason is not None
            ):
                raise WorkerExecutionError("dynamic ASR language segments are invalid")
            try:
                canonical_bcp47(language, "dynamic ASR detected language")
            except ValueError as error:
                raise WorkerExecutionError(
                    "dynamic ASR language segments are invalid"
                ) from error
        elif status == "unknown":
            if language is not None or reason not in _UNKNOWN_LANGUAGE_REASONS:
                raise WorkerExecutionError("dynamic ASR language segments are invalid")
            if raw_tag is not None:
                try:
                    canonical_bcp47(raw_tag, "dynamic ASR raw language tag")
                except ValueError as error:
                    raise WorkerExecutionError(
                        "dynamic ASR language segments are invalid"
                    ) from error
            if reason == "MISSING_LANGUAGE_TAG" and raw_tag is not None:
                raise WorkerExecutionError("dynamic ASR language segments are invalid")
            if reason == "DISABLED_LANGUAGE_TAG" and (
                raw_tag is None or raw_tag in lock.supported_languages
            ):
                raise WorkerExecutionError("dynamic ASR language segments are invalid")
            if reason == "EMPTY_TAGGED_TRANSCRIPT" and (raw_tag is None or segment_text):
                raise WorkerExecutionError("dynamic ASR language segments are invalid")
        else:
            raise WorkerExecutionError("dynamic ASR language segments are invalid")
        if segment_text:
            rendered.append(segment_text)
    if " ".join(rendered) != transcript_text:
        raise WorkerExecutionError("dynamic ASR language segments are invalid")
    try:
        validate_language_segment_source_links(value, language_spans)
    except ValueError as error:
        raise WorkerExecutionError(
            "dynamic ASR text and source language evidence differ"
        ) from error


def publish_result(path: Path, payload: dict[str, object]) -> None:
    destination = path.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=destination.parent,
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            json.dump(
                payload,
                temporary,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, destination)
        temporary_name = None
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)
