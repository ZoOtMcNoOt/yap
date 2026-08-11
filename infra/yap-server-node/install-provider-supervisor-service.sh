#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
unit_template="$script_dir/yap-provider-supervisor@.service.in"
binary_destination=/usr/local/libexec/yap-provider-supervisor
unit_destination=/etc/systemd/system/yap-provider-supervisor@.service
agent_launcher_source="$script_dir/agent-vllm-server.sh"
proxy_helper_source="$script_dir/private-container-loopback-proxy.sh"
process_group_source="$script_dir/owned-process-group.sh"
process_supervisor_source="$script_dir/owned-process-supervisor.py"
repository_root="$(cd -- "$script_dir/../.." && pwd -P)"
profile_source_root="$repository_root/server/agent-service-profiles"
candidate_lock_source="$repository_root/server/agent-reasoning-candidates.lock.json"
agent_launcher_root=/usr/local/libexec/yap-agent-vllm
profile_python_source_root="$repository_root/server/src/yap_server/pools"
profile_python_destination_root="$agent_launcher_root/python/yap_server/pools"
profile_destination_root=/usr/local/share/yap/agent-service-profiles
candidate_lock_destination=/usr/local/share/yap/agent-reasoning-candidates.lock.json
rapid_environment_destination=/etc/yap/providers/rapid-automation.env
complex_environment_destination=/etc/yap/providers/complex-orchestration.env

: "${YAP_PROVIDER_OWNER:?Set YAP_PROVIDER_OWNER to the existing non-root model owner}"
: "${YAP_PROVIDER_GROUP:?Set YAP_PROVIDER_GROUP to the existing model-owner group}"
: "${YAP_SUPERVISOR_BINARY:?Set YAP_SUPERVISOR_BINARY to the reviewed Rust binary}"
: "${YAP_CHECKED_HEAD:?Set YAP_CHECKED_HEAD to the exact release commit}"
: "${YAP_RAPID_MODEL_SNAPSHOT:?Set YAP_RAPID_MODEL_SNAPSHOT to the exact Qwen snapshot}"
: "${YAP_COMPLEX_MODEL_SNAPSHOT:?Set YAP_COMPLEX_MODEL_SNAPSHOT to the exact Gemma snapshot}"
: "${YAP_RAPID_PRIVATE_INFERENCE_NETWORK:?Set the checked rapid internal network}"
: "${YAP_COMPLEX_PRIVATE_INFERENCE_NETWORK:?Set the checked complex internal network}"
: "${YAP_RAPID_RUNTIME_OWNER_TOKEN:?Set a 32-byte lowercase-hex rapid service token}"
: "${YAP_COMPLEX_RUNTIME_OWNER_TOKEN:?Set a 32-byte lowercase-hex complex service token}"

die() {
  echo "$1" >&2
  exit 1
}

valid_account_name() {
  printf '%s' "$1" | grep -Eq '^[a-z_][a-z0-9_-]*[$]?$'
}

safe_environment_value() {
  [[ "$1" =~ ^[A-Za-z0-9_./:-]+$ ]]
}

validate_regular_source() {
  local path="$1"
  local description="$2"
  if [ -L "$path" ] || [ ! -f "$path" ]; then
    die "$description must be a real file"
  fi
}

validate_destination() {
  local path="$1"
  if [ -L "$path" ] || { [ -e "$path" ] && [ ! -f "$path" ]; }; then
    die "provider service destination is unsafe"
  fi
}

validate_inputs() {
  valid_account_name "$YAP_PROVIDER_OWNER" \
    || die "YAP_PROVIDER_OWNER is invalid"
  valid_account_name "$YAP_PROVIDER_GROUP" \
    || die "YAP_PROVIDER_GROUP is invalid"
  id "$YAP_PROVIDER_OWNER" >/dev/null 2>&1 \
    || die "YAP_PROVIDER_OWNER must already exist"
  getent group "$YAP_PROVIDER_GROUP" >/dev/null 2>&1 \
    || die "YAP_PROVIDER_GROUP must already exist"
  if [ "$(id -u "$YAP_PROVIDER_OWNER")" -eq 0 ]; then
    die "YAP_PROVIDER_OWNER must be non-root"
  fi
  case "$YAP_SUPERVISOR_BINARY" in
    /*) ;;
    *) die "YAP_SUPERVISOR_BINARY must be absolute" ;;
  esac
  if [ -L "$YAP_SUPERVISOR_BINARY" ] \
    || [ ! -f "$YAP_SUPERVISOR_BINARY" ] \
    || [ ! -x "$YAP_SUPERVISOR_BINARY" ]; then
    die "YAP_SUPERVISOR_BINARY must be a real executable file"
  fi
  if [ -L "$unit_template" ] || [ ! -f "$unit_template" ]; then
    die "The provider supervisor unit template is invalid"
  fi
  if [[ ! "$YAP_CHECKED_HEAD" =~ ^[0-9a-f]{40}$ ]]; then
    die "YAP_CHECKED_HEAD must be one full lowercase Git SHA"
  fi
  for directory in \
    "$YAP_RAPID_MODEL_SNAPSHOT" \
    "$YAP_COMPLEX_MODEL_SNAPSHOT"; do
    if [[ "$directory" != /* ]] \
      || [ -L "$directory" ] \
      || [ ! -d "$directory" ] \
      || ! safe_environment_value "$directory"; then
      die "provider service source and model directories must be safe absolute directories"
    fi
    canonical_directory="$(realpath -e -- "$directory")" \
      || die "provider service model directory must resolve exactly"
    if [ "$canonical_directory" != "$directory" ]; then
      die "provider service model directory must not contain symbolic-link ancestry"
    fi
  done
  if ! command -v git >/dev/null 2>&1 \
    || [ "$(git -C "$repository_root" rev-parse --show-toplevel)" != "$repository_root" ] \
    || [ "$(git -C "$repository_root" rev-parse HEAD)" != "$YAP_CHECKED_HEAD" ] \
    || [ -n "$(git -C "$repository_root" status --porcelain=v1 --untracked-files=all)" ]; then
    die "provider service installation requires the exact clean checked repository"
  fi
  for source in \
    "$profile_python_source_root/agent_model_snapshot.py" \
    "$profile_python_source_root/agent_vllm_launch_contract.py" \
    "$profile_python_source_root/agent_vllm_service_profile.py" \
    "$profile_python_source_root/agent_vllm_service_profile_cli.py" \
    "$profile_python_source_root/numeric_loopback_endpoint.py"; do
    validate_regular_source "$source" "The agent profile reader"
  done
  for network in \
    "$YAP_RAPID_PRIVATE_INFERENCE_NETWORK" \
    "$YAP_COMPLEX_PRIVATE_INFERENCE_NETWORK"; do
    if [[ ! "$network" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$ ]]; then
      die "agent service private inference network is invalid"
    fi
  done
  if [ "$YAP_RAPID_PRIVATE_INFERENCE_NETWORK" = "$YAP_COMPLEX_PRIVATE_INFERENCE_NETWORK" ]; then
    die "agent services require distinct private inference networks"
  fi
  for token in \
    "$YAP_RAPID_RUNTIME_OWNER_TOKEN" \
    "$YAP_COMPLEX_RUNTIME_OWNER_TOKEN"; do
    if [[ ! "$token" =~ ^[0-9a-f]{64}$ ]]; then
      die "agent service owner tokens must be 32 random bytes in lowercase hex"
    fi
  done
  if [ "$YAP_RAPID_RUNTIME_OWNER_TOKEN" = "$YAP_COMPLEX_RUNTIME_OWNER_TOKEN" ]; then
    die "agent service owner tokens must be distinct"
  fi
  for source in \
    "$agent_launcher_source" \
    "$proxy_helper_source" \
    "$process_group_source" \
    "$process_supervisor_source" \
    "$profile_source_root/rapid-automation.json" \
    "$profile_source_root/complex-orchestration.json" \
    "$candidate_lock_source"; do
    validate_regular_source "$source" "Provider service input"
  done
  for destination in \
    "$binary_destination" \
    "$unit_destination" \
    "$agent_launcher_root/agent-vllm-server.sh" \
    "$agent_launcher_root/private-container-loopback-proxy.sh" \
    "$agent_launcher_root/owned-process-group.sh" \
    "$agent_launcher_root/owned-process-supervisor.py" \
    "$profile_python_destination_root/agent_model_snapshot.py" \
    "$profile_python_destination_root/agent_vllm_launch_contract.py" \
    "$profile_python_destination_root/agent_vllm_service_profile.py" \
    "$profile_python_destination_root/agent_vllm_service_profile_cli.py" \
    "$profile_python_destination_root/numeric_loopback_endpoint.py" \
    "$profile_destination_root/rapid-automation.json" \
    "$profile_destination_root/complex-orchestration.json" \
    "$candidate_lock_destination" \
    "$rapid_environment_destination" \
    "$complex_environment_destination"; do
    validate_destination "$destination"
  done
}

render_unit() {
  rendered_unit="$(<"$unit_template")"
  rendered_unit="${rendered_unit//@YAP_PROVIDER_OWNER@/$YAP_PROVIDER_OWNER}"
  rendered_unit="${rendered_unit//@YAP_PROVIDER_GROUP@/$YAP_PROVIDER_GROUP}"
  if grep -q '@YAP_PROVIDER_' <<<"$rendered_unit"; then
    die "The provider supervisor unit template was not fully rendered"
  fi
  printf '%s\n' "$rendered_unit"
}

render_environment() {
  local profile_id="$1"
  local profile_sha256="$2"
  local model_snapshot="$3"
  local owner_token="$4"
  local network_name="$5"
  printf '%s\n' \
    "YAP_PROVIDER_PROFILE=$profile_destination_root/$profile_id.json" \
    "YAP_PROVIDER_PROFILE_SHA256=$profile_sha256" \
    "YAP_PROVIDER_CANDIDATE_LOCK=$candidate_lock_destination" \
    "YAP_PROVIDER_LAUNCHER=$agent_launcher_root/agent-vllm-server.sh" \
    "YAP_CHECKED_HEAD=$YAP_CHECKED_HEAD" \
    "YAP_AGENT_MODEL_SNAPSHOT=$model_snapshot" \
    "YAP_PRIVATE_INFERENCE_NETWORK=$network_name" \
    "YAP_RUNTIME_OWNER_TOKEN=$owner_token" \
    "YAP_PROXY_PROCESS_GROUP_FILE=/run/yap-provider-$profile_id/proxy-group"
}

main() {
  validate_inputs
  if [ "$(id -u)" -ne 0 ]; then
    die "Run this installer as root"
  fi

  temporary_unit="$(mktemp)"
  temporary_rapid_environment="$(mktemp)"
  temporary_complex_environment="$(mktemp)"
  trap 'rm -f -- "$temporary_unit" "$temporary_rapid_environment" "$temporary_complex_environment"' EXIT
  render_unit >"$temporary_unit"
  rapid_profile_sha256="$(sha256sum "$profile_source_root/rapid-automation.json" | awk '{print $1}')"
  complex_profile_sha256="$(sha256sum "$profile_source_root/complex-orchestration.json" | awk '{print $1}')"
  render_environment \
    rapid-automation \
    "$rapid_profile_sha256" \
    "$YAP_RAPID_MODEL_SNAPSHOT" \
    "$YAP_RAPID_RUNTIME_OWNER_TOKEN" \
    "$YAP_RAPID_PRIVATE_INFERENCE_NETWORK" \
    >"$temporary_rapid_environment"
  render_environment \
    complex-orchestration \
    "$complex_profile_sha256" \
    "$YAP_COMPLEX_MODEL_SNAPSHOT" \
    "$YAP_COMPLEX_RUNTIME_OWNER_TOKEN" \
    "$YAP_COMPLEX_PRIVATE_INFERENCE_NETWORK" \
    >"$temporary_complex_environment"
  install -d -m 0755 -o root -g root /usr/local/libexec
  install -m 0755 -o root -g root "$YAP_SUPERVISOR_BINARY" "$binary_destination"
  install -d -m 0755 -o root -g root "$agent_launcher_root"
  install -m 0755 -o root -g root "$agent_launcher_source" "$agent_launcher_root/agent-vllm-server.sh"
  install -m 0755 -o root -g root "$proxy_helper_source" "$agent_launcher_root/private-container-loopback-proxy.sh"
  install -m 0755 -o root -g root "$process_group_source" "$agent_launcher_root/owned-process-group.sh"
  install -m 0755 -o root -g root "$process_supervisor_source" "$agent_launcher_root/owned-process-supervisor.py"
  install -d -m 0755 -o root -g root "$agent_launcher_root/python"
  install -d -m 0755 -o root -g root "$agent_launcher_root/python/yap_server"
  install -d -m 0755 -o root -g root "$profile_python_destination_root"
  for source in \
    "$profile_python_source_root/agent_model_snapshot.py" \
    "$profile_python_source_root/agent_vllm_launch_contract.py" \
    "$profile_python_source_root/agent_vllm_service_profile.py" \
    "$profile_python_source_root/agent_vllm_service_profile_cli.py" \
    "$profile_python_source_root/numeric_loopback_endpoint.py"; do
    install -m 0644 -o root -g root "$source" "$profile_python_destination_root/$(basename "$source")"
  done
  install -d -m 0755 -o root -g root /usr/local/share/yap
  install -d -m 0755 -o root -g root "$profile_destination_root"
  install -m 0644 -o root -g root "$profile_source_root/rapid-automation.json" "$profile_destination_root/rapid-automation.json"
  install -m 0644 -o root -g root "$profile_source_root/complex-orchestration.json" "$profile_destination_root/complex-orchestration.json"
  install -m 0644 -o root -g root "$candidate_lock_source" "$candidate_lock_destination"
  install -d -m 0755 -o root -g root /etc/yap
  install -d -m 0700 -o root -g root /etc/yap/providers
  install -m 0600 -o root -g root "$temporary_rapid_environment" "$rapid_environment_destination"
  install -m 0600 -o root -g root "$temporary_complex_environment" "$complex_environment_destination"
  install -m 0644 -o root -g root "$temporary_unit" "$unit_destination"
  systemctl daemon-reload
  echo "Installed rapid-automation and complex-orchestration provider profiles without enabling or starting either instance."
}

main "$@"
