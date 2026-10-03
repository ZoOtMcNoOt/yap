"""Audit the complete core lock without installing server or model dependencies."""

import subprocess
import tempfile
from pathlib import Path

import tomllib


def main() -> None:
    server = Path(__file__).resolve().parents[1] / "server"
    with tempfile.TemporaryDirectory(prefix="yap-server-audit-") as directory:
        export = Path(directory) / "pylock.toml"
        subprocess.run(
            [
                "uv", "export", "--project", str(server), "--locked",
                "--all-extras", "--all-groups", "--no-emit-project",
                "--format", "pylock.toml", "--output-file", str(export),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        with (server / "uv.lock").open("rb") as source:
            packages = tomllib.load(source)["package"]
        expected = set()
        for package in packages:
            if package["name"] == "yap-server" and package["source"] == {"virtual": "."}:
                continue
            if package["source"] != {"registry": "https://pypi.org/simple"}:
                raise ValueError(f"Unreviewed audit source: {package['name']}")
            expected.add((package["name"], package["version"]))
        with export.open("rb") as source:
            exported = tomllib.load(source)["packages"]
        actual = {(package["name"], package["version"]) for package in exported}
        if not expected or actual != expected:
            raise ValueError("The audit export does not cover the complete core lock")
        print(f"Auditing all {len(actual)} core package versions; no marker filtering", flush=True)
        subprocess.run(
            [
                "uv", "tool", "run", "--from", "pip-audit==2.10.1",
                "pip-audit", "--locked", directory, "--strict",
                "--progress-spinner", "off", "--timeout", "30",
            ],
            check=True,
        )


if __name__ == "__main__":
    main()
