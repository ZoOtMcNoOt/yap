#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
python_root="$("$repo_root/server/.venv/bin/python" -c 'import sys; print(sys.base_prefix)')"
image='ghcr.io/catthehacker/ubuntu:act-24.04@sha256:62d572b92f9f32d3427b6d220ad1f9dca9c7b6ffad37d295425037dbff78abaf'

# Ubuntu provides the private launcher contract's real /usr/bin/python3.12.
# Docker's init reaps orphaned descendants; tests use loopback and fixtures.
env -u DOCKER_HOST -u DOCKER_CONTEXT -u DOCKER_TLS -u DOCKER_TLS_VERIFY -u DOCKER_CERT_PATH \
  docker --host=unix:///var/run/docker.sock run --rm --init --network none \
  --user "$(id -u):$(id -g)" \
  --mount "type=bind,src=$repo_root,dst=$repo_root" \
  --mount "type=bind,src=$python_root,dst=$python_root,readonly" \
  --mount "type=bind,src=$HOME/.cargo,dst=$HOME/.cargo" \
  --mount "type=bind,src=$HOME/.rustup,dst=$HOME/.rustup,readonly" \
  -e "HOME=$HOME" -e "PATH=$repo_root/.tools/powershell:$HOME/.cargo/bin:$python_root/bin:/usr/local/bin:/usr/bin:/bin" \
  -e PYTHONPATH=src -w "$repo_root/server" "$image" \
  .venv/bin/python ../verification/run-portable-server-suite.py
