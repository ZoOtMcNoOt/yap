"""Own one sequential supervised agent-service lifecycle on the private node."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import subprocess
import time
from typing import Callable, Sequence

from yap_server.evaluation.agent_service_lifecycle_observation import (
    AgentServiceLifecycleResult,
    container_pid,
    listener_absent,
    owner_token_processes,
    probe_exact_service,
    process_absent,
    read_service_state,
    recorded_proxy_absent,
    validate_container_policy,
    validate_state_identity,
)
from yap_server.pools.agent_model_snapshot import verify_agent_model_snapshot
from yap_server.pools.agent_vllm_service_profile import (
    AgentVllmServiceProfile,
    load_agent_vllm_service_profile,
)


Runner = Callable[..., subprocess.CompletedProcess[str]]
_PROFILE_MODULES = (
    "agent_model_snapshot.py",
    "agent_vllm_launch_contract.py",
    "agent_vllm_service_profile.py",
    "agent_vllm_service_profile_cli.py",
    "numeric_loopback_endpoint.py",
)
_LAUNCHER_FILES = (
    "agent-vllm-server.sh",
    "private-container-loopback-proxy.sh",
    "owned-process-group.sh",
    "owned-process-supervisor.py",
)
_SUPERVISOR_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"


class AgentServiceLifecycleRuntime:
    """Stage and contain the exact supervisor/launcher path for one route."""

    def __init__(
        self,
        *,
        repository_root: Path,
        checked_head: str,
        supervisor_binary: Path,
        private_root: Path,
        runner: Runner = subprocess.run,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._repository_root = repository_root
        self._checked_head = checked_head
        self._supervisor_binary = supervisor_binary
        self._private_root = private_root
        self._runner = runner
        self._sleep = sleep
        self._process: subprocess.Popen[bytes] | None = None
        self._network_name: str | None = None
        self._owner_token: str | None = None
        self._profile: AgentVllmServiceProfile | None = None
        self._proxy_group_file: Path | None = None
        self._log_files: tuple[object, object] | None = None
        self._observed_process_ids: set[int] = set()

    def run(
        self,
        *,
        profile_id: str,
        model_snapshot: Path,
        timeout_seconds: int = 900,
    ) -> AgentServiceLifecycleResult:
        if self._process is not None or self._network_name is not None:
            raise RuntimeError("agent service lifecycle runtime is already active")
        if profile_id not in {"rapid-automation", "complex-orchestration"}:
            raise ValueError("agent service lifecycle profile is invalid")
        if not 60 <= timeout_seconds <= 1_800:
            raise ValueError("agent service lifecycle timeout is invalid")
        profile_path = (
            self._repository_root
            / "server"
            / "agent-service-profiles"
            / f"{profile_id}.json"
        )
        candidate_lock = (
            self._repository_root
            / "server"
            / "agent-reasoning-candidates.lock.json"
        )
        profile_sha256 = _file_sha256(profile_path)
        profile = load_agent_vllm_service_profile(
            profile_path,
            candidate_lock,
            expected_profile_sha256=profile_sha256,
        )
        verify_agent_model_snapshot(
            expected_model=profile.expected_model,
            model_revision=profile.model_revision,
            expected_manifest_sha256=profile.model_artifact_manifest_sha256,
            snapshot_path=model_snapshot,
        )
        self._profile = profile
        route_root = self._private_root / profile_id
        _make_private_directory(route_root)
        launcher = self._stage_launcher(route_root)
        owner_token = secrets.token_hex(32)
        network_name = f"yap-agent-lifecycle-{owner_token[:16]}"
        self._owner_token = owner_token
        self._network_name = network_name
        proxy_group_file = route_root / "proxy-group"
        self._proxy_group_file = proxy_group_file
        state_path = route_root / "service-state.json"
        try:
            self._create_network(network_name, owner_token)
            process = self._start_supervisor(
                profile=profile,
                profile_path=profile_path,
                profile_sha256=profile_sha256,
                candidate_lock=candidate_lock,
                model_snapshot=model_snapshot,
                launcher=launcher,
                network_name=network_name,
                owner_token=owner_token,
                proxy_group_file=proxy_group_file,
                state_path=state_path,
            )
            self._process = process
            first_state = self._wait_state(
                state_path,
                profile,
                state="ready",
                minimum_generation=1,
                timeout_seconds=timeout_seconds,
            )
            first_container = self._inspect_owned_container(
                profile,
                network_name=network_name,
                owner_token=owner_token,
                model_snapshot=model_snapshot,
            )
            first_pid = container_pid(first_container)
            self._observed_process_ids.add(first_pid)
            self._observe_proxy_process()
            probe_exact_service(profile)
            self._run_command(
                ["docker", "kill", first_container["Id"]],
                timeout=30,
            )
            second_state = self._wait_state(
                state_path,
                profile,
                state="ready",
                minimum_generation=2,
                timeout_seconds=timeout_seconds,
            )
            second_container = self._inspect_owned_container(
                profile,
                network_name=network_name,
                owner_token=owner_token,
                model_snapshot=model_snapshot,
            )
            second_pid = container_pid(second_container)
            self._observed_process_ids.add(second_pid)
            self._observe_proxy_process()
            probe_exact_service(profile)
            new_container = second_container["Id"] != first_container["Id"]
            new_process = first_pid != second_pid and process_absent(first_pid)
            if not new_container or not new_process:
                raise RuntimeError("agent service restart identity did not change")
            process.terminate()
            if process.wait(timeout=30) != 0:
                raise RuntimeError("agent service supervisor did not stop cleanly")
            stopped = self._wait_state(
                state_path,
                profile,
                state="stopped",
                minimum_generation=int(second_state["processGeneration"]),
                timeout_seconds=10,
            )
            teardown = self._wait_teardown(
                profile,
                network_name,
                owner_token,
                timeout_seconds=10,
            )
            if not all(teardown.values()):
                raise RuntimeError("agent service teardown did not complete")
            self._remove_network(network_name)
            network_absent = not self._network_exists(network_name)
            if not network_absent:
                raise RuntimeError("agent service network remained after teardown")
            result = AgentServiceLifecycleResult(
                profile_id=profile.profile_id,
                profile_sha256=profile.profile_sha256,
                candidate_lock_sha256=profile.candidate_lock_sha256,
                image_id=profile.image_id,
                initial_readiness_observed=(
                    first_state["readinessTransitionCount"] == 1
                ),
                restart_readiness_observed=(
                    second_state["readinessTransitionCount"] == 2
                    and second_state["restartCount"] == 1
                ),
                new_container_observed=new_container,
                new_process_observed=new_process,
                stopped_state_observed=stopped["state"] == "stopped",
                container_absent=teardown["containerAbsent"],
                listener_absent=teardown["listenerAbsent"],
                owned_process_absent=teardown["ownedProcessAbsent"],
                network_absent=network_absent,
                same_label_owners_absent=teardown["sameLabelOwnersAbsent"],
            )
            if not all(
                value
                for value in result.public_evidence().values()
                if isinstance(value, bool)
            ):
                raise RuntimeError("agent service lifecycle evidence is incomplete")
            self._clear_runtime()
            return result
        except BaseException as error:
            try:
                self.contain_failed_run()
            except BaseException as containment_error:
                raise containment_error from error
            raise

    def contain_failed_run(self) -> None:
        process = self._process
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
        self._stop_recorded_proxy()
        self._remove_owned_containers()
        if self._network_name is not None:
            self._remove_network(self._network_name, check=False)
        profile = self._profile
        network_name = self._network_name
        owner_token = self._owner_token
        if profile is not None and network_name is not None and owner_token is not None:
            teardown = self._teardown_state(profile, network_name, owner_token)
            teardown["networkAbsent"] = not self._network_exists(network_name)
            if not all(teardown.values()):
                raise RuntimeError("agent service failure containment is incomplete")
        self._clear_runtime()

    def _stage_launcher(self, route_root: Path) -> Path:
        stage = route_root / "runtime"
        if stage.exists() or stage.is_symlink():
            raise ValueError("agent service staged runtime must be new")
        _make_private_directory(stage)
        source_infra = self._repository_root / "infra" / "yap-server-node"
        for name in _LAUNCHER_FILES:
            source = source_infra / name
            destination = stage / name
            _copy_regular_file(source, destination, mode=0o700)
        module_root = stage / "python" / "yap_server" / "pools"
        module_root.mkdir(parents=True, mode=0o700)
        os.chmod(stage / "python", 0o700)
        os.chmod(stage / "python" / "yap_server", 0o700)
        os.chmod(module_root, 0o700)
        source_modules = self._repository_root / "server" / "src" / "yap_server" / "pools"
        for name in _PROFILE_MODULES:
            _copy_regular_file(source_modules / name, module_root / name, mode=0o600)
        return (stage / "agent-vllm-server.sh").resolve(strict=True)

    def _create_network(self, name: str, token: str) -> None:
        self._run_command(
            [
                "docker",
                "network",
                "create",
                "--driver",
                "bridge",
                "--internal",
                "--label",
                "io.yap.owner=private-inference",
                "--label",
                f"io.yap.revision={self._checked_head}",
                "--label",
                f"io.yap.run-token={token}",
                name,
            ]
        )

    def _start_supervisor(
        self,
        *,
        profile: AgentVllmServiceProfile,
        profile_path: Path,
        profile_sha256: str,
        candidate_lock: Path,
        model_snapshot: Path,
        launcher: Path,
        network_name: str,
        owner_token: str,
        proxy_group_file: Path,
        state_path: Path,
    ) -> subprocess.Popen[bytes]:
        stdout_path = state_path.parent / "supervisor.stdout.log"
        stderr_path = state_path.parent / "supervisor.stderr.log"
        stdout = os.fdopen(
            os.open(stdout_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600),
            "wb",
        )
        stderr = os.fdopen(
            os.open(stderr_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600),
            "wb",
        )
        self._log_files = (stdout, stderr)
        environment = {
            "PATH": _SUPERVISOR_PATH,
            "YAP_CHECKED_HEAD": self._checked_head,
            "YAP_AGENT_MODEL_SNAPSHOT": str(model_snapshot),
            "YAP_PRIVATE_INFERENCE_NETWORK": network_name,
            "YAP_RUNTIME_OWNER_TOKEN": owner_token,
            "YAP_PROXY_PROCESS_GROUP_FILE": str(proxy_group_file),
        }
        return subprocess.Popen(
            [
                str(self._supervisor_binary),
                "--service",
                profile.profile_id,
                "--profile",
                str(profile_path.resolve(strict=True)),
                "--profile-sha256",
                profile_sha256,
                "--candidate-lock",
                str(candidate_lock.resolve(strict=True)),
                "--state-path",
                str(state_path),
                "--launcher",
                str(launcher),
                "--",
            ],
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            start_new_session=True,
        )

    def _wait_state(
        self,
        path: Path,
        profile: AgentVllmServiceProfile,
        *,
        state: str,
        minimum_generation: int,
        timeout_seconds: int,
    ) -> dict[str, object]:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            process = self._process
            if process is not None and process.poll() is not None and state != "stopped":
                raise RuntimeError("agent service supervisor exited before readiness")
            try:
                value = read_service_state(path)
            except (OSError, ValueError, json.JSONDecodeError):
                self._sleep(0.25)
                continue
            if (
                value.get("state") == state
                and value.get("processGeneration", 0) >= minimum_generation
            ):
                validate_state_identity(value, profile)
                return value
            self._sleep(0.25)
        raise TimeoutError(f"agent service did not reach {state}")

    def _inspect_owned_container(
        self,
        profile: AgentVllmServiceProfile,
        *,
        network_name: str,
        owner_token: str,
        model_snapshot: Path,
    ) -> dict[str, object]:
        identities = self._owned_container_ids(owner_token)
        if len(identities) != 1:
            raise RuntimeError("agent service container ownership differs")
        result = self._run_command(["docker", "inspect", identities[0]])
        values = json.loads(result.stdout)
        if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], dict):
            raise ValueError("agent service container inspection is invalid")
        value = values[0]
        validate_container_policy(
            value,
            profile=profile,
            checked_head=self._checked_head,
            owner_token=owner_token,
            network_name=network_name,
            model_snapshot=model_snapshot,
        )
        return value

    def _teardown_state(
        self,
        profile: AgentVllmServiceProfile,
        network_name: str,
        owner_token: str,
    ) -> dict[str, bool]:
        observed_process_absence = tuple(
            process_absent(process_id)
            for process_id in sorted(self._observed_process_ids)
        )
        return {
            "containerAbsent": not self._owned_container_ids(owner_token),
            "listenerAbsent": listener_absent(profile.endpoint),
            "ownedProcessAbsent": (
                recorded_proxy_absent(self._proxy_group_file)
                and not owner_token_processes(owner_token)
                and all(observed_process_absence)
            ),
            "sameLabelOwnersAbsent": not self._same_label_owner_ids(),
        }

    def _wait_teardown(
        self,
        profile: AgentVllmServiceProfile,
        network_name: str,
        owner_token: str,
        *,
        timeout_seconds: int,
    ) -> dict[str, bool]:
        deadline = time.monotonic() + timeout_seconds
        while True:
            teardown = self._teardown_state(profile, network_name, owner_token)
            if all(teardown.values()) or time.monotonic() >= deadline:
                return teardown
            self._sleep(0.1)

    def _observe_proxy_process(self) -> int:
        group_file = self._proxy_group_file
        if group_file is None or group_file.is_symlink() or not group_file.is_file():
            raise RuntimeError("agent service proxy identity is unavailable")
        try:
            process_id = int(group_file.read_text(encoding="ascii").strip())
        except (OSError, ValueError) as error:
            raise RuntimeError("agent service proxy identity is invalid") from error
        if process_id <= 1 or process_absent(process_id):
            raise RuntimeError("agent service proxy process is unavailable")
        self._observed_process_ids.add(process_id)
        return process_id

    def _owned_container_ids(self, token: str) -> list[str]:
        result = self._run_command(
            [
                "docker",
                "container",
                "ls",
                "--all",
                "--quiet",
                "--no-trunc",
                "--filter",
                f"label=io.yap.run-token={token}",
            ]
        )
        return [line for line in result.stdout.splitlines() if line]

    def _same_label_owner_ids(self) -> list[str]:
        result = self._run_command(
            [
                "docker",
                "container",
                "ls",
                "--all",
                "--quiet",
                "--no-trunc",
                "--filter",
                f"label=io.yap.revision={self._checked_head}",
                "--filter",
                "label=io.yap.owner=private-inference",
            ]
        )
        return [line for line in result.stdout.splitlines() if line]

    def _remove_owned_containers(self) -> None:
        token = self._owner_token
        if token is None:
            return
        for container_id in self._owned_container_ids(token):
            self._run_command(
                ["docker", "rm", "--force", container_id],
                check=False,
                timeout=20,
            )

    def _stop_recorded_proxy(self) -> None:
        group_file = self._proxy_group_file
        if group_file is None or not group_file.is_file() or group_file.is_symlink():
            return
        try:
            process_id = int(group_file.read_text(encoding="ascii").strip())
        except (OSError, ValueError):
            return
        if process_id > 1:
            self._observed_process_ids.add(process_id)
            try:
                os.killpg(process_id, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def _remove_network(self, name: str, *, check: bool = True) -> None:
        if self._network_exists(name):
            self._run_command(
                ["docker", "network", "rm", name],
                check=check,
                timeout=20,
            )

    def _network_exists(self, name: str) -> bool:
        result = self._run_command(
            ["docker", "network", "inspect", name],
            check=False,
            timeout=10,
        )
        return result.returncode == 0

    def _run_command(
        self,
        arguments: Sequence[str],
        *,
        check: bool = True,
        timeout: int = 30,
    ) -> subprocess.CompletedProcess[str]:
        return self._runner(
            list(arguments),
            capture_output=True,
            check=check,
            text=True,
            timeout=timeout,
        )

    def _clear_runtime(self) -> None:
        if self._log_files is not None:
            for stream in self._log_files:
                stream.close()
        self._process = None
        self._network_name = None
        self._owner_token = None
        self._profile = None
        self._proxy_group_file = None
        self._log_files = None
        self._observed_process_ids.clear()


def _make_private_directory(path: Path) -> None:
    path.mkdir(mode=0o700)
    if os.name == "posix":
        os.chmod(path, 0o700)


def _copy_regular_file(source: Path, destination: Path, *, mode: int) -> None:
    if source.is_symlink() or not source.is_file():
        raise ValueError("agent service runtime source must be a regular file")
    shutil.copyfile(source, destination)
    os.chmod(destination, mode)


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


__all__ = ["AgentServiceLifecycleRuntime"]
