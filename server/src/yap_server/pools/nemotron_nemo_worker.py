from __future__ import annotations

from pathlib import Path
import stat
import threading
from typing import Protocol

from yap_server.pools.batch_contract import (
    BatchAsrJob,
    WorkerCancellationAcknowledged,
    WorkerExecutionError,
)
from yap_server.pools.batch_result import publish_result, validate_result
from yap_server.pools.model_lock import ModelPoolLock
from yap_server.pools.nemotron_nemo_protocol import NemotronNemoServiceRequest


class ResidentNemotronTranscriber(Protocol):
    def verify_ready(self, lock: ModelPoolLock) -> None: ...

    def verify_startup_idle(self, lock: ModelPoolLock) -> None: ...

    def transcribe(
        self,
        request: NemotronNemoServiceRequest,
        *,
        cancellation: threading.Event,
        shutdown: threading.Event,
    ) -> dict[str, object]: ...

    def close(self) -> None: ...


class NemotronNemoBatchWorker:
    """Provider-neutral batch adapter for one resident native NeMo service."""

    def __init__(
        self,
        *,
        lock: ModelPoolLock,
        client: ResidentNemotronTranscriber,
    ) -> None:
        if lock.pool_id != "nemotron-batch" or lock.engine != "nemo":
            raise ValueError("resident NeMo worker requires the native Nemotron lock")
        if "nemo_toolkit" not in dict(lock.runtime_overlay_packages):
            raise ValueError("resident NeMo lock must pin the NeMo version")
        self._lock = lock
        self._client = client
        self._shutdown = threading.Event()

    def verify_ready(self) -> None:
        self._client.verify_ready(self._lock)

    def verify_startup_idle(self) -> None:
        self._client.verify_startup_idle(self._lock)

    def close(self) -> None:
        self._shutdown.set()
        self._client.close()

    def run(
        self,
        job: BatchAsrJob,
        cancellation: threading.Event,
    ) -> dict[str, object]:
        plan_source, plan_sha256 = _validated_nemotron_route(job, self._lock)
        if self._shutdown.is_set() or cancellation.is_set():
            raise WorkerCancellationAcknowledged(
                "resident Nemotron NeMo request was cancelled"
            )
        input_path = _canonical_regular_file(job.input_path, "input audio")
        plan_path = _canonical_regular_file(
            plan_source,
            "utterance plan",
        )
        request = NemotronNemoServiceRequest(
            job_id=job.job_id,
            input_path=str(input_path),
            input_sha256=job.input_sha256,
            utterance_plan_path=str(plan_path),
            utterance_plan_sha256=plan_sha256,
            language=job.route.provider_language,
            punctuation=job.punctuation,
        )
        result = self._client.transcribe(
            request,
            cancellation=cancellation,
            shutdown=self._shutdown,
        )
        if self._shutdown.is_set() or cancellation.is_set():
            raise WorkerCancellationAcknowledged(
                "resident Nemotron NeMo request was cancelled"
            )
        validate_result(result, job, self._lock)
        publish_result(job.result_path, result)
        return result


def _validated_nemotron_route(
    job: BatchAsrJob,
    lock: ModelPoolLock,
) -> tuple[Path, str]:
    plan_path = job.utterance_plan_path
    plan_sha256 = job.utterance_plan_sha256
    if (
        job.route.pool_id != lock.pool_id
        or job.route.model_revision != lock.model_revision
        or job.route.provider_language not in lock.supported_languages
        or plan_path is None
        or plan_sha256 is None
    ):
        raise WorkerExecutionError("resident NeMo route does not match the model lock")
    if job.route.execution_mode == "fixedBatch":
        if job.route.provider_language == "auto":
            raise WorkerExecutionError("fixed resident NeMo work cannot use auto mode")
    elif (
        job.route.execution_mode != "dynamicBatch"
        or job.route.provider_language != "auto"
    ):
        raise WorkerExecutionError("resident NeMo execution mode is invalid")
    if not job.punctuation:
        raise WorkerExecutionError("resident Nemotron NeMo always emits punctuation")
    return plan_path, plan_sha256


def _canonical_regular_file(path: Path | None, label: str) -> Path:
    if not isinstance(path, Path):
        raise WorkerExecutionError(f"resident NeMo {label} is missing")
    try:
        metadata = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise WorkerExecutionError(f"resident NeMo {label} is missing") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise WorkerExecutionError(
            f"resident NeMo {label} must be a regular file"
        )
    return resolved
