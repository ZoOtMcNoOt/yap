from __future__ import annotations

import argparse
from pathlib import Path

from yap_server.pinned_artifacts import (
    Opener,
    PinnedArtifactRedirectHandler,
    huggingface_artifact_url,
    sync_huggingface_artifacts,
)

from .component_lock import (
    LidComponentArtifactError,
    LidComponentLock,
    LockedLidArtifact,
    load_lid_component_lock,
    verify_lid_model_artifacts,
)


class _PinnedArtifactRedirectHandler(PinnedArtifactRedirectHandler):
    def __init__(self) -> None:
        super().__init__(LidComponentArtifactError)


def artifact_url(
    lock: LidComponentLock,
    artifact: LockedLidArtifact,
) -> str:
    return huggingface_artifact_url(
        lock.model.model_id,
        lock.model.revision,
        artifact.path,
    )


def sync_lid_model_artifacts(
    lock: LidComponentLock,
    model_dir: Path,
    *,
    opener: Opener | None = None,
    timeout_seconds: float = 120.0,
) -> None:
    """Explicitly acquire or verify the four immutable LID model files."""

    sync_huggingface_artifacts(
        repository_id=lock.model.model_id,
        revision=lock.model.revision,
        artifacts=lock.model.artifacts,
        model_dir=model_dir,
        verify=lambda root: verify_lid_model_artifacts(lock, root),
        error_type=LidComponentArtifactError,
        user_agent="yap-language-detection-model-fetch/1",
        opener=opener,
        timeout_seconds=timeout_seconds,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Explicitly acquire or verify the immutable language-detection model"
    )
    parser.add_argument("--lock", required=True)
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--verify-only", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    lock = load_lid_component_lock(Path(arguments.lock))
    model_dir = Path(arguments.model_dir)
    if arguments.verify_only:
        verify_lid_model_artifacts(lock, model_dir)
    else:
        sync_lid_model_artifacts(lock, model_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
