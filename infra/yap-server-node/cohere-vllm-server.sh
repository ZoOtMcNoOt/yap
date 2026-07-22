#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=private-container-loopback-proxy.sh
source "$script_dir/private-container-loopback-proxy.sh"

: "${YAP_CHECKED_HEAD:?Set YAP_CHECKED_HEAD to the exact 40-character candidate SHA}"
: "${YAP_COHERE_VLLM_IMAGE:?Set YAP_COHERE_VLLM_IMAGE to the checked-head image}"
: "${YAP_COHERE_MODEL_DIR:?Set YAP_COHERE_MODEL_DIR to the verified model directory}"
: "${YAP_COHERE_VLLM_API_KEY:?Set the private vLLM API key}"
: "${YAP_PRIVATE_INFERENCE_NETWORK:?Set the checked internal inference network}"
: "${YAP_COHERE_VLLM_PORT:=18000}"

if [ "${#YAP_COHERE_VLLM_API_KEY}" -gt 512 ] \
  || [[ "$YAP_COHERE_VLLM_API_KEY" == *$'\n'* ]] \
  || [[ "$YAP_COHERE_VLLM_API_KEY" == *$'\r'* ]] \
  || [[ "$YAP_COHERE_VLLM_API_KEY" == *$'\t'* ]]; then
  echo "YAP_COHERE_VLLM_API_KEY must be at most 512 visible ASCII characters" >&2
  exit 2
fi
if LC_ALL=C grep -q '[^!-~]' <<<"$YAP_COHERE_VLLM_API_KEY"; then
  echo "YAP_COHERE_VLLM_API_KEY must be at most 512 visible ASCII characters" >&2
  exit 2
fi
VLLM_API_KEY="$YAP_COHERE_VLLM_API_KEY"
export VLLM_API_KEY

if [[ ! "$YAP_CHECKED_HEAD" =~ ^[0-9a-f]{40}$ ]]; then
  echo "YAP_CHECKED_HEAD must be a full lowercase Git SHA" >&2
  exit 2
fi
if [[ ! "$YAP_COHERE_VLLM_PORT" =~ ^[0-9]+$ ]] \
  || [ "$YAP_COHERE_VLLM_PORT" -lt 1024 ] \
  || [ "$YAP_COHERE_VLLM_PORT" -gt 65535 ]; then
  echo "YAP_COHERE_VLLM_PORT must be an unprivileged TCP port" >&2
  exit 2
fi
if [ -L "$YAP_COHERE_MODEL_DIR" ] || [ ! -d "$YAP_COHERE_MODEL_DIR" ]; then
  echo "YAP_COHERE_MODEL_DIR must be a real directory" >&2
  exit 2
fi
run_as_uid="$(id -u)"
run_as_gid="$(id -g)"
if [ "$run_as_uid" -eq 0 ] || [ "$run_as_gid" -eq 0 ]; then
  echo "The Cohere vLLM launcher must run as a non-root model owner" >&2
  exit 2
fi
case "$YAP_COHERE_MODEL_DIR" in
  *','*|*$'\n'*|*$'\r'*)
    echo "YAP_COHERE_MODEL_DIR contains an unsafe mount character" >&2
    exit 2
    ;;
esac
if [[ ! "$YAP_PRIVATE_INFERENCE_NETWORK" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$ ]]; then
  echo "YAP_PRIVATE_INFERENCE_NETWORK is invalid" >&2
  exit 2
fi
network_identity="$(
  docker network inspect \
    --format '{{.Internal}}|{{.Driver}}|{{index .Labels "io.yap.owner"}}|{{index .Labels "io.yap.revision"}}' \
    "$YAP_PRIVATE_INFERENCE_NETWORK"
)"
IFS='|' read -r network_internal network_driver network_owner network_revision \
  <<<"$network_identity"
if [ "$network_internal" != "true" ] \
  || [ "$network_driver" != "bridge" ] \
  || [ "$network_owner" != "private-inference" ] \
  || [ "$network_revision" != "$YAP_CHECKED_HEAD" ]; then
  echo "YAP_PRIVATE_INFERENCE_NETWORK is not the checked internal network" >&2
  exit 2
fi

image_id="$(docker image inspect --format '{{.Id}}' "$YAP_COHERE_VLLM_IMAGE")"
architecture="$(docker image inspect --format '{{.Architecture}}' "$YAP_COHERE_VLLM_IMAGE")"
revision="$(
  docker image inspect \
    --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' \
    "$YAP_COHERE_VLLM_IMAGE"
)"
if [[ ! "$image_id" =~ ^sha256:[0-9a-f]{64}$ ]]; then
  echo "YAP_COHERE_VLLM_IMAGE did not resolve to an immutable image ID" >&2
  exit 2
fi
if [ "$architecture" != "arm64" ]; then
  echo "YAP_COHERE_VLLM_IMAGE must be ARM64" >&2
  exit 2
fi
if [ "$revision" != "$YAP_CHECKED_HEAD" ]; then
  echo "YAP_COHERE_VLLM_IMAGE revision differs from YAP_CHECKED_HEAD" >&2
  exit 2
fi
if docker container inspect yap-cohere-vllm >/dev/null 2>&1; then
  echo "The Yap Cohere vLLM container name is already owned; stop it explicitly" >&2
  exit 2
fi

run_private_container_with_loopback_proxy \
  yap-cohere-vllm \
  "$YAP_PRIVATE_INFERENCE_NETWORK" \
  "$YAP_COHERE_VLLM_PORT" \
  8000 \
  -- \
  docker run \
  --detach \
  --rm \
  --name yap-cohere-vllm \
  --label io.yap.owner=private-inference \
  --label "io.yap.revision=$YAP_CHECKED_HEAD" \
  --pull never \
  --network "$YAP_PRIVATE_INFERENCE_NETWORK" \
  --user "$run_as_uid:$run_as_gid" \
  --read-only \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --memory 32g \
  --memory-swap 32g \
  --cpus 16 \
  --pids-limit 4096 \
  --shm-size 16g \
  --log-driver local \
  --log-opt max-size=10m \
  --log-opt max-file=3 \
  --stop-timeout 10 \
  --tmpfs /tmp:rw,nosuid,nodev,exec,size=8g,mode=1777 \
  --device nvidia.com/gpu=all \
  --env VLLM_API_KEY \
  --env HF_HUB_OFFLINE=1 \
  --env TRANSFORMERS_OFFLINE=1 \
  --mount "type=bind,src=$YAP_COHERE_MODEL_DIR,dst=/models/asr,readonly" \
  "$image_id"
