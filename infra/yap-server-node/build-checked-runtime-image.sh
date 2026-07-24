#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 2 ]; then
  echo "usage: build-checked-runtime-image.sh RUNTIME CHECKED_HEAD" >&2
  exit 2
fi

runtime="$1"
checked_head="$2"
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/../.." && pwd)"

if [[ ! "$checked_head" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Checked head must be one full lowercase Git SHA" >&2
  exit 2
fi
if [ "$(git -C "$repo_root" rev-parse HEAD)" != "$checked_head" ]; then
  echo "Checked head does not match the repository HEAD" >&2
  exit 2
fi
if [ -n "$(
  git -C "$repo_root" status --porcelain=v1 --untracked-files=normal
)" ]; then
  echo "Checked runtime image builds require a clean worktree" >&2
  exit 2
fi

case "$runtime" in
  cohere-vllm)
    dockerfile="$repo_root/server/runtime/cohere-vllm/Dockerfile"
    image="yap-cohere-vllm:checked-head-$checked_head"
    revision_mode=build-argument
    ;;
  nemotron-nemo)
    dockerfile="$repo_root/server/runtime/nemotron-nemo/Dockerfile"
    image="yap-nemotron-nemo:checked-head-$checked_head"
    revision_mode=build-argument
    ;;
  language-detection)
    dockerfile="$repo_root/server/runtime/lid/Dockerfile"
    image="yap-lid:checked-head-$checked_head"
    revision_mode=build-argument
    ;;
  reference-batch-asr)
    dockerfile="$repo_root/server/runtime/asr/Dockerfile"
    image="yap-gb10-asr:checked-head-$checked_head"
    revision_mode=label
    ;;
  *)
    echo "Unsupported checked runtime: $runtime" >&2
    exit 2
    ;;
esac

base_output="$(
  python3.12 - "$dockerfile" <<'PY'
from __future__ import annotations

from pathlib import Path
import re
import shlex
import sys


dockerfile = Path(sys.argv[1])
arguments: dict[str, str] = {}
stages: set[str] = set()
bases: list[str] = []

for line_number, raw_line in enumerate(
    dockerfile.read_text(encoding="utf-8").splitlines(),
    start=1,
):
    line = raw_line.strip()
    if not line or line.startswith("#"):
        continue

    instruction, _, value = line.partition(" ")
    instruction = instruction.upper()
    value = value.strip()
    if instruction == "ARG":
        name, separator, default = value.partition("=")
        if separator:
            arguments[name.strip()] = default.strip()
        continue
    if instruction != "FROM":
        continue

    tokens = shlex.split(value)
    while tokens and tokens[0].startswith("--"):
        tokens.pop(0)
    if not tokens:
        raise SystemExit(f"{dockerfile}:{line_number}: FROM has no image")

    reference = tokens[0]

    def expand(match: re.Match[str]) -> str:
        name = match.group(1) or match.group(2)
        if name not in arguments:
            raise SystemExit(
                f"{dockerfile}:{line_number}: unresolved build argument {name}"
            )
        return arguments[name]

    reference = re.sub(r"\$\{([^}]+)\}|\$([A-Za-z_][A-Za-z0-9_]*)", expand, reference)
    if reference not in stages:
        if re.fullmatch(r".+@sha256:[0-9a-f]{64}", reference) is None:
            raise SystemExit(
                f"{dockerfile}:{line_number}: external base is not digest-pinned: "
                f"{reference}"
            )
        if reference not in bases:
            bases.append(reference)

    for index, token in enumerate(tokens[1:], start=1):
        if token.upper() == "AS" and index + 1 < len(tokens):
            stages.add(tokens[index + 1])
            break

if not bases:
    raise SystemExit(f"{dockerfile}: no external base image was found")

print("\n".join(bases))
PY
)"
mapfile -t base_images <<<"$base_output"

for base_image in "${base_images[@]}"; do
  if ! image_id="$(
    docker image inspect --format '{{.Id}}' "$base_image" 2>/dev/null
  )"; then
    echo "Cached digest-pinned base image is required: $base_image" >&2
    exit 2
  fi
  if [[ ! "$image_id" =~ ^sha256:[0-9a-f]{64}$ ]]; then
    echo "Cached base image has an invalid local image identity: $base_image" >&2
    exit 2
  fi
done

build_arguments=(
  --pull=false
  --file "$dockerfile"
  --tag "$image"
)
if [ "$revision_mode" = build-argument ]; then
  build_arguments+=(--build-arg "YAP_CHECKED_HEAD=$checked_head")
else
  build_arguments+=(--label "org.opencontainers.image.revision=$checked_head")
fi

docker build "${build_arguments[@]}" "$repo_root/server"
printf '%s\n' "$image"
