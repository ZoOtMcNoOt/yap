"""Run the exact sequential Qwen/Gemma supervised-service lifecycle gate."""

from __future__ import annotations

import argparse
from collections.abc import Callable
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess

from yap_server.evaluation.agent_service_lifecycle_observation import (
    AgentServiceLifecycleResult,
)
from yap_server.evaluation.agent_service_lifecycle_runtime import (
    AgentServiceLifecycleRuntime,
)
from yap_server.evaluation.private_json_evidence import (
    write_new_private_json_evidence,
)
from yap_server.evaluation.provider_runtime_observations import (
    canonical_evidence_sha256,
)


_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
_PROFILES = ("rapid-automation", "complex-orchestration")
_ROUTE_KEYS = {
    "profileId",
    "profileSha256",
    "candidateLockSha256",
    "imageId",
    "initialReadinessObserved",
    "restartReadinessObserved",
    "newContainerObserved",
    "newProcessObserved",
    "stoppedStateObserved",
    "teardown",
}
_TEARDOWN_KEYS = {
    "containerAbsent",
    "listenerAbsent",
    "ownedProcessAbsent",
    "networkAbsent",
    "sameLabelOwnersAbsent",
}
RuntimeFactory = Callable[..., AgentServiceLifecycleRuntime]


def run_agent_service_lifecycle_gate(
    *,
    repository_root: Path,
    checked_head: str,
    rapid_model_snapshot: Path,
    complex_model_snapshot: Path,
    evidence_root: Path,
    runtime_factory: RuntimeFactory = AgentServiceLifecycleRuntime,
    command_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, object]:
    """Publish one public-safe receipt only after both exact routes tear down."""

    repository_root = _validate_repository(
        repository_root,
        checked_head=checked_head,
        command_runner=command_runner,
    )
    evidence_root = _private_evidence_root(evidence_root)
    _validate_private_host(command_runner)
    supervisor_binary = _build_supervisor(repository_root, command_runner)
    supervisor_binary_sha256 = hashlib.sha256(supervisor_binary.read_bytes()).hexdigest()
    snapshots = {
        "rapid-automation": _canonical_snapshot(rapid_model_snapshot),
        "complex-orchestration": _canonical_snapshot(complex_model_snapshot),
    }
    expected_profile_sha256 = {
        profile_id: hashlib.sha256(
            (
                repository_root
                / "server"
                / "agent-service-profiles"
                / f"{profile_id}.json"
            ).read_bytes()
        ).hexdigest()
        for profile_id in _PROFILES
    }
    expected_candidate_lock_sha256 = hashlib.sha256(
        (
            repository_root / "server" / "agent-reasoning-candidates.lock.json"
        ).read_bytes()
    ).hexdigest()
    results: dict[str, AgentServiceLifecycleResult] = {}
    for profile_id in _PROFILES:
        runtime = runtime_factory(
            repository_root=repository_root,
            checked_head=checked_head,
            supervisor_binary=supervisor_binary,
            private_root=evidence_root,
        )
        results[profile_id] = runtime.run(
            profile_id=profile_id,
            model_snapshot=snapshots[profile_id],
        )
    if hashlib.sha256(supervisor_binary.read_bytes()).hexdigest() != supervisor_binary_sha256:
        raise RuntimeError("agent service supervisor changed during the gate")
    _validate_repository(
        repository_root,
        checked_head=checked_head,
        command_runner=command_runner,
    )
    evidence: dict[str, object] = {
        "schemaVersion": 1,
        "checkedHead": checked_head,
        "hardwareProfile": "dgx-spark-gb10",
        "executionShape": "sequential-supervised-agent-services",
        "supervisorBinarySha256": supervisor_binary_sha256,
        "routes": {
            profile_id: results[profile_id].public_evidence()
            for profile_id in _PROFILES
        },
        "simultaneousResidencyClaim": False,
        "capacityClaim": False,
        "passed": True,
    }
    _validate_public_evidence(
        evidence,
        expected_profile_sha256=expected_profile_sha256,
        expected_candidate_lock_sha256=expected_candidate_lock_sha256,
    )
    evidence["evidenceSha256"] = canonical_evidence_sha256(evidence)
    write_new_private_json_evidence(evidence_root / "receipt.json", evidence)
    return evidence


def _validate_repository(
    root: Path,
    *,
    checked_head: str,
    command_runner: Callable[..., subprocess.CompletedProcess[str]],
) -> Path:
    if _GIT_SHA.fullmatch(checked_head) is None or not root.is_absolute():
        raise ValueError("agent service gate candidate identity is invalid")
    if root.is_symlink() or not root.is_dir():
        raise ValueError("agent service gate repository must be a real directory")
    root = root.resolve(strict=True)
    top = _run_text(
        command_runner,
        ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
    ).strip()
    head = _run_text(
        command_runner,
        ["git", "-C", str(root), "rev-parse", "HEAD"],
    ).strip()
    status = _run_text(
        command_runner,
        [
            "git",
            "-C",
            str(root),
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
        ],
    )
    if Path(top).resolve(strict=True) != root or head != checked_head or status:
        raise RuntimeError("agent service gate requires the exact clean candidate")
    return root


def _canonical_executable(path: Path) -> Path:
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise ValueError("agent service supervisor must be a real executable")
    path = path.resolve(strict=True)
    if os.name == "posix" and not os.access(path, os.X_OK):
        raise ValueError("agent service supervisor must be executable")
    return path


def _build_supervisor(
    repository_root: Path,
    command_runner: Callable[..., subprocess.CompletedProcess[str]],
) -> Path:
    orchestrator = repository_root / "server" / "orchestrator"
    cargo = shutil.which("cargo")
    if cargo is None:
        home_cargo = Path.home() / ".cargo" / "bin" / "cargo"
        cargo = str(_canonical_executable(home_cargo))
    command_runner(
        [
            cargo,
            "build",
            "--locked",
            "--release",
            "--bin",
            "yap-provider-supervisor",
        ],
        capture_output=True,
        check=True,
        cwd=orchestrator,
        text=True,
        timeout=1_800,
    )
    return _canonical_executable(
        orchestrator / "target" / "release" / "yap-provider-supervisor"
    )


def _canonical_snapshot(path: Path) -> Path:
    if not path.is_absolute() or path.is_symlink() or not path.is_dir():
        raise ValueError("agent service model snapshot must be a real directory")
    return path.resolve(strict=True)


def _private_evidence_root(path: Path) -> Path:
    if not path.is_absolute() or path.is_symlink() or not path.is_dir():
        raise ValueError("agent service evidence root must be a real directory")
    path = path.resolve(strict=True)
    metadata = path.lstat()
    if os.name == "posix" and stat.S_IMODE(metadata.st_mode) & 0o077:
        raise ValueError("agent service evidence root must be owner-private")
    if any(path.iterdir()):
        raise ValueError("agent service evidence root must be empty")
    return path


def _validate_private_host(
    command_runner: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    architecture = _run_text(command_runner, ["uname", "-m"]).strip()
    docker = _run_text(
        command_runner,
        ["docker", "info", "--format", "{{.OSType}}|{{.Architecture}}"],
    ).strip()
    if architecture not in {"aarch64", "arm64"} or docker not in {
        "linux|aarch64",
        "linux|arm64",
    }:
        raise RuntimeError("agent service gate requires the ARM64 private node")


def _validate_public_evidence(
    evidence: dict[str, object],
    *,
    expected_profile_sha256: dict[str, str],
    expected_candidate_lock_sha256: str,
) -> None:
    routes = evidence.get("routes")
    if not isinstance(routes, dict) or tuple(routes) != _PROFILES:
        raise ValueError("agent service gate route evidence differs")
    for profile_id, route in routes.items():
        if (
            not isinstance(route, dict)
            or set(route) != _ROUTE_KEYS
            or route.get("profileId") != profile_id
        ):
            raise ValueError("agent service gate profile evidence differs")
        teardown = route.get("teardown")
        booleans = [
            value
            for key, value in route.items()
            if key.endswith("Observed")
        ]
        if (
            not booleans
            or not all(value is True for value in booleans)
            or route.get("profileSha256") != expected_profile_sha256[profile_id]
            or route.get("candidateLockSha256")
            != expected_candidate_lock_sha256
            or not isinstance(route.get("imageId"), str)
            or _IMAGE_ID.fullmatch(route["imageId"]) is None
            or not isinstance(teardown, dict)
            or set(teardown) != _TEARDOWN_KEYS
            or not all(value is True for value in teardown.values())
        ):
            raise ValueError("agent service gate lifecycle evidence did not pass")
    supervisor_sha256 = evidence.get("supervisorBinarySha256")
    if not isinstance(supervisor_sha256, str) or _SHA256.fullmatch(supervisor_sha256) is None:
        raise ValueError("agent service supervisor evidence is invalid")


def _run_text(
    runner: Callable[..., subprocess.CompletedProcess[str]],
    arguments: list[str],
) -> str:
    result = runner(
        arguments,
        capture_output=True,
        check=True,
        text=True,
        timeout=30,
    )
    return result.stdout


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the sequential supervised agent-service lifecycle gate",
        allow_abbrev=False,
    )
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--checked-head", required=True)
    parser.add_argument("--rapid-model-snapshot", type=Path, required=True)
    parser.add_argument("--complex-model-snapshot", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    return parser


def main(arguments: list[str] | None = None) -> int:
    parsed = _parser().parse_args(arguments)
    evidence = run_agent_service_lifecycle_gate(
        repository_root=parsed.repository_root,
        checked_head=parsed.checked_head,
        rapid_model_snapshot=parsed.rapid_model_snapshot,
        complex_model_snapshot=parsed.complex_model_snapshot,
        evidence_root=parsed.evidence_root,
    )
    print(
        json.dumps(
            evidence,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["run_agent_service_lifecycle_gate"]
