#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/../.." && pwd)"

: "${YAP_CHECKED_HEAD:?Set YAP_CHECKED_HEAD to the exact 40-character candidate SHA}"
: "${YAP_ASR_MODEL_DIR:?Set YAP_ASR_MODEL_DIR to the verified private model directory}"
: "${YAP_BATCH_JOB_STORAGE_DIR:?Set YAP_BATCH_JOB_STORAGE_DIR to a private job directory}"
: "${YAP_COHERE_VLLM_API_KEY:?Set the private vLLM API key without writing it to the repository}"
: "${YAP_COHERE_VLLM_ENDPOINT:=http://127.0.0.1:18000}"
: "${YAP_ASR_MODEL_LOCK:=$repo_root/server/cohere-vllm-serving.lock.json}"
: "${YAP_ASR_CAPABILITY_LOCK:=$repo_root/server/asr-capabilities.lock.json}"
: "${YAP_ASR_WORKER_TIMEOUT_SECONDS:=1800}"
: "${YAP_NEMOTRON_MODEL_DIR:=}"
: "${YAP_NEMOTRON_MODEL_LOCK:=}"
: "${YAP_NEMOTRON_ASR_RUNTIME:=nemo-resident}"
: "${YAP_NEMOTRON_NEMO_ENDPOINT:=http://127.0.0.1:18001}"
: "${YAP_NEMOTRON_NEMO_API_KEY:=}"

if [[ ! "$YAP_CHECKED_HEAD" =~ ^[0-9a-f]{40}$ ]]; then
  echo "YAP_CHECKED_HEAD must be a full lowercase Git SHA" >&2
  exit 2
fi

if ! inside_worktree="$(
  git -C "$repo_root" rev-parse --is-inside-work-tree 2>/dev/null
)" || [ "$inside_worktree" != "true" ]; then
  echo "Development batch-server launch requires a Git worktree" >&2
  exit 2
fi

actual_head="$(git -C "$repo_root" rev-parse HEAD)"
if [ "$actual_head" != "$YAP_CHECKED_HEAD" ]; then
  echo "checked head does not match the repository HEAD" >&2
  exit 2
fi
worktree_status="$(
  git -C "$repo_root" status --porcelain=v1 --untracked-files=normal
)"
if [ -n "$worktree_status" ]; then
  echo "Development batch-server launch requires a clean checked head" >&2
  exit 2
fi

if [ ! -d "$YAP_ASR_MODEL_DIR" ]; then
  echo "YAP_ASR_MODEL_DIR must be an existing directory" >&2
  exit 2
fi
if [ ! -f "$YAP_ASR_MODEL_LOCK" ]; then
  echo "YAP_ASR_MODEL_LOCK must be an existing file" >&2
  exit 2
fi
if [ ! -f "$YAP_ASR_CAPABILITY_LOCK" ]; then
  echo "YAP_ASR_CAPABILITY_LOCK must be an existing file" >&2
  exit 2
fi
if [ -n "$YAP_NEMOTRON_MODEL_DIR" ]; then
  : "${YAP_NEMOTRON_MODEL_LOCK:=$repo_root/server/nemotron-nemo-serving.lock.json}"
  if [ ! -d "$YAP_NEMOTRON_MODEL_DIR" ]; then
    echo "YAP_NEMOTRON_MODEL_DIR must be an existing directory" >&2
    exit 2
  fi
  if [ ! -f "$YAP_NEMOTRON_MODEL_LOCK" ]; then
    echo "YAP_NEMOTRON_MODEL_LOCK must be an existing file" >&2
    exit 2
  fi
  if [ -z "$YAP_NEMOTRON_NEMO_API_KEY" ]; then
    echo "YAP_NEMOTRON_NEMO_API_KEY is required with resident Nemotron" >&2
    exit 2
  fi
  selected_capability_lock="$(readlink -f -- "$YAP_ASR_CAPABILITY_LOCK")"
  committed_capability_lock="$(readlink -f -- "$repo_root/server/asr-capabilities.lock.json")"
  if [ "$selected_capability_lock" = "$committed_capability_lock" ]; then
    echo "resident Nemotron requires an explicit candidate capability lock" >&2
    exit 2
  fi
  case "$selected_capability_lock" in
    "$repo_root"/*)
      echo "candidate capability locks must remain outside the repository" >&2
      exit 2
      ;;
  esac
fi
if ! command -v python3.12 >/dev/null 2>&1; then
  echo "The batch server requires python3.12" >&2
  exit 2
fi
python_version="$(python3.12 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')"
if [ "$python_version" != "3.12" ]; then
  echo "The batch server requires Python 3.12" >&2
  exit 2
fi

umask 077
mkdir -p -- "$YAP_BATCH_JOB_STORAGE_DIR"
if [ -L "$YAP_BATCH_JOB_STORAGE_DIR" ] || [ ! -d "$YAP_BATCH_JOB_STORAGE_DIR" ]; then
  echo "YAP_BATCH_JOB_STORAGE_DIR must be a real directory" >&2
  exit 2
fi
storage_mode="$(stat -Lc '%a' "$YAP_BATCH_JOB_STORAGE_DIR")"
if [ "$storage_mode" != "700" ]; then
  echo "YAP_BATCH_JOB_STORAGE_DIR must have mode 0700" >&2
  exit 2
fi

exec env \
  PYTHONNOUSERSITE=1 \
  PYTHONPATH="$repo_root/server/src" \
  YAP_SERVER_HOST=127.0.0.1 \
  YAP_SERVER_PORT=18765 \
  YAP_BATCH_ASR_ENABLED=1 \
  YAP_CHECKED_HEAD="$YAP_CHECKED_HEAD" \
  YAP_COHERE_ASR_RUNTIME=vllm \
  YAP_COHERE_VLLM_ENDPOINT="$YAP_COHERE_VLLM_ENDPOINT" \
  YAP_COHERE_VLLM_API_KEY="$YAP_COHERE_VLLM_API_KEY" \
  YAP_NEMOTRON_MODEL_DIR="$YAP_NEMOTRON_MODEL_DIR" \
  YAP_NEMOTRON_MODEL_LOCK="$YAP_NEMOTRON_MODEL_LOCK" \
  YAP_NEMOTRON_ASR_RUNTIME="$YAP_NEMOTRON_ASR_RUNTIME" \
  YAP_NEMOTRON_NEMO_ENDPOINT="$YAP_NEMOTRON_NEMO_ENDPOINT" \
  YAP_NEMOTRON_NEMO_API_KEY="$YAP_NEMOTRON_NEMO_API_KEY" \
  YAP_ASR_MODEL_LOCK="$YAP_ASR_MODEL_LOCK" \
  YAP_ASR_CAPABILITY_LOCK="$YAP_ASR_CAPABILITY_LOCK" \
  YAP_ASR_MODEL_DIR="$YAP_ASR_MODEL_DIR" \
  YAP_BATCH_JOB_STORAGE_DIR="$YAP_BATCH_JOB_STORAGE_DIR" \
  YAP_ASR_WORKER_TIMEOUT_SECONDS="$YAP_ASR_WORKER_TIMEOUT_SECONDS" \
  python3.12 -m yap_server
