from __future__ import annotations

from pathlib import Path
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
LAUNCHER = REPOSITORY_ROOT / "infra" / "yap-server-node" / "agent-vllm-server.sh"


class AgentVllmServerContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.script = LAUNCHER.read_text(encoding="utf-8")

    def test_launcher_consumes_only_a_hashed_profile_and_private_runtime_inputs(
        self,
    ) -> None:
        for expected in (
            "--profile",
            "--profile-sha256",
            "--candidate-lock",
            "YAP_AGENT_MODEL_SNAPSHOT:?",
            "YAP_CHECKED_HEAD:?",
            "YAP_PRIVATE_INFERENCE_NETWORK:?",
            "YAP_RUNTIME_OWNER_TOKEN:?",
            "YAP_PROXY_PROCESS_GROUP_FILE:?",
            "yap_server.pools.agent_vllm_service_profile_cli",
            "--emit-null",
            "--model-snapshot",
            "PYTHONPATH=\"$script_dir/python\"",
            "owned and immutable",
            "canonical portable path",
            "^/[A-Za-z0-9_./:-]+$",
            "realpath -e",
            "must not contain symbolic-link ancestry",
        ):
            self.assertIn(expected, self.script)
        self.assertNotIn("automatic-fallback", self.script)
        self.assertNotIn("localhost", self.script)
        self.assertNotIn("Ollama", self.script)

    def test_launcher_reuses_the_single_container_proxy_owner_with_exact_bounds(
        self,
    ) -> None:
        for expected in (
            "private-container-loopback-proxy.sh",
            "run_private_container_with_loopback_proxy",
            "docker container create",
            "docker image inspect",
            'image_id" != "$profile_image_id"',
            'image_os" != "linux"',
            'image_architecture" != "arm64"',
            '--name "$profile_container_name"',
            "--ipc=host",
            "--ulimit memlock=-1",
            "--ulimit stack=67108864",
            '--memory "$profile_memory_bytes"',
            '--memory-swap "$profile_memory_swap_bytes"',
            '--cpus "$profile_cpu_count"',
            '--pids-limit "$profile_pids_limit"',
            '--shm-size "$profile_shm_bytes"',
            "nvidia.com/gpu=all",
            "--read-only",
            "--cap-drop ALL",
            "no-new-privileges",
            "HF_HUB_OFFLINE=1",
            "TRANSFORMERS_OFFLINE=1",
            "HOME=/tmp",
            "dst=/model-cache,readonly",
        ):
            self.assertIn(expected, self.script)
        self.assertNotIn("--publish", self.script)
        self.assertNotIn("--network host", self.script)
        self.assertNotIn("nohup", self.script)

    def test_launcher_loads_process_ownership_before_the_proxy_that_uses_it(
        self,
    ) -> None:
        process_group_source = 'source "$script_dir/owned-process-group.sh"'
        proxy_source = 'source "$script_dir/private-container-loopback-proxy.sh"'
        self.assertIn(process_group_source, self.script)
        self.assertIn(proxy_source, self.script)
        self.assertLess(
            self.script.index(process_group_source),
            self.script.index(proxy_source),
        )

    def test_launcher_keeps_provider_credentials_out_of_arguments_and_files(self) -> None:
        for forbidden in (
            "--api-key",
            "VLLM_API_KEY",
            "echo $YAP",
            "> .env",
        ):
            self.assertNotIn(forbidden, self.script)


if __name__ == "__main__":
    unittest.main()
