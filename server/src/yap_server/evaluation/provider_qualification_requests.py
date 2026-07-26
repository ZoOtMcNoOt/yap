from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat
from typing import Mapping

from yap_server.evaluation.duration_tracks import LoadedDurationTrack
from yap_server.evaluation.provider_runtime_observations import QualificationRequest
from yap_server.pools.batch_contract import AsrRouteDecision, BatchAsrJob
from yap_server.pools.model_lock import ModelPoolLock
from yap_server.pools.utterance_plan import (
    build_utterance_plan,
    publish_utterance_plan,
)


_NO_VAD_EVIDENCE_SHA256 = hashlib.sha256(
    b"provider-runtime-qualification-no-vad"
).hexdigest()
_SYSTEM_POOLS = {
    "vllm-cohere-batch": "cohere-batch",
    "nemo-nemotron-finalized": "nemotron-batch",
}


class LockedProviderRequestFactory:
    """Build hash-bound private jobs for one provider qualification runtime."""

    def __init__(
        self,
        *,
        system_id: str,
        provider_id: str,
        catalog_language: str,
        provider_language: str,
        lock: ModelPoolLock,
        tracks: Mapping[int, LoadedDurationTrack],
        output_root: Path,
        environ: Mapping[str, str] = os.environ,
    ) -> None:
        expected_pool = _SYSTEM_POOLS.get(system_id)
        if expected_pool is None or lock.pool_id != expected_pool:
            raise ValueError("qualification system and model pool do not match")
        if not provider_id or not catalog_language or not provider_language:
            raise ValueError("qualification route identity is invalid")
        cache_root = _private_cache_root(environ)
        copied_tracks = dict(tracks)
        if not copied_tracks or any(
            isinstance(samples, bool)
            or not isinstance(samples, int)
            or samples < 1
            or _track_duration(track) != samples
            or not _inside_cache(track.audio_path, cache_root)
            for samples, track in copied_tracks.items()
        ):
            raise ValueError("qualification duration tracks are invalid")
        self._system_id = system_id
        self._provider_id = provider_id
        self._catalog_language = catalog_language
        self._provider_language = provider_language
        self._lock = lock
        self._tracks = copied_tracks
        self._output_root = _prepare_private_output_root(
            output_root,
            cache_root=cache_root,
        )
        self._result_root = self._output_root / "results"
        self._plan_root = self._output_root / "utterance-plans"
        for directory in (self._result_root, self._plan_root):
            directory.mkdir(mode=0o700)
        self._plans: dict[int, tuple[Path, str]] = {}

    def create(
        self,
        *,
        load_case_id: str,
        concurrency: int,
        ordinal: int,
        duration_samples: int,
    ) -> QualificationRequest:
        track = self._tracks.get(duration_samples)
        if track is None:
            raise ValueError("runtime load case has no exact-duration track")
        job_id = f"{load_case_id}-c{concurrency}-{ordinal}"
        result_path = self._result_root / f"{job_id}.json"
        if result_path.exists() or result_path.is_symlink():
            raise ValueError("qualification result identity already exists")
        audio = track.manifest.get("audio")
        if not isinstance(audio, dict) or not isinstance(audio.get("sha256"), str):
            raise ValueError("qualification track omitted its audio identity")
        plan_path: Path | None = None
        plan_sha256: str | None = None
        if self._system_id == "nemo-nemotron-finalized":
            plan_path, plan_sha256 = self._utterance_plan(
                duration_samples,
                input_sha256=audio["sha256"],
            )
        return QualificationRequest(
            job=BatchAsrJob(
                job_id=job_id,
                input_path=track.audio_path,
                result_path=result_path,
                language=self._catalog_language,
                input_sha256=audio["sha256"],
                route=AsrRouteDecision(
                    provider_id=self._provider_id,
                    pool_id=self._lock.pool_id,
                    execution_mode=(
                        "dynamicBatch"
                        if self._provider_language == "auto"
                        else "fixedBatch"
                    ),
                    model_revision=self._lock.model_revision,
                    provider_language=self._provider_language,
                ),
                utterance_plan_path=plan_path,
                utterance_plan_sha256=plan_sha256,
            ),
            audio_samples=duration_samples,
        )

    def _utterance_plan(
        self,
        duration_samples: int,
        *,
        input_sha256: str,
    ) -> tuple[Path, str]:
        existing = self._plans.get(duration_samples)
        if existing is not None:
            return existing
        path = self._plan_root / f"{duration_samples}.json"
        plan = build_utterance_plan(
            input_wav_sha256=input_sha256,
            input_sample_count=duration_samples,
            source_sample_count=duration_samples,
            vad_status="error",
            vad_evidence_sha256=_NO_VAD_EVIDENCE_SHA256,
            vad_intervals=(),
        )
        identity = publish_utterance_plan(path, plan)
        self._plans[duration_samples] = (path, identity)
        return path, identity


def _track_duration(track: object) -> int | None:
    if not isinstance(track, LoadedDurationTrack):
        return None
    audio = track.manifest.get("audio")
    value = audio.get("durationSamples") if isinstance(audio, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _private_cache_root(environ: Mapping[str, str]) -> Path:
    raw = environ.get("YAP_EVAL_CACHE", "").strip()
    if not raw:
        raise ValueError("YAP_EVAL_CACHE is required for provider qualification")
    requested = Path(raw)
    if not requested.is_absolute() or requested.is_symlink():
        raise ValueError("YAP_EVAL_CACHE must be an absolute real directory")
    repository = Path(__file__).resolve().parents[4]
    resolved = requested.resolve(strict=True)
    if resolved == repository or repository in resolved.parents:
        raise ValueError("YAP_EVAL_CACHE must remain outside the repository")
    metadata = resolved.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("YAP_EVAL_CACHE must be a real directory")
    if os.name == "posix" and stat.S_IMODE(metadata.st_mode) & 0o077:
        raise ValueError("YAP_EVAL_CACHE must use private permissions")
    return resolved


def _inside_cache(path: Path, cache_root: Path) -> bool:
    if not path.is_absolute() or path.is_symlink():
        return False
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        return False
    return cache_root in resolved.parents


def _prepare_private_output_root(path: Path, *, cache_root: Path) -> Path:
    if not path.is_absolute():
        raise ValueError("qualification output root must be absolute")
    repository = Path(__file__).resolve().parents[4]
    prospective = path.resolve(strict=False)
    if prospective == repository or repository in prospective.parents:
        raise ValueError("qualification output must remain outside the repository")
    if prospective == cache_root or cache_root not in prospective.parents:
        raise ValueError("qualification output must remain inside YAP_EVAL_CACHE")
    path.mkdir(mode=0o700, parents=True, exist_ok=False)
    resolved = path.resolve(strict=True)
    metadata = resolved.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("qualification output root must be a real directory")
    if os.name == "posix" and stat.S_IMODE(metadata.st_mode) & 0o077:
        raise ValueError("qualification output root must use private permissions")
    return resolved
