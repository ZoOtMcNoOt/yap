from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Any
from urllib.parse import urlparse

from yap_server.bounded_file import read_regular_text


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_REVISION = re.compile(r"^[0-9a-f]{40}$")
_PACKAGE_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_CPU_PACKAGE_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+\+cpu$")
_SAFE_PATH_PART = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_EXPECTED_ARTIFACTS = {
    "classifier.ckpt",
    "embedding_model.ckpt",
    "hyperparams.yaml",
    "label_encoder.txt",
}
_MAX_COMPONENT_LOCK_BYTES = 256 * 1024
_MAX_REQUIREMENTS_LOCK_BYTES = 4 * 1024 * 1024
_HASH_BLOCK_BYTES = 4 * 1024 * 1024


class LidComponentArtifactError(RuntimeError):
    """Raised when staged LID inputs differ from the immutable component lock."""


@dataclass(frozen=True)
class LockedLidArtifact:
    path: str
    size: int
    sha256: str


@dataclass(frozen=True)
class LidRuntimeLock:
    image: str
    source_tag: str
    source: str
    platform: str
    index_digest: str
    platform_digest: str
    python_version: str
    cpu_only: bool
    packages: tuple[tuple[str, str], ...]
    requirements_lock: str
    requirements_sha256: str


@dataclass(frozen=True)
class LidModelLock:
    model_id: str
    revision: str
    license: str
    source: str
    label_count: int
    artifacts: tuple[LockedLidArtifact, ...]


@dataclass(frozen=True)
class LidPolicyLock:
    revision: str
    sample_rate_hz: int
    channel_count: int
    sample_width_bytes: int
    minimum_source_samples: int
    maximum_windows: int
    maximum_window_samples: int
    minimum_voiced_samples_per_window: int
    score_semantics: str
    user_confirmation_required: bool


@dataclass(frozen=True)
class LidComponentLock:
    schema_version: int
    component_id: str
    role: str
    runtime: LidRuntimeLock
    model: LidModelLock
    policy: LidPolicyLock


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    return value


def _exact_keys(value: dict[str, Any], expected: set[str], field: str) -> None:
    actual = set(value)
    unexpected = sorted(actual - expected)
    missing = sorted(expected - actual)
    if unexpected:
        raise ValueError(f"{field} contains unexpected fields: {unexpected}")
    if missing:
        raise ValueError(f"{field} is missing fields: {missing}")


def _string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _sha256(value: Any, field: str) -> str:
    text = _string(value, field)
    if not _SHA256.fullmatch(text):
        raise ValueError(f"{field} must be a lowercase SHA-256")
    return text


def _digest(value: Any, field: str) -> str:
    text = _string(value, field)
    if not _DIGEST.fullmatch(text):
        raise ValueError(f"{field} must be a pinned sha256 digest")
    return text


def _positive_integer(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _boolean(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be a boolean")
    return value


def _https_url(value: Any, field: str) -> str:
    text = _string(value, field)
    parsed = urlparse(text)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f"{field} must be a stable HTTPS URL")
    return text


def _repo_relative_path(value: Any, field: str) -> str:
    text = _string(value, field)
    parsed = PurePosixPath(text)
    if (
        "\\" in text
        or parsed.is_absolute()
        or not parsed.parts
        or any(
            part in {"", ".", ".."} or not _SAFE_PATH_PART.fullmatch(part)
            for part in parsed.parts
        )
    ):
        raise ValueError(f"{field} must be a safe repository-relative path")
    return text


def _artifact_name(value: Any, field: str) -> str:
    text = _repo_relative_path(value, field)
    if len(PurePosixPath(text).parts) != 1:
        raise ValueError(f"{field} must be a single safe file name")
    return text


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _load_runtime(raw: Any) -> LidRuntimeLock:
    runtime = _mapping(raw, "component.runtime")
    _exact_keys(
        runtime,
        {
            "image",
            "sourceTag",
            "source",
            "platform",
            "indexDigest",
            "platformDigest",
            "pythonVersion",
            "cpuOnly",
            "packages",
            "requirementsLock",
            "requirementsSha256",
        },
        "component.runtime",
    )
    platform = _string(runtime["platform"], "component.runtime.platform")
    if platform != "linux/arm64":
        raise ValueError("the LID runtime must be pinned for linux/arm64")
    cpu_only = _boolean(runtime["cpuOnly"], "component.runtime.cpuOnly")
    if not cpu_only:
        raise ValueError("the isolated LID runtime must remain CPU-only")

    python_version = _string(
        runtime["pythonVersion"],
        "component.runtime.pythonVersion",
    )
    if not re.fullmatch(r"3\.12\.[0-9]+", python_version):
        raise ValueError("the LID runtime must use an exact Python 3.12 patch")
    source_tag = _string(runtime["sourceTag"], "component.runtime.sourceTag")
    if source_tag == "latest" or not source_tag.startswith(f"{python_version}-"):
        raise ValueError("runtime sourceTag must match the exact Python version")

    raw_packages = _mapping(runtime["packages"], "component.runtime.packages")
    _exact_keys(
        raw_packages,
        {"speechbrain", "torch", "torchaudio"},
        "component.runtime.packages",
    )
    speechbrain = _string(
        raw_packages["speechbrain"],
        "component.runtime.packages.speechbrain",
    )
    torch = _string(raw_packages["torch"], "component.runtime.packages.torch")
    torchaudio = _string(
        raw_packages["torchaudio"],
        "component.runtime.packages.torchaudio",
    )
    if not _PACKAGE_VERSION.fullmatch(speechbrain):
        raise ValueError("SpeechBrain must use an exact release version")
    if not _CPU_PACKAGE_VERSION.fullmatch(torch) or not _CPU_PACKAGE_VERSION.fullmatch(
        torchaudio
    ):
        raise ValueError("torch and torchaudio must use exact +cpu builds")
    if torch.removesuffix("+cpu") != torchaudio.removesuffix("+cpu"):
        raise ValueError("torch and torchaudio versions must match")

    return LidRuntimeLock(
        image=_string(runtime["image"], "component.runtime.image"),
        source_tag=source_tag,
        source=_https_url(runtime["source"], "component.runtime.source"),
        platform=platform,
        index_digest=_digest(
            runtime["indexDigest"],
            "component.runtime.indexDigest",
        ),
        platform_digest=_digest(
            runtime["platformDigest"],
            "component.runtime.platformDigest",
        ),
        python_version=python_version,
        cpu_only=cpu_only,
        packages=tuple(sorted(raw_packages.items())),
        requirements_lock=_repo_relative_path(
            runtime["requirementsLock"],
            "component.runtime.requirementsLock",
        ),
        requirements_sha256=_sha256(
            runtime["requirementsSha256"],
            "component.runtime.requirementsSha256",
        ),
    )


def _load_model(raw: Any) -> LidModelLock:
    model = _mapping(raw, "component.model")
    _exact_keys(
        model,
        {"id", "revision", "license", "source", "labelCount", "artifacts"},
        "component.model",
    )
    revision = _string(model["revision"], "component.model.revision")
    if not _REVISION.fullmatch(revision):
        raise ValueError("component.model.revision must be a full immutable commit")
    raw_artifacts = model["artifacts"]
    if not isinstance(raw_artifacts, list):
        raise ValueError("component.model.artifacts must be an array")
    artifacts: list[LockedLidArtifact] = []
    seen: set[str] = set()
    for index, raw_artifact in enumerate(raw_artifacts):
        field = f"component.model.artifacts[{index}]"
        artifact = _mapping(raw_artifact, field)
        _exact_keys(artifact, {"path", "size", "sha256"}, field)
        path = _artifact_name(artifact["path"], f"{field}.path")
        if path in seen:
            raise ValueError("component.model artifact paths must be unique")
        artifacts.append(
            LockedLidArtifact(
                path=path,
                size=_positive_integer(artifact["size"], f"{field}.size"),
                sha256=_sha256(artifact["sha256"], f"{field}.sha256"),
            )
        )
        seen.add(path)
    if seen != _EXPECTED_ARTIFACTS:
        raise ValueError("component.model.artifacts has the wrong artifact set")
    if [artifact.path for artifact in artifacts] != sorted(seen):
        raise ValueError("component.model.artifacts must be sorted by path")
    label_count = _positive_integer(
        model["labelCount"],
        "component.model.labelCount",
    )
    if label_count != 107:
        raise ValueError("the pinned VoxLingua107 model must expose 107 labels")
    return LidModelLock(
        model_id=_string(model["id"], "component.model.id"),
        revision=revision,
        license=_string(model["license"], "component.model.license"),
        source=_https_url(model["source"], "component.model.source"),
        label_count=label_count,
        artifacts=tuple(artifacts),
    )


def _load_policy(raw: Any) -> LidPolicyLock:
    policy = _mapping(raw, "component.policy")
    _exact_keys(
        policy,
        {
            "revision",
            "sampleRateHz",
            "channelCount",
            "sampleWidthBytes",
            "minimumSourceSamples",
            "maximumWindows",
            "maximumWindowSamples",
            "minimumVoicedSamplesPerWindow",
            "scoreSemantics",
            "userConfirmationRequired",
        },
        "component.policy",
    )
    sample_rate = _positive_integer(
        policy["sampleRateHz"],
        "component.policy.sampleRateHz",
    )
    channel_count = _positive_integer(
        policy["channelCount"],
        "component.policy.channelCount",
    )
    sample_width = _positive_integer(
        policy["sampleWidthBytes"],
        "component.policy.sampleWidthBytes",
    )
    maximum_windows = _positive_integer(
        policy["maximumWindows"],
        "component.policy.maximumWindows",
    )
    maximum_window_samples = _positive_integer(
        policy["maximumWindowSamples"],
        "component.policy.maximumWindowSamples",
    )
    minimum_source_samples = _positive_integer(
        policy["minimumSourceSamples"],
        "component.policy.minimumSourceSamples",
    )
    minimum_voiced_samples = _positive_integer(
        policy["minimumVoicedSamplesPerWindow"],
        "component.policy.minimumVoicedSamplesPerWindow",
    )
    if (sample_rate, channel_count, sample_width) != (16_000, 1, 2):
        raise ValueError("the LID input contract must be mono PCM16 at 16 kHz")
    if maximum_windows != 2:
        raise ValueError("the LID policy permits exactly two bounded probes")
    if maximum_window_samples > sample_rate * 15:
        raise ValueError("an LID probe cannot exceed 15 seconds")
    if minimum_voiced_samples > maximum_window_samples:
        raise ValueError("minimum voiced samples cannot exceed the probe window")
    if minimum_source_samples < maximum_windows * maximum_window_samples:
        raise ValueError("the source must be long enough for disjoint LID probes")
    score_semantics = _string(
        policy["scoreSemantics"],
        "component.policy.scoreSemantics",
    )
    if score_semantics != "uncalibrated-log-posterior":
        raise ValueError("LID scores must remain explicitly uncalibrated")
    confirmation_required = _boolean(
        policy["userConfirmationRequired"],
        "component.policy.userConfirmationRequired",
    )
    if not confirmation_required:
        raise ValueError("an LID suggestion always requires user confirmation")
    return LidPolicyLock(
        revision=_string(policy["revision"], "component.policy.revision"),
        sample_rate_hz=sample_rate,
        channel_count=channel_count,
        sample_width_bytes=sample_width,
        minimum_source_samples=minimum_source_samples,
        maximum_windows=maximum_windows,
        maximum_window_samples=maximum_window_samples,
        minimum_voiced_samples_per_window=minimum_voiced_samples,
        score_semantics=score_semantics,
        user_confirmation_required=confirmation_required,
    )


def load_lid_component_lock(path: Path) -> LidComponentLock:
    """Load and strictly validate the immutable isolated-LID component lock."""

    payload = _mapping(
        json.loads(
            read_regular_text(path, _MAX_COMPONENT_LOCK_BYTES),
            object_pairs_hook=_object_without_duplicates,
        ),
        "root",
    )
    _exact_keys(payload, {"schemaVersion", "component"}, "root")
    if payload["schemaVersion"] != 2:
        raise ValueError("unsupported LID component lock schema")
    component = _mapping(payload["component"], "component")
    _exact_keys(
        component,
        {"id", "role", "runtime", "model", "policy"},
        "component",
    )
    return LidComponentLock(
        schema_version=2,
        component_id=_string(component["id"], "component.id"),
        role=_string(component["role"], "component.role"),
        runtime=_load_runtime(component["runtime"]),
        model=_load_model(component["model"]),
        policy=_load_policy(component["policy"]),
    )


def _resolved_regular_file(path: Path, root: Path, label: str) -> Path:
    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise LidComponentArtifactError(f"missing locked {label}") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise LidComponentArtifactError(f"locked {label} is not a regular file")
    resolved = path.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise LidComponentArtifactError(f"locked {label} escapes its root") from error
    return resolved


def _hash_regular_file(
    path: Path,
    *,
    expected_size: int | None,
    maximum_size: int,
    label: str,
) -> str:
    metadata = path.lstat()
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise LidComponentArtifactError(
            f"locked {label} could not be opened"
        ) from error
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or (metadata.st_dev, metadata.st_ino) != (opened.st_dev, opened.st_ino)
        ):
            raise LidComponentArtifactError(
                f"locked {label} changed before verification"
            )
        if expected_size is not None and opened.st_size != expected_size:
            raise LidComponentArtifactError(f"locked {label} size differs")
        if opened.st_size > maximum_size:
            raise LidComponentArtifactError(f"locked {label} is oversized")
        digest = hashlib.sha256()
        while block := os.read(descriptor, _HASH_BLOCK_BYTES):
            digest.update(block)
        after = os.fstat(descriptor)
        if (
            (opened.st_dev, opened.st_ino, opened.st_size)
            != (after.st_dev, after.st_ino, after.st_size)
        ):
            raise LidComponentArtifactError(
                f"locked {label} changed during verification"
            )
        return digest.hexdigest()
    except OSError as error:
        raise LidComponentArtifactError(f"locked {label} could not be read") from error
    finally:
        os.close(descriptor)


def verify_lid_requirements(lock: LidComponentLock, repo_root: Path) -> Path:
    """Verify the hash-pinned requirements lock inside the repository."""

    try:
        root = repo_root.resolve(strict=True)
    except FileNotFoundError as error:
        raise LidComponentArtifactError("repository root is missing") from error
    if not root.is_dir():
        raise LidComponentArtifactError("repository root is not a directory")
    candidate = root / Path(lock.runtime.requirements_lock)
    resolved = _resolved_regular_file(candidate, root, "requirements lock")
    digest = _hash_regular_file(
        candidate,
        expected_size=None,
        maximum_size=_MAX_REQUIREMENTS_LOCK_BYTES,
        label="requirements lock",
    )
    if digest != lock.runtime.requirements_sha256:
        raise LidComponentArtifactError("locked requirements digest differs")
    return resolved


def verify_lid_model_artifacts(
    lock: LidComponentLock,
    model_dir: Path,
) -> None:
    """Verify every networklessly staged model artifact against the lock."""

    try:
        root = model_dir.resolve(strict=True)
    except FileNotFoundError as error:
        raise LidComponentArtifactError("model root is missing") from error
    if not root.is_dir():
        raise LidComponentArtifactError("model root is not a directory")
    for artifact in lock.model.artifacts:
        candidate = root / artifact.path
        _resolved_regular_file(candidate, root, artifact.path)
        digest = _hash_regular_file(
            candidate,
            expected_size=artifact.size,
            maximum_size=artifact.size,
            label=artifact.path,
        )
        if digest != artifact.sha256:
            raise LidComponentArtifactError(
                f"locked {artifact.path} digest differs"
            )
