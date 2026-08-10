"""Private, create-once output for agent-model qualification evidence."""

from __future__ import annotations

import json
import os
from pathlib import Path


def write_new_agent_model_evidence(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink() or path.exists():
        raise ValueError("agent model evidence destination must be new and real")
    body = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
        output.write(body)
        output.flush()
        os.fsync(output.fileno())


__all__ = ["write_new_agent_model_evidence"]
