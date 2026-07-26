from __future__ import annotations

from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[3]
SERVER_LAUNCH = (
    REPO_ROOT / "infra" / "yap-server-node" / "nemotron-nemo-server.sh"
)


class NemotronNemoServerContractTests(unittest.TestCase):
    def test_launches_one_checked_nonroot_runtime_on_loopback(self) -> None:
        script = SERVER_LAUNCH.read_text(encoding="utf-8")

        for expected in (
            "YAP_CHECKED_HEAD:?",
            "YAP_NEMOTRON_NEMO_IMAGE:?",
            "YAP_NEMOTRON_MODEL_DIR:?",
            "YAP_BATCH_JOB_STORAGE_DIR:?",
            "YAP_NEMOTRON_NEMO_API_KEY:?",
            "YAP_PRIVATE_INFERENCE_NETWORK:?",
            "YAP_RUNTIME_OWNER_TOKEN:?",
            "YAP_PROXY_PROCESS_GROUP_FILE:?",
            "org.opencontainers.image.revision",
            "com.mcnatg1.yap.runtime",
            'runtime_identity" != "nemotron-nemo"',
            'architecture" != "arm64"',
            'run_as_uid="$(id -u)"',
            'run_as_gid="$(id -g)"',
            '--user "$run_as_uid:$run_as_gid"',
            "must run as a non-root model owner",
            "private-container-loopback-proxy.sh",
            "run_private_container_with_loopback_proxy",
            '"$YAP_NEMOTRON_NEMO_PORT"',
            '"$YAP_PROXY_PROCESS_GROUP_FILE"',
            "--env YAP_NEMOTRON_NEMO_API_KEY",
            "export YAP_NEMOTRON_NEMO_API_KEY",
            "--pull never",
            '--network "$YAP_PRIVATE_INFERENCE_NETWORK"',
            "--read-only",
            "--cap-drop ALL",
            "no-new-privileges",
            "--memory 96g",
            "--memory-swap 96g",
            "--cpus 16",
            "--log-driver local",
            "--log-opt max-size=10m",
            "nvidia.com/gpu=all",
            "-m yap_server.pools.nemotron_nemo_service",
        ):
            self.assertIn(expected, script)
        self.assertIn(
            "type=bind,src=$YAP_NEMOTRON_MODEL_DIR,dst=/models/asr,readonly",
            script,
        )
        self.assertIn(
            "type=bind,src=$YAP_BATCH_JOB_STORAGE_DIR,"
            "dst=$YAP_BATCH_JOB_STORAGE_DIR,readonly",
            script,
        )
        self.assertNotIn("nohup", script)
        self.assertNotIn("0.0.0.0:${YAP_NEMOTRON_NEMO_PORT}", script)
        self.assertNotIn("--publish", script)
        self.assertIn("docker network inspect", script)
        self.assertIn('network_internal" != "true"', script)
        self.assertIn("io.yap.owner", script)
        self.assertIn("io.yap.revision", script)
        self.assertIn("io.yap.run-token", script)
        self.assertIn('network_run_token" != "$YAP_RUNTIME_OWNER_TOKEN"', script)
        self.assertIn("YAP_RUNTIME_OWNER_TOKEN must be", script)

    def test_api_key_is_only_inherited_through_process_environment(self) -> None:
        script = SERVER_LAUNCH.read_text(encoding="utf-8")

        self.assertNotIn("--api-key", script)
        self.assertNotIn('--env "YAP_NEMOTRON_NEMO_API_KEY=', script)
        self.assertNotIn("echo $YAP_NEMOTRON_NEMO_API_KEY", script)
        self.assertNotIn("> .env", script)


if __name__ == "__main__":
    unittest.main()
