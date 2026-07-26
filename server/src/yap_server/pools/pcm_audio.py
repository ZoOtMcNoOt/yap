from __future__ import annotations

from dataclasses import dataclass
import hashlib
import io
from pathlib import Path
import stat
import wave


SAMPLE_RATE_HZ = 16_000
MAX_AUDIO_SECONDS = 4 * 60 * 60
_MAX_WAV_OVERHEAD_BYTES = 16 * 1024 * 1024
MAX_ENCODED_AUDIO_BYTES = (
    SAMPLE_RATE_HZ * MAX_AUDIO_SECONDS * 2 + _MAX_WAV_OVERHEAD_BYTES
)


class WorkerInputError(ValueError):
    """An input is outside the bounded provider-worker audio contract."""


@dataclass(frozen=True)
class PcmAudio:
    pcm_bytes: bytes
    sample_rate: int
    frame_count: int
    duration_ms: int
    sha256: str


@dataclass(frozen=True)
class PcmWavSnapshot:
    encoded_bytes: bytes
    audio: PcmAudio


def read_pcm16_wav(
    path: Path,
    *,
    max_audio_seconds: int = MAX_AUDIO_SECONDS,
) -> PcmAudio:
    return read_pcm16_wav_snapshot(
        path,
        max_audio_seconds=max_audio_seconds,
    ).audio


def read_pcm16_wav_snapshot(
    path: Path,
    *,
    max_audio_seconds: int = MAX_AUDIO_SECONDS,
) -> PcmWavSnapshot:
    if max_audio_seconds < 1:
        raise ValueError("max_audio_seconds must be positive")
    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise WorkerInputError("input audio is missing") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise WorkerInputError("input audio must be a regular file")

    max_encoded_bytes = SAMPLE_RATE_HZ * max_audio_seconds * 2 + _MAX_WAV_OVERHEAD_BYTES
    if metadata.st_size > max_encoded_bytes:
        raise WorkerInputError("input audio exceeds the bounded encoded size")
    with path.open("rb") as encoded:
        encoded_bytes = encoded.read(max_encoded_bytes + 1)
    if len(encoded_bytes) > max_encoded_bytes:
        raise WorkerInputError("input audio exceeds the bounded encoded size")

    return PcmWavSnapshot(
        encoded_bytes=encoded_bytes,
        audio=decode_pcm16_wav(
            encoded_bytes,
            max_audio_seconds=max_audio_seconds,
        ),
    )


def decode_pcm16_wav(
    encoded_bytes: bytes,
    *,
    max_audio_seconds: int = MAX_AUDIO_SECONDS,
) -> PcmAudio:
    if max_audio_seconds < 1:
        raise ValueError("max_audio_seconds must be positive")
    max_encoded_bytes = SAMPLE_RATE_HZ * max_audio_seconds * 2 + _MAX_WAV_OVERHEAD_BYTES
    if not isinstance(encoded_bytes, bytes) or len(encoded_bytes) > max_encoded_bytes:
        raise WorkerInputError("input audio exceeds the bounded encoded size")

    try:
        with wave.open(io.BytesIO(encoded_bytes), "rb") as source:
            if source.getnchannels() != 1:
                raise WorkerInputError("input audio must be mono")
            if source.getsampwidth() != 2:
                raise WorkerInputError("input audio must use signed PCM16 samples")
            if source.getframerate() != SAMPLE_RATE_HZ:
                raise WorkerInputError("input audio must be 16 kHz")
            if source.getcomptype() != "NONE":
                raise WorkerInputError("compressed WAV input is not supported")
            frame_count = source.getnframes()
            if frame_count < 1:
                raise WorkerInputError("input audio must contain at least one frame")
            if frame_count > SAMPLE_RATE_HZ * max_audio_seconds:
                raise WorkerInputError("input audio exceeds the bounded duration")
            pcm_bytes = source.readframes(frame_count)
    except (EOFError, wave.Error) as error:
        raise WorkerInputError("input audio is not a valid PCM WAV") from error
    if len(pcm_bytes) != frame_count * 2:
        raise WorkerInputError("input audio ended before its declared frame count")

    return PcmAudio(
        pcm_bytes=pcm_bytes,
        sample_rate=SAMPLE_RATE_HZ,
        frame_count=frame_count,
        duration_ms=max(1, round(frame_count * 1000 / SAMPLE_RATE_HZ)),
        sha256=hashlib.sha256(encoded_bytes).hexdigest(),
    )
