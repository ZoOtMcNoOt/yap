from __future__ import annotations

import math
import re

from yap_server.pools.batch_contract import AsrRouteDecision


MEETING_TRANSCRIPTION_PROVIDER_ID = "tiron"
MEETING_TRANSCRIPTION_POOL_ID = "tiron-meeting"
MEETING_SAMPLE_RATE_HZ = 16_000
MEETING_PCM_BYTES_PER_SAMPLE = 2
MAX_MEETING_DURATION_SECONDS = 3 * 60 * 60
MAX_MEETING_FRAME_COUNT = MEETING_SAMPLE_RATE_HZ * MAX_MEETING_DURATION_SECONDS
MAX_MEETING_PCM_BYTES = MAX_MEETING_FRAME_COUNT * MEETING_PCM_BYTES_PER_SAMPLE
MAX_MEETING_SPEAKERS = 8
MAX_MEETING_SEGMENT_COUNT = 100_000

_MEETING_SPEAKER_ID = re.compile(r"^SPEAKER_0[0-7]$")

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


def is_meeting_speaker_id(value: object) -> bool:
    return isinstance(value, str) and _MEETING_SPEAKER_ID.fullmatch(value) is not None


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
