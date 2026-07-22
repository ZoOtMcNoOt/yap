from __future__ import annotations

from pathlib import Path
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PROXY_HELPER = (
    REPOSITORY_ROOT
    / "infra"
    / "yap-server-node"
    / "private-container-loopback-proxy.sh"
)
LAUNCHERS = (
    REPOSITORY_ROOT / "infra" / "yap-server-node" / "cohere-vllm-server.sh",
    REPOSITORY_ROOT / "infra" / "yap-server-node" / "nemotron-nemo-server.sh",
)


class PrivateContainerLoopbackProxyContractTests(unittest.TestCase):
    def test_proxy_is_loopback_only_and_cleans_its_complete_process_group(self) -> None:
        helper = PROXY_HELPER.read_text(encoding="utf-8")

        for required in (
            "for program in docker env socat setsid ss ps; do",
            'command -v "$program"',
            "env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin setsid socat",
            (
                "TCP4-LISTEN:${host_port},bind=127.0.0.1,reuseaddr,fork,"
                "backlog=32,max-children=32"
            ),
            'TCP4:${container_ip}:${container_port}',
            'kill -TERM -- "-$proxy_pid"',
            'kill -KILL -- "-$proxy_pid"',
            'kill -KILL "$log_pid"',
            'docker wait "$container_name"',
            'docker logs --follow "$container_name"',
            'docker stop --time 10 "$container_name"',
            'network_mode" != "$network_name"',
            "private loopback proxy listener remained after teardown",
        ):
            self.assertIn(required, helper)
        self.assertNotIn("0.0.0.0", helper)
        self.assertNotIn("--network host", helper)
        self.assertNotIn("nohup", helper)

    def test_provider_launchers_use_the_shared_proxy_instead_of_port_publish(
        self,
    ) -> None:
        for launcher_path in LAUNCHERS:
            with self.subTest(launcher=launcher_path.name):
                launcher = launcher_path.read_text(encoding="utf-8")
                self.assertIn("private-container-loopback-proxy.sh", launcher)
                self.assertIn("run_private_container_with_loopback_proxy", launcher)
                self.assertIn("docker run", launcher)
                self.assertIn("--detach", launcher)
                self.assertNotIn("--publish", launcher)
                self.assertNotIn("-p 127.0.0.1", launcher)


if __name__ == "__main__":
    unittest.main()
