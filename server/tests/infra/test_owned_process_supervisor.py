from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from tests.infra import linux_bash
from tests.infra.linux_bash import find_linux_bash


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PROCESS_GROUP_HELPER = (
    REPOSITORY_ROOT / "infra" / "yap-server-node" / "owned-process-group.sh"
)
SUPERVISOR = (
    REPOSITORY_ROOT / "infra" / "yap-server-node" / "owned-process-supervisor.py"
)
OWNER_TOKEN = "d" * 64


def load_supervisor_module():
    specification = importlib.util.spec_from_file_location(
        "owned_process_supervisor",
        SUPERVISOR,
    )
    if specification is None or specification.loader is None:
        raise AssertionError("owned-process supervisor could not be loaded")
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


class OwnedProcessSupervisorTests(unittest.TestCase):
    def test_linux_bash_discovery_allows_cold_wsl_startup(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["bash"],
            returncode=0,
        )
        linux_bash.find_linux_bash.cache_clear()
        try:
            with (
                mock.patch.object(
                    linux_bash.shutil,
                    "which",
                    return_value="bash",
                ),
                mock.patch.object(
                    linux_bash.subprocess,
                    "run",
                    return_value=completed,
                ) as run,
            ):
                self.assertEqual(linux_bash.find_linux_bash(), "bash")
        finally:
            linux_bash.find_linux_bash.cache_clear()
        self.assertEqual(
            run.call_args.kwargs["timeout"],
            linux_bash.LINUX_BASH_DISCOVERY_TIMEOUT_SECONDS,
        )
        self.assertEqual(linux_bash.LINUX_BASH_DISCOVERY_TIMEOUT_SECONDS, 30)

    def test_already_exited_unbound_child_is_still_reaped(self) -> None:
        module = load_supervisor_module()
        with mock.patch.object(module.os, "getuid", return_value=1000, create=True):
            supervisor = module.OwnedProcessSupervisor(
                owner_token=OWNER_TOKEN,
                description="already-exited child test",
                paths=module.SupervisorPaths(
                    state_file=Path("unused-state"),
                    result_file=Path("unused-result"),
                    stdout_path=None,
                    stderr_path=None,
                ),
                command=("unused-command",),
                stdout_descriptor=None,
                stderr_descriptor=None,
            )
        supervisor.child_pid = 4242
        supervisor.child_pidfd = 99
        with (
            mock.patch.object(
                module,
                "boot_uptime_centiseconds",
                return_value=100,
            ),
            mock.patch.object(module.signal, "SIGKILL", 9, create=True),
            mock.patch.object(
                module.signal,
                "pidfd_send_signal",
                side_effect=ProcessLookupError(4242),
                create=True,
            ),
            mock.patch.object(supervisor, "wait_for_exit", return_value=True),
            mock.patch.object(supervisor, "reap_child", return_value=143) as reap,
        ):
            self.assertEqual(supervisor.stop_and_reap(), (0, 143))
        reap.assert_called_once_with()

    def test_post_reap_cleanup_failure_cannot_be_downgraded(self) -> None:
        module = load_supervisor_module()
        with mock.patch.object(module.os, "getuid", return_value=1000, create=True):
            supervisor = module.OwnedProcessSupervisor(
                owner_token=OWNER_TOKEN,
                description="cleanup failure latch test",
                paths=module.SupervisorPaths(
                    state_file=Path("unused-state"),
                    result_file=Path("unused-result"),
                    stdout_path=None,
                    stderr_path=None,
                ),
                command=("unused-command",),
                stdout_descriptor=None,
                stderr_descriptor=None,
            )
        supervisor.child_pid = 4242
        supervisor.child_pidfd = 99

        def fail_after_reap() -> tuple[int, int]:
            supervisor.reaped = True
            supervisor.reaped_process_status = 143
            raise module.SupervisorError("owned process group remained after reap")

        with mock.patch.object(
            supervisor,
            "_stop_and_reap_once",
            side_effect=fail_after_reap,
        ):
            with self.assertRaisesRegex(
                module.SupervisorError,
                "remained after reap",
            ):
                supervisor.stop_and_reap()

        self.assertTrue(supervisor.cleanup_failure_latched)
        self.assertEqual(supervisor.stop_and_reap(), (1, 143))

    def test_natural_exit_post_reap_failure_cannot_be_downgraded(self) -> None:
        module = load_supervisor_module()
        expected = module.ProcessIdentity(
            pid=4242,
            parent_pid=40,
            process_group_id=4242,
            session_id=4242,
            state="Z",
            thread_count=1,
            start_ticks=100,
            user_id=1000,
        )
        with mock.patch.object(module.os, "getuid", return_value=1000, create=True):
            supervisor = module.OwnedProcessSupervisor(
                owner_token=OWNER_TOKEN,
                description="natural cleanup failure latch test",
                paths=module.SupervisorPaths(
                    state_file=Path("unused-state"),
                    result_file=Path("unused-result"),
                    stdout_path=None,
                    stderr_path=None,
                ),
                command=("unused-command",),
                stdout_descriptor=None,
                stderr_descriptor=None,
            )
        supervisor.child_pid = expected.pid
        supervisor.child_pidfd = 99
        supervisor.child_identity = expected

        def reap_child() -> int:
            supervisor.reaped = True
            supervisor.reaped_process_status = 7
            return 7

        with (
            mock.patch.object(
                module,
                "process_group_members",
                side_effect=((), OSError("post-reap inventory failed")),
            ),
            mock.patch.object(supervisor, "reap_child", side_effect=reap_child),
        ):
            with self.assertRaisesRegex(OSError, "post-reap inventory failed"):
                supervisor.finish_natural_exit()

        self.assertTrue(supervisor.cleanup_failure_latched)
        self.assertEqual(supervisor.stop_and_reap(), (1, 7))

    def test_zombie_environment_access_denial_is_rechecked_as_exit(self) -> None:
        module = load_supervisor_module()
        live = module.ProcessIdentity(
            pid=4242,
            parent_pid=40,
            process_group_id=4242,
            session_id=4242,
            state="S",
            thread_count=1,
            start_ticks=100,
            user_id=1000,
        )
        zombie = module.ProcessIdentity(
            pid=4242,
            parent_pid=40,
            process_group_id=4242,
            session_id=4242,
            state="Z",
            thread_count=1,
            start_ticks=100,
            user_id=1000,
        )
        with (
            mock.patch.object(
                module,
                "process_group_members",
                return_value=(live,),
            ),
            mock.patch.object(
                module,
                "read_process_owner_token",
                side_effect=PermissionError("zombie environ"),
            ),
            mock.patch.object(
                module,
                "read_process_identity",
                return_value=zombie,
            ),
        ):
            self.assertEqual(
                module.verify_token_owned_group(4242, OWNER_TOKEN, 1000),
                (),
            )

    def test_pidfd_acquisition_failure_uses_a_bounded_nonblocking_reap(
        self,
    ) -> None:
        module = load_supervisor_module()
        with mock.patch.object(module.os, "getuid", return_value=1000, create=True):
            supervisor = module.OwnedProcessSupervisor(
                owner_token=OWNER_TOKEN,
                description="bounded pidfd failure test",
                paths=module.SupervisorPaths(
                    state_file=Path("unused-state"),
                    result_file=Path("unused-result"),
                    stdout_path=None,
                    stderr_path=None,
                ),
                command=("unused-command",),
                stdout_descriptor=None,
                stderr_descriptor=None,
            )
        with (
            mock.patch.object(module.os, "O_CLOEXEC", 1, create=True),
            mock.patch.object(module.os, "O_NONBLOCK", 2, create=True),
            mock.patch.object(module.os, "WNOHANG", 1, create=True),
            mock.patch.object(
                module.os,
                "pipe2",
                side_effect=((10, 11), (12, 13)),
                create=True,
            ),
            mock.patch.object(module.os, "fork", return_value=4242, create=True),
            mock.patch.object(module.os, "close"),
            mock.patch.object(
                module.os,
                "pidfd_open",
                side_effect=OSError("pidfd unavailable"),
                create=True,
            ),
            mock.patch.object(
                module.os,
                "waitpid",
                return_value=(0, 0),
            ) as waitpid,
            mock.patch.object(
                module,
                "boot_uptime_centiseconds",
                side_effect=(100, 100, 601),
            ),
            mock.patch.object(module.select, "select", return_value=([], [], [])),
        ):
            with self.assertRaisesRegex(
                module.SupervisorError,
                "bounded pidfd acquisition failure",
            ):
                supervisor.launch_behind_barrier()
        waitpid.assert_called_once_with(4242, 1)

    def test_closed_control_pipe_never_terminates_the_bash_owner(self) -> None:
        bash = find_linux_bash()
        if bash is None:
            self.skipTest("Linux-compatible bash is unavailable for the SIGPIPE replay")

        with tempfile.TemporaryDirectory() as temporary:
            marker = _bash_path(Path(temporary) / "caller-survived")
            harness = f"""
set -euo pipefail
source {shlex.quote(_bash_path(PROCESS_GROUP_HELPER))}
exec {{control_fd}}> >(exit 0)
reader_pid="$!"
wait "$reader_pid"
if _yap_write_owned_process_control "$control_fd" RELEASE; then
  exit 91
fi
: >{shlex.quote(marker)}
_yap_close_owned_process_control "$control_fd"
"""
            self._run_linux_harness(bash, harness, timeout=10)
            self.assertTrue(Path(temporary, "caller-survived").is_file())

    def test_public_exec_failure_survives_and_reaps_without_records(self) -> None:
        bash = find_linux_bash()
        if bash is None:
            self.skipTest(
                "Linux-compatible bash is unavailable for the exec-failure replay"
            )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = f"""
set -euo pipefail
source {shlex.quote(_bash_path(PROCESS_GROUP_HELPER))}
state_file={shlex.quote(_bash_path(root / "state"))}
result_file={shlex.quote(_bash_path(root / "result"))}
for iteration in {{1..20}}; do
  control_fd=
  reap_pid=
  child_pid=
  set +e
  yap_start_owned_process_group \
    control_fd reap_pid child_pid \
    "$state_file" "$result_file" - - \
    {shlex.quote(OWNER_TOKEN)} "exec failure test $iteration" \
    -- /definitely/not/a/yap/executable
  start_status="$?"
  set -e
  test "$start_status" -eq 1
  test -z "$control_fd"
  test -z "$reap_pid"
  test -z "$child_pid"
  test ! -e "$state_file"
  test ! -e "$result_file"
done
: >{shlex.quote(_bash_path(root / "caller-survived"))}
"""
            # Twenty real fork/exec/reap cycles can cross the Windows-to-WSL
            # bridge. The lifecycle assertions own their individual bounds;
            # this outer test budget only prevents a loaded bridge from
            # truncating the final cycle.
            self._run_linux_harness(bash, harness, timeout=30)
            self.assertTrue((root / "caller-survived").is_file())

    def test_public_setup_rejects_fifo_output_without_hanging(self) -> None:
        bash = find_linux_bash()
        if bash is None:
            self.skipTest("Linux-compatible bash is unavailable for the FIFO replay")

        harness = f"""
set -euo pipefail
source {shlex.quote(_bash_path(PROCESS_GROUP_HELPER))}
linux_root="$(mktemp -d)"
trap 'rm -rf -- "$linux_root"' EXIT
state_file="$linux_root/state"
result_file="$linux_root/result"
output_file="$linux_root/output-fifo"
mkfifo "$output_file"
control_fd=
reap_pid=
child_pid=
started_at="$SECONDS"
set +e
yap_start_owned_process_group \
  control_fd reap_pid child_pid \
  "$state_file" "$result_file" "$output_file" - \
  {shlex.quote(OWNER_TOKEN)} "FIFO setup test" \
  -- sleep 60
start_status="$?"
set -e
test "$start_status" -eq 1
test $((SECONDS - started_at)) -le 3
test -z "$control_fd"
test -z "$reap_pid"
test -z "$child_pid"
test ! -e "$state_file"
test ! -e "$result_file"
test -p "$output_file"
"""
        self._run_linux_harness(bash, harness, timeout=10)

    def test_isolated_python_ignores_ambient_sitecustomize(self) -> None:
        bash = find_linux_bash()
        if bash is None:
            self.skipTest(
                "Linux-compatible bash is unavailable for the isolated-Python replay"
            )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            site_directory = root / "ambient"
            site_directory.mkdir()
            marker = root / "ambient-imported"
            (site_directory / "sitecustomize.py").write_text(
                f"from pathlib import Path\nPath({_bash_path(marker)!r}).touch()\n",
                encoding="utf-8",
                newline="\n",
            )
            harness = f"""
set -euo pipefail
source {shlex.quote(_bash_path(PROCESS_GROUP_HELPER))}
export PYTHONPATH={shlex.quote(_bash_path(site_directory))}
state_file={shlex.quote(_bash_path(root / "state"))}
result_file={shlex.quote(_bash_path(root / "result"))}
control_fd=
reap_pid=
child_pid=
yap_start_owned_process_group \
  control_fd reap_pid child_pid \
  "$state_file" "$result_file" - - \
  {shlex.quote(OWNER_TOKEN)} "isolated Python test" \
  -- sleep 60
process_status=125
yap_stop_owned_process_group \
  process_status control_fd "$reap_pid" "$child_pid" \
  "$state_file" "$result_file" "isolated Python test"
test ! -e {shlex.quote(_bash_path(marker))}
"""
            self._run_linux_harness(bash, harness, timeout=30)

    def test_missing_result_supervisor_crash_recovers_token_owned_descendants(
        self,
    ) -> None:
        bash = find_linux_bash()
        if bash is None:
            self.skipTest(
                "Linux-compatible bash is unavailable for the crash-recovery replay"
            )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = f"""
set -euo pipefail
source {shlex.quote(_bash_path(PROCESS_GROUP_HELPER))}
state_file={shlex.quote(_bash_path(root / "state"))}
result_file={shlex.quote(_bash_path(root / "result"))}
control_fd=
reap_pid=
child_pid=
yap_start_owned_process_group \
  control_fd reap_pid child_pid \
  "$state_file" "$result_file" - - \
  {shlex.quote(OWNER_TOKEN)} "missing result recovery test" \
  -- bash -c 'sleep 60 & wait'
test -n "$(yap_process_group_members "$child_pid")"
kill -KILL "$reap_pid"
deadline=$((SECONDS + 5))
while ps -o stat= -p "$reap_pid" 2>/dev/null | grep -qv '^Z'; do
  test "$SECONDS" -lt "$deadline"
  sleep 0.05
done
test ! -e "$result_file"
yap_recover_owned_process_group \
  control_fd "$reap_pid" "$child_pid" "$state_file" "$result_file" \
  {shlex.quote(OWNER_TOKEN)} "missing result recovery test"
test -z "$control_fd"
test -z "$(yap_process_group_members "$child_pid")"
test ! -e "$state_file"
test ! -e "$result_file"
"""
            self._run_linux_harness(bash, harness, timeout=30)

    def test_control_stop_before_exec_reaps_without_releasing_target(self) -> None:
        bash = find_linux_bash()
        if bash is None:
            self.skipTest("Linux-compatible bash is unavailable for the pidfd replay")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state_file = _bash_path(root / "state")
            result_file = _bash_path(root / "result")
            exec_marker = _bash_path(root / "exec-marker")
            harness = f"""
set -euo pipefail
state_file={shlex.quote(state_file)}
result_file={shlex.quote(result_file)}
exec_marker={shlex.quote(exec_marker)}
exec {{control_fd}}> >(
  YAP_RUNTIME_OWNER_TOKEN={shlex.quote(OWNER_TOKEN)} \
    exec /usr/bin/python3.12 -I -S {shlex.quote(_bash_path(SUPERVISOR))} \
      --state-file "$state_file" \
      --result-file "$result_file" \
      --description "pre-exec cancellation test" \
      --stdout-path - \
      --stderr-path - \
      -- bash -c ': >"$1"; sleep 60' bash "$exec_marker"
)
supervisor_pid="$!"
deadline=$((SECONDS + 3))
while [ ! -s "$state_file" ]; do
  test "$SECONDS" -lt "$deadline"
  sleep 0.01
done
read -r version state child_pid start_ticks recorded_supervisor observed_at \
  <"$state_file"
test "$version" -eq 1
test "$state" = bound
test "$recorded_supervisor" = "$supervisor_pid"
printf 'STOP\\n' >&"$control_fd"
exec {{control_fd}}>&-
supervisor_status=0
wait "$supervisor_pid" || supervisor_status="$?"
test "$supervisor_status" -eq 1
read -r version cleanup_status process_status reason <"$result_file"
test "$cleanup_status" -eq 0
test "$reason" = stopped-before-ready
test ! -e "$exec_marker"
! kill -0 "$child_pid" 2>/dev/null
test -z "$(ps -eo pid=,pgid=,stat= \
  | awk -v expected="$child_pid" \
    '$2 == expected && $3 !~ /^Z/ {{ print $1 }}')"
"""
            self._run_linux_harness(bash, harness, timeout=30)

    def test_unreleased_launch_uses_one_five_second_boot_uptime_deadline(
        self,
    ) -> None:
        bash = find_linux_bash()
        if bash is None:
            self.skipTest(
                "Linux-compatible bash is unavailable for the deadline replay"
            )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state_file = _bash_path(root / "state")
            result_file = _bash_path(root / "result")
            exec_marker = _bash_path(root / "exec-marker")
            harness = f"""
set -euo pipefail
state_file={shlex.quote(state_file)}
result_file={shlex.quote(result_file)}
exec_marker={shlex.quote(exec_marker)}
uptime_centiseconds() {{
  awk '{{
    split($1, parts, ".")
    printf "%d\\n", parts[1] * 100 + substr(parts[2] "00", 1, 2)
  }}' /proc/uptime
}}
started_at="$(uptime_centiseconds)"
exec {{control_fd}}> >(
  YAP_RUNTIME_OWNER_TOKEN={shlex.quote(OWNER_TOKEN)} \
    exec /usr/bin/python3.12 -I -S {shlex.quote(_bash_path(SUPERVISOR))} \
      --state-file "$state_file" \
      --result-file "$result_file" \
      --description "ownership deadline test" \
      --stdout-path - \
      --stderr-path - \
      -- bash -c ': >"$1"' bash "$exec_marker"
)
supervisor_pid="$!"
supervisor_status=0
wait "$supervisor_pid" || supervisor_status="$?"
finished_at="$(uptime_centiseconds)"
exec {{control_fd}}>&- || true
elapsed=$((finished_at - started_at))
test "$supervisor_status" -eq 1
test "$elapsed" -ge 500
test "$elapsed" -le 650
read -r version cleanup_status process_status reason <"$result_file"
test "$cleanup_status" -eq 0
test "$reason" = ownership-failed
test ! -e "$exec_marker"
"""
            self._run_linux_harness(bash, harness, timeout=30)

    def test_public_start_and_stop_retire_the_complete_owned_group(self) -> None:
        bash = find_linux_bash()
        if bash is None:
            self.skipTest("Linux-compatible bash is unavailable for the group replay")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = f"""
set -euo pipefail
source {shlex.quote(_bash_path(PROCESS_GROUP_HELPER))}
state_file={shlex.quote(_bash_path(root / "state"))}
result_file={shlex.quote(_bash_path(root / "result"))}
control_fd=
reap_pid=
child_pid=
yap_start_owned_process_group \
  control_fd reap_pid child_pid \
  "$state_file" "$result_file" - - \
  {shlex.quote(OWNER_TOKEN)} "complete group test" \
  -- bash -c 'sleep 60 & wait'
test -n "$(yap_process_group_members "$child_pid")"
process_status=125
yap_stop_owned_process_group \
  process_status control_fd "$reap_pid" "$child_pid" \
  "$state_file" "$result_file" "complete group test"
test "$process_status" -eq 143
test -z "$control_fd"
test -z "$(yap_process_group_members "$child_pid")"
test ! -e "$state_file"
test ! -e "$result_file"
"""
            self._run_linux_harness(bash, harness, timeout=30)

    def test_public_wait_returns_natural_exit_and_removes_records(self) -> None:
        bash = find_linux_bash()
        if bash is None:
            self.skipTest(
                "Linux-compatible bash is unavailable for the natural-exit replay"
            )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = f"""
set -euo pipefail
source {shlex.quote(_bash_path(PROCESS_GROUP_HELPER))}
state_file={shlex.quote(_bash_path(root / "state"))}
result_file={shlex.quote(_bash_path(root / "result"))}
control_fd=
reap_pid=
child_pid=
yap_start_owned_process_group \
  control_fd reap_pid child_pid \
  "$state_file" "$result_file" - - \
  {shlex.quote(OWNER_TOKEN)} "natural exit test" \
  -- bash -c 'sleep 0.25; exit 7'
process_status=125
yap_wait_owned_process_group \
  process_status control_fd "$reap_pid" "$child_pid" \
  "$state_file" "$result_file" 5 "natural exit test"
test "$process_status" -eq 7
test -z "$control_fd"
test -z "$(yap_process_group_members "$child_pid")"
test ! -e "$state_file"
test ! -e "$result_file"
"""
            self._run_linux_harness(bash, harness, timeout=30)

    def test_public_abort_before_release_reaps_without_exec(self) -> None:
        bash = find_linux_bash()
        if bash is None:
            self.skipTest("Linux-compatible bash is unavailable for the abort replay")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state_file = _bash_path(root / "state")
            result_file = _bash_path(root / "result")
            exec_marker = _bash_path(root / "exec-marker")
            harness = f"""
set -euo pipefail
source {shlex.quote(_bash_path(PROCESS_GROUP_HELPER))}
state_file={shlex.quote(state_file)}
result_file={shlex.quote(result_file)}
exec_marker={shlex.quote(exec_marker)}
control_fd=
exec {{control_fd}}> >(
  YAP_RUNTIME_OWNER_TOKEN={shlex.quote(OWNER_TOKEN)} \
    exec /usr/bin/python3.12 -I -S {shlex.quote(_bash_path(SUPERVISOR))} \
      --state-file "$state_file" \
      --result-file "$result_file" \
      --description "public pre-release abort test" \
      --stdout-path - \
      --stderr-path - \
      -- bash -c ': >"$1"; sleep 60' bash "$exec_marker"
)
supervisor_pid="$!"
state_record="$(
  _yap_wait_for_owned_process_record \
    "$state_file" "$result_file" bound 3 "public pre-release abort test"
)"
IFS='|' read -r state child_pid start_ticks recorded_supervisor observed_at \
  <<<"$state_record"
test "$recorded_supervisor" = "$supervisor_pid"
yap_abort_owned_process_start \
  control_fd "$supervisor_pid" "$state_file" "$result_file" \
  "public pre-release abort test"
test -z "$control_fd"
test ! -e "$exec_marker"
test ! -e "$state_file"
test ! -e "$result_file"
! kill -0 "$child_pid" 2>/dev/null
test -z "$(yap_process_group_members "$child_pid")"
"""
            self._run_linux_harness(bash, harness, timeout=30)

    def test_unowned_group_is_only_a_negative_postcondition(self) -> None:
        bash = find_linux_bash()
        if bash is None:
            self.skipTest(
                "Linux-compatible bash is unavailable for the PID-reuse replay"
            )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = f"""
set -euo pipefail
source {shlex.quote(_bash_path(PROCESS_GROUP_HELPER))}
state_file={shlex.quote(_bash_path(root / "state"))}
result_file={shlex.quote(_bash_path(root / "result"))}
sentinel_pid=
cleanup_sentinel() {{
  set +e
  if [[ "$sentinel_pid" =~ ^[0-9]+$ ]] \
    && kill -0 "$sentinel_pid" 2>/dev/null; then
    kill -KILL -- "-$sentinel_pid" 2>/dev/null || true
    wait "$sentinel_pid" 2>/dev/null || true
  fi
  rm -f -- "$state_file" "$result_file"
}}
trap cleanup_sentinel EXIT
setsid bash -c 'exec sleep 60' &
sentinel_pid="$!"
control_fd=
reap_pid=
child_pid=
yap_start_owned_process_group \
  control_fd reap_pid child_pid \
  "$state_file" "$result_file" - - \
  {shlex.quote(OWNER_TOKEN)} "unowned sentinel test" \
  -- sleep 60
process_status=125
if yap_stop_owned_process_group \
  process_status control_fd "$reap_pid" "$sentinel_pid" \
  "$state_file" "$result_file" "unowned sentinel test"; then
  exit 1
fi
test -z "$control_fd"
kill -0 "$sentinel_pid"
test -z "$(yap_process_group_members "$child_pid")"
kill -TERM -- "-$sentinel_pid"
wait "$sentinel_pid" 2>/dev/null || true
sentinel_pid=
rm -f -- "$state_file" "$result_file"
trap - EXIT
"""
            self._run_linux_harness(bash, harness, timeout=30)

    def test_controller_death_still_reaps_the_ready_owned_group(self) -> None:
        bash = find_linux_bash()
        if bash is None:
            self.skipTest(
                "Linux-compatible bash is unavailable for the parent-death replay"
            )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            controller = root / "controller.sh"
            state_file = _bash_path(root / "state")
            result_file = _bash_path(root / "result")
            identity_file = _bash_path(root / "identity")
            controller.write_text(
                (
                    "#!/usr/bin/env bash\n"
                    "set -euo pipefail\n"
                    f"source {shlex.quote(_bash_path(PROCESS_GROUP_HELPER))}\n"
                    "control_fd=\n"
                    "reap_pid=\n"
                    "child_pid=\n"
                    "yap_start_owned_process_group "
                    "control_fd reap_pid child_pid "
                    f"{shlex.quote(state_file)} "
                    f"{shlex.quote(result_file)} "
                    f"- - {shlex.quote(OWNER_TOKEN)} "
                    '"parent death test" -- sleep 60\n'
                    f'printf "%s %s\\n" "$child_pid" "$reap_pid" '
                    f">{shlex.quote(identity_file)}\n"
                    'wait "$reap_pid"\n'
                ),
                encoding="utf-8",
                newline="\n",
            )
            controller.chmod(0o700)
            harness = f"""
set -euo pipefail
controller={shlex.quote(_bash_path(controller))}
identity_file={shlex.quote(identity_file)}
result_file={shlex.quote(result_file)}
"$controller" &
controller_pid="$!"
deadline=$((SECONDS + 5))
while [ ! -s "$identity_file" ]; do
  test "$SECONDS" -lt "$deadline"
  sleep 0.01
done
read -r child_pid supervisor_pid <"$identity_file"
kill -TERM "$controller_pid"
controller_status=0
wait "$controller_pid" || controller_status="$?"
test "$controller_status" -eq 143
deadline=$((SECONDS + 20))
while kill -0 "$supervisor_pid" 2>/dev/null \
  || [ -n "$(ps -eo pid=,pgid=,stat= \
    | awk -v expected="$child_pid" \
      '$2 == expected && $3 !~ /^Z/ {{ print $1 }}')" ]; do
  test "$SECONDS" -lt "$deadline"
  sleep 0.05
done
read -r version cleanup_status process_status reason <"$result_file"
test "$cleanup_status" -eq 0
test "$reason" = controller-lost
! kill -0 "$child_pid" 2>/dev/null
"""
            self._run_linux_harness(bash, harness, timeout=30)

    def test_stale_or_contaminated_identity_is_never_a_numeric_kill_target(
        self,
    ) -> None:
        module = load_supervisor_module()
        expected = module.ProcessIdentity(
            pid=4242,
            parent_pid=40,
            process_group_id=4242,
            session_id=4242,
            state="T",
            thread_count=1,
            start_ticks=100,
            user_id=1000,
        )
        reused = module.ProcessIdentity(
            pid=4242,
            parent_pid=40,
            process_group_id=4242,
            session_id=4242,
            state="T",
            thread_count=1,
            start_ticks=101,
            user_id=1000,
        )
        extra_thread = module.ProcessIdentity(
            **{**expected.__dict__, "thread_count": 2}
        )

        self.assertFalse(module.same_process(reused, expected))
        self.assertFalse(module.pending_child_is_isolated(reused, expected, ()))
        self.assertFalse(module.pending_child_is_isolated(extra_thread, expected, ()))
        self.assertFalse(module.pending_child_is_isolated(expected, expected, (9001,)))
        self.assertTrue(module.pending_child_is_isolated(expected, expected, ()))

        syntax = ast.parse(SUPERVISOR.read_text(encoding="utf-8"))
        numeric_kills = [
            node
            for node in ast.walk(syntax)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "os"
            and node.func.attr == "kill"
        ]
        self.assertEqual(numeric_kills, [])
        source = SUPERVISOR.read_text(encoding="utf-8")
        self.assertIn("signal.pidfd_send_signal", source)
        self.assertIn("os.waitid(os.P_PIDFD", source)

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
