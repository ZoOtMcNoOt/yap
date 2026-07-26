from __future__ import annotations

from dataclasses import dataclass
import math
import os
from pathlib import Path
import re
import stat
import subprocess
from typing import Mapping

from yap_server.config.runtime_environment import CHECKED_HEAD_ENV, DOCKER_BINARY_ENV
from yap_server.language_tags import canonical_bcp47
from yap_server.pools.checked_runtime_image import (
    CheckedRuntimeImageError,
    assert_clean_checked_head,
    runtime_image_contract,
    verify_prepared_checked_image,
)

from .component_lock import (
    LidComponentLock,
    load_lid_component_lock,
    verify_lid_model_artifacts,
    verify_lid_requirements,
)
from .container_runtime import (
    ContainerLidWorker,
    reconcile_lid_containers,
    verify_lid_container_absent,
)
from .materialization import reconcile_stale_lid_requests
from .preflight import LidPreflightEngine
from .service import LidPreflightService
from .transport import (
    LID_PREFLIGHT_MEDIA_TYPE,
    MAX_LID_PREFLIGHT_BODY_BYTES,
    MAX_LID_PREFLIGHT_MANIFEST_BYTES,
)


LANGUAGE_DETECTION_ENABLED_ENV = "YAP_LANGUAGE_DETECTION_ENABLED"
LANGUAGE_DETECTION_COMPONENT_LOCK_ENV = "YAP_LANGUAGE_DETECTION_COMPONENT_LOCK"
LANGUAGE_DETECTION_MODEL_DIR_ENV = "YAP_LANGUAGE_DETECTION_MODEL_DIR"
LANGUAGE_DETECTION_TIMEOUT_SECONDS_ENV = "YAP_LANGUAGE_DETECTION_TIMEOUT_SECONDS"
LANGUAGE_DETECTION_DOCKER_BINARY_ENV = "YAP_LANGUAGE_DETECTION_DOCKER_BINARY"
LANGUAGE_DETECTION_WORKER_IMAGE_ENV = "YAP_LANGUAGE_DETECTION_WORKER_IMAGE"
LANGUAGE_DETECTION_PREPARATION_RECEIPT_ENV = (
    "YAP_LANGUAGE_DETECTION_PREPARATION_RECEIPT"
)
LANGUAGE_DETECTION_PREPARATION_RECEIPT_SHA256_ENV = (
    "YAP_LANGUAGE_DETECTION_PREPARATION_RECEIPT_SHA256"
)
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(slots=True)
class LanguageDetectionRuntime:
    service: LidPreflightService
    work_root: Path
    capabilities: dict[str, object]

    def close(self) -> None:
        self.service.close()


def build_language_detection_runtime(
    environ: Mapping[str, str],
    *,
    repository_root: Path,
    storage_dir: Path,
    asr_capabilities: Mapping[str, object],
    run_as_uid: int,
    run_as_gid: int,
    storage_namespace: str,
) -> LanguageDetectionRuntime | None:
    enabled = environ.get(LANGUAGE_DETECTION_ENABLED_ENV, "0")
    if enabled == "0":
        return None
    if enabled != "1":
        raise ValueError(f"{LANGUAGE_DETECTION_ENABLED_ENV} must be 0 or 1")

    repo = _real_directory(repository_root, "Yap repository root")
    lock_path = Path(
        environ.get(
            LANGUAGE_DETECTION_COMPONENT_LOCK_ENV,
            str(repo / "server" / "lid-component.lock.json"),
        )
    ).resolve(strict=True)
    lock = load_lid_component_lock(lock_path)
    verify_lid_requirements(lock, repo)
    model_dir = _required_directory(
        environ,
        LANGUAGE_DETECTION_MODEL_DIR_ENV,
    )
    verify_lid_model_artifacts(lock, model_dir)

    catalog_revision = asr_capabilities.get("catalogRevision")
    if not isinstance(catalog_revision, str) or _SHA256.fullmatch(
        catalog_revision
    ) is None:
        raise ValueError("verified ASR catalog revision is invalid for LID")
    enabled_locales = fixed_locales_from_asr_catalog(asr_capabilities)
    timeout_seconds = _bounded_timeout_seconds(
        environ.get(LANGUAGE_DETECTION_TIMEOUT_SECONDS_ENV, "120"),
        LANGUAGE_DETECTION_TIMEOUT_SECONDS_ENV,
    )
    docker_binary = environ.get(
        LANGUAGE_DETECTION_DOCKER_BINARY_ENV,
        environ.get(DOCKER_BINARY_ENV, "docker"),
    ).strip()
    if not docker_binary:
        raise ValueError(f"{LANGUAGE_DETECTION_DOCKER_BINARY_ENV} must not be empty")
    image = resolve_language_detection_worker_image(
        environ,
        lock=lock,
        docker_binary=docker_binary,
        repository_root=repo,
    )
    checked_head = environ[CHECKED_HEAD_ENV].strip()
    reconcile_lid_containers(
        docker_binary,
        storage_namespace=storage_namespace,
    )
    work_root = _private_work_root(storage_dir)
    reconcile_stale_lid_requests(
        work_root,
        retire_container_identities=True,
        verify_container_absent=lambda container_id: verify_lid_container_absent(
            docker_binary,
            container_id,
        ),
    )

    worker = ContainerLidWorker(
        image=image,
        model_dir=model_dir,
        lock=lock,
        run_as_uid=run_as_uid,
        run_as_gid=run_as_gid,
        checked_head=checked_head,
        storage_namespace=storage_namespace,
        docker_binary=docker_binary,
        timeout_seconds=timeout_seconds,
    )
    try:
        engine = LidPreflightEngine(
            lock=lock,
            worker=worker,
            enabled_fixed_locales=enabled_locales,
            maximum_running=1,
            maximum_queued=2,
        )
        service = LidPreflightService(
            lock=lock,
            engine=engine,
            work_root=work_root,
            catalog_revision=catalog_revision,
        )
    except BaseException:
        worker.close()
        raise
    return LanguageDetectionRuntime(
        service=service,
        work_root=work_root,
        capabilities=_public_capabilities(lock, timeout_seconds=timeout_seconds),
    )


def resolve_language_detection_worker_image(
    environ: Mapping[str, str],
    *,
    lock: LidComponentLock,
    docker_binary: str,
    repository_root: Path,
) -> str:
    image = environ.get(LANGUAGE_DETECTION_WORKER_IMAGE_ENV, "").strip()
    checked_head = environ.get(CHECKED_HEAD_ENV, "").strip()
    if not image or _GIT_SHA.fullmatch(checked_head) is None:
        raise ValueError(
            f"{LANGUAGE_DETECTION_WORKER_IMAGE_ENV} and a full "
            f"{CHECKED_HEAD_ENV} are required"
        )
    receipt = environ.get(
        LANGUAGE_DETECTION_PREPARATION_RECEIPT_ENV,
        "",
    ).strip()
    receipt_sha256 = environ.get(
        LANGUAGE_DETECTION_PREPARATION_RECEIPT_SHA256_ENV,
        "",
    ).strip()
    if not receipt or _SHA256.fullmatch(receipt_sha256) is None:
        raise ValueError(
            "language-detection preparation receipt and SHA-256 are required"
        )

    def run_command(
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        actual = list(command)
        if actual and actual[0] == "docker":
            actual[0] = docker_binary
        return subprocess.run(actual, **kwargs)  # type: ignore[arg-type]

    try:
        contract = runtime_image_contract(
            repository_root,
            "language-detection",
            checked_head,
        )
        if contract.base_digest != lock.runtime.platform_digest:
            raise CheckedRuntimeImageError(
                "LID image base platform digest differs from its lock"
            )
        assert_clean_checked_head(
            repository_root,
            checked_head,
            runner=run_command,
        )
        inspected = verify_prepared_checked_image(
            contract,
            receipt_path=Path(receipt),
            receipt_sha256=receipt_sha256,
            runner=run_command,
        )
    except (CheckedRuntimeImageError, OSError) as error:
        raise ValueError(str(error)) from None
    image_id = inspected["imageId"]
    if image != image_id:
        raise ValueError(
            "LID worker image must be the receipt-bound immutable image ID"
        )
    return image_id


def fixed_locales_from_asr_catalog(
    catalog: Mapping[str, object],
) -> tuple[str, ...]:
    revision = catalog.get("catalogRevision")
    if not isinstance(revision, str) or _SHA256.fullmatch(revision) is None:
        raise ValueError("verified ASR catalog revision is invalid")
    providers = catalog.get("providers")
    if not isinstance(providers, list) or not 1 <= len(providers) <= 8:
        raise ValueError("verified ASR catalog providers are invalid")
    locales: set[str] = set()
    for provider in providers:
        if not isinstance(provider, dict):
            raise ValueError("verified ASR catalog provider is invalid")
        capabilities = provider.get("capabilities")
        if not isinstance(capabilities, list) or not 1 <= len(capabilities) <= 256:
            raise ValueError("verified ASR provider capabilities are invalid")
        for capability in capabilities:
            if not isinstance(capability, dict):
                raise ValueError("verified ASR capability is invalid")
            if capability.get("mode") != "fixedBatch":
                continue
            locales.add(
                canonical_bcp47(
                    capability.get("languageBcp47"),
                    "ASR capability languageBcp47",
                )
            )
    if not locales:
        raise ValueError("verified ASR catalog has no fixed batch locale for LID")
    return tuple(sorted(locales))


def publish_language_detection_capabilities(
    catalog: Mapping[str, object],
    runtime: LanguageDetectionRuntime,
) -> dict[str, object]:
    if "languagePreflight" in catalog:
        raise ValueError("verified ASR catalog already contains LID capabilities")
    if not isinstance(runtime, LanguageDetectionRuntime):
        raise TypeError("runtime must be a verified LanguageDetectionRuntime")
    return {**catalog, "languagePreflight": runtime.capabilities}


def _public_capabilities(
    lock: LidComponentLock,
    *,
    timeout_seconds: float,
) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "componentId": lock.component_id,
        "runtime": {
            "pythonVersion": lock.runtime.python_version,
            "cpuOnly": lock.runtime.cpu_only,
        },
        "model": {
            "id": lock.model.model_id,
            "revision": lock.model.revision,
        },
        "transport": {
            "mediaType": LID_PREFLIGHT_MEDIA_TYPE,
            "maximumBodyBytes": MAX_LID_PREFLIGHT_BODY_BYTES,
            "maximumManifestBytes": MAX_LID_PREFLIGHT_MANIFEST_BYTES,
            "maximumResponseSeconds": math.ceil(timeout_seconds),
        },
        "policy": {
            "revision": lock.policy.revision,
            "sampleRateHz": lock.policy.sample_rate_hz,
            "channelCount": lock.policy.channel_count,
            "sampleWidthBytes": lock.policy.sample_width_bytes,
            "minimumSourceSamples": lock.policy.minimum_source_samples,
            "maximumWindows": lock.policy.maximum_windows,
            "maximumWindowSamples": lock.policy.maximum_window_samples,
            "minimumVoicedSamplesPerWindow": (
                lock.policy.minimum_voiced_samples_per_window
            ),
            "scoreSemantics": lock.policy.score_semantics,
            "userConfirmationRequired": lock.policy.user_confirmation_required,
        },
    }


def _private_work_root(storage_dir: Path) -> Path:
    storage = _real_directory(storage_dir, "private server storage")
    work_root = storage / "lid-preflight"
    work_root.mkdir(mode=0o700, exist_ok=True)
    root = _real_directory(work_root, "LID preflight work root")
    try:
        root.relative_to(storage)
    except ValueError as error:
        raise ValueError("LID preflight work root escapes private storage") from error
    if os.name == "posix" and stat.S_IMODE(root.stat().st_mode) & 0o077:
        raise ValueError("LID preflight work root must remain private")
    return root


def _required_directory(environ: Mapping[str, str], name: str) -> Path:
    value = environ.get(name, "").strip()
    if not value:
        raise ValueError(f"{name} is required when language detection is enabled")
    return _real_directory(Path(value), name)


def _real_directory(path: Path, label: str) -> Path:
    requested = Path(path)
    try:
        metadata = requested.lstat()
    except FileNotFoundError as error:
        raise ValueError(f"{label} is missing") from error
    if (
        stat.S_ISLNK(metadata.st_mode)
        or bool(getattr(metadata, "st_file_attributes", 0) & 0x400)
        or not stat.S_ISDIR(metadata.st_mode)
    ):
        raise ValueError(f"{label} must be a real directory")
    resolved = requested.resolve(strict=True)
    opened = os.stat(resolved)
    if (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino):
        raise ValueError(f"{label} changed during validation")
    return resolved


def _bounded_timeout_seconds(value: str, name: str) -> float:
    try:
        parsed = float(value)
    except ValueError as error:
        raise ValueError(f"{name} must be numeric") from error
    if not math.isfinite(parsed) or not 0 < parsed <= 300:
        raise ValueError(f"{name} must be between 0 and 300 seconds")
    return parsed
