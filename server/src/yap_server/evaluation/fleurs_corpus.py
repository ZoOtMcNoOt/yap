from __future__ import annotations

import csv
from collections.abc import Iterator
from dataclasses import dataclass, field
import hashlib
import io
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
import struct
import tarfile
from typing import BinaryIO, Mapping
from urllib.parse import urlsplit

from yap_server.bounded_file import read_regular_text
from yap_server.language_tags import canonical_bcp47
from yap_server.pools.pcm_audio import PcmAudio, decode_pcm16_wav


_MAX_LOCK_BYTES = 128 * 1024
_MAX_METADATA_BYTES = 16 * 1024 * 1024
_MAX_CASES = 100_000
_MAX_REFERENCE_CHARACTERS = 16_384
_MAX_PHONEME_CHARACTERS = 65_536
_MAX_AUDIO_SECONDS = 60
_MAX_WAV_CONTAINER_OVERHEAD = 64 * 1024
_REVISION = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_BLOB_OID = re.compile(r"^[0-9a-f]{40}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,255}$")
_FLEURS_CONFIG = re.compile(
    r"^(?P<language>[a-z]{2,3})"
    r"(?:_(?P<script>[a-z]{4}))?"
    r"(?:_(?P<region>[a-z]{2}|[0-9]{3}))?$"
)
_AUDIO_FILE = re.compile(r"^[0-9]{1,20}\.wav$")


@dataclass(frozen=True, slots=True)
class FleursArtifactLock:
    repository_path: str
    download_source: str
    size: int
    sha256: str
    git_blob_oid: str | None = None


@dataclass(frozen=True, slots=True)
class FleursReleaseLock:
    dataset_id: str
    dataset_revision: str
    dataset_config: str
    split: str
    locale_bcp47: str
    source: str
    expected_case_count: int
    license_id: str
    license_declaration_source: str
    license_legal_code_source: str
    license_legal_code_sha256: str
    audio_archive: FleursArtifactLock
    metadata: FleursArtifactLock


@dataclass(frozen=True, slots=True)
class FleursCorpusInspection:
    dataset_id: str
    dataset_revision: str
    dataset_config: str
    split: str
    locale_bcp47: str
    case_count: int
    total_duration_samples: int
    minimum_duration_samples: int
    maximum_duration_samples: int
    audio_archive_sha256: str
    metadata_sha256: str


@dataclass(frozen=True, slots=True)
class FleursComparatorCase:
    case_index: int
    source_item_id: str
    prompt_id: int
    duration_samples: int
    audio: PcmAudio = field(repr=False)
    reference: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class _FleursCase:
    prompt_id: int
    audio_file: str
    duration_samples: int
    gender: str
    transcription: str = field(repr=False)
    normalized_transcription: str = field(repr=False)
    phonemes: str = field(repr=False)


def fleurs_config_to_bcp47(dataset_config: str) -> str:
    """Map one FLEURS config ID to a canonical tag without inventing a region."""

    if not isinstance(dataset_config, str):
        raise ValueError("FLEURS config must be a canonical dataset identifier")
    matched = _FLEURS_CONFIG.fullmatch(dataset_config)
    if matched is None:
        raise ValueError("FLEURS config must be a canonical dataset identifier")
    components = [matched.group("language")]
    if script := matched.group("script"):
        components.append(script.title())
    if region := matched.group("region"):
        components.append(region if region.isdigit() else region.upper())
    return canonical_bcp47("-".join(components), "FLEURS config locale")


def load_fleurs_release_lock(path: Path) -> FleursReleaseLock:
    root = _object(
        json.loads(read_regular_text(path, _MAX_LOCK_BYTES)),
        {"schemaVersion", "dataset", "expectedCaseCount", "license", "artifacts"},
        "FLEURS release lock",
    )
    if root["schemaVersion"] != 1:
        raise ValueError("unsupported FLEURS release-lock schema")
    dataset = _object(
        root["dataset"],
        {"id", "revision", "config", "split", "localeBcp47", "source"},
        "FLEURS dataset",
    )
    dataset_id = _identifier(dataset["id"], "FLEURS dataset ID")
    if dataset_id != "google/fleurs":
        raise ValueError("FLEURS dataset ID is unsupported")
    revision = _fullmatch(
        dataset["revision"],
        _REVISION,
        "FLEURS dataset revision",
    )
    config = _text(dataset["config"], "FLEURS dataset config", 32)
    locale = canonical_bcp47(dataset["localeBcp47"], "FLEURS localeBcp47")
    if fleurs_config_to_bcp47(config) != locale:
        raise ValueError("FLEURS config and localeBcp47 differ")
    split = _text(dataset["split"], "FLEURS split", 32)
    if re.fullmatch(r"[a-z][a-z0-9_-]*", split) is None:
        raise ValueError("FLEURS split is invalid")
    source = _https(dataset["source"], "FLEURS dataset source")
    if revision not in source:
        raise ValueError("FLEURS dataset source must bind the immutable revision")

    expected_case_count = _positive_int(
        root["expectedCaseCount"],
        "FLEURS expected case count",
    )
    if expected_case_count > _MAX_CASES:
        raise ValueError("FLEURS expected case count exceeds the bound")

    license_value = _object(
        root["license"],
        {"id", "declarationSource", "legalCodeSource", "legalCodeSha256"},
        "FLEURS license",
    )
    license_id = _identifier(license_value["id"], "FLEURS license ID")
    if license_id != "CC-BY-4.0":
        raise ValueError("FLEURS license ID is unsupported")
    declaration_source = _https(
        license_value["declarationSource"],
        "FLEURS license declaration source",
    )
    legal_code_source = _https(
        license_value["legalCodeSource"],
        "FLEURS license legal-code source",
    )
    legal_code_sha256 = _sha256(
        license_value["legalCodeSha256"],
        "FLEURS license legal-code SHA-256",
    )

    artifacts = _object(
        root["artifacts"],
        {"audioArchive", "metadata"},
        "FLEURS artifacts",
    )
    archive = _artifact_lock(
        artifacts["audioArchive"],
        "FLEURS audio archive",
        revision=revision,
        git_blob_required=False,
    )
    metadata = _artifact_lock(
        artifacts["metadata"],
        "FLEURS metadata",
        revision=revision,
        git_blob_required=True,
    )
    if archive.repository_path != f"data/{config}/audio/{split}.tar.gz":
        raise ValueError("FLEURS audio archive repository path is invalid")
    if metadata.repository_path != f"data/{config}/{split}.tsv":
        raise ValueError("FLEURS metadata repository path is invalid")

    return FleursReleaseLock(
        dataset_id=dataset_id,
        dataset_revision=revision,
        dataset_config=config,
        split=split,
        locale_bcp47=locale,
        source=source,
        expected_case_count=expected_case_count,
        license_id=license_id,
        license_declaration_source=declaration_source,
        license_legal_code_source=legal_code_source,
        license_legal_code_sha256=legal_code_sha256,
        audio_archive=archive,
        metadata=metadata,
    )


def inspect_fleurs_release(
    *,
    lock: FleursReleaseLock,
    archive_path: Path,
    metadata_path: Path,
    environ: Mapping[str, str] = os.environ,
) -> FleursCorpusInspection:
    """Verify one acquired FLEURS split and return transcript-free evidence."""

    inspection, _cases = _verify_fleurs_release(
        lock=lock,
        archive_path=archive_path,
        metadata_path=metadata_path,
        environ=environ,
    )
    return inspection


def iter_fleurs_comparator_cases(
    *,
    lock: FleursReleaseLock,
    archive_path: Path,
    metadata_path: Path,
    case_count: int,
    environ: Mapping[str, str] = os.environ,
) -> Iterator[FleursComparatorCase]:
    """Yield a verified metadata-prefix selection without extracting the corpus."""

    _inspection, cases = _verify_fleurs_release(
        lock=lock,
        archive_path=archive_path,
        metadata_path=metadata_path,
        environ=environ,
    )
    if (
        not isinstance(case_count, int)
        or isinstance(case_count, bool)
        or not 1 <= case_count <= len(cases)
    ):
        raise ValueError("FLEURS comparator case count is invalid")
    selected = {
        case.audio_file: (case_index, case)
        for case_index, case in enumerate(cases[:case_count])
    }
    seen: set[str] = set()
    cache_root = _private_cache_root(environ)
    private_archive = _private_artifact(
        archive_path,
        cache_root,
        "FLEURS audio archive",
    )
    with _open_verified_artifact(
        private_archive,
        lock.audio_archive,
        field="FLEURS audio archive",
    ) as source:
        try:
            with tarfile.open(fileobj=source, mode="r:gz") as archive:
                for member in archive:
                    parsed = _validated_archive_member(member)
                    if parsed is None:
                        continue
                    selected_case = selected.get(parsed.name)
                    if selected_case is None:
                        continue
                    if parsed.name in seen:
                        raise ValueError(
                            "FLEURS archive membership differs from metadata"
                        )
                    case_index, case = selected_case
                    minimum_bytes = case.duration_samples * 4
                    maximum_bytes = minimum_bytes + _MAX_WAV_CONTAINER_OVERHEAD
                    if not minimum_bytes <= member.size <= maximum_bytes:
                        raise ValueError("FLEURS archive member size is invalid")
                    extracted = archive.extractfile(member)
                    if extracted is None:
                        raise ValueError("FLEURS archive member could not be read")
                    with extracted:
                        float32_pcm = _read_wave_data(
                            extracted,
                            case,
                            member_size=member.size,
                        )
                    audio = decode_pcm16_wav(
                        _pcm16_wave(_float32_to_pcm16_le(float32_pcm)),
                        max_audio_seconds=_MAX_AUDIO_SECONDS,
                    )
                    if audio.frame_count != case.duration_samples:
                        raise RuntimeError(
                            "FLEURS PCM conversion changed source duration"
                        )
                    seen.add(parsed.name)
                    yield FleursComparatorCase(
                        case_index=case_index,
                        source_item_id=case.audio_file,
                        prompt_id=case.prompt_id,
                        duration_samples=case.duration_samples,
                        audio=audio,
                        reference=case.transcription,
                    )
        except (tarfile.TarError, EOFError) as error:
            raise ValueError("FLEURS audio archive is invalid") from error
    if seen != set(selected):
        raise ValueError("FLEURS archive membership differs from the selection")


def _verify_fleurs_release(
    *,
    lock: FleursReleaseLock,
    archive_path: Path,
    metadata_path: Path,
    environ: Mapping[str, str],
) -> tuple[FleursCorpusInspection, tuple[_FleursCase, ...]]:
    if not isinstance(lock, FleursReleaseLock):
        raise TypeError("lock must be a FleursReleaseLock")
    cache_root = _private_cache_root(environ)
    archive_path = _private_artifact(archive_path, cache_root, "FLEURS audio archive")
    metadata_path = _private_artifact(metadata_path, cache_root, "FLEURS metadata")
    metadata_body = _read_verified_small_artifact(
        metadata_path,
        lock.metadata,
        field="FLEURS metadata",
    )
    cases = _parse_metadata(
        metadata_body,
        expected_case_count=lock.expected_case_count,
    )
    _inspect_archive(
        archive_path,
        lock.audio_archive,
        cases=cases,
    )
    durations = [case.duration_samples for case in cases]
    return (
        FleursCorpusInspection(
            dataset_id=lock.dataset_id,
            dataset_revision=lock.dataset_revision,
            dataset_config=lock.dataset_config,
            split=lock.split,
            locale_bcp47=lock.locale_bcp47,
            case_count=len(cases),
            total_duration_samples=sum(durations),
            minimum_duration_samples=min(durations),
            maximum_duration_samples=max(durations),
            audio_archive_sha256=lock.audio_archive.sha256,
            metadata_sha256=lock.metadata.sha256,
        ),
        cases,
    )


def _parse_metadata(body: bytes, *, expected_case_count: int) -> tuple[_FleursCase, ...]:
    if not 1 <= len(body) <= _MAX_METADATA_BYTES:
        raise ValueError("FLEURS metadata size is invalid")
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("FLEURS metadata is not UTF-8") from error
    try:
        rows = list(csv.reader(io.StringIO(text), delimiter="\t", strict=True))
    except csv.Error as error:
        raise ValueError("FLEURS metadata is not valid TSV") from error
    if len(rows) != expected_case_count:
        raise ValueError("FLEURS metadata case count differs from the lock")

    cases: list[_FleursCase] = []
    audio_files: set[str] = set()
    for row_index, row in enumerate(rows):
        if len(row) != 7:
            raise ValueError(f"FLEURS metadata row {row_index} has the wrong shape")
        raw_id, audio_file, transcription, normalized, phonemes, samples, gender = row
        try:
            prompt_id = int(raw_id)
        except ValueError as error:
            raise ValueError(
                f"FLEURS metadata row {row_index} has an invalid prompt ID"
            ) from error
        if prompt_id < 0:
            raise ValueError("FLEURS metadata prompt IDs must be nonnegative integers")
        if _AUDIO_FILE.fullmatch(audio_file) is None or audio_file in audio_files:
            raise ValueError("FLEURS metadata audio files must be unique safe WAV names")
        if not 1 <= len(transcription) <= _MAX_REFERENCE_CHARACTERS:
            raise ValueError("FLEURS transcription length is invalid")
        if not 1 <= len(normalized) <= _MAX_REFERENCE_CHARACTERS:
            raise ValueError("FLEURS normalized transcription length is invalid")
        if not 1 <= len(phonemes) <= _MAX_PHONEME_CHARACTERS:
            raise ValueError("FLEURS phoneme sequence length is invalid")
        try:
            duration_samples = int(samples)
        except ValueError as error:
            raise ValueError("FLEURS duration sample count is invalid") from error
        if not 1 <= duration_samples <= 16_000 * _MAX_AUDIO_SECONDS:
            raise ValueError("FLEURS duration sample count is outside the bound")
        if gender not in {"FEMALE", "MALE"}:
            raise ValueError("FLEURS gender label is unsupported")
        audio_files.add(audio_file)
        cases.append(
            _FleursCase(
                prompt_id=prompt_id,
                audio_file=audio_file,
                duration_samples=duration_samples,
                gender=gender,
                transcription=transcription,
                normalized_transcription=normalized,
                phonemes=phonemes,
            )
        )
    return tuple(cases)


def _inspect_archive(
    path: Path,
    artifact: FleursArtifactLock,
    *,
    cases: tuple[_FleursCase, ...],
) -> None:
    expected = {case.audio_file: case for case in cases}
    seen: set[str] = set()
    with _open_verified_artifact(path, artifact, field="FLEURS audio archive") as source:
        try:
            with tarfile.open(fileobj=source, mode="r:gz") as archive:
                for member in archive:
                    parsed = _validated_archive_member(member)
                    if parsed is None:
                        continue
                    audio_file = parsed.name
                    case = expected.get(audio_file)
                    if case is None or audio_file in seen:
                        raise ValueError("FLEURS archive membership differs from metadata")
                    minimum_bytes = case.duration_samples * 4
                    maximum_bytes = minimum_bytes + _MAX_WAV_CONTAINER_OVERHEAD
                    if not minimum_bytes <= member.size <= maximum_bytes:
                        raise ValueError("FLEURS archive member size is invalid")
                    extracted = archive.extractfile(member)
                    if extracted is None:
                        raise ValueError("FLEURS archive member could not be read")
                    with extracted:
                        _read_wave_data(extracted, case, member_size=member.size)
                    seen.add(audio_file)
        except (tarfile.TarError, EOFError) as error:
            raise ValueError("FLEURS audio archive is invalid") from error
    if seen != set(expected):
        raise ValueError("FLEURS archive membership differs from metadata")


def _validated_archive_member(member: tarfile.TarInfo) -> PurePosixPath | None:
    parsed = PurePosixPath(member.name)
    if parsed.is_absolute() or ".." in parsed.parts or "\\" in member.name:
        raise ValueError("FLEURS archive member path is unsafe")
    if member.isdir():
        return None
    if not member.isfile():
        raise ValueError("FLEURS archive member must be a regular file")
    return parsed


def _read_wave_data(
    source: BinaryIO,
    case: _FleursCase,
    *,
    member_size: int,
) -> bytes:
    header = source.read(12)
    if len(header) != 12 or header[:4] != b"RIFF" or header[8:] != b"WAVE":
        raise ValueError("FLEURS archive member is not a RIFF WAV")
    if struct.unpack("<I", header[4:8])[0] + 8 != member_size:
        raise ValueError("FLEURS archive member RIFF size is invalid")

    format_verified = False
    for _chunk_index in range(32):
        chunk_header = source.read(8)
        if len(chunk_header) != 8:
            break
        chunk_id = chunk_header[:4]
        chunk_size = struct.unpack("<I", chunk_header[4:])[0]
        if chunk_id == b"fmt ":
            if not 16 <= chunk_size <= 256:
                raise ValueError("FLEURS archive member WAV format size is invalid")
            format_body = source.read(chunk_size)
            if len(format_body) != chunk_size:
                raise ValueError("FLEURS archive member WAV format is truncated")
            audio_format, channels, sample_rate, byte_rate, alignment, bits = (
                struct.unpack("<HHIIHH", format_body[:16])
            )
            if (
                audio_format != 3
                or channels != 1
                or sample_rate != 16_000
                or byte_rate != 64_000
                or alignment != 4
                or bits != 32
            ):
                raise ValueError(
                    "FLEURS archive member must be mono 16 kHz float32 WAV"
                )
            format_verified = True
        elif chunk_id == b"data":
            if not format_verified:
                raise ValueError("FLEURS archive member WAV data precedes its format")
            if chunk_size != case.duration_samples * 4:
                raise ValueError("FLEURS archive member WAV shape differs from metadata")
            body = source.read(chunk_size)
            if len(body) != chunk_size:
                raise ValueError("FLEURS archive member WAV data is truncated")
            return body
        else:
            _skip_exact(source, chunk_size)
        if chunk_size % 2:
            _skip_exact(source, 1)
    raise ValueError("FLEURS archive member WAV data is missing")


def _float32_to_pcm16_le(body: bytes) -> bytes:
    if not body or len(body) % 4:
        raise ValueError("FLEURS float32 PCM length is invalid")
    try:
        import numpy as np
    except ModuleNotFoundError:
        return _float32_to_pcm16_le_portable(body)

    samples = np.frombuffer(body, dtype="<f4")
    if not bool(np.isfinite(samples).all()):
        raise ValueError("FLEURS float32 PCM contains a non-finite sample")
    bounded = np.clip(samples, np.float32(-1.0), np.float32(1.0))
    scaled = bounded * np.float32(32_767.0)
    rounded = np.where(
        scaled >= 0,
        np.floor(scaled + np.float32(0.5)),
        np.ceil(scaled - np.float32(0.5)),
    )
    values = rounded.astype("<i2")
    values[samples <= -1.0] = -32_768
    values[samples >= 1.0] = 32_767
    return values.tobytes()


def _float32_to_pcm16_le_portable(body: bytes) -> bytes:
    output = bytearray(len(body) // 2)
    offset = 0
    for (sample,) in struct.iter_unpack("<f", body):
        if not math.isfinite(sample):
            raise ValueError("FLEURS float32 PCM contains a non-finite sample")
        if sample <= -1.0:
            value = -32_768
        elif sample >= 1.0:
            value = 32_767
        else:
            scaled = sample * 32_767.0
            value = (
                math.floor(scaled + 0.5)
                if scaled >= 0
                else math.ceil(scaled - 0.5)
            )
        struct.pack_into("<h", output, offset, value)
        offset += 2
    return bytes(output)


def _pcm16_wave(pcm: bytes) -> bytes:
    data_size = len(pcm)
    return b"".join(
        (
            b"RIFF",
            struct.pack("<I", 36 + data_size),
            b"WAVEfmt ",
            struct.pack("<IHHIIHH", 16, 1, 1, 16_000, 32_000, 2, 16),
            b"data",
            struct.pack("<I", data_size),
            pcm,
        )
    )


def _skip_exact(source: BinaryIO, byte_count: int) -> None:
    remaining = byte_count
    while remaining:
        body = source.read(min(remaining, 64 * 1024))
        if not body:
            raise ValueError("FLEURS archive member WAV chunk is truncated")
        remaining -= len(body)


class _VerifiedArtifact:
    def __init__(self, source: BinaryIO) -> None:
        self._source = source

    def __enter__(self) -> BinaryIO:
        return self._source

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self._source.close()


def _open_verified_artifact(
    path: Path,
    artifact: FleursArtifactLock,
    *,
    field: str,
) -> _VerifiedArtifact:
    if path.is_symlink():
        raise ValueError(f"{field} must be a real file")
    try:
        resolved = path.resolve(strict=True)
        metadata = resolved.lstat()
    except FileNotFoundError as error:
        raise ValueError(f"{field} is missing") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ValueError(f"{field} must be a real file")
    if metadata.st_size != artifact.size:
        raise ValueError(f"{field} size differs from the lock")
    source = resolved.open("rb")
    try:
        digest = hashlib.sha256()
        for block in iter(lambda: source.read(4 * 1024 * 1024), b""):
            digest.update(block)
        if digest.hexdigest() != artifact.sha256:
            raise ValueError(f"{field} SHA-256 differs from the lock")
        after = os.fstat(source.fileno())
        if after.st_size != metadata.st_size or after.st_mtime_ns != metadata.st_mtime_ns:
            raise ValueError(f"{field} changed during verification")
        source.seek(0)
        return _VerifiedArtifact(source)
    except Exception:
        source.close()
        raise


def _read_verified_small_artifact(
    path: Path,
    artifact: FleursArtifactLock,
    *,
    field: str,
) -> bytes:
    if artifact.size > _MAX_METADATA_BYTES:
        raise ValueError(f"{field} exceeds the bounded metadata size")
    with _open_verified_artifact(path, artifact, field=field) as source:
        body = source.read(_MAX_METADATA_BYTES + 1)
    if len(body) != artifact.size:
        raise ValueError(f"{field} changed while it was read")
    if artifact.git_blob_oid is not None:
        header = f"blob {len(body)}\0".encode("ascii")
        if (
            hashlib.sha1(header + body, usedforsecurity=False).hexdigest()
            != artifact.git_blob_oid
        ):
            raise ValueError(f"{field} Git blob identity differs from the lock")
    return body


def _artifact_lock(
    value: object,
    field: str,
    *,
    revision: str,
    git_blob_required: bool,
) -> FleursArtifactLock:
    fields = {"repositoryPath", "downloadSource", "size", "sha256"}
    if git_blob_required:
        fields.add("gitBlobOid")
    item = _object(value, fields, field)
    repository_path = _safe_repository_path(item["repositoryPath"], field)
    download_source = _https(item["downloadSource"], f"{field} download source")
    if revision not in download_source or repository_path not in download_source:
        raise ValueError(f"{field} download source is not revision-bound")
    git_blob_oid = None
    if git_blob_required:
        git_blob_oid = _fullmatch(
            item["gitBlobOid"],
            _GIT_BLOB_OID,
            f"{field} Git blob OID",
        )
    return FleursArtifactLock(
        repository_path=repository_path,
        download_source=download_source,
        size=_positive_int(item["size"], f"{field} size"),
        sha256=_sha256(item["sha256"], f"{field} SHA-256"),
        git_blob_oid=git_blob_oid,
    )


def _object(value: object, keys: set[str], field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise ValueError(f"{field} fields differ from the contract")
    return value


def _text(value: object, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= maximum:
        raise ValueError(f"{field} must be bounded text")
    return value


def _identifier(value: object, field: str) -> str:
    text = _text(value, field, 256)
    if _IDENTIFIER.fullmatch(text) is None:
        raise ValueError(f"{field} is invalid")
    return text


def _fullmatch(value: object, pattern: re.Pattern[str], field: str) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise ValueError(f"{field} is invalid")
    return value


def _sha256(value: object, field: str) -> str:
    return _fullmatch(value, _SHA256, field)


def _positive_int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _https(value: object, field: str) -> str:
    text = _text(value, field, 2048)
    try:
        parsed = urlsplit(text)
    except ValueError as error:
        raise ValueError(f"{field} must be an absolute HTTPS URL") from error
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError(f"{field} must be an absolute HTTPS URL")
    return text


def _safe_repository_path(value: object, field: str) -> str:
    text = _text(value, f"{field} repository path", 512)
    parsed = PurePosixPath(text)
    if parsed.is_absolute() or ".." in parsed.parts or "\\" in text:
        raise ValueError(f"{field} repository path is unsafe")
    return text


def _private_cache_root(environ: Mapping[str, str]) -> Path:
    raw = environ.get("YAP_EVAL_CACHE", "").strip()
    if not raw:
        raise ValueError("YAP_EVAL_CACHE is required for FLEURS evidence")
    requested = Path(raw)
    if not requested.is_absolute() or requested.is_symlink():
        raise ValueError("YAP_EVAL_CACHE must be an absolute real directory")
    repository = _find_repository_root(Path(__file__))
    resolved = requested.resolve(strict=True)
    if repository is not None and (
        resolved == repository or repository in resolved.parents
    ):
        raise ValueError("YAP_EVAL_CACHE must remain outside the repository")
    metadata = resolved.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("YAP_EVAL_CACHE must be a real directory")
    if os.name == "posix" and stat.S_IMODE(metadata.st_mode) & 0o077:
        raise ValueError("YAP_EVAL_CACHE must use private permissions")
    return resolved


def _find_repository_root(module_path: Path) -> Path | None:
    """Return the enclosing Git worktree, or None for an installed source mount."""

    resolved = module_path.resolve(strict=False)
    start = resolved if resolved.is_dir() else resolved.parent
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate.resolve(strict=True)
    return None


def _private_artifact(path: Path, cache_root: Path, field: str) -> Path:
    if not path.is_absolute() or path.is_symlink():
        raise ValueError(f"{field} must be an absolute real file")
    resolved = path.resolve(strict=True)
    if cache_root not in resolved.parents:
        raise ValueError(f"{field} must remain inside YAP_EVAL_CACHE")
    return resolved
