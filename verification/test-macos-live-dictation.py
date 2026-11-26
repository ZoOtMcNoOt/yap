"""Exercise the installed Mac app with a licensed WAV through virtual CoreAudio."""

import argparse
import json
import os
import plistlib
import signal
import subprocess
import tempfile
import time
from contextlib import contextmanager
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from recording_fixture_evidence import REPO, digest, read_fixture_pcm, read_json, require

CHECKS = Path(__file__).resolve().parent


def load_script(name):
    spec = spec_from_file_location(name, CHECKS / f"{name}.py")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def wait_for(label, observe, app, log, timeout=90):
    deadline = time.monotonic() + timeout
    while app.poll() is None and time.monotonic() < deadline:
        value = observe()
        if value:
            return value
        time.sleep(0.05)
    tail = log.read_text(errors="replace")[-2500:] if log.exists() else "(no application log)"
    raise RuntimeError(f"Waiting for {label} failed (app status {app.poll()}).\n{tail}")


@contextmanager
def launch(executable, env, prefix):
    app = subprocess.Popen([*prefix, executable], env=env, start_new_session=True)
    try:
        yield app
    finally:
        if app.poll() is None:
            os.killpg(app.pid, signal.SIGTERM)
            try:
                app.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(app.pid, signal.SIGKILL)
                app.wait()


def run(bundle, models, switch):
    require(os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted" and os.uname().sysname == "Darwin",
            "Requires the disposable Mac audio runner")
    def verify_loopback():
        for kind in ("input", "output"):
            name = subprocess.check_output([switch, "-t", kind, "-c"], text=True).strip()
            require(name == "BlackHole 2ch", f"Virtual {kind} is unavailable")

    verify_loopback()
    with (bundle / "Contents/Info.plist").open("rb") as file:
        executable = bundle / "Contents/MacOS" / plistlib.load(file)["CFBundleExecutable"]
    fixture = read_json(REPO / "server/model-pools.lock.json")["fixture"]
    audio = REPO / fixture["path"]
    require(digest(audio) == fixture["sha256"], "Speech fixture hash differs from the model lock")
    offline = load_script("test-desktop-package").macos_offline_prefix()
    check_session = load_script("check-installed-dictation").check_session
    with tempfile.TemporaryDirectory(prefix="yap-installed-mac-") as work:
        profile = Path(work) / "profile"
        profile.mkdir(mode=0o700)
        (profile / "primary-language.json").write_text(json.dumps({"schemaVersion": 1, "languageBcp47": "en-US"}))
        env = {**os.environ, "YAP_APP_DATA_DIR": str(profile), "YAP_MODELS_DIR": str(models.resolve(strict=True))}
        controls = Path(work) / "workspace-control"
        subprocess.run(["swiftc", CHECKS / "test-macos-saved-history.swift", "-o", controls], check=True)
        log = profile / "logs/yap.log"
        recordings = profile / "live-recordings"
        def perform(app, action, *args):
            subprocess.run([controls, str(app.pid), action, *args], check=True, timeout=55)

        with launch(executable, env, offline) as app:
            perform(app, "settings")
            verify_loopback()
            perform(app, "start")
            wait_for("cold microphone samples", lambda: any(p.stat().st_size > 44 for p in recordings.glob("*.wav.part")),
                     app, log)
            require("live ASR adapter spawned" not in log.read_text(), "The cold session was already ready before Stop")
            perform(app, "stop")
            cold = wait_for("cold-stop commit", lambda: next(recordings.glob("*.commit.json"), None), app, log)
            manifest = read_json(cold)
            cold_audio = recordings / manifest["audioFile"]
            require(manifest["status"] == "complete" and read_fixture_pcm(cold_audio)
                    and digest(cold_audio) == manifest["audioSha256"], "Cold stop lost the saved audio")
            cold_stem = cold.name.removesuffix(".commit.json")
            require(not list(recordings.glob(f"{cold_stem}.transcript.*")) and not (recordings / f"{cold_stem}.txt").exists(),
                    "Cold stop published transcript text")
            print(f"Cold stop saved {cold_audio.stat().st_size} bytes of audio before recognition.", flush=True)

            prior_log = log.stat().st_size
            verify_loopback()
            perform(app, "start")
            wait_for("warm recognizer", lambda: b"live ASR adapter spawned" in log.read_bytes()[prior_log:], app, log)
            verify_loopback()
            subprocess.run(["/usr/bin/afplay", audio], check=True, timeout=30)
            time.sleep(1)
            perform(app, "stop")
            warm = wait_for("new transcript revision", lambda: next(recordings.glob("*.transcript.r1.json"), None), app, log)
            stem = warm.name.removesuffix(".transcript.r1.json")
            require(stem != cold_stem, "The warm recording reused the cold session")
            commit = recordings / f"{stem}.commit.json"
            before = check_session(commit)
            require(not list(recordings.glob("*.wav.part")), "A stopped session retained a partial audio file")

        with launch(executable, env, offline) as app:
            perform(app, "review", stem, recordings / f"{stem}.txt")
            require(check_session(commit) == before, "Saved recording changed on offline restart")
            require(digest(cold_audio) == manifest["audioSha256"], "Cold-stop audio changed on restart")
        print(json.dumps(before, sort_keys=True), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("models", type=Path)
    parser.add_argument("switch", type=Path)
    args = parser.parse_args()
    run(args.bundle.resolve(strict=True), args.models, args.switch.resolve(strict=True))
