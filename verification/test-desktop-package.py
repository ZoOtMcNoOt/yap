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
    parser.add_argument("--test-home", type=Path, help="Reuse the disposable user's default profile")
    parser.add_argument("--check-saved-history", action="store_true", help="Read the saved transcript from the reinstalled workspace")
    args = parser.parse_args()
    if args.check_saved_history and not args.test_home:
        parser.error("--check-saved-history requires the disposable home with the saved profile")
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
        env = {**os.environ, "YAP_APP_DATA_DIR": str(profile)}
        if args.test_home:
            home = args.test_home.resolve(strict=True)
            env["HOME"] = str(home)
            for key in ("YAP_APP_DATA_DIR", "XDG_DATA_HOME", "LOCALAPPDATA"):
                env.pop(key, None)
            data_dir = "Library/Application Support" if sys.platform == "darwin" else ".local/share"
            profile = home / data_dir / config["identifier"]
        if args.check_saved_history and sys.platform == "linux":
            env.update(NO_AT_BRIDGE="0", GTK_MODULES="gail:atk-bridge")
        log = profile / "logs/yap.log"
        previous_starts = log.read_text().count(" app start") if log.exists() else 0
        process = subprocess.Popen(
            [executable],
            env=env,
            start_new_session=True,
        )
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(
                        f"Packaged app exited during startup: {process.returncode}"
                    )
                if (
                    log.exists()
                    and log.read_text().count(" app start") > previous_starts
                    and (sys.platform != "linux" or linux_window_is_visible())
                ):
                    break
                time.sleep(0.25)
            else:
                raise RuntimeError("Packaged app did not start in its expected profile")
            time.sleep(3)
            if process.poll() is not None:
                raise RuntimeError("Packaged app exited immediately after startup")
            if args.check_saved_history:
                checks = Path(__file__).resolve().parent
                reference = checks / "fixtures/package-profile/local-dictation/live-s-package-dictation.txt"
                if args.macos_app:
                    subprocess.run(
                        ["swift", str(checks / "test-macos-saved-history.swift"), str(process.pid), str(reference)],
                        check=True, timeout=90,
                    )
                else:
                    verify_debian_history(reference)
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
                    str(args.macos_app.resolve()), str(Path(directory) / "hidden-launch"),
                ],
                check=True,
                timeout=120,
            )
    print(f"Verified package resources and fresh-profile startup on {sys.platform}.")


def verify_debian_history(reference: Path) -> None:
    from desktop_accessibility import has_text, wait_for

    name = "live-s-package-dictation"
    review = f"Review recording {name}"

    def is_button(node, label):
        return node.getRoleName() == "button" and node.name == label

    button = wait_for(
        "onboarding or saved recording",
        lambda n: is_button(n, "Skip for now") or is_button(n, review),
    )
    if button.name == "Skip for now":
        if not button.queryAction().doAction(0):
            raise RuntimeError("Could not dismiss onboarding")
        button = wait_for(review, lambda n: is_button(n, review))
    if not button.queryAction().doAction(0):
        raise RuntimeError("Could not open the saved recording from History")
    wait_for("transcript action", lambda n: is_button(n, f"Open transcript for {name}"))
    text = reference.read_text()
    wait_for("complete saved transcript", lambda n: has_text(n, text))
    print("The installed Debian client reopened the saved dictation from History and displayed the complete reference transcript.")


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
