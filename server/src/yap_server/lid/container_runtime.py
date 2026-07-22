from __future__ import annotations

from collections.abc import Callable
import json
import os
from pathlib import Path
import re
import subprocess
import stat
import threading
from typing import Any
from uuid import uuid4

from yap_server.pools.batch_contract import WorkerExecutionError
from yap_server.pools.container_runtime import (
    JOB_LABEL,
    OWNER_LABEL,
    REVISION_LABEL,
    RUNTIME_LABEL,
    STORAGE_LABEL,
    force_remove_container,
    reconcile_owned_containers,
    run_bounded_process,
)

from .component_lock import LidComponentLock
from .worker_contract import (
    LidWorkerRequest,
    WorkerResultError,
    load_lid_worker_request,
    validate_lid_worker_result,
)


_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_IMMUTABLE_IMAGE = re.compile(r"^(?:sha256:[0-9a-f]{64}|.+@sha256:[0-9a-f]{64})$")
_LABEL_VALUE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_OWNER_VALUE = "lid-preflight"
_MAX_OUTPUT_BYTES = 64 * 1024


def reconcile_lid_containers(
    docker_binary: str,
    *,
    storage_namespace: str,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> int:
    return reconcile_owned_containers(
        docker_binary,
        storage_namespace=storage_namespace,
        owner_value=_OWNER_VALUE,
        runner=runner,
    )


class ContainerLidWorker:
    """One-shot, replaceable execution adapter for assistive LID inference."""

    def __init__(
        self,
        *,
        image: str,
        model_dir: Path,
        lock: LidComponentLock,
        run_as_uid: int,
        run_as_gid: int,
        checked_head: str,
        storage_namespace: str,
        runtime_instance_id: str | None = None,
        docker_binary: str = "docker",
        timeout_seconds: float = 120.0,
        runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
        process_runner: Callable[
            ..., subprocess.CompletedProcess[str]
        ] = run_bounded_process,
        container_remover: Callable[[str, str], None] = force_remove_container,
    ) -> None:
        if _IMMUTABLE_IMAGE.fullmatch(image) is None:
            raise ValueError("LID worker image must use an immutable digest")
        if not isinstance(lock, LidComponentLock):
            raise TypeError("lock must be a validated LidComponentLock")
        if _GIT_SHA.fullmatch(checked_head) is None:
            raise ValueError("LID worker checked head must be a full Git SHA")
        if _LABEL_VALUE.fullmatch(storage_namespace) is None:
            raise ValueError("LID worker storage namespace is invalid")
        runtime_id = runtime_instance_id or uuid4().hex
        if _LABEL_VALUE.fullmatch(runtime_id) is None:
            raise ValueError("LID worker runtime identity is invalid")
        if (
            not isinstance(run_as_uid, int)
            or isinstance(run_as_uid, bool)
            or run_as_uid < 1
            or not isinstance(run_as_gid, int)
            or isinstance(run_as_gid, bool)
            or run_as_gid < 1
        ):
            raise ValueError(
                "LID worker identity must be an explicit non-root UID and GID"
            )
        if timeout_seconds <= 0:
            raise ValueError("LID worker timeout must be positive")
        self._image = image
        self._model_dir = _safe_mount_path(
            _resolve_real_directory(Path(model_dir), "LID model root")
        )
        self._lock = lock
        self._identity = f"{run_as_uid}:{run_as_gid}"
        self._uid = run_as_uid
        self._gid = run_as_gid
        self._checked_head = checked_head
        self._storage_namespace = storage_namespace
        self._runtime_instance_id = runtime_id
        self._docker_binary = docker_binary
        self._timeout_seconds = timeout_seconds
        self._runner = runner
        self._process_runner = process_runner
        self._container_remover = container_remover
        self._shutdown = threading.Event()

    def close(self) -> None:
        self._shutdown.set()

    def build_command(self, request: LidWorkerRequest, request_root: Path) -> list[str]:
        return self._build_command(
            request,
            request_root,
            container_name=f"yap-language-detection-{uuid4().hex}",
        )

    def _build_command(
        self,
        request: LidWorkerRequest,
        request_root: Path,
        *,
        container_name: str,
    ) -> list[str]:
        root = _safe_mount_path(
            _resolve_real_directory(Path(request_root), "LID request root")
        )
        persisted = load_lid_worker_request(root / "request.json", self._lock)
        if persisted != request:
            raise ValueError("LID request differs from its materialized contract")
        return [
            self._docker_binary,
            "run",
            "--rm",
            "--name",
            container_name,
            "--label",
            f"{OWNER_LABEL}={_OWNER_VALUE}",
            "--label",
            f"{STORAGE_LABEL}={self._storage_namespace}",
            "--label",
            f"{RUNTIME_LABEL}={self._runtime_instance_id}",
            "--label",
            f"{JOB_LABEL}={request.request_id}",
            "--label",
            f"{REVISION_LABEL}={self._checked_head}",
            "--pull",
            "never",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--user",
            self._identity,
            "--pids-limit",
            "128",
            "--memory",
            "2g",
            "--memory-swap",
            "2g",
            "--cpus",
            "4",
            "--shm-size",
            "256m",
            "--tmpfs",
            (
                "/tmp:rw,nosuid,nodev,noexec,size=512m,mode=0700,"
                f"uid={self._uid},gid={self._gid}"
            ),
            "--env",
            "HF_HUB_OFFLINE=1",
            "--env",
            "TRANSFORMERS_OFFLINE=1",
            "--env",
            "HF_HUB_DISABLE_TELEMETRY=1",
            "--env",
            "DO_NOT_TRACK=1",
            "--mount",
            f"type=bind,src={self._model_dir},dst=/models/lid,readonly",
            "--mount",
            f"type=bind,src={root},dst=/request,readonly",
            self._image,
            "--model-dir",
            "/models/lid",
            "--request",
            "/request/request.json",
            "--probe-dir",
            "/request",
        ]

    def run(
        self,
        request: LidWorkerRequest,
        request_root: Path,
        cancellation: threading.Event | None = None,
    ) -> dict[str, Any]:
        cancelled = cancellation or threading.Event()
        if self._shutdown.is_set() or cancelled.is_set():
            raise WorkerExecutionError("isolated LID worker was cancelled")
        container_name = f"yap-language-detection-{uuid4().hex}"
        command = self._build_command(
            request,
            request_root,
            container_name=container_name,
        )
        if self._runner is None:
            try:
                completed = self._process_runner(
                    command,
                    timeout_seconds=self._timeout_seconds,
                    output_limit_bytes=_MAX_OUTPUT_BYTES,
                    cancellation=(self._shutdown, cancelled),
                )
            finally:
                self._container_remover(self._docker_binary, container_name)
        else:
            completed = self._runner(
                command,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self._timeout_seconds,
                stdin=subprocess.DEVNULL,
            )
        _validate_output(completed)
        if completed.returncode != 0:
            raise WorkerExecutionError(
                f"isolated LID worker exited with status {completed.returncode}"
            )
        try:
            payload = json.loads(completed.stdout)
            validate_lid_worker_result(payload, request=request, lock=self._lock)
        except json.JSONDecodeError as error:
            raise WorkerExecutionError(
                "isolated LID worker returned invalid JSON"
            ) from error
        except WorkerResultError as error:
            raise WorkerExecutionError(str(error)) from error
        if not isinstance(payload, dict):
            raise WorkerExecutionError("isolated LID worker returned an invalid result")
        return payload


def _safe_mount_path(path: Path) -> Path:
    if any(character in str(path) for character in (",", "\n", "\r")):
        raise ValueError("LID container mount paths cannot contain commas or newlines")
    return path


def _resolve_real_directory(path: Path, field: str) -> Path:
    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise ValueError(f"{field} is missing") from error
    if (
        stat.S_ISLNK(metadata.st_mode)
        or bool(getattr(metadata, "st_file_attributes", 0) & 0x400)
        or not stat.S_ISDIR(metadata.st_mode)
    ):
        raise ValueError(f"{field} must be a real directory")
    resolved = path.resolve(strict=True)
    opened = os.stat(resolved)
    if (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino):
        raise ValueError(f"{field} changed during validation")
    return resolved


def _validate_output(completed: subprocess.CompletedProcess[str]) -> None:
    for stream in (completed.stdout, completed.stderr):
        if not isinstance(stream, str):
            raise WorkerExecutionError(
                "isolated LID worker output was not decoded text"
            )
        if len(stream.encode("utf-8", errors="replace")) > _MAX_OUTPUT_BYTES:
            raise WorkerExecutionError(
                "isolated LID worker exceeded the bounded output"
            )
