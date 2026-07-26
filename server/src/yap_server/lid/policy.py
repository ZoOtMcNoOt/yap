from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
import math
import re
from typing import Sequence

from yap_server.language_tags import canonical_bcp47


_MAX_SOURCE_SAMPLES = 16_000 * 4 * 60 * 60
_MAX_VAD_INTERVALS = 4_096
_MAX_LOCALES = 256
_MODEL_LABEL = re.compile(r"^[a-z]{2,3}$")
_STRATIFIED_PROBE_COUNT = 5
_LANGUAGE_ALIASES = {
    "in": "id",
    "iw": "he",
    "ji": "yi",
    "jw": "jv",
    "mo": "ro",
}


@dataclass(frozen=True)
class SourceVadInterval:
    start_sample: int
    end_sample_exclusive: int


@dataclass(frozen=True)
class LidProbeWindow:
    index: int
    source_start_sample: int
    source_end_sample: int
    voiced_samples: int


@dataclass(frozen=True)
class LidProbeSelection:
    status: str
    reason: str
    windows: tuple[LidProbeWindow, ...]


@dataclass(frozen=True)
class LidObservation:
    index: int
    source_start_sample: int
    source_end_sample: int
    raw_label: str
    top_score: float
    score_margin: float


@dataclass(frozen=True)
class LidSuggestionDecision:
    status: str
    reason: str
    suggested_locale: str | None
    observations: tuple[LidObservation, ...]
    user_confirmation_required: bool


@dataclass(frozen=True)
class _VadTimeline:
    intervals: tuple[SourceVadInterval, ...]
    starts: tuple[int, ...]
    ends: tuple[int, ...]
    cumulative_voiced: tuple[int, ...]


def _integer(value: object, field: str, *, minimum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise ValueError(f"{field} must be an integer of at least {minimum}")
    return value


def _validated_intervals(
    intervals: Sequence[SourceVadInterval],
    source_samples: int,
) -> tuple[SourceVadInterval, ...]:
    if len(intervals) > _MAX_VAD_INTERVALS:
        raise ValueError("too many VAD intervals for LID selection")
    result: list[SourceVadInterval] = []
    previous_end = 0
    for position, interval in enumerate(intervals):
        if not isinstance(interval, SourceVadInterval):
            raise ValueError("VAD intervals must use SourceVadInterval")
        start = _integer(
            interval.start_sample,
            f"vad_intervals[{position}].start_sample",
            minimum=0,
        )
        end = _integer(
            interval.end_sample_exclusive,
            f"vad_intervals[{position}].end_sample_exclusive",
            minimum=1,
        )
        if start >= end or end > source_samples or start < previous_end:
            raise ValueError("VAD intervals are invalid, unordered, or overlapping")
        result.append(SourceVadInterval(start, end))
        previous_end = end
    return tuple(result)


def _voiced_samples(
    start: int,
    end: int,
    timeline: _VadTimeline,
) -> int:
    first = bisect_right(timeline.ends, start)
    stop = bisect_left(timeline.starts, end)
    if first >= stop:
        return 0
    total = (
        timeline.cumulative_voiced[stop]
        - timeline.cumulative_voiced[first]
    )
    first_interval = timeline.intervals[first]
    last_interval = timeline.intervals[stop - 1]
    total -= max(0, start - first_interval.start_sample)
    total -= max(0, last_interval.end_sample_exclusive - end)
    return total


def _timeline(intervals: tuple[SourceVadInterval, ...]) -> _VadTimeline:
    cumulative = [0]
    for interval in intervals:
        cumulative.append(
            cumulative[-1]
            + interval.end_sample_exclusive
            - interval.start_sample
        )
    return _VadTimeline(
        intervals=intervals,
        starts=tuple(interval.start_sample for interval in intervals),
        ends=tuple(interval.end_sample_exclusive for interval in intervals),
        cumulative_voiced=tuple(cumulative),
    )


def _candidate_window(
    *,
    index: int,
    start: int,
    source_samples: int,
    maximum_window_samples: int,
    minimum_voiced_samples: int,
    timeline: _VadTimeline,
) -> LidProbeWindow | None:
    if start < 0 or start >= source_samples:
        return None
    end = min(source_samples, start + maximum_window_samples)
    voiced = _voiced_samples(start, end, timeline)
    if voiced < minimum_voiced_samples:
        return None
    return LidProbeWindow(
        index=index,
        source_start_sample=start,
        source_end_sample=end,
        voiced_samples=voiced,
    )


def select_lid_probe_windows(
    *,
    source_samples: int,
    vad_intervals: Sequence[SourceVadInterval],
    minimum_source_samples: int,
    maximum_windows: int,
    maximum_window_samples: int,
    minimum_voiced_samples: int,
) -> LidProbeSelection:
    """Select five deterministic regions spanning the complete recording."""

    source_samples = _integer(source_samples, "source_samples", minimum=1)
    if source_samples > _MAX_SOURCE_SAMPLES:
        raise ValueError("source_samples exceeds the accepted four-hour bound")
    minimum_source_samples = _integer(
        minimum_source_samples,
        "minimum_source_samples",
        minimum=1,
    )
    maximum_windows = _integer(maximum_windows, "maximum_windows", minimum=1)
    maximum_window_samples = _integer(
        maximum_window_samples,
        "maximum_window_samples",
        minimum=1,
    )
    minimum_voiced_samples = _integer(
        minimum_voiced_samples,
        "minimum_voiced_samples",
        minimum=1,
    )
    if maximum_windows != _STRATIFIED_PROBE_COUNT:
        raise ValueError("the accepted LID policy requires exactly five probes")
    if minimum_voiced_samples > maximum_window_samples:
        raise ValueError("minimum voiced samples exceed the probe window")
    if minimum_source_samples < maximum_windows * maximum_window_samples:
        raise ValueError("minimum source is too short for disjoint probe windows")
    intervals = _validated_intervals(vad_intervals, source_samples)
    timeline = _timeline(intervals)
    if source_samples < minimum_source_samples:
        return LidProbeSelection("manual", "short_recording", ())

    maximum_start = source_samples - maximum_window_samples
    windows: list[LidProbeWindow] = []
    for index in range(_STRATIFIED_PROBE_COUNT):
        # Integer half-up rounding is mirrored by the native client. The first
        # region begins at zero and the fifth ends at the exact source tail.
        start = (maximum_start * index + 2) // 4
        window = _candidate_window(
            index=index,
            start=start,
            source_samples=source_samples,
            maximum_window_samples=maximum_window_samples,
            minimum_voiced_samples=minimum_voiced_samples,
            timeline=timeline,
        )
        if window is None:
            return LidProbeSelection(
                "manual",
                "stratified_region_unavailable",
                (),
            )
        windows.append(window)
    return LidProbeSelection(
        "selected",
        "five_stratified_probes_selected",
        tuple(windows),
    )


def select_lid_probe_windows_from_lock(
    *,
    source_samples: int,
    vad_intervals: Sequence[SourceVadInterval],
    lock: object,
) -> LidProbeSelection:
    """Apply the immutable component policy without copying its thresholds."""

    from .component_lock import LidComponentLock

    if not isinstance(lock, LidComponentLock):
        raise TypeError("lock must be a validated LidComponentLock")
    return select_lid_probe_windows(
        source_samples=source_samples,
        vad_intervals=vad_intervals,
        minimum_source_samples=lock.policy.minimum_source_samples,
        maximum_windows=lock.policy.maximum_windows,
        maximum_window_samples=lock.policy.maximum_window_samples,
        minimum_voiced_samples=lock.policy.minimum_voiced_samples_per_window,
    )


def _manual(
    reason: str,
    observations: tuple[LidObservation, ...],
) -> LidSuggestionDecision:
    return LidSuggestionDecision(
        status="manual",
        reason=reason,
        suggested_locale=None,
        observations=observations,
        user_confirmation_required=True,
    )


def _validated_observations(
    observations: Sequence[LidObservation],
) -> tuple[LidObservation, ...]:
    if len(observations) > _STRATIFIED_PROBE_COUNT:
        raise ValueError("LID observations exceed the five-probe bound")
    result: list[LidObservation] = []
    previous_end = 0
    for position, observation in enumerate(observations):
        if not isinstance(observation, LidObservation):
            raise ValueError("LID observations must use LidObservation")
        index = _integer(observation.index, "observation.index", minimum=0)
        start = _integer(
            observation.source_start_sample,
            "observation.source_start_sample",
            minimum=0,
        )
        end = _integer(
            observation.source_end_sample,
            "observation.source_end_sample",
            minimum=1,
        )
        if index != position or start >= end or start < previous_end:
            raise ValueError("LID observation windows are invalid or overlap")
        if (
            isinstance(observation.top_score, bool)
            or not isinstance(observation.top_score, (int, float))
            or isinstance(observation.score_margin, bool)
            or not isinstance(observation.score_margin, (int, float))
        ):
            raise ValueError("LID score evidence is invalid")
        top_score = float(observation.top_score)
        score_margin = float(observation.score_margin)
        if (
            not math.isfinite(top_score)
            or not math.isfinite(score_margin)
            or top_score > 0.0
            or score_margin < 0.0
        ):
            raise ValueError("LID score evidence is invalid")
        result.append(
            LidObservation(
                index=index,
                source_start_sample=start,
                source_end_sample=end,
                raw_label=observation.raw_label,
                top_score=top_score,
                score_margin=score_margin,
            )
        )
        previous_end = end
    return tuple(result)


def _language_code(raw_label: object) -> str | None:
    if not isinstance(raw_label, str) or len(raw_label) > 128:
        return None
    if _MODEL_LABEL.fullmatch(raw_label) is None or not raw_label.isprintable():
        return None
    return _LANGUAGE_ALIASES.get(raw_label, raw_label)


def map_lid_label_to_enabled_locales(
    raw_label: object,
    *,
    enabled_fixed_locales: Sequence[str],
) -> tuple[str, ...]:
    """Return exact enabled locale candidates; never guess a country variant."""

    locales = validate_enabled_fixed_locales(enabled_fixed_locales)
    code = _language_code(raw_label)
    if code is None:
        return ()
    return tuple(
        locale for locale in locales if locale.split("-", maxsplit=1)[0] == code
    )


def resolve_lid_suggestion(
    observations: Sequence[LidObservation],
    *,
    enabled_fixed_locales: Sequence[str],
) -> LidSuggestionDecision:
    """Resolve five region labels to a suggestion, never routing authority."""

    validated = _validated_observations(observations)
    locales = validate_enabled_fixed_locales(enabled_fixed_locales)
    if len(validated) != _STRATIFIED_PROBE_COUNT:
        return _manual("five_probes_required", validated)
    if any(item.score_margin <= 0.0 for item in validated):
        return _manual("ambiguous_model_output", validated)

    codes = tuple(_language_code(item.raw_label) for item in validated)
    if any(code is None for code in codes):
        return _manual("invalid_model_label", validated)
    if any(code != codes[0] for code in codes[1:]):
        return _manual("language_disagreement", validated)
    candidates = map_lid_label_to_enabled_locales(
        validated[0].raw_label,
        enabled_fixed_locales=locales,
    )
    if not candidates:
        return _manual("unsupported_language", validated)
    if len(candidates) != 1:
        return _manual("ambiguous_locale", validated)
    return LidSuggestionDecision(
        status="suggestion",
        reason="mapped_language_agreement",
        suggested_locale=candidates[0],
        observations=validated,
        user_confirmation_required=True,
    )


def validate_enabled_fixed_locales(
    enabled_fixed_locales: Sequence[str],
) -> tuple[str, ...]:
    """Canonicalize and freeze the exact destinations LID may suggest."""

    if len(enabled_fixed_locales) > _MAX_LOCALES:
        raise ValueError("too many enabled locales for LID resolution")
    locales = tuple(
        canonical_bcp47(value, "enabled_fixed_locales")
        for value in enabled_fixed_locales
    )
    if len(locales) != len(set(locales)):
        raise ValueError("enabled fixed locales must be unique")
    return locales
