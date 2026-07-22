from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
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
)
from yap_server.pools.batch_asr import (
    ContainerBatchAsrWorker,
    inspect_worker_image,
    reconcile_owned_containers,
)
from yap_server.pools.batch_contract import BatchWorker
from yap_server.pools.cohere_vllm_worker import CohereVllmBatchWorker
from yap_server.pools.model_lock import (
    ModelPoolLock,
    verify_model_artifacts,
)
from yap_server.pools.nemotron_nemo_client import NemotronNemoClient
from yap_server.pools.nemotron_nemo_worker import NemotronNemoBatchWorker
from yap_server.pools.vllm_transcription_client import VllmTranscriptionClient

from .contract_values import MAX_JOB_PCM_BYTES


_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_COHERE_POOL = "cohere-batch"
_NEMOTRON_POOL = "nemotron-batch"
_VLLM_RUNTIME = "vllm"
_TRANSFORMERS_REFERENCE_RUNTIME = "transformers-reference"
_NEMO_REFERENCE_RUNTIME = "nemo-reference"
_NEMO_RESIDENT_RUNTIME = "nemo-resident"
_RETIRED_GLOBAL_RUNTIME_ENV = "YAP_ASR_ENGINE"


@dataclass(frozen=True, slots=True)
class AsrWorkerPlan:
    worker: BatchWorker
    max_workers: int
    max_queued: int
    max_inflight_pcm_bytes: int


def build_asr_worker_plan(
    source: Mapping[str, str],
    *,
    model_dir: Path,
    lock: ModelPoolLock,
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
        run_as_uid=run_as_uid,
        run_as_gid=run_as_gid,
        storage_namespace=storage_namespace,
        timeout_seconds=timeout_seconds,
        worker_image_env=worker_image_env,
    )


def _build_cohere_vllm_plan(
    source: Mapping[str, str],
    *,
    model_dir: Path,
    lock: ModelPoolLock,
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
        max_inflight_pcm_bytes=MAX_JOB_PCM_BYTES,
    )


def _build_nemotron_nemo_plan(
    source: Mapping[str, str],
    *,
    model_dir: Path,
    lock: ModelPoolLock,
    timeout_seconds: float,
) -> AsrWorkerPlan:
    endpoint = source.get(NEMOTRON_NEMO_ENDPOINT_ENV, "").strip()
    if not endpoint:
        raise ValueError(
            f"{NEMOTRON_NEMO_ENDPOINT_ENV} is required for resident NeMo"
        )
    api_key = source.get(NEMOTRON_NEMO_API_KEY_ENV, "")
    if not api_key:
        raise ValueError(
            f"{NEMOTRON_NEMO_API_KEY_ENV} is required for resident NeMo"
        )
    verify_model_artifacts(lock, model_dir)
    client = NemotronNemoClient(
        endpoint=endpoint,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
    )
    worker = NemotronNemoBatchWorker(lock=lock, client=client)
    try:
        worker.verify_ready()
    except BaseException:
        worker.close()
        raise
    return AsrWorkerPlan(
        worker=worker,
        max_workers=8,
        max_queued=8,
        max_inflight_pcm_bytes=MAX_JOB_PCM_BYTES,
    )


def _build_isolated_reference_plan(
    source: Mapping[str, str],
    *,
    model_dir: Path,
    lock: ModelPoolLock,
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
        max_inflight_pcm_bytes=MAX_JOB_PCM_BYTES,
    )


def resolve_checked_worker_image(
    environ: Mapping[str, str],
    *,
    docker_binary: str,
    image_env: str = ASR_WORKER_IMAGE_ENV,
) -> str:
    image = environ.get(image_env, "").strip()
    checked_head = environ.get(CHECKED_HEAD_ENV, "").strip()
    if not image or _GIT_SHA.fullmatch(checked_head) is None:
        raise ValueError(
            f"{image_env} and a full {CHECKED_HEAD_ENV} are required"
        )
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
        raise ValueError("checked-head worker image inspection omitted its immutable ID")
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
