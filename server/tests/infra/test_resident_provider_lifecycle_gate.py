from __future__ import annotations

from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
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
PROCESS_GROUP_HELPER = (
    REPOSITORY_ROOT / "infra" / "yap-server-node" / "owned-process-group.sh"
)
OWNER_TOKEN = "d" * 64
FOREIGN_TOKEN = "e" * 64


class ResidentProviderLifecycleGateContractTests(unittest.TestCase):
    def test_control_empty_recovery_stops_owned_group_and_removes_records(
        self,
    ) -> None:
        bash = _linux_bash_or_skip(self, "recovery replay")

        function = _shell_function(
            GATE.read_text(encoding="utf-8"),
            "stop_owned_runtime_process",
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state_file = _bash_path(root / "resident.state")
            result_file = _bash_path(root / "resident.result")
            harness = f"""
set -euo pipefail
source {shlex.quote(_bash_path(PROCESS_GROUP_HELPER))}
{function}
runtime_owner_token={OWNER_TOKEN}
state_file={shlex.quote(state_file)}
result_file={shlex.quote(result_file)}
setsid env YAP_RUNTIME_OWNER_TOKEN="$runtime_owner_token" \
  bash -c 'sleep 60 & wait' &
child_pid="$!"
owned_group="$child_pid"
start_ticks="$(awk '{{print $22}}' "/proc/$child_pid/stat")"
(exit 1) &
reap_pid="$!"
control_fd=
printf '1 ready %s %s %s 0\\n' \
  "$child_pid" "$start_ticks" "$reap_pid" >"$state_file"
printf '1 1 143 ownership-failed\\n' >"$result_file"
set +e
stop_owned_runtime_process \
  child_pid reap_pid control_fd state_file result_file \
  "Resident recovery replay"
recovery_status="$?"
set -e
test "$recovery_status" -eq 1
test -z "$child_pid"
test -z "$reap_pid"
test -z "$control_fd"
test -z "$state_file"
test -z "$result_file"
test -z "$(yap_process_group_members "$owned_group")"
wait "$owned_group" 2>/dev/null || true
test ! -e {shlex.quote(state_file)}
test ! -e {shlex.quote(result_file)}
"""
            self._run_bash_harness(bash, harness, timeout=30)

    def test_control_empty_recovery_refuses_foreign_token_and_retains_records(
        self,
    ) -> None:
        bash = _linux_bash_or_skip(self, "refusal replay")

        function = _shell_function(
            GATE.read_text(encoding="utf-8"),
            "stop_owned_runtime_process",
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state_file = _bash_path(root / "resident.state")
            result_file = _bash_path(root / "resident.result")
            harness = f"""
set -euo pipefail
source {shlex.quote(_bash_path(PROCESS_GROUP_HELPER))}
{function}
runtime_owner_token={OWNER_TOKEN}
state_file={shlex.quote(state_file)}
result_file={shlex.quote(result_file)}
setsid env YAP_RUNTIME_OWNER_TOKEN={FOREIGN_TOKEN} bash -c 'sleep 60 & wait' &
child_pid="$!"
owned_group="$child_pid"
start_ticks="$(awk '{{print $22}}' "/proc/$child_pid/stat")"
(exit 1) &
reap_pid="$!"
recorded_reap_pid="$reap_pid"
control_fd=
printf '1 ready %s %s %s 0\\n' \
  "$child_pid" "$start_ticks" "$reap_pid" >"$state_file"
printf '1 1 143 ownership-failed\\n' >"$result_file"
set +e
stop_owned_runtime_process \
  child_pid reap_pid control_fd state_file result_file \
  "Resident foreign-token replay"
recovery_status="$?"
set -e
test "$recovery_status" -eq 1
test "$child_pid" = "$owned_group"
test "$reap_pid" = "$recorded_reap_pid"
test -z "$control_fd"
test "$state_file" = {shlex.quote(state_file)}
test "$result_file" = {shlex.quote(result_file)}
test -e "$state_file"
test -e "$result_file"
test -n "$(yap_process_group_members "$owned_group")"
stop_token_owned_process_group \
  "$owned_group" {FOREIGN_TOKEN} "Foreign-token test teardown"
wait "$owned_group" 2>/dev/null || true
rm -f -- "$state_file" "$result_file"
"""
            self._run_bash_harness(bash, harness, timeout=30)

    def test_sampler_handles_clear_only_after_executable_cleanup_proof(self) -> None:
        bash = shutil.which("bash")
        if bash is None:
            self.skipTest("bash is unavailable for the sampler lifecycle replay")

        function = _shell_function(
            GATE.read_text(encoding="utf-8"),
            "finalize_resource_sampler_lifecycle",
        )
        harness = f"""
set -euo pipefail
{function}
sampler_pid=101
sampler_reap_pid=102
sampler_control_fd=10
sampler_state_file=/tmp/sampler-state
sampler_result_file=/tmp/sampler-result
yap_wait_owned_process_group() {{ return 1; }}
yap_stop_owned_process_group() {{ exit 91; }}
sampler_status=0
set +e
finalize_resource_sampler_lifecycle sampler_status
cleanup_status="$?"
set -e
test "$cleanup_status" -eq 1
test "$sampler_status" -eq 1
test "$sampler_pid" = 101
test "$sampler_reap_pid" = 102
test "$sampler_control_fd" = 10
test "$sampler_state_file" = /tmp/sampler-state
test "$sampler_result_file" = /tmp/sampler-result

yap_wait_owned_process_group() {{ return 124; }}
yap_stop_owned_process_group() {{ return 0; }}
sampler_status=0
finalize_resource_sampler_lifecycle sampler_status
test "$sampler_status" -eq 1
test -z "$sampler_pid"
test -z "$sampler_reap_pid"
test -z "$sampler_control_fd"
test -z "$sampler_state_file"
test -z "$sampler_result_file"
"""
        self._run_bash_harness(bash, harness, timeout=10)

    def test_unknown_container_creation_retains_gate_recovery_identity(self) -> None:
        bash = _linux_bash_or_skip(self, "container recovery replay")

        function = _shell_function(
            GATE.read_text(encoding="utf-8"),
            "stop_owned_runtime",
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            proxy_group_file = _bash_path(root / "proxy.pgid")
            recovery_file = f"{proxy_group_file}.container-recovery"
            harness = f"""
set -euo pipefail
{function}
runtime_owner_token={OWNER_TOKEN}
proxy_group_file={shlex.quote(proxy_group_file)}
active_container_id=
active_container_name=yap-test-provider
observed_container_running=
network_id=
sampler_pid=
sampler_reap_pid=
sampler_control_fd=
sampler_state_file=
sampler_result_file=
launcher_pid=
launcher_reap_pid=
launcher_control_fd=
launcher_state_file=
launcher_result_file=
printf '%s\\n' \
  "1 create-pending yap-test-provider {OWNER_TOKEN} -" \
  >{shlex.quote(recovery_file)}
stop_owned_runtime_process() {{ return 0; }}
stop_recorded_proxy_group() {{ proxy_group_file=; return 0; }}
capture_owned_provider_container() {{ return 1; }}
capture_owned_network() {{ return 1; }}
if stop_owned_runtime; then
  cleanup_status=0
else
  cleanup_status="$?"
fi
test "$cleanup_status" -eq 1
test -e {shlex.quote(recovery_file)}
test "$active_container_name" = yap-test-provider
"""
            self._run_bash_harness(bash, harness, timeout=10)

    def test_normal_provider_stop_requires_all_recovery_artifacts_absent(
        self,
    ) -> None:
        bash = _linux_bash_or_skip(self, "recovery-retirement replay")

        script = GATE.read_text(encoding="utf-8")
        absence_function = _shell_function(
            script,
            "require_private_container_recovery_absence",
        )
        stop_function = _shell_function(script, "stop_provider")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            group_file_prefix = _bash_path(root / "proxy")
            harness = f"""
set -euo pipefail
{absence_function}
{stop_function}
capture_owned_provider_container() {{ return 0; }}
docker() {{ return 0; }}
stop_recorded_proxy_group() {{ proxy_group_file=; return 0; }}
wait_for_owned_container_absence() {{ exit 91; }}
ss() {{ return 1; }}
for suffix in .container-recovery .container-recovery.part .container-id; do
  expected_group_file={shlex.quote(group_file_prefix)}"$suffix"
  proxy_group_file="$expected_group_file"
  active_container_id=owned-container
  active_container_name=yap-test-provider
  observed_container_running=true
  launcher_pid=
  launcher_reap_pid=
  launcher_control_fd=
  launcher_state_file=
  launcher_result_file=
  : >"$expected_group_file$suffix"
  if stop_provider 18000; then
    stop_status=0
  else
    stop_status="$?"
  fi
  test "$stop_status" -eq 1
  test "$proxy_group_file" = "$expected_group_file"
  test -e "$expected_group_file$suffix"
  command rm -f -- "$expected_group_file$suffix"
done
"""
            self._run_bash_harness(bash, harness, timeout=10)

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
            "Resident providers require distinct loopback ports",
            "runtime_owner_token",
            "io.yap.run-token",
            "active_container_id",
            "network_id",
            "wait_for_owned_container",
            "owned-process-group.sh",
            "yap_start_owned_process_group",
            "yap_wait_owned_process_group",
            "yap_stop_owned_process_group",
            "launcher_control_fd",
            "launcher_reap_pid",
            "launcher_state_file",
            "launcher_result_file",
            "sampler_control_fd",
            "sampler_reap_pid",
            "finalize_resource_sampler_lifecycle",
            "cleanup_proven=false",
            'if [ "$cleanup_proven" != true ]; then',
            "yap_stop_or_recover_owned_process_group",
            "stop_recorded_proxy_group",
            "container-recovery",
            "container creation outcome remains unresolved",
            'docker rm --force "$active_container_id"',
            "YAP_PROXY_PROCESS_GROUP_FILE",
            'YAP_RUNTIME_OWNER_TOKEN="$runtime_owner_token"',
            'docker port "$container"',
            '("1.1.1.1", 443)',
            'launcher_status="$supervisor_wait_status"',
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
            assignment = script.index(f'active_container_name="{container_name}"')
            launch = script.index("yap_start_owned_process_group \\", assignment)
            self.assertLess(assignment, launch)
        self.assertEqual(script.count("yap_start_owned_process_group \\"), 3)
        self.assertNotIn("stop_owned_child_process_group", script)
        self.assertNotIn("\n  setsid \\\n", script)
        proven_cleanup = script.index('if [ "$cleanup_proven" != true ]; then')
        cleared_sampler = script.index('sampler_pid=""', proven_cleanup)
        finalizer_call = script.rindex(
            "finalize_resource_sampler_lifecycle sampler_status"
        )
        failed_workload = script.index(
            'if [ "$workload_status" -ne 0 ]',
            finalizer_call,
        )
        self.assertLess(proven_cleanup, cleared_sampler)
        self.assertLess(finalizer_call, failed_workload)

    def test_uses_a_temporary_internal_network_and_never_mutates_host_policy(
        self,
    ) -> None:
        script = GATE.read_text(encoding="utf-8")

        self.assertIn("docker network create", script)
        self.assertIn("--internal", script)
        self.assertIn("io.yap.owner=private-inference", script)
        self.assertIn("io.yap.revision=$YAP_CHECKED_HEAD", script)
        self.assertIn("io.yap.run-token=$runtime_owner_token", script)
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
        function_end = script.index("\nverify_private_container_network() {")
        function = script[function_start:function_end]
        container_id = "a" * 64
        owner_token = "b" * 64
        harness = f"""
set -euo pipefail
runtime_owner_token={owner_token}
launcher_pid=424242
launcher_result_file="$(mktemp)"
trap 'rm -f "$launcher_result_file"' EXIT
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

    def _run_bash_harness(
        self,
        bash: str,
        harness: str,
        *,
        timeout: int,
    ) -> None:
        try:
            completed = subprocess.run(
                [bash],
                input=harness.encode("utf-8"),
                check=False,
                capture_output=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as error:
            output = (error.stdout or b"") + (error.stderr or b"")
            self.fail(output.decode("utf-8", errors="replace"))
        self.assertEqual(
            completed.returncode,
            0,
            (completed.stdout + completed.stderr).decode(
                "utf-8",
                errors="replace",
            ),
        )


def _linux_bash_or_skip(test: unittest.TestCase, purpose: str) -> str:
    """Resolve a Linux bash, or skip.

    These replays drive Linux process groups and address the temporary
    directory through _bash_path, which emits a /mnt/<drive> path. A Windows
    host resolves bash but cannot reach that path, so the Linux check is what
    makes the skip honest rather than a failure.
    """
    bash = shutil.which("bash")
    if bash is None:
        test.skipTest(f"bash is unavailable for the {purpose}")
    if subprocess.run(
        [bash, "-lc", 'test "$(uname -s)" = Linux'],
        check=False,
        capture_output=True,
        timeout=5,
    ).returncode != 0:
        test.skipTest(f"Linux process groups are unavailable for the {purpose}")
    return bash


def _shell_function(script: str, name: str) -> str:
    start = script.index(f"{name}() {{")
    end = script.index("\n}\n", start) + len("\n}\n")
    return script[start:end]


def _bash_path(path: Path) -> str:
    resolved = path.resolve()
    if resolved.drive:
        drive = resolved.drive.rstrip(":").lower()
        remainder = resolved.as_posix().split(":", maxsplit=1)[1]
        return f"/mnt/{drive}{remainder}"
    return resolved.as_posix()


if __name__ == "__main__":
    unittest.main()
