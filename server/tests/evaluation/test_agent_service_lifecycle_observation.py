from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from yap_server.evaluation.agent_service_lifecycle_observation import (
    read_service_state,
    validate_container_policy,
    validate_state_identity,
)
from yap_server.pools.agent_vllm_service_profile import (
    AgentVllmServiceProfile,
    load_agent_vllm_service_profile,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CANDIDATE_LOCK = REPOSITORY_ROOT / "server" / "agent-reasoning-candidates.lock.json"
PROFILE_PATH = (
    REPOSITORY_ROOT
    / "server"
    / "agent-service-profiles"
    / "rapid-automation.json"
)
CHECKED_HEAD = "a" * 40
OWNER_TOKEN = "b" * 64
NETWORK_NAME = "yap-agent-lifecycle-test"


class AgentServiceLifecycleObservationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.profile = load_agent_vllm_service_profile(
            PROFILE_PATH,
            CANDIDATE_LOCK,
            expected_profile_sha256=hashlib.sha256(PROFILE_PATH.read_bytes()).hexdigest(),
        )

    def test_container_policy_requires_exact_identity_resources_and_attachment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            model_root = Path(temporary) / "models--nvidia--Qwen"
            snapshot = model_root / "snapshots" / self.profile.model_revision
            snapshot.mkdir(parents=True)
            inspection = _inspection(self.profile, snapshot)
            with (
                patch.object(os, "getuid", create=True, return_value=1000),
                patch.object(os, "getgid", create=True, return_value=1000),
            ):
                validate_container_policy(
                    inspection,
                    profile=self.profile,
                    checked_head=CHECKED_HEAD,
                    owner_token=OWNER_TOKEN,
                    network_name=NETWORK_NAME,
                    model_snapshot=snapshot,
                )
                for mutation in (
                    "id",
                    "memory",
                    "network",
                    "mount",
                    "snapshot-mount",
                    "gpu",
                ):
                    with self.subTest(mutation=mutation):
                        changed = copy.deepcopy(inspection)
                        if mutation == "id":
                            changed["Id"] = "not-a-container"
                        elif mutation == "memory":
                            changed["HostConfig"]["Memory"] = 1
                        elif mutation == "network":
                            changed["NetworkSettings"]["Networks"]["unexpected"] = {}
                        elif mutation == "snapshot-mount":
                            changed["Mounts"][0]["Source"] = str(snapshot)
                        elif mutation == "gpu":
                            changed["HostConfig"]["DeviceRequests"][0][
                                "DeviceIDs"
                            ] = ["nvidia.com/gpu=0"]
                        else:
                            changed["Mounts"][0]["RW"] = True
                        with self.assertRaises((RuntimeError, ValueError)):
                            validate_container_policy(
                                changed,
                                profile=self.profile,
                                checked_head=CHECKED_HEAD,
                                owner_token=OWNER_TOKEN,
                                network_name=NETWORK_NAME,
                                model_snapshot=snapshot,
                            )

    def test_state_identity_is_exact_and_counters_reject_boolean_values(self) -> None:
        state = _state(self.profile)
        validate_state_identity(state, self.profile)
        mutations = (
            {**state, "unexpected": True},
            {**state, "profileSha256": "c" * 64},
            {**state, "restartCount": True},
        )
        for mutation in mutations:
            with self.subTest(mutation=json.dumps(mutation, sort_keys=True)):
                with self.assertRaises(ValueError):
                    validate_state_identity(mutation, self.profile)

    def test_state_reader_rejects_duplicate_json_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state_path = Path(temporary) / "state.json"
            state_path.write_text(
                '{"schemaVersion":2,"schemaVersion":1}\n',
                encoding="utf-8",
            )
            if os.name == "posix":
                state_path.chmod(0o600)

            with self.assertRaisesRegex(ValueError, "state is invalid"):
                read_service_state(state_path)


def _inspection(
    profile: AgentVllmServiceProfile,
    snapshot: Path,
) -> dict[str, object]:
    return {
        "Id": "d" * 64,
        "Name": f"/{profile.container_name}",
        "Image": profile.image_id,
        "Config": {
            "Cmd": list(profile.launch_arguments),
            "User": "1000:1000",
            "StopTimeout": 10,
            "Env": [
                "HF_HUB_OFFLINE=1",
                "TRANSFORMERS_OFFLINE=1",
                "HF_HUB_DISABLE_TELEMETRY=1",
                "DO_NOT_TRACK=1",
                "HOME=/tmp",
            ],
            "Labels": {
                "io.yap.owner": "private-inference",
                "io.yap.revision": CHECKED_HEAD,
                "io.yap.run-token": OWNER_TOKEN,
                "io.yap.agent-profile": profile.profile_id,
                "io.yap.model": profile.expected_model,
                "io.yap.model-revision": profile.model_revision,
                "io.yap.model-artifact-sha256": (
                    profile.model_artifact_manifest_sha256
                ),
            },
        },
        "HostConfig": {
            "NetworkMode": NETWORK_NAME,
            "IpcMode": "host",
            "ReadonlyRootfs": True,
            "Privileged": False,
            "AutoRemove": False,
            "PublishAllPorts": False,
            "PortBindings": None,
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges"],
            "Memory": profile.resources.memory_bytes,
            "MemorySwap": profile.resources.memory_swap_bytes,
            "NanoCpus": profile.resources.cpu_count * 1_000_000_000,
            "PidsLimit": profile.resources.pids_limit,
            "ShmSize": profile.resources.shm_bytes,
            "Ulimits": [
                {"Name": "memlock", "Soft": -1, "Hard": -1},
                {
                    "Name": "stack",
                    "Soft": 67_108_864,
                    "Hard": 67_108_864,
                },
            ],
            "DeviceRequests": [
                {
                    "Driver": "cdi",
                    "Count": 0,
                    "DeviceIDs": ["nvidia.com/gpu=all"],
                    "Capabilities": None,
                    "Options": None,
                }
            ],
            "Tmpfs": {
                "/tmp": (
                    "rw,nosuid,nodev,exec,"
                    f"size={profile.resources.tmpfs_bytes},mode=1777"
                )
            },
            "LogConfig": {
                "Type": "local",
                "Config": {"max-file": "3", "max-size": "10m"},
            },
        },
        "State": {"Running": True, "Pid": 1234},
        "NetworkSettings": {"Networks": {NETWORK_NAME: {}}},
        "Mounts": [
            {
                "Type": "bind",
                "Source": str(snapshot.parent.parent.resolve(strict=True)),
                "Destination": "/model-cache",
                "RW": False,
            }
        ],
    }


def _state(profile: AgentVllmServiceProfile) -> dict[str, object]:
    return {
        "schemaVersion": 2,
        "service": profile.service,
        "profileId": profile.profile_id,
        "profileSha256": profile.profile_sha256,
        "candidateLockSha256": profile.candidate_lock_sha256,
        "state": "ready",
        "processGeneration": 2,
        "startCount": 2,
        "restartCount": 1,
        "consecutiveFailureCount": 0,
        "readinessTransitionCount": 2,
    }


if __name__ == "__main__":
    unittest.main()
