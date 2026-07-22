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
            "org.opencontainers.image.revision",
            'architecture" != "arm64"',
            'run_as_uid="$(id -u)"',
            'run_as_gid="$(id -g)"',
            '--user "$run_as_uid:$run_as_gid"',
            "must run as a non-root model owner",
            "127.0.0.1:${YAP_NEMOTRON_NEMO_PORT}:8000",
            "--env YAP_NEMOTRON_NEMO_API_KEY",
            "export YAP_NEMOTRON_NEMO_API_KEY",
            "--pull never",
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

    def test_api_key_is_only_inherited_through_process_environment(self) -> None:
        script = SERVER_LAUNCH.read_text(encoding="utf-8")

        self.assertNotIn("--api-key", script)
        self.assertNotIn('--env "YAP_NEMOTRON_NEMO_API_KEY=', script)
        self.assertNotIn("echo $YAP_NEMOTRON_NEMO_API_KEY", script)
        self.assertNotIn("> .env", script)


if __name__ == "__main__":
    unittest.main()
