#!/usr/bin/env bash
set -euo pipefail

# Non-interactive SSH callers can omit system directories such as /usr/sbin.
# Preserve their runtime-command precedence, then add standard fallbacks.
append_command_path_fallbacks() {
  local fallback_path="$1"
  PATH="${PATH:+$PATH:}$fallback_path"
  export PATH
}
append_command_path_fallbacks "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/../.." && pwd)"
# shellcheck source=owned-process-group.sh
source "$script_dir/owned-process-group.sh"

: "${YAP_CHECKED_HEAD:?Set YAP_CHECKED_HEAD to the exact 40-character candidate SHA}"
: "${YAP_EVAL_CACHE:?Set YAP_EVAL_CACHE to the private mode-0700 evaluation cache}"
: "${YAP_PROVIDER_DURATION_SUITE:?Set the private provider duration suite path}"
: "${YAP_PROVIDER_DURATION_SUITE_SHA256:?Set the out-of-band provider suite SHA-256}"
: "${YAP_COHERE_MODEL_DIR:?Set the verified Cohere model directory}"
: "${YAP_NEMOTRON_MODEL_DIR:?Set the verified Nemotron model directory}"
: "${YAP_COHERE_VLLM_API_KEY:?Set the private Cohere vLLM API key}"
: "${YAP_NEMOTRON_NEMO_API_KEY:?Set the private Nemotron NeMo API key}"
: "${YAP_COHERE_VLLM_PREPARATION_RECEIPT:?Set the private Cohere image preparation receipt}"
: "${YAP_COHERE_VLLM_PREPARATION_RECEIPT_SHA256:?Set its frozen SHA-256}"
: "${YAP_NEMOTRON_NEMO_PREPARATION_RECEIPT:?Set the private Nemotron image preparation receipt}"
: "${YAP_NEMOTRON_NEMO_PREPARATION_RECEIPT_SHA256:?Set its frozen SHA-256}"
: "${YAP_RESIDENT_PROVIDER_EVIDENCE_DIR:=$YAP_EVAL_CACHE/resident-provider-lifecycle/$YAP_CHECKED_HEAD}"
: "${YAP_PROVIDER_READY_TIMEOUT_SECONDS:=1800}"
: "${YAP_PROVIDER_TIMEOUT_SECONDS:=1800}"
: "${YAP_COHERE_VLLM_PORT:=18000}"
: "${YAP_NEMOTRON_NEMO_PORT:=18001}"

for provider_port in "$YAP_COHERE_VLLM_PORT" "$YAP_NEMOTRON_NEMO_PORT"; do
  if [[ ! "$provider_port" =~ ^[0-9]+$ ]] \
    || [ "$provider_port" -lt 1024 ] \
    || [ "$provider_port" -gt 65535 ]; then
    echo "Resident provider ports must be unprivileged TCP ports" >&2
    exit 2
  fi
done
if [ "$YAP_COHERE_VLLM_PORT" = "$YAP_NEMOTRON_NEMO_PORT" ]; then
  echo "Resident providers require distinct loopback ports" >&2
  exit 2
fi

plan_path="$repo_root/server/asr-evaluation-plan.json"
vllm_lock="$repo_root/server/cohere-vllm-serving.lock.json"
nemo_lock="$repo_root/server/nemotron-nemo-serving.lock.json"
network_name="yap-private-inference-${YAP_CHECKED_HEAD:0:12}"
vllm_endpoint="http://127.0.0.1:$YAP_COHERE_VLLM_PORT"
nemo_endpoint="http://127.0.0.1:$YAP_NEMOTRON_NEMO_PORT"
runtime_owner_token="$(
  python3.12 -c 'import secrets; print(secrets.token_hex(32))'
)"

active_container_id=""
active_container_name=""
observed_container_running=""
launcher_pid=""
launcher_reap_pid=""
launcher_control_fd=""
launcher_state_file=""
launcher_result_file=""
sampler_pid=""
sampler_reap_pid=""
sampler_control_fd=""
sampler_state_file=""
sampler_result_file=""
network_id=""
proxy_group_file=""

verify_clean_head() {
  local actual_head worktree_status inside_worktree
  if ! inside_worktree="$(
    git -C "$repo_root" rev-parse --is-inside-work-tree 2>/dev/null
  )" || [ "$inside_worktree" != "true" ]; then
    echo "Resident provider lifecycle gate requires a Git worktree" >&2
    return 1
  fi
  actual_head="$(git -C "$repo_root" rev-parse HEAD)"
  if [ "$actual_head" != "$YAP_CHECKED_HEAD" ]; then
    echo "checked head does not match the repository HEAD" >&2
    return 1
  fi
  worktree_status="$(
    git -C "$repo_root" status --porcelain=v1 --untracked-files=normal
  )"
  if [ -n "$worktree_status" ]; then
    echo "Resident provider lifecycle gate requires a clean checked head" >&2
    return 1
  fi
}

stop_recorded_proxy_group() {
  stop_recorded_token_owned_process_group \
    "$proxy_group_file" \
    "$runtime_owner_token" \
    "Resident provider proxy" \
    || return 1
  proxy_group_file=""
}

require_private_container_recovery_absence() {
  local group_file="$1"
  local artifact
  if [ -z "$group_file" ]; then
    echo "Resident provider container recovery path is unavailable" >&2
    return 1
  fi
  for artifact in \
    "$group_file.container-recovery" \
    "$group_file.container-recovery.part" \
    "$group_file.container-id"; do
    if [ -e "$artifact" ] || [ -L "$artifact" ]; then
      echo \
        "Resident provider container recovery artifact remained after teardown: $artifact" \
        >&2
      return 1
    fi
  done
}

stop_owned_runtime_process() {
  local child_pid_variable="$1"
  local reap_pid_variable="$2"
  local control_variable="$3"
  local state_file_variable="$4"
  local result_file_variable="$5"
  local description="$6"
  local stopped_process_status=125
  yap_stop_or_recover_owned_process_group \
    stopped_process_status \
    "$control_variable" \
    "$reap_pid_variable" \
    "$child_pid_variable" \
    "$state_file_variable" \
    "$result_file_variable" \
    "$runtime_owner_token" \
    "$description"
}

finalize_resource_sampler_lifecycle() {
  local sampler_status_variable="$1"
  if [[ ! "$sampler_status_variable" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
    echo "Resident provider sampler status variable is invalid" >&2
    return 2
  fi
  local -n output_sampler_status="$sampler_status_variable"
  local observed_sampler_status=125
  local wait_status=0
  local cleanup_proven=false
  output_sampler_status=1
  if yap_wait_owned_process_group \
    observed_sampler_status \
    sampler_control_fd \
    "$sampler_reap_pid" \
    "$sampler_pid" \
    "$sampler_state_file" \
    "$sampler_result_file" \
    30 \
      "Resident provider sampler"; then
    output_sampler_status="$observed_sampler_status"
    cleanup_proven=true
  else
    wait_status="$?"
    if [ "$wait_status" -eq 124 ] \
      && yap_stop_owned_process_group \
        observed_sampler_status \
        sampler_control_fd \
        "$sampler_reap_pid" \
        "$sampler_pid" \
        "$sampler_state_file" \
        "$sampler_result_file" \
        "Resident provider sampler"; then
      cleanup_proven=true
    fi
  fi
  if [ "$cleanup_proven" != true ]; then
    return 1
  fi
  sampler_pid=""
  sampler_reap_pid=""
  sampler_control_fd=""
  sampler_state_file=""
  sampler_result_file=""
}

stop_owned_runtime() {
  local cleanup_status=0
  local private_container_proxy_group_file="$proxy_group_file"
  local container_recovery_file=""
  local container_id_file=""
  if [ -n "$private_container_proxy_group_file" ]; then
    container_recovery_file="$private_container_proxy_group_file.container-recovery"
    container_id_file="$private_container_proxy_group_file.container-id"
  fi
  set +e
  stop_owned_runtime_process \
    sampler_pid \
    sampler_reap_pid \
    sampler_control_fd \
    sampler_state_file \
    sampler_result_file \
    "Resident provider sampler" \
    || cleanup_status=1
  stop_owned_runtime_process \
    launcher_pid \
    launcher_reap_pid \
    launcher_control_fd \
    launcher_state_file \
    launcher_result_file \
    "Resident provider launcher" \
    || cleanup_status=1
  stop_recorded_proxy_group || cleanup_status=1
  local recovery_status=0
  capture_owned_provider_container
  recovery_status="$?"
  if [ "$recovery_status" -eq 0 ]; then
    if ! docker rm --force "$active_container_id" >/dev/null 2>&1 \
      && ! verify_owned_container_absent "$active_container_id"; then
      cleanup_status=1
    elif ! wait_for_owned_container_absence "$active_container_id"; then
      cleanup_status=1
    elif [ -n "$container_recovery_file" ]; then
      rm -f -- \
        "$container_recovery_file" \
        "$container_recovery_file.part" \
        "$container_id_file"
    fi
  elif [ "$recovery_status" -ne 1 ]; then
    cleanup_status=1
  fi
  local unresolved_container_creation=false
  if [ -n "$private_container_proxy_group_file" ] \
    && ! require_private_container_recovery_absence \
      "$private_container_proxy_group_file"; then
    unresolved_container_creation=true
  fi
  if [ "$unresolved_container_creation" = true ]; then
    echo \
      "Resident provider container creation outcome remains unresolved; private recovery identity retained" \
      >&2
    cleanup_status=1
  else
    active_container_id=""
    active_container_name=""
    observed_container_running=""
  fi
  local network_recovery_status=0
  capture_owned_network
  network_recovery_status="$?"
  if [ "$network_recovery_status" -eq 0 ]; then
    if docker network rm "$network_id" >/dev/null 2>&1; then
      if verify_network_absent "$network_id"; then
        network_id=""
      else
        echo "Resident provider owned network absence could not be verified" >&2
        cleanup_status=1
      fi
    else
      echo "Resident provider owned network cleanup failed" >&2
      cleanup_status=1
    fi
  elif [ "$network_recovery_status" -ne 1 ]; then
    cleanup_status=1
  fi
  set -e
  return "$cleanup_status"
}

cleanup() {
  local status="$?"
  trap - EXIT
  if ! stop_owned_runtime && [ "$status" -eq 0 ]; then
    status=1
  fi
  exit "$status"
}
trap cleanup EXIT

capture_host_boundary() {
  local target="$1"
  install -d -m 0700 "$target"
  if ! command -v ss >/dev/null 2>&1; then
    echo "Resident provider lifecycle gate requires ss" >&2
    return 1
  fi
  ss -H -lntu | LC_ALL=C sort >"$target/listeners.txt"

  if command -v ufw >/dev/null 2>&1; then
    local firewall_probe="$target/.firewall-probe"
    if { sudo -n ufw status verbose; } >"$firewall_probe" 2>/dev/null; then
      {
        printf '%s\n' "tool=ufw-status"
        cat "$firewall_probe"
      } >"$target/firewall.txt"
    else
      rm -f -- "$firewall_probe"
      {
        printf '%s\n' "tool=ufw-config-metadata"
        stat -Lc '%n|%d|%i|%s|%Y|%Z|%a|%U|%G' \
          /etc/default/ufw \
          /etc/ufw/ufw.conf \
          /etc/ufw/user.rules \
          /etc/ufw/user6.rules
        systemctl show ufw --property=ActiveState,SubState,UnitFileState
      } >"$target/firewall.txt"
    fi
    rm -f -- "$firewall_probe"
  elif command -v nft >/dev/null 2>&1; then
    {
      printf '%s\n' "tool=nft"
      sudo -n nft --stateless list ruleset
    } >"$target/firewall.txt"
  elif command -v iptables-save >/dev/null 2>&1; then
    {
      printf '%s\n' "tool=iptables-save"
      sudo -n iptables-save
    } >"$target/firewall.txt"
  else
    echo "Resident provider lifecycle gate cannot observe the firewall" >&2
    return 1
  fi

  if command -v systemctl >/dev/null 2>&1; then
    systemctl list-unit-files --type=service --no-legend --no-pager \
      | awk '$1 ~ /^yap.*\.service$/ { print }' \
      | LC_ALL=C sort >"$target/services.txt"
  else
    printf '%s\n' "systemd-unavailable" >"$target/services.txt"
  fi

  {
    for name in yap-cohere-vllm yap-nemotron-nemo; do
      if docker container inspect "$name" >/dev/null 2>&1; then
        docker container inspect --format '{{.Name}}|{{.State.Status}}' "$name"
      fi
    done
  } | LC_ALL=C sort >"$target/containers.txt"
  {
    pgrep -af '[c]ohere-vllm-server\.sh|[n]emotron-nemo-server\.sh' || true
    for provider_port in "$YAP_COHERE_VLLM_PORT" "$YAP_NEMOTRON_NEMO_PORT"; do
      pgrep -af "[s]ocat.*TCP4-LISTEN:${provider_port}," || true
    done
  } | LC_ALL=C sort -u >"$target/runtime-processes.txt"
  if docker network inspect "$network_name" >/dev/null 2>&1; then
    docker network inspect --format '{{.Name}}|{{.Internal}}' "$network_name" \
      >"$target/networks.txt"
  else
    : >"$target/networks.txt"
  fi
}

capture_owned_provider_container() {
  local identity container_id observed_owner observed_name running
  if [ -z "$active_container_name" ]; then
    return 1
  fi
  if ! identity="$(
    docker container inspect \
      --format '{{.Id}}|{{index .Config.Labels "io.yap.run-token"}}|{{.Name}}|{{.State.Running}}' \
      "$active_container_name" 2>&1
  )"; then
    if grep -Eqi 'no such (container|object)' <<<"$identity"; then
      return 1
    fi
    echo "Resident provider container inventory failed" >&2
    return 2
  fi
  IFS='|' read -r container_id observed_owner observed_name running <<<"$identity"
  if [[ ! "$container_id" =~ ^[0-9a-f]{64}$ ]] \
    || [ "$observed_owner" != "$runtime_owner_token" ] \
    || [ "$observed_name" != "/$active_container_name" ] \
    || { [ "$running" != "true" ] && [ "$running" != "false" ]; } \
    || { [ -n "$active_container_id" ] \
      && [ "$active_container_id" != "$container_id" ]; }; then
    echo "Resident provider container ownership is invalid" >&2
    return 2
  fi
  active_container_id="$container_id"
  observed_container_running="$running"
}

verify_owned_container_absent() {
  local container_id="$1"
  local output
  if output="$(docker container inspect "$container_id" 2>&1)"; then
    return 1
  fi
  if grep -Eqi 'no such (container|object)' <<<"$output"; then
    return 0
  fi
  echo "Resident provider container absence check failed" >&2
  return 2
}

wait_for_owned_container_absence() {
  local container_id="$1"
  local absence_status
  local deadline=$((SECONDS + 60))
  while true; do
    absence_status=0
    verify_owned_container_absent "$container_id" || absence_status="$?"
    if [ "$absence_status" -eq 0 ]; then
      return 0
    fi
    if [ "$absence_status" -ne 1 ]; then
      return 1
    fi
    if [ "$SECONDS" -ge "$deadline" ]; then
      echo "Resident provider container remained after teardown" >&2
      return 1
    fi
    sleep 0.1
  done
}

docker_network_absence_response() {
  local requested_network="$1"
  local output="$2"
  local current_message="Error response from daemon: network $requested_network not found"
  local legacy_message="Error: No such network: $requested_network"
  local legacy_daemon_message=\
"Error response from daemon: No such network: $requested_network"

  [ "$output" = "$current_message" ] \
    || [ "$output" = $'\n'"$current_message" ] \
    || [ "$output" = "[]"$'\n'"$current_message" ] \
    || [ "$output" = "$legacy_message" ] \
    || [ "$output" = $'\n'"$legacy_message" ] \
    || [ "$output" = "[]"$'\n'"$legacy_message" ] \
    || [ "$output" = "$legacy_daemon_message" ] \
    || [ "$output" = $'\n'"$legacy_daemon_message" ] \
    || [ "$output" = "[]"$'\n'"$legacy_daemon_message" ]
}

capture_owned_network() {
  local identity observed_id observed_owner observed_revision observed_name
  if ! identity="$(
    docker network inspect \
      --format '{{.Id}}|{{index .Labels "io.yap.run-token"}}|{{index .Labels "io.yap.revision"}}|{{.Name}}' \
      "$network_name" 2>&1
  )"; then
    if docker_network_absence_response "$network_name" "$identity"; then
      return 1
    fi
    echo "Resident provider network inventory failed" >&2
    return 2
  fi
  IFS='|' read -r \
    observed_id observed_owner observed_revision observed_name \
    <<<"$identity"
  if [[ ! "$observed_id" =~ ^[0-9a-f]{64}$ ]] \
    || [ "$observed_owner" != "$runtime_owner_token" ] \
    || [ "$observed_revision" != "$YAP_CHECKED_HEAD" ] \
    || [ "$observed_name" != "$network_name" ] \
    || { [ -n "$network_id" ] && [ "$network_id" != "$observed_id" ]; }; then
    echo "Resident provider network ownership is invalid" >&2
    return 2
  fi
  network_id="$observed_id"
}

verify_network_absent() {
  local owned_network_id="$1"
  local output
  if output="$(docker network inspect "$owned_network_id" 2>&1)"; then
    return 1
  fi
  if docker_network_absence_response "$owned_network_id" "$output"; then
    return 0
  fi
  echo "Resident provider network absence check failed" >&2
  return 2
}

wait_for_owned_container() {
  local container="$1"
  local capture_status
  local deadline=$((SECONDS + 60))
  if [ "$container" != "$active_container_name" ]; then
    echo "Resident provider expected container identity changed" >&2
    return 1
  fi
  while [ "$SECONDS" -lt "$deadline" ]; do
    capture_status=0
    capture_owned_provider_container || capture_status="$?"
    if [ "$capture_status" -eq 0 ]; then
      if [ "$observed_container_running" = "true" ]; then
        return 0
      fi
    elif [ "$capture_status" -ne 1 ]; then
      return 1
    fi
    if [ -n "$launcher_result_file" ] && [ -e "$launcher_result_file" ]; then
      echo "Resident provider launcher exited before its container became ready" >&2
      return 1
    fi
    sleep 0.1
  done
  echo "Resident provider container did not start" >&2
  return 1
}

verify_private_container_network() {
  local container="$1"
  local network_mode
  network_mode="$(
    docker container inspect \
      --format '{{.HostConfig.NetworkMode}}' \
      "$container"
  )"
  if [ "$network_mode" != "$network_name" ]; then
    echo "Resident provider joined an unexpected Docker network" >&2
    return 1
  fi
  if [ -n "$(docker port "$container")" ]; then
    echo "Resident provider exposed a Docker-published port" >&2
    return 1
  fi
  if ! docker exec "$container" python3 -c '
import socket
import sys

probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
probe.settimeout(2.0)
try:
    result = probe.connect_ex(("1.1.1.1", 443))
finally:
    probe.close()
sys.exit(1 if result == 0 else 0)
'; then
    echo "Resident provider unexpectedly reached an external address" >&2
    return 1
  fi
}

wait_for_file() {
  local path="$1"
  local timeout_seconds="$2"
  local deadline=$((SECONDS + timeout_seconds))
  while [ "$SECONDS" -lt "$deadline" ]; do
    if [ -f "$path" ] && [ ! -L "$path" ]; then
      return 0
    fi
    if [ -n "$sampler_result_file" ] && [ -e "$sampler_result_file" ]; then
      echo "Resident provider resource sampler exited before readiness" >&2
      return 1
    fi
    sleep 0.1
  done
  echo "Resident provider resource sampler did not become ready" >&2
  return 1
}

stop_provider() {
  local port="$1"
  local container="$active_container_id"
  local provider_proxy_group_file="$proxy_group_file"
  local launcher_status=0 supervisor_wait_status=0
  local capture_status=0 wait_status=0
  capture_owned_provider_container || capture_status="$?"
  if [ "$capture_status" -ne 0 ] \
    || [ -z "$container" ] \
    || [ "$active_container_id" != "$container" ]; then
    echo "Resident provider container disappeared before explicit teardown" >&2
    return 1
  fi
  docker stop --time 10 "$container" >/dev/null
  if [ -n "$launcher_pid" ]; then
    if yap_wait_owned_process_group \
      supervisor_wait_status \
      launcher_control_fd \
      "$launcher_reap_pid" \
      "$launcher_pid" \
      "$launcher_state_file" \
      "$launcher_result_file" \
      60 \
      "Resident provider launcher"; then
      launcher_status="$supervisor_wait_status"
    else
      wait_status="$?"
      if [ "$wait_status" -ne 124 ]; then
        return 1
      fi
      if ! yap_stop_owned_process_group \
        supervisor_wait_status \
        launcher_control_fd \
        "$launcher_reap_pid" \
        "$launcher_pid" \
        "$launcher_state_file" \
        "$launcher_result_file" \
        "Resident provider launcher"; then
        return 1
      fi
      launcher_status=1
    fi
  fi
  if ! stop_recorded_proxy_group; then
    echo "Resident provider proxy remained after teardown" >&2
    return 1
  fi
  if ! require_private_container_recovery_absence \
    "$provider_proxy_group_file"; then
    proxy_group_file="$provider_proxy_group_file"
    return 1
  fi
  launcher_pid=""
  launcher_reap_pid=""
  launcher_control_fd=""
  launcher_state_file=""
  launcher_result_file=""
  wait_for_owned_container_absence "$container"
  active_container_id=""
  active_container_name=""
  observed_container_running=""
  if ss -H -ltn | awk -v port=":$port" '$4 ~ port "$" { found=1 } END { exit !found }'; then
    echo "Resident provider listener remained after teardown" >&2
    return 1
  fi
  if [ "$launcher_status" -ne 0 ]; then
    echo "Resident provider launcher reported unclean teardown" >&2
    return 1
  fi
}

move_child_evidence() {
  local source="$1"
  local destination="$2"
  if [ ! -f "$source" ] || [ -L "$source" ] || [ -e "$destination" ]; then
    echo "Resident provider child evidence publication is invalid" >&2
    return 1
  fi
  mv -- "$source" "$destination"
  chmod 0600 "$destination"
}

run_standard() {
  local provider="$1"
  local logical_name="$2"
  local load_case="$3"
  local model_lock="$4"
  local endpoint="$5"
  local catalog_language="$6"
  local provider_language="$7"
  local repeat_count="$8"
  local qualification_scope="$9"
  shift 9
  local output_root="$gate_root/workloads/$provider-$logical_name"
  local destination="$provider_evidence_root/$provider/$logical_name.json"
  local arguments=(
    "--plan" "$plan_path"
    "--checked-head" "$YAP_CHECKED_HEAD"
    "--repository-root" "$repo_root"
    "--load-case" "$load_case"
    "--model-lock" "$model_lock"
    "--duration-suite" "$YAP_PROVIDER_DURATION_SUITE"
    "--duration-suite-sha256" "$YAP_PROVIDER_DURATION_SUITE_SHA256"
    "--endpoint" "$endpoint"
    "--catalog-language" "$catalog_language"
    "--provider-language" "$provider_language"
    "--output-root" "$output_root"
    "--timeout-seconds-per-wave" "$YAP_PROVIDER_TIMEOUT_SECONDS"
    "--repeat-count" "$repeat_count"
    "--qualification-scope" "$qualification_scope"
  )
  local concurrency
  for concurrency in "$@"; do
    arguments+=("--concurrency" "$concurrency")
  done
  PYTHONPATH="$repo_root/server/src" \
    python3.12 -m yap_server.evaluation.provider_runtime_qualification \
      "${arguments[@]}" \
      >"$gate_root/logs/$provider-$logical_name.json"
  move_child_evidence "$output_root/evidence.json" "$destination"
}

run_cancellation() {
  local provider="$1" logical_name="$2" load_case="$3" model_lock="$4"
  local endpoint="$5" catalog_language="$6" provider_language="$7"
  local output_root="$gate_root/workloads/$provider-$logical_name"
  PYTHONPATH="$repo_root/server/src" \
    python3.12 -m yap_server.evaluation.provider_cancellation_qualification \
      --plan "$plan_path" \
      --checked-head "$YAP_CHECKED_HEAD" \
      --repository-root "$repo_root" \
      --load-case "$load_case" \
      --model-lock "$model_lock" \
      --duration-suite "$YAP_PROVIDER_DURATION_SUITE" \
      --duration-suite-sha256 "$YAP_PROVIDER_DURATION_SUITE_SHA256" \
      --endpoint "$endpoint" \
      --catalog-language "$catalog_language" \
      --provider-language "$provider_language" \
      --output-root "$output_root" \
      --timeout-seconds "$YAP_PROVIDER_TIMEOUT_SECONDS" \
      >"$gate_root/logs/$provider-$logical_name.json"
  move_child_evidence \
    "$output_root/evidence.json" \
    "$provider_evidence_root/$provider/$logical_name.json"
}

run_capacity() {
  local provider="$1" logical_name="$2" load_case="$3" model_lock="$4"
  local endpoint="$5" catalog_language="$6" provider_language="$7"
  local output_root="$gate_root/workloads/$provider-$logical_name"
  PYTHONPATH="$repo_root/server/src" \
    python3.12 -m yap_server.evaluation.provider_capacity_qualification \
      --plan "$plan_path" \
      --checked-head "$YAP_CHECKED_HEAD" \
      --repository-root "$repo_root" \
      --load-case "$load_case" \
      --model-lock "$model_lock" \
      --duration-suite "$YAP_PROVIDER_DURATION_SUITE" \
      --duration-suite-sha256 "$YAP_PROVIDER_DURATION_SUITE_SHA256" \
      --endpoint "$endpoint" \
      --catalog-language "$catalog_language" \
      --provider-language "$provider_language" \
      --output-root "$output_root" \
      --timeout-seconds "$YAP_PROVIDER_TIMEOUT_SECONDS" \
      >"$gate_root/logs/$provider-$logical_name.json"
  move_child_evidence \
    "$output_root/evidence.json" \
    "$provider_evidence_root/$provider/$logical_name.json"
}

run_duration_ladder() {
  local provider="$1" logical_name="$2" system_id="$3" ladder="$4"
  local model_lock="$5" endpoint="$6" catalog_language="$7"
  local provider_language="$8" include_maximum="$9"
  local output_root="$gate_root/workloads/$provider-$logical_name"
  local arguments=(
    "--plan" "$plan_path"
    "--checked-head" "$YAP_CHECKED_HEAD"
    "--repository-root" "$repo_root"
    "--system-id" "$system_id"
    "--duration-ladder" "$ladder"
    "--model-lock" "$model_lock"
    "--duration-suite" "$YAP_PROVIDER_DURATION_SUITE"
    "--duration-suite-sha256" "$YAP_PROVIDER_DURATION_SUITE_SHA256"
    "--endpoint" "$endpoint"
    "--catalog-language" "$catalog_language"
    "--provider-language" "$provider_language"
    "--output-root" "$output_root"
    "--timeout-seconds-per-duration" "$YAP_PROVIDER_TIMEOUT_SECONDS"
  )
  if [ "$include_maximum" = true ]; then
    arguments+=("--include-exact-maximum")
  fi
  PYTHONPATH="$repo_root/server/src" \
    python3.12 -m yap_server.evaluation.resident_provider_duration_qualification \
      "${arguments[@]}" \
      >"$gate_root/logs/$provider-$logical_name.json"
  move_child_evidence \
    "$output_root/evidence.json" \
    "$provider_evidence_root/$provider/$logical_name.json"
}

run_resource_profile() {
  local provider="$1" system_id="$2" container="$3" model_lock="$4"
  local endpoint="$5" catalog_language="$6" provider_language="$7"
  local load_case="$8"
  local raw_root="$gate_root/raw/$provider-resource"
  local control_root="$raw_root/control"
  local sample_path="$raw_root/samples.jsonl"
  install -d -m 0700 "$raw_root" "$control_root"
  sampler_state_file="$control_root/sampler-supervisor.state"
  sampler_result_file="$control_root/sampler-supervisor.result"
  yap_start_owned_process_group \
    sampler_control_fd \
    sampler_reap_pid \
    sampler_pid \
    "$sampler_state_file" \
    "$sampler_result_file" \
    "$raw_root/sampler.json" \
    - \
    "$runtime_owner_token" \
    "Resident provider sampler" \
    -- \
    env PYTHONPATH="$repo_root/server/src" \
      python3.12 -m yap_server.evaluation.resident_provider_resource_sampler \
      --container "$container" \
      --checked-head "$YAP_CHECKED_HEAD" \
      --output "$sample_path" \
      --control-directory "$control_root" \
      --interval-ms 250
  wait_for_file "$control_root/ready.json" 30
  local observation_start_ms observation_elapsed_ms observation_remaining_ms
  observation_start_ms="$((
    $(python3.12 -c 'import time; print(time.monotonic_ns() // 1_000_000)')
  ))"
  install -m 0600 /dev/null "$control_root/workload-start"
  local workload_status=0
  set +e
  run_standard \
    "$provider" resource-load "$load_case" "$model_lock" "$endpoint" \
    "$catalog_language" "$provider_language" 8 resource-lifecycle 8
  workload_status="$?"
  set -e
  if [ "$workload_status" -eq 0 ]; then
    observation_elapsed_ms=$((
      $(python3.12 -c 'import time; print(time.monotonic_ns() // 1_000_000)')
      - observation_start_ms
    ))
    observation_remaining_ms=$(( 125000 - observation_elapsed_ms ))
    if [ "$observation_remaining_ms" -gt 0 ]; then
      sleep "$(( (observation_remaining_ms + 999) / 1000 ))"
    fi
  fi
  install -m 0600 /dev/null "$control_root/workload-end"
  install -m 0600 /dev/null "$control_root/stop"
  local sampler_status=1
  finalize_resource_sampler_lifecycle sampler_status || sampler_status=1
  if [ "$workload_status" -ne 0 ] || [ "$sampler_status" -ne 0 ]; then
    echo "Resident provider resource workload or sampler failed" >&2
    return 1
  fi
  PYTHONPATH="$repo_root/server/src" \
    python3.12 -m yap_server.evaluation.provider_resource_observations \
      --samples "$sample_path" \
      --workload-window "$control_root/workload-window.json" \
      --checked-head "$YAP_CHECKED_HEAD" \
      --repository-root "$repo_root" \
      --provider-serving-lock "$model_lock" \
      --output "$provider_evidence_root/$provider/resources.json" \
      --plan "$plan_path" \
      --system-id "$system_id" \
      "--completed-request-count" "1600" \
      "--concurrency" "8" \
      >"$raw_root/resources.json"
}

run_readiness() {
  local provider="$1" system_id="$2" model_lock="$3" endpoint="$4"
  PYTHONPATH="$repo_root/server/src" \
    python3.12 -m yap_server.evaluation.resident_provider_readiness \
      --checked-head "$YAP_CHECKED_HEAD" \
      --repository-root "$repo_root" \
      --system-id "$system_id" \
      --model-lock "$model_lock" \
      --endpoint "$endpoint" \
      --timeout-seconds "$YAP_PROVIDER_READY_TIMEOUT_SECONDS" \
      --poll-seconds 1 \
      --output "$provider_evidence_root/$provider/readiness.json" \
      >"$gate_root/logs/$provider-readiness.json"
}

run_vllm_qualification() {
  run_duration_ladder \
    vllm duration-batch vllm-cohere-batch batch-file "$vllm_lock" \
    "$vllm_endpoint" en en true
  run_standard \
    vllm short-tail vllm-short-tail "$vllm_lock" "$vllm_endpoint" \
    en en 1 request-lifecycle 1 2 4
  run_cancellation \
    vllm cancellation vllm-cancelled-sibling "$vllm_lock" "$vllm_endpoint" en en
  run_capacity \
    vllm slot-capacity vllm-slot-capacity "$vllm_lock" "$vllm_endpoint" en en
  run_capacity \
    vllm pcm-capacity vllm-pcm-capacity "$vllm_lock" "$vllm_endpoint" en en
  run_resource_profile \
    vllm vllm-cohere-batch yap-cohere-vllm "$vllm_lock" "$vllm_endpoint" \
    en en vllm-short-tail
}

run_nemo_qualification() {
  run_duration_ladder \
    nemo duration-finalized nemo-nemotron-finalized server-finalized-utterance \
    "$nemo_lock" "$nemo_endpoint" en-US en-US false
  run_duration_ladder \
    nemo duration-batch nemo-nemotron-finalized batch-file "$nemo_lock" \
    "$nemo_endpoint" en-US en-US true
  run_standard \
    nemo short-tail nemo-finalized-short-tail "$nemo_lock" "$nemo_endpoint" \
    en-US en-US 1 request-lifecycle 1 2 4
  run_standard \
    nemo long-windows nemo-finalized-long-windows "$nemo_lock" "$nemo_endpoint" \
    en-US en-US 1 request-lifecycle 2
  local contract_root="$gate_root/workloads/nemo-language-contract"
  PYTHONPATH="$repo_root/server/src" \
    python3.12 -m yap_server.evaluation.provider_fixed_auto_contract_qualification \
      --plan "$plan_path" \
      --checked-head "$YAP_CHECKED_HEAD" \
      --repository-root "$repo_root" \
      --load-case nemo-finalized-fixed-auto-contract \
      --model-lock "$nemo_lock" \
      --duration-suite "$YAP_PROVIDER_DURATION_SUITE" \
      --duration-suite-sha256 "$YAP_PROVIDER_DURATION_SUITE_SHA256" \
      --endpoint "$nemo_endpoint" \
      --fixed-catalog-language en-US \
      --fixed-provider-language en-US \
      --automatic-catalog-language und \
      --output-root "$contract_root" \
      --timeout-seconds-per-wave "$YAP_PROVIDER_TIMEOUT_SECONDS" \
      >"$gate_root/logs/nemo-language-contract.json"
  move_child_evidence \
    "$contract_root/evidence.json" \
    "$provider_evidence_root/nemo/language-contract.json"
  run_cancellation \
    nemo cancellation nemo-finalized-cancelled-sibling "$nemo_lock" \
    "$nemo_endpoint" en-US en-US
  run_capacity \
    nemo active-capacity nemo-finalized-active-capacity "$nemo_lock" \
    "$nemo_endpoint" en-US en-US
  run_resource_profile \
    nemo nemo-nemotron-finalized yap-nemotron-nemo "$nemo_lock" "$nemo_endpoint" \
    en-US en-US nemo-finalized-short-tail
}

if [[ ! "$YAP_CHECKED_HEAD" =~ ^[0-9a-f]{40}$ ]]; then
  echo "YAP_CHECKED_HEAD must be a full lowercase Git SHA" >&2
  exit 2
fi
if [[ ! "$YAP_PROVIDER_DURATION_SUITE_SHA256" =~ ^[0-9a-f]{64}$ ]]; then
  echo "YAP_PROVIDER_DURATION_SUITE_SHA256 must be a lowercase SHA-256" >&2
  exit 2
fi
for value in "$YAP_PROVIDER_READY_TIMEOUT_SECONDS" "$YAP_PROVIDER_TIMEOUT_SECONDS"; do
  if [[ ! "$value" =~ ^[0-9]+$ ]] || [ "$value" -lt 1 ] || [ "$value" -gt 3600 ]; then
    echo "Resident provider timeouts must be integers from 1 through 3600" >&2
    exit 2
  fi
done
if ! command -v python3.12 >/dev/null 2>&1 \
  || [ "$(python3.12 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')" != "3.12" ]; then
  echo "Resident provider lifecycle gate requires Python 3.12" >&2
  exit 2
fi
for program in ps; do
  if ! command -v "$program" >/dev/null 2>&1; then
    echo "Resident provider lifecycle gate requires $program" >&2
    exit 2
  fi
done
verify_clean_head

eval_cache="$(readlink -f -- "$YAP_EVAL_CACHE")"
if [ -L "$YAP_EVAL_CACHE" ] || [ ! -d "$eval_cache" ] \
  || [ "$(stat -Lc '%a' "$eval_cache")" != "700" ]; then
  echo "YAP_EVAL_CACHE must be a real mode-0700 directory" >&2
  exit 2
fi
case "$eval_cache" in
  "$repo_root"|"$repo_root"/*)
    echo "YAP_EVAL_CACHE must remain outside the repository" >&2
    exit 2
    ;;
esac
suite_path="$(readlink -f -- "$YAP_PROVIDER_DURATION_SUITE")"
case "$suite_path" in
  "$eval_cache"/*) ;;
  *)
    echo "Provider duration suite must remain inside YAP_EVAL_CACHE" >&2
    exit 2
    ;;
esac
if [ -L "$YAP_PROVIDER_DURATION_SUITE" ] || [ ! -f "$suite_path" ]; then
  echo "Provider duration suite must be a real file" >&2
  exit 2
fi
YAP_PROVIDER_DURATION_SUITE="$suite_path"
export YAP_PROVIDER_DURATION_SUITE YAP_EVAL_CACHE

gate_root="$(readlink -m -- "$YAP_RESIDENT_PROVIDER_EVIDENCE_DIR")"
case "$gate_root" in
  "$eval_cache"/*) ;;
  *)
    echo "Resident provider evidence must remain inside YAP_EVAL_CACHE" >&2
    exit 2
    ;;
esac
if [ -e "$gate_root" ] || [ -L "$YAP_RESIDENT_PROVIDER_EVIDENCE_DIR" ]; then
  echo "Resident provider lifecycle evidence directory already exists" >&2
  exit 2
fi
install -d -m 0700 "$(dirname -- "$gate_root")"
install -d -m 0700 \
  "$gate_root" \
  "$gate_root/logs" \
  "$gate_root/raw" \
  "$gate_root/runtime" \
  "$gate_root/workloads" \
  "$gate_root/provider-evidence" \
  "$gate_root/provider-evidence/vllm" \
  "$gate_root/provider-evidence/nemo"
provider_evidence_root="$gate_root/provider-evidence"

capture_host_boundary "$gate_root/before"

PYTHONPATH="$repo_root/server/src" python3.12 -m yap_server.pools.model_assets \
  --lock "$vllm_lock" --model-dir "$YAP_COHERE_MODEL_DIR" --verify-only
PYTHONPATH="$repo_root/server/src" python3.12 -m yap_server.pools.model_assets \
  --lock "$nemo_lock" --model-dir "$YAP_NEMOTRON_MODEL_DIR" --verify-only

vllm_image="$(
  PYTHONPATH="$repo_root/server/src" \
    python3.12 -m yap_server.pools.checked_runtime_image \
      verify-prepared cohere-vllm "$YAP_CHECKED_HEAD" \
      "$YAP_COHERE_VLLM_PREPARATION_RECEIPT" \
      "$YAP_COHERE_VLLM_PREPARATION_RECEIPT_SHA256"
)"
nemo_image="$(
  PYTHONPATH="$repo_root/server/src" \
    python3.12 -m yap_server.pools.checked_runtime_image \
      verify-prepared nemotron-nemo "$YAP_CHECKED_HEAD" \
      "$YAP_NEMOTRON_NEMO_PREPARATION_RECEIPT" \
      "$YAP_NEMOTRON_NEMO_PREPARATION_RECEIPT_SHA256"
)"
printf '%s\n' "$vllm_image" >"$gate_root/logs/vllm-image-id.txt"
printf '%s\n' "$nemo_image" >"$gate_root/logs/nemo-image-id.txt"

network_id="$(
  docker network create \
  --driver bridge \
  --internal \
  --label io.yap.owner=private-inference \
  --label "io.yap.revision=$YAP_CHECKED_HEAD" \
  --label "io.yap.run-token=$runtime_owner_token" \
  "$network_name" \
)"
if [[ ! "$network_id" =~ ^[0-9a-f]{64}$ ]] || ! capture_owned_network; then
  echo "Resident provider network identity is invalid" >&2
  exit 1
fi
printf '%s\n' "$network_id" >"$gate_root/logs/network-create.txt"
export YAP_PRIVATE_INFERENCE_NETWORK="$network_name"

proxy_group_file="$gate_root/runtime/cohere-vllm-proxy.pgid"
active_container_name="yap-cohere-vllm"
launcher_state_file="$gate_root/runtime/cohere-vllm-launcher.state"
launcher_result_file="$gate_root/runtime/cohere-vllm-launcher.result"
yap_start_owned_process_group \
  launcher_control_fd \
  launcher_reap_pid \
  launcher_pid \
  "$launcher_state_file" \
  "$launcher_result_file" \
  "$gate_root/logs/vllm-service.log" \
  "$gate_root/logs/vllm-service.log" \
  "$runtime_owner_token" \
  "Resident Cohere vLLM launcher" \
  -- \
  env \
    YAP_COHERE_VLLM_IMAGE="$vllm_image" \
    YAP_COHERE_VLLM_PORT="$YAP_COHERE_VLLM_PORT" \
    YAP_RUNTIME_OWNER_TOKEN="$runtime_owner_token" \
    YAP_PROXY_PROCESS_GROUP_FILE="$proxy_group_file" \
    bash "$script_dir/cohere-vllm-server.sh"
wait_for_owned_container "yap-cohere-vllm"
verify_private_container_network "$active_container_id"
run_readiness vllm vllm-cohere-batch "$vllm_lock" "$vllm_endpoint"
run_vllm_qualification
stop_provider "$YAP_COHERE_VLLM_PORT"

proxy_group_file="$gate_root/runtime/nemotron-nemo-proxy.pgid"
active_container_name="yap-nemotron-nemo"
launcher_state_file="$gate_root/runtime/nemotron-nemo-launcher.state"
launcher_result_file="$gate_root/runtime/nemotron-nemo-launcher.result"
yap_start_owned_process_group \
  launcher_control_fd \
  launcher_reap_pid \
  launcher_pid \
  "$launcher_state_file" \
  "$launcher_result_file" \
  "$gate_root/logs/nemo-service.log" \
  "$gate_root/logs/nemo-service.log" \
  "$runtime_owner_token" \
  "Resident Nemotron NeMo launcher" \
  -- \
  env \
    YAP_NEMOTRON_NEMO_IMAGE="$nemo_image" \
    YAP_BATCH_JOB_STORAGE_DIR="$eval_cache" \
    YAP_NEMOTRON_NEMO_PORT="$YAP_NEMOTRON_NEMO_PORT" \
    YAP_RUNTIME_OWNER_TOKEN="$runtime_owner_token" \
    YAP_PROXY_PROCESS_GROUP_FILE="$proxy_group_file" \
    bash "$script_dir/nemotron-nemo-server.sh"
wait_for_owned_container "yap-nemotron-nemo"
verify_private_container_network "$active_container_id"
run_readiness nemo nemo-nemotron-finalized "$nemo_lock" "$nemo_endpoint"
run_nemo_qualification
stop_provider "$YAP_NEMOTRON_NEMO_PORT"

if ! capture_owned_network; then
  echo "Resident provider network ownership changed before teardown" >&2
  exit 1
fi
docker network rm "$network_id" >"$gate_root/logs/network-remove.txt"
if ! verify_network_absent "$network_id"; then
  echo "Resident provider network remained after teardown" >&2
  exit 1
fi
network_id=""
capture_host_boundary "$gate_root/after"
verify_clean_head

PYTHONPATH="$repo_root/server/src" \
  python3.12 -m yap_server.evaluation.resident_provider_lifecycle_evidence \
    --before "$gate_root/before" \
    --after "$gate_root/after" \
    --provider-evidence-root "$provider_evidence_root" \
    --checked-head "$YAP_CHECKED_HEAD" \
    --vllm-image-id "$vllm_image" \
    --nemo-image-id "$nemo_image" \
    --vllm-preparation-receipt-sha256 \
      "$YAP_COHERE_VLLM_PREPARATION_RECEIPT_SHA256" \
    --nemo-preparation-receipt-sha256 \
      "$YAP_NEMOTRON_NEMO_PREPARATION_RECEIPT_SHA256" \
    --output "$gate_root/evidence.json" \
    >"$gate_root/logs/lifecycle-evidence.json"

printf '%s\n' "$gate_root/evidence.json"
