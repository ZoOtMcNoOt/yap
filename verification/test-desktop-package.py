"""Check the installed Debian client or a built macOS app on its native host."""

import argparse
import configparser
import json
import os
import plistlib
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--macos-app", type=Path)
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1] / "desktop/src-tauri"
    config = json.loads((source / "tauri.conf.json").read_text())
    if sys.platform == "darwin" and args.macos_app:
        contents = args.macos_app.resolve(strict=True) / "Contents"
        with (contents / "Info.plist").open("rb") as metadata:
            info = plistlib.load(metadata)
        if info["CFBundleIdentifier"] != config["identifier"]:
            raise ValueError("Packaged app has the wrong identity")
        with (source / "Info.plist").open("rb") as metadata:
            expected = plistlib.load(metadata)["NSMicrophoneUsageDescription"]
        if not expected.strip() or info.get("NSMicrophoneUsageDescription") != expected:
            raise ValueError("Packaged app is missing its microphone permission text")
        executable = contents / "MacOS" / info["CFBundleExecutable"]
        resources = contents / "Resources"
    elif sys.platform == "linux" and args.macos_app is None:
        entry = configparser.ConfigParser(interpolation=None)
        entry.read("/usr/share/applications/Yap.desktop")
        if entry["Desktop Entry"]["Exec"] != "yap-desktop":
            raise ValueError("Installed launcher points to the wrong executable")
        executable = Path("/usr/bin/yap-desktop")
        resources = Path("/usr/lib/Yap")
    else:
        parser.error("use --macos-app on macOS or install the .deb on Linux")

    for original, packaged in config["bundle"]["resources"].items():
        if (source / original).read_bytes() != (resources / packaged).read_bytes():
            raise ValueError(f"Packaged resource differs: {packaged}")

    with tempfile.TemporaryDirectory(prefix="yap-package-") as directory:
        profile = Path(directory).resolve()
        process = subprocess.Popen(
            [executable],
            env={**os.environ, "YAP_APP_DATA_DIR": str(profile)},
            start_new_session=True,
        )
        try:
            deadline = time.monotonic() + 30
            log = profile / "logs/yap.log"
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(
                        f"Packaged app exited during startup: {process.returncode}"
                    )
                if (
                    log.exists()
                    and " app start" in log.read_text()
                    and (sys.platform != "linux" or linux_window_is_visible())
                ):
                    break
                time.sleep(0.25)
            else:
                raise RuntimeError("Packaged app did not start in its fresh profile")
            time.sleep(3)
            if process.poll() is not None:
                raise RuntimeError("Packaged app exited immediately after startup")
        finally:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            except ProcessLookupError:
                process.wait()
        if args.macos_app:
            subprocess.run(
                [
                    "swift", str(Path(__file__).with_name("test-macos-reopen.swift")),
                    str(args.macos_app.resolve()), str(profile / "hidden-launch"),
                ],
                check=True,
                timeout=120,
            )
    print(f"Verified package resources and fresh-profile startup on {sys.platform}.")


def linux_window_is_visible() -> bool:
    result = subprocess.run(
        ["xwininfo", "-name", "Yap"],
        check=False,
        capture_output=True,
        text=True,
        timeout=3,
        env={**os.environ, "LC_ALL": "C"},
    )
    return result.returncode == 0 and "Map State: IsViewable" in result.stdout


if __name__ == "__main__":
    main()
