#!/usr/bin/env python3.12
"""Launch and reap one token-owned Linux process without PID-reuse races."""

from __future__ import annotations

import argparse
import ctypes
import errno
import os
import re
import select
import signal
import stat
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

PROTOCOL_VERSION = 1
OWNERSHIP_DEADLINE_CENTISECONDS = 500
TERM_DEADLINE_CENTISECONDS = 1_000
KILL_DEADLINE_CENTISECONDS = 500
STOP_POLL_SECONDS = 0.01
OWNER_TOKEN_PATTERN = re.compile(r"[0-9a-f]{64}")
PR_SET_PDEATHSIG = 1
LIBC = ctypes.CDLL(None, use_errno=True) if sys.platform == "linux" else None


class SupervisorError(RuntimeError):
    """A fail-closed owned-process lifecycle error."""


class ControlChannelClosed(SupervisorError):
    """The Bash owner disappeared or closed its control channel."""


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    parent_pid: int
    process_group_id: int
    session_id: int
    state: str
    thread_count: int
    start_ticks: int
    user_id: int


@dataclass(frozen=True)
class SupervisorPaths:
    state_file: Path
    result_file: Path
    stdout_path: Path | None
    stderr_path: Path | None


stop_requested = False


def request_stop(_signal_number: int, _frame: object) -> None:
    """Let the serialized lifecycle loop perform signal-safe cleanup."""

    global stop_requested
    stop_requested = True


def fail(message: str) -> NoReturn:
    print(message, file=sys.stderr)
    raise SystemExit(2)


def boot_uptime_centiseconds() -> int:
    """Return Linux boot uptime as an integer monotonic deadline clock."""

    with open("/proc/uptime", encoding="ascii") as uptime_file:
        value = uptime_file.read(64).split(maxsplit=1)[0]
    whole, separator, fraction = value.partition(".")
    if not whole.isdecimal() or (separator and fraction and not fraction.isdecimal()):
        raise SupervisorError("Linux boot uptime is invalid")
    hundredths = (fraction + "00")[:2] if separator else "00"
    return int(whole) * 100 + int(hundredths)


def set_parent_death_signal(signal_number: int) -> None:
    if LIBC is None:
        raise OSError(errno.ENOSYS, "parent-death signals require Linux")
    if LIBC.prctl(PR_SET_PDEATHSIG, signal_number, 0, 0, 0) != 0:
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number))


def read_process_identity(pid: int) -> ProcessIdentity:
    try:
        stat_text = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
        status_text = Path(f"/proc/{pid}/status").read_text(encoding="ascii")
    except (FileNotFoundError, ProcessLookupError) as error:
        raise ProcessLookupError(pid) from error
    closing_parenthesis = stat_text.rfind(") ")
    if closing_parenthesis < 0:
        raise SupervisorError(f"process {pid} has an invalid stat record")
    fields = stat_text[closing_parenthesis + 2 :].split()
    if len(fields) < 20:
        raise SupervisorError(f"process {pid} has an incomplete stat record")
    user_id: int | None = None
    for line in status_text.splitlines():
        if line.startswith("Uid:"):
            values = line.split()
            if len(values) >= 2 and values[1].isdecimal():
                user_id = int(values[1])
            break
    if user_id is None:
        raise SupervisorError(f"process {pid} has an invalid user identity")
    try:
        return ProcessIdentity(
            pid=pid,
            state=fields[0],
            parent_pid=int(fields[1]),
            process_group_id=int(fields[2]),
            session_id=int(fields[3]),
            thread_count=int(fields[17]),
            start_ticks=int(fields[19]),
            user_id=user_id,
        )
    except ValueError as error:
        raise SupervisorError(f"process {pid} has a nonnumeric identity") from error


def read_process_owner_token(pid: int) -> str | None:
    try:
        environment = Path(f"/proc/{pid}/environ").read_bytes()
    except (FileNotFoundError, ProcessLookupError) as error:
        raise ProcessLookupError(pid) from error
    prefix = b"YAP_RUNTIME_OWNER_TOKEN="
    for entry in environment.split(b"\0"):
        if entry.startswith(prefix):
            try:
                return entry[len(prefix) :].decode("ascii")
            except UnicodeDecodeError:
                return None
    return None


def read_direct_children(pid: int) -> tuple[int, ...]:
    children_path = Path(f"/proc/{pid}/task/{pid}/children")
    try:
        children = children_path.read_text(encoding="ascii").split()
    except (FileNotFoundError, ProcessLookupError) as error:
        raise ProcessLookupError(pid) from error
    if any(not child.isdecimal() for child in children):
        raise SupervisorError(f"process {pid} has an invalid child inventory")
    return tuple(int(child) for child in children)


def process_group_members(process_group_id: int) -> tuple[ProcessIdentity, ...]:
    members: list[ProcessIdentity] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdecimal():
            continue
        try:
            identity = read_process_identity(int(entry.name))
        except ProcessLookupError:
            continue
        if identity.process_group_id == process_group_id and identity.state != "Z":
            members.append(identity)
    return tuple(sorted(members, key=lambda member: member.pid))


def verify_token_owned_group(
    process_group_id: int,
    owner_token: str,
    expected_user_id: int,
) -> tuple[ProcessIdentity, ...]:
    members = process_group_members(process_group_id)
    verified_members: list[ProcessIdentity] = []
    for member in members:
        if member.user_id != expected_user_id:
            raise SupervisorError(
                "owned process group contains a different user identity"
            )
        try:
            observed_token = read_process_owner_token(member.pid)
        except ProcessLookupError:
            continue
        except PermissionError as error:
            try:
                rechecked = read_process_identity(member.pid)
            except ProcessLookupError:
                continue
            if rechecked.state == "Z" or rechecked.process_group_id != process_group_id:
                continue
            if not same_process(rechecked, member):
                raise SupervisorError(
                    "owned process group member identity changed during verification"
                ) from error
            raise SupervisorError(
                "owned process group member environment could not be verified"
            ) from error
        if observed_token != owner_token:
            raise SupervisorError("owned process group contains an unverified process")
        verified_members.append(member)
    return tuple(verified_members)


def same_process(
    observed: ProcessIdentity,
    expected: ProcessIdentity,
) -> bool:
    return (
        observed.pid == expected.pid
        and observed.start_ticks == expected.start_ticks
        and observed.parent_pid == expected.parent_pid
        and observed.user_id == expected.user_id
    )


def pending_child_is_isolated(
    observed: ProcessIdentity,
    expected: ProcessIdentity,
    direct_children: Sequence[int],
) -> bool:
    return (
        same_process(observed, expected)
        and observed.thread_count == 1
        and not direct_children
    )


def atomic_write(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.part")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
        0o600,
    )
    try:
        encoded = content.encode("ascii")
        offset = 0
        while offset < len(encoded):
            written = os.write(descriptor, encoded[offset:])
            if written == 0:
                raise SupervisorError("owned-process record write made no progress")
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)


def validate_record_destination(path: Path, description: str) -> None:
    if not path.is_absolute():
        raise SupervisorError(f"{description} must be absolute")
    parent = path.parent
    if not parent.is_dir() or parent.is_symlink():
        raise SupervisorError(f"{description} parent must be a real directory")
    if path.exists() or path.is_symlink():
        raise SupervisorError(f"{description} must not already exist")


def open_output(path: Path | None) -> int | None:
    if path is None:
        return None
    if not path.is_absolute():
        raise SupervisorError("owned-process output paths must be absolute")
    if not path.parent.is_dir() or path.parent.is_symlink():
        raise SupervisorError("owned-process output parent must be a real directory")
    descriptor = os.open(
        path,
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | os.O_CLOEXEC
        | os.O_NOFOLLOW
        | os.O_NOCTTY,
        0o600,
    )
    observed = os.fstat(descriptor)
    if not stat.S_ISREG(observed.st_mode) or observed.st_uid != os.getuid():
        os.close(descriptor)
        raise SupervisorError(
            "owned-process output must be an owner-controlled regular file"
        )
    os.fchmod(descriptor, 0o600)
    return descriptor


def wait_status_to_process_status(wait_status: int) -> int:
    exit_code = os.waitstatus_to_exitcode(wait_status)
    return exit_code if exit_code >= 0 else 128 - exit_code


def close_descriptors_except(retained: set[int]) -> None:
    for entry in Path("/proc/self/fd").iterdir():
        if not entry.name.isdecimal():
            continue
        descriptor = int(entry.name)
        if descriptor > 2 and descriptor not in retained:
            try:
                os.close(descriptor)
            except OSError:
                pass


def child_exec(
    command: Sequence[str],
    release_descriptor: int,
    exec_status_descriptor: int,
    stdout_descriptor: int | None,
    stderr_descriptor: int | None,
    supervisor_pid: int,
) -> NoReturn:
    try:
        for signal_number in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
            signal.signal(signal_number, signal.SIG_DFL)
        set_parent_death_signal(signal.SIGKILL)
        if os.getppid() != supervisor_pid:
            raise SupervisorError("owned-process supervisor disappeared before launch")
        os.setsid()
        release = os.read(release_descriptor, 1)
        if release != b"G":
            raise SupervisorError("owned-process launch was not released")
        devnull = os.open("/dev/null", os.O_RDONLY | os.O_CLOEXEC)
        os.dup2(devnull, 0)
        if stdout_descriptor is not None:
            os.dup2(stdout_descriptor, 1)
        if stderr_descriptor is not None:
            os.dup2(stderr_descriptor, 2)
        retained = {exec_status_descriptor}
        close_descriptors_except(retained)
        os.execvpe(command[0], list(command), os.environ)
    except (OSError, SupervisorError) as error:
        try:
            message = f"{type(error).__name__}: {error}".encode(
                "utf-8",
                errors="replace",
            )[:1_024]
            os.write(exec_status_descriptor, message)
        except OSError:
            os._exit(126)
        os._exit(126)


def waitid_result_to_status(result: os.waitid_result) -> int:
    if result.si_code == os.CLD_EXITED:
        return int(result.si_status)
    if result.si_code in (os.CLD_KILLED, os.CLD_DUMPED):
        return 128 + int(result.si_status)
    return 125


class OwnedProcessSupervisor:
    def __init__(
        self,
        *,
        owner_token: str,
        description: str,
        paths: SupervisorPaths,
        command: Sequence[str],
        stdout_descriptor: int | None,
        stderr_descriptor: int | None,
    ) -> None:
        self.owner_token = owner_token
        self.description = description
        self.paths = paths
        self.command = tuple(command)
        self.stdout_descriptor = stdout_descriptor
        self.stderr_descriptor = stderr_descriptor
        self.supervisor_pid = os.getpid()
        self.expected_user_id = os.getuid()
        self.child_pid: int | None = None
        self.child_pidfd: int | None = None
        self.child_identity: ProcessIdentity | None = None
        self.release_descriptor: int | None = None
        self.exec_status_descriptor: int | None = None
        self.reaped = False
        self.reaped_process_status: int | None = None
        self.cleanup_failure_latched = False
        self.ready_published = False
        self.result_written = False
        self.control_buffer = bytearray()

    def publish_state(self, state_name: str, observed_at: int) -> None:
        identity = self.require_identity()
        atomic_write(
            self.paths.state_file,
            (
                f"{PROTOCOL_VERSION} {state_name} {identity.pid} "
                f"{identity.start_ticks} {self.supervisor_pid} {observed_at}\n"
            ),
        )

    def publish_result(
        self,
        cleanup_status: int,
        process_status: int,
        reason: str,
    ) -> None:
        if self.result_written:
            return
        atomic_write(
            self.paths.result_file,
            (f"{PROTOCOL_VERSION} {cleanup_status} {process_status} {reason}\n"),
        )
        self.result_written = True

    def require_identity(self) -> ProcessIdentity:
        if self.child_identity is None:
            raise SupervisorError("owned-process identity was not captured")
        return self.child_identity

    def require_pidfd(self) -> int:
        if self.child_pidfd is None:
            raise SupervisorError("owned-process pidfd was not captured")
        return self.child_pidfd

    def launch_behind_barrier(self) -> None:
        release_read, release_write = os.pipe2(os.O_CLOEXEC)
        exec_read, exec_write = os.pipe2(os.O_CLOEXEC | os.O_NONBLOCK)
        launch_start = boot_uptime_centiseconds()
        child_pid = os.fork()
        if child_pid == 0:
            os.close(release_write)
            os.close(exec_read)
            child_exec(
                self.command,
                release_read,
                exec_write,
                self.stdout_descriptor,
                self.stderr_descriptor,
                self.supervisor_pid,
            )
        os.close(release_read)
        os.close(exec_write)
        self.child_pid = child_pid
        self.release_descriptor = release_write
        self.exec_status_descriptor = exec_read
        try:
            self.child_pidfd = os.pidfd_open(child_pid, 0)
        except OSError as error:
            os.close(release_write)
            self.release_descriptor = None
            reap_deadline = launch_start + OWNERSHIP_DEADLINE_CENTISECONDS
            while boot_uptime_centiseconds() <= reap_deadline:
                observed_pid, wait_status = os.waitpid(child_pid, os.WNOHANG)
                if observed_pid == child_pid:
                    self.reaped = True
                    self.reaped_process_status = wait_status_to_process_status(
                        wait_status
                    )
                    break
                select.select([], [], [], STOP_POLL_SECONDS)
            if not self.reaped:
                raise SupervisorError(
                    "owned process did not exit after bounded pidfd acquisition failure"
                ) from error
            raise SupervisorError("owned-process pidfd could not be opened") from error

        deadline = launch_start + OWNERSHIP_DEADLINE_CENTISECONDS
        while boot_uptime_centiseconds() <= deadline:
            if self.pidfd_has_exited():
                raise SupervisorError("owned process exited before identity binding")
            try:
                identity = read_process_identity(child_pid)
                direct_children = read_direct_children(child_pid)
            except ProcessLookupError:
                continue
            if (
                identity.parent_pid == self.supervisor_pid
                and identity.user_id == self.expected_user_id
                and identity.state != "Z"
                and identity.thread_count == 1
                and not direct_children
            ):
                if self.child_identity is None:
                    self.child_identity = identity
                elif not same_process(identity, self.child_identity):
                    raise SupervisorError(
                        "owned-process identity changed before binding"
                    )
                self.raise_if_stop_requested()
                if (
                    identity.process_group_id == child_pid
                    and identity.session_id == child_pid
                ):
                    self.publish_state("bound", boot_uptime_centiseconds())
                    self.wait_for_release(deadline)
                    return
            command = self.wait_for_control_or_exit(STOP_POLL_SECONDS)
            if command == "stop":
                raise InterruptedError("owned-process stop was requested")
            if command == "release":
                raise SupervisorError(
                    "owned-process release arrived before identity binding"
                )
        raise SupervisorError("owned-process identity deadline expired")

    def wait_for_release(self, deadline: int) -> None:
        while boot_uptime_centiseconds() <= deadline:
            command = self.wait_for_control_or_exit(STOP_POLL_SECONDS)
            if command == "release":
                if self.release_descriptor is None:
                    raise SupervisorError("owned-process release pipe is unavailable")
                os.write(self.release_descriptor, b"G")
                os.close(self.release_descriptor)
                self.release_descriptor = None
                self.wait_for_exec_and_ownership(deadline)
                return
            if command == "stop":
                raise InterruptedError("owned-process stop was requested")
        raise SupervisorError("owned-process release deadline expired")

    def wait_for_exec_and_ownership(self, deadline: int) -> None:
        exec_completed = False
        while boot_uptime_centiseconds() <= deadline:
            command = self.wait_for_control_or_exit(STOP_POLL_SECONDS)
            if command == "stop":
                raise InterruptedError("owned-process stop was requested")
            if self.exec_status_descriptor is not None:
                try:
                    report = os.read(self.exec_status_descriptor, 1_025)
                except BlockingIOError:
                    report = None
                if report == b"":
                    os.close(self.exec_status_descriptor)
                    self.exec_status_descriptor = None
                    exec_completed = True
                elif report:
                    raise SupervisorError(
                        "owned-process exec failed: "
                        + report.decode("utf-8", errors="replace")
                    )
            if exec_completed and self.ownership_is_verified():
                observed_at = boot_uptime_centiseconds()
                if observed_at > deadline:
                    break
                self.publish_state("ready", observed_at)
                self.ready_published = True
                return
        raise SupervisorError("owned-process execution deadline expired")

    def ownership_is_verified(self) -> bool:
        expected = self.require_identity()
        try:
            observed = read_process_identity(expected.pid)
            token = read_process_owner_token(expected.pid)
        except ProcessLookupError:
            return False
        if (
            not same_process(observed, expected)
            or observed.state == "Z"
            or observed.process_group_id != expected.pid
            or observed.session_id != expected.pid
            or token != self.owner_token
        ):
            return False
        try:
            members = verify_token_owned_group(
                expected.pid,
                self.owner_token,
                self.expected_user_id,
            )
        except SupervisorError:
            return False
        return any(member.pid == expected.pid for member in members)

    def wait_for_control_or_exit(self, timeout_seconds: float) -> str | None:
        self.raise_if_stop_requested()
        buffered_command = self.pop_control_command()
        if buffered_command is not None:
            return buffered_command
        descriptors = [0, self.require_pidfd()]
        if self.exec_status_descriptor is not None:
            descriptors.append(self.exec_status_descriptor)
        readable, _, _ = select.select(descriptors, [], [], timeout_seconds)
        if self.require_pidfd() in readable:
            raise ChildProcessError("owned process exited")
        if 0 not in readable:
            return None
        data = os.read(0, 4_096)
        if not data:
            raise ControlChannelClosed("owned-process control channel closed")
        self.control_buffer.extend(data)
        if len(self.control_buffer) > 4_096:
            raise SupervisorError("owned-process control record is too large")
        return self.pop_control_command()

    def pop_control_command(self) -> str | None:
        if b"\n" not in self.control_buffer:
            return None
        line, remainder = self.control_buffer.split(b"\n", maxsplit=1)
        self.control_buffer = bytearray(remainder)
        if line == b"RELEASE":
            return "release"
        if line == b"STOP":
            return "stop"
        raise SupervisorError("owned-process control record is invalid")

    def raise_if_stop_requested(self) -> None:
        if stop_requested:
            raise InterruptedError("owned-process supervisor received a stop signal")

    def pidfd_has_exited(self) -> bool:
        readable, _, _ = select.select([self.require_pidfd()], [], [], 0)
        return bool(readable)

    def wait_for_exit(self, deadline: int) -> bool:
        while boot_uptime_centiseconds() <= deadline:
            if self.pidfd_has_exited():
                return True
            select.select(
                [self.require_pidfd()],
                [],
                [],
                STOP_POLL_SECONDS,
            )
        return self.pidfd_has_exited()

    def stop_and_reap(self) -> tuple[int, int]:
        failure_was_already_latched = self.cleanup_failure_latched
        try:
            cleanup_status, process_status = self._stop_and_reap_once()
        except (OSError, SupervisorError):
            self.cleanup_failure_latched = True
            raise
        if failure_was_already_latched or self.cleanup_failure_latched:
            cleanup_status = 1
        return (cleanup_status, process_status)

    def _stop_and_reap_once(self) -> tuple[int, int]:
        if self.child_pid is None:
            return (0, 0)
        if self.reaped:
            return (0, self.reaped_process_status or 0)
        pidfd = self.require_pidfd()
        if self.child_identity is None:
            try:
                signal.pidfd_send_signal(pidfd, signal.SIGKILL)
            except ProcessLookupError:
                pass
            if not self.wait_for_exit(
                boot_uptime_centiseconds() + KILL_DEADLINE_CENTISECONDS
            ):
                raise SupervisorError("unbound owned process did not exit")
            return (0, self.reap_child())
        identity = self.require_identity()
        try:
            signal.pidfd_send_signal(pidfd, signal.SIGSTOP)
        except ProcessLookupError:
            pass
        except OSError as error:
            if error.errno != errno.ESRCH:
                raise SupervisorError("owned process could not be frozen") from error

        stop_deadline = boot_uptime_centiseconds() + 200
        observed: ProcessIdentity | None = None
        while boot_uptime_centiseconds() <= stop_deadline:
            try:
                candidate = read_process_identity(identity.pid)
            except ProcessLookupError:
                break
            if not same_process(candidate, identity):
                raise SupervisorError("owned-process identity changed before cleanup")
            if candidate.state in ("T", "t", "Z"):
                observed = candidate
                break
            if self.pidfd_has_exited():
                observed = candidate
                break
            select.select([pidfd], [], [], STOP_POLL_SECONDS)

        if observed is None:
            try:
                observed = read_process_identity(identity.pid)
            except ProcessLookupError:
                observed = None
        if observed is not None and not same_process(observed, identity):
            raise SupervisorError("owned-process identity changed during cleanup")

        if observed is not None and observed.state != "Z":
            try:
                observed_token = read_process_owner_token(identity.pid)
            except ProcessLookupError:
                observed_token = None
                observed = None
            except PermissionError as error:
                try:
                    rechecked = read_process_identity(identity.pid)
                except ProcessLookupError:
                    observed = None
                else:
                    if rechecked.state == "Z" or self.pidfd_has_exited():
                        observed = None
                    elif not same_process(rechecked, identity):
                        raise SupervisorError(
                            "owned-process identity changed while rechecking its "
                            "environment"
                        ) from error
                    else:
                        raise SupervisorError(
                            "owned-process environment could not be verified"
                        ) from error
            if observed is not None and (
                observed.process_group_id == identity.pid
                and observed_token == self.owner_token
            ):
                self.stop_verified_group(identity.pid)
            elif observed is not None:
                self.kill_pending_child(observed)
        if (observed is None or observed.state == "Z") and process_group_members(
            identity.pid
        ):
            self.stop_verified_group(identity.pid)

        if not self.wait_for_exit(
            boot_uptime_centiseconds() + KILL_DEADLINE_CENTISECONDS
        ):
            raise SupervisorError("owned process did not exit after cleanup")
        process_status = self.reap_child()
        if process_group_members(identity.pid):
            raise SupervisorError("owned process group remained after reap")
        return (0, process_status)

    def kill_pending_child(self, observed: ProcessIdentity) -> None:
        expected = self.require_identity()
        try:
            direct_children = read_direct_children(observed.pid)
        except ProcessLookupError:
            if self.pidfd_has_exited():
                return
            raise SupervisorError(
                "pending owned-process child inventory disappeared"
            ) from None
        if not pending_child_is_isolated(
            observed,
            expected,
            direct_children,
        ):
            raise SupervisorError(
                "pending owned process is contaminated and cannot be signalled"
            )
        try:
            signal.pidfd_send_signal(self.require_pidfd(), signal.SIGKILL)
        except ProcessLookupError:
            return

    def stop_verified_group(self, process_group_id: int) -> None:
        verified_members = verify_token_owned_group(
            process_group_id,
            self.owner_token,
            self.expected_user_id,
        )
        if not verified_members:
            return
        try:
            os.killpg(process_group_id, signal.SIGTERM)
            os.killpg(process_group_id, signal.SIGCONT)
        except ProcessLookupError:
            return
        term_deadline = boot_uptime_centiseconds() + TERM_DEADLINE_CENTISECONDS
        while boot_uptime_centiseconds() <= term_deadline:
            if not process_group_members(process_group_id):
                return
            select.select(
                [self.require_pidfd()],
                [],
                [],
                STOP_POLL_SECONDS,
            )
        remaining = verify_token_owned_group(
            process_group_id,
            self.owner_token,
            self.expected_user_id,
        )
        if remaining:
            try:
                os.killpg(process_group_id, signal.SIGKILL)
            except ProcessLookupError:
                pass
        kill_deadline = boot_uptime_centiseconds() + KILL_DEADLINE_CENTISECONDS
        while boot_uptime_centiseconds() <= kill_deadline:
            if not process_group_members(process_group_id):
                return
            select.select(
                [self.require_pidfd()],
                [],
                [],
                STOP_POLL_SECONDS,
            )
        raise SupervisorError("owned process group remained after bounded cleanup")

    def reap_child(self) -> int:
        if self.reaped:
            return self.reaped_process_status or 0
        result = os.waitid(os.P_PIDFD, self.require_pidfd(), os.WEXITED)
        if result is None:
            raise SupervisorError("owned process could not be reaped")
        process_status = waitid_result_to_status(result)
        self.reaped = True
        self.reaped_process_status = process_status
        return process_status

    def monitor_ready_process(self) -> int:
        while True:
            try:
                command = self.wait_for_control_or_exit(0.25)
            except ChildProcessError:
                return self.finish_natural_exit()
            if command == "stop":
                cleanup_status, process_status = self.stop_and_reap()
                self.publish_result(cleanup_status, process_status, "stopped")
                return cleanup_status

    def finish_natural_exit(self) -> int:
        try:
            identity = self.require_identity()
            remaining = process_group_members(identity.pid)
            cleanup_status = 0
            if remaining:
                try:
                    self.stop_verified_group(identity.pid)
                except SupervisorError:
                    cleanup_status = 1
            process_status = self.reap_child()
            if process_group_members(identity.pid):
                cleanup_status = 1
            reason = "exited" if cleanup_status == 0 else "orphaned-group"
            self.publish_result(cleanup_status, process_status, reason)
            return process_status if cleanup_status == 0 else 125
        except (OSError, SupervisorError):
            if self.reaped:
                self.cleanup_failure_latched = True
            raise

    def run(self) -> int:
        failure_reason = "supervisor-failed"
        try:
            self.launch_behind_barrier()
            return self.monitor_ready_process()
        except InterruptedError:
            failure_reason = (
                "stopped" if self.ready_published else "stopped-before-ready"
            )
        except ChildProcessError:
            failure_reason = "exited-before-ready"
        except ControlChannelClosed as error:
            print(f"{self.description}: {error}", file=sys.stderr)
            failure_reason = "controller-lost"
        except (OSError, SupervisorError) as error:
            print(f"{self.description}: {error}", file=sys.stderr)
            failure_reason = "ownership-failed"

        cleanup_status = 1
        process_status = 125
        try:
            cleanup_status, process_status = self.stop_and_reap()
        except (OSError, SupervisorError) as error:
            print(f"{self.description}: {error}", file=sys.stderr)
        self.publish_result(cleanup_status, process_status, failure_reason)
        return 1 if cleanup_status == 0 else 125

    def close(self) -> None:
        for descriptor in (
            self.release_descriptor,
            self.exec_status_descriptor,
            self.child_pidfd,
            self.stdout_descriptor,
            self.stderr_descriptor,
        ):
            if descriptor is None or descriptor in (1, 2):
                continue
            try:
                os.close(descriptor)
            except OSError:
                pass


def parse_path(value: str) -> Path | None:
    return None if value == "-" else Path(value)


def parse_arguments(arguments: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-file", required=True)
    parser.add_argument("--result-file", required=True)
    parser.add_argument("--description", required=True)
    parser.add_argument("--stdout-path", default="-")
    parser.add_argument("--stderr-path", default="-")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    parsed = parser.parse_args(arguments)
    if parsed.command and parsed.command[0] == "--":
        parsed.command = parsed.command[1:]
    if not parsed.command:
        parser.error("one owned-process command is required")
    return parsed


def main(arguments: Sequence[str] | None = None) -> int:
    parsed = parse_arguments(sys.argv[1:] if arguments is None else arguments)
    paths = SupervisorPaths(
        state_file=Path(parsed.state_file),
        result_file=Path(parsed.result_file),
        stdout_path=parse_path(parsed.stdout_path),
        stderr_path=parse_path(parsed.stderr_path),
    )
    try:
        validate_record_destination(paths.result_file, "owned-process result file")
    except SupervisorError as error:
        fail(f"owned-process supervisor setup failed: {error}")

    stdout_descriptor: int | None = None
    stderr_descriptor: int | None = None
    try:
        if sys.platform != "linux":
            raise SupervisorError("the owned-process supervisor requires Linux")
        if not hasattr(os, "pidfd_open") or not hasattr(
            signal,
            "pidfd_send_signal",
        ):
            raise SupervisorError(
                "the owned-process supervisor requires Linux pidfd support"
            )
        owner_token = os.environ.get("YAP_RUNTIME_OWNER_TOKEN", "")
        if OWNER_TOKEN_PATTERN.fullmatch(owner_token) is None:
            raise SupervisorError(
                "YAP_RUNTIME_OWNER_TOKEN must be 32 random bytes in lowercase hex"
            )
        if not parsed.description or "\n" in parsed.description:
            raise SupervisorError("owned-process description is invalid")
        validate_record_destination(paths.state_file, "owned-process state file")
        if paths.state_file.parent != paths.result_file.parent:
            raise SupervisorError(
                "owned-process records must share one private directory"
            )

        parent_pid = os.getppid()
        parent_identity = read_process_identity(parent_pid)
        set_parent_death_signal(signal.SIGTERM)
        if (
            os.getppid() != parent_pid
            or read_process_identity(parent_pid).start_ticks
            != parent_identity.start_ticks
        ):
            raise SupervisorError(
                "owned-process controller disappeared before supervision"
            )
        os.setsid()
        for signal_number in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
            signal.signal(signal_number, request_stop)

        stdout_descriptor = open_output(paths.stdout_path)
        if paths.stderr_path == paths.stdout_path and stdout_descriptor is not None:
            stderr_descriptor = stdout_descriptor
        else:
            stderr_descriptor = open_output(paths.stderr_path)
    except (OSError, ProcessLookupError, SupervisorError) as error:
        for descriptor in {stdout_descriptor, stderr_descriptor}:
            if descriptor is not None:
                os.close(descriptor)
        print(f"{parsed.description}: owned-process setup failed: {error}", file=sys.stderr)
        try:
            atomic_write(
                paths.result_file,
                f"{PROTOCOL_VERSION} 0 125 setup-failed\n",
            )
        except (OSError, SupervisorError) as result_error:
            print(
                f"{parsed.description}: setup result could not be published: "
                f"{result_error}",
                file=sys.stderr,
            )
            return 125
        return 2

    supervisor = OwnedProcessSupervisor(
        owner_token=owner_token,
        description=parsed.description,
        paths=paths,
        command=parsed.command,
        stdout_descriptor=stdout_descriptor,
        stderr_descriptor=stderr_descriptor,
    )
    try:
        return supervisor.run()
    finally:
        supervisor.close()


if __name__ == "__main__":
    raise SystemExit(main())
