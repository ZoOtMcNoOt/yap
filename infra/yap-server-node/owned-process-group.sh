#!/usr/bin/env bash

# Source from a runtime owner. New children launch through the retained-pidfd
# supervisor below. Recorded groups remain a crash-recovery boundary: every
# live member must carry the same per-run token before Bash will signal them.

yap_process_group_members() {
  local group="$1"
  local inventory
  if ! inventory="$(ps -eo pid=,pgid=,stat=)"; then
    return 1
  fi
  awk -v expected="$group" \
    '$2 == expected && $3 !~ /^Z/ { print $1 }' <<<"$inventory"
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

_yap_close_owned_process_control() {
  local control_descriptor="$1"
  if [[ ! "$control_descriptor" =~ ^[0-9]+$ ]]; then
    return 1
  fi
  eval "exec ${control_descriptor}>&-"
}

_yap_write_owned_process_control() {
  local control_descriptor="$1"
  local command="$2"
  if [[ ! "$control_descriptor" =~ ^[0-9]+$ ]] \
    || [[ ! "$command" =~ ^(RELEASE|STOP)$ ]]; then
    return 1
  fi
  (
    printf '%s\n' "$command" >&"$control_descriptor"
  ) 2>/dev/null
}

_yap_reap_finished_owned_process_supervisor() {
  local supervisor_pid="$1"
  local description="$2"
  if [[ ! "$supervisor_pid" =~ ^[0-9]+$ ]]; then
    echo "$description owned-process supervisor identity is invalid" >&2
    return 1
  fi
  local deadline=$((SECONDS + 2))
  local identity parent_pid process_state extra
  while [ "$SECONDS" -le "$deadline" ]; do
    if ! identity="$(ps -o ppid=,stat= -p "$supervisor_pid" 2>/dev/null)"; then
      wait "$supervisor_pid" 2>/dev/null || true
      return 0
    fi
    read -r parent_pid process_state extra <<<"$identity"
    if [ "$parent_pid" != "$BASHPID" ] || [ -n "${extra:-}" ]; then
      echo "$description owned-process supervisor parent identity changed" >&2
      return 1
    fi
    if [[ "$process_state" == Z* ]]; then
      wait "$supervisor_pid" 2>/dev/null || true
      return 0
    fi
    sleep 0.05
  done
  echo "$description owned-process supervisor did not exit after its result" >&2
  return 1
}

_yap_read_owned_process_state() {
  local state_file="$1"
  local record version state child_pid start_ticks supervisor_pid observed_at extra
  if [ -L "$state_file" ] || [ ! -f "$state_file" ]; then
    return 1
  fi
  record="$(cat -- "$state_file")" || return 1
  read -r version state child_pid start_ticks supervisor_pid observed_at extra \
    <<<"$record"
  if [ "$version" != "1" ] \
    || [[ ! "$state" =~ ^(bound|ready)$ ]] \
    || [[ ! "$child_pid" =~ ^[0-9]+$ ]] \
    || [[ ! "$start_ticks" =~ ^[0-9]+$ ]] \
    || [[ ! "$supervisor_pid" =~ ^[0-9]+$ ]] \
    || [[ ! "$observed_at" =~ ^[0-9]+$ ]] \
    || [ -n "${extra:-}" ]; then
    return 1
  fi
  printf '%s|%s|%s|%s|%s\n' \
    "$state" "$child_pid" "$start_ticks" "$supervisor_pid" "$observed_at"
}

_yap_read_owned_process_result() {
  local result_file="$1"
  local record version cleanup_status process_status reason extra
  if [ -L "$result_file" ] || [ ! -f "$result_file" ]; then
    return 1
  fi
  record="$(cat -- "$result_file")" || return 1
  read -r version cleanup_status process_status reason extra <<<"$record"
  if [ "$version" != "1" ] \
    || [[ ! "$cleanup_status" =~ ^[0-9]+$ ]] \
    || [[ ! "$process_status" =~ ^[0-9]+$ ]] \
    || [[ ! "$reason" =~ ^[a-z][a-z-]*$ ]] \
    || [ -n "${extra:-}" ]; then
    return 1
  fi
  printf '%s|%s|%s\n' "$cleanup_status" "$process_status" "$reason"
}

yap_recover_owned_process_group() {
  local control_variable="$1"
  local supervisor_pid="$2"
  local expected_child_pid="$3"
  local state_file="$4"
  local result_file="$5"
  local owner_token="$6"
  local description="$7"
  if [[ ! "$control_variable" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] \
    || [[ ! "$supervisor_pid" =~ ^[0-9]+$ ]] \
    || { [ -n "$expected_child_pid" ] \
      && [[ ! "$expected_child_pid" =~ ^[0-9]+$ ]]; } \
    || [[ ! "$owner_token" =~ ^[0-9a-f]{64}$ ]]; then
    echo "$description owned-process recovery identity is invalid" >&2
    return 2
  fi
  local -n owned_process_control_descriptor="$control_variable"
  if [ -n "$owned_process_control_descriptor" ] \
    && [[ ! "$owned_process_control_descriptor" =~ ^[0-9]+$ ]]; then
    echo "$description owned-process control identity is invalid" >&2
    return 2
  fi
  local state_record state recorded_child_pid start_ticks
  local recorded_supervisor observed_at
  if ! state_record="$(_yap_read_owned_process_state "$state_file")"; then
    echo "$description recovery state is unavailable" >&2
    return 1
  fi
  IFS='|' read -r \
    state recorded_child_pid start_ticks recorded_supervisor observed_at \
    <<<"$state_record"
  if [ "$recorded_supervisor" != "$supervisor_pid" ] \
    || { [ -n "$expected_child_pid" ] \
      && [ "$expected_child_pid" != "$recorded_child_pid" ]; }; then
    echo "$description recovery identity changed" >&2
    return 1
  fi
  _yap_reap_finished_owned_process_supervisor \
    "$supervisor_pid" "$description" \
    || return 1
  if [ -n "$owned_process_control_descriptor" ]; then
    _yap_close_owned_process_control "$owned_process_control_descriptor" || true
    owned_process_control_descriptor=""
  fi
  stop_token_owned_process_group \
    "$recorded_child_pid" "$owner_token" "$description recovery" \
    || return 1
  rm -f -- "$state_file" "$result_file"
}

yap_stop_or_recover_owned_process_group() {
  local process_status_variable="$1"
  local control_variable="$2"
  local reap_pid_variable="$3"
  local child_pid_variable="$4"
  local state_file_variable="$5"
  local result_file_variable="$6"
  local owner_token="$7"
  local description="$8"
  for variable_name in \
    "$process_status_variable" \
    "$control_variable" \
    "$reap_pid_variable" \
    "$child_pid_variable" \
    "$state_file_variable" \
    "$result_file_variable"; do
    if [[ ! "$variable_name" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
      echo "$description owned-process lifecycle variable is invalid" >&2
      return 2
    fi
  done
  local -n output_process_status="$process_status_variable"
  local -n owned_process_control_descriptor="$control_variable"
  local -n owned_process_reap_pid="$reap_pid_variable"
  local -n owned_process_child_pid="$child_pid_variable"
  local -n owned_process_state_file="$state_file_variable"
  local -n owned_process_result_file="$result_file_variable"
  if [ -z "$owned_process_reap_pid" ]; then
    return 0
  fi

  output_process_status=125
  local lifecycle_status=0
  if [ -z "$owned_process_control_descriptor" ]; then
    lifecycle_status=1
    yap_recover_owned_process_group \
      "$control_variable" \
      "$owned_process_reap_pid" \
      "$owned_process_child_pid" \
      "$owned_process_state_file" \
      "$owned_process_result_file" \
      "$owner_token" \
      "$description" \
      || return 1
  elif [ -n "$owned_process_child_pid" ]; then
    if ! yap_stop_owned_process_group \
      "$process_status_variable" \
      "$control_variable" \
      "$owned_process_reap_pid" \
      "$owned_process_child_pid" \
      "$owned_process_state_file" \
      "$owned_process_result_file" \
      "$description"; then
      lifecycle_status=1
      yap_recover_owned_process_group \
        "$control_variable" \
        "$owned_process_reap_pid" \
        "$owned_process_child_pid" \
        "$owned_process_state_file" \
        "$owned_process_result_file" \
        "$owner_token" \
        "$description" \
        || return 1
    fi
  elif ! yap_abort_owned_process_start \
    "$control_variable" \
    "$owned_process_reap_pid" \
    "$owned_process_state_file" \
    "$owned_process_result_file" \
    "$description"; then
    lifecycle_status=1
    yap_recover_owned_process_group \
      "$control_variable" \
      "$owned_process_reap_pid" \
      "$owned_process_child_pid" \
      "$owned_process_state_file" \
      "$owned_process_result_file" \
      "$owner_token" \
      "$description" \
      || return 1
  fi
  owned_process_child_pid=""
  owned_process_reap_pid=""
  owned_process_control_descriptor=""
  owned_process_state_file=""
  owned_process_result_file=""
  return "$lifecycle_status"
}

_yap_wait_for_owned_process_record() {
  local state_file="$1"
  local result_file="$2"
  local expected_state="$3"
  local timeout_seconds="$4"
  local description="$5"
  local deadline=$((SECONDS + timeout_seconds))
  local state_record state
  while [ "$SECONDS" -le "$deadline" ]; do
    if state_record="$(_yap_read_owned_process_state "$state_file")"; then
      IFS='|' read -r state _ <<<"$state_record"
      if [ "$state" = "$expected_state" ]; then
        printf '%s\n' "$state_record"
        return 0
      fi
    fi
    if [ -e "$result_file" ]; then
      echo "$description exited before $expected_state ownership" >&2
      return 1
    fi
    sleep 0.01
  done
  echo "$description did not publish $expected_state ownership" >&2
  return 1
}

yap_abort_owned_process_start() {
  local control_variable="$1"
  local supervisor_pid="$2"
  local state_file="$3"
  local result_file="$4"
  local description="$5"
  if [[ ! "$control_variable" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
    echo "$description owned-process control variable is invalid" >&2
    return 2
  fi
  local -n owned_process_control_descriptor="$control_variable"
  local control_descriptor="$owned_process_control_descriptor"
  if [[ ! "$control_descriptor" =~ ^[0-9]+$ ]]; then
    echo "$description owned-process control identity is invalid" >&2
    return 2
  fi
  _yap_write_owned_process_control "$control_descriptor" STOP || true
  local result_record cleanup_status process_status reason
  if ! result_record="$(
    _yap_wait_for_owned_process_result "$result_file" 18 "$description"
  )"; then
    return 1
  fi
  _yap_close_owned_process_control "$control_descriptor" || true
  owned_process_control_descriptor=""
  _yap_reap_finished_owned_process_supervisor \
    "$supervisor_pid" "$description" \
    || return 1
  IFS='|' read -r cleanup_status process_status reason <<<"$result_record"
  if [ "$cleanup_status" -ne 0 ]; then
    return 1
  fi
  local state_record state child_pid start_ticks recorded_supervisor observed_at
  local remaining
  if state_record="$(_yap_read_owned_process_state "$state_file")"; then
    IFS='|' read -r \
      state child_pid start_ticks recorded_supervisor observed_at \
      <<<"$state_record"
    if ! remaining="$(yap_process_group_members "$child_pid")" \
      || [ -n "$remaining" ]; then
      return 1
    fi
  fi
  rm -f -- "$state_file" "$result_file"
}

yap_start_owned_process_group() {
  local control_variable="$1"
  local reap_pid_variable="$2"
  local child_pid_variable="$3"
  local state_file="$4"
  local result_file="$5"
  local stdout_path="$6"
  local stderr_path="$7"
  local owner_token="$8"
  local description="$9"
  shift 9
  if [ "${1:-}" != "--" ]; then
    echo "$description owned-process command separator is missing" >&2
    return 2
  fi
  shift
  if [ "$#" -eq 0 ]; then
    echo "$description owned-process command is missing" >&2
    return 2
  fi
  for variable_name in \
    "$control_variable" "$reap_pid_variable" "$child_pid_variable"; do
    if [[ ! "$variable_name" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
      echo "$description owned-process output variable is invalid" >&2
      return 2
    fi
  done
  local -n output_control_descriptor="$control_variable"
  local -n output_reap_pid="$reap_pid_variable"
  local -n output_child_pid="$child_pid_variable"
  if [[ ! "$owner_token" =~ ^[0-9a-f]{64}$ ]] \
    || [ -z "$state_file" ] \
    || [ -z "$result_file" ] \
    || [ -e "$state_file" ] \
    || [ -L "$state_file" ] \
    || [ -e "$result_file" ] \
    || [ -L "$result_file" ]; then
    echo "$description owned-process launch identity is invalid" >&2
    return 2
  fi
  local supervisor_python="/usr/bin/python3.12"
  if [ -L "$supervisor_python" ] \
    || [ ! -x "$supervisor_python" ] \
    || [ "$(
      "$supervisor_python" -I -S -c \
        'import sys; print(".".join(map(str, sys.version_info[:2])))'
    )" != "3.12" ]; then
    echo "$description owned-process launch requires system Python 3.12" >&2
    return 2
  fi
  local helper_directory supervisor_path
  helper_directory="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
  supervisor_path="$helper_directory/owned-process-supervisor.py"
  if [ -L "$supervisor_path" ] || [ ! -f "$supervisor_path" ]; then
    echo "$description owned-process supervisor is unavailable" >&2
    return 2
  fi

  local control_descriptor supervisor_pid
  exec {control_descriptor}> >(
    YAP_RUNTIME_OWNER_TOKEN="$owner_token" \
      exec "$supervisor_python" \
        -I \
        -S \
        "$supervisor_path" \
        --state-file "$state_file" \
        --result-file "$result_file" \
        --description "$description" \
        --stdout-path "$stdout_path" \
        --stderr-path "$stderr_path" \
        -- "$@"
  )
  supervisor_pid="$!"
  output_control_descriptor="$control_descriptor"
  output_reap_pid="$supervisor_pid"
  output_child_pid=""

  local state_record state observed_child_pid start_ticks
  local recorded_supervisor observed_at
  if ! state_record="$(
    _yap_wait_for_owned_process_record \
      "$state_file" "$result_file" bound 6 "$description"
  )"; then
    if yap_abort_owned_process_start \
      "$control_variable" "$supervisor_pid" \
      "$state_file" "$result_file" "$description"; then
      output_reap_pid=""
      output_child_pid=""
    fi
    return 1
  fi
  IFS='|' read -r \
    state observed_child_pid start_ticks recorded_supervisor observed_at \
    <<<"$state_record"
  if [ "$recorded_supervisor" != "$supervisor_pid" ]; then
    echo "$description owned-process supervisor identity changed" >&2
    if yap_abort_owned_process_start \
      "$control_variable" "$supervisor_pid" \
      "$state_file" "$result_file" "$description"; then
      output_reap_pid=""
      output_child_pid=""
    fi
    return 1
  fi
  output_child_pid="$observed_child_pid"
  if ! _yap_write_owned_process_control "$control_descriptor" RELEASE; then
    echo "$description owned-process release failed" >&2
    if yap_abort_owned_process_start \
      "$control_variable" "$supervisor_pid" \
      "$state_file" "$result_file" "$description"; then
      output_reap_pid=""
      output_child_pid=""
    fi
    return 1
  fi
  if ! state_record="$(
    _yap_wait_for_owned_process_record \
      "$state_file" "$result_file" ready 6 "$description"
  )"; then
    if yap_abort_owned_process_start \
      "$control_variable" "$supervisor_pid" \
      "$state_file" "$result_file" "$description"; then
      output_reap_pid=""
      output_child_pid=""
    fi
    return 1
  fi
  IFS='|' read -r \
    state observed_child_pid start_ticks recorded_supervisor observed_at \
    <<<"$state_record"
  if [ "$recorded_supervisor" != "$supervisor_pid" ] \
    || [ "$observed_child_pid" != "$output_child_pid" ]; then
    echo "$description ready ownership identity changed" >&2
    if yap_abort_owned_process_start \
      "$control_variable" "$supervisor_pid" \
      "$state_file" "$result_file" "$description"; then
      output_reap_pid=""
      output_child_pid=""
    fi
    return 1
  fi
}

_yap_wait_for_owned_process_result() {
  local result_file="$1"
  local timeout_seconds="$2"
  local description="$3"
  local deadline=$((SECONDS + timeout_seconds))
  local result_record
  while [ "$SECONDS" -le "$deadline" ]; do
    if result_record="$(_yap_read_owned_process_result "$result_file")"; then
      printf '%s\n' "$result_record"
      return 0
    fi
    sleep 0.05
  done
  echo "$description did not publish a bounded cleanup result" >&2
  return 1
}

yap_stop_owned_process_group() {
  local process_status_variable="$1"
  local control_variable="$2"
  local supervisor_pid="$3"
  local child_pid="$4"
  local state_file="$5"
  local result_file="$6"
  local description="$7"
  if [[ ! "$process_status_variable" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] \
    || [[ ! "$control_variable" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] \
    || [[ ! "$supervisor_pid" =~ ^[0-9]+$ ]] \
    || [[ ! "$child_pid" =~ ^[0-9]+$ ]]; then
    echo "$description owned-process stop identity is invalid" >&2
    return 2
  fi
  local -n output_process_status="$process_status_variable"
  local -n owned_process_control_descriptor="$control_variable"
  local control_descriptor="$owned_process_control_descriptor"
  if [[ ! "$control_descriptor" =~ ^[0-9]+$ ]]; then
    echo "$description owned-process control identity is invalid" >&2
    return 2
  fi
  output_process_status=125
  _yap_write_owned_process_control "$control_descriptor" STOP || true
  local result_record cleanup_status observed_process_status reason
  if ! result_record="$(
    _yap_wait_for_owned_process_result "$result_file" 18 "$description"
  )"; then
    return 1
  fi
  _yap_close_owned_process_control "$control_descriptor" || true
  owned_process_control_descriptor=""
  IFS='|' read -r \
    cleanup_status observed_process_status reason \
    <<<"$result_record"
  _yap_reap_finished_owned_process_supervisor \
    "$supervisor_pid" "$description" \
    || return 1
  output_process_status="$observed_process_status"
  if [ "$cleanup_status" -ne 0 ]; then
    echo "$description owned-process cleanup was not proven" >&2
    return 1
  fi
  local remaining
  if ! remaining="$(yap_process_group_members "$child_pid")" \
    || [ -n "$remaining" ]; then
    echo "$description process group remained after supervisor cleanup" >&2
    return 1
  fi
  rm -f -- "$state_file" "$result_file"
}

yap_wait_owned_process_group() {
  local process_status_variable="$1"
  local control_variable="$2"
  local supervisor_pid="$3"
  local child_pid="$4"
  local state_file="$5"
  local result_file="$6"
  local timeout_seconds="$7"
  local description="$8"
  if [[ ! "$process_status_variable" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] \
    || [[ ! "$control_variable" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] \
    || [[ ! "$supervisor_pid" =~ ^[0-9]+$ ]] \
    || [[ ! "$child_pid" =~ ^[0-9]+$ ]] \
    || [[ ! "$timeout_seconds" =~ ^[0-9]+$ ]]; then
    echo "$description owned-process wait identity is invalid" >&2
    return 2
  fi
  local -n output_process_status="$process_status_variable"
  local -n owned_process_control_descriptor="$control_variable"
  local control_descriptor="$owned_process_control_descriptor"
  if [[ ! "$control_descriptor" =~ ^[0-9]+$ ]]; then
    echo "$description owned-process control identity is invalid" >&2
    return 2
  fi
  output_process_status=125
  local result_record cleanup_status observed_process_status reason
  if ! result_record="$(
    _yap_wait_for_owned_process_result \
      "$result_file" "$timeout_seconds" "$description"
  )"; then
    return 124
  fi
  _yap_close_owned_process_control "$control_descriptor" || true
  owned_process_control_descriptor=""
  _yap_reap_finished_owned_process_supervisor \
    "$supervisor_pid" "$description" \
    || return 1
  IFS='|' read -r \
    cleanup_status observed_process_status reason \
    <<<"$result_record"
  output_process_status="$observed_process_status"
  if [ "$cleanup_status" -ne 0 ]; then
    echo "$description owned-process exit cleanup was not proven" >&2
    return 1
  fi
  local remaining
  if ! remaining="$(yap_process_group_members "$child_pid")" \
    || [ -n "$remaining" ]; then
    echo "$description process group remained after supervisor exit" >&2
    return 1
  fi
  rm -f -- "$state_file" "$result_file"
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
