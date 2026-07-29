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
    REPOSITORY_ROOT / "infra" / "yap-server-node" / "owned-process-group.sh"
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
            "for program in docker env python3.12 socat ss ps timeout; do",
            'command -v "$program"',
            'YAP_RUNTIME_OWNER_TOKEN="$_yap_owner_token"',
            "yap_start_owned_process_group",
            "yap_stop_or_recover_owned_process_group",
            "_yap_proxy_control_fd",
            "_yap_proxy_reap_pid",
            "_yap_proxy_state_file",
            "_yap_proxy_result_file",
            '[ -e "$_yap_proxy_result_file" ]',
            'printf "%s\\n" "$_yap_proxy_pid" >"$_yap_proxy_group_file.part"',
            'mv -- "$_yap_proxy_group_file.part" "$_yap_proxy_group_file"',
            '"$_yap_proxy_group_file"',
            (
                "TCP4-LISTEN:${host_port},bind=127.0.0.1,reuseaddr,fork,"
                "backlog=32,max-children=32"
            ),
            "TCP4:${container_ip}:${container_port}",
            'docker wait "$_yap_container_id"',
            'docker logs "$_yap_container_id"',
            'docker stop --time 1 "$_yap_container_id"',
            'docker rm --force "$_yap_container_id"',
            "docker container create",
            'docker container start "$_yap_container_id"',
            '--cidfile "$_yap_container_id_file"',
            "container-recovery",
            "create-pending",
            "creation outcome remains unproven",
            "private_loopback_proxy_verify_owned_container_id",
            '"$_yap_container_id" \\\n      id',
            "docker container ls",
            "--no-trunc",
            "timeout --signal=KILL 1s",
            "timeout --signal=KILL 2s",
            "io.yap.run-token",
            'inspected_token" != "$_yap_owner_token"',
            "run_private_container_with_loopback_proxy() {",
            '_yap_container_id="$reported_container_id"',
            'inspected_name" != "/$_yap_container_name"',
            'network_mode" != "$network_name"',
            "private loopback proxy listener remained after teardown",
            'exit "$_yap_requested_exit"',
        ):
            self.assertIn(required, helper)
        for required in (
            "owned-process-supervisor.py",
            "yap_start_owned_process_group",
            "yap_wait_owned_process_group",
            "yap_stop_owned_process_group",
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
        self.assertNotIn("exec setsid socat", helper)
        self.assertNotIn("stop_owned_child_process_group", helper)
        self.assertNotIn('kill -0 "$_yap_proxy_pid"', helper)
        self.assertNotIn("_yap_log_pid", helper)
        self.assertNotIn("docker logs --follow", helper)
        self.assertLess(
            helper.index("yap_start_owned_process_group"),
            helper.index(
                'printf "%s\\n" "$_yap_proxy_pid" >"$_yap_proxy_group_file.part"'
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
                self.assertIn("docker container create", launcher)
                self.assertNotIn("docker run", launcher)
                self.assertNotIn("--detach", launcher)
                self.assertNotIn("--publish", launcher)
                self.assertNotIn("-p 127.0.0.1", launcher)


if __name__ == "__main__":
    unittest.main()
