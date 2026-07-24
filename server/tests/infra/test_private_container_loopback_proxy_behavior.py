from __future__ import annotations

from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PROXY_HELPER = (
    REPOSITORY_ROOT
    / "infra"
    / "yap-server-node"
    / "private-container-loopback-proxy.sh"
)
PROCESS_GROUP_HELPER = (
    REPOSITORY_ROOT
    / "infra"
    / "yap-server-node"
    / "owned-process-group.sh"
)
CONTAINER_ID = "a" * 64
OWNER_TOKEN = "b" * 64


class PrivateContainerLoopbackProxyBehaviorTests(unittest.TestCase):
    def test_failure_cleanup_stops_only_the_created_owned_container_id(self) -> None:
        bash = shutil.which("bash")
        if bash is None:
            self.skipTest("bash is unavailable for the shell ownership replay")

        with tempfile.TemporaryDirectory() as temporary:
            marker_path = Path(temporary) / "owned-stop"
            foreign_marker_path = Path(temporary) / "foreign-access"
            proxy_group_path = Path(temporary) / "proxy.pgid"
            marker = _bash_path(marker_path)
            foreign_marker = _bash_path(foreign_marker_path)
            proxy_group = _bash_path(proxy_group_path)
            harness = f"""
marker={shlex.quote(marker)}
foreign_marker={shlex.quote(foreign_marker)}
proxy_group={shlex.quote(proxy_group)}
export marker foreign_marker proxy_group

docker() {{
  if [ "$1" = "run" ]; then
    printf '%s\\n' "{CONTAINER_ID}"
    return 0
  fi
  if [ "$1" = "container" ] && [ "$2" = "inspect" ]; then
    last="${{@: -1}}"
    if [ "$last" != "{CONTAINER_ID}" ]; then
      : >"$foreign_marker"
      return 99
    fi
    case "$*" in
      *io.yap.run-token*) printf '%s\\n' "{OWNER_TOKEN}" ;;
      *'{{.Name}}'*) printf '%s\\n' "/yap-test-provider" ;;
      *'{{.State.Running}}'*) printf '%s\\n' "true" ;;
      *'{{.HostConfig.NetworkMode}}'*) printf '%s\\n' "foreign-network" ;;
      *) return 98 ;;
    esac
    return 0
  fi
  if [ "$1" = "stop" ]; then
    last="${{@: -1}}"
    printf '%s\\n' "$last" >"$marker"
    return 0
  fi
  : >"$foreign_marker"
  return 97
}}
ss() {{ return 0; }}
socat() {{ return 0; }}
setsid() {{ return 0; }}
ps() {{ return 0; }}

run_private_container_with_loopback_proxy \
  yap-test-provider yap-test-network 18000 8000 "{OWNER_TOKEN}" \
  "$proxy_group" -- \
  docker run
exit 99
"""
            try:
                completed = subprocess.run(
                    [bash],
                    input=(
                        PROCESS_GROUP_HELPER.read_text(encoding="utf-8")
                        .replace("\r\n", "\n")
                        .replace("\r", "\n")
                        + PROXY_HELPER.read_text(encoding="utf-8")
                        .replace("\r\n", "\n")
                        .replace("\r", "\n")
                        + harness
                    ).encode("utf-8"),
                    check=False,
                    capture_output=True,
                    timeout=30,
                )
            except subprocess.TimeoutExpired as error:
                output = (error.stdout or b"") + (error.stderr or b"")
                self.fail(output.decode("utf-8", errors="replace"))

            self.assertEqual(
                completed.returncode,
                1,
                (completed.stdout + completed.stderr).decode(
                    "utf-8",
                    errors="replace",
                ),
            )
            self.assertEqual(marker_path.read_text(encoding="utf-8").strip(), CONTAINER_ID)
            self.assertFalse(foreign_marker_path.exists())

    def test_term_to_outer_launcher_retires_owned_runtime(self) -> None:
        bash = shutil.which("bash")
        if bash is None:
            self.skipTest("bash is unavailable for the shell TERM replay")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake_socat = root / "socat"
            fake_socat.write_text(
                "#!/usr/bin/env bash\n"
                'trap \': >"$proxy_stop"; exit 0\' TERM INT HUP\n'
                ': >"$listener"\n'
                'while [ ! -e "$proxy_stop" ]; do sleep 0.05; done\n',
                encoding="utf-8",
                newline="\n",
            )
            fake_socat.chmod(0o700)
            paths = {
                name: _bash_path(root / name)
                for name in (
                    "container-stop",
                    "docker-wait-ready",
                    "launcher-log",
                    "listener",
                    "proxy-stop",
                    "proxy.pgid",
                )
            }
            harness = f"""
PATH={shlex.quote(_bash_path(root))}:$PATH
export PATH
container_stop={shlex.quote(paths["container-stop"])}
docker_wait_ready={shlex.quote(paths["docker-wait-ready"])}
listener={shlex.quote(paths["listener"])}
proxy_stop={shlex.quote(paths["proxy-stop"])}
proxy_group={shlex.quote(paths["proxy.pgid"])}
export container_stop docker_wait_ready listener proxy_stop proxy_group

docker() {{
  if [ "$1" = "run" ]; then
    printf '%s\\n' "{CONTAINER_ID}"
    return 0
  fi
  if [ "$1" = "container" ] && [ "$2" = "inspect" ]; then
    case "$*" in
      *io.yap.run-token*) printf '%s\\n' "{OWNER_TOKEN}" ;;
      *'{{.Name}}'*) printf '%s\\n' "/yap-test-provider" ;;
      *'{{.State.Running}}'*) printf '%s\\n' "true" ;;
      *'{{.HostConfig.NetworkMode}}'*) printf '%s\\n' "yap-test-network" ;;
      *NetworkSettings.Networks*) printf '%s\\n' "172.19.0.2" ;;
      *) return 98 ;;
    esac
    return 0
  fi
  if [ "$1" = "logs" ]; then
    while [ ! -e "$container_stop" ]; do sleep 0.05; done
    return 0
  fi
  if [ "$1" = "wait" ]; then
    : >"$docker_wait_ready"
    while [ ! -e "$container_stop" ]; do sleep 0.05; done
    printf '%s\\n' 143
    return 0
  fi
  if [ "$1" = "stop" ]; then
    printf '%s\\n' "${{@: -1}}" >"$container_stop"
    return 0
  fi
  return 97
}}
ss() {{
  if [ -e "$listener" ] \
    && [ ! -e "$container_stop" ] \
    && [ ! -e "$proxy_stop" ]; then
    printf '%s\\n' 'LISTEN 0 32 127.0.0.1:18000 0.0.0.0:*'
  fi
}}
env() {{
  shift
  while [[ "$1" == *=* ]]; do
    if [[ "$1" == PATH=* ]]; then
      export PATH={shlex.quote(_bash_path(root))}:"${{1#PATH=}}"
    else
      export "$1"
    fi
    shift
  done
  exec "$@"
}}

run_private_container_with_loopback_proxy \
  yap-test-provider yap-test-network 18000 8000 "{OWNER_TOKEN}" \
  "$proxy_group" -- \
  docker run
"""
            launcher_path = root / "launcher.sh"
            launcher_path.write_text(
                (
                    PROCESS_GROUP_HELPER.read_text(encoding="utf-8")
                    .replace("\r\n", "\n")
                    .replace("\r", "\n")
                    + PROXY_HELPER.read_text(encoding="utf-8")
                    .replace("\r\n", "\n")
                    .replace("\r", "\n")
                    + harness
                ),
                encoding="utf-8",
                newline="\n",
            )
            outer_harness = f"""
container_stop={shlex.quote(paths["container-stop"])}
docker_wait_ready={shlex.quote(paths["docker-wait-ready"])}
launcher_log={shlex.quote(paths["launcher-log"])}
proxy_stop={shlex.quote(paths["proxy-stop"])}
setsid bash {shlex.quote(_bash_path(launcher_path))} \
  >"$launcher_log" 2>&1 &
launcher_pid="$!"
deadline=$((SECONDS + 10))
while [ ! -e "$docker_wait_ready" ]; do
  if ! builtin kill -0 "$launcher_pid" 2>/dev/null || [ "$SECONDS" -ge "$deadline" ]; then
    cat "$launcher_log" >&2
    exit 91
  fi
  sleep 0.05
done
builtin kill -TERM -- "-$launcher_pid"
set +e
wait "$launcher_pid"
status="$?"
set -e
if [ "$status" -ne 143 ]; then
  cat "$launcher_log" >&2
  echo "launcher status: $status" >&2
  exit 92
fi
if [ ! -e "$container_stop" ] \
  || [ "$(cat "$container_stop")" != "{CONTAINER_ID}" ]; then
  cat "$launcher_log" >&2
  echo "owned container was not stopped" >&2
  exit 93
fi
"""
            try:
                completed = subprocess.run(
                    [bash],
                    input=outer_harness.encode("utf-8"),
                    check=False,
                    capture_output=True,
                    timeout=30,
                )
            except subprocess.TimeoutExpired as error:
                output = (error.stdout or b"") + (error.stderr or b"")
                self.fail(output.decode("utf-8", errors="replace"))

            self.assertEqual(
                completed.returncode,
                0,
                (completed.stdout + completed.stderr).decode(
                    "utf-8",
                    errors="replace",
                ),
            )


def _bash_path(path: Path) -> str:
    resolved = path.resolve()
    if resolved.drive:
        drive = resolved.drive.rstrip(":").lower()
        remainder = resolved.as_posix().split(":", maxsplit=1)[1]
        return f"/mnt/{drive}{remainder}"
    return resolved.as_posix()


if __name__ == "__main__":
    unittest.main()
