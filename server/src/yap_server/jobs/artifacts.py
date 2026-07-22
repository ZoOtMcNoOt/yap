from __future__ import annotations

from concurrent.futures import CancelledError
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import threading
from typing import Mapping, Sequence
import wave

from yap_server.bounded_file import read_regular_file


# A durable dynamic result repeats the transcript text across its lossless
# language segments. This remains bounded independently from uploaded audio.
MAX_STATE_BYTES = 4 * 1024 * 1024
_OWNED_ARTIFACT_TEMPORARY = re.compile(
    r"^(?:"
    r"\.input-[A-Za-z0-9_-]+\.wav\.part|"
    r"\.utterance-plan-[A-Za-z0-9_-]+\.json\.part|"
    r"\.result-[A-Za-z0-9_-]+|"
    r"\.worker-result\.json\.[A-Za-z0-9_-]+\.tmp"
    r")$"
)


@dataclass(frozen=True, slots=True)
class PcmChunkSource:
    path: Path
    byte_length: int
    sha256: str


def publish_wav(
    destination: Path,
    chunk_sources: Sequence[PcmChunkSource],
    *,
    cancellation: threading.Event | None = None,
) -> str:
    temporary_path: Path | None = None
    pcm_digest = hashlib.sha256()
    try:
        with tempfile.NamedTemporaryFile(
            mode="w+b",
            dir=destination.parent,
            prefix=".input-",
            suffix=".wav.part",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            with wave.open(temporary, "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(16000)
                for source in chunk_sources:
                    _raise_if_cancelled(cancellation)
                    body = read_regular_file(source.path, source.byte_length)
                    if (
                        len(body) != source.byte_length
                        or hashlib.sha256(body).hexdigest() != source.sha256
                    ):
                        raise ValueError(
                            "an uploaded chunk no longer matches its identity"
                        )
                    pcm_digest.update(body)
                    output.writeframesraw(body)
                _raise_if_cancelled(cancellation)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, destination)
        temporary_path = None
        _raise_if_cancelled(cancellation)
        return pcm_digest.hexdigest()
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def sha256_file(
    path: Path,
    *,
    cancellation: threading.Event | None = None,
) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            _raise_if_cancelled(cancellation)
            digest.update(block)
    _raise_if_cancelled(cancellation)
    return digest.hexdigest()


def _raise_if_cancelled(cancellation: threading.Event | None) -> None:
    if cancellation is not None and cancellation.is_set():
        raise CancelledError()


def publish_json(destination: Path, payload: Mapping[str, object]) -> None:
    encoded = (
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    if len(encoded) > MAX_STATE_BYTES:
        raise ValueError("persisted JSON exceeds its readable byte limit")
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=destination.parent,
            prefix=".result-",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(encoded)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, destination)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def read_json_file(path: Path) -> dict[str, object]:
    body = read_regular_file(path, MAX_STATE_BYTES)
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"persisted JSON is invalid: {path.name}") from error
    if not isinstance(value, dict):
        raise ValueError(f"persisted JSON must be an object: {path.name}")
    return value


def unlink_private_regular_file(path: Path, label: str) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ValueError(f"{label} is unsafe")
    path.unlink()


def unlink_owned_artifact_temporaries(root: Path) -> None:
    metadata = root.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("private artifact root is unsafe")
    for entry in root.iterdir():
        if _OWNED_ARTIFACT_TEMPORARY.fullmatch(entry.name) is not None:
            unlink_private_regular_file(entry, "private recording temporary")
