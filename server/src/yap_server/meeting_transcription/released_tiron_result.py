"""Strict validation for one public Tiron whole-source inference result."""

from __future__ import annotations

import json
import math
import re
from typing import Mapping

from yap_server.limits import MAX_TRANSCRIPT_BYTES
from yap_server.pools import pcm_audio

from .contract import (
    MAX_MEETING_SEGMENT_COUNT,
    TIRON_DECODE_SPEAKER_LIMIT,
    is_tiron_speaker_id,
    maximum_upstream_window_count,
)


_UPSTREAM_RESULT_KEYS = {
    "duration",
    "language",
    "speakers",
    "segments",
    "num_chunks",
    "elapsed_s",
    "two_pass",
}
_UPSTREAM_SEGMENT_KEYS = {"speaker", "start", "end", "text"}
_MAX_DIAGNOSTIC_BYTES = 64 * 1024
_LANGUAGE = re.compile(r"^[A-Za-z][A-Za-z-]{0,34}$")


def validate_released_tiron_result(
    value: object,
    audio: pcm_audio.PcmAudio,
) -> dict[str, object]:
    result = _exact_mapping(value, _UPSTREAM_RESULT_KEYS, "Tiron result")
    source_duration = audio.frame_count / audio.sample_rate
    duration = _finite_number(result["duration"], "Tiron duration")
    if abs(duration - source_duration) > 0.011:
        raise ValueError("Tiron duration differs from the canonical source")

    language = result["language"]
    if not isinstance(language, str) or _LANGUAGE.fullmatch(language) is None:
        raise ValueError("Tiron language is invalid")
    raw_speakers = result["speakers"]
    if (
        not isinstance(raw_speakers, list)
        or len(raw_speakers) > TIRON_DECODE_SPEAKER_LIMIT
        or any(not is_tiron_speaker_id(item) for item in raw_speakers)
        or raw_speakers != sorted(set(raw_speakers))
    ):
        raise ValueError("Tiron speakers are invalid")

    raw_segments = result["segments"]
    if (
        not isinstance(raw_segments, list)
        or len(raw_segments) > MAX_MEETING_SEGMENT_COUNT
    ):
        raise ValueError("Tiron segments exceed the bounded contract")
    segments: list[dict[str, object]] = []
    transcript_bytes = 0
    previous_start = -1
    observed_speakers: set[str] = set()
    for index, raw_segment in enumerate(raw_segments):
        segment = _exact_mapping(
            raw_segment,
            _UPSTREAM_SEGMENT_KEYS,
            f"Tiron segment {index}",
        )
        speaker = segment["speaker"]
        text = segment["text"]
        if not is_tiron_speaker_id(speaker):
            raise ValueError("Tiron segment speaker is invalid")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Tiron segment text is invalid")
        transcript_bytes += len(text.encode("utf-8"))
        if transcript_bytes > MAX_TRANSCRIPT_BYTES:
            raise ValueError("Tiron transcript exceeds the bounded contract")
        start = _finite_number(segment["start"], "Tiron segment start")
        end = _finite_number(segment["end"], "Tiron segment end")
        start_sample = round(start * audio.sample_rate)
        end_sample = round(end * audio.sample_rate)
        if (
            start_sample < 0
            or start_sample < previous_start
            or end_sample <= start_sample
            or end_sample > audio.frame_count
        ):
            raise ValueError("Tiron segment source bounds are invalid")
        previous_start = start_sample
        observed_speakers.add(str(speaker))
        segments.append(
            {
                "index": index,
                "speaker": speaker,
                "startSample": start_sample,
                "endSample": end_sample,
                "text": text,
            }
        )
    if observed_speakers != set(raw_speakers):
        raise ValueError("Tiron speaker inventory differs from its segments")

    num_chunks = result["num_chunks"]
    maximum_chunks = maximum_upstream_window_count(source_duration)
    if (
        not isinstance(num_chunks, int)
        or isinstance(num_chunks, bool)
        or not 1 <= num_chunks <= maximum_chunks
    ):
        raise ValueError("Tiron chunk count is invalid")
    elapsed = _finite_number(result["elapsed_s"], "Tiron elapsed time")
    if elapsed < 0:
        raise ValueError("Tiron elapsed time is invalid")
    try:
        diagnostics = json.dumps(
            result["two_pass"],
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ValueError("Tiron two-pass diagnostics are invalid") from error
    if len(diagnostics) > _MAX_DIAGNOSTIC_BYTES:
        raise ValueError("Tiron two-pass diagnostics exceed the bounded contract")

    return {
        "language": language,
        "speakers": raw_speakers,
        "segments": segments,
        "numWindows": num_chunks,
        "sourceTimeUnit": "samples",
    }


def _exact_mapping(
    value: object,
    keys: set[str],
    field: str,
) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise ValueError(f"{field} fields are invalid")
    return value


def _finite_number(value: object, field: str) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
    ):
        raise ValueError(f"{field} is invalid")
    return float(value)
