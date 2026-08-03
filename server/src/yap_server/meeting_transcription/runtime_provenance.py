"""Immutable provenance for the upstream Tiron whole-meeting runtime."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
import stat
from typing import Mapping

from yap_server.artifact_identity import (
    ArtifactIdentity,
    artifact_identities,
    portable_artifact_path,
    require_artifact_paths,
)
from yap_server.json_contract import (
    exact_object,
    https_uri,
    positive_int,
    sha256,
)
from yap_server.private_artifact import (
    read_bounded_regular_file,
    read_json_object_with_identity,
)


_CURRENT_MODEL_REVISION = "90bc0a4d198cd5cf6679b0e478375ba3a0040575"
_CURRENT_HARNESS_REVISION = "d249c5a81fc6e0f1ecd34fd30cf2519f06fe671c"
_CURRENT_ECAPA_REVISION = "0f99f2d0ebe89ac095bcc5903c4dd8f72b367286"
_BASE_DIGEST = (
    "sha256:dcae8df08ef61b019b8eb109113428cba4ef0e37484c6e722406150dd5ada759"
)
_HEX_REVISION = re.compile(r"^[0-9a-f]{40}$")
_MAX_LOCK_BYTES = 256 * 1024

_MODEL_PATHS = frozenset(
    {
        ".gitattributes",
        "README.md",
        "added_tokens.json",
        "config.json",
        "generation_config.json",
        "merges.txt",
        "model.safetensors",
        "normalizer.json",
        "preprocessor_config.json",
        "special_tokens_map.json",
        "tiron_benchmark.png",
        "tokenizer.json",
        "tokenizer_config.json",
        "vocab.json",
    }
)
_HARNESS_PATHS = frozenset(
    {
        ".gitignore",
        "docs/benchmark.png",
        "eval/README.md",
        "eval/run_eval.py",
        "eval/scoring.py",
        "LICENSE",
        "pyproject.toml",
        "README.md",
        "tests/test_chunking.py",
        "tests/test_constraints.py",
        "tests/test_decode.py",
        "tests/test_linking.py",
        "tiron/__init__.py",
        "tiron/cli.py",
        "tiron/config.py",
        "tiron/constraints.py",
        "tiron/decode.py",
        "tiron/engine.py",
        "tiron/formats.py",
        "tiron/pipeline.py",
    }
)
_ECAPA_PATHS = frozenset(
    {
        ".gitattributes",
        "README.md",
        "classifier.ckpt",
        "config.json",
        "embedding_model.ckpt",
        "example1.wav",
        "example2.flac",
        "hyperparams.yaml",
        "label_encoder.txt",
        "mean_var_norm_emb.ckpt",
    }
)
_BASE_PACKAGES = {
    "fsspec": "2026.4.0",
    "huggingface-hub": "1.18.0",
    "numpy": "2.1.0",
    "packaging": "26.0",
    "PyYAML": "6.0.1",
    "requests": "2.34.2",
    "safetensors": "0.8.0",
    "scipy": "1.17.1",
    "tqdm": "4.68.2",
    "torchvision": "0.27.0a0+499ca510.nv26.6.54250401",
}


@dataclass(frozen=True, slots=True)
class CompatibilityPatch:
    identifier: str
    script: str
    script_sha256: str
    target: str
    upstream_sha256: str
    patched_sha256: str


@dataclass(frozen=True, slots=True)
class RepositorySource:
    identifier: str
    revision: str
    source: str
    license_spdx: str
    artifacts: tuple[ArtifactIdentity, ...]
    compatibility_patches: tuple[CompatibilityPatch, ...] = ()

    def artifact(self, path: str) -> ArtifactIdentity:
        for artifact in self.artifacts:
            if artifact.path == path:
                return artifact
        raise ValueError(f"artifact {path!r} is not locked")


@dataclass(frozen=True, slots=True)
class BaseRuntime:
    image: str
    source_tag: str
    source: str
    platform: str
    digest: str
    python_version: str
    torch_version: str
    cuda_version: str
    torch_cuda_version: str
    base_packages: Mapping[str, str]
    requirements_lock: str
    requirements_lock_sha256: str


@dataclass(frozen=True, slots=True)
class ExecutionPolicy:
    network_downloads_allowed: bool
    model_directory_environment: str
    speaker_encoder_directory_environment: str
    offline_environment: tuple[str, ...]
    production_default: bool
    requires_acceptance_seal: bool


@dataclass(frozen=True, slots=True)
class MeetingRuntimeProvenance:
    runtime_authority: str
    model: RepositorySource
    harness: RepositorySource
    speaker_encoder: RepositorySource
    base_runtime: BaseRuntime
    execution: ExecutionPolicy


def load_meeting_runtime_provenance(path: Path) -> MeetingRuntimeProvenance:
    root, _identity = read_json_object_with_identity(
        path,
        maximum_bytes=_MAX_LOCK_BYTES,
        field="meeting runtime provenance",
    )
    root = exact_object(
        root,
        {
            "schemaVersion",
            "runtimeAuthority",
            "model",
            "harness",
            "speakerEncoder",
            "baseRuntime",
            "execution",
            "supersedes",
        },
        "meeting runtime provenance",
    )
    if root["schemaVersion"] != 1:
        raise ValueError("unsupported meeting runtime provenance schema")
    if root["runtimeAuthority"] != "upstream-tiron-harness":
        raise ValueError("whole-meeting runtime authority must remain the upstream harness")

    model = _model_source(root["model"])
    harness = _harness_source(root["harness"])
    speaker_encoder = _speaker_encoder_source(root["speakerEncoder"])
    base_runtime = _base_runtime(root["baseRuntime"])
    execution = _execution_policy(root["execution"])
    _superseded_sources(root["supersedes"])
    return MeetingRuntimeProvenance(
        runtime_authority="upstream-tiron-harness",
        model=model,
        harness=harness,
        speaker_encoder=speaker_encoder,
        base_runtime=base_runtime,
        execution=execution,
    )


def verify_meeting_runtime_repository_files(
    provenance: MeetingRuntimeProvenance,
    *,
    repository_root: Path,
) -> None:
    if not isinstance(provenance, MeetingRuntimeProvenance):
        raise ValueError("meeting runtime provenance is invalid")
    root = repository_root.resolve(strict=True)
    requirements_path = root / provenance.base_runtime.requirements_lock
    body = read_bounded_regular_file(
        requirements_path,
        maximum_bytes=128 * 1024,
        field="meeting runtime requirements lock",
        containment_root=root,
    )
    if hashlib.sha256(body).hexdigest() != provenance.base_runtime.requirements_lock_sha256:
        raise ValueError("meeting runtime requirements lock SHA-256 differs")
    for patch in provenance.harness.compatibility_patches:
        patch_body = read_bounded_regular_file(
            root / patch.script,
            maximum_bytes=64 * 1024,
            field="meeting runtime compatibility patch",
            containment_root=root,
        )
        if hashlib.sha256(patch_body).hexdigest() != patch.script_sha256:
            raise ValueError("meeting runtime compatibility patch SHA-256 differs")


def verify_repository_source_directory(
    source: RepositorySource,
    directory: Path,
) -> Path:
    """Verify one materialized upstream repository without accepting extras."""

    if not isinstance(source, RepositorySource):
        raise ValueError("repository source identity is invalid")
    try:
        root = directory.resolve(strict=True)
    except FileNotFoundError as error:
        raise ValueError("locked repository source directory is missing") from error
    if not root.is_dir():
        raise ValueError("locked repository source root is not a directory")

    actual_paths: set[str] = set()
    for candidate in root.rglob("*"):
        metadata = candidate.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise ValueError("locked repository source contains a symbolic link")
        if stat.S_ISDIR(metadata.st_mode):
            continue
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("locked repository source contains a special file")
        actual_paths.add(candidate.relative_to(root).as_posix())

    expected_paths = {artifact.path for artifact in source.artifacts}
    if actual_paths - expected_paths:
        raise ValueError("locked repository source contains unexpected artifacts")
    if expected_paths - actual_paths:
        raise ValueError("locked repository source is missing artifacts")

    for artifact in source.artifacts:
        candidate = root / artifact.path
        metadata = candidate.lstat()
        if metadata.st_size != artifact.size:
            raise ValueError(
                f"locked repository artifact size differs: {artifact.path}"
            )
        digest = hashlib.sha256()
        with candidate.open("rb") as handle:
            for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
                digest.update(block)
        if digest.hexdigest() != artifact.sha256:
            raise ValueError(
                f"locked repository artifact digest differs: {artifact.path}"
            )
    return root


def _model_source(value: object) -> RepositorySource:
    source = exact_object(
        value,
        {"id", "revision", "source", "license", "artifacts"},
        "Tiron model source",
    )
    result = _repository_source(
        source,
        field="Tiron model",
        expected_id="Trelis/tiron",
        expected_revision=_CURRENT_MODEL_REVISION,
        expected_source="https://huggingface.co/Trelis/tiron",
        expected_paths=_MODEL_PATHS,
        license_spdx="Apache-2.0",
        license_declaration=(
            "README.md",
            "80a327fa681ea70489a61361525eb628a6c9b5c98be5692e4fde57ed871a1e48",
        ),
    )
    if result.artifact("model.safetensors") != ArtifactIdentity(
        path="model.safetensors",
        size=3_087_229_512,
        sha256="2e9f644c5eb633d3c387975cf38677d3ffe1a7b98830a735867865ec1bd519b5",
    ):
        raise ValueError("current Tiron model weight differs from the contract")
    return result


def _harness_source(value: object) -> RepositorySource:
    source = exact_object(
        value,
            {
                "id",
                "revision",
                "source",
                "install",
                "license",
                "artifacts",
                "compatibilityPatches",
            },
        "Tiron harness source",
    )
    if source["install"] != "verified-pinned-source-runtime":
        raise ValueError("Tiron harness install policy differs from the contract")
    result = _repository_source(
        source,
        field="Tiron harness",
        expected_id="TrelisResearch/tiron",
        expected_revision=_CURRENT_HARNESS_REVISION,
        expected_source="https://github.com/TrelisResearch/tiron",
        expected_paths=_HARNESS_PATHS,
        license_spdx="Apache-2.0",
        license_file=(
            "https://raw.githubusercontent.com/TrelisResearch/tiron/"
            f"{_CURRENT_HARNESS_REVISION}/LICENSE",
            11_386,
            "a2b0a1e07f59d67612f486b5bc40e0b33ac468d20f3a9c59e577ff3570706dd8",
        ),
    )
    if result.artifact("tiron/pipeline.py").sha256 != (
        "0ec09dbb3fd7bf6fe5df1cf4215df77d7b5eab29439d53d3b1cd451ad33666e6"
    ):
        raise ValueError("current Tiron harness pipeline differs from the contract")
    return RepositorySource(
        identifier=result.identifier,
        revision=result.revision,
        source=result.source,
        license_spdx=result.license_spdx,
        artifacts=result.artifacts,
        compatibility_patches=_compatibility_patches(
            source["compatibilityPatches"]
        ),
    )


def _compatibility_patches(value: object) -> tuple[CompatibilityPatch, ...]:
    if not isinstance(value, list) or len(value) != 1:
        raise ValueError("Tiron compatibility patches differ from the contract")
    patch = exact_object(
        value[0],
        {
            "id",
            "script",
            "scriptSha256",
            "target",
            "upstreamSha256",
            "patchedSha256",
            "reason",
        },
        "Tiron local ECAPA compatibility patch",
    )
    expected = {
        "id": "local-ecapa-artifact-path",
        "script": "server/runtime/tiron/compatibility/patch_local_ecapa_source.py",
        "target": "tiron/engine.py",
        "reason": (
            "SpeechBrain otherwise repeats the Hub identifier from hyperparams.yaml "
            "and attempts a network fetch instead of loading the verified local "
            "ECAPA snapshot."
        ),
    }
    if any(patch[key] != expected_value for key, expected_value in expected.items()):
        raise ValueError("Tiron local ECAPA compatibility patch differs")
    script_sha256 = sha256(
        patch["scriptSha256"], "Tiron compatibility patch script SHA-256"
    )
    upstream_sha256 = sha256(
        patch["upstreamSha256"], "Tiron compatibility patch upstream SHA-256"
    )
    patched_sha256 = sha256(
        patch["patchedSha256"], "Tiron compatibility patch result SHA-256"
    )
    if (
        script_sha256
        != "593d056eeac251a5bbbdef18198f4be57309f78103f2498c78a2690e99f2a5fa"
        or upstream_sha256
        != "aea9684b5057972856a85c56aa49f769592fdcae9263678676d730d0fccb9632"
        or patched_sha256
        != "b75b3cad7fe978534e75475f10e7d387ff7c2b9c5b0622aa22373c0b3c010aad"
    ):
        raise ValueError("Tiron local ECAPA compatibility patch identity differs")
    return (
        CompatibilityPatch(
            identifier="local-ecapa-artifact-path",
            script="server/runtime/tiron/compatibility/patch_local_ecapa_source.py",
            script_sha256=script_sha256,
            target="tiron/engine.py",
            upstream_sha256=upstream_sha256,
            patched_sha256=patched_sha256,
        ),
    )


def _speaker_encoder_source(value: object) -> RepositorySource:
    source = exact_object(
        value,
        {"id", "revision", "source", "use", "license", "artifacts"},
        "ECAPA source",
    )
    if source["use"] != "anonymous-cross-window-speaker-embedding":
        raise ValueError("ECAPA use differs from the anonymous speaker contract")
    result = _repository_source(
        source,
        field="ECAPA",
        expected_id="speechbrain/spkrec-ecapa-voxceleb",
        expected_revision=_CURRENT_ECAPA_REVISION,
        expected_source=(
            "https://huggingface.co/speechbrain/spkrec-ecapa-voxceleb"
        ),
        expected_paths=_ECAPA_PATHS,
        license_spdx="Apache-2.0",
        license_declaration=(
            "README.md",
            "00f58c3cbd7a7510de9374080da0e82a4c4e8f4df567f7338fe6efe108be705a",
        ),
    )
    if result.artifact("embedding_model.ckpt").sha256 != (
        "0575cb64845e6b9a10db9bcb74d5ac32b326b8dc90352671d345e2ee3d0126a2"
    ):
        raise ValueError("ECAPA embedding weight differs from the contract")
    return result


def _repository_source(
    source: Mapping[str, object],
    *,
    field: str,
    expected_id: str,
    expected_revision: str,
    expected_source: str,
    expected_paths: frozenset[str],
    license_spdx: str,
    license_declaration: tuple[str, str] | None = None,
    license_file: tuple[str, int, str] | None = None,
) -> RepositorySource:
    if source["id"] != expected_id:
        raise ValueError(f"{field} ID differs from the contract")
    revision = _revision(source["revision"], f"{field} revision")
    if revision != expected_revision:
        raise ValueError(f"current {field} revision differs from the contract")
    source_uri = https_uri(source["source"], f"{field} source")
    if source_uri != expected_source:
        raise ValueError(f"{field} source differs from the contract")
    if license_declaration is not None:
        license_value = exact_object(
            source["license"],
            {"spdx", "declarationArtifact", "declarationSha256"},
            f"{field} license",
        )
        if (
            license_value["spdx"] != license_spdx
            or license_value["declarationArtifact"] != license_declaration[0]
            or sha256(
                license_value["declarationSha256"],
                f"{field} license declaration SHA-256",
            )
            != license_declaration[1]
        ):
            raise ValueError(f"{field} license declaration differs from the contract")
    elif license_file is not None:
        license_value = exact_object(
            source["license"],
            {"spdx", "source", "size", "sha256"},
            f"{field} license",
        )
        if (
            license_value["spdx"] != license_spdx
            or https_uri(license_value["source"], f"{field} license source")
            != license_file[0]
            or positive_int(license_value["size"], f"{field} license size")
            != license_file[1]
            or sha256(license_value["sha256"], f"{field} license SHA-256")
            != license_file[2]
        ):
            raise ValueError(f"{field} license differs from the contract")
    else:
        raise AssertionError("repository source requires a license contract")
    artifacts = artifact_identities(source["artifacts"], f"{field} artifacts")
    require_artifact_paths(artifacts, expected_paths, field)
    return RepositorySource(
        identifier=expected_id,
        revision=revision,
        source=source_uri,
        license_spdx=license_spdx,
        artifacts=artifacts,
    )


def _base_runtime(value: object) -> BaseRuntime:
    runtime = exact_object(
        value,
        {
            "image",
            "sourceTag",
            "source",
            "platform",
            "digest",
            "pythonVersion",
            "torchVersion",
            "cudaVersion",
            "torchCudaVersion",
            "basePackages",
            "requirementsLock",
            "requirementsLockSha256",
            "sourceBuilds",
        },
        "meeting base runtime",
    )
    expected_scalars = {
        "image": "nvcr.io/nvidia/pytorch",
        "sourceTag": "26.06-py3",
        "platform": "linux/arm64",
        "digest": _BASE_DIGEST,
        "pythonVersion": "3.12.3",
        "torchVersion": "2.13.0a0+8145d630e8.nv26.06",
        "cudaVersion": "13.3.0",
        "torchCudaVersion": "13.3",
    }
    if any(runtime[key] != expected for key, expected in expected_scalars.items()):
        raise ValueError("meeting base runtime differs from the checked NVIDIA contract")
    source = https_uri(runtime["source"], "meeting base runtime source")
    if source != "https://catalog.ngc.nvidia.com/orgs/nvidia/containers/pytorch/tags":
        raise ValueError("meeting base runtime source differs from the contract")
    packages = exact_object(
        runtime["basePackages"], set(_BASE_PACKAGES), "meeting base packages"
    )
    if dict(packages) != _BASE_PACKAGES:
        raise ValueError("meeting base packages differ from the observed image")
    requirements_lock = portable_artifact_path(
        runtime["requirementsLock"], "meeting requirements lock path"
    )
    if requirements_lock != "server/runtime/tiron/requirements.lock":
        raise ValueError("meeting requirements lock path differs from the contract")
    _source_builds(runtime["sourceBuilds"])
    return BaseRuntime(
        image="nvcr.io/nvidia/pytorch",
        source_tag="26.06-py3",
        source=source,
        platform="linux/arm64",
        digest=_BASE_DIGEST,
        python_version="3.12.3",
        torch_version="2.13.0a0+8145d630e8.nv26.06",
        cuda_version="13.3.0",
        torch_cuda_version="13.3",
        base_packages=dict(packages),
        requirements_lock=requirements_lock,
        requirements_lock_sha256=sha256(
            runtime["requirementsLockSha256"],
            "meeting requirements lock SHA-256",
        ),
    )


def _source_builds(value: object) -> None:
    if not isinstance(value, list) or len(value) != 1:
        raise ValueError("meeting source builds differ from the contract")
    build = exact_object(
        value[0],
        {
            "id",
            "version",
            "repository",
            "revision",
            "source",
            "buildFlags",
            "outputIdentity",
            "license",
        },
        "TorchAudio source build",
    )
    expected = {
        "id": "torchaudio",
        "version": "2.11.0+34c52a6",
        "repository": "pytorch/audio",
        "revision": "34c52a67e8941bbd8e6adaca0eb0b9eabec11d78",
        "source": "https://github.com/pytorch/audio",
        "outputIdentity": "bound-by-checked-container-image",
    }
    if any(build[key] != expected_value for key, expected_value in expected.items()):
        raise ValueError("TorchAudio source build differs from the contract")
    if build["buildFlags"] != ["BUILD_RNNT=0", "BUILD_SOX=0", "USE_CUDA=0"]:
        raise ValueError("TorchAudio build flags differ from the contract")
    license_value = exact_object(
        build["license"], {"spdx", "source", "size", "sha256"}, "TorchAudio license"
    )
    if (
        license_value["spdx"] != "BSD-2-Clause"
        or positive_int(license_value["size"], "TorchAudio license size") != 1_338
        or sha256(license_value["sha256"], "TorchAudio license SHA-256")
        != "93a58861a858cc108e6b6b833e08e76e8b2a66339e4a8007c8a5a8c1ff9c40d6"
    ):
        raise ValueError("TorchAudio license differs from the contract")
    https_uri(license_value["source"], "TorchAudio license source")


def _execution_policy(value: object) -> ExecutionPolicy:
    policy = exact_object(
        value,
        {
            "networkDownloadsAllowed",
            "modelDirectoryEnvironment",
            "speakerEncoderDirectoryEnvironment",
            "offlineEnvironment",
            "productionDefault",
            "requiresAcceptanceSeal",
        },
        "meeting execution policy",
    )
    if policy["networkDownloadsAllowed"] is not False:
        raise ValueError("meeting runtime network downloads must remain forbidden")
    if policy["productionDefault"] is not False:
        raise ValueError("unqualified meeting runtime cannot be the production default")
    if policy["requiresAcceptanceSeal"] is not True:
        raise ValueError("meeting runtime must require the acceptance seal")
    offline = policy["offlineEnvironment"]
    expected_offline = (
        "DO_NOT_TRACK",
        "HF_HUB_DISABLE_TELEMETRY",
        "HF_HUB_OFFLINE",
        "TRANSFORMERS_OFFLINE",
    )
    if not isinstance(offline, list) or tuple(offline) != expected_offline:
        raise ValueError("meeting runtime offline environment differs from the contract")
    if (
        policy["modelDirectoryEnvironment"] != "YAP_TIRON_MODEL_DIR"
        or policy["speakerEncoderDirectoryEnvironment"] != "YAP_TIRON_ECAPA_DIR"
    ):
        raise ValueError("meeting runtime model directory contract differs")
    return ExecutionPolicy(
        network_downloads_allowed=False,
        model_directory_environment="YAP_TIRON_MODEL_DIR",
        speaker_encoder_directory_environment="YAP_TIRON_ECAPA_DIR",
        offline_environment=expected_offline,
        production_default=False,
        requires_acceptance_seal=True,
    )


def _superseded_sources(value: object) -> None:
    superseded = exact_object(
        value,
        {"modelRevision", "modelWeightSha256", "harnessRevision", "reason"},
        "superseded meeting sources",
    )
    if (
        superseded["modelRevision"]
        != "aed145c7d6cc5cbd381a0e87b6d0089bcc76a1fc"
        or superseded["harnessRevision"]
        != "5b3766ac64ff3a8d98443e0a850d1ce569952520"
        or sha256(
            superseded["modelWeightSha256"], "superseded model weight SHA-256"
        )
        != "921e078a8e89000ccb467c5f9bce8a46c9e484c52b63e3ddddaa571c34306a2e"
        or not isinstance(superseded["reason"], str)
        or not 20 <= len(superseded["reason"]) <= 512
    ):
        raise ValueError("superseded meeting source record differs from the contract")


def _revision(value: object, field: str) -> str:
    if not isinstance(value, str) or _HEX_REVISION.fullmatch(value) is None:
        raise ValueError(f"{field} is invalid")
    return value
