"""Check saved recordings and organization settings in a disposable installed profile."""

import argparse
import json
import shutil
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "desktop/src-tauri/tests/fixtures"
SAVED = FIXTURES / "accepted-word-timings"
SOURCE = FIXTURES / "tone-mono-vorbis.webm"
PREPARED = Path(__file__).resolve().parent / "fixtures/package-profile"
JOB = "job-cff6a712a80acc6d8d33e5c0"
REVISION = Path("result-00000000000000000001")
FILES = (
    REVISION / "transcript.txt",
    REVISION / "result.json",
    Path("transcript-corrections/correction-00000000000000000001.json"),
    Path("transcript-corrections/correction-00000000000000000002.json"),
)


def check_local_dictation(action, profile):
    fixture = PREPARED / "local-dictation"
    stem = "live-s-package-dictation"
    recording = profile / "live-recordings"
    files = {
        f"{stem}.{suffix}": fixture / f"{stem}.{suffix}"
        for suffix in ("capture.json", "commit.json", "transcript.r1.json", "txt")
    }
    files[f"{stem}.wav"] = ROOT / "server/tests/fixtures/asr/2086-149220-0033.wav"
    if action == "seed":
        recording.mkdir(mode=0o700, exist_ok=True)
        for name, source in files.items():
            destination = recording / name
            shutil.copyfile(source, destination)
            destination.chmod(0o600)
    if {path.name for path in recording.glob(f"{stem}.*")} != set(files):
        raise ValueError("Package lifecycle changed the set of saved dictation files")
    for name, source in files.items():
        if (recording / name).read_bytes() != source.read_bytes():
            raise ValueError(f"Package lifecycle changed the saved dictation file {name}")


def check_profile_settings(action, profile):
    registration = json.loads((PREPARED / "server-settings.json").read_bytes())
    files = {
        profile / "primary-language.json": {"schemaVersion": 1, "languageBcp47": "en-AU"},
        profile / "server-settings.json": registration,
        profile / "organization-sign-out.json": True,
    }
    if action == "seed" and any(path.exists() for path in files):
        raise ValueError("Seeding requires a disposable profile without saved language or organization settings")
    for path, expected in files.items():
        if action == "seed":
            with path.open("x", encoding="utf-8") as stream:
                json.dump(expected, stream, indent=2)
        actual = json.loads(path.read_bytes())
        # Compare JSON types as well as values. In Python, False equals zero.
        if json.dumps(actual, sort_keys=True) != json.dumps(expected, sort_keys=True):
            raise ValueError(f"Package lifecycle changed {path.name}")


def check(action, profile):
    job_dir = profile / "remote-jobs" / JOB
    output = job_dir / FILES[0]
    capture_hash = json.loads((SAVED / FILES[1]).read_bytes())["captureManifestSha256"]
    expected = (SOURCE.name, str(SOURCE), str(output), "complete", capture_hash)
    manifest = job_dir / "capture-manifest.json"
    preparation = ((PREPARED / "create-request.json").read_text().strip(), str(manifest), capture_hash)
    uri = (profile / "jobs.sqlite3").as_uri()
    mode = "rw" if action == "seed" else "ro"
    with sqlite3.connect(f"{uri}?mode={mode}", uri=True) as db:
        if action == "seed":
            if db.execute("SELECT count(*) FROM recording_jobs").fetchone() != (0,):
                raise ValueError("Seeding requires an empty disposable recording ledger")
            if any((profile / "live-recordings").glob("live-*")):
                raise ValueError("Seeding requires a disposable profile without live recordings")
            check_profile_settings(action, profile)
            shutil.copytree(SAVED, job_dir)
            corrections = job_dir / "transcript-corrections"
            corrections.chmod(0o700)
            for revision in corrections.iterdir():
                revision.chmod(0o600)
            shutil.copyfile(PREPARED / manifest.name, manifest)
            now = time.time_ns() // 1_000_000
            db.execute(
                """INSERT INTO recording_jobs
                   (job_id, session_mode, session_origin, route, display_name, source_path,
                    output_path, status, capture_manifest_sha256, created_at_ms, updated_at_ms)
                   VALUES (?, 'meeting', 'imported_file', 'server_batch', ?, ?, ?, ?, ?, ?, ?)""",
                (JOB, *expected, now, now),
            )
            db.execute(
                """INSERT INTO prepared_remote_jobs
                   (job_id, create_request_json, capture_manifest_path, capture_manifest_sha256)
                   VALUES (?, ?, ?, ?)""", (JOB, *preparation),
            )
        prepared = db.execute(
            """SELECT create_request_json, capture_manifest_path, capture_manifest_sha256
               FROM prepared_remote_jobs WHERE job_id = ?""", (JOB,),
        ).fetchone()
        if prepared != preparation or manifest.read_bytes() != (PREPARED / manifest.name).read_bytes():
            raise ValueError("Package lifecycle changed the saved recording's source evidence")
        rows = db.execute(
            """SELECT job_id, display_name, source_path, output_path, status, capture_manifest_sha256
               FROM recording_jobs"""
        ).fetchall()
        if rows != [(JOB, *expected)]:
            raise ValueError("Package lifecycle lost, duplicated or changed the completed recording row")
        revisions = sorted((job_dir / "transcript-corrections").glob("correction-*.json"))
        if revisions != [job_dir / revision for revision in FILES[2:]]:
            raise ValueError("Package lifecycle changed the set of accepted corrections")
        for relative in FILES:
            if (job_dir / relative).read_bytes() != (SAVED / relative).read_bytes():
                raise ValueError(f"Package lifecycle changed {relative}")
    if action == "verify":
        check_profile_settings(action, profile)
    check_local_dictation(action, profile)
    print("Verified the recording, both corrections, saved dictation, primary language, disabled server registration and explicit sign-out.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("seed", "verify"))
    parser.add_argument("profile", type=Path)
    args = parser.parse_args()
    check(args.action, args.profile.resolve(strict=True))
