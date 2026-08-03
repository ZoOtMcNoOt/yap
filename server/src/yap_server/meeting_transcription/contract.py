from __future__ import annotations

import math


MEETING_TRANSCRIPTION_PROVIDER_ID = "tiron"
MEETING_TRANSCRIPTION_POOL_ID = "tiron-meeting"
MEETING_SAMPLE_RATE_HZ = 16_000
MEETING_PCM_BYTES_PER_SAMPLE = 2
MAX_MEETING_DURATION_SECONDS = 3 * 60 * 60
MAX_MEETING_FRAME_COUNT = MEETING_SAMPLE_RATE_HZ * MAX_MEETING_DURATION_SECONDS
MAX_MEETING_PCM_BYTES = MAX_MEETING_FRAME_COUNT * MEETING_PCM_BYTES_PER_SAMPLE
MAX_MEETING_SPEAKERS = 8

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
