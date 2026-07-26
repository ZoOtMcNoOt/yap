from __future__ import annotations

import numpy as np


def energy_chunk_ranges(
    samples: np.ndarray,
    *,
    chunk_frames: int,
    boundary_context_frames: int,
    energy_window_frames: int,
) -> tuple[tuple[int, int], ...]:
    """Return contiguous Cohere-compatible ranges without copying PCM.

    The checked Cohere feature extractor searches the final boundary-context
    window of each maximum-length clip and cuts at the first quietest energy
    window. Keeping that policy here lets Yap feed the model in bounded
    microbatches instead of asking the processor to materialize every chunk of
    a multi-hour recording at once.
    """

    if (
        not isinstance(samples, np.ndarray)
        or samples.ndim != 1
        or samples.dtype != np.dtype("<i2")
    ):
        raise ValueError("Cohere chunking requires one little-endian PCM16 array")
    if (
        isinstance(chunk_frames, bool)
        or not isinstance(chunk_frames, int)
        or isinstance(boundary_context_frames, bool)
        or not isinstance(boundary_context_frames, int)
        or isinstance(energy_window_frames, bool)
        or not isinstance(energy_window_frames, int)
        or chunk_frames < 1
        or not 1 <= boundary_context_frames < chunk_frames
        or energy_window_frames < 1
    ):
        raise ValueError("Cohere chunking limits are invalid")
    total_frames = int(samples.shape[0])
    if total_frames < 1:
        raise ValueError("Cohere chunking requires non-empty PCM")
    if total_frames <= chunk_frames:
        return ((0, total_frames),)

    ranges: list[tuple[int, int]] = []
    start = 0
    while start < total_frames:
        if start + chunk_frames >= total_frames:
            ranges.append((start, total_frames))
            break
        search_start = max(start, start + chunk_frames - boundary_context_frames)
        search_end = min(start + chunk_frames, total_frames)
        segment_frames = search_end - search_start
        if segment_frames <= energy_window_frames:
            split = (search_start + search_end) // 2
        else:
            minimum_energy = float("inf")
            split = search_start
            upper = segment_frames - energy_window_frames
            for offset in range(0, upper, energy_window_frames):
                window = samples[
                    search_start + offset : search_start + offset + energy_window_frames
                ].astype(np.float32)
                energy = float(np.sqrt(np.mean(window * window)))
                if energy < minimum_energy:
                    minimum_energy = energy
                    split = search_start + offset
        split = max(start + 1, min(split, total_frames))
        ranges.append((start, split))
        start = split

    if (
        ranges[0][0] != 0
        or ranges[-1][1] != total_frames
        or any(
            end <= begin
            or end - begin > chunk_frames
            or (index > 0 and ranges[index - 1][1] != begin)
            for index, (begin, end) in enumerate(ranges)
        )
    ):
        raise RuntimeError("Cohere chunk planning produced an invalid partition")
    return tuple(ranges)
