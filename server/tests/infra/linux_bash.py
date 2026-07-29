from __future__ import annotations

from functools import cache
import os
import shutil
import subprocess


LINUX_BASH_DISCOVERY_TIMEOUT_SECONDS = 30


@cache
def find_linux_bash() -> str | None:
    """Return bash only when it provides the Linux process model under test."""

    bash = shutil.which("bash")
    if bash is None:
        _raise_if_linux_lifecycle_is_required("bash is unavailable")
        return None
    try:
        probe = subprocess.run(
            [bash, "-lc", 'test "$(uname -s)" = Linux'],
            check=False,
            capture_output=True,
            timeout=LINUX_BASH_DISCOVERY_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        _raise_if_linux_lifecycle_is_required("the Linux bash probe failed")
        return None
    if probe.returncode != 0:
        _raise_if_linux_lifecycle_is_required(
            "bash does not expose the Linux process model"
        )
        return None
    return bash


def _raise_if_linux_lifecycle_is_required(reason: str) -> None:
    if os.environ.get("YAP_REQUIRE_LINUX_LIFECYCLE_TESTS") == "1":
        raise RuntimeError(
            f"Linux lifecycle tests are required and cannot skip: {reason}"
        )
