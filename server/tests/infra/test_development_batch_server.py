import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SERVER_LAUNCH = (
    REPO_ROOT / "infra" / "yap-server-node" / "development-batch-server.sh"
)


class DevelopmentBatchServerContractTests(unittest.TestCase):
    def test_launch_is_clean_head_foreground_and_loopback_only(self) -> None:
        script = SERVER_LAUNCH.read_text(encoding="utf-8")

        self.assertIn('git -C "$repo_root" rev-parse --is-inside-work-tree', script)
        self.assertIn('git -C "$repo_root" rev-parse HEAD', script)
        self.assertIn("status --porcelain=v1 --untracked-files=normal", script)
        self.assertIn("python3.12 -m yap_server", script)
        self.assertIn("exec env", script)
        self.assertIn("YAP_SERVER_HOST=127.0.0.1", script)
        self.assertIn("YAP_SERVER_PORT=18765", script)
        self.assertIn("YAP_BATCH_ASR_ENABLED=1", script)
        self.assertIn('YAP_CHECKED_HEAD="$YAP_CHECKED_HEAD"', script)
        self.assertIn("YAP_COHERE_ASR_RUNTIME=vllm", script)
        self.assertIn(
            'YAP_COHERE_VLLM_ENDPOINT="$YAP_COHERE_VLLM_ENDPOINT"',
            script,
        )
        self.assertIn(
            'YAP_COHERE_VLLM_API_KEY="$YAP_COHERE_VLLM_API_KEY"',
            script,
        )
        self.assertIn(
            'YAP_NEMOTRON_ASR_RUNTIME="$YAP_NEMOTRON_ASR_RUNTIME"',
            script,
        )
        self.assertIn(
            'YAP_NEMOTRON_NEMO_ENDPOINT="$YAP_NEMOTRON_NEMO_ENDPOINT"',
            script,
        )
        self.assertIn(
            'YAP_NEMOTRON_NEMO_API_KEY="$YAP_NEMOTRON_NEMO_API_KEY"',
            script,
        )
        self.assertIn('YAP_ASR_MODEL_LOCK="$YAP_ASR_MODEL_LOCK"', script)
        self.assertIn(
            'YAP_ASR_CAPABILITY_LOCK="$YAP_ASR_CAPABILITY_LOCK"',
            script,
        )
        self.assertIn('YAP_ASR_MODEL_DIR="$YAP_ASR_MODEL_DIR"', script)
        self.assertIn(
            'YAP_BATCH_JOB_STORAGE_DIR="$YAP_BATCH_JOB_STORAGE_DIR"', script
        )
        self.assertIn('storage_mode="$(stat -Lc \'%a\'', script)
        self.assertIn('if [ "$storage_mode" != "700" ]', script)
        for forbidden in (
            "0.0.0.0",
            "localhost",
            "nohup",
            "systemctl",
            "ufw ",
            "--publish",
        ):
            self.assertNotIn(forbidden, script)

    def test_launch_requires_the_checked_head_and_private_vllm_inputs(self) -> None:
        script = SERVER_LAUNCH.read_text(encoding="utf-8")

        for required in (
            "YAP_CHECKED_HEAD:?",
            "YAP_ASR_MODEL_DIR:?",
            "YAP_BATCH_JOB_STORAGE_DIR:?",
            "YAP_COHERE_VLLM_API_KEY:?",
        ):
            self.assertIn(required, script)
        self.assertIn(
            "server/cohere-vllm-serving.lock.json",
            script,
        )
        self.assertIn("server/nemotron-nemo-serving.lock.json", script)
        self.assertIn("nemo-resident", script)
        self.assertIn("http://127.0.0.1:18001", script)
        self.assertIn(
            "resident Nemotron requires an explicit candidate capability lock",
            script,
        )
        self.assertIn(
            "candidate capability locks must remain outside the repository",
            script,
        )
        self.assertNotIn("nvcr.io/nvidia/pytorch", script)
        self.assertNotIn("YAP_ASR_WORKER_IMAGE:?", script)


if __name__ == "__main__":
    unittest.main()
