from __future__ import annotations

from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PROCESS_GROUP_HELPER = (
    REPOSITORY_ROOT
    / "infra"
    / "yap-server-node"
    / "owned-process-group.sh"
)
OWNER_TOKEN = "d" * 64


class OwnedProcessGroupBehaviorTests(unittest.TestCase):
    def test_recorded_group_is_retired_after_its_launcher_leader_exits(self) -> None:
        bash = shutil.which("bash")
        if bash is None:
            self.skipTest("bash is unavailable for the process-group replay")

        with tempfile.TemporaryDirectory() as temporary:
            identity_file = _bash_path(Path(temporary) / "proxy.pgid")
            harness = f"""
identity_file={shlex.quote(identity_file)}
owner_token={shlex.quote(OWNER_TOKEN)}
setsid bash -c '
  setsid env YAP_RUNTIME_OWNER_TOKEN="$1" \
    bash -c '"'"'printf "%s\\n" "$$" >"$1"; exec sleep 60'"'"' \
    bash "$2" &
  deadline=$((SECONDS + 10))
  while [ ! -f "$2" ]; do
    if [ "$SECONDS" -ge "$deadline" ]; then exit 91; fi
    sleep 0.05
  done
' bash "$owner_token" "$identity_file" &
launcher_pid="$!"
wait "$launcher_pid"
recorded_group="$(cat -- "$identity_file")"
test -n "$(yap_process_group_members "$recorded_group")"
stop_recorded_token_owned_process_group \
  "$identity_file" "$owner_token" "test proxy"
test ! -e "$identity_file"
test -z "$(yap_process_group_members "$recorded_group")"
"""
            completed = subprocess.run(
                [bash],
                input=(
                    PROCESS_GROUP_HELPER.read_text(encoding="utf-8")
                    .replace("\r\n", "\n")
                    .replace("\r", "\n")
                    + harness
                ).encode("utf-8"),
                check=False,
                capture_output=True,
                timeout=30,
            )

            self.assertEqual(
                completed.returncode,
                0,
                (completed.stdout + completed.stderr).decode(
                    "utf-8",
                    errors="replace",
                ),
            )

    def test_recorded_group_with_another_owner_is_not_signalled(self) -> None:
        bash = shutil.which("bash")
        if bash is None:
            self.skipTest("bash is unavailable for the process-group replay")

        with tempfile.TemporaryDirectory() as temporary:
            identity_file = _bash_path(Path(temporary) / "foreign.pgid")
            harness = f"""
identity_file={shlex.quote(identity_file)}
expected_owner={shlex.quote(OWNER_TOKEN)}
foreign_owner={"e" * 64}
setsid env YAP_RUNTIME_OWNER_TOKEN="$foreign_owner" \
  bash -c 'printf "%s\\n" "$$" >"$1"; exec sleep 60' \
  bash "$identity_file" &
group="$!"
deadline=$((SECONDS + 10))
while [ ! -f "$identity_file" ]; do
  if [ "$SECONDS" -ge "$deadline" ]; then exit 91; fi
  sleep 0.05
done
set +e
stop_recorded_token_owned_process_group \
  "$identity_file" "$expected_owner" "foreign test proxy"
status="$?"
set -e
test "$status" -eq 1
test -e "$identity_file"
test -n "$(yap_process_group_members "$group")"
kill -TERM -- "-$group"
wait "$group" 2>/dev/null || true
"""
            completed = subprocess.run(
                [bash],
                input=(
                    PROCESS_GROUP_HELPER.read_text(encoding="utf-8")
                    .replace("\r\n", "\n")
                    .replace("\r", "\n")
                    + harness
                ).encode("utf-8"),
                check=False,
                capture_output=True,
                timeout=30,
            )

            self.assertEqual(
                completed.returncode,
                0,
                (completed.stdout + completed.stderr).decode(
                    "utf-8",
                    errors="replace",
                ),
            )

    def test_inventory_failure_retains_the_recorded_identity(self) -> None:
        bash = shutil.which("bash")
        if bash is None:
            self.skipTest("bash is unavailable for the process-group replay")

        with tempfile.TemporaryDirectory() as temporary:
            identity_file = _bash_path(Path(temporary) / "inventory-failed.pgid")
            harness = f"""
set -euo pipefail
identity_file={shlex.quote(identity_file)}
printf '%s\\n' 424242 >"$identity_file"
ps() {{ return 1; }}
set +e
stop_recorded_token_owned_process_group \
  "$identity_file" "{OWNER_TOKEN}" "inventory test proxy"
status="$?"
set -e
test "$status" -eq 1
test -e "$identity_file"
"""
            completed = subprocess.run(
                [bash],
                input=(
                    PROCESS_GROUP_HELPER.read_text(encoding="utf-8")
                    .replace("\r\n", "\n")
                    .replace("\r", "\n")
                    + harness
                ).encode("utf-8"),
                check=False,
                capture_output=True,
                timeout=30,
            )

            self.assertEqual(
                completed.returncode,
                0,
                (completed.stdout + completed.stderr).decode(
                    "utf-8",
                    errors="replace",
                ),
            )

    def test_targeted_recheck_failure_never_signals_a_live_member(self) -> None:
        bash = shutil.which("bash")
        if bash is None:
            self.skipTest("bash is unavailable for the process-group replay")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            identity_file = _bash_path(root / "recheck-failed.pgid")
            signal_marker = _bash_path(root / "signal-attempted")
            harness = f"""
set -euo pipefail
identity_file={shlex.quote(identity_file)}
signal_marker={shlex.quote(signal_marker)}
printf '%s\\n' 424242 >"$identity_file"
ps() {{
  if [ "$1" = "-eo" ]; then
    printf '%s\\n' "$$ 424242 S"
    return 0
  fi
  return 1
}}
kill() {{
  if [ "$1" = "-0" ]; then
    return 0
  fi
  : >"$signal_marker"
  return 0
}}
set +e
stop_recorded_token_owned_process_group \
  "$identity_file" "{OWNER_TOKEN}" "recheck test proxy"
status="$?"
set -e
test "$status" -eq 1
test -e "$identity_file"
test ! -e "$signal_marker"
"""
            completed = subprocess.run(
                [bash],
                input=(
                    PROCESS_GROUP_HELPER.read_text(encoding="utf-8")
                    .replace("\r\n", "\n")
                    .replace("\r", "\n")
                    + harness
                ).encode("utf-8"),
                check=False,
                capture_output=True,
                timeout=30,
            )

            self.assertEqual(
                completed.returncode,
                0,
                (completed.stdout + completed.stderr).decode(
                    "utf-8",
                    errors="replace",
                ),
            )

    def test_pre_session_direct_child_is_stopped_before_it_can_detach(self) -> None:
        bash = shutil.which("bash")
        if bash is None:
            self.skipTest("bash is unavailable for the pre-session replay")

        with tempfile.TemporaryDirectory() as temporary:
            release_file = _bash_path(Path(temporary) / "release")
            harness = f"""
set -euo pipefail
release_file={shlex.quote(release_file)}
owner_token={shlex.quote(OWNER_TOKEN)}
env YAP_RUNTIME_OWNER_TOKEN="$owner_token" bash -c '
  while [ ! -e "$1" ]; do sleep 0.05; done
  exec setsid env YAP_RUNTIME_OWNER_TOKEN="$2" sleep 60
' bash "$release_file" "$owner_token" &
child_pid="$!"
stop_owned_child_process_group \
  "$child_pid" "$owner_token" "pre-session child" "$$"
wait "$child_pid" 2>/dev/null || true
: >"$release_file"
test -z "$(yap_process_group_members "$child_pid")"
"""
            completed = subprocess.run(
                [bash],
                input=(
                    PROCESS_GROUP_HELPER.read_text(encoding="utf-8")
                    .replace("\r\n", "\n")
                    .replace("\r", "\n")
                    + harness
                ).encode("utf-8"),
                check=False,
                capture_output=True,
                timeout=30,
            )

            self.assertEqual(
                completed.returncode,
                0,
                (completed.stdout + completed.stderr).decode(
                    "utf-8",
                    errors="replace",
                ),
            )

    def test_pre_session_child_with_another_token_is_not_signalled(self) -> None:
        bash = shutil.which("bash")
        if bash is None:
            self.skipTest("bash is unavailable for the pre-session replay")

        harness = f"""
set -euo pipefail
expected_owner={shlex.quote(OWNER_TOKEN)}
foreign_owner={"e" * 64}
env YAP_RUNTIME_OWNER_TOKEN="$foreign_owner" sleep 60 &
child_pid="$!"
set +e
stop_owned_child_process_group \
  "$child_pid" "$expected_owner" "foreign pre-session child" "$$"
status="$?"
set -e
test "$status" -eq 1
kill -0 "$child_pid"
kill -TERM "$child_pid"
wait "$child_pid" 2>/dev/null || true
"""
        completed = subprocess.run(
            [bash],
            input=(
                PROCESS_GROUP_HELPER.read_text(encoding="utf-8")
                .replace("\r\n", "\n")
                .replace("\r", "\n")
                + harness
            ).encode("utf-8"),
            check=False,
            capture_output=True,
            timeout=30,
        )

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
