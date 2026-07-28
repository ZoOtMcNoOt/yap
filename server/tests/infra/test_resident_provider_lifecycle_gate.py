from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
IMAGE_CONTRACT = (
    REPOSITORY_ROOT
    / "server"
    / "src"
    / "yap_server"
    / "pools"
    / "checked_runtime_image.py"
)
GATE = (
    REPOSITORY_ROOT
    / "infra"
    / "yap-server-node"
    / "resident-provider-lifecycle-gate.sh"
)
PLAN = REPOSITORY_ROOT / "server" / "asr-evaluation-plan.json"


class ResidentProviderLifecycleGateContractTests(unittest.TestCase):
    def test_appends_standard_system_command_fallbacks_after_caller_path(
        self,
    ) -> None:
        bash = shutil.which("bash")
        if bash is None:
            self.skipTest("bash is unavailable for the command-path replay")
        script = GATE.read_text(encoding="utf-8")
        function_start = script.index("append_command_path_fallbacks() {")
        function_end = script.index("\n}\n", function_start) + len("\n}\n")
        function = script[function_start:function_end]
        production_call = (
            'append_command_path_fallbacks "/usr/local/sbin:/usr/local/bin:'
            '/usr/sbin:/usr/bin:/sbin:/bin"'
        )
        self.assertIn(production_call, script)
        self.assertLess(
            script.index(production_call), script.index("capture_host_boundary()")
        )
        harness = r"""
set -euo pipefail
caller_bin="$(mktemp -d)"
fallback_bin="$(mktemp -d)"
trap 'rm -rf "$caller_bin" "$fallback_bin"' EXIT
for command_name in python3.12 uv; do
  printf '#!/usr/bin/env bash\nexit 0\n' >"$caller_bin/$command_name"
  chmod 0700 "$caller_bin/$command_name"
done
for command_name in ufw nft iptables-save; do
  printf '#!/usr/bin/env bash\nexit 0\n' >"$fallback_bin/$command_name"
  chmod 0700 "$fallback_bin/$command_name"
done
PATH="$caller_bin:/usr/bin:/bin"
append_command_path_fallbacks "$fallback_bin"
test "$PATH" = "$caller_bin:/usr/bin:/bin:$fallback_bin"
test "$(command -v python3.12)" = "$caller_bin/python3.12"
test "$(command -v uv)" = "$caller_bin/uv"
test "$(command -v ufw)" = "$fallback_bin/ufw"
test "$(command -v nft)" = "$fallback_bin/nft"
test "$(command -v iptables-save)" = "$fallback_bin/iptables-save"
test "$(/bin/bash -c 'printf %s "$PATH"')" = "$PATH"
"""
        completed = subprocess.run(
            [bash],
            input=(function + harness).encode("utf-8"),
            check=False,
            capture_output=True,
            timeout=30,
        )
        self.assertEqual(
            completed.returncode,
            0,
            (completed.stdout + completed.stderr).decode(
                "utf-8",
                errors="replace",
            ),
        )

    def test_requires_prepared_images_without_building_during_the_gate(self) -> None:
        contract = IMAGE_CONTRACT.read_text(encoding="utf-8")
        script = GATE.read_text(encoding="utf-8")

        for required in (
            "cohere-vllm",
            "nemotron-nemo",
            "language-detection",
            "reference-batch-asr",
            "runtime/cohere-vllm/Dockerfile",
            "runtime/nemotron-nemo/Dockerfile",
            '"docker", "image", "inspect"',
            "@sha256:",
            "--pull=false",
            "status --porcelain=v1 --untracked-files=normal",
            "Prepared checked runtime image is required",
            "runtime identity differs",
        ):
            self.assertIn(required, contract)

        self.assertNotIn("\n  --pull \\", script)
        self.assertNotIn("docker build", script)
        self.assertEqual(script.count("yap_server.pools.checked_runtime_image"), 2)
        self.assertIn('verify-prepared cohere-vllm "$YAP_CHECKED_HEAD"', script)
        self.assertIn('verify-prepared nemotron-nemo "$YAP_CHECKED_HEAD"', script)
        self.assertIn('vllm_image="$(', script)
        self.assertIn('nemo_image="$(', script)
        self.assertIn('>"$gate_root/logs/vllm-image-id.txt"', script)
        self.assertIn('>"$gate_root/logs/nemo-image-id.txt"', script)
        self.assertNotIn(
            'vllm_image="yap-cohere-vllm:checked-head-$YAP_CHECKED_HEAD"',
            script,
        )
        self.assertNotIn(
            'nemo_image="yap-nemotron-nemo:checked-head-$YAP_CHECKED_HEAD"',
            script,
        )
        self.assertIn("cohere-vllm", script)
        self.assertIn("nemotron-nemo", script)

    def test_runs_both_checked_providers_sequentially_and_finalizes_after_teardown(
        self,
    ) -> None:
        script = GATE.read_text(encoding="utf-8")
        plan = PLAN.read_text(encoding="utf-8")

        for required in (
            "YAP_CHECKED_HEAD:?",
            "YAP_EVAL_CACHE:?",
            "YAP_PROVIDER_DURATION_SUITE:?",
            "YAP_PROVIDER_DURATION_SUITE_SHA256:?",
            "YAP_COHERE_MODEL_DIR:?",
            "YAP_NEMOTRON_MODEL_DIR:?",
            "YAP_COHERE_VLLM_API_KEY:?",
            "YAP_NEMOTRON_NEMO_API_KEY:?",
            "YAP_COHERE_VLLM_PREPARATION_RECEIPT:?",
            "YAP_COHERE_VLLM_PREPARATION_RECEIPT_SHA256:?",
            "YAP_NEMOTRON_NEMO_PREPARATION_RECEIPT:?",
            "YAP_NEMOTRON_NEMO_PREPARATION_RECEIPT_SHA256:?",
            "status --porcelain=v1 --untracked-files=normal",
            "cohere-vllm-server.sh",
            "nemotron-nemo-server.sh",
            "resident_provider_readiness",
            "provider_runtime_qualification",
            "provider_cancellation_qualification",
            "provider_capacity_qualification",
            "provider_fixed_auto_contract_qualification",
            "resident_provider_duration_qualification",
            "resident_provider_resource_sampler",
            "provider_resource_observations",
            "resident_provider_lifecycle_evidence",
            "--vllm-image-id",
            "--nemo-image-id",
            "--vllm-preparation-receipt-sha256",
            "--nemo-preparation-receipt-sha256",
            "vllm-short-tail",
            "vllm-cancelled-sibling",
            "vllm-slot-capacity",
            "vllm-pcm-capacity",
            "nemo-finalized-short-tail",
            "nemo-finalized-fixed-auto-contract",
            "nemo-finalized-long-windows",
            "nemo-finalized-cancelled-sibling",
            "nemo-finalized-active-capacity",
            "server-finalized-utterance",
            "batch-file",
            '"--repeat-count" "$repeat_count"',
            '"--qualification-scope" "$qualification_scope"',
            '"--completed-request-count" "1600"',
            '"--concurrency" "8"',
            "workload-start",
            "workload-end",
            "workload-window.json",
            "request-lifecycle",
            "resource-lifecycle",
            "125000 - observation_elapsed_ms",
            "capture_host_boundary",
            "verify_private_container_network",
            "runtime-processes.txt",
            "[d]ocker logs --follow (yap-cohere-vllm|yap-nemotron-nemo)",
            "Resident providers require distinct loopback ports",
            "runtime_owner_token",
            "io.yap.run-token",
            "active_container_id",
            "network_id",
            "wait_for_owned_container",
            "verify_launcher_process_group",
            "setsid \\",
            "owned-process-group.sh",
            "stop_token_owned_process_group",
            "stop_recorded_proxy_group",
            "YAP_PROXY_PROCESS_GROUP_FILE",
            'yap_process_group_members "$launcher_pid"',
            'ps -o pgid= -p "$process_id"',
            "stop_owned_child_process_group",
            'YAP_RUNTIME_OWNER_TOKEN="$runtime_owner_token"',
            'docker port "$container"',
            '("1.1.1.1", 443)',
            'launcher_status="$?"',
            "Resident provider launcher reported unclean teardown",
            "--verify-only",
        ):
            self.assertIn(required, script)

        for promotion_only in ("vllm-long-waves", "vllm-mixed-eight"):
            self.assertNotIn(promotion_only, script)
            self.assertIn(f'"id": "{promotion_only}"', plan)

        self.assertLess(
            script.rindex("\nrun_vllm_qualification\n"),
            script.rindex('stop_provider "$YAP_COHERE_VLLM_PORT"'),
        )
        self.assertLess(
            script.rindex('stop_provider "$YAP_COHERE_VLLM_PORT"'),
            script.rindex("\nrun_nemo_qualification\n"),
        )
        self.assertLess(
            script.index('stop_provider "$YAP_NEMOTRON_NEMO_PORT"'),
            script.index('capture_host_boundary "$gate_root/after"'),
        )
        self.assertLess(
            script.index('capture_host_boundary "$gate_root/after"'),
            script.index("resident_provider_lifecycle_evidence"),
        )
        self.assertIn(
            '"$catalog_language" "$provider_language" 8 resource-lifecycle 8',
            script,
        )
        for container_name in ("yap-cohere-vllm", "yap-nemotron-nemo"):
            assignment = script.index(
                f'active_container_name="{container_name}"'
            )
            launch = script.index("setsid \\", assignment)
            self.assertLess(assignment, launch)

    def test_uses_a_temporary_internal_network_and_never_mutates_host_policy(self) -> None:
        script = GATE.read_text(encoding="utf-8")

        self.assertIn("docker network create", script)
        self.assertIn("--internal", script)
        self.assertIn("io.yap.owner=private-inference", script)
        self.assertIn('io.yap.revision=$YAP_CHECKED_HEAD', script)
        self.assertIn('io.yap.run-token=$runtime_owner_token', script)
        self.assertIn('docker network rm "$network_id"', script)
        self.assertIn(
            'if docker network rm "$network_id" >/dev/null 2>&1; then',
            script,
        )
        self.assertIn("Resident provider owned network cleanup failed", script)
        self.assertNotIn('docker network rm "$network_name"', script)
        self.assertIn("docker network rm", script)
        self.assertIn("networks.txt", script)
        self.assertNotIn("--network host", script)
        self.assertNotIn("nohup", script)
        for mutation in (
            "ufw allow",
            "ufw delete",
            "ufw enable",
            "systemctl enable",
            "systemctl start",
            "systemctl restart",
        ):
            self.assertNotIn(mutation, script.lower())

    def test_dead_launcher_still_publishes_the_owned_container_id_for_cleanup(
        self,
    ) -> None:
        bash = shutil.which("bash")
        if bash is None:
            self.skipTest("bash is unavailable for the dead-launcher replay")
        script = GATE.read_text(encoding="utf-8")
        function_start = script.index("capture_owned_provider_container() {")
        function_end = script.index("\nverify_owned_process_group() {")
        function = script[function_start:function_end]
        container_id = "a" * 64
        owner_token = "b" * 64
        harness = f"""
set -euo pipefail
runtime_owner_token={owner_token}
launcher_pid=424242
active_container_id=
active_container_name=yap-test-provider
observed_container_running=
docker() {{
  printf '%s\\n' '{container_id}|{owner_token}|/yap-test-provider|false'
}}
kill() {{ return 1; }}
set +e
wait_for_owned_container yap-test-provider
status="$?"
set -e
test "$status" -eq 1
test "$active_container_id" = "{container_id}"
"""
        completed = subprocess.run(
            [bash],
            input=(function + harness).encode("utf-8"),
            check=False,
            capture_output=True,
            timeout=30,
        )
        self.assertEqual(
            completed.returncode,
            0,
            (completed.stdout + completed.stderr).decode(
                "utf-8",
                errors="replace",
            ),
        )

    def test_network_identity_is_recovered_if_create_output_is_lost(self) -> None:
        bash = shutil.which("bash")
        if bash is None:
            self.skipTest("bash is unavailable for the network recovery replay")
        script = GATE.read_text(encoding="utf-8")
        function_start = script.index("capture_owned_network() {")
        function_end = script.index("\nverify_network_absent() {")
        function = script[function_start:function_end]
        network_id = "c" * 64
        owner_token = "d" * 64
        checked_head = "e" * 40
        harness = f"""
set -euo pipefail
runtime_owner_token={owner_token}
YAP_CHECKED_HEAD={checked_head}
network_name=yap-private-inference-recovery
network_id=
docker() {{
  printf '%s\\n' \
    '{network_id}|{owner_token}|{checked_head}|yap-private-inference-recovery'
}}
capture_owned_network
test "$network_id" = "{network_id}"
"""
        completed = subprocess.run(
            [bash],
            input=(function + harness).encode("utf-8"),
            check=False,
            capture_output=True,
            timeout=30,
        )
        self.assertEqual(
            completed.returncode,
            0,
            (completed.stdout + completed.stderr).decode(
                "utf-8",
                errors="replace",
            ),
        )

    def test_docker_29_network_not_found_is_treated_as_absent(self) -> None:
        bash = shutil.which("bash")
        if bash is None:
            self.skipTest("bash is unavailable for the network absence replay")
        script = GATE.read_text(encoding="utf-8")
        function_start = script.index("docker_network_absence_response() {")
        function_end = script.index("\nwait_for_owned_container() {")
        functions = script[function_start:function_end]
        network_id = "c" * 64
        network_name = "yap-private-inference-absence"
        harness = f"""
set -euo pipefail
network_name={network_name}
docker() {{
  local requested="${{@: -1}}"
  if [[ " $* " == *" --format "* ]]; then
    printf '\\n'
  else
    printf '[]\\n'
  fi
  printf '%s\\n' \
    "Error response from daemon: network $requested not found" >&2
  return 1
}}
set +e
capture_owned_network
capture_status="$?"
set -e
test "$capture_status" -eq 1
verify_network_absent {network_id}
docker() {{
  local requested="${{@: -1}}"
  printf '%s\\n' \
    "permission denied while plugin reported network $requested not found" >&2
  return 1
}}
set +e
capture_owned_network
capture_status="$?"
verify_network_absent {network_id}
verify_status="$?"
set -e
test "$capture_status" -eq 2
test "$verify_status" -eq 2
"""
        completed = subprocess.run(
            [bash],
            input=(functions + harness).encode("utf-8"),
            check=False,
            capture_output=True,
            timeout=30,
        )
        self.assertEqual(
            completed.returncode,
            0,
            (completed.stdout + completed.stderr).decode(
                "utf-8",
                errors="replace",
            ),
        )

    def test_captured_container_identity_cannot_be_replaced(self) -> None:
        bash = shutil.which("bash")
        if bash is None:
            self.skipTest("bash is unavailable for the replacement replay")
        script = GATE.read_text(encoding="utf-8")
        function_start = script.index("capture_owned_provider_container() {")
        function_end = script.index("\nverify_owned_container_absent() {")
        function = script[function_start:function_end]
        original_id = "a" * 64
        replacement_id = "b" * 64
        owner_token = "c" * 64
        harness = f"""
set -euo pipefail
runtime_owner_token={owner_token}
active_container_name=yap-test-provider
active_container_id={original_id}
observed_container_running=true
docker() {{
  printf '%s\\n' \
    '{replacement_id}|{owner_token}|/yap-test-provider|true'
}}
set +e
capture_owned_provider_container
status="$?"
set -e
test "$status" -eq 2
test "$active_container_id" = "{original_id}"
"""
        completed = subprocess.run(
            [bash],
            input=(function + harness).encode("utf-8"),
            check=False,
            capture_output=True,
            timeout=30,
        )
        self.assertEqual(
            completed.returncode,
            0,
            (completed.stdout + completed.stderr).decode(
                "utf-8",
                errors="replace",
            ),
        )


if __name__ == "__main__":
    unittest.main()
