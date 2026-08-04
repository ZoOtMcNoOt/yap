from __future__ import annotations

import math
import re

from yap_server.pools.batch_contract import AsrRouteDecision


MEETING_TRANSCRIPTION_PROVIDER_ID = "tiron"
MEETING_TRANSCRIPTION_POOL_ID = "tiron-meeting"
YAP_SPEAKER_RECONCILIATION_COMPONENT_ID = "yap/speaker-epoch-reconciliation"
MEETING_SAMPLE_RATE_HZ = 16_000
MEETING_PCM_BYTES_PER_SAMPLE = 2
MAX_MEETING_DURATION_SECONDS = 3 * 60 * 60
MAX_MEETING_FRAME_COUNT = MEETING_SAMPLE_RATE_HZ * MAX_MEETING_DURATION_SECONDS
MAX_MEETING_PCM_BYTES = MAX_MEETING_FRAME_COUNT * MEETING_PCM_BYTES_PER_SAMPLE
TIRON_DECODE_SPEAKER_LIMIT = 8
MEETING_SESSION_SPEAKER_TARGET = 32
MEETING_SESSION_SPEAKER_LIMIT = 64
MINIMUM_STABLE_SPEAKER_EVIDENCE_SAMPLES = 25_600
SPEAKER_CAPACITY_REACHED_CODE = "SPEAKER_CAPACITY_REACHED"
SOURCE_TIME_EPOCH_SECONDS = 30
SOURCE_TIME_EPOCH_SAMPLES = SOURCE_TIME_EPOCH_SECONDS * MEETING_SAMPLE_RATE_HZ
MAX_SOURCE_TIME_EPOCH_COUNT = math.ceil(
    MAX_MEETING_FRAME_COUNT / SOURCE_TIME_EPOCH_SAMPLES
)
MAX_MEETING_SEGMENT_COUNT = 100_000

_TIRON_SPEAKER_ID = re.compile(r"^SPEAKER_0[0-7]$")
_SESSION_SPEAKER_ID = re.compile(r"^speaker-(?:[1-9]|[1-5][0-9]|6[0-4])$")

# The pinned upstream chunker targets 30-second windows and may snap a
# non-final boundary up to three seconds earlier to end on silence. It also
# right-pads the source by 0.75 seconds before chunking. A source can therefore
# contain more windows than ceil(duration / 30), while every non-final window
# still advances by at least 27 seconds.
_UPSTREAM_WINDOW_SECONDS = 30.0
_UPSTREAM_MAXIMUM_SILENCE_SNAP_SECONDS = 3.0
_UPSTREAM_RIGHT_PADDING_SECONDS = 0.75


def maximum_upstream_window_count(source_duration_seconds: float) -> int:
    if not math.isfinite(source_duration_seconds) or source_duration_seconds <= 0:
        raise ValueError("meeting source duration must be positive and finite")
    minimum_advance = _UPSTREAM_WINDOW_SECONDS - _UPSTREAM_MAXIMUM_SILENCE_SNAP_SECONDS
    return max(
        1,
        math.ceil(
            (source_duration_seconds + _UPSTREAM_RIGHT_PADDING_SECONDS)
            / minimum_advance
        ),
    )


def is_tiron_speaker_id(value: object) -> bool:
    return isinstance(value, str) and _TIRON_SPEAKER_ID.fullmatch(value) is not None


def is_session_speaker_id(value: object) -> bool:
    return isinstance(value, str) and _SESSION_SPEAKER_ID.fullmatch(value) is not None


def canonical_session_speaker_ids(count: int) -> list[str]:
    if (
        not isinstance(count, int)
        or isinstance(count, bool)
        or not 0 <= count <= MEETING_SESSION_SPEAKER_LIMIT
    ):
        raise ValueError("meeting session speaker count is invalid")
    return [f"speaker-{number}" for number in range(1, count + 1)]


def maximum_source_time_decode_window_count(frame_count: int) -> int:
    if (
        not isinstance(frame_count, int)
        or isinstance(frame_count, bool)
        or not 1 <= frame_count <= MAX_MEETING_FRAME_COUNT
    ):
        raise ValueError("meeting frame count is outside the runtime boundary")
    total = 0
    for start in range(0, frame_count, SOURCE_TIME_EPOCH_SAMPLES):
        epoch_frames = min(SOURCE_TIME_EPOCH_SAMPLES, frame_count - start)
        total += maximum_upstream_window_count(epoch_frames / MEETING_SAMPLE_RATE_HZ)
    return total


def validate_meeting_transcription_route(
    route: AsrRouteDecision,
    *,
    model_revision: str,
    has_utterance_plan: bool,
) -> None:
    validate_meeting_transcription_route_identity(
        route,
        has_utterance_plan=has_utterance_plan,
    )
    if route.model_revision != model_revision:
        raise ValueError("meeting transcription received a different ASR route")


def validate_meeting_transcription_route_identity(
    route: AsrRouteDecision,
    *,
    has_utterance_plan: bool,
) -> None:
    if (
        route.provider_id != MEETING_TRANSCRIPTION_PROVIDER_ID
        or route.pool_id != MEETING_TRANSCRIPTION_POOL_ID
        or route.execution_mode != "fixedBatch"
        or route.provider_language == "auto"
        or has_utterance_plan
    ):
        raise ValueError("meeting transcription received a different ASR route")
