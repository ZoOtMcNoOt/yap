from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest


def configure_canonical_test_temp_root() -> None:
    """Keep test fixtures off hosted-runner junction aliases."""

    try:
        canonical_root = Path(tempfile.gettempdir()).resolve(strict=True)
    except OSError as error:
        raise RuntimeError(
            "The portable server suite temp root is unavailable."
        ) from error
    if not canonical_root.is_dir():
        raise RuntimeError("The portable server suite temp root is not a directory.")

    canonical = str(canonical_root)
    tempfile.tempdir = canonical
    for variable in ("TMPDIR", "TEMP", "TMP"):
        os.environ[variable] = canonical


def validate_runtime_identity() -> dict[str, object]:
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError("The portable server suite requires Python 3.12.")

    server_root = Path.cwd().resolve(strict=True)
    lock_path = server_root / "uv.lock"
    lock_bytes = lock_path.read_bytes()
    lock = tomllib.loads(lock_bytes.decode("utf-8"))
    locked_versions = {
        package["name"]: package["version"]
        for package in lock["package"]
        if package["name"] in {"numpy", "rapidfuzz", "regex"}
    }
    if set(locked_versions) != {"numpy", "rapidfuzz", "regex"}:
        raise RuntimeError("uv.lock does not contain the portable suite dependencies.")
    installed_versions = {
        name: importlib.metadata.version(name)
        for name in sorted(locked_versions)
    }
    if installed_versions != dict(sorted(locked_versions.items())):
        raise RuntimeError("Installed evaluation dependencies do not match uv.lock.")

    return {
        "lockSha256": hashlib.sha256(lock_bytes).hexdigest(),
        "packages": installed_versions,
        "python": ".".join(str(part) for part in sys.version_info[:3]),
    }


def main() -> int:
    arguments = sys.argv[1:]
    if arguments not in ([], ["--identity-only"]):
        raise RuntimeError("Only the optional --identity-only argument is supported.")
    identity = validate_runtime_identity()
    print(json.dumps(identity, sort_keys=True))
    if arguments == ["--identity-only"]:
        return 0

    configure_canonical_test_temp_root()
    suite = unittest.defaultTestLoader.discover(
        "tests",
        pattern="test_*.py",
        top_level_dir=".",
    )
    result = unittest.TextTestRunner(
        verbosity=2,
        failfast=True,
    ).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
