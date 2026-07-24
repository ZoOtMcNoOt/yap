#!/usr/bin/env bash

# Source this helper from a checked provider launcher. The model container stays
# on an egress-blocked Docker internal bridge; one bounded host process group
# exposes only its service port on numeric IPv4 loopback.

run_private_container_with_loopback_proxy() {
  set -euo pipefail
  if [ "$#" -lt 9 ] || [ "$7" != "--" ]; then
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
  proxy_group_parent="$(dirname -- "$proxy_group_file")"
  if [ ! -d "$proxy_group_parent" ] \
    || [ -L "$proxy_group_parent" ] \
    || [ -e "$proxy_group_file" ] \
    || [ -L "$proxy_group_file" ] \
    || [ -e "$proxy_group_file.part" ] \
    || [ -L "$proxy_group_file.part" ]; then
    echo "private proxy process-group identity path is unsafe" >&2
    return 2
  fi
  for program in docker env socat setsid ss ps; do
    if ! command -v "$program" >/dev/null 2>&1; then
      echo "private container proxy requires $program" >&2
      return 2
    fi
  done
  if ss -H -ltn "sport = :$host_port" | grep -q .; then
    echo "private loopback proxy port is already owned" >&2
    return 2
  fi

  _yap_proxy_pid=""
  _yap_log_pid=""
  _yap_container_id=""
  _yap_host_port="$host_port"
  _yap_owner_token="$owner_token"
  _yap_proxy_group_file="$proxy_group_file"
  _yap_requested_exit=0

  private_loopback_proxy_stop_group() {
    if [ -z "$_yap_proxy_pid" ]; then
      return 0
    fi
    stop_owned_child_process_group \
      "$_yap_proxy_pid" \
      "$_yap_owner_token" \
      "Private loopback proxy" \
      "$$" \
      || return 1
    wait "$_yap_proxy_pid" 2>/dev/null || true
    _yap_proxy_pid=""
    rm -f -- "$_yap_proxy_group_file" "$_yap_proxy_group_file.part"
  }

  private_loopback_proxy_stop_log_follower() {
    if [ -z "$_yap_log_pid" ]; then
      return 0
    fi
    if kill -0 "$_yap_log_pid" 2>/dev/null; then
      kill -TERM "$_yap_log_pid" 2>/dev/null || true
      local deadline=$((SECONDS + 5))
      while kill -0 "$_yap_log_pid" 2>/dev/null; do
        if [ "$SECONDS" -ge "$deadline" ]; then
          kill -KILL "$_yap_log_pid" 2>/dev/null || true
          break
        fi
        sleep 0.1
      done
    fi
    wait "$_yap_log_pid" 2>/dev/null || true
    _yap_log_pid=""
  }

  private_loopback_proxy_owns_container() {
    [ -n "$_yap_container_id" ] && [ "$(
      docker container inspect \
        --format '{{index .Config.Labels "io.yap.run-token"}}' \
        "$_yap_container_id" 2>/dev/null || true
    )" = "$_yap_owner_token" ]
  }

  private_loopback_proxy_cleanup() {
    local cleanup_status=0
    private_loopback_proxy_stop_group || cleanup_status=1
    private_loopback_proxy_stop_log_follower
    if private_loopback_proxy_owns_container; then
      docker stop --time 10 "$_yap_container_id" >/dev/null 2>&1 \
        || cleanup_status=1
    fi
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
    private_loopback_proxy_stop_group || true
    if private_loopback_proxy_owns_container; then
      docker stop --time 10 "$_yap_container_id" >/dev/null 2>&1 || true
    fi
  }

  trap private_loopback_proxy_exit EXIT
  trap 'private_loopback_proxy_request_stop 129' HUP
  trap 'private_loopback_proxy_request_stop 130' INT
  trap 'private_loopback_proxy_request_stop 143' TERM

  if ! _yap_container_id="$("$@")"; then
    echo "private provider container failed to start" >&2
    return 1
  fi
  if [[ ! "$_yap_container_id" =~ ^[0-9a-f]{64}$ ]] \
    || ! private_loopback_proxy_owns_container \
    || [ "$(
      docker container inspect --format '{{.Name}}' "$_yap_container_id"
    )" != "/$container_name" ]; then
    echo "private provider container identity is invalid" >&2
    return 1
  fi

  local deadline=$((SECONDS + 30))
  local container_ip=""
  while [ "$SECONDS" -lt "$deadline" ]; do
    if [ "$(
      docker container inspect \
        --format '{{.State.Running}}' \
        "$_yap_container_id" 2>/dev/null || true
    )" != "true" ]; then
      if ! private_loopback_proxy_owns_container; then
        echo "private provider container exited before proxy startup" >&2
        return 1
      fi
      sleep 0.1
      continue
    fi
    local network_mode
    network_mode="$(
      docker container inspect \
        --format '{{.HostConfig.NetworkMode}}' \
        "$_yap_container_id"
    )"
    if [ "$network_mode" != "$network_name" ]; then
      echo "private provider container joined an unexpected network" >&2
      return 1
    fi
    container_ip="$(
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

  docker logs --follow "$_yap_container_id" &
  _yap_log_pid="$!"

  env -i \
    PATH=/usr/sbin:/usr/bin:/sbin:/bin \
    YAP_RUNTIME_OWNER_TOKEN="$_yap_owner_token" \
    bash -c '
      set -euo pipefail
      deadline=$((SECONDS + 10))
      while [ ! -f "$1" ]; do
        if [ "$SECONDS" -ge "$deadline" ]; then
          exit 92
        fi
        sleep 0.05
      done
      if [ "$(cat -- "$1")" != "$$" ]; then
        exit 93
      fi
      exec setsid socat "$2" "$3"
    ' bash \
    "$_yap_proxy_group_file" \
    "TCP4-LISTEN:${host_port},bind=127.0.0.1,reuseaddr,fork,backlog=32,max-children=32" \
    "TCP4:${container_ip}:${container_port}" &
  _yap_proxy_pid="$!"
  (
    umask 077
    printf "%s\n" "$_yap_proxy_pid" >"$_yap_proxy_group_file.part"
    mv -- "$_yap_proxy_group_file.part" "$_yap_proxy_group_file"
  )
  deadline=$((SECONDS + 10))
  local proxy_group=""
  while [ "$SECONDS" -lt "$deadline" ]; do
    proxy_group="$(ps -o pgid= -p "$_yap_proxy_pid" | tr -d '[:space:]')"
    if [ "$proxy_group" = "$_yap_proxy_pid" ]; then
      break
    fi
    if ! kill -0 "$_yap_proxy_pid" 2>/dev/null; then
      echo "private loopback proxy exited before process-group ownership" >&2
      return 1
    fi
    sleep 0.05
  done
  if [ "$proxy_group" != "$_yap_proxy_pid" ]; then
    echo "private loopback proxy did not enter its own process group" >&2
    return 1
  fi
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
    if ! kill -0 "$_yap_proxy_pid" 2>/dev/null; then
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
