from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
from typing import Literal, Mapping, Sequence, cast

from yap_server.bounded_file import read_regular_file


SAMPLE_RATE_HZ = 16_000
UTTERANCE_PLAN_SCHEMA_VERSION = 1
UTTERANCE_PLAN_POLICY_REVISION = "complete-source-utterance-plan-v1"
MAX_UTTERANCE_SAMPLES = 30 * SAMPLE_RATE_HZ
BOUNDARY_SEARCH_SAMPLES = 5 * SAMPLE_RATE_HZ
MAX_RECORDING_SAMPLES = 4 * 60 * 60 * SAMPLE_RATE_HZ + 15
MAX_UTTERANCE_WINDOWS = 1_024
MAX_UTTERANCE_PLAN_BYTES = 512 * 1_024

_BOUNDARY_REASONS = frozenset({"endOfInput", "maxDuration", "vadSilence"})
_VAD_STATUSES = frozenset({"complete", "error"})


BoundaryReason = Literal["endOfInput", "maxDuration", "vadSilence"]


@dataclass(frozen=True, slots=True)
class UtteranceWindow:
    index: int
    start_sample: int
    end_sample_exclusive: int
    boundary_reason: BoundaryReason

    def to_payload(self) -> dict[str, object]:
        return {
            "index": self.index,
            "startSample": self.start_sample,
            "endSampleExclusive": self.end_sample_exclusive,
            "boundaryReason": self.boundary_reason,
        }


@dataclass(frozen=True, slots=True)
class UtterancePlan:
    input_wav_sha256: str
    input_sample_count: int
    source_sample_count: int
    vad_status: Literal["complete", "error"]
    vad_evidence_sha256: str
    utterances: tuple[UtteranceWindow, ...]

    def __post_init__(self) -> None:
        _validate_sha256(self.input_wav_sha256, "input WAV identity")
        _validate_sha256(self.vad_evidence_sha256, "VAD evidence identity")
        if (
            not _is_int_between(self.input_sample_count, 1, MAX_RECORDING_SAMPLES)
            or not _is_int_between(
                self.source_sample_count,
                1,
                self.input_sample_count,
            )
            or self.input_sample_count - self.source_sample_count >= SAMPLE_RATE_HZ // 1_000
            or not isinstance(self.vad_status, str)
            or self.vad_status not in _VAD_STATUSES
            or not 1 <= len(self.utterances) <= MAX_UTTERANCE_WINDOWS
        ):
            raise ValueError("utterance plan identity or bounds are invalid")
        cursor = 0
        for index, window in enumerate(self.utterances):
            if (
                not isinstance(window, UtteranceWindow)
                or window.index != index
                or window.start_sample != cursor
                or not _is_int_between(
                    window.end_sample_exclusive,
                    cursor + 1,
                    self.input_sample_count,
                )
                or window.end_sample_exclusive - cursor > MAX_UTTERANCE_SAMPLES
                or not isinstance(window.boundary_reason, str)
                or window.boundary_reason not in _BOUNDARY_REASONS
                or (
                    window.end_sample_exclusive == self.input_sample_count
                    and window.boundary_reason != "endOfInput"
                )
                or (
                    window.end_sample_exclusive != self.input_sample_count
                    and window.boundary_reason == "endOfInput"
                )
            ):
                raise ValueError("utterance plan is not one contiguous bounded partition")
            cursor = window.end_sample_exclusive
        if cursor != self.input_sample_count:
            raise ValueError("utterance plan does not preserve the complete input")

    def to_payload(self) -> dict[str, object]:
        return {
            "schemaVersion": UTTERANCE_PLAN_SCHEMA_VERSION,
            "policyRevision": UTTERANCE_PLAN_POLICY_REVISION,
            "inputWavSha256": self.input_wav_sha256,
            "inputSampleCount": self.input_sample_count,
            "sourceSampleCount": self.source_sample_count,
            "vadStatus": self.vad_status,
            "vadEvidenceSha256": self.vad_evidence_sha256,
            "maxUtteranceSamples": MAX_UTTERANCE_SAMPLES,
            "boundarySearchSamples": BOUNDARY_SEARCH_SAMPLES,
            "utterances": [window.to_payload() for window in self.utterances],
        }


@dataclass(frozen=True, slots=True)
class UtterancePlanSnapshot:
    encoded_bytes: bytes
    sha256: str
    plan: UtterancePlan


@dataclass(frozen=True, slots=True)
class UtterancePlanSource:
    input_sample_count: int
    source_sample_count: int
    vad_status: Literal["complete", "error"]
    vad_evidence_sha256: str
    vad_intervals: tuple[tuple[int, int], ...]

    def __post_init__(self) -> None:
        _validate_plan_source(self)

    def build(self, input_wav_sha256: str) -> UtterancePlan:
        return build_utterance_plan(
            input_wav_sha256=input_wav_sha256,
            input_sample_count=self.input_sample_count,
            source_sample_count=self.source_sample_count,
            vad_status=self.vad_status,
            vad_evidence_sha256=self.vad_evidence_sha256,
            vad_intervals=self.vad_intervals,
        )

    def input_fingerprint(self, output_pcm_sha256: str) -> str:
        _validate_sha256(output_pcm_sha256, "normalized PCM identity")
        return hashlib.sha256(
            json.dumps(
                {
                    "schemaVersion": UTTERANCE_PLAN_SCHEMA_VERSION,
                    "policyRevision": UTTERANCE_PLAN_POLICY_REVISION,
                    "outputPcmSha256": output_pcm_sha256,
                    "inputSampleCount": self.input_sample_count,
                    "sourceSampleCount": self.source_sample_count,
                    "vadStatus": self.vad_status,
                    "vadEvidenceSha256": self.vad_evidence_sha256,
                    "maxUtteranceSamples": MAX_UTTERANCE_SAMPLES,
                    "boundarySearchSamples": BOUNDARY_SEARCH_SAMPLES,
                },
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()


def build_utterance_plan(
    *,
    input_wav_sha256: str,
    input_sample_count: int,
    source_sample_count: int,
    vad_status: str,
    vad_evidence_sha256: str,
    vad_intervals: Sequence[tuple[int, int]],
) -> UtterancePlan:
    source = UtterancePlanSource(
        input_sample_count=input_sample_count,
        source_sample_count=source_sample_count,
        vad_status=cast(Literal["complete", "error"], vad_status),
        vad_evidence_sha256=vad_evidence_sha256,
        vad_intervals=tuple(vad_intervals),
    )
    _validate_sha256(input_wav_sha256, "input WAV identity")
    silence = (
        _silence_ranges(
            source.vad_intervals,
            source_sample_count=source.source_sample_count,
            input_sample_count=source.input_sample_count,
        )
        if source.vad_status == "complete"
        else ()
    )
    windows: list[UtteranceWindow] = []
    cursor = 0
    while source.input_sample_count - cursor > MAX_UTTERANCE_SAMPLES:
        hard_boundary = cursor + MAX_UTTERANCE_SAMPLES
        search_start = hard_boundary - BOUNDARY_SEARCH_SAMPLES
        silence_boundary = _latest_silence_boundary(
            silence,
            search_start=search_start,
            hard_boundary=hard_boundary,
        )
        boundary = silence_boundary or hard_boundary
        reason: BoundaryReason = (
            "vadSilence" if silence_boundary is not None else "maxDuration"
        )
        windows.append(
            UtteranceWindow(
                index=len(windows),
                start_sample=cursor,
                end_sample_exclusive=boundary,
                boundary_reason=reason,
            )
        )
        cursor = boundary
    windows.append(
        UtteranceWindow(
            index=len(windows),
            start_sample=cursor,
            end_sample_exclusive=source.input_sample_count,
            boundary_reason="endOfInput",
        )
    )
    return UtterancePlan(
        input_wav_sha256=input_wav_sha256,
        input_sample_count=source.input_sample_count,
        source_sample_count=source.source_sample_count,
        vad_status=source.vad_status,
        vad_evidence_sha256=source.vad_evidence_sha256,
        utterances=tuple(windows),
    )


def canonical_vad_evidence_sha256(value: Mapping[str, object]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def publish_utterance_plan(
    destination: Path,
    plan: UtterancePlan,
    *,
    cancellation: threading.Event | None = None,
) -> str:
    snapshot = snapshot_utterance_plan(plan)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=destination.parent,
            prefix=".utterance-plan-",
            suffix=".json.part",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            _raise_if_cancelled(cancellation)
            temporary.write(snapshot.encoded_bytes)
            temporary.flush()
            os.fsync(temporary.fileno())
        _raise_if_cancelled(cancellation)
        os.replace(temporary_path, destination)
        temporary_path = None
        _raise_if_cancelled(cancellation)
        return snapshot.sha256
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def snapshot_utterance_plan(plan: UtterancePlan) -> UtterancePlanSnapshot:
    """Return the canonical bounded wire representation of one checked plan."""

    if not isinstance(plan, UtterancePlan):
        raise ValueError("utterance plan snapshot requires a checked plan")
    encoded = _encode_plan(plan)
    return UtterancePlanSnapshot(
        encoded_bytes=encoded,
        sha256=hashlib.sha256(encoded).hexdigest(),
        plan=plan,
    )


def read_utterance_plan(
    path: Path,
    *,
    expected_sha256: str,
    expected_input_wav_sha256: str,
    expected_input_sample_count: int,
) -> UtterancePlan:
    return read_utterance_plan_snapshot(
        path,
        expected_sha256=expected_sha256,
        expected_input_wav_sha256=expected_input_wav_sha256,
        expected_input_sample_count=expected_input_sample_count,
    ).plan


def read_utterance_plan_snapshot(
    path: Path,
    *,
    expected_sha256: str,
    expected_input_wav_sha256: str,
    expected_input_sample_count: int,
) -> UtterancePlanSnapshot:
    _validate_sha256(expected_sha256, "utterance plan identity")
    encoded = read_regular_file(path, MAX_UTTERANCE_PLAN_BYTES)
    return parse_utterance_plan_snapshot(
        encoded,
        expected_sha256=expected_sha256,
        expected_input_wav_sha256=expected_input_wav_sha256,
        expected_input_sample_count=expected_input_sample_count,
    )


def parse_utterance_plan_snapshot(
    encoded: bytes,
    *,
    expected_sha256: str,
    expected_input_wav_sha256: str,
    expected_input_sample_count: int,
) -> UtterancePlanSnapshot:
    _validate_sha256(expected_sha256, "utterance plan identity")
    if (
        not isinstance(encoded, bytes)
        or len(encoded) > MAX_UTTERANCE_PLAN_BYTES
        or hashlib.sha256(encoded).hexdigest() != expected_sha256
    ):
        raise ValueError("utterance plan differs from its immutable identity")
    try:
        value = json.loads(encoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("utterance plan is not valid JSON") from error
    plan = _plan_from_payload(value)
    if (
        plan.input_wav_sha256 != expected_input_wav_sha256
        or plan.input_sample_count != expected_input_sample_count
    ):
        raise ValueError("utterance plan differs from the checked input WAV")
    return UtterancePlanSnapshot(
        encoded_bytes=encoded,
        sha256=expected_sha256,
        plan=plan,
    )


def _plan_from_payload(value: object) -> UtterancePlan:
    if not isinstance(value, Mapping) or set(value) != {
        "schemaVersion",
        "policyRevision",
        "inputWavSha256",
        "inputSampleCount",
        "sourceSampleCount",
        "vadStatus",
        "vadEvidenceSha256",
        "maxUtteranceSamples",
        "boundarySearchSamples",
        "utterances",
    }:
        raise ValueError("utterance plan fields are invalid")
    raw_windows = value.get("utterances")
    if (
        value.get("schemaVersion") != UTTERANCE_PLAN_SCHEMA_VERSION
        or value.get("policyRevision") != UTTERANCE_PLAN_POLICY_REVISION
        or value.get("maxUtteranceSamples") != MAX_UTTERANCE_SAMPLES
        or value.get("boundarySearchSamples") != BOUNDARY_SEARCH_SAMPLES
        or not isinstance(raw_windows, list)
        or len(raw_windows) > MAX_UTTERANCE_WINDOWS
    ):
        raise ValueError("utterance plan version or limits are invalid")
    windows: list[UtteranceWindow] = []
    for raw_window in raw_windows:
        if not isinstance(raw_window, Mapping) or set(raw_window) != {
            "index",
            "startSample",
            "endSampleExclusive",
            "boundaryReason",
        }:
            raise ValueError("utterance window fields are invalid")
        windows.append(
            UtteranceWindow(
                index=cast(int, raw_window.get("index")),
                start_sample=cast(int, raw_window.get("startSample")),
                end_sample_exclusive=cast(
                    int,
                    raw_window.get("endSampleExclusive"),
                ),
                boundary_reason=cast(
                    BoundaryReason,
                    raw_window.get("boundaryReason"),
                ),
            )
        )
    return UtterancePlan(
        input_wav_sha256=cast(str, value.get("inputWavSha256")),
        input_sample_count=cast(int, value.get("inputSampleCount")),
        source_sample_count=cast(int, value.get("sourceSampleCount")),
        vad_status=cast(Literal["complete", "error"], value.get("vadStatus")),
        vad_evidence_sha256=cast(str, value.get("vadEvidenceSha256")),
        utterances=tuple(windows),
    )


def _validate_plan_source(source: UtterancePlanSource) -> None:
    _validate_sha256(source.vad_evidence_sha256, "VAD evidence identity")
    if (
        not _is_int_between(source.input_sample_count, 1, MAX_RECORDING_SAMPLES)
        or not _is_int_between(
            source.source_sample_count,
            1,
            source.input_sample_count,
        )
        or source.input_sample_count - source.source_sample_count
        >= SAMPLE_RATE_HZ // 1_000
        or not isinstance(source.vad_status, str)
        or source.vad_status not in _VAD_STATUSES
        or len(source.vad_intervals) > 4_096
        or (source.vad_status == "error" and source.vad_intervals)
    ):
        raise ValueError("utterance plan source is invalid")
    previous_end = 0
    for interval in source.vad_intervals:
        if (
            not isinstance(interval, tuple)
            or len(interval) != 2
            or not _is_int_between(interval[0], 0, source.source_sample_count)
            or not _is_int_between(interval[1], 1, source.source_sample_count)
            or interval[0] >= interval[1]
            or interval[0] < previous_end
        ):
            raise ValueError("utterance plan VAD intervals are invalid")
        previous_end = interval[1]


def _silence_ranges(
    intervals: Sequence[tuple[int, int]],
    *,
    source_sample_count: int,
    input_sample_count: int,
) -> tuple[tuple[int, int], ...]:
    silence: list[tuple[int, int]] = []
    cursor = 0
    for start, end in intervals:
        if cursor < start:
            silence.append((cursor, start))
        cursor = end
    if cursor < input_sample_count:
        silence.append((cursor, input_sample_count))
    elif source_sample_count < input_sample_count:
        silence.append((source_sample_count, input_sample_count))
    return tuple(silence)


def _latest_silence_boundary(
    silence: Sequence[tuple[int, int]],
    *,
    search_start: int,
    hard_boundary: int,
) -> int | None:
    candidate: int | None = None
    for gap_start, gap_end in silence:
        overlap_start = max(gap_start, search_start)
        overlap_end = min(gap_end, hard_boundary)
        if overlap_start >= overlap_end:
            continue
        if gap_end > hard_boundary:
            boundary = hard_boundary
        else:
            boundary = overlap_start + (overlap_end - overlap_start) // 2
        if boundary >= search_start and (candidate is None or boundary > candidate):
            candidate = boundary
    return candidate


def _encode_plan(plan: UtterancePlan) -> bytes:
    encoded = (
        json.dumps(
            plan.to_payload(),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    if len(encoded) > MAX_UTTERANCE_PLAN_BYTES:
        raise ValueError("utterance plan exceeds its private artifact bound")
    return encoded


def _validate_sha256(value: object, field: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")


def _is_int_between(value: object, minimum: int, maximum: int) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and minimum <= value <= maximum
    )


def _raise_if_cancelled(cancellation: threading.Event | None) -> None:
    if cancellation is not None and cancellation.is_set():
        from concurrent.futures import CancelledError

        raise CancelledError()
