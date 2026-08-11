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


def build_agent_vllm_launch_arguments(
    candidate: dict[str, object],
) -> list[str]:
    """Build the exact checked vLLM command for one admitted workload route."""

    candidate_id = str(candidate.get("candidateId", ""))
    revision = str(candidate.get("revision", ""))
    model = str(candidate.get("model", ""))
    tool_parser = str(candidate.get("toolCallParser", ""))
    final_response_protocol = str(candidate.get("finalResponseProtocol", ""))
    if (
        candidate_id
        not in {"qwen3.6-35b-a3b-nvfp4", "gemma-4-31b-it-nvfp4"}
        or not re.fullmatch(r"[0-9a-f]{40}", revision)
        or not model
        or not tool_parser
    ):
        raise ValueError("agent vLLM launch candidate is invalid")
    arguments = [
        "vllm",
        "serve",
        f"/model-cache/snapshots/{revision}",
        "--host",
        "127.0.0.1",
        "--port",
        str(_PORT),
        "--served-model-name",
        model,
    ]
    if candidate_id == "qwen3.6-35b-a3b-nvfp4":
        reasoning_parser = candidate.get("reasoningParser")
        if (
            reasoning_parser != "qwen3"
            or final_response_protocol != "json-schema"
            or "chatTemplate" in candidate
        ):
            raise ValueError("Qwen reasoning parser is invalid")
        arguments.extend(["--reasoning-parser", reasoning_parser])
    else:
        chat_template = candidate.get("chatTemplate")
        if (
            "reasoningParser" in candidate
            or final_response_protocol != "forced-answer-tool"
            or chat_template
            != "/opt/vllm/vllm-src/examples/tool_chat_template_gemma4.jinja"
        ):
            raise ValueError("Gemma response protocol is invalid")
        arguments.extend(["--chat-template", chat_template])
    arguments.extend(
        [
            "--enable-auto-tool-choice",
            "--tool-call-parser",
            tool_parser,
            "--max-model-len",
            "8192",
            "--tensor-parallel-size",
            "1",
            "--kv-cache-dtype",
            "fp8",
            "--enable-prefix-caching",
            "--enable-chunked-prefill",
            "--async-scheduling",
            "--language-model-only",
        ]
    )
    if candidate_id == "qwen3.6-35b-a3b-nvfp4":
        arguments.extend(
            [
                "--attention-backend",
                "flashinfer",
                "--moe-backend",
                "marlin",
                "--gpu-memory-utilization",
                "0.40",
                "--max-num-seqs",
                "4",
                "--max-num-batched-tokens",
                "8192",
                "--speculative-config",
                json.dumps(
                    {
                        "method": "mtp",
                        "moe_backend": "triton",
                        "num_speculative_tokens": 3,
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                "--load-format",
                "fastsafetensors",
            ]
        )
    else:
        arguments.extend(
            [
                "--gpu-memory-utilization",
                "0.70",
                "--max-num-seqs",
                "8",
                "--max-num-batched-tokens",
                "8192",
                "--load-format",
                "fastsafetensors",
            ]
        )
    return arguments


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


@dataclass(frozen=True, slots=True)
class _PendingAgentVllmRuntime:
    image_id: str
    model_root: Path
    model_artifact_manifest_sha256: str
    launch_arguments_sha256: str
    launch_arguments: tuple[str, ...]


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
        self._pending: _PendingAgentVllmRuntime | None = None
        self._container_created = False
        self._created_container_id: str | None = None

    def start(self, *, timeout_seconds: int) -> StartedAgentVllmRuntime:
        if self._started is not None or self._pending is not None:
            raise RuntimeError("agent runtime is already started")
        if not 1 <= timeout_seconds <= 900:
            raise ValueError("agent runtime startup timeout is invalid")
        self._assert_container_absent()
        _assert_listener_absent(_PORT)
        image_id = self._verified_image_id()
        model_root, snapshot, artifact_sha256 = self._verified_model_snapshot()
        arguments = self._launch_arguments(snapshot)
        argument_sha256 = canonical_evidence_sha256(arguments)
        self._pending = _PendingAgentVllmRuntime(
            image_id=image_id,
            model_root=model_root,
            model_artifact_manifest_sha256=artifact_sha256,
            launch_arguments_sha256=argument_sha256,
            launch_arguments=tuple(arguments),
        )
        completed = self._run(
            [
                "docker",
                "run",
                "-d",
                "--name",
                _CONTAINER_NAME,
                "--pull",
                "never",
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
        self._container_created = True
        if re.fullmatch(r"[0-9a-f]{64}", container_id):
            self._created_container_id = container_id
        started, inspection = self._observe_started_container(
            self._created_container_id or _CONTAINER_NAME
        )
        if container_id != started.container_id:
            raise RuntimeError("agent runtime container identity is invalid")
        self._verify_container_policy(inspection, started=started)
        self._wait_ready(timeout_seconds)
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
            ["docker", "stop", "--time", str(timeout_seconds), started.container_id],
            timeout=timeout_seconds + 10,
        )
        self._run(["docker", "rm", started.container_id])
        container_absent = not self._container_exists(started.container_id)
        listener_absent = _listener_is_absent(_PORT)
        workers_reaped = not Path(f"/proc/{started.process_id}").exists()
        cgroup_empty = _cgroup_is_empty(started.cgroup_path)
        label_owners_absent = self._same_label_owners_absent()
        if not (
            container_absent
            and listener_absent
            and workers_reaped
            and cgroup_empty
            and label_owners_absent
        ):
            raise RuntimeError("agent runtime teardown did not complete")
        self._clear_identity()
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
            "toolCallStructuralGuidanceEnabled": True,
            "childEvidenceSha256": dict(sorted(child_evidence_sha256.items())),
            "teardown": {
                "containerAbsent": container_absent,
                "listenerAbsent": listener_absent,
                "ownedWorkersReaped": workers_reaped,
                "ownedCgroupEmpty": cgroup_empty,
                "sameLabelOwnersAbsent": label_owners_absent,
            },
        }

    def contain_failed_run(self, *, timeout_seconds: int) -> dict[str, object]:
        """Stop a verified runtime and prove containment after candidate rejection."""

        observation_error: BaseException | None = None
        if self._started is None and self._container_created:
            try:
                self._observe_started_container(
                    self._created_container_id or _CONTAINER_NAME
                )
            except BaseException as error:
                observation_error = error
        started = self._started
        target = self._created_container_id or _CONTAINER_NAME
        self._run(
            ["docker", "stop", "--time", str(timeout_seconds), target],
            check=False,
            timeout=timeout_seconds + 10,
        )
        self._run(["docker", "rm", "--force", target], check=False)
        identity_unobserved = self._container_created and started is None
        teardown = {
            "containerAbsent": not self._container_exists(target),
            "listenerAbsent": _listener_is_absent(_PORT),
            "ownedWorkersReaped": (
                True
                if started is None
                else not Path(f"/proc/{started.process_id}").exists()
            ),
            "ownedCgroupEmpty": (
                True if started is None else _cgroup_is_empty(started.cgroup_path)
            ),
            "sameLabelOwnersAbsent": self._same_label_owners_absent(),
        }
        if not all(teardown.values()):
            raise RuntimeError("failed agent runtime containment did not complete")
        if identity_unobserved:
            raise RuntimeError(
                "created agent runtime identity could not be observed for containment"
            ) from observation_error
        if started is None:
            raise RuntimeError("failed agent runtime was not created")
        self._clear_identity()
        return {
            "imageId": started.image_id,
            "modelArtifactManifestSha256": started.model_artifact_manifest_sha256,
            "launchArguments": list(started.launch_arguments),
            "launchArgumentsSha256": started.launch_arguments_sha256,
            "teardown": teardown,
        }

    def _verified_image_id(self) -> str:
        image = str(self._runtime.get("image", ""))
        inspected = _single_inspection(self._run(["docker", "image", "inspect", image]))
        image_id = inspected.get("Id")
        expected_image_id = self._runtime.get("observedImageId")
        repo_digests = inspected.get("RepoDigests")
        provenance = self._runtime.get("provenance")
        if not (
            inspected.get("Os") == "linux"
            and inspected.get("Architecture") == "arm64"
            and isinstance(image_id, str)
            and _IMAGE_SHA256.fullmatch(image_id)
            and image_id == expected_image_id
            and isinstance(provenance, dict)
        ):
            raise ValueError("agent runtime image differs from its lock")
        kind = provenance.get("kind")
        if kind == "upstream-manifest":
            manifest_digest = self._runtime.get("manifestDigest")
            if (
                not isinstance(manifest_digest, str)
                or _IMAGE_SHA256.fullmatch(manifest_digest) is None
                or not isinstance(repo_digests, list)
                or not any(
                    str(value).endswith(f"@{manifest_digest}")
                    for value in repo_digests
                )
            ):
                raise ValueError("agent runtime image differs from its lock")
        elif kind == "xgrammar-wheel-overlay":
            config = inspected.get("Config")
            labels = config.get("Labels") if isinstance(config, dict) else None
            if (
                repo_digests not in (None, [])
                or not isinstance(labels, dict)
                or labels.get("io.yap.base-manifest-digest")
                != provenance.get("baseManifestDigest")
                or labels.get("io.yap.xgrammar-version")
                != self._runtime.get("xgrammar")
                or labels.get("io.yap.xgrammar-wheel-sha256")
                != provenance.get("wheelSha256")
                or labels.get("io.yap.runtime") != "agent-vllm"
            ):
                raise ValueError("agent runtime image differs from its lock")
        else:
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
        if required or not any(
            record["path"].endswith(".safetensors") for record in records
        ):
            raise ValueError("agent model snapshot is incomplete")
        identity = {
            "schemaVersion": 1,
            "model": model,
            "revision": revision,
            "artifacts": records,
        }
        observed_manifest = canonical_evidence_sha256(identity)
        if observed_manifest != self._candidate.get("artifactManifestSha256"):
            raise ValueError("agent model artifacts differ from the checked manifest")
        return model_root, snapshot, observed_manifest

    def _launch_arguments(self, snapshot: Path) -> list[str]:
        if snapshot.name != self._candidate.get("revision"):
            raise ValueError("agent model snapshot revision differs")
        return build_agent_vllm_launch_arguments(self._candidate)

    def _inspect_container(self, target: str) -> dict[str, object]:
        return _single_inspection(
            self._run(["docker", "container", "inspect", target])
        )

    def _observe_started_container(
        self, target: str
    ) -> tuple[StartedAgentVllmRuntime, dict[str, object]]:
        pending = self._pending
        if pending is None:
            raise RuntimeError("agent runtime launch identity is unavailable")
        inspection = self._inspect_container(target)
        state = inspection.get("State")
        container_id = inspection.get("Id")
        process_id = state.get("Pid") if isinstance(state, dict) else None
        if (
            not isinstance(container_id, str)
            or not re.fullmatch(r"[0-9a-f]{64}", container_id)
            or (
                self._created_container_id is not None
                and container_id != self._created_container_id
            )
            or not isinstance(state, dict)
            or state.get("Running") is not True
            or isinstance(process_id, bool)
            or not isinstance(process_id, int)
            or process_id < 2
        ):
            raise ValueError("agent runtime observed identity differs")
        self._created_container_id = container_id
        cgroup_path = _owned_cgroup_path(process_id)
        started = StartedAgentVllmRuntime(
            endpoint=f"http://127.0.0.1:{_PORT}",
            container_name=_CONTAINER_NAME,
            container_id=container_id,
            image_id=pending.image_id,
            model_artifact_manifest_sha256=(
                pending.model_artifact_manifest_sha256
            ),
            launch_arguments_sha256=pending.launch_arguments_sha256,
            launch_arguments=pending.launch_arguments,
            cgroup_path=cgroup_path,
            process_id=process_id,
        )
        self._started = started
        return started, inspection

    def _verify_container_policy(
        self,
        inspection: dict[str, object],
        *,
        started: StartedAgentVllmRuntime,
    ) -> None:
        config = inspection.get("Config")
        labels = config.get("Labels") if isinstance(config, dict) else None
        environment = config.get("Env") if isinstance(config, dict) else None
        host_config = inspection.get("HostConfig")
        mounts = inspection.get("Mounts")
        pending = self._pending
        if (
            pending is None
            or inspection.get("Id") != started.container_id
            or inspection.get("Name") != f"/{_CONTAINER_NAME}"
            or inspection.get("Image") != started.image_id
            or not isinstance(config, dict)
            or config.get("Cmd") != list(started.launch_arguments)
            or config.get("User") != "1000:1000"
            or not isinstance(environment, list)
            or "HOME=/tmp" not in environment
            or any(
                isinstance(value, str)
                and value.startswith("VLLM_ENFORCE_STRICT_TOOL_CALLING=")
                for value in environment
            )
            or not isinstance(labels, dict)
            or labels.get("io.yap.owner") != "private-inference"
            or labels.get("io.yap.revision") != self._checked_head
            or not _exact_vllm_host_policy(host_config)
            or not _exact_read_only_model_mount(mounts, pending.model_root)
        ):
            raise ValueError("agent runtime container ownership differs")

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
            if not self._container_exists(self._created_container_id or _CONTAINER_NAME):
                raise RuntimeError("agent runtime exited before readiness")
            time.sleep(0.25)
        raise TimeoutError("agent runtime readiness timed out")

    def _assert_container_absent(self) -> None:
        if self._container_exists(_CONTAINER_NAME):
            raise RuntimeError("agent runtime container already exists")

    def _container_exists(self, target: str) -> bool:
        completed = self._run(
            ["docker", "container", "inspect", target],
            check=False,
        )
        return completed.returncode == 0

    def _same_label_owners_absent(self) -> bool:
        completed = self._run(
            [
                "docker",
                "ps",
                "--all",
                "--quiet",
                "--filter",
                "label=io.yap.owner=private-inference",
                "--filter",
                f"label=io.yap.revision={self._checked_head}",
            ],
            check=False,
        )
        return completed.returncode == 0 and not completed.stdout.strip()

    def _clear_identity(self) -> None:
        self._started = None
        self._pending = None
        self._container_created = False
        self._created_container_id = None

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


def _single_inspection(
    completed: subprocess.CompletedProcess[str],
) -> dict[str, object]:
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


def _owned_cgroup_path(process_id: int) -> Path:
    membership = Path(f"/proc/{process_id}/cgroup").read_text(encoding="ascii")
    lines = [line for line in membership.splitlines() if line.startswith("0::")]
    if len(lines) != 1:
        raise ValueError("agent runtime cgroup membership is invalid")
    hierarchy = Path("/sys/fs/cgroup").resolve(strict=True)
    cgroup = (hierarchy / lines[0][3:].lstrip("/")).resolve(strict=True)
    if hierarchy not in cgroup.parents:
        raise ValueError("agent runtime cgroup escaped its hierarchy")
    return cgroup


def _exact_vllm_host_policy(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    ulimits = value.get("Ulimits")
    requests = value.get("DeviceRequests")
    expected_ulimits = {
        ("memlock", -1, -1),
        ("stack", 67_108_864, 67_108_864),
    }
    observed_ulimits = (
        {
            (item.get("Name"), item.get("Soft"), item.get("Hard"))
            for item in ulimits
            if isinstance(item, dict)
        }
        if isinstance(ulimits, list)
        else set()
    )
    if (
        value.get("NetworkMode") != "host"
        or value.get("IpcMode") != "host"
        or observed_ulimits != expected_ulimits
        or not isinstance(requests, list)
        or len(requests) != 1
        or not isinstance(requests[0], dict)
        or requests[0].get("Count") != -1
    ):
        return False
    capabilities = requests[0].get("Capabilities")
    return (
        isinstance(capabilities, list)
        and len(capabilities) == 1
        and capabilities[0] == ["gpu"]
    )


def _exact_read_only_model_mount(value: object, model_root: Path) -> bool:
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        return False
    mount = value[0]
    try:
        source = Path(str(mount.get("Source"))).resolve(strict=True)
    except (OSError, RuntimeError):
        return False
    return (
        mount.get("Type") == "bind"
        and mount.get("Destination") == "/model-cache"
        and mount.get("RW") is False
        and source == model_root
    )


def _assert_listener_absent(port: int) -> None:
    if not _listener_is_absent(port):
        raise RuntimeError("agent runtime loopback listener is already occupied")


def _listener_is_absent(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.25):
            return False
    except OSError:
        return True


def _cgroup_is_empty(path: Path) -> bool:
    try:
        contents = (path / "cgroup.procs").read_text(encoding="ascii")
    except FileNotFoundError:
        return True
    return not contents.split()


__all__ = ["OwnedAgentVllmRuntime", "StartedAgentVllmRuntime"]
