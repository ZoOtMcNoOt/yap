from __future__ import annotations

from functools import cache
import shutil
import subprocess


@cache
def find_linux_bash() -> str | None:
    """Return bash only when it provides the Linux process model under test."""

    bash = shutil.which("bash")
    if bash is None:
        return None
    try:
        probe = subprocess.run(
            [bash, "-lc", 'test "$(uname -s)" = Linux'],
            check=False,
            capture_output=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return bash if probe.returncode == 0 else None
