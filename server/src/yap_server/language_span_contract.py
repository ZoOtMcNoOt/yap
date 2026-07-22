from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Mapping, Sequence, cast

from yap_server.language_tags import canonical_bcp47


LANGUAGE_SPAN_SCHEMA_VERSION = 1
LANGUAGE_SPAN_SAMPLE_RATE_HZ = 16_000
MAX_LANGUAGE_SPANS = 4_096
MAX_LANGUAGE_SPAN_SOURCE_SAMPLES = 4 * 60 * 60 * LANGUAGE_SPAN_SAMPLE_RATE_HZ + 15

_OPAQUE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_MODEL_REVISION = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_MODEL_ID_BYTES = 256


@dataclass(frozen=True, slots=True)
class ServerUtteranceLanguageObservation:
    """Text-language evidence attached to one finalized source-time window."""

    start_sample: int
    end_sample: int
    language_segments: Sequence[Mapping[str, object]]


def build_server_language_span_evidence(
    *,
    source_end_sample: int,
    provider_id: str,
    pool_id: str,
    model_id: str,
    model_revision: str,
    utterance_plan_sha256: str,
    utterances: Sequence[ServerUtteranceLanguageObservation],
) -> dict[str, object]:
    """Bind model language output to finalized utterance source windows.

    The server owns only the supplied utterance boundaries. A window containing
    mixed or incomplete text-language evidence is deliberately labeled ``und``;
    token tags never become invented within-utterance source boundaries.
    """

    spans: list[dict[str, object]] = []
    for index, utterance in enumerate(utterances):
        if not isinstance(utterance, ServerUtteranceLanguageObservation):
            raise ValueError("server utterance language observation is invalid")
        language, disposition = server_utterance_language_decision(
            utterance.language_segments
        )
        spans.append(
            {
                "startSample": utterance.start_sample,
                "endSample": utterance.end_sample,
                "languageBcp47": language,
                "decisionRevision": index + 1,
                "disposition": disposition,
                "componentRevision": model_revision,
                "decisionEvidence": None,
            }
        )

    evidence: dict[str, object] = {
        "schemaVersion": LANGUAGE_SPAN_SCHEMA_VERSION,
        "sampleRateHz": LANGUAGE_SPAN_SAMPLE_RATE_HZ,
        "sourceEndSample": source_end_sample,
        "boundaryAuthority": "serverUtterance",
        "providerId": provider_id,
        "poolId": pool_id,
        "modelId": model_id,
        "modelRevision": model_revision,
        "utterancePlanSha256": utterance_plan_sha256,
        "spans": spans,
    }
    validate_language_span_evidence(evidence)
    return evidence


def validate_language_span_evidence(
    value: object,
    *,
    expected_source_end_sample: int | None = None,
    expected_provider_id: str | None = None,
    expected_pool_id: str | None = None,
    expected_model_id: str | None = None,
    expected_model_revision: str | None = None,
    expected_utterance_plan_sha256: str | None = None,
) -> Mapping[str, object]:
    """Validate one exact, bounded source-time language evidence envelope."""

    fields = {
        "schemaVersion",
        "sampleRateHz",
        "sourceEndSample",
        "boundaryAuthority",
        "providerId",
        "poolId",
        "modelId",
        "modelRevision",
        "utterancePlanSha256",
        "spans",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError("language span evidence fields are invalid")
    source_end_sample = _bounded_int(
        value.get("sourceEndSample"),
        1,
        MAX_LANGUAGE_SPAN_SOURCE_SAMPLES,
        "language span source end",
    )
    provider_id = _opaque_id(value.get("providerId"), "language span provider")
    pool_id = _opaque_id(value.get("poolId"), "language span pool")
    model_id = _model_id(value.get("modelId"))
    model_revision = _model_revision(value.get("modelRevision"))
    plan_sha256 = _sha256(
        value.get("utterancePlanSha256"),
        "language span utterance plan",
    )
    if (
        value.get("schemaVersion") != LANGUAGE_SPAN_SCHEMA_VERSION
        or value.get("sampleRateHz") != LANGUAGE_SPAN_SAMPLE_RATE_HZ
        or value.get("boundaryAuthority") != "serverUtterance"
        or (
            expected_source_end_sample is not None
            and source_end_sample != expected_source_end_sample
        )
        or (expected_provider_id is not None and provider_id != expected_provider_id)
        or (expected_pool_id is not None and pool_id != expected_pool_id)
        or (expected_model_id is not None and model_id != expected_model_id)
        or (
            expected_model_revision is not None
            and model_revision != expected_model_revision
        )
        or (
            expected_utterance_plan_sha256 is not None
            and plan_sha256 != expected_utterance_plan_sha256
        )
    ):
        raise ValueError("language span evidence identity is invalid")

    raw_spans = value.get("spans")
    if (
        not isinstance(raw_spans, list)
        or not 1 <= len(raw_spans) <= MAX_LANGUAGE_SPANS
    ):
        raise ValueError("language spans are invalid")
    expected_start = 0
    for index, raw_span in enumerate(raw_spans):
        if not isinstance(raw_span, Mapping) or set(raw_span) != {
            "startSample",
            "endSample",
            "languageBcp47",
            "decisionRevision",
            "disposition",
            "componentRevision",
            "decisionEvidence",
        }:
            raise ValueError("language span fields are invalid")
        start_sample = _bounded_int(
            raw_span.get("startSample"),
            0,
            source_end_sample - 1,
            "language span start",
        )
        end_sample = _bounded_int(
            raw_span.get("endSample"),
            1,
            source_end_sample,
            "language span end",
        )
        language = canonical_bcp47(
            raw_span.get("languageBcp47"),
            "language span language",
        )
        disposition = raw_span.get("disposition")
        if (
            start_sample != expected_start
            or end_sample <= start_sample
            or raw_span.get("decisionRevision") != index + 1
            or raw_span.get("componentRevision") != model_revision
            or raw_span.get("decisionEvidence") is not None
            or (
                disposition == "serverDetected"
                and language == "und"
            )
            or (
                disposition == "serverUnknown"
                and language != "und"
            )
            or disposition not in {"serverDetected", "serverUnknown"}
        ):
            raise ValueError("language span content is invalid")
        expected_start = end_sample
    if expected_start != source_end_sample:
        raise ValueError("language spans do not cover source time")
    return value


def server_utterance_language_decision(
    language_segments: Sequence[Mapping[str, object]],
) -> tuple[str, str]:
    if (
        not isinstance(language_segments, Sequence)
        or isinstance(language_segments, (str, bytes, bytearray))
        or len(language_segments) > MAX_LANGUAGE_SPANS
    ):
        raise ValueError("server utterance language segments are invalid")
    detected: set[str] = set()
    has_nonempty_unknown = False
    for segment in language_segments:
        if not isinstance(segment, Mapping):
            raise ValueError("server utterance language segment is invalid")
        text = segment.get("text")
        status = segment.get("status")
        if not isinstance(text, str) or status not in {"detected", "unknown"}:
            raise ValueError("server utterance language segment is invalid")
        if not text:
            continue
        if status == "unknown":
            has_nonempty_unknown = True
            continue
        detected.add(
            canonical_bcp47(
                segment.get("languageBcp47"),
                "server utterance detected language",
            )
        )
    if len(detected) == 1 and not has_nonempty_unknown:
        return next(iter(detected)), "serverDetected"
    return "und", "serverUnknown"


def validate_language_segment_source_links(
    language_segments: object,
    language_spans: object,
) -> None:
    """Require every text segment to reference one coherent source window."""

    if (
        not isinstance(language_segments, list)
        or not isinstance(language_spans, list)
        or not 1 <= len(language_segments) <= MAX_LANGUAGE_SPANS
        or not 1 <= len(language_spans) <= MAX_LANGUAGE_SPANS
    ):
        raise ValueError("language segment source links are invalid")
    by_source_span: list[list[Mapping[str, object]]] = [
        [] for _ in range(len(language_spans))
    ]
    for segment in language_segments:
        if not isinstance(segment, Mapping):
            raise ValueError("language segment source links are invalid")
        source_span_index = _bounded_int(
            segment.get("sourceSpanIndex"),
            0,
            len(language_spans) - 1,
            "language segment source span index",
        )
        by_source_span[source_span_index].append(segment)
    for source_span_index, source_segments in enumerate(by_source_span):
        if not source_segments:
            raise ValueError("language source span is unreferenced")
        language, disposition = server_utterance_language_decision(source_segments)
        source_span = language_spans[source_span_index]
        if (
            not isinstance(source_span, Mapping)
            or source_span.get("languageBcp47") != language
            or source_span.get("disposition") != disposition
        ):
            raise ValueError("text and source language evidence differ")


def _bounded_int(value: object, minimum: int, maximum: int, field: str) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not minimum <= value <= maximum
    ):
        raise ValueError(f"{field} is invalid")
    return value


def _opaque_id(value: object, field: str) -> str:
    if not isinstance(value, str) or _OPAQUE_ID.fullmatch(value) is None:
        raise ValueError(f"{field} is invalid")
    return value


def _model_id(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value.encode("utf-8")) > _MAX_MODEL_ID_BYTES
        or not value.isascii()
        or any(not 0x21 <= ord(character) <= 0x7E for character in value)
    ):
        raise ValueError("language span model is invalid")
    return value


def _model_revision(value: object) -> str:
    if not isinstance(value, str) or _MODEL_REVISION.fullmatch(value) is None:
        raise ValueError("language span model revision is invalid")
    return value


def _sha256(value: object, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{field} identity is invalid")
    return cast(str, value)
