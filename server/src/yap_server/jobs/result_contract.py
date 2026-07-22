from __future__ import annotations

from typing import Mapping

from yap_server.alignment_contract import validate_alignment_payload
from yap_server.language_span_contract import (
    validate_language_segment_source_links,
    validate_language_span_evidence,
)
from yap_server.transcript_text import canonical_transcript

from .contract_values import (
    JOB_STATUSES,
    MAX_MODEL_PROVENANCE_CHARS,
    NONRETRYABLE_PERSISTED_ERROR_CODES,
    PERSISTED_ERROR_CODES,
    exact_keys,
    identifier,
    language_tag,
    mapping,
    text,
    utc_timestamp,
)


_MAX_LANGUAGE_SEGMENTS = 4_096
_MAX_RESULT_DURATION_MS = 4 * 60 * 60 * 1_000
_UNKNOWN_LANGUAGE_REASONS = frozenset(
    {
        "DISABLED_LANGUAGE_TAG",
        "EMPTY_TAGGED_TRANSCRIPT",
        "MISSING_LANGUAGE_TAG",
    }
)


def validate_persisted_projection(
    job_id: str,
    creation: Mapping[str, object],
    projection: Mapping[str, object],
) -> None:
    metadata = mapping(creation.get("metadata"), "metadata")
    status = text(projection.get("status"), "persisted projection.status")
    if status not in JOB_STATUSES:
        raise ValueError("persisted job status is invalid")

    keys = {
        "jobId",
        "sessionId",
        "displayName",
        "sessionMode",
        "sessionOrigin",
        "status",
        "route",
        "captureManifest",
        "createdAtUtc",
        "updatedAtUtc",
    }
    if status == "failed":
        keys.add("error")
    exact_keys(projection, keys, "persisted projection")

    if (
        projection.get("jobId") != job_id
        or projection.get("sessionId") != metadata.get("sessionId")
        or projection.get("displayName") != creation.get("displayName")
        or projection.get("sessionMode") != metadata.get("mode")
        or projection.get("sessionOrigin") != metadata.get("origin")
        or projection.get("route") != creation.get("route")
        or projection.get("captureManifest") != creation.get("captureManifest")
    ):
        raise ValueError("persisted job projection differs from creation")

    created_at = utc_timestamp(
        projection.get("createdAtUtc"),
        "persisted projection.createdAtUtc",
    )
    updated_at = utc_timestamp(
        projection.get("updatedAtUtc"),
        "persisted projection.updatedAtUtc",
    )
    if updated_at < created_at:
        raise ValueError("persisted job projection timestamps are invalid")

    if status != "failed":
        return
    error = mapping(projection.get("error"), "persisted projection.error")
    exact_keys(
        error,
        {"code", "message", "retryable", "requestId"},
        "persisted projection.error",
    )
    code = identifier(error.get("code"), 64, "persisted projection.error.code")
    message = text(error.get("message"), "persisted projection.error.message")
    retryable = error.get("retryable")
    expected_retryable = code not in NONRETRYABLE_PERSISTED_ERROR_CODES
    if (
        code not in PERSISTED_ERROR_CODES
        or len(message) > 512
        or not isinstance(retryable, bool)
        or retryable is not expected_retryable
        or error.get("requestId") != f"job-{job_id}"
    ):
        raise ValueError("persisted job error is invalid")


def validate_result_revision(
    result: Mapping[str, object],
    projection: Mapping[str, object],
    *,
    maximum_end_ms: int | None = None,
) -> None:
    result_fields = {
        "sessionId",
        "revision",
        "authority",
        "createdAtUtc",
        "captureManifestSha256",
        "previousResultSha256",
        "status",
        "language",
        "transcript",
        "alignedWords",
        "modelProvenance",
    }
    if "languageSegments" in result:
        result_fields.add("languageSegments")
    if "languageSpanEvidence" in result:
        result_fields.add("languageSpanEvidence")
    if "alignment" in result:
        result_fields.add("alignment")
    exact_keys(
        result,
        result_fields,
        "result revision",
    )
    capture_manifest = mapping(projection.get("captureManifest"), "captureManifest")
    transcript = canonical_transcript(result.get("transcript"), "result transcript")
    if (
        result.get("sessionId") != projection.get("sessionId")
        or result.get("revision") != 1
        or result.get("authority") != "server_authoritative"
        or result.get("captureManifestSha256") != capture_manifest.get("sha256")
        or result.get("previousResultSha256") is not None
        or result.get("status") not in {"complete", "partial"}
    ):
        raise ValueError("result revision identity or content is invalid")
    utc_timestamp(result.get("createdAtUtc"), "result createdAtUtc")

    if "alignment" not in result:
        if result.get("alignedWords") != []:
            raise ValueError("legacy result contains untyped alignment")
    else:
        alignment = mapping(result.get("alignment"), "result alignment")
        validate_alignment_payload(
            {
                **alignment,
                "alignedWords": result.get("alignedWords"),
            },
            transcript=transcript,
            maximum_end_ms=maximum_end_ms,
        )

    language = mapping(result.get("language"), "result language")
    exact_keys(language, {"languageBcp47", "confidence"}, "result language")
    language_tag(language.get("languageBcp47"), "result languageBcp47")
    confidence = language.get("confidence")
    if confidence is not None and (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not 0 <= confidence <= 1
    ):
        raise ValueError("result language confidence is invalid")
    provenance = result.get("modelProvenance")
    if not isinstance(provenance, list) or len(provenance) != 1:
        raise ValueError("result model provenance is invalid")
    model = mapping(provenance[0], "result model provenance")
    exact_keys(
        model,
        {"modelId", "revision", "calibrationRevision"},
        "result model provenance",
    )
    for field in ("modelId", "revision", "calibrationRevision"):
        if len(text(model.get(field), f"result {field}")) > MAX_MODEL_PROVENANCE_CHARS:
            raise ValueError("result model provenance is oversized")

    language_bcp47 = language.get("languageBcp47")
    if language_bcp47 == "und":
        evidence = validate_language_span_evidence(
            result.get("languageSpanEvidence"),
            expected_model_id=model.get("modelId"),
            expected_model_revision=model.get("revision"),
        )
        if maximum_end_ms is not None and max(
            1,
            round(evidence["sourceEndSample"] * 1_000 / 16_000),
        ) != maximum_end_ms:
            raise ValueError("result language span evidence differs from capture time")
        _validate_language_segments(
            result.get("languageSegments"),
            transcript,
            evidence["spans"],
        )
    elif "languageSegments" in result or "languageSpanEvidence" in result:
        raise ValueError("fixed-language result cannot contain dynamic language evidence")


def capture_duration_ms(creation: Mapping[str, object]) -> int:
    chunks = creation.get("chunks")
    if not isinstance(chunks, list) or not chunks:
        raise ValueError("job creation chunks are invalid")
    total = 0
    for raw_chunk in chunks:
        chunk = mapping(raw_chunk, "job creation chunk")
        duration_ms = chunk.get("durationMs")
        if (
            isinstance(duration_ms, bool)
            or not isinstance(duration_ms, int)
            or duration_ms < 1
        ):
            raise ValueError("job creation chunk duration is invalid")
        total += duration_ms
        if total > _MAX_RESULT_DURATION_MS:
            raise ValueError("job creation duration exceeds the result boundary")
    return total


def _validate_language_segments(
    value: object,
    transcript: str,
    language_spans: object,
) -> None:
    if not isinstance(value, list) or not 1 <= len(value) <= _MAX_LANGUAGE_SEGMENTS:
        raise ValueError("result language segments are invalid")
    if not isinstance(language_spans, list):
        raise ValueError("result language spans are invalid")
    rendered: list[str] = []
    for index, raw_segment in enumerate(value):
        segment = mapping(raw_segment, "result language segment")
        exact_keys(
            segment,
            {
                "index",
                "sourceSpanIndex",
                "text",
                "status",
                "languageBcp47",
                "rawLanguageTag",
                "reason",
            },
            "result language segment",
        )
        segment_text = canonical_transcript(
            segment.get("text"),
            "result language segment text",
        )
        if segment.get("index") != index:
            raise ValueError("result language segments are invalid")
        status = segment.get("status")
        language = segment.get("languageBcp47")
        raw_tag = segment.get("rawLanguageTag")
        reason = segment.get("reason")
        if status == "detected":
            if (
                not segment_text
                or not isinstance(language, str)
                or language != raw_tag
                or reason is not None
            ):
                raise ValueError("result language segments are invalid")
            language_tag(language, "result detected language")
        elif status == "unknown":
            if language is not None or reason not in _UNKNOWN_LANGUAGE_REASONS:
                raise ValueError("result language segments are invalid")
            if raw_tag is not None:
                language_tag(raw_tag, "result raw language tag")
            if reason == "MISSING_LANGUAGE_TAG" and raw_tag is not None:
                raise ValueError("result language segments are invalid")
            if reason == "DISABLED_LANGUAGE_TAG" and raw_tag is None:
                raise ValueError("result language segments are invalid")
            if reason == "EMPTY_TAGGED_TRANSCRIPT" and (
                raw_tag is None or segment_text
            ):
                raise ValueError("result language segments are invalid")
        else:
            raise ValueError("result language segments are invalid")
        if segment_text:
            rendered.append(segment_text)
    if " ".join(rendered) != transcript:
        raise ValueError("result language segments do not preserve transcript text")
    validate_language_segment_source_links(value, language_spans)
