#!/usr/bin/env python3.12
"""Execute a frozen uv binary from an immutable in-memory copy."""

from __future__ import annotations

import fcntl
import hashlib
import os
import stat
import subprocess
import sys
from typing import NoReturn

MAX_EXECUTABLE_BYTES = 256 * 1024 * 1024


def fail(message: str) -> NoReturn:
    print(message, file=sys.stderr)
    raise SystemExit(2)


def required_environment(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        fail(f"Set {name}")
    return value


def copy_checked_executable(
    source_path: str,
    expected_sha256: str,
    expected_size_bytes: int,
) -> tuple[int, str]:
    if not os.path.isabs(source_path):
        fail("the checked uv executor requires an absolute executable")
    if len(expected_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in expected_sha256
    ):
        fail("the checked uv executor requires one lowercase SHA-256")
    if not 0 < expected_size_bytes <= MAX_EXECUTABLE_BYTES:
        fail("the checked uv executable size exceeds the supported bound")

    try:
        source_fd = os.open(
            source_path,
            os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
        )
    except OSError as error:
        fail(f"the checked uv executable could not be opened safely: {error}")

    try:
        source_stat = os.fstat(source_fd)
        if not stat.S_ISREG(source_stat.st_mode) or source_stat.st_mode & 0o111 == 0:
            fail("the checked uv executor requires a regular executable")
        if source_stat.st_size != expected_size_bytes:
            fail("the checked uv executable differs from its frozen size")

        memfd = os.memfd_create("yap-checked-uv", os.MFD_ALLOW_SEALING)
        digest = hashlib.sha256()
        remaining = expected_size_bytes
        while remaining:
            chunk = os.read(source_fd, min(remaining, 1024 * 1024))
            if not chunk:
                fail("the checked uv executable ended before its frozen size")
            digest.update(chunk)
            remaining -= len(chunk)
            view = memoryview(chunk)
            while view:
                written = os.write(memfd, view)
                if written == 0:
                    fail("the checked uv executable could not be copied")
                view = view[written:]
        if os.read(source_fd, 1) or os.fstat(source_fd).st_size != expected_size_bytes:
            fail("the checked uv executable changed while it was copied")
    finally:
        os.close(source_fd)

    observed_sha256 = digest.hexdigest()
    if observed_sha256 != expected_sha256:
        os.close(memfd)
        fail("the checked uv executable differs from its frozen SHA-256")

    os.fchmod(memfd, 0o500)
    required_seals = (
        fcntl.F_SEAL_SEAL | fcntl.F_SEAL_GROW | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_WRITE
    )
    fcntl.fcntl(memfd, fcntl.F_ADD_SEALS, required_seals)
    observed_seals = fcntl.fcntl(memfd, fcntl.F_GET_SEALS)
    if observed_seals & required_seals != required_seals:
        os.close(memfd)
        fail("the checked uv executable could not be sealed")

    return memfd, observed_sha256


def verify_version(memfd: int, expected_version: str) -> str:
    memfd_path = f"/proc/self/fd/{memfd}"
    result = subprocess.run(
        [memfd_path, "--version"],
        check=False,
        capture_output=True,
        pass_fds=(memfd,),
    )
    try:
        observed_version = result.stdout.decode("utf-8").rstrip("\n")
        observed_error = result.stderr.decode("utf-8")
    except UnicodeDecodeError:
        fail("the checked uv executable returned non-UTF-8 version output")
    if result.returncode != 0 or observed_error or observed_version != expected_version:
        fail("the checked uv executable differs from its frozen version")
    return observed_version


def main() -> NoReturn:
    source_path = required_environment("YAP_UV_EXECUTABLE")
    expected_sha256 = required_environment("YAP_UV_EXECUTABLE_SHA256")
    expected_size_text = required_environment("YAP_UV_EXECUTABLE_SIZE_BYTES")
    expected_version = required_environment("YAP_UV_EXECUTABLE_VERSION")
    if not expected_size_text.isdecimal():
        fail("YAP_UV_EXECUTABLE_SIZE_BYTES must be one decimal byte count")
    expected_size_bytes = int(expected_size_text)
    report_identity = os.environ.get("YAP_UV_REPORT_IDENTITY")
    if report_identity not in (None, "0", "1"):
        fail("YAP_UV_REPORT_IDENTITY must be 0 or 1")
    if os.execve not in os.supports_fd:
        fail("the checked uv executor requires descriptor-based execve")

    memfd, observed_sha256 = copy_checked_executable(
        source_path,
        expected_sha256,
        expected_size_bytes,
    )
    verify_version(memfd, expected_version)
    if report_identity == "1":
        print(f"YAP_CHECKED_UV_SHA256={observed_sha256}", flush=True)
        print(f"YAP_CHECKED_UV_SIZE_BYTES={expected_size_bytes}", flush=True)

    os.execve(memfd, [source_path, *sys.argv[1:]], os.environ)


if __name__ == "__main__":
    main()
