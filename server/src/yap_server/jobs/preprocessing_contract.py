from __future__ import annotations

import json
import re
from typing import Mapping

from .contract_values import exact_keys, integer_between, mapping, valid_sha256


PREPROCESSING_EVIDENCE_SCHEMA_VERSION = 1
SAMPLE_RATE_HZ = 16_000
SAMPLES_PER_MILLISECOND = SAMPLE_RATE_HZ // 1_000
MAX_SOURCE_SAMPLES = SAMPLE_RATE_HZ * 4 * 60 * 60
MAX_VAD_INTERVALS = 4_096
MAX_PREPROCESSING_EVIDENCE_BYTES = 512 * 1_024

_COMPONENT_TEXT = re.compile(r"^[A-Za-z0-9_.\-/:]+$")
_ERROR_CODE = re.compile(r"^[A-Za-z0-9_.\-]+$")


def validate_preprocessing_evidence(
    value: object,
    *,
    output_sample_count: int,
) -> None:
    evidence = mapping(value, "preprocessingEvidence")
    exact_keys(
        evidence,
        {"schemaVersion", "normalization", "vad"},
        "preprocessingEvidence",
    )
    if evidence.get("schemaVersion") != PREPROCESSING_EVIDENCE_SCHEMA_VERSION:
        raise ValueError("unsupported preprocessing evidence schema")
    encoded = json.dumps(
        evidence,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if len(encoded) > MAX_PREPROCESSING_EVIDENCE_BYTES:
        raise ValueError("preprocessing evidence exceeds its byte limit")

    source_sample_count = _validate_normalization(
        evidence.get("normalization"),
        output_sample_count=output_sample_count,
    )
    _validate_vad(
        evidence.get("vad"),
        source_sample_count=source_sample_count,
    )


def _validate_normalization(
    value: object,
    *,
    output_sample_count: int,
) -> int:
    normalization = mapping(value, "preprocessingEvidence.normalization")
    exact_keys(
        normalization,
        {
            "status",
            "componentId",
            "componentRevision",
            "method",
            "inputSourceSha256",
            "sourcePcmSha256",
            "outputPcmSha256",
            "audioCodec",
            "sampleRateHz",
            "channels",
            "sourceSampleCount",
            "outputSampleCount",
            "paddingSamples",
            "gainAppliedMilliDb",
            "samplesModified",
            "sourceTimePreserved",
        },
        "preprocessingEvidence.normalization",
    )
    source_samples = normalization.get("sourceSampleCount")
    declared_output_samples = normalization.get("outputSampleCount")
    padding_samples = normalization.get("paddingSamples")
    if (
        normalization.get("status") != "complete"
        or normalization.get("componentId") != "yap-imported-audio-normalizer"
        or normalization.get("componentRevision") != "canonical-pcm16-normalization-v1"
        or normalization.get("method") != "canonical_pcm16_identity"
        or not valid_sha256(normalization.get("inputSourceSha256"))
        or not valid_sha256(normalization.get("sourcePcmSha256"))
        or not valid_sha256(normalization.get("outputPcmSha256"))
        or normalization.get("audioCodec") != "pcm_s16le"
        or normalization.get("sampleRateHz") != SAMPLE_RATE_HZ
        or normalization.get("channels") != 1
        or not integer_between(source_samples, 1, MAX_SOURCE_SAMPLES)
        or not integer_between(declared_output_samples, 1, MAX_SOURCE_SAMPLES)
        or declared_output_samples != output_sample_count
        or not integer_between(padding_samples, 0, SAMPLES_PER_MILLISECOND - 1)
        or source_samples + padding_samples != declared_output_samples
        or normalization.get("gainAppliedMilliDb") != 0
        or normalization.get("samplesModified") != 0
        or normalization.get("sourceTimePreserved") is not True
    ):
        raise ValueError("normalization evidence differs from canonical PCM output")
    return source_samples


def _validate_vad(value: object, *, source_sample_count: int) -> None:
    vad = mapping(value, "preprocessingEvidence.vad")
    status = vad.get("status")
    expected_keys = {"status", "component", "sourceSampleCount", "intervals"}
    if status == "error":
        expected_keys.add("errorCode")
    exact_keys(vad, expected_keys, "preprocessingEvidence.vad")
    _validate_component(vad.get("component"))
    intervals = vad.get("intervals")
    if (
        vad.get("sourceSampleCount") != source_sample_count
        or not isinstance(intervals, list)
        or len(intervals) > MAX_VAD_INTERVALS
    ):
        raise ValueError("VAD evidence differs from the normalized source")
    if status == "complete":
        if "errorCode" in vad:
            raise ValueError("complete VAD evidence cannot contain an error")
    elif status == "error":
        error_code = vad.get("errorCode")
        if intervals or not _valid_error_code(error_code):
            raise ValueError("failed VAD evidence must contain one bounded error code")
    else:
        raise ValueError("VAD evidence status is invalid")

    previous_end = 0
    for index, value in enumerate(intervals):
        interval = mapping(value, f"preprocessingEvidence.vad.intervals[{index}]")
        exact_keys(
            interval,
            {"startSample", "endSampleExclusive", "startMs", "endMs"},
            f"preprocessingEvidence.vad.intervals[{index}]",
        )
        start_sample = interval.get("startSample")
        end_sample = interval.get("endSampleExclusive")
        if (
            not integer_between(start_sample, 0, source_sample_count)
            or not integer_between(end_sample, 1, source_sample_count)
            or start_sample >= end_sample
            or start_sample < previous_end
            or interval.get("startMs") != start_sample // SAMPLES_PER_MILLISECOND
            or interval.get("endMs")
            != (end_sample + SAMPLES_PER_MILLISECOND - 1)
            // SAMPLES_PER_MILLISECOND
        ):
            raise ValueError("VAD intervals are invalid or overlap")
        previous_end = end_sample


def _validate_component(value: object) -> None:
    component = mapping(value, "preprocessingEvidence.vad.component")
    exact_keys(
        component,
        {"id", "revision", "modelId", "modelRevision", "artifactSha256"},
        "preprocessingEvidence.vad.component",
    )
    for field, maximum in (
        ("id", 128),
        ("revision", 128),
        ("modelId", 256),
        ("modelRevision", 256),
    ):
        if not _valid_component_text(component.get(field), maximum):
            raise ValueError(f"VAD component {field} is invalid")
    if not valid_sha256(component.get("artifactSha256")):
        raise ValueError("VAD component artifact identity is invalid")


def _valid_component_text(value: object, maximum: int) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= maximum
        and _COMPONENT_TEXT.fullmatch(value) is not None
    )


def _valid_error_code(value: object) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= 64
        and _ERROR_CODE.fullmatch(value) is not None
    )
