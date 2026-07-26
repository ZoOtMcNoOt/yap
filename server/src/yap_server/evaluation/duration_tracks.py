from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
from typing import Callable, Mapping, Protocol
from uuid import uuid4
import wave

from yap_server.pools.pcm_audio import MAX_AUDIO_SECONDS, SAMPLE_RATE_HZ


_CASE_ID = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_CHANNELS = 1
_SAMPLE_WIDTH_BYTES = 2
_COPY_FRAMES = SAMPLE_RATE_HZ * 10
_MAX_SEGMENTS = 4096
_MAX_MANIFEST_BYTES = 4 * 1024 * 1024
_MAX_COLLECTION_MANIFEST_BYTES = 64 * 1024


class _Digest(Protocol):
    def update(self, value: bytes) -> None: ...


@dataclass(frozen=True, slots=True)
class LoadedDurationTrack:
    audio_path: Path
    manifest: dict[str, object]


@dataclass(frozen=True, slots=True)
class DurationTrackSpec:
    case_id: str
    duration_samples: int


def load_duration_track(manifest_path: Path) -> LoadedDurationTrack:
    admitted = manifest_path.lstat()
    if _is_link_or_reparse(admitted) or not stat.S_ISREG(admitted.st_mode):
        raise ValueError("duration-track manifest must be a real file")
    resolved = manifest_path.resolve(strict=True)
    metadata = resolved.lstat()
    if _is_link_or_reparse(metadata) or not stat.S_ISREG(metadata.st_mode):
        raise ValueError("duration-track manifest must be a real file")
    if not 1 <= metadata.st_size <= _MAX_MANIFEST_BYTES:
        raise ValueError("duration-track manifest size is invalid")
    encoded = resolved.read_bytes()
    if not 1 <= len(encoded) <= _MAX_MANIFEST_BYTES:
        raise ValueError("duration-track manifest size is invalid")
    try:
        body = json.loads(encoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("duration-track manifest is not valid JSON") from error
    _validate_manifest(body)
    manifest = dict(body)
    audio_path = resolved.parent / "audio.wav"
    inspected = _inspect_source(audio_path)
    audio = manifest["audio"]
    if not isinstance(audio, dict) or (
        audio["sha256"] != inspected.raw_sha256
        or audio["decodedPcmSha256"]
        != inspected.public_descriptor["decodedPcmSha256"]
        or audio["byteLength"] != inspected.public_descriptor["byteLength"]
        or audio["durationSamples"] != inspected.frame_count
    ):
        raise ValueError("duration-track audio differs from its immutable manifest")
    return LoadedDurationTrack(audio_path=audio_path, manifest=manifest)


def build_duration_track(
    *,
    case_id: str,
    duration_samples: int,
    source_paths: list[Path],
    environ: Mapping[str, str] = os.environ,
) -> dict[str, object]:
    """Build one immutable exact-duration PCM runtime control outside Git."""

    _validate_track_spec(DurationTrackSpec(case_id, duration_samples))
    if not source_paths or len(source_paths) > 64:
        raise ValueError("duration track requires one to 64 source WAVs")

    track_root = _runtime_track_root(environ)
    sources = [_inspect_source(path) for path in source_paths]
    if _planned_segment_count(duration_samples, sources) > _MAX_SEGMENTS:
        raise ValueError("duration track exceeds the bounded segment count")
    return _build_duration_track_at_root(
        case_id=case_id,
        duration_samples=duration_samples,
        sources=sources,
        track_root=track_root,
        verify_sources_before_publish=True,
    )


def build_duration_track_collection(
    *,
    collection_id: str,
    tracks: list[DurationTrackSpec],
    source_paths: list[Path],
    manifest_factory: Callable[
        [Mapping[str, dict[str, object]]], tuple[str, bytes]
    ],
    environ: Mapping[str, str] = os.environ,
) -> Path:
    """Build several exact tracks and one caller-defined manifest atomically."""

    if _CASE_ID.fullmatch(collection_id) is None:
        raise ValueError("duration-track collection ID is invalid")
    if not tracks or len(tracks) > 64:
        raise ValueError("duration-track collection requires one to 64 tracks")
    if not source_paths or len(source_paths) > 64:
        raise ValueError("duration track requires one to 64 source WAVs")
    identities: set[str] = set()
    for track in tracks:
        _validate_track_spec(track)
        if track.case_id in identities:
            raise ValueError("duration-track collection case IDs must be unique")
        identities.add(track.case_id)

    track_root = _runtime_track_root(environ)
    destination = track_root / collection_id
    if destination.exists() or destination.is_symlink():
        raise ValueError("duration-track collection already exists and is immutable")
    sources = [_inspect_source(path) for path in source_paths]
    for track in tracks:
        if _planned_segment_count(track.duration_samples, sources) > _MAX_SEGMENTS:
            raise ValueError("duration track exceeds the bounded segment count")

    temporary: Path | None = Path(
        tempfile.mkdtemp(prefix=f".{collection_id}.{uuid4().hex}.", dir=track_root)
    )
    try:
        os.chmod(temporary, 0o700)
        manifests: dict[str, dict[str, object]] = {}
        for track in tracks:
            manifests[track.case_id] = _build_duration_track_at_root(
                case_id=track.case_id,
                duration_samples=track.duration_samples,
                sources=sources,
                track_root=temporary,
                verify_sources_before_publish=False,
            )
        _require_unchanged_sources(sources)
        manifest_name, manifest_bytes = manifest_factory(dict(manifests))
        if (
            not isinstance(manifest_name, str)
            or not manifest_name
            or Path(manifest_name).name != manifest_name
            or "/" in manifest_name
            or "\\" in manifest_name
            or not manifest_name.endswith(".json")
            or not isinstance(manifest_bytes, bytes)
            or not 1 <= len(manifest_bytes) <= _MAX_COLLECTION_MANIFEST_BYTES
        ):
            raise ValueError("duration-track collection manifest is invalid")
        manifest_path = temporary / manifest_name
        with manifest_path.open("xb") as output:
            output.write(manifest_bytes)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(manifest_path, 0o600)
        os.replace(temporary, destination)
        _sync_directory(track_root)
        temporary = None
        return destination
    finally:
        if temporary is not None and temporary.exists():
            shutil.rmtree(temporary)


def _build_duration_track_at_root(
    *,
    case_id: str,
    duration_samples: int,
    sources: list[_Source],
    track_root: Path,
    verify_sources_before_publish: bool,
) -> dict[str, object]:
    destination = track_root / case_id
    if destination.exists() or destination.is_symlink():
        raise ValueError("duration-track case already exists and is immutable")
    temporary: Path | None = Path(
        tempfile.mkdtemp(prefix=f".{case_id}.{uuid4().hex}.", dir=track_root)
    )
    try:
        os.chmod(temporary, 0o700)
        audio_path = temporary / "audio.wav"
        segments, decoded_pcm_sha256 = _write_exact_track(
            audio_path,
            duration_samples=duration_samples,
            sources=sources,
        )
        raw_sha256 = _sha256_file(audio_path)
        body = {
            "schemaVersion": 1,
            "caseId": case_id,
            "runtimeControlKind": _control_kind(segments, len(sources)),
            "audio": {
                "sha256": raw_sha256,
                "decodedPcmSha256": decoded_pcm_sha256,
                "byteLength": audio_path.stat().st_size,
                "durationSamples": duration_samples,
                "sampleRateHz": SAMPLE_RATE_HZ,
                "channels": _CHANNELS,
                "sampleWidthBytes": _SAMPLE_WIDTH_BYTES,
            },
            "sources": [source.public_descriptor for source in sources],
            "segments": segments,
            "accuracySampleIncrement": 0,
        }
        manifest_path = temporary / "manifest.json"
        _write_json(manifest_path, body)
        if verify_sources_before_publish:
            _require_unchanged_sources(sources)
        os.chmod(audio_path, 0o600)
        os.chmod(manifest_path, 0o600)
        os.replace(temporary, destination)
        _sync_directory(track_root)
        temporary = None
        return body
    finally:
        if temporary is not None and temporary.exists():
            shutil.rmtree(temporary)


class _Source:
    def __init__(
        self,
        *,
        path: Path,
        raw_sha256: str,
        decoded_pcm_sha256: str,
        byte_length: int,
        frame_count: int,
    ) -> None:
        self.path = path
        self.raw_sha256 = raw_sha256
        self.frame_count = frame_count
        self.public_descriptor: dict[str, object] = {
            "sha256": raw_sha256,
            "decodedPcmSha256": decoded_pcm_sha256,
            "byteLength": byte_length,
            "frameCount": frame_count,
        }


def _inspect_source(path: Path) -> _Source:
    admitted = path.lstat()
    if _is_link_or_reparse(admitted) or not stat.S_ISREG(admitted.st_mode):
        raise ValueError("duration-track source must be a real file")
    resolved = path.resolve(strict=True)
    metadata = resolved.lstat()
    if _is_link_or_reparse(metadata) or not stat.S_ISREG(metadata.st_mode):
        raise ValueError("duration-track source must be a real file")
    raw_sha256 = _sha256_file(resolved)
    decoded_digest = hashlib.sha256()
    try:
        with wave.open(str(resolved), "rb") as source:
            if (
                source.getnchannels() != _CHANNELS
                or source.getsampwidth() != _SAMPLE_WIDTH_BYTES
                or source.getframerate() != SAMPLE_RATE_HZ
                or source.getcomptype() != "NONE"
                or source.getnframes() < 1
            ):
                raise ValueError(
                    "duration-track source must be mono PCM16 WAV at 16 kHz"
                )
            frame_count = source.getnframes()
            while True:
                body = source.readframes(_COPY_FRAMES)
                if not body:
                    break
                decoded_digest.update(body)
    except (EOFError, wave.Error) as error:
        raise ValueError("duration-track source WAV is invalid") from error
    if _sha256_file(resolved) != raw_sha256:
        raise ValueError("duration-track source changed during inspection")
    return _Source(
        path=resolved,
        raw_sha256=raw_sha256,
        decoded_pcm_sha256=decoded_digest.hexdigest(),
        byte_length=metadata.st_size,
        frame_count=frame_count,
    )


def _require_unchanged_sources(sources: list[_Source]) -> None:
    for source in sources:
        try:
            metadata = source.path.lstat()
            raw_sha256 = _sha256_file(source.path)
        except OSError as error:
            raise ValueError(
                "duration-track source changed during track construction"
            ) from error
        if (
            _is_link_or_reparse(metadata)
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_size != source.public_descriptor["byteLength"]
            or raw_sha256 != source.raw_sha256
        ):
            raise ValueError("duration-track source changed during track construction")


def _write_exact_track(
    path: Path,
    *,
    duration_samples: int,
    sources: list[_Source],
) -> tuple[list[dict[str, object]], str]:
    remaining = duration_samples
    output_start = 0
    source_index = 0
    decoded_digest = hashlib.sha256()
    segments: list[dict[str, object]] = []
    with wave.open(str(path), "wb") as output:
        output.setnchannels(_CHANNELS)
        output.setsampwidth(_SAMPLE_WIDTH_BYTES)
        output.setframerate(SAMPLE_RATE_HZ)
        while remaining > 0:
            source = sources[source_index % len(sources)]
            take = min(source.frame_count, remaining)
            copied = _copy_source_frames(
                output,
                source,
                take,
                decoded_digest,
            )
            if copied != take:
                raise ValueError("duration-track source ended before its declared frame count")
            segments.append(
                {
                    "sourceIndex": source_index % len(sources),
                    "sourceStartSample": 0,
                    "sourceEndSampleExclusive": take,
                    "outputStartSample": output_start,
                    "outputEndSampleExclusive": output_start + take,
                }
            )
            remaining -= take
            output_start += take
            source_index += 1
    if output_start != duration_samples:
        raise RuntimeError("duration-track output length is inconsistent")
    return segments, decoded_digest.hexdigest()


def _copy_source_frames(
    output: wave.Wave_write,
    source: _Source,
    frame_count: int,
    digest: _Digest,
) -> int:
    copied = 0
    with wave.open(str(source.path), "rb") as input_audio:
        while copied < frame_count:
            request = min(_COPY_FRAMES, frame_count - copied)
            body = input_audio.readframes(request)
            if not body:
                break
            if len(body) % _SAMPLE_WIDTH_BYTES != 0:
                raise ValueError("duration-track source returned a partial PCM frame")
            frames = len(body) // _SAMPLE_WIDTH_BYTES
            if frames > request:
                raise ValueError("duration-track source exceeded the requested frame count")
            output.writeframesraw(body)
            digest.update(body)
            copied += frames
    return copied


def _control_kind(segments: list[dict[str, object]], source_count: int) -> str:
    if len(segments) > source_count:
        return "looped"
    if len(segments) > 1:
        return "concatenated"
    return "truncated"


def _validate_manifest(value: object) -> None:
    if not isinstance(value, dict) or set(value) != {
        "schemaVersion",
        "caseId",
        "runtimeControlKind",
        "audio",
        "sources",
        "segments",
        "accuracySampleIncrement",
    }:
        raise ValueError("duration-track manifest fields differ from the contract")
    if value["schemaVersion"] != 1 or value["accuracySampleIncrement"] != 0:
        raise ValueError("duration-track manifest identity is invalid")
    case_id = value["caseId"]
    if not isinstance(case_id, str) or _CASE_ID.fullmatch(case_id) is None:
        raise ValueError("duration-track manifest case ID is invalid")
    audio = value["audio"]
    if not isinstance(audio, dict) or set(audio) != {
        "sha256",
        "decodedPcmSha256",
        "byteLength",
        "durationSamples",
        "sampleRateHz",
        "channels",
        "sampleWidthBytes",
    }:
        raise ValueError("duration-track audio fields differ from the contract")
    if (
        not _valid_sha256(audio["sha256"])
        or not _valid_sha256(audio["decodedPcmSha256"])
        or not _positive_integer(audio["byteLength"])
        or not _positive_integer(audio["durationSamples"])
        or audio["durationSamples"] > SAMPLE_RATE_HZ * MAX_AUDIO_SECONDS
        or audio["sampleRateHz"] != SAMPLE_RATE_HZ
        or audio["channels"] != _CHANNELS
        or audio["sampleWidthBytes"] != _SAMPLE_WIDTH_BYTES
    ):
        raise ValueError("duration-track audio identity is invalid")

    sources = value["sources"]
    if not isinstance(sources, list) or not 1 <= len(sources) <= 64:
        raise ValueError("duration-track sources are invalid")
    for source in sources:
        if not isinstance(source, dict) or set(source) != {
            "sha256",
            "decodedPcmSha256",
            "byteLength",
            "frameCount",
        }:
            raise ValueError("duration-track source fields differ from the contract")
        if (
            not _valid_sha256(source["sha256"])
            or not _valid_sha256(source["decodedPcmSha256"])
            or not _positive_integer(source["byteLength"])
            or not _positive_integer(source["frameCount"])
        ):
            raise ValueError("duration-track source identity is invalid")

    segments = value["segments"]
    if not isinstance(segments, list) or not 1 <= len(segments) <= _MAX_SEGMENTS:
        raise ValueError("duration-track segments are invalid")
    expected_output_start = 0
    for segment in segments:
        if not isinstance(segment, dict) or set(segment) != {
            "sourceIndex",
            "sourceStartSample",
            "sourceEndSampleExclusive",
            "outputStartSample",
            "outputEndSampleExclusive",
        }:
            raise ValueError("duration-track segment fields differ from the contract")
        source_index = segment["sourceIndex"]
        source_start = segment["sourceStartSample"]
        source_end = segment["sourceEndSampleExclusive"]
        output_start = segment["outputStartSample"]
        output_end = segment["outputEndSampleExclusive"]
        if (
            not isinstance(source_index, int)
            or isinstance(source_index, bool)
            or not 0 <= source_index < len(sources)
            or source_start != 0
            or not _positive_integer(source_end)
            or output_start != expected_output_start
            or not _positive_integer(output_end)
            or output_end - output_start != source_end
            or source_end > sources[source_index]["frameCount"]
        ):
            raise ValueError("duration-track segment continuity is invalid")
        expected_output_start = output_end
    if expected_output_start != audio["durationSamples"]:
        raise ValueError("duration-track segments do not cover the audio")
    kind = value["runtimeControlKind"]
    if kind != _control_kind(segments, len(sources)):
        raise ValueError("duration-track control kind is invalid")


def _valid_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _positive_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _planned_segment_count(duration_samples: int, sources: list[_Source]) -> int:
    remaining = duration_samples
    count = 0
    while remaining > 0 and count <= _MAX_SEGMENTS:
        remaining -= min(sources[count % len(sources)].frame_count, remaining)
        count += 1
    return count


def _validate_track_spec(track: DurationTrackSpec) -> None:
    if _CASE_ID.fullmatch(track.case_id) is None:
        raise ValueError("duration-track case ID is invalid")
    if (
        not isinstance(track.duration_samples, int)
        or isinstance(track.duration_samples, bool)
        or not 1 <= track.duration_samples <= SAMPLE_RATE_HZ * MAX_AUDIO_SECONDS
    ):
        raise ValueError("duration-track sample count is invalid")


def _runtime_track_root(environ: Mapping[str, str]) -> Path:
    cache_root = _private_cache_root(environ)
    track_root = cache_root / "runtime-tracks"
    track_root.mkdir(mode=0o700, exist_ok=True)
    _require_private_directory(track_root)
    resolved = track_root.resolve(strict=True)
    repository = Path(__file__).resolve().parents[4]
    if resolved == repository or repository in resolved.parents:
        raise ValueError("duration-track root must remain outside the repository")
    _require_private_directory(resolved)
    return resolved


def _private_cache_root(environ: Mapping[str, str]) -> Path:
    raw = environ.get("YAP_EVAL_CACHE", "").strip()
    if not raw:
        raise ValueError("YAP_EVAL_CACHE is required for duration tracks")
    requested = Path(raw)
    if not requested.is_absolute():
        raise ValueError("YAP_EVAL_CACHE must be an absolute path")
    repository = Path(__file__).resolve().parents[4]
    prospective = requested.resolve(strict=False)
    if prospective == repository or repository in prospective.parents:
        raise ValueError("YAP_EVAL_CACHE must remain outside the repository")
    requested.mkdir(mode=0o700, parents=True, exist_ok=True)
    _require_private_directory(requested)
    resolved = requested.resolve(strict=True)
    if resolved == repository or repository in resolved.parents:
        raise ValueError("YAP_EVAL_CACHE must remain outside the repository")
    _require_private_directory(resolved)
    return resolved


def _require_private_directory(path: Path) -> None:
    metadata = path.lstat()
    if _is_link_or_reparse(metadata) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("evaluation cache path must be a real directory")
    if os.name == "posix" and stat.S_IMODE(metadata.st_mode) & 0o077:
        raise ValueError("evaluation cache directories must use private permissions")


def _is_link_or_reparse(metadata: os.stat_result) -> bool:
    reparse_point = 0x400
    return stat.S_ISLNK(metadata.st_mode) or bool(
        getattr(metadata, "st_file_attributes", 0) & reparse_point
    )


def _sync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for body in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(body)
    return digest.hexdigest()


def _write_json(path: Path, value: dict[str, object]) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as output:
        json.dump(value, output, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a private exact-duration runtime track")
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--duration-samples", required=True, type=int)
    parser.add_argument("--source", action="append", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    result = build_duration_track(
        case_id=arguments.case_id,
        duration_samples=arguments.duration_samples,
        source_paths=arguments.source,
    )
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
