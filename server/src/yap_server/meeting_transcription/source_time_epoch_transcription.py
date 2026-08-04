"""Compose bounded Tiron calls into one source-time meeting result."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tempfile
from typing import Protocol, Sequence
import wave

from yap_server.limits import MAX_TRANSCRIPT_BYTES
from yap_server.pools import pcm_audio
from yap_server.transcript_text import canonical_transcript

from .released_tiron_result import validate_released_tiron_result
from .contract import (
    MEETING_SESSION_SPEAKER_LIMIT,
    MAX_MEETING_SEGMENT_COUNT,
    MINIMUM_STABLE_SPEAKER_EVIDENCE_SAMPLES,
    SOURCE_TIME_EPOCH_SAMPLES,
    TIRON_DECODE_SPEAKER_LIMIT,
)
from .speaker_epoch_reconciliation import (
    EpochSpeaker,
    EpochTurn,
    ReconciledSpeakerTurn,
    SpeakerEpoch,
    reconcile_speaker_epochs,
)
from .speaker_capacity import SpeakerCapacityDegradation


class TironEpochEngine(Protocol):
    def transcribe(
        self,
        audio: str,
        *,
        language: str,
        max_speakers: int,
        two_pass: bool,
    ) -> dict[str, object]: ...


class SpeakerEmbeddingEncoder(Protocol):
    def encode_pcm16(self, pcm_bytes: bytes) -> Sequence[float]: ...


class SpeechBrainSpeakerEncoder:
    """Use the ECAPA classifier already owned by the pinned Tiron engine."""

    def __init__(self, classifier: object) -> None:
        encode_batch = getattr(classifier, "encode_batch", None)
        if not callable(encode_batch):
            raise RuntimeError("Tiron ECAPA classifier does not expose encode_batch")
        import numpy as np
        import torch

        self._classifier = classifier
        self._np = np
        self._torch = torch

    def encode_pcm16(self, pcm_bytes: bytes) -> tuple[float, ...]:
        if not isinstance(pcm_bytes, bytes) or not pcm_bytes or len(pcm_bytes) % 2:
            raise ValueError("speaker embedding input must be non-empty PCM16")
        samples = (
            self._np.frombuffer(pcm_bytes, dtype="<i2").astype(self._np.float32)
            / 32_768.0
        )
        waveform = self._torch.from_numpy(samples).unsqueeze(0)
        with self._torch.inference_mode():
            encoded = self._classifier.encode_batch(waveform, normalize=True)
        flattened = encoded.detach().to("cpu").reshape(-1).tolist()
        if not isinstance(flattened, list):
            raise RuntimeError("Tiron ECAPA classifier returned an invalid embedding")
        return tuple(float(value) for value in flattened)


@dataclass(frozen=True, slots=True)
class SourceTimeMeetingTranscription:
    language: str
    session_speaker_ids: tuple[str, ...]
    turns: tuple[ReconciledSpeakerTurn, ...]
    num_decode_windows: int
    capacity_degradation: SpeakerCapacityDegradation | None


def transcribe_source_time_epochs(
    *,
    audio: pcm_audio.PcmAudio,
    engine: TironEpochEngine,
    language: str,
    speaker_encoder: SpeakerEmbeddingEncoder,
) -> SourceTimeMeetingTranscription:
    """Run the public whole-source API on source-bounded 30-second epochs."""

    if (
        audio.sample_rate != pcm_audio.SAMPLE_RATE_HZ
        or audio.frame_count < 1
        or len(audio.pcm_bytes) != audio.frame_count * 2
    ):
        raise ValueError("meeting epoch input is not canonical PCM16 audio")

    epochs: list[SpeakerEpoch] = []
    total_windows = 0
    total_turns = 0
    total_transcript_bytes = 0
    observed_language: str | None = None
    first_saturated_epoch: tuple[int, int] | None = None
    with tempfile.TemporaryDirectory(prefix="yap-tiron-epochs-") as temporary:
        temporary_root = Path(temporary)
        for epoch_index, start_sample in enumerate(
            range(0, audio.frame_count, SOURCE_TIME_EPOCH_SAMPLES)
        ):
            end_sample = min(
                audio.frame_count,
                start_sample + SOURCE_TIME_EPOCH_SAMPLES,
            )
            epoch_pcm = audio.pcm_bytes[start_sample * 2 : end_sample * 2]
            epoch_path = temporary_root / f"epoch-{epoch_index:05d}.wav"
            _write_pcm16_wav(epoch_path, epoch_pcm)
            epoch_audio = pcm_audio.read_pcm16_wav(
                epoch_path,
                max_audio_seconds=30,
            )
            raw_result = engine.transcribe(
                str(epoch_path.resolve()),
                language=language,
                max_speakers=TIRON_DECODE_SPEAKER_LIMIT,
                two_pass=True,
            )
            validated = validate_released_tiron_result(raw_result, epoch_audio)
            epoch_language = validated["language"]
            if not isinstance(epoch_language, str):
                raise ValueError("Tiron epoch language is invalid")
            if observed_language is None:
                observed_language = epoch_language
            elif epoch_language != observed_language:
                raise ValueError("Tiron epochs returned inconsistent languages")

            speakers = validated["speakers"]
            segments = validated["segments"]
            num_windows = validated["numWindows"]
            if (
                not isinstance(speakers, list)
                or not isinstance(segments, list)
                or not isinstance(num_windows, int)
            ):
                raise ValueError("validated Tiron epoch changed shape")
            total_turns += len(segments)
            if total_turns > MAX_MEETING_SEGMENT_COUNT:
                raise ValueError("meeting turns exceed the bounded contract")
            total_windows += num_windows
            if (
                len(speakers) == TIRON_DECODE_SPEAKER_LIMIT
                and first_saturated_epoch is None
            ):
                first_saturated_epoch = (start_sample, end_sample)

            epoch_speakers = tuple(
                _epoch_speaker(
                    speaker=str(speaker),
                    segments=segments,
                    source_pcm=audio.pcm_bytes,
                    source_offset=start_sample,
                    speaker_encoder=speaker_encoder,
                )
                for speaker in speakers
            )
            epoch_turns = tuple(
                EpochTurn(
                    local_speaker_id=str(segment["speaker"]),
                    start_sample=start_sample + int(segment["startSample"]),
                    end_sample=start_sample + int(segment["endSample"]),
                    text=canonical_transcript(
                        " ".join(str(segment["text"]).split()),
                        "Tiron epoch turn text",
                    ),
                )
                for segment in segments
            )
            total_transcript_bytes += sum(
                len(turn.text.encode("utf-8")) for turn in epoch_turns
            )
            if total_transcript_bytes > MAX_TRANSCRIPT_BYTES:
                raise ValueError("meeting transcript exceeds the bounded contract")
            epochs.append(
                SpeakerEpoch(
                    index=epoch_index,
                    start_sample=start_sample,
                    end_sample=end_sample,
                    speakers=epoch_speakers,
                    turns=epoch_turns,
                )
            )

    if observed_language is None:
        raise ValueError("meeting epoch transcription produced no language")
    reconciliation = reconcile_speaker_epochs(epochs)
    degradation: SpeakerCapacityDegradation | None = None
    if first_saturated_epoch is not None:
        degradation = SpeakerCapacityDegradation(
            scope="decode_window",
            start_sample=first_saturated_epoch[0],
            end_sample=first_saturated_epoch[1],
            observed_speaker_count=TIRON_DECODE_SPEAKER_LIMIT,
            speaker_limit=TIRON_DECODE_SPEAKER_LIMIT,
        )
    elif reconciliation.session_speaker_ceiling_reached:
        degradation = SpeakerCapacityDegradation(
            scope="meeting",
            start_sample=0,
            end_sample=audio.frame_count,
            observed_speaker_count=MEETING_SESSION_SPEAKER_LIMIT,
            speaker_limit=MEETING_SESSION_SPEAKER_LIMIT,
        )
    return SourceTimeMeetingTranscription(
        language=observed_language,
        session_speaker_ids=reconciliation.session_speaker_ids,
        turns=reconciliation.turns,
        num_decode_windows=total_windows,
        capacity_degradation=degradation,
    )


def _epoch_speaker(
    *,
    speaker: str,
    segments: list[object],
    source_pcm: bytes,
    source_offset: int,
    speaker_encoder: SpeakerEmbeddingEncoder,
) -> EpochSpeaker:
    target_intervals = _speaker_intervals(segments, speaker=speaker)
    other_intervals = _speaker_intervals(segments, speaker=speaker, invert=True)
    clean_intervals = _subtract_intervals(target_intervals, other_intervals)
    clean_sample_count = sum(end - start for start, end in clean_intervals)
    if clean_sample_count < MINIMUM_STABLE_SPEAKER_EVIDENCE_SAMPLES:
        embedding = None
    else:
        pcm_parts = [
            source_pcm[(source_offset + start) * 2 : (source_offset + end) * 2]
            for start, end in clean_intervals
        ]
        raw_embedding = speaker_encoder.encode_pcm16(b"".join(pcm_parts))
        embedding = tuple(float(value) for value in raw_embedding)
    return EpochSpeaker(
        local_speaker_id=speaker,
        embedding=embedding,
        clean_speech_sample_count=clean_sample_count,
    )


def _speaker_intervals(
    segments: list[object],
    *,
    speaker: str,
    invert: bool = False,
) -> list[tuple[int, int]]:
    intervals: list[tuple[int, int]] = []
    for value in segments:
        if not isinstance(value, dict):
            raise ValueError("validated Tiron segment changed shape")
        is_speaker = value.get("speaker") == speaker
        if is_speaker == invert:
            continue
        start = value.get("startSample")
        end = value.get("endSample")
        if (
            not isinstance(start, int)
            or isinstance(start, bool)
            or not isinstance(end, int)
            or isinstance(end, bool)
        ):
            raise ValueError("validated Tiron segment bounds changed shape")
        intervals.append((start, end))
    return _merged_intervals(intervals)


def _merged_intervals(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(intervals):
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    return merged


def _subtract_intervals(
    targets: list[tuple[int, int]],
    blockers: list[tuple[int, int]],
) -> list[tuple[int, int]]:
    clean: list[tuple[int, int]] = []
    for target_start, target_end in targets:
        cursor = target_start
        for blocker_start, blocker_end in blockers:
            if blocker_end <= cursor:
                continue
            if blocker_start >= target_end:
                break
            if blocker_start > cursor:
                clean.append((cursor, min(blocker_start, target_end)))
            cursor = max(cursor, blocker_end)
            if cursor >= target_end:
                break
        if cursor < target_end:
            clean.append((cursor, target_end))
    return clean


def _write_pcm16_wav(path: Path, pcm_bytes: bytes) -> None:
    if not pcm_bytes or len(pcm_bytes) % 2 != 0:
        raise ValueError("meeting epoch PCM is invalid")
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(pcm_audio.SAMPLE_RATE_HZ)
        output.writeframes(pcm_bytes)
