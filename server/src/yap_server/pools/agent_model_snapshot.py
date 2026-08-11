from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def verify_agent_model_snapshot(
    *,
    expected_model: str,
    model_revision: str,
    expected_manifest_sha256: str,
    snapshot_path: Path,
) -> None:
    """Recompute the qualified artifact manifest for one mounted snapshot."""

    if snapshot_path.is_symlink() or not snapshot_path.is_dir():
        raise ValueError("agent model snapshot must be a real directory")
    snapshot = snapshot_path.resolve(strict=True)
    if (
        snapshot != snapshot_path
        or snapshot.name != model_revision
        or snapshot.parent.name != "snapshots"
    ):
        raise ValueError("agent model snapshot revision differs")
    model_root = snapshot.parent.parent.resolve(strict=True)
    records: list[dict[str, object]] = []
    required = {"config.json", "tokenizer_config.json"}
    for path in sorted(snapshot.iterdir(), key=lambda item: item.name):
        if len(records) >= 2_048:
            raise ValueError("agent model snapshot has too many artifacts")
        resolved = path.resolve(strict=True)
        if model_root not in resolved.parents or not resolved.is_file():
            raise ValueError("agent model artifact escaped its cache")
        record: dict[str, object] = {
            "path": path.name,
            "blobIdentity": resolved.name,
            "size": resolved.stat().st_size,
        }
        if path.name.endswith(".safetensors"):
            if not _SHA256.fullmatch(resolved.name):
                raise ValueError("agent model weight lacks a SHA-256 blob identity")
            record["sha256"] = resolved.name
        else:
            record["sha256"] = _file_sha256(resolved)
        records.append(record)
        required.discard(path.name)
    if required or not any(
        record["path"].endswith(".safetensors") for record in records
    ):
        raise ValueError("agent model snapshot is incomplete")
    identity = {
        "schemaVersion": 1,
        "model": expected_model,
        "revision": model_revision,
        "artifacts": records,
    }
    observed = hashlib.sha256(
        json.dumps(
            identity,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    if observed != expected_manifest_sha256:
        raise ValueError("agent model artifacts differ from the checked manifest")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = ["verify_agent_model_snapshot"]
