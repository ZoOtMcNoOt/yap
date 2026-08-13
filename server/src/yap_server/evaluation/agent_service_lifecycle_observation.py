"""Validate public-safe state, runtime identity, and teardown observations."""

from __future__ import annotations

from dataclasses import dataclass
import http.client
import json
import os
from pathlib import Path
import socket
import stat

from yap_server.pools.agent_vllm_service_profile import AgentVllmServiceProfile
from yap_server.pools.numeric_loopback_endpoint import (
    parse_numeric_loopback_http_endpoint,
)


_SNAPSHOT_KEYS = {
    "schemaVersion",
    "service",
    "profileId",
    "profileSha256",
    "candidateLockSha256",
    "state",
    "processGeneration",
    "startCount",
    "restartCount",
    "consecutiveFailureCount",
    "readinessTransitionCount",
}


class _DuplicateJsonKeyError(ValueError):
    pass


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKeyError(key)
        result[key] = value
    return result


@dataclass(frozen=True, slots=True)
class AgentServiceLifecycleResult:
    profile_id: str
    profile_sha256: str
    candidate_lock_sha256: str
    image_id: str
    initial_readiness_observed: bool
    restart_readiness_observed: bool
    new_container_observed: bool
    new_process_observed: bool
    stopped_state_observed: bool
    container_absent: bool
    listener_absent: bool
    owned_process_absent: bool
    network_absent: bool
    same_label_owners_absent: bool

    def public_evidence(self) -> dict[str, object]:
        return {
            "profileId": self.profile_id,
            "profileSha256": self.profile_sha256,
            "candidateLockSha256": self.candidate_lock_sha256,
            "imageId": self.image_id,
            "initialReadinessObserved": self.initial_readiness_observed,
            "restartReadinessObserved": self.restart_readiness_observed,
            "newContainerObserved": self.new_container_observed,
            "newProcessObserved": self.new_process_observed,
            "stoppedStateObserved": self.stopped_state_observed,
            "teardown": {
                "containerAbsent": self.container_absent,
                "listenerAbsent": self.listener_absent,
                "ownedProcessAbsent": self.owned_process_absent,
                "networkAbsent": self.network_absent,
                "sameLabelOwnersAbsent": self.same_label_owners_absent,
            },
        }


def validate_container_policy(
    value: dict[str, object],
    *,
    profile: AgentVllmServiceProfile,
    checked_head: str,
    owner_token: str,
    network_name: str,
    model_snapshot: Path,
) -> None:
    config = value.get("Config")
    host = value.get("HostConfig")
    state = value.get("State")
    network_settings = value.get("NetworkSettings")
    mounts = value.get("Mounts")
    if not all(
        isinstance(item, dict) for item in (config, host, state, network_settings)
    ):
        raise ValueError("agent service container inspection is incomplete")
    assert isinstance(config, dict)
    assert isinstance(host, dict)
    assert isinstance(state, dict)
    assert isinstance(network_settings, dict)
    labels = config.get("Labels")
    environment = config.get("Env")
    networks = network_settings.get("Networks")
    expected_labels = {
        "io.yap.owner": "private-inference",
        "io.yap.revision": checked_head,
        "io.yap.run-token": owner_token,
        "io.yap.agent-profile": profile.profile_id,
        "io.yap.model": profile.expected_model,
        "io.yap.model-revision": profile.model_revision,
        "io.yap.model-artifact-sha256": profile.model_artifact_manifest_sha256,
    }
    container_id = value.get("Id")
    if (
        not isinstance(container_id, str)
        or len(container_id) != 64
        or any(character not in "0123456789abcdef" for character in container_id)
        or value.get("Name") != f"/{profile.container_name}"
        or value.get("Image") != profile.image_id
        or state.get("Running") is not True
        or container_pid(value) <= 1
        or config.get("Cmd") != list(profile.launch_arguments)
        or not isinstance(labels, dict)
        or any(labels.get(key) != expected for key, expected in expected_labels.items())
        or not _exact_environment(environment, profile)
        or config.get("User") != f"{os.getuid()}:{os.getgid()}"
        or config.get("StopTimeout") != 10
        or not _exact_host_policy(host, profile, network_name)
        or not isinstance(networks, dict)
        or set(networks) != {network_name}
        or not isinstance(mounts, list)
        or not _exact_model_mount(mounts, model_snapshot)
    ):
        raise RuntimeError("agent service container policy differs")


def _exact_environment(
    value: object,
    profile: AgentVllmServiceProfile,
) -> bool:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return False
    required = {
        "HF_HUB_OFFLINE=1",
        "TRANSFORMERS_OFFLINE=1",
        "HF_HUB_DISABLE_TELEMETRY=1",
        "DO_NOT_TRACK=1",
        "HOME=/tmp",
    }
    batch_invariance = [
        item for item in value if item.startswith("VLLM_BATCH_INVARIANT=")
    ]
    expected_batch_invariance = (
        ["VLLM_BATCH_INVARIANT=1"] if profile.batch_invariant else []
    )
    return (
        required.issubset(value)
        and batch_invariance == expected_batch_invariance
        and not any(
            item.startswith(("VLLM_API_KEY=", "HF_TOKEN=", "HUGGING_FACE_HUB_TOKEN="))
            for item in value
        )
    )


def _exact_host_policy(
    value: dict[str, object],
    profile: AgentVllmServiceProfile,
    network_name: str,
) -> bool:
    ulimits = value.get("Ulimits")
    requests = value.get("DeviceRequests")
    tmpfs = value.get("Tmpfs")
    log_config = value.get("LogConfig")
    observed_ulimits = (
        {
            (item.get("Name"), item.get("Soft"), item.get("Hard"))
            for item in ulimits
            if isinstance(item, dict)
        }
        if isinstance(ulimits, list)
        else set()
    )
    expected_tmpfs = {
        "rw",
        "nosuid",
        "nodev",
        "exec",
        f"size={profile.resources.tmpfs_bytes}",
        "mode=1777",
    }
    return (
        value.get("NetworkMode") == network_name
        and value.get("IpcMode") == "host"
        and value.get("ReadonlyRootfs") is True
        and value.get("Privileged") is False
        and value.get("AutoRemove") is False
        and value.get("PublishAllPorts") is False
        and value.get("PortBindings") in (None, {})
        and value.get("CapDrop") == ["ALL"]
        and value.get("SecurityOpt")
        in (
            ["no-new-privileges", "label=disable"],
            ["no-new-privileges:true", "label=disable"],
        )
        and value.get("Memory") == profile.resources.memory_bytes
        and value.get("MemorySwap") == profile.resources.memory_swap_bytes
        and value.get("NanoCpus") == profile.resources.cpu_count * 1_000_000_000
        and value.get("PidsLimit") == profile.resources.pids_limit
        and value.get("ShmSize") == profile.resources.shm_bytes
        and observed_ulimits
        == {
            ("memlock", -1, -1),
            ("stack", 67_108_864, 67_108_864),
        }
        and requests
        == [
            {
                "Driver": "",
                "Count": -1,
                "DeviceIDs": None,
                "Capabilities": [["gpu"]],
                "Options": {},
            }
        ]
        and isinstance(tmpfs, dict)
        and set(tmpfs) == {"/tmp"}
        and isinstance(tmpfs["/tmp"], str)
        and set(tmpfs["/tmp"].split(",")) == expected_tmpfs
        and log_config
        == {
            "Type": "local",
            "Config": {"max-file": "3", "max-size": "10m"},
        }
    )


def _exact_model_mount(mounts: list[object], model_snapshot: Path) -> bool:
    model_root = model_snapshot.resolve(strict=True).parent.parent.resolve(strict=True)
    matches = [
        value
        for value in mounts
        if isinstance(value, dict) and value.get("Destination") == "/model-cache"
    ]
    return (
        len(mounts) == 1
        and len(matches) == 1
        and (
            matches[0].get("Type") == "bind"
            and matches[0].get("RW") is False
            and matches[0].get("Source") == str(model_root)
        )
    )


def validate_state_identity(
    value: dict[str, object],
    profile: AgentVllmServiceProfile,
) -> None:
    if (
        set(value) != _SNAPSHOT_KEYS
        or value.get("schemaVersion") != 2
        or value.get("service") != profile.service
        or value.get("profileId") != profile.profile_id
        or value.get("profileSha256") != profile.profile_sha256
        or value.get("candidateLockSha256") != profile.candidate_lock_sha256
    ):
        raise ValueError("agent service state identity differs")
    for field in (
        "processGeneration",
        "startCount",
        "restartCount",
        "consecutiveFailureCount",
        "readinessTransitionCount",
    ):
        field_value = value.get(field)
        if (
            isinstance(field_value, bool)
            or not isinstance(field_value, int)
            or field_value < 0
        ):
            raise ValueError("agent service state counter is invalid")


def read_service_state(path: Path) -> dict[str, object]:
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise ValueError("agent service state must be a regular file")
    if os.name == "posix" and stat.S_IMODE(metadata.st_mode) & 0o077:
        raise ValueError("agent service state must be owner-private")
    if metadata.st_size > 8_192:
        raise ValueError("agent service state exceeds its byte bound")
    try:
        value = json.loads(
            path.read_bytes(),
            object_pairs_hook=_unique_json_object,
        )
    except _DuplicateJsonKeyError as error:
        raise ValueError("agent service state is invalid") from error
    if not isinstance(value, dict):
        raise ValueError("agent service state is invalid")
    return value


def probe_exact_service(profile: AgentVllmServiceProfile) -> None:
    host, port = parse_numeric_loopback_http_endpoint(
        profile.endpoint,
        component="agent service lifecycle",
    )
    connection = http.client.HTTPConnection(host, port, timeout=5)
    try:
        connection.request("GET", "/health")
        response = connection.getresponse()
        response.read(1_025)
        if response.status != 200:
            raise RuntimeError("agent service health response differs")
    finally:
        connection.close()
    connection = http.client.HTTPConnection(host, port, timeout=5)
    try:
        connection.request("GET", "/v1/models")
        response = connection.getresponse()
        payload = response.read(65_537)
        if response.status != 200 or len(payload) > 65_536:
            raise RuntimeError("agent service model response differs")
        value = json.loads(payload, object_pairs_hook=_unique_json_object)
        if (
            not isinstance(value, dict)
            or not isinstance(value.get("data"), list)
            or len(value["data"]) != 1
            or not isinstance(value["data"][0], dict)
            or value["data"][0].get("id") != profile.expected_model
        ):
            raise RuntimeError("agent service model identity differs")
    finally:
        connection.close()


def container_pid(value: dict[str, object]) -> int:
    state = value.get("State")
    process_id = state.get("Pid") if isinstance(state, dict) else None
    if (
        isinstance(process_id, bool)
        or not isinstance(process_id, int)
        or process_id <= 1
    ):
        raise ValueError("agent service container process identity is invalid")
    return process_id


def process_absent(process_id: int) -> bool:
    return not Path(f"/proc/{process_id}").exists()


def listener_absent(endpoint: str) -> bool:
    host, port = parse_numeric_loopback_http_endpoint(
        endpoint,
        component="agent service lifecycle",
    )
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return False
    except OSError:
        return True


def recorded_proxy_absent(group_file: Path | None) -> bool:
    if group_file is None or not group_file.exists():
        return True
    if group_file.is_symlink() or not group_file.is_file():
        return False
    try:
        process_id = int(group_file.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return False
    return process_absent(process_id)


def owner_token_processes(owner_token: str) -> tuple[int, ...]:
    marker = f"YAP_RUNTIME_OWNER_TOKEN={owner_token}".encode("ascii")
    matches: list[int] = []
    for environment_path in Path("/proc").glob("[0-9]*/environ"):
        try:
            payload = environment_path.read_bytes()
        except OSError:
            continue
        if len(payload) <= 1024 * 1024 and marker in payload.split(b"\0"):
            matches.append(int(environment_path.parent.name))
    return tuple(matches)


__all__ = [
    "AgentServiceLifecycleResult",
    "container_pid",
    "listener_absent",
    "owner_token_processes",
    "probe_exact_service",
    "process_absent",
    "read_service_state",
    "recorded_proxy_absent",
    "validate_container_policy",
    "validate_state_identity",
]
