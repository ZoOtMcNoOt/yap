from __future__ import annotations

import argparse
from pathlib import Path

from .component_lock import (
    LidComponentLock,
    load_lid_component_lock,
    verify_lid_model_artifacts,
)


def verify_lid_model_import(lock: LidComponentLock, model_dir: Path) -> None:
    """Verify an explicitly imported model; never acquire or redistribute it."""

    verify_lid_model_artifacts(lock, model_dir)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify an explicitly imported language-detection model"
    )
    parser.add_argument("--lock", required=True)
    parser.add_argument("--model-dir", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    lock = load_lid_component_lock(Path(arguments.lock))
    verify_lid_model_import(lock, Path(arguments.model_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
