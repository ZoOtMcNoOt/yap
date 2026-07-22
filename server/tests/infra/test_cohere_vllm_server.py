import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SERVER_LAUNCH = REPO_ROOT / "infra" / "yap-server-node" / "cohere-vllm-server.sh"


class CohereVllmServerContractTests(unittest.TestCase):
    def test_launches_the_checked_image_on_a_loopback_only_host_port(self) -> None:
        script = SERVER_LAUNCH.read_text(encoding="utf-8")

        self.assertIn("YAP_CHECKED_HEAD:?", script)
        self.assertIn("YAP_COHERE_VLLM_IMAGE:?", script)
        self.assertIn("YAP_COHERE_MODEL_DIR:?", script)
        self.assertIn("YAP_COHERE_VLLM_API_KEY:?", script)
        self.assertIn("YAP_PRIVATE_INFERENCE_NETWORK:?", script)
        self.assertIn("org.opencontainers.image.revision", script)
        self.assertIn('architecture" != "arm64"', script)
        self.assertIn('run_as_uid="$(id -u)"', script)
        self.assertIn('run_as_gid="$(id -g)"', script)
        self.assertIn('--user "$run_as_uid:$run_as_gid"', script)
        self.assertIn("must run as a non-root model owner", script)
        self.assertIn("private-container-loopback-proxy.sh", script)
        self.assertIn("run_private_container_with_loopback_proxy", script)
        self.assertIn('"$YAP_COHERE_VLLM_PORT"', script)
        self.assertIn("--env VLLM_API_KEY", script)
        self.assertIn('VLLM_API_KEY="$YAP_COHERE_VLLM_API_KEY"', script)
        self.assertIn("export VLLM_API_KEY", script)
        self.assertIn("--pull", script)
        self.assertIn("never", script)
        self.assertIn('--network "$YAP_PRIVATE_INFERENCE_NETWORK"', script)
        self.assertIn("docker network inspect", script)
        self.assertIn('network_internal" != "true"', script)
        self.assertIn("io.yap.owner", script)
        self.assertIn("io.yap.revision", script)
        self.assertIn("--read-only", script)
        self.assertIn("--cap-drop", script)
        self.assertIn("ALL", script)
        self.assertIn("no-new-privileges", script)
        self.assertIn("--memory 32g", script)
        self.assertIn("--memory-swap 32g", script)
        self.assertIn("--cpus 16", script)
        self.assertIn("--log-driver local", script)
        self.assertIn("--log-opt max-size=10m", script)
        self.assertIn("nvidia.com/gpu=all", script)
        self.assertIn(
            "type=bind,src=$YAP_COHERE_MODEL_DIR,dst=/models/asr,readonly", script
        )
        self.assertNotIn("nohup", script)
        self.assertNotIn("0.0.0.0:", script)
        self.assertNotIn("--publish", script)

    def test_never_places_the_private_api_key_in_an_argument_or_file(self) -> None:
        script = SERVER_LAUNCH.read_text(encoding="utf-8")

        self.assertNotIn("--api-key", script)
        self.assertNotIn('--env "VLLM_API_KEY=', script)
        self.assertNotIn("echo $YAP_COHERE_VLLM_API_KEY", script)
        self.assertNotIn("> .env", script)
        self.assertNotIn("YAP_COHERE_VLLM_API_KEY >", script)


if __name__ == "__main__":
    unittest.main()
