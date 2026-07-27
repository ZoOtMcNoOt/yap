#!/usr/bin/env bash

# Source from a runtime owner. Every member must carry the same per-run token
# before this helper will signal the immutable process-group identity.

yap_process_group_members() {
  local group="$1"
  local inventory
  if ! inventory="$(ps -eo pid=,pgid=,stat=)"; then
    return 1
  fi
  awk -v expected="$group" \
    '$2 == expected && $3 !~ /^Z/ { print $1 }' <<<"$inventory"
}

yap_direct_child_state() {
  local child_pid="$1"
  local expected_parent_pid="$2"
  local owner_token="$3"
  local identity parent_pid state
  if ! identity="$(ps -o ppid=,stat= -p "$child_pid" 2>/dev/null)"; then
    if kill -0 "$child_pid" 2>/dev/null; then
      return 2
    fi
    return 1
  fi
  read -r parent_pid state <<<"$identity"
  if [[ "$state" == Z* ]]; then
    return 1
  fi
  if [ "$parent_pid" != "$expected_parent_pid" ]; then
    return 2
  fi
  if [ ! -r "/proc/$child_pid/environ" ] \
    || ! tr '\0' '\n' <"/proc/$child_pid/environ" 2>/dev/null \
      | grep -Fqx -- "YAP_RUNTIME_OWNER_TOKEN=$owner_token"; then
    if ! kill -0 "$child_pid" 2>/dev/null; then
      return 1
    fi
    return 2
  fi
  return 0
}

verify_token_owned_process_group_members() {
  local group="$1"
  local owner_token="$2"
  local description="$3"
  local members="$4"
  local member current_group current_state current_identity
  while IFS= read -r member; do
    if [[ ! "$member" =~ ^[0-9]+$ ]]; then
      echo "$description process-group ownership could not be verified" >&2
      return 1
    fi
    if [ ! -r "/proc/$member/environ" ] \
      || ! tr '\0' '\n' <"/proc/$member/environ" 2>/dev/null \
        | grep -Fqx -- "YAP_RUNTIME_OWNER_TOKEN=$owner_token"; then
      if ! current_identity="$(
        ps -o pgid=,stat= -p "$member" 2>/dev/null
      )"; then
        if kill -0 "$member" 2>/dev/null; then
          echo "$description process-group ownership could not be verified" >&2
          return 1
        fi
        continue
      fi
      read -r current_group current_state <<<"$current_identity"
      if [ "$current_group" != "$group" ] \
        || [[ "$current_state" == Z* ]]; then
        continue
      fi
      echo "$description process-group ownership could not be verified" >&2
      return 1
    fi
  done <<<"$members"
  return 0
}

stop_owned_child_process_group() {
  local child_pid="$1"
  local owner_token="$2"
  local description="$3"
  local expected_parent_pid="$4"
  local members deadline child_state=0 delegated_status=0
  if [[ ! "$child_pid" =~ ^[0-9]+$ ]] \
    || [[ ! "$expected_parent_pid" =~ ^[0-9]+$ ]]; then
    echo "$description child process identity is invalid" >&2
    return 1
  fi
  if ! members="$(yap_process_group_members "$child_pid")"; then
    echo "$description process-group inventory failed" >&2
    return 1
  fi
  if [ -n "$members" ]; then
    stop_token_owned_process_group \
      "$child_pid" "$owner_token" "$description" \
      || delegated_status="$?"
    if [ "$delegated_status" -ne 0 ]; then
      echo \
        "$description delegated process-group stop failed with status $delegated_status" \
        >&2
      return "$delegated_status"
    fi
    return 0
  fi
  yap_direct_child_state \
    "$child_pid" "$expected_parent_pid" "$owner_token" \
    || child_state="$?"
  if [ "$child_state" -eq 1 ]; then
    return 0
  fi
  if [ "$child_state" -ne 0 ]; then
    echo "$description direct-child ownership could not be verified" >&2
    return 1
  fi
  kill -TERM "$child_pid" 2>/dev/null || true
  deadline=$((SECONDS + 10))
  while true; do
    if ! members="$(yap_process_group_members "$child_pid")"; then
      echo "$description process-group inventory failed" >&2
      return 1
    fi
    if [ -n "$members" ]; then
      stop_token_owned_process_group \
        "$child_pid" "$owner_token" "$description" \
        || return 1
      return 0
    fi
    child_state=0
    yap_direct_child_state \
      "$child_pid" "$expected_parent_pid" "$owner_token" \
      || child_state="$?"
    if [ "$child_state" -eq 1 ]; then
      return 0
    fi
    if [ "$child_state" -ne 0 ]; then
      echo "$description direct-child ownership could not be verified" >&2
      return 1
    fi
    if [ "$SECONDS" -ge "$deadline" ]; then
      kill -KILL "$child_pid" 2>/dev/null || true
      break
    fi
    sleep 0.1
  done
  deadline=$((SECONDS + 5))
  while true; do
    child_state=0
    yap_direct_child_state \
      "$child_pid" "$expected_parent_pid" "$owner_token" \
      || child_state="$?"
    if [ "$child_state" -eq 1 ]; then
      return 0
    fi
    if [ "$child_state" -ne 0 ]; then
      echo "$description direct-child ownership could not be verified" >&2
      return 1
    fi
    if [ "$SECONDS" -ge "$deadline" ]; then
      echo "$description child remained after bounded teardown" >&2
      return 1
    fi
    sleep 0.1
  done
  return 0
}

stop_token_owned_process_group() {
  local group="$1"
  local owner_token="$2"
  local description="$3"
  local members deadline
  if [[ ! "$group" =~ ^[0-9]+$ ]] \
    || [[ ! "$owner_token" =~ ^[0-9a-f]{64}$ ]]; then
    echo "$description process-group identity is invalid" >&2
    return 1
  fi
  if ! members="$(yap_process_group_members "$group")"; then
    echo "$description process-group inventory failed" >&2
    return 1
  fi
  if [ -z "$members" ]; then
    return 0
  fi
  verify_token_owned_process_group_members \
    "$group" "$owner_token" "$description" "$members" \
    || return 1
  kill -TERM -- "-$group" 2>/dev/null || true
  deadline=$((SECONDS + 10))
  while true; do
    if ! members="$(yap_process_group_members "$group")"; then
      echo "$description process-group inventory failed" >&2
      return 1
    fi
    if [ -z "$members" ]; then
      break
    fi
    if [ "$SECONDS" -ge "$deadline" ]; then
      verify_token_owned_process_group_members \
        "$group" "$owner_token" "$description" "$members" \
        || return 1
      kill -KILL -- "-$group" 2>/dev/null || true
      break
    fi
    sleep 0.1
  done
  deadline=$((SECONDS + 5))
  while true; do
    if ! members="$(yap_process_group_members "$group")"; then
      echo "$description process-group inventory failed" >&2
      return 1
    fi
    if [ -z "$members" ]; then
      break
    fi
    if [ "$SECONDS" -ge "$deadline" ]; then
      echo "$description process group remained after bounded teardown" >&2
      return 1
    fi
    sleep 0.1
  done
  return 0
}

stop_recorded_token_owned_process_group() {
  local identity_file="$1"
  local owner_token="$2"
  local description="$3"
  local recorded_group
  if [ -z "$identity_file" ] || [ ! -e "$identity_file" ]; then
    return 0
  fi
  if [ -L "$identity_file" ] || [ ! -f "$identity_file" ]; then
    echo "$description process-group identity is unsafe" >&2
    return 1
  fi
  recorded_group="$(cat -- "$identity_file")"
  if [[ ! "$recorded_group" =~ ^[0-9]+$ ]]; then
    echo "$description process-group identity is invalid" >&2
    return 1
  fi
  stop_token_owned_process_group \
    "$recorded_group" "$owner_token" "$description" \
    || return 1
  rm -f -- "$identity_file"
}
