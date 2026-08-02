#!/usr/bin/env bash
# One command that converges a yap-server node as far as software can, and
# tells the truth about the rest.
#
#   ./infra/yap-server-node/yap-server-setup.sh          # report + converge
#   ./infra/yap-server-node/yap-server-setup.sh --check  # report only
#
# The old posture was ten environment variables, a runbook, and a failed
# launch as the error message. This walks every precondition in order,
# CONVERGES what is safe to do for you (venv, directories), PASSES what is
# already right, and lists what genuinely needs a human — with the exact
# commands, filled in for this machine. It never fakes a green: the
# production launch script's own validation still runs at launch and remains
# the authority.
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/../.." && pwd)"
check_only=false
[ "${1:-}" = "--check" ] && check_only=true

pass=0; converged=0; missing=0
say()      { printf '  %-9s %s\n' "$1" "$2"; }
ok()       { say "PASS" "$1"; pass=$((pass+1)); }
did()      { say "CONVERGED" "$1"; converged=$((converged+1)); }
need()     { say "MISSING" "$1"; missing=$((missing+1)); human+=("$2"); }
human=()

echo "yap-server node setup — $(hostname) — repo $repo_root"
echo
echo "software preconditions:"

if command -v git >/dev/null && git -C "$repo_root" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  ok "git worktree at $repo_root"
else
  need "not a git worktree" "clone the repository; the launch gates require an exact clean head"
fi

if command -v uv >/dev/null; then
  ok "uv $(uv --version | awk '{print $2}')"
else
  need "uv is not installed" "install uv: curl -LsSf https://astral.sh/uv/install.sh | sh"
fi

if python3 --version 2>/dev/null | grep -q "3\.12"; then
  ok "python $(python3 --version | awk '{print $2}')"
else
  # uv can supply the interpreter; report rather than block.
  say "NOTE" "system python is not 3.12; uv will manage the interpreter"
fi

if [ -x "$repo_root/server/.venv/bin/python" ] && "$repo_root/server/.venv/bin/python" -c "import jwt, websockets" 2>/dev/null; then
  ok "server virtualenv with dependencies"
elif command -v uv >/dev/null && ! $check_only; then
  (cd "$repo_root/server" && uv sync --extra test >/dev/null 2>&1)
  did "server virtualenv (uv sync)"
else
  need "server virtualenv is missing dependencies" "cd server && uv sync"
fi

if command -v docker >/dev/null && docker info >/dev/null 2>&1; then
  ok "docker daemon reachable"
else
  need "docker daemon is not reachable" "install docker and add this user to the docker group; the LID and ASR workers are containers"
fi

echo
echo "configuration files:"
for lock in server/asr-capabilities.lock.json server/cohere-vllm-serving.lock.json server/lid-component.lock.json; do
  if [ -f "$repo_root/$lock" ]; then
    ok "$lock"
  else
    need "$lock is absent" "restore $lock from the repository; launches refuse to run without it"
  fi
done

echo
echo "runtime state (reported, never invented):"
if [ -n "${YAP_ASR_MODEL_DIR:-}" ] && [ -d "${YAP_ASR_MODEL_DIR:-}" ]; then
  ok "YAP_ASR_MODEL_DIR=$YAP_ASR_MODEL_DIR"
else
  need "YAP_ASR_MODEL_DIR is unset or absent" "place the verified model directory on this node and export YAP_ASR_MODEL_DIR=/path/to/models"
fi
if [ -n "${YAP_BATCH_JOB_STORAGE_DIR:-}" ]; then
  if [ -d "$YAP_BATCH_JOB_STORAGE_DIR" ]; then
    ok "YAP_BATCH_JOB_STORAGE_DIR=$YAP_BATCH_JOB_STORAGE_DIR"
  elif ! $check_only; then
    mkdir -p -m 700 "$YAP_BATCH_JOB_STORAGE_DIR"
    did "created YAP_BATCH_JOB_STORAGE_DIR=$YAP_BATCH_JOB_STORAGE_DIR (mode 700)"
  else
    need "YAP_BATCH_JOB_STORAGE_DIR does not exist" "mkdir -m 700 \"$YAP_BATCH_JOB_STORAGE_DIR\""
  fi
else
  need "YAP_BATCH_JOB_STORAGE_DIR is unset" "export YAP_BATCH_JOB_STORAGE_DIR=/private/yap-jobs (created 700)"
fi
vllm="${YAP_COHERE_VLLM_ENDPOINT:-http://127.0.0.1:18000}"
if curl -sf --max-time 4 -o /dev/null "$vllm/v1/models" 2>/dev/null; then
  ok "vLLM answering at $vllm"
else
  need "no vLLM endpoint at $vllm" "start the ASR serving container: ./infra/yap-server-node/cohere-vllm-server.sh (needs YAP_COHERE_VLLM_API_KEY)"
fi

echo
echo "identity (always a human decision, never converged):"
say "NOTE" "production auth needs the IT Entra app registration; until it exists, the demo identity stack exercises the same shipping auth path:"
say "" "  ./demo/run-demo-identity-provider.py serve && ./demo/run-demo-server.py && ./demo/run-demo-loop.py"

echo
echo "client reachability (per laptop, run ON the laptop):"
say "" "  ssh -o ExitOnForwardFailure=yes -N -T -L 127.0.0.1:18765:127.0.0.1:18765 -L 127.0.0.1:18766:127.0.0.1:18766 -L 127.0.0.1:18790:127.0.0.1:18790 $(hostname)"

echo
echo "summary: $pass pass, $converged converged, $missing missing"
if [ "$missing" -gt 0 ]; then
  echo
  echo "remaining human steps:"
  for step in "${human[@]}"; do echo "  - $step"; done
  exit 1
fi
echo "node is ready as far as software can verify; the launch gates remain the authority."
