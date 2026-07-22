from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import struct
import tarfile


FLEURS_REVISION = "70bb2e84b976b7e960aa89f1c648e09c59f894dd"


def build_fleurs_release(
    root: Path,
    *,
    first_member_name: str = "test/100.wav",
    first_link_target: str | None = None,
    second_member_name: str = "test/200.wav",
    first_samples: tuple[float, ...] | None = None,
    second_samples: tuple[float, ...] | None = None,
) -> tuple[Path, Path, Path]:
    first = first_samples if first_samples is not None else (0.0,) * 160
    second = second_samples if second_samples is not None else (0.0,) * 320
    metadata_path = root / "test.tsv"
    metadata_path.write_text(
        f"1\t100.wav\tUno.\tuno\tu n o |\t{len(first)}\tFEMALE\n"
        f"1\t200.wav\tDos.\tdos\td o s |\t{len(second)}\tMALE\n",
        encoding="utf-8",
    )
    archive_path = root / "test.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        _add_member(
            archive,
            first_member_name,
            _float32_wav_bytes(first),
            link_target=first_link_target,
        )
        _add_member(
            archive,
            second_member_name,
            _float32_wav_bytes(second),
        )

    lock_path = root / "fleurs.lock.json"
    lock_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "dataset": {
                    "id": "google/fleurs",
                    "revision": FLEURS_REVISION,
                    "config": "es_419",
                    "split": "test",
                    "localeBcp47": "es-419",
                    "source": (
                        "https://huggingface.co/datasets/google/fleurs/tree/"
                        f"{FLEURS_REVISION}/data/es_419"
                    ),
                },
                "expectedCaseCount": 2,
                "license": {
                    "id": "CC-BY-4.0",
                    "declarationSource": "https://huggingface.co/datasets/google/fleurs",
                    "legalCodeSource": (
                        "https://creativecommons.org/licenses/by/4.0/legalcode.txt"
                    ),
                    "legalCodeSha256": "9" * 64,
                },
                "artifacts": {
                    "audioArchive": _artifact(
                        archive_path,
                        "data/es_419/audio/test.tar.gz",
                    ),
                    "metadata": {
                        **_artifact(metadata_path, "data/es_419/test.tsv"),
                        "gitBlobOid": git_blob_oid(metadata_path.read_bytes()),
                    },
                },
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return lock_path, archive_path, metadata_path


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_blob_oid(body: bytes) -> str:
    return hashlib.sha1(
        f"blob {len(body)}\0".encode() + body,
        usedforsecurity=False,
    ).hexdigest()


def _artifact(path: Path, repository_path: str) -> dict[str, object]:
    return {
        "repositoryPath": repository_path,
        "downloadSource": (
            "https://huggingface.co/datasets/google/fleurs/resolve/"
            f"{FLEURS_REVISION}/{repository_path}"
        ),
        "size": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _add_member(
    archive: tarfile.TarFile,
    name: str,
    body: bytes,
    *,
    link_target: str | None = None,
) -> None:
    member = tarfile.TarInfo(name)
    if link_target is None:
        member.size = len(body)
        archive.addfile(member, io.BytesIO(body))
    else:
        member.type = tarfile.SYMTYPE
        member.linkname = link_target
        archive.addfile(member)


def _float32_wav_bytes(samples: tuple[float, ...]) -> bytes:
    pcm = b"".join(struct.pack("<f", sample) for sample in samples)
    format_body = struct.pack("<HHIIHH", 3, 1, 16_000, 64_000, 4, 32)
    riff_size = 4 + 8 + len(format_body) + 8 + len(pcm)
    return b"".join(
        (
            b"RIFF",
            struct.pack("<I", riff_size),
            b"WAVE",
            b"fmt ",
            struct.pack("<I", len(format_body)),
            format_body,
            b"data",
            struct.pack("<I", len(pcm)),
            pcm,
        )
    )
