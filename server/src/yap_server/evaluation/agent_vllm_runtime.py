from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import socket
import subprocess
import time
from typing import Callable
import urllib.error
import urllib.request

from .provider_runtime_observations import canonical_evidence_sha256


Runner = Callable[..., subprocess.CompletedProcess[str]]
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_CONTAINER_NAME = "yap-agent-vllm"
_PORT = 30000


@dataclass(frozen=True, slots=True)
class StartedAgentVllmRuntime:
    endpoint: str
    container_name: str
    container_id: str
    image_id: str
    model_artifact_manifest_sha256: str
    launch_arguments_sha256: str
    launch_arguments: tuple[str, ...]
    cgroup_path: Path
    process_id: int

    def memory_bytes(self) -> int:
        raw = (self.cgroup_path / "memory.current").read_text(encoding="ascii").strip()
        value = int(raw)
        if value < 0:
            raise ValueError("agent runtime cgroup memory is invalid")
        return value


class OwnedAgentVllmRuntime:
    """Own one exact digest/model/container lifecycle for private qualification."""

    def __init__(
        self,
        *,
        checked_head: str,
        runtime: dict[str, object],
        candidate: dict[str, object],
        runner: Runner = subprocess.run,
        home: Path | None = None,
    ) -> None:
        if not re.fullmatch(r"[0-9a-f]{40}", checked_head):
            raise ValueError("agent runtime checked head is invalid")
        self._checked_head = checked_head
        self._runtime = runtime
        self._candidate = candidate
        self._runner = runner
        self._home = (home or Path.home()).resolve(strict=True)
        self._started: StartedAgentVllmRuntime | None = None

    def start(self, *, timeout_seconds: int) -> StartedAgentVllmRuntime:
        if self._started is not None:
            raise RuntimeError("agent runtime is already started")
        if not 1 <= timeout_seconds <= 900:
            raise ValueError("agent runtime startup timeout is invalid")
        self._assert_container_absent()
        _assert_listener_absent(_PORT)
        image_id = self._verified_image_id()
        model_root, snapshot, artifact_sha256 = self._verified_model_snapshot()
        arguments = self._launch_arguments(snapshot)
        argument_sha256 = canonical_evidence_sha256(arguments)
        completed = self._run(
            [
                "docker",
                "run",
                "-d",
                "--name",
                _CONTAINER_NAME,
                "--label",
                "io.yap.owner=private-inference",
                "--label",
                f"io.yap.revision={self._checked_head}",
                "--user",
                "1000:1000",
                "--gpus",
                "all",
                "--ipc=host",
                "--ulimit",
                "memlock=-1",
                "--ulimit",
                "stack=67108864",
                "--network",
                "host",
                "--env",
                "HOME=/tmp",
                "--volume",
                f"{model_root}:/model-cache:ro",
                image_id,
                *arguments,
            ]
        )
        container_id = completed.stdout.strip()
        if not re.fullmatch(r"[0-9a-f]{64}", container_id):
            self._remove_failed_container()
            raise RuntimeError("agent runtime container identity is invalid")
        try:
            inspection = self._inspect_container()
            process_id, cgroup_path = self._verify_container(
                inspection,
                image_id=image_id,
                arguments=arguments,
            )
            self._wait_ready(timeout_seconds)
        except BaseException:
            self._remove_failed_container()
            raise
        started = StartedAgentVllmRuntime(
            endpoint=f"http://127.0.0.1:{_PORT}",
            container_name=_CONTAINER_NAME,
            container_id=container_id,
            image_id=image_id,
            model_artifact_manifest_sha256=artifact_sha256,
            launch_arguments_sha256=argument_sha256,
            launch_arguments=tuple(arguments),
            cgroup_path=cgroup_path,
            process_id=process_id,
        )
        self._started = started
        return started

    def stop(
        self,
        *,
        timeout_seconds: int,
        child_evidence_sha256: dict[str, str],
    ) -> dict[str, object]:
        started = self._started
        if started is None:
            raise RuntimeError("agent runtime was not started")
        expected_children = {
            "fixtures",
            "pressure",
            "cancellation",
            "resources",
            "lifecycle",
        }
        if set(child_evidence_sha256) != expected_children or any(
            not _SHA256.fullmatch(value) for value in child_evidence_sha256.values()
        ):
            raise ValueError("agent runtime child evidence is incomplete")
        self._run(
            ["docker", "stop", "--time", str(timeout_seconds), _CONTAINER_NAME],
            timeout=timeout_seconds + 10,
        )
        self._run(["docker", "rm", _CONTAINER_NAME])
        self._started = None
        container_absent = not self._container_exists()
        listener_absent = _listener_is_absent(_PORT)
        workers_reaped = not Path(f"/proc/{started.process_id}").exists()
        if not (container_absent and listener_absent and workers_reaped):
            raise RuntimeError("agent runtime teardown did not complete")
        return {
            "schemaVersion": 1,
            "checkedHead": self._checked_head,
            "candidateId": self._candidate["candidateId"],
            "model": self._candidate["model"],
            "revision": self._candidate["revision"],
            "runtime": self._runtime,
            "imageId": started.image_id,
            "quantization": self._candidate["quantization"],
            "modelArtifactManifestSha256": started.model_artifact_manifest_sha256,
            "launchArguments": list(started.launch_arguments),
            "launchArgumentsSha256": started.launch_arguments_sha256,
            "childEvidenceSha256": dict(sorted(child_evidence_sha256.items())),
            "teardown": {
                "containerAbsent": container_absent,
                "listenerAbsent": listener_absent,
                "ownedWorkersReaped": workers_reaped,
            },
        }

    def abort(self, *, timeout_seconds: int = 30) -> None:
        """Contain a failed qualification without emitting an admissible receipt."""

        if self._started is None:
            return
        self._run(
            ["docker", "stop", "--time", str(timeout_seconds), _CONTAINER_NAME],
            check=False,
            timeout=timeout_seconds + 10,
        )
        self._run(["docker", "rm", "--force", _CONTAINER_NAME], check=False)
        self._started = None

    def _verified_image_id(self) -> str:
        image = str(self._runtime.get("image", ""))
        digest = str(self._runtime.get("digest", ""))
        inspected = _single_inspection(self._run(["docker", "image", "inspect", image]))
        image_id = inspected.get("Id")
        repo_digests = inspected.get("RepoDigests")
        if (
            inspected.get("Architecture") != "arm64"
            or not isinstance(image_id, str)
            or not _IMAGE_SHA256.fullmatch(image_id)
            or not isinstance(repo_digests, list)
            or not any(str(value).endswith(f"@{digest}") for value in repo_digests)
        ):
            raise ValueError("agent runtime image differs from its lock")
        return image_id

    def _verified_model_snapshot(self) -> tuple[Path, Path, str]:
        model = str(self._candidate["model"])
        revision = str(self._candidate["revision"])
        model_root = (
            self._home
            / ".cache"
            / "huggingface"
            / "hub"
            / f"models--{model.replace('/', '--')}"
        ).resolve(strict=True)
        snapshot = (model_root / "snapshots" / revision).resolve(strict=True)
        if snapshot.parent != (model_root / "snapshots").resolve(strict=True):
            raise ValueError("agent model snapshot escaped its cache")
        records: list[dict[str, object]] = []
        required = {"config.json", "tokenizer_config.json"}
        for path in sorted(snapshot.iterdir(), key=lambda item: item.name):
            resolved = path.resolve(strict=True)
            if model_root not in resolved.parents or not resolved.is_file():
                raise ValueError("agent model artifact escaped its cache")
            size = resolved.stat().st_size
            record: dict[str, object] = {
                "path": path.name,
                "blobIdentity": resolved.name,
                "size": size,
            }
            if path.name.endswith(".safetensors"):
                if not _SHA256.fullmatch(resolved.name):
                    raise ValueError("model weight lacks a SHA-256 blob identity")
                record["sha256"] = resolved.name
            else:
                record["sha256"] = _file_sha256(resolved)
            records.append(record)
            required.discard(path.name)
        if required or not any(record["path"].endswith(".safetensors") for record in records):
            raise ValueError("agent model snapshot is incomplete")
        identity = {
            "schemaVersion": 1,
            "model": model,
            "revision": revision,
            "artifacts": records,
        }
        return model_root, snapshot, canonical_evidence_sha256(identity)

    def _launch_arguments(self, snapshot: Path) -> list[str]:
        relative = snapshot.relative_to(
            self._home / ".cache" / "huggingface" / "hub"
        )
        container_snapshot = "/model-cache/" + "/".join(relative.parts[1:])
        arguments = [
            "vllm",
            "serve",
            container_snapshot,
            "--host",
            "127.0.0.1",
            "--port",
            str(_PORT),
            "--served-model-name",
            str(self._candidate["model"]),
            "--reasoning-parser",
            str(self._candidate["reasoningParser"]),
            "--enable-auto-tool-choice",
            "--tool-call-parser",
            str(self._candidate["toolCallParser"]),
            "--max-model-len",
            "8192",
            "--gpu-memory-utilization",
            "0.70",
            "--enable-prefix-caching",
            "--generation-config",
            "vllm",
        ]
        if str(self._candidate["candidateId"]).startswith("qwen3.6-"):
            arguments.append("--language-model-only")
        return arguments

    def _inspect_container(self) -> dict[str, object]:
        return _single_inspection(
            self._run(["docker", "container", "inspect", _CONTAINER_NAME])
        )

    def _verify_container(
        self,
        inspection: dict[str, object],
        *,
        image_id: str,
        arguments: list[str],
    ) -> tuple[int, Path]:
        state = inspection.get("State")
        config = inspection.get("Config")
        labels = config.get("Labels") if isinstance(config, dict) else None
        process_id = state.get("Pid") if isinstance(state, dict) else None
        if (
            inspection.get("Image") != image_id
            or not isinstance(state, dict)
            or state.get("Running") is not True
            or isinstance(process_id, bool)
            or not isinstance(process_id, int)
            or process_id < 2
            or not isinstance(config, dict)
            or config.get("Cmd") != arguments
            or not isinstance(labels, dict)
            or labels.get("io.yap.owner") != "private-inference"
            or labels.get("io.yap.revision") != self._checked_head
        ):
            raise ValueError("agent runtime container ownership differs")
        membership = Path(f"/proc/{process_id}/cgroup").read_text(encoding="ascii")
        lines = [line for line in membership.splitlines() if line.startswith("0::")]
        if len(lines) != 1:
            raise ValueError("agent runtime cgroup membership is invalid")
        cgroup = (Path("/sys/fs/cgroup") / lines[0][3:].lstrip("/")).resolve(strict=True)
        if Path("/sys/fs/cgroup").resolve(strict=True) not in cgroup.parents:
            raise ValueError("agent runtime cgroup escaped its hierarchy")
        return process_id, cgroup

    def _wait_ready(self, timeout_seconds: int) -> None:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{_PORT}/health", timeout=1
                ) as response:
                    if response.status == 200:
                        return
            except (urllib.error.URLError, TimeoutError):
                pass
            if not self._container_exists():
                raise RuntimeError("agent runtime exited before readiness")
            time.sleep(0.25)
        raise TimeoutError("agent runtime readiness timed out")

    def _assert_container_absent(self) -> None:
        if self._container_exists():
            raise RuntimeError("agent runtime container already exists")

    def _container_exists(self) -> bool:
        completed = self._run(
            ["docker", "container", "inspect", _CONTAINER_NAME],
            check=False,
        )
        return completed.returncode == 0

    def _remove_failed_container(self) -> None:
        self._run(["docker", "rm", "--force", _CONTAINER_NAME], check=False)

    def _run(
        self,
        command: list[str],
        *,
        check: bool = True,
        timeout: int = 30,
    ) -> subprocess.CompletedProcess[str]:
        return self._runner(
            command,
            check=check,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            timeout=timeout,
        )


def _single_inspection(completed: subprocess.CompletedProcess[str]) -> dict[str, object]:
    try:
        value = json.loads(completed.stdout)
    except (json.JSONDecodeError, TypeError) as error:
        raise ValueError("Docker inspection is invalid") from error
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        raise ValueError("Docker inspection is ambiguous")
    return value[0]


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _assert_listener_absent(port: int) -> None:
    if not _listener_is_absent(port):
        raise RuntimeError("agent runtime loopback listener is already occupied")


def _listener_is_absent(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.25):
            return False
    except OSError:
        return True


__all__ = ["OwnedAgentVllmRuntime", "StartedAgentVllmRuntime"]
