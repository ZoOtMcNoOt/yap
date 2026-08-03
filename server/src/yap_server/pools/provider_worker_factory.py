from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
from typing import Mapping

from yap_server.config.runtime_environment import (
    ASR_WORKER_IMAGE_ENV,
    CHECKED_HEAD_ENV,
    COHERE_ASR_RUNTIME_ENV,
    COHERE_VLLM_API_KEY_ENV,
    COHERE_VLLM_ENDPOINT_ENV,
    DOCKER_BINARY_ENV,
    NEMOTRON_ASR_RUNTIME_ENV,
    NEMOTRON_NEMO_API_KEY_ENV,
    NEMOTRON_NEMO_ENDPOINT_ENV,
    NEMOTRON_WORKER_IMAGE_ENV,
    TIRON_PREPARATION_RECEIPT_ENV,
    TIRON_PREPARATION_RECEIPT_SHA256_ENV,
    TIRON_WORKER_IMAGE_ENV,
)
from yap_server.meeting_transcription.batch_worker import (
    MeetingTranscriptionBatchWorker,
)
from yap_server.meeting_transcription.container_worker import (
    ContainerMeetingTranscriptionWorker,
)
from yap_server.meeting_transcription.result_revisions import MeetingResultAuthority
from yap_server.pools.batch_asr import (
    ContainerBatchAsrWorker,
    inspect_worker_image,
    reconcile_owned_containers,
)
from yap_server.pools.batch_contract import BatchWorker
from yap_server.pools.checked_runtime_image import (
    CheckedRuntimeImageError,
    assert_clean_checked_head,
    runtime_image_contract,
    verify_prepared_checked_image,
)
from yap_server.pools.cohere_vllm_worker import CohereVllmBatchWorker
from yap_server.pools.model_lock import (
    ModelPoolLock,
    verify_model_artifacts,
)
from yap_server.pools.nemotron_nemo_client import NemotronNemoClient
from yap_server.pools.nemotron_nemo_worker import NemotronNemoBatchWorker
from yap_server.pools.vllm_transcription_client import VllmTranscriptionClient


_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
_COHERE_POOL = "cohere-batch"
_NEMOTRON_POOL = "nemotron-batch"
_VLLM_RUNTIME = "vllm"
_TRANSFORMERS_REFERENCE_RUNTIME = "transformers-reference"
_NEMO_REFERENCE_RUNTIME = "nemo-reference"
_NEMO_RESIDENT_RUNTIME = "nemo-resident"
_RETIRED_GLOBAL_RUNTIME_ENV = "YAP_ASR_ENGINE"
_IMAGE_RUNTIME_LABEL = "com.mcnatg1.yap.runtime"


@dataclass(frozen=True, slots=True)
class AsrWorkerPlan:
    worker: BatchWorker
    max_workers: int
    max_queued: int
    max_inflight_pcm_bytes: int
    startup_cleanup_verified: bool

    def __post_init__(self) -> None:
        if not isinstance(self.startup_cleanup_verified, bool):
            raise ValueError("provider startup cleanup proof must be boolean")


def build_asr_worker_plan(
    source: Mapping[str, str],
    *,
    model_dir: Path,
    lock: ModelPoolLock,
    max_inflight_pcm_bytes: int,
    run_as_uid: int,
    run_as_gid: int,
    storage_namespace: str,
    timeout_seconds: float,
) -> AsrWorkerPlan:
    if source.get(_RETIRED_GLOBAL_RUNTIME_ENV, "").strip():
        raise ValueError(
            f"{_RETIRED_GLOBAL_RUNTIME_ENV} is retired; configure each provider runtime"
        )
    if lock.pool_id == _COHERE_POOL:
        runtime = source.get(COHERE_ASR_RUNTIME_ENV, _VLLM_RUNTIME).strip()
        if runtime == _VLLM_RUNTIME:
            _require_lock_engine(lock, "vllm", COHERE_ASR_RUNTIME_ENV)
            return _build_cohere_vllm_plan(
                source,
                model_dir=model_dir,
                lock=lock,
                max_inflight_pcm_bytes=max_inflight_pcm_bytes,
                timeout_seconds=timeout_seconds,
            )
        if runtime != _TRANSFORMERS_REFERENCE_RUNTIME:
            raise ValueError(
                f"{COHERE_ASR_RUNTIME_ENV} must be vllm or transformers-reference"
            )
        _require_lock_engine(lock, "transformers", COHERE_ASR_RUNTIME_ENV)
        worker_image_env = ASR_WORKER_IMAGE_ENV
    elif lock.pool_id == _NEMOTRON_POOL:
        runtime = source.get(
            NEMOTRON_ASR_RUNTIME_ENV,
            _TRANSFORMERS_REFERENCE_RUNTIME,
        ).strip()
        if runtime == _NEMO_RESIDENT_RUNTIME:
            _require_lock_engine(lock, "nemo", NEMOTRON_ASR_RUNTIME_ENV)
            return _build_nemotron_nemo_plan(
                source,
                model_dir=model_dir,
                lock=lock,
                max_inflight_pcm_bytes=max_inflight_pcm_bytes,
                timeout_seconds=timeout_seconds,
            )
        if runtime == _TRANSFORMERS_REFERENCE_RUNTIME:
            _require_lock_engine(lock, "transformers", NEMOTRON_ASR_RUNTIME_ENV)
            worker_image_env = ASR_WORKER_IMAGE_ENV
        elif runtime == _NEMO_REFERENCE_RUNTIME:
            _require_lock_engine(lock, "nemo", NEMOTRON_ASR_RUNTIME_ENV)
            worker_image_env = NEMOTRON_WORKER_IMAGE_ENV
        else:
            raise ValueError(
                f"{NEMOTRON_ASR_RUNTIME_ENV} must be transformers-reference "
                "nemo-reference, or nemo-resident"
            )
    else:
        raise ValueError("model pool has no configured ASR runtime")

    return _build_isolated_reference_plan(
        source,
        model_dir=model_dir,
        lock=lock,
        max_inflight_pcm_bytes=max_inflight_pcm_bytes,
        run_as_uid=run_as_uid,
        run_as_gid=run_as_gid,
        storage_namespace=storage_namespace,
        timeout_seconds=timeout_seconds,
        worker_image_env=worker_image_env,
    )


def build_meeting_transcription_worker_plan(
    source: Mapping[str, str],
    *,
    model_dir: Path,
    speaker_encoder_dir: Path,
    runtime_lock_path: Path,
    authority: MeetingResultAuthority,
    repository_root: Path,
    max_inflight_pcm_bytes: int,
    run_as_uid: int,
    run_as_gid: int,
    storage_namespace: str,
    timeout_seconds: float,
) -> AsrWorkerPlan:
    """Build the bounded whole-meeting worker from its checked image."""

    docker_binary = source.get(DOCKER_BINARY_ENV, "docker")
    worker_image = resolve_prepared_meeting_transcription_image(
        source,
        docker_binary=docker_binary,
        repository_root=repository_root,
        expected_base_digest=authority.provenance.base_runtime.digest,
    )
    checked_head = source[CHECKED_HEAD_ENV].strip()
    reconcile_owned_containers(
        docker_binary,
        storage_namespace=storage_namespace,
    )
    container_worker = ContainerMeetingTranscriptionWorker(
        image=worker_image,
        model_dir=model_dir,
        speaker_encoder_dir=speaker_encoder_dir,
        runtime_lock_path=runtime_lock_path,
        run_as_uid=run_as_uid,
        run_as_gid=run_as_gid,
        checked_head=checked_head,
        storage_namespace=storage_namespace,
        docker_binary=docker_binary,
        timeout_seconds=timeout_seconds,
    )
    worker = MeetingTranscriptionBatchWorker(
        worker=container_worker,
        authority=authority,
    )
    return AsrWorkerPlan(
        worker=worker,
        max_workers=1,
        max_queued=2,
        max_inflight_pcm_bytes=max_inflight_pcm_bytes,
        startup_cleanup_verified=True,
    )


def resolve_prepared_meeting_transcription_image(
    source: Mapping[str, str],
    *,
    docker_binary: str,
    repository_root: Path,
    expected_base_digest: str,
) -> str:
    """Resolve the exact receipt-bound Tiron image prepared for this Git head."""

    image = source.get(TIRON_WORKER_IMAGE_ENV, "").strip()
    checked_head = source.get(CHECKED_HEAD_ENV, "").strip()
    receipt = source.get(TIRON_PREPARATION_RECEIPT_ENV, "").strip()
    receipt_sha256 = source.get(
        TIRON_PREPARATION_RECEIPT_SHA256_ENV,
        "",
    ).strip()
    if not image or _GIT_SHA.fullmatch(checked_head) is None:
        raise ValueError(
            f"{TIRON_WORKER_IMAGE_ENV} and a full {CHECKED_HEAD_ENV} are required"
        )
    if not receipt or _SHA256_HEX.fullmatch(receipt_sha256) is None:
        raise ValueError("Tiron preparation receipt and SHA-256 are required")

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
            "meeting-transcription",
            checked_head,
        )
        if contract.base_digest != expected_base_digest:
            raise CheckedRuntimeImageError(
                "Tiron image base platform digest differs from its runtime lock"
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
            "Tiron worker image must be the receipt-bound immutable image ID"
        )
    return image_id


def _build_cohere_vllm_plan(
    source: Mapping[str, str],
    *,
    model_dir: Path,
    lock: ModelPoolLock,
    max_inflight_pcm_bytes: int,
    timeout_seconds: float,
) -> AsrWorkerPlan:
    endpoint = source.get(COHERE_VLLM_ENDPOINT_ENV, "").strip()
    if not endpoint:
        raise ValueError(
            f"{COHERE_VLLM_ENDPOINT_ENV} is required for the Cohere vLLM runtime"
        )
    api_key = source.get(COHERE_VLLM_API_KEY_ENV, "")
    if not api_key:
        raise ValueError(
            f"{COHERE_VLLM_API_KEY_ENV} is required for the Cohere vLLM runtime"
        )
    verify_model_artifacts(lock, model_dir)
    client = VllmTranscriptionClient(
        endpoint=endpoint,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
    )
    worker = CohereVllmBatchWorker(lock=lock, client=client)
    try:
        worker.verify_ready()
        worker.verify_startup_idle()
    except BaseException:
        worker.close()
        raise
    return AsrWorkerPlan(
        worker=worker,
        # vLLM owns continuous batching and scheduling. Yap keeps bounded
        # admission and sends independent requests; it never assembles tensors
        # across users.
        max_workers=8,
        max_queued=8,
        max_inflight_pcm_bytes=max_inflight_pcm_bytes,
        startup_cleanup_verified=True,
    )


def _build_nemotron_nemo_plan(
    source: Mapping[str, str],
    *,
    model_dir: Path,
    lock: ModelPoolLock,
    max_inflight_pcm_bytes: int,
    timeout_seconds: float,
) -> AsrWorkerPlan:
    endpoint = source.get(NEMOTRON_NEMO_ENDPOINT_ENV, "").strip()
    if not endpoint:
        raise ValueError(f"{NEMOTRON_NEMO_ENDPOINT_ENV} is required for resident NeMo")
    api_key = source.get(NEMOTRON_NEMO_API_KEY_ENV, "")
    if not api_key:
        raise ValueError(f"{NEMOTRON_NEMO_API_KEY_ENV} is required for resident NeMo")
    verify_model_artifacts(lock, model_dir)
    client = NemotronNemoClient(
        endpoint=endpoint,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
    )
    worker = NemotronNemoBatchWorker(lock=lock, client=client)
    try:
        worker.verify_ready()
        worker.verify_startup_idle()
    except BaseException:
        worker.close()
        raise
    return AsrWorkerPlan(
        worker=worker,
        max_workers=8,
        max_queued=8,
        max_inflight_pcm_bytes=max_inflight_pcm_bytes,
        startup_cleanup_verified=True,
    )


def _build_isolated_reference_plan(
    source: Mapping[str, str],
    *,
    model_dir: Path,
    lock: ModelPoolLock,
    max_inflight_pcm_bytes: int,
    run_as_uid: int,
    run_as_gid: int,
    storage_namespace: str,
    timeout_seconds: float,
    worker_image_env: str,
) -> AsrWorkerPlan:

    docker_binary = source.get(DOCKER_BINARY_ENV, "docker")
    worker_image = resolve_checked_worker_image(
        source,
        docker_binary=docker_binary,
        image_env=worker_image_env,
    )
    checked_head = source[CHECKED_HEAD_ENV].strip()
    reconcile_owned_containers(
        docker_binary,
        storage_namespace=storage_namespace,
    )
    worker = ContainerBatchAsrWorker(
        image=worker_image,
        model_dir=model_dir,
        lock=lock,
        run_as_uid=run_as_uid,
        run_as_gid=run_as_gid,
        checked_head=checked_head,
        storage_namespace=storage_namespace,
        docker_binary=docker_binary,
        timeout_seconds=timeout_seconds,
    )
    return AsrWorkerPlan(
        worker=worker,
        max_workers=1,
        max_queued=2,
        max_inflight_pcm_bytes=max_inflight_pcm_bytes,
        startup_cleanup_verified=True,
    )


def resolve_checked_worker_image(
    environ: Mapping[str, str],
    *,
    docker_binary: str,
    image_env: str = ASR_WORKER_IMAGE_ENV,
    expected_runtime_label: str | None = None,
) -> str:
    image = environ.get(image_env, "").strip()
    checked_head = environ.get(CHECKED_HEAD_ENV, "").strip()
    if not image or _GIT_SHA.fullmatch(checked_head) is None:
        raise ValueError(f"{image_env} and a full {CHECKED_HEAD_ENV} are required")
    try:
        inspected = inspect_worker_image(
            image,
            checked_head,
            docker_binary=docker_binary,
        )
    except RuntimeError as error:
        raise ValueError(str(error)) from None
    image_id = inspected.get("id")
    if not isinstance(image_id, str):
        raise ValueError(
            "checked-head worker image inspection omitted its immutable ID"
        )
    if expected_runtime_label is not None:
        labels = inspected.get("labels")
        if (
            not isinstance(labels, dict)
            or labels.get(_IMAGE_RUNTIME_LABEL) != expected_runtime_label
        ):
            raise ValueError("checked-head worker image has the wrong runtime label")
    return image_id


def _require_lock_engine(
    lock: ModelPoolLock,
    expected: str,
    runtime_env: str,
) -> None:
    if lock.engine != expected:
        raise ValueError(
            f"{runtime_env} selects {expected}, but the model lock selects "
            f"{lock.engine}"
        )
