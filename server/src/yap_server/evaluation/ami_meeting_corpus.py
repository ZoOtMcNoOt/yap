"""Private-cache boundary for the pinned AMI long-meeting comparator."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path, PurePosixPath
import stat
from typing import Mapping

from yap_server.evaluation.ami_meeting_lock import (
    MAX_ANNOTATION_ARCHIVE_BYTES,
    MAX_AUDIO_BYTES,
    AmiArtifactLock,
    AmiMeetingCorpusLock,
)
from yap_server.evaluation.ami_word_timeline import (
    AmiWordTimeline,
    count_cross_speaker_overlap_words,
    parse_ami_word_timeline,
)
from yap_server.evaluation.private_evaluation_artifact import (
    read_bounded_regular_file,
)
from yap_server.pools.batch_asr_worker import PcmAudio, decode_pcm16_wav


@dataclass(frozen=True, slots=True)
class AmiAudioInspection:
    condition_id: str
    encoded_size: int
    encoded_sha256: str


@dataclass(frozen=True, slots=True)
class AmiMeetingInspection:
    corpus_id: str
    release: str
    meeting_id: str
    language_bcp47: str
    scenario_split: str
    asr_split: str
    promotion_eligible: bool
    exposure_status: str
    sample_rate_hz: int
    frame_count: int
    word_element_count: int
    vocal_sound_count: int
    disfluency_marker_count: int
    gap_count: int
    cross_speaker_overlap_word_count: int
    annotations_sha256: str
    audio: tuple[AmiAudioInspection, ...]


def load_ami_word_timeline(
    lock: AmiMeetingCorpusLock,
    *,
    environ: Mapping[str, str] = os.environ,
) -> AmiWordTimeline:
    """Verify the locked archive and return private timed words without extraction."""

    _require_lock(lock)
    cache_root = _private_cache_root(environ)
    body = _read_locked_artifact(
        cache_root,
        lock.annotations.artifact,
        field="AMI annotation archive",
        maximum_bytes=MAX_ANNOTATION_ARCHIVE_BYTES,
    )
    return parse_ami_word_timeline(body, lock)


def load_ami_condition_audio(
    lock: AmiMeetingCorpusLock,
    condition_id: str,
    *,
    environ: Mapping[str, str] = os.environ,
) -> PcmAudio:
    """Load one exact long-form condition through the batch worker PCM boundary."""

    _require_lock(lock)
    selected = next(
        (item for item in lock.audio.conditions if item.identifier == condition_id),
        None,
    )
    if selected is None:
        raise ValueError("AMI audio condition is not locked")
    cache_root = _private_cache_root(environ)
    encoded = _read_locked_artifact(
        cache_root,
        selected.artifact,
        field=f"AMI {condition_id} audio",
        maximum_bytes=MAX_AUDIO_BYTES,
    )
    try:
        audio = decode_pcm16_wav(
            encoded,
            max_audio_seconds=(
                lock.audio.frame_count + lock.audio.sample_rate_hz - 1
            )
            // lock.audio.sample_rate_hz,
        )
    except ValueError as error:
        raise ValueError(f"AMI {condition_id} audio violates the PCM contract") from error
    if (
        audio.sample_rate != lock.audio.sample_rate_hz
        or audio.frame_count != lock.audio.frame_count
        or len(audio.pcm_bytes)
        != lock.audio.frame_count
        * lock.audio.channel_count
        * lock.audio.sample_width_bytes
    ):
        raise ValueError(f"AMI {condition_id} audio differs from the locked shape")
    return audio


def inspect_ami_meeting_corpus(
    lock: AmiMeetingCorpusLock,
    *,
    environ: Mapping[str, str] = os.environ,
) -> AmiMeetingInspection:
    """Return aggregate-only corpus evidence; transcript text remains private."""

    timeline = load_ami_word_timeline(lock, environ=environ)
    audio_inspections: list[AmiAudioInspection] = []
    for condition in lock.audio.conditions:
        audio = load_ami_condition_audio(lock, condition.identifier, environ=environ)
        audio_inspections.append(
            AmiAudioInspection(
                condition_id=condition.identifier,
                encoded_size=condition.artifact.size,
                encoded_sha256=audio.sha256,
            )
        )
    identity = lock.identity
    return AmiMeetingInspection(
        corpus_id=identity.corpus_id,
        release=identity.release,
        meeting_id=identity.meeting_id,
        language_bcp47=identity.language_bcp47,
        scenario_split=identity.scenario_split,
        asr_split=identity.asr_split,
        promotion_eligible=lock.usage.promotion_eligible,
        exposure_status=lock.usage.exposure_status,
        sample_rate_hz=lock.audio.sample_rate_hz,
        frame_count=lock.audio.frame_count,
        word_element_count=len(timeline.words),
        vocal_sound_count=timeline.vocal_sound_count,
        disfluency_marker_count=timeline.disfluency_marker_count,
        gap_count=timeline.gap_count,
        cross_speaker_overlap_word_count=count_cross_speaker_overlap_words(
            timeline.merged_words
        ),
        annotations_sha256=lock.annotations.artifact.sha256,
        audio=tuple(audio_inspections),
    )


def _read_locked_artifact(
    cache_root: Path,
    artifact: AmiArtifactLock,
    *,
    field: str,
    maximum_bytes: int,
) -> bytes:
    portable = PurePosixPath(artifact.cache_path)
    path = cache_root.joinpath(*portable.parts)
    body = read_bounded_regular_file(
        path,
        maximum_bytes=min(artifact.size, maximum_bytes),
        field=field,
        containment_root=cache_root,
    )
    if len(body) != artifact.size:
        raise ValueError(f"{field} size differs from the lock")
    if hashlib.sha256(body).hexdigest() != artifact.sha256:
        raise ValueError(f"{field} SHA-256 differs from the lock")
    return body


def _private_cache_root(environ: Mapping[str, str]) -> Path:
    raw = environ.get("YAP_EVAL_CACHE", "").strip()
    if not raw:
        raise ValueError("YAP_EVAL_CACHE is required for AMI evidence")
    requested = Path(raw)
    if not requested.is_absolute() or requested.is_symlink():
        raise ValueError("YAP_EVAL_CACHE must be an absolute real directory")
    resolved = requested.resolve(strict=True)
    repository = Path(__file__).resolve().parents[4]
    if resolved == repository or repository in resolved.parents:
        raise ValueError("YAP_EVAL_CACHE must remain outside the repository")
    metadata = resolved.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("YAP_EVAL_CACHE must be a real directory")
    if os.name == "posix" and stat.S_IMODE(metadata.st_mode) & 0o077:
        raise ValueError("YAP_EVAL_CACHE must use private permissions")
    return resolved


def _require_lock(lock: AmiMeetingCorpusLock) -> None:
    if not isinstance(lock, AmiMeetingCorpusLock):
        raise TypeError("lock must be an AmiMeetingCorpusLock")
