#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=owned-process-group.sh
source "$script_dir/owned-process-group.sh"
# shellcheck source=private-container-loopback-proxy.sh
source "$script_dir/private-container-loopback-proxy.sh"

: "${YAP_CHECKED_HEAD:?Set YAP_CHECKED_HEAD to the exact 40-character candidate SHA}"
: "${YAP_AGENT_MODEL_SNAPSHOT:?Set the exact verified model snapshot directory}"
: "${YAP_PRIVATE_INFERENCE_NETWORK:?Set the checked internal inference network}"
: "${YAP_RUNTIME_OWNER_TOKEN:?Set the per-run container ownership token}"
: "${YAP_PROXY_PROCESS_GROUP_FILE:?Set the private proxy process-group identity path}"

die() {
  echo "$1" >&2
  exit 2
}

if [ "$#" -ne 6 ] \
  || [ "$1" != "--profile" ] \
  || [ "$3" != "--profile-sha256" ] \
  || [ "$5" != "--candidate-lock" ]; then
  die "agent vLLM launcher requires one supervisor-bound profile"
fi
if [[ ! "$YAP_CHECKED_HEAD" =~ ^[0-9a-f]{40}$ ]]; then
  die "YAP_CHECKED_HEAD must be a full lowercase Git SHA"
fi
run_as_uid="$(id -u)"
run_as_gid="$(id -g)"
if [ "$run_as_uid" -eq 0 ] || [ "$run_as_gid" -eq 0 ]; then
  die "The agent vLLM launcher must run as a non-root model owner"
fi
for directory in "$YAP_AGENT_MODEL_SNAPSHOT" "$script_dir/python"; do
  if [[ "$directory" != /* ]] || [ -L "$directory" ] || [ ! -d "$directory" ]; then
    die "agent vLLM source and model directories must be real absolute directories"
  fi
done
if [[ ! "$YAP_AGENT_MODEL_SNAPSHOT" =~ ^/[A-Za-z0-9_./:-]+$ ]] \
  || [[ "$YAP_AGENT_MODEL_SNAPSHOT" == *"/../"* ]] \
  || [[ "$YAP_AGENT_MODEL_SNAPSHOT" == *"/./"* ]] \
  || [[ "$YAP_AGENT_MODEL_SNAPSHOT" == */.. ]] \
  || [[ "$YAP_AGENT_MODEL_SNAPSHOT" == */. ]]; then
  die "YAP_AGENT_MODEL_SNAPSHOT must use a canonical portable path"
fi
model_snapshot_canonical="$(realpath -e -- "$YAP_AGENT_MODEL_SNAPSHOT")" \
  || die "YAP_AGENT_MODEL_SNAPSHOT must resolve exactly"
if [ "$model_snapshot_canonical" != "$YAP_AGENT_MODEL_SNAPSHOT" ]; then
  die "YAP_AGENT_MODEL_SNAPSHOT must not contain symbolic-link ancestry"
fi
source_uid=""
for source in \
  "$script_dir/python/yap_server/pools/agent_model_snapshot.py" \
  "$script_dir/python/yap_server/pools/agent_vllm_launch_contract.py" \
  "$script_dir/python/yap_server/pools/agent_vllm_service_profile.py" \
  "$script_dir/python/yap_server/pools/agent_vllm_service_profile_cli.py" \
  "$script_dir/python/yap_server/pools/numeric_loopback_endpoint.py"; do
  if [ -L "$source" ] || [ ! -f "$source" ]; then
    die "agent vLLM profile runtime is not owned and immutable"
  fi
  source_uid="$(stat -c '%u' "$source")"
  if { [ "$source_uid" -ne 0 ] && [ "$source_uid" -ne "$run_as_uid" ]; } \
    || [ $((8#$(stat -c '%a' "$source") & 8#022)) -ne 0 ]; then
    die "agent vLLM profile runtime is not owned and immutable"
  fi
done
if [[ ! "$YAP_PRIVATE_INFERENCE_NETWORK" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$ ]]; then
  die "YAP_PRIVATE_INFERENCE_NETWORK is invalid"
fi
if [[ ! "$YAP_RUNTIME_OWNER_TOKEN" =~ ^[0-9a-f]{64}$ ]]; then
  die "YAP_RUNTIME_OWNER_TOKEN must be 32 random bytes in lowercase hex"
fi

mapfile -d '' -t profile_values < <(
  env -i \
    PATH=/usr/sbin:/usr/bin:/sbin:/bin \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH="$script_dir/python" \
    python3.12 -m yap_server.pools.agent_vllm_service_profile_cli \
      "$@" \
      --model-snapshot "$YAP_AGENT_MODEL_SNAPSHOT" \
      --emit-null
)
if [ "${#profile_values[@]}" -lt 18 ]; then
  die "agent vLLM service profile output is incomplete"
fi
profile_id="${profile_values[0]}"
profile_service="${profile_values[1]}"
profile_host_port="${profile_values[2]}"
profile_container_name="${profile_values[3]}"
profile_image="${profile_values[4]}"
profile_image_id="${profile_values[5]}"
profile_model="${profile_values[6]}"
profile_model_revision="${profile_values[7]}"
profile_artifact_sha256="${profile_values[8]}"
profile_container_port="${profile_values[9]}"
profile_memory_bytes="${profile_values[10]}"
profile_memory_swap_bytes="${profile_values[11]}"
profile_cpu_count="${profile_values[12]}"
profile_pids_limit="${profile_values[13]}"
profile_shm_bytes="${profile_values[14]}"
profile_tmpfs_bytes="${profile_values[15]}"
profile_argument_count="${profile_values[16]}"
if [[ ! "$profile_argument_count" =~ ^[0-9]+$ ]] \
  || [ "$profile_argument_count" -lt 1 ] \
  || [ "${#profile_values[@]}" -ne "$((17 + profile_argument_count))" ]; then
  die "agent vLLM service profile argument count differs"
fi
profile_launch_arguments=("${profile_values[@]:17}")
if [ "$profile_id" != "$profile_service" ]; then
  die "agent vLLM service profile identity differs"
fi
model_root_canonical="$(realpath -e -- "$YAP_AGENT_MODEL_SNAPSHOT/../..")" \
  || die "agent vLLM model repository must resolve exactly"
if [ -L "$model_root_canonical" ] \
  || [ ! -d "$model_root_canonical" ] \
  || [ "$YAP_AGENT_MODEL_SNAPSHOT" != "$model_root_canonical/snapshots/$profile_model_revision" ]; then
  die "agent vLLM snapshot is outside its exact model repository"
fi

network_identity="$(
  docker network inspect \
    --format '{{.Internal}}|{{.Driver}}|{{index .Labels "io.yap.owner"}}|{{index .Labels "io.yap.revision"}}|{{index .Labels "io.yap.run-token"}}' \
    "$YAP_PRIVATE_INFERENCE_NETWORK"
)"
IFS='|' read -r network_internal network_driver network_owner network_revision network_run_token \
  <<<"$network_identity"
if [ "$network_internal" != "true" ] \
  || [ "$network_driver" != "bridge" ] \
  || [ "$network_owner" != "private-inference" ] \
  || [ "$network_revision" != "$YAP_CHECKED_HEAD" ] \
  || [ "$network_run_token" != "$YAP_RUNTIME_OWNER_TOKEN" ]; then
  die "YAP_PRIVATE_INFERENCE_NETWORK is not the checked internal network"
fi

image_identity="$(
  docker image inspect \
    --format '{{.Id}}|{{.Os}}|{{.Architecture}}' \
    "$profile_image"
)"
IFS='|' read -r image_id image_os image_architecture <<<"$image_identity"
if [ "$image_id" != "$profile_image_id" ] \
  || [ "$image_os" != "linux" ] \
  || [ "$image_architecture" != "arm64" ]; then
  die "agent vLLM image differs from the checked profile"
fi
if docker container inspect "$profile_container_name" >/dev/null 2>&1; then
  die "The agent vLLM container name is already owned; stop it explicitly"
fi

run_private_container_with_loopback_proxy \
  "$profile_container_name" \
  "$YAP_PRIVATE_INFERENCE_NETWORK" \
  "$profile_host_port" \
  "$profile_container_port" \
  "$YAP_RUNTIME_OWNER_TOKEN" \
  "$YAP_PROXY_PROCESS_GROUP_FILE" \
  -- \
  docker container create \
  --name "$profile_container_name" \
  --label io.yap.owner=private-inference \
  --label "io.yap.revision=$YAP_CHECKED_HEAD" \
  --label "io.yap.run-token=$YAP_RUNTIME_OWNER_TOKEN" \
  --label "io.yap.agent-profile=$profile_id" \
  --label "io.yap.model=$profile_model" \
  --label "io.yap.model-revision=$profile_model_revision" \
  --label "io.yap.model-artifact-sha256=$profile_artifact_sha256" \
  --pull never \
  --network "$YAP_PRIVATE_INFERENCE_NETWORK" \
  --ipc=host \
  --user "$run_as_uid:$run_as_gid" \
  --ulimit memlock=-1 \
  --ulimit stack=67108864 \
  --read-only \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --memory "$profile_memory_bytes" \
  --memory-swap "$profile_memory_swap_bytes" \
  --cpus "$profile_cpu_count" \
  --pids-limit "$profile_pids_limit" \
  --shm-size "$profile_shm_bytes" \
  --log-driver local \
  --log-opt max-size=10m \
  --log-opt max-file=3 \
  --stop-timeout 10 \
  --tmpfs "/tmp:rw,nosuid,nodev,exec,size=$profile_tmpfs_bytes,mode=1777" \
  --device nvidia.com/gpu=all \
  --env HF_HUB_OFFLINE=1 \
  --env TRANSFORMERS_OFFLINE=1 \
  --env HF_HUB_DISABLE_TELEMETRY=1 \
  --env DO_NOT_TRACK=1 \
  --env HOME=/tmp \
  --mount "type=bind,src=$model_root_canonical,dst=/model-cache,readonly" \
  "$profile_image_id" \
  "${profile_launch_arguments[@]}"
