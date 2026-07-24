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
PROCESS_GROUP_HELPER = (
    REPOSITORY_ROOT
    / "infra"
    / "yap-server-node"
    / "owned-process-group.sh"
)
LAUNCHERS = (
    REPOSITORY_ROOT / "infra" / "yap-server-node" / "cohere-vllm-server.sh",
    REPOSITORY_ROOT / "infra" / "yap-server-node" / "nemotron-nemo-server.sh",
)


class PrivateContainerLoopbackProxyContractTests(unittest.TestCase):
    def test_proxy_is_loopback_only_and_cleans_its_complete_process_group(self) -> None:
        helper = PROXY_HELPER.read_text(encoding="utf-8")
        ownership_helper = PROCESS_GROUP_HELPER.read_text(encoding="utf-8")

        for required in (
            "for program in docker env socat setsid ss ps; do",
            'command -v "$program"',
            "YAP_RUNTIME_OWNER_TOKEN=\"$_yap_owner_token\"",
            "exec setsid socat",
            'if [ "$(cat -- "$1")" != "$$" ]; then',
            'printf "%s\\n" "$_yap_proxy_pid" '
            '>"$_yap_proxy_group_file.part"',
            'mv -- "$_yap_proxy_group_file.part" '
            '"$_yap_proxy_group_file"',
            '"$_yap_proxy_group_file"',
            (
                "TCP4-LISTEN:${host_port},bind=127.0.0.1,reuseaddr,fork,"
                "backlog=32,max-children=32"
            ),
            'TCP4:${container_ip}:${container_port}',
            'kill -KILL "$_yap_log_pid"',
            'docker wait "$_yap_container_id"',
            'docker logs --follow "$_yap_container_id"',
            'docker stop --time 10 "$_yap_container_id"',
            "io.yap.run-token",
            ')" = "$_yap_owner_token" ]',
            "run_private_container_with_loopback_proxy() {",
            '_yap_container_id="$("$@")"',
            ')" != "/$container_name"',
            'network_mode" != "$network_name"',
            "private loopback proxy listener remained after teardown",
            "stop_owned_child_process_group",
        ):
            self.assertIn(required, helper)
        for required in (
            'kill -TERM -- "-$group"',
            'kill -KILL -- "-$group"',
            "YAP_RUNTIME_OWNER_TOKEN=$owner_token",
            "process group remained after bounded teardown",
        ):
            self.assertIn(required, ownership_helper)
        self.assertNotIn('docker stop --time 10 "$container_name"', helper)
        self.assertNotIn('docker wait "$container_name"', helper)
        self.assertNotIn("0.0.0.0", helper)
        self.assertNotIn("--network host", helper)
        self.assertNotIn("nohup", helper)
        self.assertLess(
            helper.index('if [ "$(cat -- "$1")" != "$$" ]; then'),
            helper.index("exec setsid socat"),
        )
        self.assertLess(
            helper.index('_yap_proxy_pid="$!"'),
            helper.index(
                'printf "%s\\n" "$_yap_proxy_pid" '
                '>"$_yap_proxy_group_file.part"'
            ),
        )

    def test_provider_launchers_use_the_shared_proxy_instead_of_port_publish(
        self,
    ) -> None:
        for launcher_path in LAUNCHERS:
            with self.subTest(launcher=launcher_path.name):
                launcher = launcher_path.read_text(encoding="utf-8")
                self.assertIn("private-container-loopback-proxy.sh", launcher)
                self.assertIn("run_private_container_with_loopback_proxy", launcher)
                self.assertIn("YAP_PROXY_PROCESS_GROUP_FILE:?", launcher)
                self.assertIn("docker run", launcher)
                self.assertIn("--detach", launcher)
                self.assertNotIn("--publish", launcher)
                self.assertNotIn("-p 127.0.0.1", launcher)


if __name__ == "__main__":
    unittest.main()
