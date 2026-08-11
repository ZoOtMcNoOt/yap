"""Create-once owner-private canonical JSON evidence publication."""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat


def write_new_private_json_evidence(path: Path, value: object) -> None:
    _ensure_private_parent(path.parent)
    if path.exists() or path.is_symlink():
        raise ValueError("private JSON evidence destination must be new and real")
    body = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
        output.write(body + "\n")
        output.flush()
        os.fsync(output.fileno())


def _ensure_private_parent(parent: Path) -> None:
    missing: list[Path] = []
    current = parent
    while not current.exists():
        if current.is_symlink() or current.parent == current:
            raise ValueError("private JSON evidence destination must be new and real")
        missing.append(current)
        current = current.parent
    if current.is_symlink() or not current.is_dir():
        raise ValueError("private JSON evidence destination must be new and real")
    for directory in reversed(missing):
        try:
            directory.mkdir(mode=0o700)
        except FileExistsError:
            pass
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError("private JSON evidence destination must be new and real")
        _require_owner_private_directory(directory)
    _require_owner_private_directory(parent)


def _require_owner_private_directory(path: Path) -> None:
    if os.name != "posix":
        return
    metadata = path.lstat()
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_mode & 0o077
        or metadata.st_uid != os.geteuid()
    ):
        raise ValueError("private JSON evidence parent must be owner-private")


__all__ = ["write_new_private_json_evidence"]
