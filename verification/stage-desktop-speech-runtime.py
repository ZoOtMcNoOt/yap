"""Stage the exact native speech archive recorded for a desktop package build."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory


def verify(path, archive):
    with path.open("rb") as stream:
        digest = hashlib.sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    if path.stat().st_size != archive["sizeBytes"] or digest.hexdigest() != archive["sha256"]:
        raise ValueError(f"Archive size or SHA-256 differs from the model lock: {path}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("platform", choices=["linux-x86_64", "macos-aarch64", "windows-x86_64"])
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    lock = Path(__file__).resolve().parents[1] / "desktop/model-artifacts.lock.json"
    artifacts = json.loads(lock.read_text())["artifacts"]
    artifact, = (item for item in artifacts if item["id"] == "silero-vad-v4-k2-export")
    runtime = artifact["runtime"]
    archive, = (item for item in runtime["nativeArchives"] if item["platform"] == args.platform)
    filename = archive["fileName"]
    if Path(filename).name != filename or archive["source"] != (
        f"https://github.com/k2-fsa/sherpa-onnx/releases/download/v{runtime['version']}/{filename}"
    ):
        raise ValueError("Unexpected native speech runtime archive source")
    args.directory.mkdir(exist_ok=True, parents=True)
    destination = args.directory / filename
    if destination.exists():
        verify(destination, archive)
    else:
        with TemporaryDirectory(dir=args.directory) as tmp:
            downloaded = Path(tmp) / filename
            subprocess.run(["curl", "-fsSL", "--retry", "2", archive["source"], "-o", downloaded], check=True)
            verify(downloaded, archive)
            downloaded.replace(destination)
    print(f"Verified {destination.name}")


if __name__ == "__main__":
    main()
