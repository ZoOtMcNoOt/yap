from __future__ import annotations

import argparse
from collections.abc import Callable
import json
import os
from pathlib import Path
import sys
from typing import Any

from .component_lock import (
    LidComponentArtifactError,
    load_lid_component_lock,
    verify_lid_model_artifacts,
)
from .ambernet_classifier import AmberNetClassifier
from .worker_contract import (
    LidClassifier,
    WorkerInputError,
    load_lid_worker_request,
    run_lid_worker_request,
)


ClassifierLoader = Callable[[Path, int], LidClassifier]


def execute_lid_worker(
    *,
    lock_path: Path,
    model_dir: Path,
    request_path: Path,
    probe_dir: Path,
    classifier_loader: ClassifierLoader = AmberNetClassifier.load,
) -> dict[str, Any]:
    """Verify all immutable inputs before loading or invoking AmberNet."""

    lock = load_lid_component_lock(lock_path)
    try:
        resolved_model_dir = model_dir.resolve(strict=True)
    except FileNotFoundError as error:
        raise LidComponentArtifactError("model root is missing") from error
    verify_lid_model_artifacts(lock, resolved_model_dir)
    request = load_lid_worker_request(request_path, lock)
    classifier = classifier_loader(
        resolved_model_dir,
        lock.model.label_count,
    )
    return run_lid_worker_request(
        lock=lock,
        request=request,
        probe_root=probe_dir,
        classifier=classifier,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one offline, assistive AmberNet LID preflight",
    )
    parser.add_argument(
        "--lock",
        default=os.environ.get("YAP_LID_COMPONENT_LOCK"),
    )
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--request", required=True)
    parser.add_argument("--probe-dir", required=True)
    return parser


def _emit_error(code: str, message: str) -> None:
    payload = {
        "schemaVersion": 1,
        "code": code,
        "message": message,
    }
    print(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        file=sys.stderr,
    )


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if not arguments.lock:
        _emit_error(
            "LID_WORKER_COMPONENT_INVALID",
            "an immutable LID component lock is required",
        )
        return 2
    try:
        result = execute_lid_worker(
            lock_path=Path(arguments.lock),
            model_dir=Path(arguments.model_dir),
            request_path=Path(arguments.request),
            probe_dir=Path(arguments.probe_dir),
        )
    except WorkerInputError as error:
        _emit_error("LID_WORKER_INPUT_INVALID", str(error))
        return 2
    except (LidComponentArtifactError, OSError, ValueError):
        _emit_error(
            "LID_WORKER_COMPONENT_INVALID",
            "the locked LID component or staged artifacts are invalid",
        )
        return 2
    except Exception:
        _emit_error(
            "LID_WORKER_INFERENCE_FAILED",
            "language identification failed",
        )
        return 1
    print(
        json.dumps(
            result,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
