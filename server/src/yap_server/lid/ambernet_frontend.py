"""Exact fixed-window feature extraction for NVIDIA AmberNet 1.12.0."""

from __future__ import annotations

import numpy as np


SAMPLE_RATE_HZ = 16_000
WINDOW_SAMPLES = SAMPLE_RATE_HZ * 3
MEL_BINS = 80
PADDED_FRAMES = 304

_FFT_SIZE = 512
_WINDOW_LENGTH = 400
_HOP_LENGTH = 160
_VALID_FRAMES = 300
_STFT_FRAMES = 301
_PREEMPHASIS = np.float32(0.97)
_LOG_GUARD = np.float32(5.960_464_5e-8)
_STANDARD_DEVIATION_GUARD = np.float32(1.0e-5)


class AmberNetFeatureExtractor:
    """Reconstruct the locked NeMo frontend without a NeMo dependency."""

    def __init__(self) -> None:
        self._hann_window = np.zeros(_FFT_SIZE, dtype=np.float32)
        offset = (_FFT_SIZE - _WINDOW_LENGTH) // 2
        indexes = np.arange(_WINDOW_LENGTH, dtype=np.float32)
        angles = (
            np.float32(2.0 * np.pi)
            * indexes
            / np.float32(_WINDOW_LENGTH - 1)
        )
        self._hann_window[offset : offset + _WINDOW_LENGTH] = (
            np.float32(0.5) - np.float32(0.5) * np.cos(angles)
        )
        self._mel_filterbank = _slaney_mel_filterbank()

    def process(self, signal: np.ndarray) -> np.ndarray:
        samples = np.asarray(signal, dtype=np.float32)
        if (
            samples.shape != (WINDOW_SAMPLES,)
            or not np.isfinite(samples).all()
            or bool(np.any(np.abs(samples) > np.float32(2.0)))
        ):
            raise RuntimeError(
                "AmberNet requires one finite three-second 16 kHz window"
            )

        emphasized = np.empty(WINDOW_SAMPLES, dtype=np.float32)
        emphasized[0] = samples[0]
        emphasized[1:] = samples[1:] - _PREEMPHASIS * samples[:-1]
        centered = np.pad(emphasized, (_FFT_SIZE // 2, _FFT_SIZE // 2))
        frames = np.lib.stride_tricks.sliding_window_view(centered, _FFT_SIZE)[
            ::_HOP_LENGTH
        ][:_STFT_FRAMES]
        transformed = np.fft.rfft(
            frames * self._hann_window,
            n=_FFT_SIZE,
            axis=1,
        ).astype(np.complex64)
        power = (
            transformed.real * transformed.real
            + transformed.imag * transformed.imag
        ).astype(np.float32)
        mel_energy = self._mel_filterbank @ power.T
        logged_mel = np.log(mel_energy + _LOG_GUARD).astype(np.float32)

        valid = logged_mel[:, :_VALID_FRAMES]
        means = valid.mean(axis=1, dtype=np.float32, keepdims=True)
        centered_valid = valid - means
        variances = (
            np.sum(centered_valid * centered_valid, axis=1, dtype=np.float32)
            / np.float32(_VALID_FRAMES - 1)
        )
        standard_deviations = np.sqrt(variances).astype(
            np.float32
        ) + _STANDARD_DEVIATION_GUARD
        output = np.zeros((MEL_BINS, PADDED_FRAMES), dtype=np.float32)
        output[:, :_VALID_FRAMES] = centered_valid / standard_deviations[:, None]
        return output[None, :, :]


def _slaney_mel_filterbank() -> np.ndarray:
    mel_min = _hertz_to_mel(0.0)
    mel_max = _hertz_to_mel(SAMPLE_RATE_HZ / 2.0)
    mel_frequencies = np.asarray(
        [
            _mel_to_hertz(
                mel_min + index / (MEL_BINS + 1) * (mel_max - mel_min)
            )
            for index in range(MEL_BINS + 2)
        ],
        dtype=np.float64,
    )
    fft_frequencies = (
        np.arange(_FFT_SIZE // 2 + 1, dtype=np.float64)
        * SAMPLE_RATE_HZ
        / _FFT_SIZE
    )
    weights = np.zeros((MEL_BINS, _FFT_SIZE // 2 + 1), dtype=np.float32)
    for mel in range(MEL_BINS):
        lower = (
            (fft_frequencies - mel_frequencies[mel])
            / (mel_frequencies[mel + 1] - mel_frequencies[mel])
        )
        upper = (
            (mel_frequencies[mel + 2] - fft_frequencies)
            / (mel_frequencies[mel + 2] - mel_frequencies[mel + 1])
        )
        normalization = 2.0 / (
            mel_frequencies[mel + 2] - mel_frequencies[mel]
        )
        weights[mel] = (
            normalization * np.maximum(0.0, np.minimum(lower, upper))
        ).astype(np.float32)
    return weights


def _hertz_to_mel(frequency: float) -> float:
    if frequency >= 1_000.0:
        return 15.0 + np.log(frequency / 1_000.0) / (np.log(6.4) / 27.0)
    return frequency / (200.0 / 3.0)


def _mel_to_hertz(mel: float) -> float:
    if mel >= 15.0:
        return 1_000.0 * np.exp((np.log(6.4) / 27.0) * (mel - 15.0))
    return (200.0 / 3.0) * mel
