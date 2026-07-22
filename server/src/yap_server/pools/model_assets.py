from __future__ import annotations

import argparse
from pathlib import Path

from yap_server.pinned_artifacts import (
    Opener,
    PinnedArtifactRedirectHandler,
    huggingface_artifact_url,
    sync_huggingface_artifacts,
)
from yap_server.pools.model_lock import (
    LockedArtifact,
    ModelArtifactError,
    ModelPoolLock,
    load_model_pool_lock,
    verify_model_artifacts,
)


class _PinnedArtifactRedirectHandler(PinnedArtifactRedirectHandler):
    def __init__(self) -> None:
        super().__init__(ModelArtifactError)


def artifact_url(lock: ModelPoolLock, artifact: LockedArtifact) -> str:
    return huggingface_artifact_url(
        lock.model_distribution_id,
        lock.model_distribution_revision,
        artifact.path,
    )


def sync_model_artifacts(
    lock: ModelPoolLock,
    model_dir: Path,
    *,
    opener: Opener | None = None,
    timeout_seconds: float = 120.0,
) -> None:
    """Explicitly acquire or verify the immutable batch-ASR distribution."""

    sync_huggingface_artifacts(
        repository_id=lock.model_distribution_id,
        revision=lock.model_distribution_revision,
        artifacts=lock.artifacts,
        model_dir=model_dir,
        verify=lambda root: verify_model_artifacts(lock, root),
        error_type=ModelArtifactError,
        user_agent="yap-asr-model-fetch/1",
        opener=opener,
        timeout_seconds=timeout_seconds,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Acquire or verify immutable batch-ASR model artifacts"
    )
    parser.add_argument("--lock", required=True)
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--verify-only", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    lock = load_model_pool_lock(Path(arguments.lock))
    model_dir = Path(arguments.model_dir)
    if arguments.verify_only:
        verify_model_artifacts(lock, model_dir)
    else:
        sync_model_artifacts(lock, model_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
