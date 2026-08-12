"""Build and observe the exact owner-private agent admission broker."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import socket
import stat
import struct
import subprocess
from typing import Callable


Runner = Callable[..., subprocess.CompletedProcess[str]]
_MAXIMUM_BROKER_BINARY_BYTES = 64 * 1024 * 1024
_MAXIMUM_BROKER_DOCUMENT_BYTES = 1024 * 1024
_BROKER_BINARY = "yap-agent-admission-broker"
_BROKER_ARGUMENTS = frozenset(
    {
        "--socket-path",
        "--candidate-lock",
        "--rapid-profile",
        "--rapid-profile-sha256",
        "--rapid-state-path",
        "--complex-profile",
        "--complex-profile-sha256",
        "--complex-state-path",
    }
)


def build_checked_admission_broker(
    repository_root: Path,
    *,
    runner: Runner = subprocess.run,
) -> str:
    """Build the checked release broker and return its exact binary digest."""

    cargo = shutil.which("cargo")
    if cargo is None:
        cargo = str(Path.home() / ".cargo/bin/cargo")
    completed = runner(
        [cargo, "build", "--locked", "--release", "--bin", _BROKER_BINARY],
        cwd=repository_root / "server/orchestrator",
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        timeout=1_800,
    )
    if completed.returncode != 0:
        raise RuntimeError("admission broker checked build failed")
    binary = repository_root / "server/orchestrator/target/release" / _BROKER_BINARY
    if binary.is_symlink() or not binary.is_file():
        raise RuntimeError("admission broker checked build is unavailable")
    return hashlib.sha256(binary.read_bytes()).hexdigest()


def observe_admission_broker(
    socket_path: Path,
    *,
    expected_binary_sha256: str,
    expected_candidate_lock_sha256: str,
    expected_rapid_profile_sha256: str,
    expected_rapid_state_path: Path,
) -> dict[str, object]:
    """Bind an owner-private socket to one exact running broker executable."""

    if (
        len(expected_binary_sha256) != 64
        or any(
            character not in "0123456789abcdef"
            for character in expected_binary_sha256
        )
    ):
        raise ValueError("admission broker binary digest is invalid")
    requested = Path(os.path.abspath(socket_path))
    resolved = socket_path.resolve(strict=True)
    before = resolved.lstat()
    if (
        requested != resolved
        or not stat.S_ISSOCK(before.st_mode)
        or stat.S_IMODE(before.st_mode) != 0o600
        or before.st_uid != os.geteuid()
        or not hasattr(socket, "SO_PEERCRED")
    ):
        raise ValueError("admission broker socket identity is invalid")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(2.0)
        client.connect(str(resolved))
        credentials = client.getsockopt(
            socket.SOL_SOCKET,
            socket.SO_PEERCRED,
            struct.calcsize("3i"),
        )
    process_id, user_id, _group_id = struct.unpack("3i", credentials)
    after = resolved.lstat()
    if (
        process_id < 2
        or user_id != os.geteuid()
        or (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino)
    ):
        raise ValueError("admission broker process identity is invalid")
    actual_binary_sha256 = process_binary_sha256(process_id)
    if actual_binary_sha256 != expected_binary_sha256:
        raise ValueError("admission broker executable differs from the checked build")
    _validate_broker_command_line(
        process_id,
        socket_path=resolved,
        expected_candidate_lock_sha256=expected_candidate_lock_sha256,
        expected_rapid_profile_sha256=expected_rapid_profile_sha256,
        expected_rapid_state_path=expected_rapid_state_path,
    )
    return {
        "processId": process_id,
        "processStartTicks": _process_start_ticks(process_id),
        "binarySha256": actual_binary_sha256,
        "socketDevice": int(after.st_dev),
        "socketInode": int(after.st_ino),
    }


def process_binary_sha256(process_id: int) -> str:
    """Hash one observed process executable through its open descriptor."""

    descriptor = os.open(Path(f"/proc/{process_id}/exe"), os.O_RDONLY)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or not (
            1 <= metadata.st_size <= _MAXIMUM_BROKER_BINARY_BYTES
        ):
            raise ValueError("admission broker executable identity is invalid")
        digest = hashlib.sha256()
        remaining = _MAXIMUM_BROKER_BINARY_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            digest.update(chunk)
            remaining -= len(chunk)
        if remaining == 0:
            raise ValueError("admission broker executable exceeds its byte bound")
        return digest.hexdigest()
    finally:
        os.close(descriptor)


def _process_start_ticks(process_id: int) -> int:
    value = Path(f"/proc/{process_id}/stat").read_text(encoding="ascii")
    end = value.rfind(")")
    fields = value[end + 2 :].split() if end > 0 else []
    if len(fields) <= 19 or not fields[19].isdigit() or int(fields[19]) < 1:
        raise ValueError("admission broker process start identity is invalid")
    return int(fields[19])


def _validate_broker_command_line(
    process_id: int,
    *,
    socket_path: Path,
    expected_candidate_lock_sha256: str,
    expected_rapid_profile_sha256: str,
    expected_rapid_state_path: Path,
) -> None:
    try:
        raw = Path(f"/proc/{process_id}/cmdline").read_bytes()
        values = [part.decode("utf-8") for part in raw.split(b"\0") if part]
    except (OSError, UnicodeError) as error:
        raise ValueError("admission broker command line is unavailable") from error
    if (
        not values
        or len(raw) > 16 * 1024
        or len(values[1:]) != len(_BROKER_ARGUMENTS) * 2
    ):
        raise ValueError("admission broker command line differs")
    arguments: dict[str, str] = {}
    for index in range(1, len(values), 2):
        name = values[index]
        if name not in _BROKER_ARGUMENTS or name in arguments:
            raise ValueError("admission broker command line differs")
        arguments[name] = values[index + 1]
    if set(arguments) != _BROKER_ARGUMENTS:
        raise ValueError("admission broker command line differs")
    if (
        _resolved_path(arguments["--socket-path"]) != socket_path
        or _resolved_path(arguments["--rapid-state-path"])
        != expected_rapid_state_path.resolve(strict=True)
        or _sha256_regular_file(Path(arguments["--candidate-lock"]))
        != expected_candidate_lock_sha256
        or _sha256_regular_file(Path(arguments["--rapid-profile"]))
        != expected_rapid_profile_sha256
        or arguments["--rapid-profile-sha256"] != expected_rapid_profile_sha256
    ):
        raise ValueError("admission broker checked configuration differs")
    complex_profile_sha256 = _sha256_regular_file(
        Path(arguments["--complex-profile"])
    )
    if arguments["--complex-profile-sha256"] != complex_profile_sha256:
        raise ValueError("admission broker complex profile identity differs")
    _resolved_path(arguments["--complex-state-path"])


def _resolved_path(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute() or path.is_symlink():
        raise ValueError("admission broker configured path is invalid")
    return path.resolve(strict=True)


def _sha256_regular_file(path: Path) -> str:
    if not path.is_absolute() or path.is_symlink():
        raise ValueError("admission broker configured file is invalid")
    metadata = path.lstat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or not 1 <= metadata.st_size <= _MAXIMUM_BROKER_DOCUMENT_BYTES
    ):
        raise ValueError("admission broker configured file is invalid")
    return hashlib.sha256(path.read_bytes()).hexdigest()


__all__ = [
    "build_checked_admission_broker",
    "observe_admission_broker",
    "process_binary_sha256",
]
