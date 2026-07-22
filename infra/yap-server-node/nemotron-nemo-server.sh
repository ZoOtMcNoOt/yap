#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=private-container-loopback-proxy.sh
source "$script_dir/private-container-loopback-proxy.sh"

: "${YAP_CHECKED_HEAD:?Set YAP_CHECKED_HEAD to the exact 40-character candidate SHA}"
: "${YAP_NEMOTRON_NEMO_IMAGE:?Set YAP_NEMOTRON_NEMO_IMAGE to the checked-head image}"
: "${YAP_NEMOTRON_MODEL_DIR:?Set YAP_NEMOTRON_MODEL_DIR to the verified model directory}"
: "${YAP_BATCH_JOB_STORAGE_DIR:?Set YAP_BATCH_JOB_STORAGE_DIR to the private job directory}"
: "${YAP_NEMOTRON_NEMO_API_KEY:?Set the private resident NeMo API key}"
: "${YAP_PRIVATE_INFERENCE_NETWORK:?Set the checked internal inference network}"
: "${YAP_NEMOTRON_NEMO_PORT:=18001}"

if [[ ! "$YAP_CHECKED_HEAD" =~ ^[0-9a-f]{40}$ ]]; then
  echo "YAP_CHECKED_HEAD must be a full lowercase Git SHA" >&2
  exit 2
fi
if [[ ! "$YAP_NEMOTRON_NEMO_PORT" =~ ^[0-9]+$ ]] \
  || [ "$YAP_NEMOTRON_NEMO_PORT" -lt 1024 ] \
  || [ "$YAP_NEMOTRON_NEMO_PORT" -gt 65535 ]; then
  echo "YAP_NEMOTRON_NEMO_PORT must be an unprivileged TCP port" >&2
  exit 2
fi
if [ "${#YAP_NEMOTRON_NEMO_API_KEY}" -gt 512 ] \
  || [[ "$YAP_NEMOTRON_NEMO_API_KEY" == *$'\n'* ]] \
  || [[ "$YAP_NEMOTRON_NEMO_API_KEY" == *$'\r'* ]] \
  || [[ "$YAP_NEMOTRON_NEMO_API_KEY" == *$'\t'* ]] \
  || LC_ALL=C grep -q '[^!-~]' <<<"$YAP_NEMOTRON_NEMO_API_KEY"; then
  echo "YAP_NEMOTRON_NEMO_API_KEY must be at most 512 visible ASCII characters" >&2
  exit 2
fi
for directory in "$YAP_NEMOTRON_MODEL_DIR" "$YAP_BATCH_JOB_STORAGE_DIR"; do
  if [ -L "$directory" ] || [ ! -d "$directory" ]; then
    echo "resident NeMo directories must be real directories" >&2
    exit 2
  fi
  case "$directory" in
    *','*|*$'\n'*|*$'\r'*)
      echo "resident NeMo directory contains an unsafe mount character" >&2
      exit 2
      ;;
  esac
done
storage_mode="$(stat -Lc '%a' "$YAP_BATCH_JOB_STORAGE_DIR")"
if [ "$storage_mode" != "700" ]; then
  echo "YAP_BATCH_JOB_STORAGE_DIR must have mode 0700" >&2
  exit 2
fi
run_as_uid="$(id -u)"
run_as_gid="$(id -g)"
if [ "$run_as_uid" -eq 0 ] || [ "$run_as_gid" -eq 0 ]; then
  echo "The resident NeMo launcher must run as a non-root model owner" >&2
  exit 2
fi
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

image_id="$(docker image inspect --format '{{.Id}}' "$YAP_NEMOTRON_NEMO_IMAGE")"
architecture="$(docker image inspect --format '{{.Architecture}}' "$YAP_NEMOTRON_NEMO_IMAGE")"
revision="$(
  docker image inspect \
    --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' \
    "$YAP_NEMOTRON_NEMO_IMAGE"
)"
if [[ ! "$image_id" =~ ^sha256:[0-9a-f]{64}$ ]]; then
  echo "YAP_NEMOTRON_NEMO_IMAGE did not resolve to an immutable image ID" >&2
  exit 2
fi
if [ "$architecture" != "arm64" ]; then
  echo "YAP_NEMOTRON_NEMO_IMAGE must be ARM64" >&2
  exit 2
fi
if [ "$revision" != "$YAP_CHECKED_HEAD" ]; then
  echo "YAP_NEMOTRON_NEMO_IMAGE revision differs from YAP_CHECKED_HEAD" >&2
  exit 2
fi
if docker container inspect yap-nemotron-nemo >/dev/null 2>&1; then
  echo "The Yap resident NeMo container name is already owned; stop it explicitly" >&2
  exit 2
fi

export YAP_NEMOTRON_NEMO_API_KEY
run_private_container_with_loopback_proxy \
  yap-nemotron-nemo \
  "$YAP_PRIVATE_INFERENCE_NETWORK" \
  "$YAP_NEMOTRON_NEMO_PORT" \
  8000 \
  -- \
  docker run \
  --detach \
  --rm \
  --name yap-nemotron-nemo \
  --label io.yap.owner=private-inference \
  --label "io.yap.revision=$YAP_CHECKED_HEAD" \
  --pull never \
  --network "$YAP_PRIVATE_INFERENCE_NETWORK" \
  --user "$run_as_uid:$run_as_gid" \
  --read-only \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --memory 96g \
  --memory-swap 96g \
  --cpus 16 \
  --pids-limit 4096 \
  --shm-size 1g \
  --log-driver local \
  --log-opt max-size=10m \
  --log-opt max-file=3 \
  --stop-timeout 10 \
  --tmpfs /tmp:rw,nosuid,nodev,noexec,size=4g,mode=1777 \
  --tmpfs "/torch-compile-cache:rw,nosuid,nodev,exec,size=256m,mode=0700,uid=$run_as_uid,gid=$run_as_gid" \
  --device nvidia.com/gpu=all \
  --env YAP_NEMOTRON_NEMO_API_KEY \
  --env HF_HUB_OFFLINE=1 \
  --env TRANSFORMERS_OFFLINE=1 \
  --env HF_HUB_DISABLE_TELEMETRY=1 \
  --env DO_NOT_TRACK=1 \
  --env TRITON_CACHE_DIR=/torch-compile-cache \
  --mount "type=bind,src=$YAP_NEMOTRON_MODEL_DIR,dst=/models/asr,readonly" \
  --mount "type=bind,src=$YAP_BATCH_JOB_STORAGE_DIR,dst=$YAP_BATCH_JOB_STORAGE_DIR,readonly" \
  --entrypoint python3 \
  "$image_id" \
  -m yap_server.pools.nemotron_nemo_service \
  --lock /opt/yap-server/model-locks/nemotron-batch.json \
  --model-dir /models/asr \
  --storage-dir "$YAP_BATCH_JOB_STORAGE_DIR" \
  --host 0.0.0.0 \
  --port 8000
