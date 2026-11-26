"""Exercise the native desktop recognizer with the licensed LibriSpeech recording."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
from tempfile import TemporaryDirectory
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server/src"))

from yap_server.transcript_metrics import word_error_rate


MODEL_ID = "nemotron-3.5-asr-streaming-0.6b-1120ms-int8"
RELEASE = f"sherpa-onnx-{MODEL_ID}-2026-06-11"
ARCHIVE_SHA256 = "adbdd5e9fef87300c37cebfcfc4f1ebe56845c860c8a760af0a1dd65ce9beed3"


def stage_model(directory):
    archive = directory / "model.tar.bz2"
    url = f"https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/{RELEASE}.tar.bz2"
    subprocess.run(["curl", "-fsSL", "--retry", "2", url, "-o", str(archive)], check=True)
    with archive.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != ARCHIVE_SHA256:
            raise ValueError("The Nemotron release archive does not match its SHA-256")
    model = directory / "models" / MODEL_ID
    model.mkdir(parents=True)
    names = ("encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx", "tokens.txt")
    files = {f"{RELEASE}/{name}": model / name for name in names}
    with tarfile.open(archive, "r|bz2") as package:
        for member in package:
            if member.name in files and member.isfile():
                with package.extractfile(member) as src, files.pop(member.name).open("xb") as dst:
                    shutil.copyfileobj(src, dst, 1024 * 1024)
    if files:
        raise ValueError("The release archive is missing a required model file")
    archive.unlink()


def check_sessions(output, inputs, samples, audio_ms, reference):
    rows = [json.loads(line) for line in output.splitlines()]
    if [row["input"] for row in rows] != [str(path) for path in inputs]:
        raise ValueError("The profiler did not return the requested sessions in order")
    for session, row in enumerate(rows, start=1):
        if row["samples"] != samples:
            raise ValueError(f"Session {session} did not consume all {samples} samples")
        if session == 2:
            if row["transcript"].strip():
                raise ValueError("The silent session produced text")
            print(f"Silent session: {samples} samples, empty transcript")
            continue
        wer = word_error_rate(reference, row["transcript"])
        if wer:
            raise ValueError(f"Speech session {session} differs from the locked transcript (WER {wer:.2%})")
        decode_ms = row["decode_ms"]
        if not 0 < decode_ms < audio_ms:
            raise ValueError(f"Decoding took {decode_ms} ms for {audio_ms} ms of audio")
        print(
            f"Speech session {session}: {audio_ms} ms of audio, {decode_ms} ms to decode, "
            f"RTF {decode_ms / audio_ms:.3f}, fixture WER {wer:.2%}"
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    model_source = parser.add_mutually_exclusive_group()
    model_source.add_argument(
        "--installed-models", type=Path,
        help="Use an existing Yap models directory for an offline run",
    )
    model_source.add_argument("--stage-model-in", type=Path,
                              help="Keep the verified models in a new directory for the installed desktop test")
    args = parser.parse_args()
    fixture = json.loads((ROOT / "server/model-pools.lock.json").read_bytes())["fixture"]
    audio = ROOT / fixture["path"]
    if hashlib.sha256(audio.read_bytes()).hexdigest() != fixture["sha256"]:
        raise ValueError("The speech fixture does not match the lock")
    with wave.open(str(audio)) as wav:
        if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, 16_000):
            raise ValueError("Expected the locked mono 16 kHz PCM16 fixture")
        samples = wav.getnframes()
        audio_ms = samples * 1000 // wav.getframerate()
        params = wav.getparams()

    command = ["cargo", "run", "--locked", "--example", "nemotron_profile", "--"]
    with TemporaryDirectory(prefix="yap-dictation-") as tmp:
        stage = Path(tmp)
        if args.stage_model_in:
            stage = args.stage_model_in.resolve()
            stage.mkdir(mode=0o700)
        models = args.installed_models.resolve() if args.installed_models else stage / "models"
        env = {**os.environ, "YAP_APP_DATA_DIR": tmp, "YAP_MODELS_DIR": str(models)}
        cwd = ROOT / "desktop/src-tauri"
        if args.installed_models is None:
            stage_model(stage)
            subprocess.run([*command, "--verify-model"], cwd=cwd, env=env, check=True)
        silence = Path(tmp) / "silence.wav"
        with wave.open(str(silence), "wb") as wav:
            wav.setparams(params)
            wav.writeframes(bytes(samples * params.sampwidth))
        inputs = [audio, silence, audio]
        result = subprocess.run(
            [*command, "--batch", *inputs], cwd=cwd, env=env, check=False,
            stdout=subprocess.PIPE, encoding="utf-8",
        )
        if result.returncode:
            sys.stderr.write(result.stdout)
            result.check_returncode()
        check_sessions(result.stdout, inputs, samples, audio_ms, fixture["goldenTranscript"])


if __name__ == "__main__":
    main()
