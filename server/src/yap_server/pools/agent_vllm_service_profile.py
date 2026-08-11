from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re

from .agent_vllm_launch_contract import (
    build_qualified_agent_vllm_launch_arguments,
    validate_qualified_agent_vllm_route_policy,
)
from .numeric_loopback_endpoint import parse_numeric_loopback_http_endpoint


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_IMAGE_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_NAME = re.compile(r"^[a-z0-9][a-z0-9.-]{0,63}$")
_CONTAINER_NAME = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,127}$")
_MAX_DOCUMENT_BYTES = 1_048_576
_COMMON_PROFILE_KEYS = {
    "schemaVersion",
    "profileId",
    "service",
    "endpoint",
    "containerName",
    "candidateLockSha256",
    "candidateId",
    "runtimeId",
    "expectedModel",
    "modelRevision",
    "modelArtifactManifestSha256",
    "toolCallParser",
    "finalResponseProtocol",
    "containerPort",
    "maximumModelLength",
    "maximumSequences",
    "maximumBatchedTokens",
    "gpuMemoryUtilization",
    "loadFormat",
    "resources",
}
_RESOURCE_KEYS = {
    "memoryBytes",
    "memorySwapBytes",
    "cpuCount",
    "pidsLimit",
    "shmBytes",
    "tmpfsBytes",
}


@dataclass(frozen=True, slots=True)
class AgentContainerResources:
    memory_bytes: int
    memory_swap_bytes: int
    cpu_count: int
    pids_limit: int
    shm_bytes: int
    tmpfs_bytes: int


@dataclass(frozen=True, slots=True)
class AgentVllmServiceProfile:
    profile_sha256: str
    profile_id: str
    service: str
    endpoint: str
    container_name: str
    candidate_lock_sha256: str
    candidate_id: str
    runtime_id: str
    expected_model: str
    model_revision: str
    model_artifact_manifest_sha256: str
    image: str
    image_id: str
    container_port: int
    maximum_sequences: int
    resources: AgentContainerResources
    launch_arguments: tuple[str, ...]

    def validate_identity(self) -> None:
        expected = _PROFILE_IDENTITIES.get(self.profile_id)
        if expected is None or (
            self.service,
            self.candidate_id,
            self.runtime_id,
            self.expected_model,
            self.container_name,
            self.endpoint,
        ) != expected:
            raise ValueError("agent service profile identity differs")


_PROFILE_IDENTITIES = {
    "rapid-automation": (
        "rapid-automation",
        "qwen3.6-35b-a3b-nvfp4",
        "qwen-vllm-26.07-xgrammar-0.2.1",
        "nvidia/Qwen3.6-35B-A3B-NVFP4",
        "yap-agent-qwen-rapid",
        "http://127.0.0.1:18100",
    ),
    "complex-orchestration": (
        "complex-orchestration",
        "gemma-4-31b-it-nvfp4",
        "gemma-vllm-26.06",
        "nvidia/Gemma-4-31B-IT-NVFP4",
        "yap-agent-gemma-complex",
        "http://127.0.0.1:18101",
    ),
}


def load_agent_vllm_service_profile(
    profile_path: Path,
    candidate_lock_path: Path,
    *,
    expected_profile_sha256: str,
) -> AgentVllmServiceProfile:
    """Load one exact production profile and bind it to the qualified lock."""

    profile_bytes = _read_regular_bytes(profile_path, "agent service profile")
    if (
        not _SHA256.fullmatch(expected_profile_sha256)
        or hashlib.sha256(profile_bytes).hexdigest() != expected_profile_sha256
    ):
        raise ValueError("agent service profile bytes differ")
    profile = _json_object(profile_bytes, "agent service profile")
    profile_id = _text(profile, "profileId")
    variant_keys = {
        "rapid-automation": {
            "reasoningParser",
            "attentionBackend",
            "moeBackend",
            "speculativeConfig",
        },
        "complex-orchestration": {"chatTemplate"},
    }.get(profile_id)
    if variant_keys is None or set(profile) != _COMMON_PROFILE_KEYS | variant_keys:
        raise ValueError("agent service profile shape differs")
    if profile.get("schemaVersion") != 1:
        raise ValueError("agent service profile schema differs")

    candidate_lock_bytes = _read_regular_bytes(
        candidate_lock_path,
        "agent candidate lock",
    )
    candidate_lock_sha256 = _text(profile, "candidateLockSha256")
    if (
        not _SHA256.fullmatch(candidate_lock_sha256)
        or hashlib.sha256(candidate_lock_bytes).hexdigest()
        != candidate_lock_sha256
    ):
        raise ValueError("agent candidate lock bytes differ")
    lock = _json_object(candidate_lock_bytes, "agent candidate lock")
    if lock.get("schemaVersion") != 3:
        raise ValueError("agent candidate lock schema differs")
    candidate = _one_candidate(lock, _text(profile, "candidateId"))
    runtime_id = _text(profile, "runtimeId")
    runtimes = lock.get("runtimes")
    runtime = runtimes.get(runtime_id) if isinstance(runtimes, dict) else None
    if not isinstance(runtime, dict):
        raise ValueError("agent service runtime is absent from its lock")

    service = _text(profile, "service")
    endpoint = _text(profile, "endpoint")
    host, endpoint_port = parse_numeric_loopback_http_endpoint(
        endpoint,
        component="agent service profile",
    )
    if host != "127.0.0.1" or endpoint != f"http://{host}:{endpoint_port}":
        raise ValueError("agent service endpoint differs")
    container_name = _text(profile, "containerName")
    if not _CONTAINER_NAME.fullmatch(container_name):
        raise ValueError("agent service container name is invalid")
    if not _NAME.fullmatch(profile_id) or service != profile_id:
        raise ValueError("agent service profile identity differs")

    expected_model = _text(profile, "expectedModel")
    model_revision = _text(profile, "modelRevision")
    artifact_sha256 = _text(profile, "modelArtifactManifestSha256")
    if (
        candidate.get("workloadClass") != service
        or candidate.get("runtimeId") != runtime_id
        or candidate.get("model") != expected_model
        or candidate.get("revision") != model_revision
        or candidate.get("artifactManifestSha256") != artifact_sha256
        or not _GIT_SHA.fullmatch(model_revision)
        or not _SHA256.fullmatch(artifact_sha256)
        or candidate.get("toolCallParser") != profile.get("toolCallParser")
        or candidate.get("finalResponseProtocol")
        != profile.get("finalResponseProtocol")
    ):
        raise ValueError("agent service profile differs from its candidate")

    image = runtime.get("image")
    image_id = runtime.get("observedImageId")
    if (
        runtime.get("engine") != "vllm"
        or runtime.get("platform") != "linux/arm64"
        or not isinstance(image, str)
        or not image
        or not isinstance(image_id, str)
        or not _IMAGE_SHA256.fullmatch(image_id)
    ):
        raise ValueError("agent service runtime differs from its lock")

    container_port = _integer(profile, "containerPort", minimum=1024, maximum=65535)
    maximum_model_length = _integer(
        profile,
        "maximumModelLength",
        minimum=1,
        maximum=65_536,
    )
    maximum_sequences = _integer(
        profile,
        "maximumSequences",
        minimum=1,
        maximum=64,
    )
    maximum_batched_tokens = _integer(
        profile,
        "maximumBatchedTokens",
        minimum=1,
        maximum=65_536,
    )
    gpu_memory_utilization = _text(profile, "gpuMemoryUtilization")
    load_format = _text(profile, "loadFormat")
    resources = _resources(profile.get("resources"))

    validate_qualified_agent_vllm_route_policy(
        profile,
        candidate,
        maximum_model_length=maximum_model_length,
        maximum_sequences=maximum_sequences,
        maximum_batched_tokens=maximum_batched_tokens,
        gpu_memory_utilization=gpu_memory_utilization,
        load_format=load_format,
        memory_bytes=resources.memory_bytes,
        memory_swap_bytes=resources.memory_swap_bytes,
        cpu_count=resources.cpu_count,
        pids_limit=resources.pids_limit,
        shm_bytes=resources.shm_bytes,
        tmpfs_bytes=resources.tmpfs_bytes,
    )
    launch_arguments = build_qualified_agent_vllm_launch_arguments(
        candidate,
        model_path=f"/model-cache/snapshots/{model_revision}",
        host="0.0.0.0",
        port=container_port,
    )
    loaded = AgentVllmServiceProfile(
        profile_sha256=expected_profile_sha256,
        profile_id=profile_id,
        service=service,
        endpoint=endpoint,
        container_name=container_name,
        candidate_lock_sha256=candidate_lock_sha256,
        candidate_id=_text(profile, "candidateId"),
        runtime_id=runtime_id,
        expected_model=expected_model,
        model_revision=model_revision,
        model_artifact_manifest_sha256=artifact_sha256,
        image=image,
        image_id=image_id,
        container_port=container_port,
        maximum_sequences=maximum_sequences,
        resources=resources,
        launch_arguments=launch_arguments,
    )
    loaded.validate_identity()
    return loaded


def _resources(value: object) -> AgentContainerResources:
    if not isinstance(value, dict) or set(value) != _RESOURCE_KEYS:
        raise ValueError("agent service resource policy differs")
    return AgentContainerResources(
        memory_bytes=_integer(value, "memoryBytes", minimum=1),
        memory_swap_bytes=_integer(value, "memorySwapBytes", minimum=1),
        cpu_count=_integer(value, "cpuCount", minimum=1, maximum=64),
        pids_limit=_integer(value, "pidsLimit", minimum=1, maximum=16_384),
        shm_bytes=_integer(value, "shmBytes", minimum=1),
        tmpfs_bytes=_integer(value, "tmpfsBytes", minimum=1),
    )


def _one_candidate(lock: dict[str, object], candidate_id: str) -> dict[str, object]:
    candidates = lock.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError("agent candidate lock is invalid")
    matches = [
        value
        for value in candidates
        if isinstance(value, dict) and value.get("candidateId") == candidate_id
    ]
    if len(matches) != 1:
        raise ValueError("agent service candidate is absent from its lock")
    return matches[0]


def _read_regular_bytes(path: Path, component: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{component} must be a regular file")
    payload = path.read_bytes()
    if not payload or len(payload) > _MAX_DOCUMENT_BYTES:
        raise ValueError(f"{component} size is invalid")
    return payload


def _json_object(payload: bytes, component: str) -> dict[str, object]:
    try:
        value = json.loads(payload, object_pairs_hook=_unique_json_object)
    except (UnicodeDecodeError, json.JSONDecodeError, _DuplicateJsonKeyError) as error:
        raise ValueError(f"{component} is invalid") from error
    if not isinstance(value, dict):
        raise ValueError(f"{component} is invalid")
    return value


class _DuplicateJsonKeyError(ValueError):
    pass


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKeyError(key)
        result[key] = value
    return result


def _text(value: dict[str, object], field: str) -> str:
    result = value.get(field)
    if (
        not isinstance(result, str)
        or not result
        or len(result) > 512
        or result.strip() != result
        or any(ord(character) < 32 or ord(character) == 127 for character in result)
    ):
        raise ValueError(f"agent service {field} is invalid")
    return result


def _integer(
    value: dict[str, object],
    field: str,
    *,
    minimum: int,
    maximum: int | None = None,
) -> int:
    result = value.get(field)
    if (
        isinstance(result, bool)
        or not isinstance(result, int)
        or result < minimum
        or (maximum is not None and result > maximum)
    ):
        raise ValueError(f"agent service {field} is invalid")
    return result


__all__ = [
    "AgentContainerResources",
    "AgentVllmServiceProfile",
    "load_agent_vllm_service_profile",
]
