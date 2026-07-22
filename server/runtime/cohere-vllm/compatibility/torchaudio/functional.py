# SPDX-License-Identifier: BSD-2-Clause
# Adapted from pytorch/audio v2.11.0 solely for vLLM Cohere ASR compatibility:
# https://github.com/pytorch/audio/blob/v2.11.0/src/torchaudio/functional/functional.py

from __future__ import annotations

import math
from typing import Literal
import warnings

import torch
from torch import Tensor


MelScale = Literal["htk", "slaney"]


def _hz_to_mel(freq: float, mel_scale: MelScale) -> float:
    if mel_scale == "htk":
        return 2595.0 * math.log10(1.0 + (freq / 700.0))
    if mel_scale != "slaney":
        raise ValueError('mel_scale must be "htk" or "slaney"')
    linear_spacing = 200.0 / 3
    mels = freq / linear_spacing
    minimum_log_hz = 1000.0
    minimum_log_mel = minimum_log_hz / linear_spacing
    log_step = math.log(6.4) / 27.0
    if freq >= minimum_log_hz:
        mels = minimum_log_mel + math.log(freq / minimum_log_hz) / log_step
    return mels


def _mel_to_hz(mels: Tensor, mel_scale: MelScale) -> Tensor:
    if mel_scale == "htk":
        return 700.0 * (10.0 ** (mels / 2595.0) - 1.0)
    if mel_scale != "slaney":
        raise ValueError('mel_scale must be "htk" or "slaney"')
    linear_spacing = 200.0 / 3
    frequencies = linear_spacing * mels
    minimum_log_hz = 1000.0
    minimum_log_mel = minimum_log_hz / linear_spacing
    log_step = math.log(6.4) / 27.0
    logarithmic = mels >= minimum_log_mel
    frequencies[logarithmic] = minimum_log_hz * torch.exp(
        log_step * (mels[logarithmic] - minimum_log_mel)
    )
    return frequencies


def _triangular_filterbank(all_frequencies: Tensor, points: Tensor) -> Tensor:
    point_differences = points[1:] - points[:-1]
    slopes = points.unsqueeze(0) - all_frequencies.unsqueeze(1)
    descending = -slopes[:, :-2] / point_differences[:-1]
    ascending = slopes[:, 2:] / point_differences[1:]
    return torch.maximum(
        torch.zeros(1, dtype=slopes.dtype, device=slopes.device),
        torch.minimum(descending, ascending),
    )


def melscale_fbanks(
    n_freqs: int,
    f_min: float,
    f_max: float,
    n_mels: int,
    sample_rate: int,
    norm: str | None = None,
    mel_scale: MelScale = "htk",
) -> Tensor:
    """Return the triangular Mel filter bank needed by Cohere ASR."""

    if norm not in (None, "slaney"):
        raise ValueError('norm must be None or "slaney"')
    all_frequencies = torch.linspace(0, sample_rate // 2, n_freqs)
    minimum_mel = _hz_to_mel(f_min, mel_scale)
    maximum_mel = _hz_to_mel(f_max, mel_scale)
    mel_points = torch.linspace(minimum_mel, maximum_mel, n_mels + 2)
    frequency_points = _mel_to_hz(mel_points, mel_scale)
    filterbank = _triangular_filterbank(all_frequencies, frequency_points)
    if norm == "slaney":
        energy = 2.0 / (
            frequency_points[2 : n_mels + 2] - frequency_points[:n_mels]
        )
        filterbank *= energy.unsqueeze(0)
    if (filterbank.max(dim=0).values == 0.0).any():
        warnings.warn(
            "At least one Mel filter bank is empty for the requested dimensions.",
            stacklevel=2,
        )
    return filterbank
