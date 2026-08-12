#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
repository_root="$(cd -- "$script_dir/../.." && pwd -P)"
unit_template="$script_dir/yap-agent-admission-broker.service.in"
binary_destination=/usr/local/libexec/yap-agent-admission-broker
unit_destination=/etc/systemd/system/yap-agent-admission-broker.service
profile_source_root="$repository_root/server/agent-service-profiles"
profile_destination_root=/usr/local/share/yap/agent-service-profiles
candidate_lock_source="$repository_root/server/agent-reasoning-candidates.lock.json"
candidate_lock_destination=/usr/local/share/yap/agent-reasoning-candidates.lock.json

: "${YAP_PROVIDER_OWNER:?Set YAP_PROVIDER_OWNER to the existing non-root model owner}"
: "${YAP_PROVIDER_GROUP:?Set YAP_PROVIDER_GROUP to the existing model-owner group}"
: "${YAP_ADMISSION_BROKER_BINARY:?Set YAP_ADMISSION_BROKER_BINARY to the reviewed Rust broker}"
: "${YAP_CHECKED_HEAD:?Set YAP_CHECKED_HEAD to the exact release commit}"

die() {
  echo "$1" >&2
  exit 1
}

valid_account_name() {
  printf '%s' "$1" | grep -Eq '^[a-z_][a-z0-9_-]*[$]?$'
}

require_regular_file() {
  local path="$1"
  local description="$2"
  if [ -L "$path" ] || [ ! -f "$path" ]; then
    die "$description must be a real file"
  fi
}

validate_inputs() {
  valid_account_name "$YAP_PROVIDER_OWNER" || die "YAP_PROVIDER_OWNER is invalid"
  valid_account_name "$YAP_PROVIDER_GROUP" || die "YAP_PROVIDER_GROUP is invalid"
  id "$YAP_PROVIDER_OWNER" >/dev/null 2>&1 \
    || die "YAP_PROVIDER_OWNER must already exist"
  getent group "$YAP_PROVIDER_GROUP" >/dev/null 2>&1 \
    || die "YAP_PROVIDER_GROUP must already exist"
  if [ "$(id -u "$YAP_PROVIDER_OWNER")" -eq 0 ]; then
    die "YAP_PROVIDER_OWNER must be non-root"
  fi
  case "$YAP_ADMISSION_BROKER_BINARY" in
    /*) ;;
    *) die "YAP_ADMISSION_BROKER_BINARY must be absolute" ;;
  esac
  require_regular_file "$YAP_ADMISSION_BROKER_BINARY" "Admission broker binary"
  [ -x "$YAP_ADMISSION_BROKER_BINARY" ] \
    || die "Admission broker binary must be executable"
  require_regular_file "$unit_template" "Admission broker unit template"
  if [[ ! "$YAP_CHECKED_HEAD" =~ ^[0-9a-f]{40}$ ]]; then
    die "YAP_CHECKED_HEAD must be one full lowercase Git SHA"
  fi
  if ! command -v git >/dev/null 2>&1 \
    || [ "$(git -C "$repository_root" rev-parse --show-toplevel)" != "$repository_root" ] \
    || [ "$(git -C "$repository_root" rev-parse HEAD)" != "$YAP_CHECKED_HEAD" ] \
    || [ -n "$(git -C "$repository_root" status --porcelain=v1 --untracked-files=all)" ]; then
    die "admission service installation requires the exact clean checked repository"
  fi
  for source in \
    "$profile_source_root/rapid-automation.json" \
    "$profile_source_root/complex-orchestration.json" \
    "$candidate_lock_source"; do
    require_regular_file "$source" "Admission identity source"
  done
  for installed in \
    "$profile_destination_root/rapid-automation.json" \
    "$profile_destination_root/complex-orchestration.json" \
    "$candidate_lock_destination"; do
    require_regular_file "$installed" "Installed provider identity"
  done
  cmp -s "$profile_source_root/rapid-automation.json" "$profile_destination_root/rapid-automation.json" \
    || die "Installed rapid profile differs from the checked source"
  cmp -s "$profile_source_root/complex-orchestration.json" "$profile_destination_root/complex-orchestration.json" \
    || die "Installed complex profile differs from the checked source"
  cmp -s "$candidate_lock_source" "$candidate_lock_destination" \
    || die "Installed candidate lock differs from the checked source"
  for destination in "$binary_destination" "$unit_destination"; do
    if [ -L "$destination" ] || { [ -e "$destination" ] && [ ! -f "$destination" ]; }; then
      die "Admission service destination is unsafe"
    fi
  done
}

render_unit() {
  local rendered
  local rapid_sha256
  local complex_sha256
  rapid_sha256="$(sha256sum "$profile_source_root/rapid-automation.json" | awk '{print $1}')"
  complex_sha256="$(sha256sum "$profile_source_root/complex-orchestration.json" | awk '{print $1}')"
  rendered="$(<"$unit_template")"
  rendered="${rendered//@YAP_PROVIDER_OWNER@/$YAP_PROVIDER_OWNER}"
  rendered="${rendered//@YAP_PROVIDER_GROUP@/$YAP_PROVIDER_GROUP}"
  rendered="${rendered//@YAP_RAPID_PROFILE_SHA256@/$rapid_sha256}"
  rendered="${rendered//@YAP_COMPLEX_PROFILE_SHA256@/$complex_sha256}"
  if grep -q '@YAP_' <<<"$rendered"; then
    die "Admission broker unit template was not fully rendered"
  fi
  printf '%s\n' "$rendered"
}

main() {
  validate_inputs
  if [ "$(id -u)" -ne 0 ]; then
    die "Run this installer as root"
  fi
  temporary_unit="$(mktemp)"
  trap 'rm -f -- "${temporary_unit:-}"' EXIT
  render_unit >"$temporary_unit"
  install -d -m 0755 -o root -g root /usr/local/libexec
  install -m 0755 -o root -g root "$YAP_ADMISSION_BROKER_BINARY" "$binary_destination"
  install -m 0644 -o root -g root "$temporary_unit" "$unit_destination"
  systemctl daemon-reload
  echo "Installed the owner-private agent admission broker without enabling or starting it."
}

main "$@"
