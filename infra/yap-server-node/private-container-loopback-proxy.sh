#!/usr/bin/env bash

# Source this helper from a checked provider launcher. The model container stays
# on an egress-blocked Docker internal bridge; one bounded host process group
# exposes only its service port on numeric IPv4 loopback.

resolve_private_container_socat_executable() {
  local socat_command socat_path
  if ! socat_command="$(command -v socat)"; then
    return 1
  fi
  if [[ "$socat_command" != /* ]] \
    || ! socat_path="$(readlink -f -- "$socat_command")" \
    || [[ "$socat_path" != /* ]] \
    || [ -L "$socat_path" ] \
    || [ ! -f "$socat_path" ] \
    || [ ! -x "$socat_path" ]; then
    return 1
  fi
  printf '%s\n' "$socat_path"
}

stop_private_loopback_proxy_process_group() {
  local process_status_variable="$1"
  local control_variable="$2"
  local reap_pid_variable="$3"
  local child_pid_variable="$4"
  local state_file_variable="$5"
  local result_file_variable="$6"
  local group_file="$7"
  local owner_token="$8"
  if [[ ! "$reap_pid_variable" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
    echo "Private loopback proxy reap variable is invalid" >&2
    return 2
  fi
  local -n proxy_reap_pid="$reap_pid_variable"
  local lifecycle_status=0
  if yap_stop_or_recover_owned_process_group \
    "$process_status_variable" \
    "$control_variable" \
    "$reap_pid_variable" \
    "$child_pid_variable" \
    "$state_file_variable" \
    "$result_file_variable" \
    "$owner_token" \
    "Private loopback proxy"; then
    lifecycle_status=0
  else
    lifecycle_status="$?"
  fi
  if [ -z "$proxy_reap_pid" ]; then
    rm -f -- "$group_file" "$group_file.part"
  fi
  return "$lifecycle_status"
}

run_private_container_with_loopback_proxy() {
  set -euo pipefail
  if [ "$#" -lt 11 ] || [ "$7" != "--" ]; then
    echo "private container proxy arguments are invalid" >&2
    return 2
  fi
  local container_name="$1"
  local network_name="$2"
  local host_port="$3"
  local container_port="$4"
  local owner_token="$5"
  local proxy_group_file="$6"
  shift 7
  if [ "$1" != "docker" ] \
    || [ "$2" != "container" ] \
    || [ "$3" != "create" ]; then
    echo "private container proxy requires an explicit Docker create command" >&2
    return 2
  fi
  shift 3
  local -a container_create_arguments=("$@")
  local argument
  for argument in "${container_create_arguments[@]}"; do
    if [ "$argument" = "--cidfile" ] || [[ "$argument" == --cidfile=* ]]; then
      echo "private container proxy owns the Docker identity file" >&2
      return 2
    fi
  done

  if [[ ! "$container_name" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$ ]] \
    || [[ ! "$network_name" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$ ]]; then
    echo "private container or network name is invalid" >&2
    return 2
  fi
  for port in "$host_port" "$container_port"; do
    if [[ ! "$port" =~ ^[0-9]+$ ]] \
      || [ "$port" -lt 1 ] \
      || [ "$port" -gt 65535 ]; then
      echo "private container proxy port is invalid" >&2
      return 2
    fi
  done
  if [[ ! "$owner_token" =~ ^[0-9a-f]{64}$ ]]; then
    echo "private container proxy owner token is invalid" >&2
    return 2
  fi
  local proxy_group_parent
  local proxy_state_file="$proxy_group_file.supervisor-state"
  local proxy_result_file="$proxy_group_file.supervisor-result"
  local container_recovery_file="$proxy_group_file.container-recovery"
  local container_id_file="$proxy_group_file.container-id"
  proxy_group_parent="$(dirname -- "$proxy_group_file")"
  if [ ! -d "$proxy_group_parent" ] \
    || [ -L "$proxy_group_parent" ] \
    || [ -e "$proxy_group_file" ] \
    || [ -L "$proxy_group_file" ] \
    || [ -e "$proxy_group_file.part" ] \
    || [ -L "$proxy_group_file.part" ] \
    || [ -e "$proxy_state_file" ] \
    || [ -L "$proxy_state_file" ] \
    || [ -e "$proxy_result_file" ] \
    || [ -L "$proxy_result_file" ] \
    || [ -e "$container_recovery_file" ] \
    || [ -L "$container_recovery_file" ] \
    || [ -e "$container_recovery_file.part" ] \
    || [ -L "$container_recovery_file.part" ] \
    || [ -e "$container_id_file" ] \
    || [ -L "$container_id_file" ]; then
    echo "private proxy process-group identity path is unsafe" >&2
    return 2
  fi
  for program in docker env python3.12 readlink socat ss ps timeout; do
    if ! command -v "$program" >/dev/null 2>&1; then
      echo "private container proxy requires $program" >&2
      return 2
    fi
  done
  local socat_path
  if ! socat_path="$(resolve_private_container_socat_executable)"; then
    echo "private container proxy requires a real socat executable" >&2
    return 2
  fi
  if ss -H -ltn "sport = :$host_port" | grep -q .; then
    echo "private loopback proxy port is already owned" >&2
    return 2
  fi

  _yap_proxy_pid=""
  _yap_proxy_reap_pid=""
  _yap_proxy_control_fd=""
  _yap_proxy_state_file="$proxy_state_file"
  _yap_proxy_result_file="$proxy_result_file"
  _yap_container_id=""
  _yap_container_identity_bound=false
  _yap_container_name="$container_name"
  _yap_host_port="$host_port"
  _yap_owner_token="$owner_token"
  _yap_container_recovery_file="$container_recovery_file"
  _yap_container_id_file="$container_id_file"
  _yap_proxy_group_file="$proxy_group_file"
  _yap_requested_exit=0

  private_loopback_proxy_stop_group() {
    local process_status=125
    stop_private_loopback_proxy_process_group \
      process_status \
      _yap_proxy_control_fd \
      _yap_proxy_reap_pid \
      _yap_proxy_pid \
      _yap_proxy_state_file \
      _yap_proxy_result_file \
      "$_yap_proxy_group_file" \
      "$_yap_owner_token"
  }

  private_loopback_proxy_capture_owned_container_reference() {
    local reference="$1"
    local reference_kind="$2"
    local identity inspected_id inspected_token inspected_name extra
    if [ "$reference_kind" != name ] && [ "$reference_kind" != id ]; then
      echo "private provider container reference kind is invalid" >&2
      return 2
    fi
    if ! identity="$(
      timeout --signal=KILL 1s \
        docker container inspect \
          --format '{{.Id}}|{{index .Config.Labels "io.yap.run-token"}}|{{.Name}}' \
          "$reference" 2>/dev/null
    )"; then
      local inventory
      if ! inventory="$(
        timeout --signal=KILL 1s \
          docker container ls \
            --all \
            --no-trunc \
            --format '{{.ID}}|{{.Names}}' 2>/dev/null
      )"; then
        echo "private provider container absence could not be verified" >&2
        return 2
      fi
      if [ "$reference_kind" = name ]; then
        if awk -F '|' -v expected="$_yap_container_name" \
          '$2 == expected { found=1 } END { exit !found }' <<<"$inventory"; then
          echo "private provider container exists but could not be inspected" >&2
          return 2
        fi
      else
        if awk -F '|' \
          -v expected_id="$reference" \
          -v expected_name="$_yap_container_name" \
          '$1 == expected_id && $2 != expected_name { found=1 }
           END { exit !found }' <<<"$inventory"; then
          echo "private provider container ID has an unexpected name" >&2
          return 2
        fi
        if awk -F '|' \
          -v expected_id="$reference" \
          -v expected_name="$_yap_container_name" \
          '$1 == expected_id && $2 == expected_name { found=1 }
           END { exit !found }' \
          <<<"$inventory"; then
          echo "private provider container ID exists but could not be inspected" >&2
          return 3
        fi
        if awk -F '|' -v expected_name="$_yap_container_name" \
          '$2 == expected_name { found=1 } END { exit !found }' \
          <<<"$inventory"; then
          echo "private provider container name belongs to another ID" >&2
          return 2
        fi
      fi
      return 1
    fi
    IFS='|' read -r inspected_id inspected_token inspected_name extra \
      <<<"$identity"
    if [[ ! "$inspected_id" =~ ^[0-9a-f]{64}$ ]] \
      || [ "$inspected_token" != "$_yap_owner_token" ] \
      || [ "$inspected_name" != "/$_yap_container_name" ] \
      || [ -n "${extra:-}" ] \
      || { [ -n "$_yap_container_id" ] \
        && [ "$_yap_container_id" != "$inspected_id" ]; }; then
      echo "private provider container ownership could not be verified" >&2
      return 2
    fi
    _yap_container_id="$inspected_id"
    _yap_container_identity_bound=true
  }

  private_loopback_proxy_capture_owned_container_by_name() {
    private_loopback_proxy_capture_owned_container_reference \
      "$_yap_container_name" \
      name
  }

  private_loopback_proxy_verify_owned_container_id() {
    if [[ ! "$_yap_container_id" =~ ^[0-9a-f]{64}$ ]]; then
      echo "private provider container identity is invalid" >&2
      return 2
    fi
    private_loopback_proxy_capture_owned_container_reference \
      "$_yap_container_id" \
      id
  }

  private_loopback_proxy_publish_container_recovery() {
    local state="$1"
    local container_id="${2:--}"
    (
      umask 077
      printf '1 %s %s %s %s\n' \
        "$state" \
        "$_yap_container_name" \
        "$_yap_owner_token" \
        "$container_id" \
        >"$_yap_container_recovery_file.part"
      mv -- \
        "$_yap_container_recovery_file.part" \
        "$_yap_container_recovery_file"
    )
  }

  private_loopback_proxy_read_container_id_file() {
    local -a identity_lines=()
    if [ -L "$_yap_container_id_file" ]; then
      echo "private provider container identity file is unsafe" >&2
      return 2
    fi
    if [ ! -e "$_yap_container_id_file" ]; then
      return 1
    fi
    if [ ! -f "$_yap_container_id_file" ]; then
      echo "private provider container identity file is unsafe" >&2
      return 2
    fi
    mapfile -t identity_lines <"$_yap_container_id_file"
    if [ "${#identity_lines[@]}" -ne 1 ] \
      || [[ ! "${identity_lines[0]}" =~ ^[0-9a-f]{64}$ ]]; then
      echo "private provider container identity file is invalid" >&2
      return 2
    fi
    _yap_container_id="${identity_lines[0]}"
  }

  private_loopback_proxy_retire_container_recovery() {
    if ! rm -f -- \
      "$_yap_container_recovery_file" \
      "$_yap_container_recovery_file.part" \
      "$_yap_container_id_file"; then
      echo "private provider container recovery records could not be retired" >&2
      return 1
    fi
  }

  private_loopback_proxy_stop_container() {
    local capture_status=0
    if [ -z "$_yap_container_id" ]; then
      if private_loopback_proxy_read_container_id_file; then
        :
      else
        capture_status="$?"
        if [ "$capture_status" -ne 1 ]; then
          return 1
        fi
      fi
    fi
    if [ -n "$_yap_container_id" ]; then
      if private_loopback_proxy_verify_owned_container_id; then
        private_loopback_proxy_publish_container_recovery \
          created \
          "$_yap_container_id"
      else
        capture_status="$?"
        if [ "$capture_status" -eq 1 ]; then
          _yap_container_id=""
          _yap_container_identity_bound=false
          if ! private_loopback_proxy_retire_container_recovery; then
            return 1
          fi
          return 0
        fi
        if [ "$capture_status" -ne 3 ] \
          || [ "$_yap_container_identity_bound" != true ]; then
          return 1
        fi
      fi
    elif private_loopback_proxy_capture_owned_container_by_name; then
      private_loopback_proxy_publish_container_recovery \
        created \
        "$_yap_container_id"
    else
      capture_status="$?"
      if [ "$capture_status" -eq 1 ]; then
        echo "private provider container creation outcome remains unproven; recovery identity retained" >&2
      fi
      return 1
    fi

    # The ID was captured only after name/token verification and is immutable.
    # Target it even if a later Docker ownership probe stalls; a foreign
    # replacement at the fixed name is never used as a teardown target.
    timeout --signal=KILL 1s docker logs "$_yap_container_id" || true
    timeout --signal=KILL 2s \
      docker stop --time 1 "$_yap_container_id" >/dev/null 2>&1 || true
    timeout --signal=KILL 2s \
      docker rm --force "$_yap_container_id" >/dev/null 2>&1 || true

    if private_loopback_proxy_verify_owned_container_id; then
      echo "private provider container remained after bounded teardown" >&2
      return 1
    else
      capture_status="$?"
    fi
    if [ "$capture_status" -ne 1 ]; then
      return 1
    fi
    _yap_container_id=""
    _yap_container_identity_bound=false
    private_loopback_proxy_retire_container_recovery
  }

  private_loopback_proxy_cleanup() {
    local cleanup_status=0
    private_loopback_proxy_stop_container || cleanup_status=1
    private_loopback_proxy_stop_group || cleanup_status=1
    if ss -H -ltn "sport = :$_yap_host_port" | grep -q .; then
      echo "private loopback proxy listener remained after teardown" >&2
      cleanup_status=1
    fi
    return "$cleanup_status"
  }

  # Invoked indirectly through the traps installed below.
  # shellcheck disable=SC2317
  private_loopback_proxy_exit() {
    local original_status="$?"
    trap - EXIT HUP INT TERM
    if ! private_loopback_proxy_cleanup && [ "$original_status" -eq 0 ]; then
      original_status=1
    fi
    exit "$original_status"
  }

  # Invoked indirectly through the traps installed below.
  # shellcheck disable=SC2317
  private_loopback_proxy_request_stop() {
    _yap_requested_exit="$1"
    exit "$_yap_requested_exit"
  }

  trap private_loopback_proxy_exit EXIT
  trap 'private_loopback_proxy_request_stop 129' HUP
  trap 'private_loopback_proxy_request_stop 130' INT
  trap 'private_loopback_proxy_request_stop 143' TERM

  if [ "$_yap_requested_exit" -ne 0 ]; then
    return "$_yap_requested_exit"
  fi
  private_loopback_proxy_publish_container_recovery create-pending
  local reported_container_id="" container_create_status=0
  if reported_container_id="$(
    docker container create \
      --cidfile "$_yap_container_id_file" \
      "${container_create_arguments[@]}"
  )"; then
    container_create_status=0
  else
    container_create_status="$?"
  fi
  local container_id_file_status=0
  if private_loopback_proxy_read_container_id_file; then
    container_id_file_status=0
  else
    container_id_file_status="$?"
  fi
  if [ "$container_id_file_status" -eq 2 ]; then
    return 1
  fi
  if [[ "$reported_container_id" =~ ^[0-9a-f]{64}$ ]]; then
    if [ -n "$_yap_container_id" ] \
      && [ "$_yap_container_id" != "$reported_container_id" ]; then
      echo "private provider container identity is inconsistent" >&2
      return 1
    fi
    _yap_container_id="$reported_container_id"
  fi
  if ! private_loopback_proxy_capture_owned_container_by_name; then
    _yap_container_id=""
    _yap_container_identity_bound=false
    if [ "$container_create_status" -ne 0 ]; then
      echo "private provider container failed to create" >&2
    else
      echo "private provider container identity is invalid" >&2
    fi
    return 1
  fi
  private_loopback_proxy_publish_container_recovery \
    created \
    "$_yap_container_id"
  if [ "$container_create_status" -ne 0 ]; then
    echo "private provider container create command reported failure" >&2
    return 1
  fi
  if ! docker container start "$_yap_container_id" >/dev/null; then
    echo "private provider container failed to start" >&2
    return 1
  fi
  if ! private_loopback_proxy_verify_owned_container_id; then
    echo "private provider container identity is invalid" >&2
    return 1
  fi
  private_loopback_proxy_publish_container_recovery \
    started \
    "$_yap_container_id"

  local deadline=$((SECONDS + 30))
  local container_ip=""
  while [ "$SECONDS" -lt "$deadline" ]; do
    local running_state=""
    if ! running_state="$(
      timeout --signal=KILL 1s \
        docker container inspect \
          --format '{{.State.Running}}' \
          "$_yap_container_id" 2>/dev/null
    )"; then
      echo "private provider container state could not be inspected" >&2
      return 1
    fi
    if [ "$running_state" != "true" ]; then
      local running_capture_status=0
      if private_loopback_proxy_verify_owned_container_id; then
        running_capture_status=0
      else
        running_capture_status="$?"
      fi
      if [ "$running_capture_status" -eq 1 ]; then
        echo "private provider container exited before proxy startup" >&2
        return 1
      fi
      if [ "$running_capture_status" -ne 0 ]; then
        echo "private provider container ownership could not be reconciled" >&2
        return 1
      fi
      sleep 0.1
      continue
    fi
    local network_mode
    network_mode="$(
      timeout --signal=KILL 1s \
        docker container inspect \
          --format '{{.HostConfig.NetworkMode}}' \
          "$_yap_container_id"
    )"
    if [ "$network_mode" != "$network_name" ]; then
      echo "private provider container joined an unexpected network" >&2
      return 1
    fi
    container_ip="$(
      timeout --signal=KILL 1s \
        docker container inspect \
          --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' \
          "$_yap_container_id"
    )"
    if [[ "$container_ip" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; then
      break
    fi
    sleep 0.1
  done
  if [[ ! "$container_ip" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; then
    echo "private provider container has no bounded IPv4 address" >&2
    return 1
  fi

  if [ "$_yap_requested_exit" -ne 0 ]; then
    return "$_yap_requested_exit"
  fi
  yap_start_owned_process_group \
    _yap_proxy_control_fd \
    _yap_proxy_reap_pid \
    _yap_proxy_pid \
    "$_yap_proxy_state_file" \
    "$_yap_proxy_result_file" \
    - \
    - \
    "$_yap_owner_token" \
    "Private loopback proxy" \
    -- \
    env -i \
    PATH=/usr/sbin:/usr/bin:/sbin:/bin \
    YAP_RUNTIME_OWNER_TOKEN="$_yap_owner_token" \
    "$socat_path" \
    "TCP4-LISTEN:${host_port},bind=127.0.0.1,reuseaddr,fork,backlog=32,max-children=32" \
    "TCP4:${container_ip}:${container_port}"
  (
    umask 077
    printf "%s\n" "$_yap_proxy_pid" >"$_yap_proxy_group_file.part"
    mv -- "$_yap_proxy_group_file.part" "$_yap_proxy_group_file"
  )
  local recorded_proxy_group
  recorded_proxy_group="$(cat -- "$_yap_proxy_group_file")"
  if [ "$recorded_proxy_group" != "$_yap_proxy_pid" ]; then
    echo "private loopback proxy process-group identity is invalid" >&2
    return 1
  fi

  deadline=$((SECONDS + 10))
  while [ "$SECONDS" -lt "$deadline" ]; do
    if ss -H -ltn "sport = :$host_port" \
      | awk -v expected="127.0.0.1:$host_port" \
        '$4 == expected { found=1 } END { exit !found }'; then
      break
    fi
    if [ -e "$_yap_proxy_result_file" ]; then
      echo "private loopback proxy exited before listening" >&2
      return 1
    fi
    sleep 0.1
  done
  if ! ss -H -ltn "sport = :$host_port" \
    | awk -v expected="127.0.0.1:$host_port" \
      '$4 == expected { found=1 } END { exit !found }'; then
    echo "private loopback proxy did not bind numeric IPv4 loopback" >&2
    return 1
  fi

  local container_exit wait_status
  set +e
  container_exit="$(docker wait "$_yap_container_id")"
  wait_status="$?"
  set -e
  if [ "$_yap_requested_exit" -ne 0 ]; then
    container_exit="$_yap_requested_exit"
  elif [ "$wait_status" -ne 0 ] \
    || [[ ! "$container_exit" =~ ^[0-9]+$ ]] \
    || [ "$container_exit" -gt 255 ]; then
    container_exit=1
  fi

  trap - EXIT HUP INT TERM
  local cleanup_status=0
  private_loopback_proxy_cleanup || cleanup_status="$?"
  if [ "$container_exit" -eq 0 ] && [ "$cleanup_status" -ne 0 ]; then
    container_exit="$cleanup_status"
  fi
  return "$container_exit"
}
