"""Bounded same-open reads for private evaluation trust artifacts."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from typing import Iterable


class _DuplicateJsonKey(ValueError):
    pass


def read_bounded_regular_file(
    path: Path,
    *,
    maximum_bytes: int,
    field: str,
    containment_root: Path | None = None,
) -> bytes:
    """Read one regular file through the same handle used for its bounds check."""

    if not isinstance(maximum_bytes, int) or isinstance(maximum_bytes, bool):
        raise ValueError(f"{field} size bound is invalid")
    _drive, path_without_drive = os.path.splitdrive(str(path))
    if maximum_bytes < 1 or path.is_symlink() or ":" in path_without_drive:
        raise ValueError(f"{field} must be a real file")
    try:
        root = _containment_boundary(containment_root, field)
        requested = Path(os.path.abspath(path))
        resolved = path.resolve(strict=True)
        before = resolved.lstat()
    except OSError as error:
        raise ValueError(f"{field} must be a real file") from error
    if root is not None and not _is_beneath(resolved, root):
        raise ValueError(f"{field} escaped its private containment root")
    if root is None and not _same_path(resolved, requested):
        raise ValueError(f"{field} must not traverse a link or junction")
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise ValueError(f"{field} must be a real file")

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOINHERIT", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(resolved, flags)
    except OSError as error:
        raise ValueError(f"{field} could not be opened safely") from error
    try:
        source = os.fdopen(descriptor, "rb", closefd=True)
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise
    with source:
        opened = os.fstat(source.fileno())
        if (
            not stat.S_ISREG(opened.st_mode)
            or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
        ):
            raise ValueError(f"{field} changed before it was opened")
        opened_path = _opened_file_path(source.fileno())
        if opened_path is None or not _same_path(opened_path, resolved):
            raise ValueError(f"{field} changed before it was opened")
        if root is not None and not _is_beneath(opened_path, root):
            raise ValueError(f"{field} escaped its private containment root")
        if not 1 <= opened.st_size <= maximum_bytes:
            raise ValueError(f"{field} size is invalid")
        body = source.read(maximum_bytes + 1)
        after = os.fstat(source.fileno())
    if (
        len(body) != opened.st_size
        or len(body) > maximum_bytes
        or (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        != (
            opened.st_dev,
            opened.st_ino,
            opened.st_size,
            opened.st_mtime_ns,
            opened.st_ctime_ns,
        )
    ):
        raise ValueError(f"{field} changed while it was read")
    return body


def read_json_object_with_identity(
    path: Path,
    *,
    maximum_bytes: int,
    field: str,
    expected_sha256: str | None = None,
    containment_root: Path | None = None,
) -> tuple[dict[str, object], str]:
    body = read_bounded_regular_file(
        path,
        maximum_bytes=maximum_bytes,
        field=field,
        containment_root=containment_root,
    )
    return decode_json_object_with_identity(
        body,
        field=field,
        expected_sha256=expected_sha256,
    )


def decode_json_object_with_identity(
    body: bytes,
    *,
    field: str,
    expected_sha256: str | None = None,
) -> tuple[dict[str, object], str]:
    """Decode JSON bytes already captured through a trusted bounded read."""

    identity = hashlib.sha256(body).hexdigest()
    if expected_sha256 is not None and identity != expected_sha256:
        raise ValueError(f"{field} differs from its out-of-band digest")
    try:
        payload = json.loads(body, object_pairs_hook=_unique_json_object)
    except _DuplicateJsonKey as error:
        raise ValueError(f"{field} contains a duplicate JSON key") from error
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise ValueError(f"{field} is not valid JSON") from error
    if not isinstance(payload, dict):
        raise ValueError(f"{field} must be an object")
    return payload, identity


def _is_beneath(path: Path, root: Path) -> bool:
    candidate = os.path.normcase(os.path.abspath(path))
    boundary = os.path.normcase(os.path.abspath(root))
    try:
        return (
            os.path.commonpath((candidate, boundary)) == boundary
            and candidate != boundary
        )
    except ValueError:
        return False


def _same_path(first: Path, second: Path) -> bool:
    return os.path.normcase(os.path.abspath(first)) == os.path.normcase(
        os.path.abspath(second)
    )


def _containment_boundary(root: Path | None, field: str) -> Path | None:
    if root is None:
        return None
    if not root.is_absolute():
        raise ValueError(f"{field} containment root is invalid")
    boundary = Path(os.path.abspath(root))
    try:
        metadata = boundary.lstat()
    except OSError as error:
        raise ValueError(f"{field} containment root is invalid") from error
    is_junction = getattr(boundary, "is_junction", lambda: False)
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or is_junction()
    ):
        raise ValueError(f"{field} containment root is invalid")
    return boundary


def _opened_file_path(descriptor: int) -> Path | None:
    if os.name == "nt":
        return _windows_opened_file_path(descriptor)
    if sys.platform == "darwin":
        return _darwin_opened_file_path(descriptor)
    descriptor_link = Path(f"/proc/self/fd/{descriptor}")
    try:
        return Path(os.readlink(descriptor_link)).resolve(strict=True)
    except OSError:
        return None


def _darwin_opened_file_path(descriptor: int) -> Path | None:
    try:
        import fcntl

        value = fcntl.fcntl(descriptor, 50, b"\0" * 1_024)
        encoded = value.split(b"\0", 1)[0]
        if not encoded:
            return None
        return Path(os.fsdecode(encoded))
    except (AttributeError, ImportError, OSError, TypeError, ValueError):
        return None


def _windows_opened_file_path(descriptor: int) -> Path | None:
    try:
        import ctypes
        import msvcrt

        handle = msvcrt.get_osfhandle(descriptor)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        final_path = kernel32.GetFinalPathNameByHandleW
        final_path.argtypes = [
            ctypes.c_void_p,
            ctypes.c_wchar_p,
            ctypes.c_ulong,
            ctypes.c_ulong,
        ]
        final_path.restype = ctypes.c_ulong
        required = final_path(handle, None, 0, 0)
        if required == 0:
            return None
        buffer = ctypes.create_unicode_buffer(required + 1)
        written = final_path(handle, buffer, len(buffer), 0)
        if written == 0 or written >= len(buffer):
            return None
        value = buffer.value
        if value.startswith("\\\\?\\UNC\\"):
            value = "\\\\" + value[8:]
        elif value.startswith("\\\\?\\"):
            value = value[4:]
        return Path(value)
    except (AttributeError, ImportError, OSError, TypeError, ValueError):
        return None


def _unique_json_object(pairs: Iterable[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise _DuplicateJsonKey(key)
        value[key] = item
    return value
