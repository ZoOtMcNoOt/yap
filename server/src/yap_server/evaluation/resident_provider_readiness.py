"""Bounded exact-model readiness probe for resident ASR providers."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import stat
import time
from typing import Callable, Mapping, Protocol

from yap_server.evaluation.checked_candidate import (
    admit_checked_candidate,
    bind_checked_candidate_evidence,
)
from yap_server.evaluation.provider_runtime_observations import (
    canonical_evidence_sha256,
)
from yap_server.evaluation.provider_runtime_qualification import (
    build_resident_worker,
    resident_provider_configuration,
    validate_resident_provider_lock,
    write_private_evidence,
)
from yap_server.pools.batch_contract import ProviderServiceUnavailable
from yap_server.pools.model_lock import ModelPoolLock, load_model_pool_lock


_MAXIMUM_TIMEOUT_SECONDS = 3_600.0
_MINIMUM_POLL_SECONDS = 0.05
_MAXIMUM_POLL_SECONDS = 5.0


class ReadinessWorker(Protocol):
    def verify_ready(self) -> None: ...


@dataclass(frozen=True, slots=True)
class ResidentProviderReadiness:
    system_id: str
    model_id: str
    model_revision: str
    attempt_count: int
    ready_after_ms: int

    def public_evidence(self) -> dict[str, object]:
        evidence: dict[str, object] = {
            "schemaVersion": 1,
            "systemId": self.system_id,
            "readinessBoundary": "probe-start-to-exact-model-ready",
            "model": {
                "id": self.model_id,
                "revision": self.model_revision,
            },
            "attemptCount": self.attempt_count,
            "readyAfterMs": self.ready_after_ms,
            "passed": True,
        }
        evidence["evidenceSha256"] = canonical_evidence_sha256(evidence)
        return evidence


def wait_for_resident_provider_readiness(
    worker: ReadinessWorker,
    lock: ModelPoolLock,
    *,
    system_id: str,
    timeout_seconds: float,
    poll_seconds: float,
    monotonic: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> ResidentProviderReadiness:
    """Wait only for connection/startup failures; exact identity still gates success."""

    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(timeout_seconds)
        or timeout_seconds <= 0
        or timeout_seconds > _MAXIMUM_TIMEOUT_SECONDS
        or isinstance(poll_seconds, bool)
        or not isinstance(poll_seconds, (int, float))
        or not math.isfinite(poll_seconds)
        or not _MINIMUM_POLL_SECONDS <= poll_seconds <= _MAXIMUM_POLL_SECONDS
    ):
        raise ValueError("resident provider readiness timing is invalid")
    validate_resident_provider_lock(system_id, lock)
    started = monotonic()
    deadline = started + timeout_seconds
    attempts = 0
    while True:
        attempts += 1
        try:
            worker.verify_ready()
        except ProviderServiceUnavailable as error:
            now = monotonic()
            if now >= deadline:
                raise TimeoutError("resident provider readiness timed out") from error
            sleeper(min(poll_seconds, deadline - now))
            continue
        ready_after_ms = max(0, round((monotonic() - started) * 1_000))
        return ResidentProviderReadiness(
            system_id=system_id,
            model_id=lock.model_id,
            model_revision=lock.model_revision,
            attempt_count=attempts,
            ready_after_ms=ready_after_ms,
        )


def _private_new_output(path: Path, environ: Mapping[str, str]) -> Path:
    raw_cache = environ.get("YAP_EVAL_CACHE", "").strip()
    if not raw_cache:
        raise ValueError("YAP_EVAL_CACHE is required for readiness evidence")
    cache = Path(raw_cache)
    if not cache.is_absolute() or cache.is_symlink():
        raise ValueError("YAP_EVAL_CACHE must be an absolute real directory")
    cache = cache.resolve(strict=True)
    repository = Path(__file__).resolve().parents[4]
    if cache == repository or repository in cache.parents:
        raise ValueError("YAP_EVAL_CACHE must remain outside the repository")
    cache_metadata = cache.lstat()
    if stat.S_ISLNK(cache_metadata.st_mode) or not stat.S_ISDIR(cache_metadata.st_mode):
        raise ValueError("YAP_EVAL_CACHE must be a real directory")
    if os.name == "posix" and stat.S_IMODE(cache_metadata.st_mode) & 0o077:
        raise ValueError("YAP_EVAL_CACHE must use private permissions")
    if not path.is_absolute() or path.is_symlink():
        raise ValueError("readiness evidence output must be an absolute new file")
    parent = path.parent.resolve(strict=True)
    if cache not in parent.parents and parent != cache:
        raise ValueError("readiness evidence output escaped YAP_EVAL_CACHE")
    parent_metadata = parent.lstat()
    if stat.S_ISLNK(parent_metadata.st_mode) or not stat.S_ISDIR(parent_metadata.st_mode):
        raise ValueError("readiness evidence parent must be a real directory")
    if os.name == "posix" and stat.S_IMODE(parent_metadata.st_mode) & 0o077:
        raise ValueError("readiness evidence parent must use private permissions")
    if path.exists() or path.is_symlink():
        raise ValueError("readiness evidence output must be new")
    return path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Wait for one checked resident provider's exact model identity",
    )
    parser.add_argument("--checked-head", required=True)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--system-id", required=True)
    parser.add_argument("--model-lock", type=Path, required=True)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--timeout-seconds", type=float, required=True)
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    lock_path = arguments.model_lock.resolve(strict=True)
    candidate = admit_checked_candidate(
        repository_root=arguments.repository_root,
        checked_head=arguments.checked_head,
        input_paths=(lock_path,),
    )
    lock = load_model_pool_lock(lock_path)
    validate_resident_provider_lock(arguments.system_id, lock)
    _provider_id, api_key_environment = resident_provider_configuration(
        arguments.system_id
    )
    api_key = os.environ.get(api_key_environment, "")
    if not api_key:
        raise ValueError(f"{api_key_environment} is required for readiness")
    worker = build_resident_worker(
        system_id=arguments.system_id,
        endpoint=arguments.endpoint,
        api_key=api_key,
        timeout_seconds=min(arguments.timeout_seconds, 30.0),
        lock=lock,
    )
    try:
        readiness = wait_for_resident_provider_readiness(
            worker,
            lock,
            system_id=arguments.system_id,
            timeout_seconds=arguments.timeout_seconds,
            poll_seconds=arguments.poll_seconds,
        )
    finally:
        worker.close()
    candidate.verify_unchanged()
    evidence = bind_checked_candidate_evidence(
        readiness.public_evidence(),
        candidate,
    )
    output = _private_new_output(arguments.output, os.environ)
    write_private_evidence(output, evidence)
    print(json.dumps(evidence, ensure_ascii=True, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
