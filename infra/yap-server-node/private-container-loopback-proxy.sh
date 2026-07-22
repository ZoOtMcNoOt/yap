#!/usr/bin/env bash

# Source this helper from a checked provider launcher. The model container stays
# on an egress-blocked Docker internal bridge; one bounded host process group
# exposes only its service port on numeric IPv4 loopback.

run_private_container_with_loopback_proxy() {
  if [ "$#" -lt 7 ] || [ "$5" != "--" ]; then
    echo "private container proxy arguments are invalid" >&2
    return 2
  fi
  local container_name="$1"
  local network_name="$2"
  local host_port="$3"
  local container_port="$4"
  shift 5

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

  local proxy_pid=""
  local log_pid=""
  local requested_exit=0

  private_loopback_proxy_stop_group() {
    if [ -z "$proxy_pid" ]; then
      return 0
    fi
    if kill -0 -- "-$proxy_pid" 2>/dev/null; then
      kill -TERM -- "-$proxy_pid" 2>/dev/null || true
      local deadline=$((SECONDS + 10))
      while kill -0 -- "-$proxy_pid" 2>/dev/null; do
        if [ "$SECONDS" -ge "$deadline" ]; then
          kill -KILL -- "-$proxy_pid" 2>/dev/null || true
          break
        fi
        sleep 0.1
      done
    fi
    wait "$proxy_pid" 2>/dev/null || true
    proxy_pid=""
  }

  private_loopback_proxy_stop_log_follower() {
    if [ -z "$log_pid" ]; then
      return 0
    fi
    if kill -0 "$log_pid" 2>/dev/null; then
      kill -TERM "$log_pid" 2>/dev/null || true
      local deadline=$((SECONDS + 5))
      while kill -0 "$log_pid" 2>/dev/null; do
        if [ "$SECONDS" -ge "$deadline" ]; then
          kill -KILL "$log_pid" 2>/dev/null || true
          break
        fi
        sleep 0.1
      done
    fi
    wait "$log_pid" 2>/dev/null || true
    log_pid=""
  }

  private_loopback_proxy_cleanup() {
    local cleanup_status=0
    private_loopback_proxy_stop_group
    private_loopback_proxy_stop_log_follower
    if docker container inspect "$container_name" >/dev/null 2>&1; then
      docker stop --time 10 "$container_name" >/dev/null 2>&1 || cleanup_status=1
    fi
    if ss -H -ltn "sport = :$host_port" | grep -q .; then
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
    requested_exit="$1"
    private_loopback_proxy_stop_group
    if docker container inspect "$container_name" >/dev/null 2>&1; then
      docker stop --time 10 "$container_name" >/dev/null 2>&1 || true
    fi
  }

  trap private_loopback_proxy_exit EXIT
  trap 'private_loopback_proxy_request_stop 129' HUP
  trap 'private_loopback_proxy_request_stop 130' INT
  trap 'private_loopback_proxy_request_stop 143' TERM

  "$@" >/dev/null

  local deadline=$((SECONDS + 30))
  local container_ip=""
  while [ "$SECONDS" -lt "$deadline" ]; do
    if [ "$(
      docker container inspect \
        --format '{{.State.Running}}' \
        "$container_name" 2>/dev/null || true
    )" != "true" ]; then
      if ! docker container inspect "$container_name" >/dev/null 2>&1; then
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
        "$container_name"
    )"
    if [ "$network_mode" != "$network_name" ]; then
      echo "private provider container joined an unexpected network" >&2
      return 1
    fi
    container_ip="$(
      docker container inspect \
        --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' \
        "$container_name"
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

  docker logs --follow "$container_name" &
  log_pid="$!"

  env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin setsid socat \
    "TCP4-LISTEN:${host_port},bind=127.0.0.1,reuseaddr,fork,backlog=32,max-children=32" \
    "TCP4:${container_ip}:${container_port}" &
  proxy_pid="$!"
  local proxy_group
  proxy_group="$(ps -o pgid= -p "$proxy_pid" | tr -d '[:space:]')"
  if [ "$proxy_group" != "$proxy_pid" ]; then
    echo "private loopback proxy did not enter its own process group" >&2
    return 1
  fi

  deadline=$((SECONDS + 10))
  while [ "$SECONDS" -lt "$deadline" ]; do
    if ss -H -ltn "sport = :$host_port" \
      | awk -v expected="127.0.0.1:$host_port" \
        '$4 == expected { found=1 } END { exit !found }'; then
      break
    fi
    if ! kill -0 "$proxy_pid" 2>/dev/null; then
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
  container_exit="$(docker wait "$container_name")"
  wait_status="$?"
  set -e
  if [ "$requested_exit" -ne 0 ]; then
    container_exit="$requested_exit"
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
