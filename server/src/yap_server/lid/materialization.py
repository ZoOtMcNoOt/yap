from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import wave

from .component_lock import LidComponentLock
from .policy import LidProbeSelection, LidProbeWindow
from .worker_contract import LidWorkerRequest, load_lid_worker_request


_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_STAGED_DIRECTORY = re.compile(r"^lid-[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_MAX_SOURCE_SAMPLES = 16_000 * 4 * 60 * 60
_MAX_WAV_OVERHEAD_BYTES = 64 * 1024
_REQUEST_FILE_NAME = "request.json"
_REQUEST_STAGING_FILE_NAME = ".request.json.part"
_ALLOWED_ARTIFACTS = frozenset(
    {
        _REQUEST_FILE_NAME,
        _REQUEST_STAGING_FILE_NAME,
        "probe-0.wav",
        "probe-1.wav",
    }
)


@dataclass(frozen=True)
class LidMaterializedRequest:
    root: Path
    request_path: Path
    request: LidWorkerRequest
    _root_device: int = field(repr=False)
    _root_inode: int = field(repr=False)


@dataclass(frozen=True)
class LidPcmProbe:
    index: int
    source_start_sample: int
    source_end_sample: int
    voiced_samples: int
    pcm_bytes: bytes = field(repr=False)


def canonical_lid_source_samples(path: Path, lock: LidComponentLock) -> int:
    """Inspect a canonical source through the same no-follow boundary."""

    if not isinstance(lock, LidComponentLock):
        raise TypeError("lock must be a validated LidComponentLock")
    try:
        with _open_canonical_source(path) as source:
            with wave.open(source, "rb") as reader:
                return _validate_source(reader, source)
    except (EOFError, wave.Error) as error:
        raise ValueError("LID source is not a valid PCM WAV") from error


def materialize_lid_worker_request(
    *,
    source_wav: Path,
    destination: Path,
    request_id: str,
    selection: LidProbeSelection,
    lock: LidComponentLock,
    ensure_active: Callable[[], None] = lambda: None,
) -> LidMaterializedRequest:
    """Extract fixed source spans and publish request.json as the final marker."""

    destination = Path(destination)
    _validate_materialization_start(destination, request_id, lock)
    ensure_active()
    try:
        with _open_canonical_source(source_wav) as source:
            with wave.open(source, "rb") as reader:
                source_samples = _validate_source(reader, source)
                windows = _validate_selection(selection, source_samples, lock)
                probes: list[LidPcmProbe] = []
                for window in windows:
                    ensure_active()
                    pcm = _extract_probe_pcm(reader, window, lock)
                    probes.append(
                        LidPcmProbe(
                            index=window.index,
                            source_start_sample=window.source_start_sample,
                            source_end_sample=window.source_end_sample,
                            voiced_samples=window.voiced_samples,
                            pcm_bytes=pcm,
                        )
                    )
                    ensure_active()
    except (EOFError, wave.Error) as error:
        raise ValueError("LID source is not a valid PCM WAV") from error
    return materialize_lid_pcm_request(
        destination=destination,
        request_id=request_id,
        source_samples=source_samples,
        probes=probes,
        lock=lock,
        ensure_active=ensure_active,
    )


def materialize_lid_pcm_request(
    *,
    destination: Path,
    request_id: str,
    source_samples: int,
    probes: Sequence[LidPcmProbe],
    lock: LidComponentLock,
    ensure_active: Callable[[], None] = lambda: None,
) -> LidMaterializedRequest:
    """Publish validated probe PCM with one atomic request marker."""

    if (
        not isinstance(source_samples, int)
        or isinstance(source_samples, bool)
        or not 1 <= source_samples <= _MAX_SOURCE_SAMPLES
    ):
        raise ValueError("LID source sample count is invalid")
    destination = Path(destination)
    _validate_materialization_start(destination, request_id, lock)
    selection = LidProbeSelection(
        status="selected",
        reason="two_probes_selected",
        windows=tuple(
            LidProbeWindow(
                index=probe.index,
                source_start_sample=probe.source_start_sample,
                source_end_sample=probe.source_end_sample,
                voiced_samples=probe.voiced_samples,
            )
            for probe in probes
        ),
    )
    windows = _validate_selection(selection, source_samples, lock)
    if len(probes) != len(windows):
        raise ValueError("LID PCM probes do not match the selected windows")
    encoded_probes: list[tuple[LidProbeWindow, bytes]] = []
    for window, probe in zip(windows, probes, strict=True):
        if not isinstance(probe, LidPcmProbe) or not isinstance(probe.pcm_bytes, bytes):
            raise ValueError("LID PCM probe is invalid")
        expected_bytes = (
            window.source_end_sample - window.source_start_sample
        ) * lock.policy.sample_width_bytes
        if len(probe.pcm_bytes) != expected_bytes:
            raise ValueError("LID PCM probe length differs from its source span")
        encoded_probes.append((window, _encode_probe(probe.pcm_bytes, lock)))
    ensure_active()
    os.mkdir(destination, mode=0o700)
    owned = destination.lstat()
    try:
        references: list[dict[str, object]] = []
        for window, encoded in encoded_probes:
            ensure_active()
            file_name = f"probe-{window.index}.wav"
            _write_new_synced(destination / file_name, encoded)
            references.append(
                {
                    "index": window.index,
                    "fileName": file_name,
                    "wavSha256": hashlib.sha256(encoded).hexdigest(),
                    "sourceStartSample": window.source_start_sample,
                    "sourceEndSample": window.source_end_sample,
                    "voicedSamples": window.voiced_samples,
                }
            )
        payload = {
            "schemaVersion": 1,
            "requestId": request_id,
            "sourceSamples": source_samples,
            "probes": references,
        }
        encoded_request = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        staging_request = destination / _REQUEST_STAGING_FILE_NAME
        _write_new_synced(staging_request, encoded_request)
        request = load_lid_worker_request(staging_request, lock)
        ensure_active()
        request_path = destination / _REQUEST_FILE_NAME
        os.replace(staging_request, request_path)
        _sync_directory(destination)
        return LidMaterializedRequest(
            root=destination,
            request_path=request_path,
            request=request,
            _root_device=owned.st_dev,
            _root_inode=owned.st_ino,
        )
    except BaseException:
        try:
            _remove_owned_directory(
                destination,
                expected_device=owned.st_dev,
                expected_inode=owned.st_ino,
            )
        except Exception as cleanup_error:
            raise RuntimeError(
                "LID request failed and its private staging could not be removed"
            ) from cleanup_error
        raise


def remove_materialized_lid_request(request: LidMaterializedRequest) -> None:
    """Remove only the exact private directory returned by this module."""

    if not isinstance(request, LidMaterializedRequest):
        raise TypeError("request must be a LidMaterializedRequest")
    _remove_owned_directory(
        request.root,
        expected_device=request._root_device,
        expected_inode=request._root_inode,
    )


def reconcile_stale_lid_requests(work_root: Path) -> int:
    """Remove only exact transient directories left by an interrupted runtime."""

    root = Path(work_root)
    metadata = root.lstat()
    if _is_link_or_reparse(metadata) or not stat.S_ISDIR(metadata.st_mode):
        raise RuntimeError("LID work root changed before startup reconciliation")
    resolved = root.resolve(strict=True)
    opened = os.stat(resolved)
    if (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino):
        raise RuntimeError("LID work root changed before startup reconciliation")

    removed = 0
    for child in sorted(root.iterdir(), key=lambda value: value.name):
        if _STAGED_DIRECTORY.fullmatch(child.name) is None:
            raise RuntimeError("LID work root contains an unexpected entry")
        child_metadata = child.lstat()
        if _is_link_or_reparse(child_metadata) or not stat.S_ISDIR(
            child_metadata.st_mode
        ):
            raise RuntimeError("stale LID request is not a real directory")
        _remove_owned_directory(
            child,
            expected_device=child_metadata.st_dev,
            expected_inode=child_metadata.st_ino,
        )
        removed += 1

    after = root.lstat()
    if (after.st_dev, after.st_ino) != (metadata.st_dev, metadata.st_ino):
        raise RuntimeError("LID work root changed during startup reconciliation")
    return removed


def _validate_selection(
    selection: LidProbeSelection,
    source_samples: int,
    lock: LidComponentLock,
) -> tuple[LidProbeWindow, ...]:
    if (
        not isinstance(selection, LidProbeSelection)
        or selection.status != "selected"
        or selection.reason != "two_probes_selected"
        or len(selection.windows) != lock.policy.maximum_windows
        or source_samples < lock.policy.minimum_source_samples
    ):
        raise ValueError("LID probe selection is not runnable")
    previous_end = 0
    for position, window in enumerate(selection.windows):
        if not isinstance(window, LidProbeWindow):
            raise ValueError("LID probe selection contains an invalid window")
        values = (
            window.index,
            window.source_start_sample,
            window.source_end_sample,
            window.voiced_samples,
        )
        if any(
            not isinstance(value, int) or isinstance(value, bool)
            for value in values
        ):
            raise ValueError("LID probe selection contains invalid numeric evidence")
        span = window.source_end_sample - window.source_start_sample
        if (
            window.index != position
            or window.source_start_sample < previous_end
            or window.source_start_sample < 0
            or window.source_end_sample > source_samples
            or span < 1
            or span > lock.policy.maximum_window_samples
            or window.voiced_samples < lock.policy.minimum_voiced_samples_per_window
            or window.voiced_samples > span
        ):
            raise ValueError("LID probe selection violates the locked policy")
        previous_end = window.source_end_sample
    return selection.windows


def _validate_materialization_start(
    destination: Path,
    request_id: str,
    lock: LidComponentLock,
) -> None:
    if not isinstance(lock, LidComponentLock):
        raise TypeError("lock must be a validated LidComponentLock")
    if not isinstance(request_id, str) or _REQUEST_ID.fullmatch(request_id) is None:
        raise ValueError("LID request ID is invalid")
    _validate_real_directory(destination.parent, "LID request parent")
    if _lstat(destination) is not None:
        raise FileExistsError("LID request destination already exists")


def _open_canonical_source(path: Path) -> io.BufferedReader:
    path = Path(path)
    metadata = _lstat(path)
    maximum_bytes = _MAX_SOURCE_SAMPLES * 2 + _MAX_WAV_OVERHEAD_BYTES
    if (
        metadata is None
        or _is_link_or_reparse(metadata)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_size > maximum_bytes
    ):
        raise ValueError("LID source must be a bounded regular PCM WAV")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise ValueError("LID source could not be opened safely") from error
    opened = os.fstat(descriptor)
    if (
        not stat.S_ISREG(opened.st_mode)
        or (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino)
        or opened.st_size != metadata.st_size
    ):
        os.close(descriptor)
        raise ValueError("LID source changed before it was opened")
    return os.fdopen(descriptor, "rb")


def _validate_source(reader: wave.Wave_read, source: io.BufferedReader) -> int:
    if (
        reader.getnchannels() != 1
        or reader.getsampwidth() != 2
        or reader.getframerate() != 16_000
        or reader.getcomptype() != "NONE"
    ):
        raise ValueError("LID source must be canonical mono PCM16 at 16 kHz")
    source_samples = reader.getnframes()
    if not 1 <= source_samples <= _MAX_SOURCE_SAMPLES:
        raise ValueError("LID source duration is outside the accepted bound")
    if os.fstat(source.fileno()).st_size > source_samples * 2 + _MAX_WAV_OVERHEAD_BYTES:
        raise ValueError("LID source WAV overhead exceeds its bound")
    return source_samples


def _extract_probe_pcm(
    reader: wave.Wave_read,
    window: LidProbeWindow,
    lock: LidComponentLock,
) -> bytes:
    frame_count = window.source_end_sample - window.source_start_sample
    reader.setpos(window.source_start_sample)
    pcm = reader.readframes(frame_count)
    if len(pcm) != frame_count * lock.policy.sample_width_bytes:
        raise ValueError("LID source ended before the selected probe")
    return pcm


def _encode_probe(pcm: bytes, lock: LidComponentLock) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as writer:
        writer.setnchannels(lock.policy.channel_count)
        writer.setsampwidth(lock.policy.sample_width_bytes)
        writer.setframerate(lock.policy.sample_rate_hz)
        writer.writeframes(pcm)
    return output.getvalue()


def _write_new_synced(path: Path, body: bytes) -> None:
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as target:
            target.write(body)
            target.flush()
            os.fsync(target.fileno())
    finally:
        os.close(descriptor)


def _remove_owned_directory(
    path: Path,
    *,
    expected_device: int,
    expected_inode: int,
) -> None:
    metadata = path.lstat()
    if (
        _is_link_or_reparse(metadata)
        or not stat.S_ISDIR(metadata.st_mode)
        or (metadata.st_dev, metadata.st_ino) != (expected_device, expected_inode)
    ):
        raise RuntimeError("private LID request directory changed before cleanup")
    for child in path.iterdir():
        if child.name not in _ALLOWED_ARTIFACTS:
            raise RuntimeError("private LID request contains an unexpected artifact")
        child_metadata = child.lstat()
        if _is_link_or_reparse(child_metadata) or not stat.S_ISREG(
            child_metadata.st_mode
        ):
            raise RuntimeError("private LID request artifact changed before cleanup")
        child.unlink()
    path.rmdir()


def _validate_real_directory(path: Path, label: str) -> None:
    metadata = _lstat(path)
    if (
        metadata is None
        or _is_link_or_reparse(metadata)
        or not stat.S_ISDIR(metadata.st_mode)
    ):
        raise ValueError(f"{label} must be a real directory")


def _lstat(path: Path) -> os.stat_result | None:
    try:
        return path.lstat()
    except FileNotFoundError:
        return None


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
