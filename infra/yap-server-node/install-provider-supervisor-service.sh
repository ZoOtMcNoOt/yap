#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
unit_template="$script_dir/yap-provider-supervisor@.service.in"
binary_destination=/usr/local/libexec/yap-provider-supervisor
unit_destination=/etc/systemd/system/yap-provider-supervisor@.service

: "${YAP_PROVIDER_OWNER:?Set YAP_PROVIDER_OWNER to the existing non-root model owner}"
: "${YAP_PROVIDER_GROUP:?Set YAP_PROVIDER_GROUP to the existing model-owner group}"
: "${YAP_SUPERVISOR_BINARY:?Set YAP_SUPERVISOR_BINARY to the reviewed Rust binary}"

die() {
  echo "$1" >&2
  exit 1
}

valid_account_name() {
  printf '%s' "$1" | grep -Eq '^[a-z_][a-z0-9_-]*[$]?$'
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
  if [ -L "$binary_destination" ] \
    || { [ -e "$binary_destination" ] && [ ! -f "$binary_destination" ]; }; then
    die "The provider supervisor binary destination must be absent or a regular file"
  fi
  if [ -L "$unit_destination" ] \
    || { [ -e "$unit_destination" ] && [ ! -f "$unit_destination" ]; }; then
    die "The provider supervisor unit destination must be absent or a regular file"
  fi
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

main() {
  validate_inputs
  if [ "$(id -u)" -ne 0 ]; then
    die "Run this installer as root"
  fi

  temporary_unit="$(mktemp)"
  trap 'rm -f -- "$temporary_unit"' EXIT
  render_unit >"$temporary_unit"
  install -d -m 0755 -o root -g root /usr/local/libexec
  install -m 0755 -o root -g root "$YAP_SUPERVISOR_BINARY" "$binary_destination"
  install -d -m 0755 -o root -g root /etc/yap
  install -d -m 0700 -o root -g root /etc/yap/providers
  install -m 0644 -o root -g root "$temporary_unit" "$unit_destination"
  systemctl daemon-reload
  echo "Installed the provider supervisor unit without enabling or starting an instance."
}

main "$@"
