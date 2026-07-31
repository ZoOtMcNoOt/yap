from __future__ import annotations

from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

from tests.infra.linux_bash import find_linux_bash


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PROXY_HELPER = (
    REPOSITORY_ROOT
    / "infra"
    / "yap-server-node"
    / "private-container-loopback-proxy.sh"
)
PROCESS_GROUP_HELPER = (
    REPOSITORY_ROOT / "infra" / "yap-server-node" / "owned-process-group.sh"
)
CONTAINER_ID = "a" * 64
OWNER_TOKEN = "b" * 64


class PrivateContainerLoopbackProxyBehaviorTests(unittest.TestCase):
    def test_canonical_system_socat_target_is_accepted(self) -> None:
        bash = find_linux_bash()
        if bash is None:
            self.skipTest(
                "Linux-compatible bash is unavailable for the socat path replay"
            )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake_socat_target = root / "socat1"
            fake_socat_target.write_text(
                "#!/usr/bin/env bash\nexit 0\n",
                encoding="utf-8",
                newline="\n",
            )
            fake_socat_target.chmod(0o700)
            harness = f"""
set -euo pipefail
root={shlex.quote(_bash_path(root))}
ln -s socat1 "$root/socat"
PATH="$root:$PATH"
export PATH
resolved="$(resolve_private_container_socat_executable)"
expected="$(readlink -f -- "$root/socat1")"
if [ "$resolved" != "$expected" ]; then
  echo "canonical socat target did not resolve to the executable" >&2
  exit 90
fi
"""
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
                timeout=10,
            )
            self.assertEqual(
                completed.returncode,
                0,
                (completed.stdout + completed.stderr).decode(
                    "utf-8",
                    errors="replace",
                ),
            )

    def test_inspect_and_inventory_failure_cannot_claim_container_absence(
        self,
    ) -> None:
        bash = find_linux_bash()
        if bash is None:
            self.skipTest(
                "Linux-compatible bash is unavailable for the fail-closed replay"
            )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inventory_marker_path = root / "inventory-attempted"
            stop_marker_path = root / "unsafe-stop"
            proxy_group_path = root / "proxy.pgid"
            fake_socat = root / "socat"
            fake_socat.write_text(
                "#!/usr/bin/env bash\nexit 0\n",
                encoding="utf-8",
                newline="\n",
            )
            fake_socat.chmod(0o700)
            fake_docker = root / "docker"
            fake_docker.write_text(
                """#!/usr/bin/env bash
set -euo pipefail
if [ "$1" = container ] && [ "$2" = create ]; then
  printf '%s\n' "$YAP_TEST_CONTAINER_ID" >"$4"
  printf '%s\n' "$YAP_TEST_CONTAINER_ID"
  exit 0
fi
if [ "$1" = container ] && [ "$2" = inspect ]; then
  exit 1
fi
if [ "$1" = container ] && [ "$2" = ls ]; then
  : >"$YAP_TEST_INVENTORY_MARKER"
  exit 1
fi
if [ "$1" = stop ] || [ "$1" = kill ]; then
  : >"$YAP_TEST_STOP_MARKER"
  exit 0
fi
exit 97
""",
                encoding="utf-8",
                newline="\n",
            )
            fake_docker.chmod(0o700)
            harness = f"""
PATH={shlex.quote(_bash_path(root))}:$PATH
export PATH
export YAP_TEST_CONTAINER_ID={CONTAINER_ID}
export YAP_TEST_INVENTORY_MARKER={
                shlex.quote(_bash_path(inventory_marker_path))
            }
export YAP_TEST_STOP_MARKER={shlex.quote(_bash_path(stop_marker_path))}
ss() {{ return 0; }}
ps() {{ return 0; }}

run_private_container_with_loopback_proxy \
  yap-test-provider yap-test-network 18000 8000 "{OWNER_TOKEN}" \
  {shlex.quote(_bash_path(proxy_group_path))} -- \
  docker container create test-image
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
            self.assertTrue(inventory_marker_path.exists())
            self.assertFalse(stop_marker_path.exists())

    def test_failure_cleanup_stops_only_the_created_owned_container_id(self) -> None:
        bash = find_linux_bash()
        if bash is None:
            self.skipTest(
                "Linux-compatible bash is unavailable for the shell ownership replay"
            )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            marker_path = root / "owned-stop"
            foreign_marker_path = root / "foreign-access"
            proxy_group_path = root / "proxy.pgid"
            fake_socat = root / "socat"
            fake_socat.write_text(
                "#!/usr/bin/env bash\nexit 0\n",
                encoding="utf-8",
                newline="\n",
            )
            fake_socat.chmod(0o700)
            fake_docker = root / "docker"
            fake_docker.write_text(
                """#!/usr/bin/env bash
set -euo pipefail
if [ "$1" = container ] && [ "$2" = create ]; then
  printf '%s\n' "$YAP_TEST_CONTAINER_ID" >"$4"
  printf '%s\n' "$YAP_TEST_CONTAINER_ID"
  exit 0
fi
if [ "$1" = container ] && [ "$2" = start ]; then
  exit 0
fi
if [ "$1" = container ] && [ "$2" = inspect ]; then
  if [ -e "$YAP_TEST_STOP_MARKER" ]; then
    exit 1
  fi
  case "$*" in
    *'{{.Id}}|'*) printf '%s|%s|/%s\n' \
      "$YAP_TEST_CONTAINER_ID" "$YAP_TEST_OWNER_TOKEN" "$YAP_TEST_CONTAINER_NAME" ;;
    *'{{.State.Running}}'*) printf '%s\n' true ;;
    *'{{.HostConfig.NetworkMode}}'*) printf '%s\n' foreign-network ;;
    *) exit 0 ;;
  esac
  exit 0
fi
if [ "$1" = container ] && [ "$2" = ls ]; then
  exit 0
fi
if [ "$1" = logs ]; then
  exit 0
fi
if [ "$1" = stop ] || [ "$1" = kill ] || [ "$1" = rm ]; then
  printf '%s\n' "${@: -1}" >"$YAP_TEST_STOP_MARKER"
  exit 0
fi
: >"$YAP_TEST_FOREIGN_MARKER"
exit 97
""",
                encoding="utf-8",
                newline="\n",
            )
            fake_docker.chmod(0o700)
            marker = _bash_path(marker_path)
            foreign_marker = _bash_path(foreign_marker_path)
            proxy_group = _bash_path(proxy_group_path)
            harness = f"""
PATH={shlex.quote(_bash_path(root))}:$PATH
export PATH
marker={shlex.quote(marker)}
foreign_marker={shlex.quote(foreign_marker)}
proxy_group={shlex.quote(proxy_group)}
export marker foreign_marker proxy_group
export YAP_TEST_CONTAINER_ID={CONTAINER_ID}
export YAP_TEST_OWNER_TOKEN={OWNER_TOKEN}
export YAP_TEST_CONTAINER_NAME=yap-test-provider
export YAP_TEST_STOP_MARKER="$marker"
export YAP_TEST_FOREIGN_MARKER="$foreign_marker"
ss() {{ return 0; }}
ps() {{ return 0; }}

run_private_container_with_loopback_proxy \
  yap-test-provider yap-test-network 18000 8000 "{OWNER_TOKEN}" \
  "$proxy_group" -- \
  docker container create test-image
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
            self.assertEqual(
                marker_path.read_text(encoding="utf-8").strip(), CONTAINER_ID
            )
            self.assertFalse(foreign_marker_path.exists())

    def test_renamed_created_container_retains_immutable_recovery_identity(
        self,
    ) -> None:
        bash = find_linux_bash()
        if bash is None:
            self.skipTest(
                "Linux-compatible bash is unavailable for the renamed-container replay"
            )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            proxy_group_path = root / "proxy.pgid"
            renamed_marker_path = root / "container-renamed"
            unsafe_remove_path = root / "unsafe-remove"
            fake_socat = root / "socat"
            fake_socat.write_text(
                "#!/usr/bin/env bash\nexit 0\n",
                encoding="utf-8",
                newline="\n",
            )
            fake_socat.chmod(0o700)
            fake_docker = root / "docker"
            fake_docker.write_text(
                """#!/usr/bin/env bash
set -euo pipefail
if [ "$1" = container ] && [ "$2" = create ]; then
  printf '%s\n' "$YAP_TEST_CONTAINER_ID" >"$4"
  printf '%s\n' "$YAP_TEST_CONTAINER_ID"
  exit 0
fi
if [ "$1" = container ] && [ "$2" = start ]; then
  exit 0
fi
if [ "$1" = container ] && [ "$2" = inspect ]; then
  case "$*" in
    *'{{.Id}}|'*)
      inspected_name="$YAP_TEST_CONTAINER_NAME"
      if [ -e "$YAP_TEST_RENAMED_MARKER" ]; then
        inspected_name=renamed-provider
      fi
      printf '%s|%s|/%s\n' \
        "$YAP_TEST_CONTAINER_ID" "$YAP_TEST_OWNER_TOKEN" "$inspected_name"
      ;;
    *'{{.State.Running}}'*) printf '%s\n' true ;;
    *'{{.HostConfig.NetworkMode}}'*)
      : >"$YAP_TEST_RENAMED_MARKER"
      printf '%s\n' foreign-network
      ;;
    *) exit 0 ;;
  esac
  exit 0
fi
if [ "$1" = container ] && [ "$2" = ls ]; then
  printf '%s|%s\n' "$YAP_TEST_CONTAINER_ID" renamed-provider
  exit 0
fi
if [ "$1" = logs ] || [ "$1" = stop ] || [ "$1" = rm ]; then
  : >"$YAP_TEST_UNSAFE_REMOVE"
  exit 0
fi
exit 97
""",
                encoding="utf-8",
                newline="\n",
            )
            fake_docker.chmod(0o700)
            proxy_group = _bash_path(proxy_group_path)
            harness = f"""
PATH={shlex.quote(_bash_path(root))}:$PATH
export PATH
export YAP_TEST_CONTAINER_ID={CONTAINER_ID}
export YAP_TEST_OWNER_TOKEN={OWNER_TOKEN}
export YAP_TEST_CONTAINER_NAME=yap-test-provider
export YAP_TEST_RENAMED_MARKER={
                shlex.quote(_bash_path(renamed_marker_path))
            }
export YAP_TEST_UNSAFE_REMOVE={shlex.quote(_bash_path(unsafe_remove_path))}
ss() {{ return 0; }}
ps() {{ return 0; }}

run_private_container_with_loopback_proxy \
  yap-test-provider yap-test-network 18000 8000 "{OWNER_TOKEN}" \
  {shlex.quote(proxy_group)} -- \
  docker container create test-image
exit 99
"""
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
            output = (completed.stdout + completed.stderr).decode(
                "utf-8",
                errors="replace",
            )
            self.assertEqual(completed.returncode, 1, output)
            self.assertTrue(renamed_marker_path.exists())
            self.assertFalse(unsafe_remove_path.exists())
            self.assertEqual(
                Path(f"{proxy_group_path}.container-id")
                .read_text(encoding="utf-8")
                .strip(),
                CONTAINER_ID,
            )
            self.assertEqual(
                Path(f"{proxy_group_path}.container-recovery")
                .read_text(encoding="utf-8")
                .strip(),
                f"1 started yap-test-provider {OWNER_TOKEN} {CONTAINER_ID}",
            )
            self.assertIn(
                "private provider container ownership could not be verified",
                output,
            )

    def test_control_empty_proxy_recovery_stops_owned_group_and_removes_records(
        self,
    ) -> None:
        bash = find_linux_bash()
        if bash is None:
            self.skipTest(
                "Linux-compatible bash is unavailable for the proxy recovery replay"
            )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = f"""
set -euo pipefail
source {shlex.quote(_bash_path(PROCESS_GROUP_HELPER))}
source {shlex.quote(_bash_path(PROXY_HELPER))}
state_file={shlex.quote(_bash_path(root / "proxy.state"))}
result_file={shlex.quote(_bash_path(root / "proxy.result"))}
group_file={shlex.quote(_bash_path(root / "proxy.pgid"))}
setsid env YAP_RUNTIME_OWNER_TOKEN={OWNER_TOKEN} bash -c 'sleep 60 & wait' &
child_pid="$!"
owned_group="$child_pid"
start_ticks="$(awk '{{print $22}}' "/proc/$child_pid/stat")"
(exit 1) &
reap_pid="$!"
control_fd=
process_status=125
printf '%s\\n' "$child_pid" >"$group_file"
printf '1 ready %s %s %s 0\\n' \
  "$child_pid" "$start_ticks" "$reap_pid" >"$state_file"
printf '1 1 143 ownership-failed\\n' >"$result_file"
set +e
stop_private_loopback_proxy_process_group \
  process_status control_fd reap_pid child_pid state_file result_file \
  "$group_file" {OWNER_TOKEN}
recovery_status="$?"
set -e
test "$recovery_status" -eq 1
test -z "$control_fd"
test -z "$reap_pid"
test -z "$child_pid"
test -z "$state_file"
test -z "$result_file"
test -z "$(yap_process_group_members "$owned_group")"
wait "$owned_group" 2>/dev/null || true
test ! -e "$group_file"
test ! -e {shlex.quote(_bash_path(root / "proxy.state"))}
test ! -e {shlex.quote(_bash_path(root / "proxy.result"))}
"""
            self._run_linux_harness(bash, harness, timeout=30)

    def test_control_empty_proxy_recovery_refuses_foreign_token_and_keeps_records(
        self,
    ) -> None:
        bash = find_linux_bash()
        if bash is None:
            self.skipTest(
                "Linux-compatible bash is unavailable for the proxy refusal replay"
            )

        foreign_token = "c" * 64
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state_path = root / "proxy.state"
            result_path = root / "proxy.result"
            group_path = root / "proxy.pgid"
            harness = f"""
set -euo pipefail
source {shlex.quote(_bash_path(PROCESS_GROUP_HELPER))}
source {shlex.quote(_bash_path(PROXY_HELPER))}
state_file={shlex.quote(_bash_path(state_path))}
result_file={shlex.quote(_bash_path(result_path))}
group_file={shlex.quote(_bash_path(group_path))}
setsid env YAP_RUNTIME_OWNER_TOKEN={foreign_token} bash -c 'sleep 60 & wait' &
child_pid="$!"
owned_group="$child_pid"
start_ticks="$(awk '{{print $22}}' "/proc/$child_pid/stat")"
(exit 1) &
reap_pid="$!"
recorded_reap_pid="$reap_pid"
control_fd=
process_status=125
printf '%s\\n' "$child_pid" >"$group_file"
printf '1 ready %s %s %s 0\\n' \
  "$child_pid" "$start_ticks" "$reap_pid" >"$state_file"
printf '1 1 143 ownership-failed\\n' >"$result_file"
set +e
stop_private_loopback_proxy_process_group \
  process_status control_fd reap_pid child_pid state_file result_file \
  "$group_file" {OWNER_TOKEN}
recovery_status="$?"
set -e
test "$recovery_status" -eq 1
test -z "$control_fd"
test "$reap_pid" = "$recorded_reap_pid"
test "$child_pid" = "$owned_group"
test -e "$state_file"
test -e "$result_file"
test -e "$group_file"
test -n "$(yap_process_group_members "$owned_group")"
stop_token_owned_process_group \
  "$owned_group" {foreign_token} "Proxy foreign-token test teardown"
wait "$owned_group" 2>/dev/null || true
rm -f -- "$state_file" "$result_file" "$group_file"
"""
            self._run_linux_harness(bash, harness, timeout=30)

    def test_term_during_container_create_retains_unknown_recovery_identity(
        self,
    ) -> None:
        bash = find_linux_bash()
        if bash is None:
            self.skipTest(
                "Linux-compatible bash is unavailable for the startup TERM replay"
            )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = {
                name: _bash_path(root / name)
                for name in (
                    "container-exists",
                    "container-stop",
                    "daemon-trigger",
                    "docker-trace",
                    "launcher-log",
                    "proxy-started",
                    "run-entered",
                )
            }
            fake_socat = root / "socat"
            fake_socat.write_text(
                "#!/usr/bin/env bash\n"
                f": >{shlex.quote(paths['proxy-started'])}\n"
                "exit 0\n",
                encoding="utf-8",
                newline="\n",
            )
            fake_socat.chmod(0o700)
            fake_docker = root / "docker"
            fake_docker.write_text(
                """#!/usr/bin/env bash
set -euo pipefail
printf '%s exists=%s\n' "$*" \
  "$([ -e "$YAP_TEST_CONTAINER_EXISTS" ] && echo yes || echo no)" \
  >>"$YAP_TEST_DOCKER_TRACE"
if [ "$1" = container ] && [ "$2" = create ]; then
  : >"$YAP_TEST_RUN_ENTERED"
  trap ': >"$YAP_TEST_DAEMON_TRIGGER"; exit 143' TERM INT HUP
  while true; do sleep 0.05; done
fi
if [ "$1" = container ] && [ "$2" = inspect ]; then
  if [ ! -e "$YAP_TEST_CONTAINER_EXISTS" ]; then
    exit 1
  fi
  case "$*" in
    *'{{.Id}}|'*) printf '%s|%s|/%s\n' \
      "$YAP_TEST_CONTAINER_ID" "$YAP_TEST_OWNER_TOKEN" "$YAP_TEST_CONTAINER_NAME" ;;
    *) exit 0 ;;
  esac
  exit 0
fi
if [ "$1" = container ] && [ "$2" = ls ]; then
  exit 0
fi
if [ "$1" = logs ]; then
  exit 0
fi
if [ "$1" = stop ] || [ "$1" = kill ] || [ "$1" = rm ]; then
  printf '%s\n' "${@: -1}" >"$YAP_TEST_CONTAINER_STOP"
  rm -f -- "$YAP_TEST_CONTAINER_EXISTS"
  exit 0
fi
exit 97
""",
                encoding="utf-8",
                newline="\n",
            )
            fake_docker.chmod(0o700)
            launcher = root / "launcher.sh"
            launcher.write_text(
                (
                    "#!/usr/bin/env bash\n"
                    "set -euo pipefail\n"
                    f"source {shlex.quote(_bash_path(PROCESS_GROUP_HELPER))}\n"
                    f"source {shlex.quote(_bash_path(PROXY_HELPER))}\n"
                    f"PATH={shlex.quote(_bash_path(root))}:$PATH\n"
                    "export PATH\n"
                    f"export YAP_TEST_CONTAINER_ID={CONTAINER_ID}\n"
                    f"export YAP_TEST_OWNER_TOKEN={OWNER_TOKEN}\n"
                    "export YAP_TEST_CONTAINER_NAME=yap-test-provider\n"
                    f"export YAP_TEST_CONTAINER_EXISTS={shlex.quote(paths['container-exists'])}\n"
                    f"export YAP_TEST_CONTAINER_STOP={shlex.quote(paths['container-stop'])}\n"
                    f"export YAP_TEST_DAEMON_TRIGGER={shlex.quote(paths['daemon-trigger'])}\n"
                    f"export YAP_TEST_DOCKER_TRACE={shlex.quote(paths['docker-trace'])}\n"
                    f"export YAP_TEST_RUN_ENTERED={shlex.quote(paths['run-entered'])}\n"
                    "ss() { return 0; }\n"
                    "run_private_container_with_loopback_proxy "
                    "yap-test-provider yap-test-network 18000 8000 "
                    f'{OWNER_TOKEN} "$YAP_TEST_PROXY_GROUP_FILE" -- '
                    "docker container create test-image\n"
                ),
                encoding="utf-8",
                newline="\n",
            )
            launcher.chmod(0o700)
            harness = f"""
set -euo pipefail
linux_runtime_root="$(mktemp -d)"
chmod 0700 "$linux_runtime_root"
trap 'rm -rf -- "$linux_runtime_root"' EXIT
proxy_group_file="$linux_runtime_root/proxy.pgid"
recovery_file="$proxy_group_file.container-recovery"
export YAP_TEST_PROXY_GROUP_FILE="$proxy_group_file"
(
  while [ ! -e {shlex.quote(paths["daemon-trigger"])} ]; do sleep 0.01; done
  sleep 2.25
  : >{shlex.quote(paths["container-exists"])}
) &
daemon_pid="$!"
setsid bash {shlex.quote(_bash_path(launcher))} \
  >{shlex.quote(paths["launcher-log"])} 2>&1 &
launcher_pid="$!"
deadline=$((SECONDS + 10))
while [ ! -e {shlex.quote(paths["run-entered"])} ]; do
  if ! kill -0 "$launcher_pid" 2>/dev/null || [ "$SECONDS" -ge "$deadline" ]; then
    cat {shlex.quote(paths["launcher-log"])} >&2
    exit 91
  fi
  sleep 0.05
done
kill -TERM -- "-$launcher_pid"
set +e
wait "$launcher_pid"
launcher_status="$?"
set -e
wait "$daemon_pid"
if [ "$launcher_status" -ne 143 ] \
  || [ -e {shlex.quote(paths["container-stop"])} ] \
  || [ ! -e {shlex.quote(paths["container-exists"])} ] \
  || [ ! -e "$recovery_file" ] \
  || [ -L "$recovery_file" ] \
  || [ "$(stat -Lc '%a' "$recovery_file")" != 600 ] \
  || [ "$(cat "$recovery_file" 2>/dev/null || true)" != \
    "1 create-pending yap-test-provider {OWNER_TOKEN} -" ] \
  || ! grep -q "creation outcome remains unproven" \
    {shlex.quote(paths["launcher-log"])} \
  || [ -e {shlex.quote(paths["proxy-started"])} ]; then
  cat {shlex.quote(paths["launcher-log"])} >&2
  cat {shlex.quote(paths["docker-trace"])} >&2
  printf 'status=%s stop=%s exists=%s recovery=%s proxy=%s\n' \
    "$launcher_status" \
    "$(cat {shlex.quote(paths["container-stop"])} 2>/dev/null || true)" \
    "$([ -e {shlex.quote(paths["container-exists"])} ] && echo yes || echo no)" \
    "$(cat "$recovery_file" 2>/dev/null || true)" \
    "$([ -e {shlex.quote(paths["proxy-started"])} ] && echo yes || echo no)" >&2
  exit 92
fi
"""
            self._run_linux_harness(bash, harness, timeout=30)

    def test_term_removes_owned_created_container_before_proxy_creation(
        self,
    ) -> None:
        bash = find_linux_bash()
        if bash is None:
            self.skipTest(
                "Linux-compatible bash is unavailable for the created-container replay"
            )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = {
                name: _bash_path(root / name)
                for name in (
                    "container-exists",
                    "container-remove",
                    "launcher-log",
                    "proxy-started",
                    "proxy.pgid",
                    "state-polled",
                )
            }
            fake_socat = root / "socat"
            fake_socat.write_text(
                "#!/usr/bin/env bash\n"
                f": >{shlex.quote(paths['proxy-started'])}\n"
                "exit 0\n",
                encoding="utf-8",
                newline="\n",
            )
            fake_socat.chmod(0o700)
            fake_docker = root / "docker"
            fake_docker.write_text(
                """#!/usr/bin/env bash
set -euo pipefail
if [ "$1" = container ] && [ "$2" = create ]; then
  : >"$YAP_TEST_CONTAINER_EXISTS"
  printf '%s\n' "$YAP_TEST_CONTAINER_ID" >"$4"
  printf '%s\n' "$YAP_TEST_CONTAINER_ID"
  exit 0
fi
if [ "$1" = container ] && [ "$2" = start ]; then
  exit 0
fi
if [ "$1" = container ] && [ "$2" = inspect ]; then
  if [ ! -e "$YAP_TEST_CONTAINER_EXISTS" ]; then
    exit 1
  fi
  case "$*" in
    *'{{.Id}}|'*) printf '%s|%s|/%s\n' \
      "$YAP_TEST_CONTAINER_ID" "$YAP_TEST_OWNER_TOKEN" "$YAP_TEST_CONTAINER_NAME" ;;
    *'{{.State.Running}}'*)
      : >"$YAP_TEST_STATE_POLLED"
      printf '%s\n' false
      ;;
    *) exit 0 ;;
  esac
  exit 0
fi
if [ "$1" = container ] && [ "$2" = ls ]; then
  if [ -e "$YAP_TEST_CONTAINER_EXISTS" ]; then
    printf '%s|%s\n' "$YAP_TEST_CONTAINER_ID" "$YAP_TEST_CONTAINER_NAME"
  fi
  exit 0
fi
if [ "$1" = logs ]; then
  exit 0
fi
if [ "$1" = stop ]; then
  exit 1
fi
if [ "$1" = rm ]; then
  printf '%s\n' "${@: -1}" >"$YAP_TEST_CONTAINER_REMOVE"
  rm -f -- "$YAP_TEST_CONTAINER_EXISTS"
  exit 0
fi
exit 97
""",
                encoding="utf-8",
                newline="\n",
            )
            fake_docker.chmod(0o700)
            launcher = root / "launcher.sh"
            launcher.write_text(
                (
                    "#!/usr/bin/env bash\n"
                    "set -euo pipefail\n"
                    f"source {shlex.quote(_bash_path(PROCESS_GROUP_HELPER))}\n"
                    f"source {shlex.quote(_bash_path(PROXY_HELPER))}\n"
                    f"PATH={shlex.quote(_bash_path(root))}:$PATH\n"
                    "export PATH\n"
                    f"export YAP_TEST_CONTAINER_ID={CONTAINER_ID}\n"
                    f"export YAP_TEST_OWNER_TOKEN={OWNER_TOKEN}\n"
                    "export YAP_TEST_CONTAINER_NAME=yap-test-provider\n"
                    f"export YAP_TEST_CONTAINER_EXISTS={shlex.quote(paths['container-exists'])}\n"
                    f"export YAP_TEST_CONTAINER_REMOVE={shlex.quote(paths['container-remove'])}\n"
                    f"export YAP_TEST_STATE_POLLED={shlex.quote(paths['state-polled'])}\n"
                    "ss() { return 0; }\n"
                    "run_private_container_with_loopback_proxy "
                    "yap-test-provider yap-test-network 18000 8000 "
                    f"{OWNER_TOKEN} {shlex.quote(paths['proxy.pgid'])} -- "
                    "docker container create test-image\n"
                ),
                encoding="utf-8",
                newline="\n",
            )
            launcher.chmod(0o700)
            harness = f"""
set -euo pipefail
setsid bash {shlex.quote(_bash_path(launcher))} \
  >{shlex.quote(paths["launcher-log"])} 2>&1 &
launcher_pid="$!"
deadline=$((SECONDS + 10))
while [ ! -e {shlex.quote(paths["state-polled"])} ]; do
  if ! kill -0 "$launcher_pid" 2>/dev/null || [ "$SECONDS" -ge "$deadline" ]; then
    cat {shlex.quote(paths["launcher-log"])} >&2
    exit 91
  fi
  sleep 0.05
done
kill -TERM -- "-$launcher_pid"
set +e
wait "$launcher_pid"
launcher_status="$?"
set -e
test "$launcher_status" -eq 143
test -e {shlex.quote(paths["container-remove"])}
test "$(cat {shlex.quote(paths["container-remove"])})" = {CONTAINER_ID}
test ! -e {shlex.quote(paths["container-exists"])}
test ! -e {shlex.quote(paths["proxy-started"])}
"""
            self._run_linux_harness(bash, harness, timeout=30)

    def test_clean_exit_fails_when_container_recovery_cannot_retire(
        self,
    ) -> None:
        bash = find_linux_bash()
        if bash is None:
            self.skipTest(
                "Linux-compatible bash is unavailable for the retirement replay"
            )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = {
                name: _bash_path(root / name)
                for name in (
                    "container-absent",
                    "launcher-log",
                    "listener",
                    "proxy-stop",
                    "proxy.pgid",
                    "retirement-failed",
                )
            }
            fake_socat = root / "socat"
            fake_socat.write_text(
                "#!/usr/bin/env bash\n"
                f"listener={shlex.quote(paths['listener'])}\n"
                f"proxy_stop={shlex.quote(paths['proxy-stop'])}\n"
                "trap '/bin/rm -f -- \"$listener\"; "
                ': >"$proxy_stop"; exit 0\' TERM INT HUP\n'
                ': >"$listener"\n'
                'while [ ! -e "$proxy_stop" ]; do sleep 0.05; done\n',
                encoding="utf-8",
                newline="\n",
            )
            fake_socat.chmod(0o700)
            fake_docker = root / "docker"
            fake_docker.write_text(
                """#!/usr/bin/env bash
set -euo pipefail
if [ "$1" = container ] && [ "$2" = create ]; then
  printf '%s\n' "$YAP_TEST_CONTAINER_ID" >"$4"
  printf '%s\n' "$YAP_TEST_CONTAINER_ID"
  exit 0
fi
if [ "$1" = container ] && [ "$2" = start ]; then
  exit 0
fi
if [ "$1" = container ] && [ "$2" = inspect ]; then
  if [ -e "$YAP_TEST_CONTAINER_ABSENT" ]; then
    exit 1
  fi
  case "$*" in
    *'{{.Id}}|'*) printf '%s|%s|/%s\n' \
      "$YAP_TEST_CONTAINER_ID" "$YAP_TEST_OWNER_TOKEN" "$YAP_TEST_CONTAINER_NAME" ;;
    *'{{.State.Running}}'*) printf '%s\n' true ;;
    *'{{.HostConfig.NetworkMode}}'*) printf '%s\n' yap-test-network ;;
    *NetworkSettings.Networks*) printf '%s\n' 172.19.0.2 ;;
    *) exit 0 ;;
  esac
  exit 0
fi
if [ "$1" = container ] && [ "$2" = ls ]; then
  if [ ! -e "$YAP_TEST_CONTAINER_ABSENT" ]; then
    printf '%s|%s\n' "$YAP_TEST_CONTAINER_ID" "$YAP_TEST_CONTAINER_NAME"
  fi
  exit 0
fi
if [ "$1" = wait ]; then
  : >"$YAP_TEST_CONTAINER_ABSENT"
  printf '%s\n' 0
  exit 0
fi
if [ "$1" = logs ] || [ "$1" = stop ] || [ "$1" = rm ]; then
  exit 0
fi
exit 97
""",
                encoding="utf-8",
                newline="\n",
            )
            fake_docker.chmod(0o700)
            harness = f"""
set -euo pipefail
source {shlex.quote(_bash_path(PROCESS_GROUP_HELPER))}
source {shlex.quote(_bash_path(PROXY_HELPER))}
PATH={shlex.quote(_bash_path(root))}:$PATH
export PATH
export YAP_TEST_CONTAINER_ID={CONTAINER_ID}
export YAP_TEST_OWNER_TOKEN={OWNER_TOKEN}
export YAP_TEST_CONTAINER_NAME=yap-test-provider
export YAP_TEST_CONTAINER_ABSENT={shlex.quote(paths["container-absent"])}
proxy_group_file={shlex.quote(paths["proxy.pgid"])}
listener={shlex.quote(paths["listener"])}
retirement_failed={shlex.quote(paths["retirement-failed"])}
rm() {{
  local candidate
  for candidate in "$@"; do
    case "$candidate" in
      "$proxy_group_file.container-recovery"|\
"$proxy_group_file.container-recovery.part"|\
"$proxy_group_file.container-id")
        : >"$retirement_failed"
        return 1
        ;;
    esac
  done
  command rm "$@"
}}
ss() {{
  if [ -e "$listener" ]; then
    printf '%s\\n' 'LISTEN 0 32 127.0.0.1:18000 0.0.0.0:*'
  fi
}}
if run_private_container_with_loopback_proxy \
  yap-test-provider yap-test-network 18000 8000 "{OWNER_TOKEN}" \
  "$proxy_group_file" -- \
  docker container create test-image \
  >{shlex.quote(paths["launcher-log"])} 2>&1; then
  launcher_status=0
else
  launcher_status="$?"
fi
test "$launcher_status" -eq 1
test -e "$retirement_failed"
test -e "$proxy_group_file.container-recovery"
test -e "$proxy_group_file.container-id"
grep -q \
  "private provider container recovery records could not be retired" \
  {shlex.quote(paths["launcher-log"])}
"""
            self._run_linux_harness(bash, harness, timeout=30)

    def test_normal_exit_fetches_logs_before_exact_container_removal(
        self,
    ) -> None:
        bash = find_linux_bash()
        if bash is None:
            self.skipTest(
                "Linux-compatible bash is unavailable for the normal-exit replay"
            )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = {
                name: _bash_path(root / name)
                for name in (
                    "container-exists",
                    "container-exited",
                    "docker-trace",
                    "listener",
                    "proxy-stop",
                    "proxy.pgid",
                )
            }
            fake_socat = root / "socat"
            fake_socat.write_text(
                "#!/usr/bin/env bash\n"
                f"listener={shlex.quote(paths['listener'])}\n"
                f"proxy_stop={shlex.quote(paths['proxy-stop'])}\n"
                "trap '/bin/rm -f -- \"$listener\"; "
                ': >"$proxy_stop"; exit 0\' TERM INT HUP\n'
                ': >"$listener"\n'
                'while [ ! -e "$proxy_stop" ]; do sleep 0.05; done\n',
                encoding="utf-8",
                newline="\n",
            )
            fake_socat.chmod(0o700)
            fake_docker = root / "docker"
            fake_docker.write_text(
                """#!/usr/bin/env bash
set -euo pipefail
if [ "$1" = container ] && [ "$2" = create ]; then
  : >"$YAP_TEST_CONTAINER_EXISTS"
  printf '%s\n' "$YAP_TEST_CONTAINER_ID" >"$4"
  printf '%s\n' "$YAP_TEST_CONTAINER_ID"
  exit 0
fi
if [ "$1" = container ] && [ "$2" = start ]; then
  exit 0
fi
if [ "$1" = container ] && [ "$2" = inspect ]; then
  if [ ! -e "$YAP_TEST_CONTAINER_EXISTS" ]; then
    exit 1
  fi
  case "$*" in
    *'{{.Id}}|'*) printf '%s|%s|/%s\n' \
      "$YAP_TEST_CONTAINER_ID" "$YAP_TEST_OWNER_TOKEN" "$YAP_TEST_CONTAINER_NAME" ;;
    *'{{.State.Running}}'*)
      if [ -e "$YAP_TEST_CONTAINER_EXITED" ]; then
        printf '%s\n' false
      else
        printf '%s\n' true
      fi
      ;;
    *'{{.HostConfig.NetworkMode}}'*) printf '%s\n' yap-test-network ;;
    *NetworkSettings.Networks*) printf '%s\n' 172.19.0.2 ;;
    *) exit 0 ;;
  esac
  exit 0
fi
if [ "$1" = container ] && [ "$2" = ls ]; then
  if [ -e "$YAP_TEST_CONTAINER_EXISTS" ]; then
    printf '%s|%s\n' "$YAP_TEST_CONTAINER_ID" "$YAP_TEST_CONTAINER_NAME"
  fi
  exit 0
fi
if [ "$1" = wait ]; then
  : >"$YAP_TEST_CONTAINER_EXITED"
  printf '%s\n' 0
  exit 0
fi
if [ "$1" = logs ]; then
  test "${@: -1}" = "$YAP_TEST_CONTAINER_ID"
  test -e "$YAP_TEST_CONTAINER_EXISTS"
  printf '%s\n' logs >>"$YAP_TEST_DOCKER_TRACE"
  exit 0
fi
if [ "$1" = stop ]; then
  exit 0
fi
if [ "$1" = rm ]; then
  test "${@: -1}" = "$YAP_TEST_CONTAINER_ID"
  grep -qx logs "$YAP_TEST_DOCKER_TRACE"
  printf '%s\n' rm >>"$YAP_TEST_DOCKER_TRACE"
  /bin/rm -f -- "$YAP_TEST_CONTAINER_EXISTS"
  exit 0
fi
exit 97
""",
                encoding="utf-8",
                newline="\n",
            )
            fake_docker.chmod(0o700)
            harness = f"""
set -euo pipefail
source {shlex.quote(_bash_path(PROCESS_GROUP_HELPER))}
source {shlex.quote(_bash_path(PROXY_HELPER))}
PATH={shlex.quote(_bash_path(root))}:$PATH
export PATH
export YAP_TEST_CONTAINER_ID={CONTAINER_ID}
export YAP_TEST_OWNER_TOKEN={OWNER_TOKEN}
export YAP_TEST_CONTAINER_NAME=yap-test-provider
export YAP_TEST_CONTAINER_EXISTS={shlex.quote(paths["container-exists"])}
export YAP_TEST_CONTAINER_EXITED={shlex.quote(paths["container-exited"])}
export YAP_TEST_DOCKER_TRACE={shlex.quote(paths["docker-trace"])}
listener={shlex.quote(paths["listener"])}
proxy_group_file={shlex.quote(paths["proxy.pgid"])}
ss() {{
  if [ -e "$listener" ]; then
    printf '%s\\n' 'LISTEN 0 32 127.0.0.1:18000 0.0.0.0:*'
  fi
}}
if run_private_container_with_loopback_proxy \
  yap-test-provider yap-test-network 18000 8000 "{OWNER_TOKEN}" \
  "$proxy_group_file" -- \
  docker container create test-image; then
  launcher_status=0
else
  launcher_status="$?"
fi
test "$launcher_status" -eq 0
test "$(cat {shlex.quote(paths["docker-trace"])})" = $'logs\\nrm'
test ! -e {shlex.quote(paths["container-exists"])}
test ! -e "$proxy_group_file.container-recovery"
test ! -e "$proxy_group_file.container-recovery.part"
test ! -e "$proxy_group_file.container-id"
test ! -e "$proxy_group_file"
test ! -e "$proxy_group_file.supervisor-state"
test ! -e "$proxy_group_file.supervisor-result"
"""
            self._run_linux_harness(bash, harness, timeout=30)

    def test_supervised_term_bounds_hung_docker_probe_and_removes_container(
        self,
    ) -> None:
        bash = find_linux_bash()
        if bash is None:
            self.skipTest(
                "Linux-compatible bash is unavailable for the hung-probe replay"
            )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = {
                name: _bash_path(root / name)
                for name in (
                    "container-exists",
                    "container-stop",
                    "docker-wait-ready",
                    "hung-probe",
                    "launcher-log",
                    "listener",
                    "outer-result",
                    "outer-state",
                    "proxy-stop",
                    "proxy.pgid",
                )
            }
            fake_socat = root / "socat"
            fake_socat.write_text(
                "#!/usr/bin/env bash\n"
                f"proxy_stop={shlex.quote(paths['proxy-stop'])}\n"
                f"listener={shlex.quote(paths['listener'])}\n"
                "trap ': >\"$proxy_stop\"; exit 0' TERM INT HUP\n"
                ': >"$listener"\n'
                'while [ ! -e "$proxy_stop" ]; do sleep 0.05; done\n',
                encoding="utf-8",
                newline="\n",
            )
            fake_socat.chmod(0o700)
            fake_docker = root / "docker"
            fake_docker.write_text(
                """#!/usr/bin/env bash
set -euo pipefail
if [ "$1" = container ] && [ "$2" = create ]; then
  : >"$YAP_TEST_CONTAINER_EXISTS"
  printf '%s\n' "$YAP_TEST_CONTAINER_ID" >"$4"
  printf '%s\n' "$YAP_TEST_CONTAINER_ID"
  exit 0
fi
if [ "$1" = container ] && [ "$2" = start ]; then
  exit 0
fi
if [ "$1" = container ] && [ "$2" = inspect ]; then
  if [ -e "$YAP_TEST_DOCKER_WAIT_READY" ]; then
    : >"$YAP_TEST_HUNG_PROBE"
    sleep 60
  fi
  if [ ! -e "$YAP_TEST_CONTAINER_EXISTS" ]; then
    exit 1
  fi
  case "$*" in
    *'{{.Id}}|'*) printf '%s|%s|/%s\n' \
      "$YAP_TEST_CONTAINER_ID" "$YAP_TEST_OWNER_TOKEN" "$YAP_TEST_CONTAINER_NAME" ;;
    *'{{.State.Running}}'*) printf '%s\n' true ;;
    *'{{.HostConfig.NetworkMode}}'*) printf '%s\n' yap-test-network ;;
    *NetworkSettings.Networks*) printf '%s\n' 172.19.0.2 ;;
    *) exit 0 ;;
  esac
  exit 0
fi
if [ "$1" = container ] && [ "$2" = ls ]; then
  if [ -e "$YAP_TEST_CONTAINER_EXISTS" ]; then
    printf '%s|%s\n' "$YAP_TEST_CONTAINER_ID" "$YAP_TEST_CONTAINER_NAME"
  fi
  exit 0
fi
if [ "$1" = logs ]; then
  sleep 60
fi
if [ "$1" = wait ]; then
  : >"$YAP_TEST_DOCKER_WAIT_READY"
  while [ ! -e "$YAP_TEST_CONTAINER_STOP" ]; do sleep 0.05; done
  printf '%s\n' 143
  exit 0
fi
if [ "$1" = stop ] || [ "$1" = rm ]; then
  printf '%s\n' "${@: -1}" >"$YAP_TEST_CONTAINER_STOP"
  rm -f -- "$YAP_TEST_CONTAINER_EXISTS"
  exit 0
fi
exit 97
""",
                encoding="utf-8",
                newline="\n",
            )
            fake_docker.chmod(0o700)
            launcher = root / "launcher.sh"
            launcher.write_text(
                (
                    "#!/usr/bin/env bash\n"
                    "set -euo pipefail\n"
                    f"source {shlex.quote(_bash_path(PROCESS_GROUP_HELPER))}\n"
                    f"source {shlex.quote(_bash_path(PROXY_HELPER))}\n"
                    f"PATH={shlex.quote(_bash_path(root))}:$PATH\n"
                    "export PATH\n"
                    f"export YAP_TEST_CONTAINER_ID={CONTAINER_ID}\n"
                    f"export YAP_TEST_OWNER_TOKEN={OWNER_TOKEN}\n"
                    "export YAP_TEST_CONTAINER_NAME=yap-test-provider\n"
                    f"export YAP_TEST_CONTAINER_EXISTS={shlex.quote(paths['container-exists'])}\n"
                    f"export YAP_TEST_CONTAINER_STOP={shlex.quote(paths['container-stop'])}\n"
                    f"export YAP_TEST_DOCKER_WAIT_READY={shlex.quote(paths['docker-wait-ready'])}\n"
                    f"export YAP_TEST_HUNG_PROBE={shlex.quote(paths['hung-probe'])}\n"
                    "ss() {\n"
                    f"  if [ -e {shlex.quote(paths['listener'])} ] "
                    f"&& [ ! -e {shlex.quote(paths['container-stop'])} ] "
                    f"&& [ ! -e {shlex.quote(paths['proxy-stop'])} ]; then\n"
                    "    printf '%s\\n' "
                    "'LISTEN 0 32 127.0.0.1:18000 0.0.0.0:*'\n"
                    "  fi\n"
                    "}\n"
                    "run_private_container_with_loopback_proxy "
                    "yap-test-provider yap-test-network 18000 8000 "
                    f"{OWNER_TOKEN} {shlex.quote(paths['proxy.pgid'])} -- "
                    "docker container create test-image\n"
                ),
                encoding="utf-8",
                newline="\n",
            )
            launcher.chmod(0o700)
            harness = f"""
set -euo pipefail
source {shlex.quote(_bash_path(PROCESS_GROUP_HELPER))}
control_fd=
reap_pid=
child_pid=
yap_start_owned_process_group \
  control_fd reap_pid child_pid \
  {shlex.quote(paths["outer-state"])} \
  {shlex.quote(paths["outer-result"])} \
  {shlex.quote(paths["launcher-log"])} \
  {shlex.quote(paths["launcher-log"])} \
  {OWNER_TOKEN} "hung Docker probe launcher" \
  -- bash {shlex.quote(_bash_path(launcher))}
deadline=$((SECONDS + 10))
while [ ! -e {shlex.quote(paths["docker-wait-ready"])} ]; do
  test "$SECONDS" -lt "$deadline"
  sleep 0.05
done
started_at="$SECONDS"
process_status=125
yap_stop_owned_process_group \
  process_status control_fd "$reap_pid" "$child_pid" \
  {shlex.quote(paths["outer-state"])} \
  {shlex.quote(paths["outer-result"])} \
  "hung Docker probe launcher"
test "$process_status" -eq 143
test $((SECONDS - started_at)) -lt 10
test -z "$control_fd"
test -z "$(yap_process_group_members "$child_pid")"
test -e {shlex.quote(paths["container-stop"])}
test -e {shlex.quote(paths["hung-probe"])}
test ! -e {shlex.quote(paths["container-exists"])}
test ! -e {shlex.quote(paths["outer-state"])}
test ! -e {shlex.quote(paths["outer-result"])}
"""
            self._run_linux_harness(bash, harness, timeout=30)

    def test_term_to_outer_launcher_retires_owned_runtime(self) -> None:
        bash = find_linux_bash()
        if bash is None:
            self.skipTest(
                "Linux-compatible bash is unavailable for the shell TERM replay"
            )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake_socat = root / "socat"
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
            fake_socat.write_text(
                "#!/usr/bin/env bash\n"
                f"proxy_stop={shlex.quote(paths['proxy-stop'])}\n"
                f"listener={shlex.quote(paths['listener'])}\n"
                "trap ': >\"$proxy_stop\"; exit 0' TERM INT HUP\n"
                ': >"$listener"\n'
                'while [ ! -e "$proxy_stop" ]; do sleep 0.05; done\n',
                encoding="utf-8",
                newline="\n",
            )
            fake_socat.chmod(0o700)
            fake_docker = root / "docker"
            fake_docker.write_text(
                """#!/usr/bin/env bash
set -euo pipefail
if [ "$1" = container ] && [ "$2" = create ]; then
  printf '%s\n' "$YAP_TEST_CONTAINER_ID" >"$4"
  printf '%s\n' "$YAP_TEST_CONTAINER_ID"
  exit 0
fi
if [ "$1" = container ] && [ "$2" = start ]; then
  exit 0
fi
if [ "$1" = container ] && [ "$2" = inspect ]; then
  if [ -e "$YAP_TEST_CONTAINER_STOP" ]; then
    exit 1
  fi
  case "$*" in
    *'{{.Id}}|'*) printf '%s|%s|/%s\n' \
      "$YAP_TEST_CONTAINER_ID" "$YAP_TEST_OWNER_TOKEN" "$YAP_TEST_CONTAINER_NAME" ;;
    *'{{.State.Running}}'*) printf '%s\n' true ;;
    *'{{.HostConfig.NetworkMode}}'*) printf '%s\n' yap-test-network ;;
    *NetworkSettings.Networks*) printf '%s\n' 172.19.0.2 ;;
    *) exit 0 ;;
  esac
  exit 0
fi
if [ "$1" = container ] && [ "$2" = ls ]; then
  exit 0
fi
if [ "$1" = logs ]; then
  exit 0
fi
if [ "$1" = wait ]; then
  : >"$YAP_TEST_DOCKER_WAIT_READY"
  while [ ! -e "$YAP_TEST_CONTAINER_STOP" ]; do sleep 0.05; done
  printf '%s\n' 143
  exit 0
fi
if [ "$1" = stop ] || [ "$1" = kill ] || [ "$1" = rm ]; then
  printf '%s\n' "${@: -1}" >"$YAP_TEST_CONTAINER_STOP"
  exit 0
fi
exit 97
""",
                encoding="utf-8",
                newline="\n",
            )
            fake_docker.chmod(0o700)
            harness = f"""
PATH={shlex.quote(_bash_path(root))}:$PATH
export PATH
container_stop={shlex.quote(paths["container-stop"])}
docker_wait_ready={shlex.quote(paths["docker-wait-ready"])}
listener={shlex.quote(paths["listener"])}
proxy_stop={shlex.quote(paths["proxy-stop"])}
proxy_group={shlex.quote(paths["proxy.pgid"])}
export container_stop docker_wait_ready listener proxy_stop proxy_group
export YAP_TEST_CONTAINER_ID={CONTAINER_ID}
export YAP_TEST_OWNER_TOKEN={OWNER_TOKEN}
export YAP_TEST_CONTAINER_NAME=yap-test-provider
export YAP_TEST_CONTAINER_STOP="$container_stop"
export YAP_TEST_DOCKER_WAIT_READY="$docker_wait_ready"
ss() {{
  if [ -e "$listener" ] \
    && [ ! -e "$container_stop" ] \
    && [ ! -e "$proxy_stop" ]; then
    printf '%s\\n' 'LISTEN 0 32 127.0.0.1:18000 0.0.0.0:*'
  fi
}}

run_private_container_with_loopback_proxy \
  yap-test-provider yap-test-network 18000 8000 "{OWNER_TOKEN}" \
  "$proxy_group" -- \
  docker container create test-image
"""
            launcher_path = root / "launcher.sh"
            launcher_path.write_text(
                (
                    "set -euo pipefail\n"
                    f"source {shlex.quote(_bash_path(PROCESS_GROUP_HELPER))}\n"
                    f"source {shlex.quote(_bash_path(PROXY_HELPER))}\n" + harness
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

    def _run_linux_harness(
        self,
        bash: str,
        harness: str,
        *,
        timeout: int,
    ) -> None:
        try:
            completed = subprocess.run(
                [bash],
                input=harness.encode("utf-8"),
                check=False,
                capture_output=True,
                timeout=timeout,
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
