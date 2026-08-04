"""Typed source-bound speaker-capacity disclosures."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .contract import (
    MEETING_SESSION_SPEAKER_LIMIT,
    SPEAKER_CAPACITY_REACHED_CODE,
    SOURCE_TIME_EPOCH_SAMPLES,
    TIRON_DECODE_SPEAKER_LIMIT,
)


@dataclass(frozen=True, slots=True)
class SpeakerCapacityDegradation:
    scope: str
    start_sample: int
    end_sample: int
    observed_speaker_count: int
    speaker_limit: int


def speaker_capacity_degradation_to_wire(
    degradation: SpeakerCapacityDegradation | None,
) -> dict[str, object] | None:
    if degradation is None:
        return None
    return {
        "code": SPEAKER_CAPACITY_REACHED_CODE,
        "scope": degradation.scope,
        "startSample": degradation.start_sample,
        "endSample": degradation.end_sample,
        "observedSpeakerCount": degradation.observed_speaker_count,
        "speakerLimit": degradation.speaker_limit,
    }


def validate_speaker_capacity_degradation(
    value: object,
    *,
    source_frame_count: int,
) -> dict[str, object] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or set(value) != {
        "code",
        "scope",
        "startSample",
        "endSample",
        "observedSpeakerCount",
        "speakerLimit",
    }:
        raise ValueError("speaker capacity degradation fields are invalid")
    start = value["startSample"]
    end = value["endSample"]
    observed = value["observedSpeakerCount"]
    limit = value["speakerLimit"]
    if (
        value["code"] != SPEAKER_CAPACITY_REACHED_CODE
        or not _is_int(start)
        or not _is_int(end)
        or not _is_int(observed)
        or not _is_int(limit)
        or start < 0
        or end <= start
        or end > source_frame_count
        or observed != limit
    ):
        raise ValueError("speaker capacity degradation is invalid")
    scope = value["scope"]
    if scope == "decode_window":
        if (
            limit != TIRON_DECODE_SPEAKER_LIMIT
            or start % SOURCE_TIME_EPOCH_SAMPLES != 0
            or end != min(source_frame_count, start + SOURCE_TIME_EPOCH_SAMPLES)
        ):
            raise ValueError("decode-window speaker capacity is invalid")
    elif scope == "meeting":
        if (
            limit != MEETING_SESSION_SPEAKER_LIMIT
            or start != 0
            or end != source_frame_count
        ):
            raise ValueError("meeting speaker capacity is invalid")
    else:
        raise ValueError("speaker capacity scope is invalid")
    return dict(value)


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)
