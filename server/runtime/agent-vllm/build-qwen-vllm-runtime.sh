#!/usr/bin/env bash
set -euo pipefail

server_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
cd "$server_root"

export SOURCE_DATE_EPOCH=0
docker buildx build \
  --quiet \
  --pull=false \
  --no-cache \
  --build-arg SOURCE_DATE_EPOCH=0 \
  --output type=docker,rewrite-timestamp=true \
  --file runtime/agent-vllm/Dockerfile \
  --tag yap-agent-vllm:qwen-26.07-xgrammar-0.2.1 \
  .
