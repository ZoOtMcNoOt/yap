from __future__ import annotations

import threading
from typing import Protocol

from yap_server.alignment_contract import (
    AlignmentUnavailableReason,
    unavailable_alignment,
)
from yap_server.pools.batch_asr_worker import read_pcm16_wav_snapshot
from yap_server.pools.batch_contract import (
    BatchAsrJob,
    WorkerCancellationAcknowledged,
    WorkerExecutionError,
)
from yap_server.pools.batch_result import publish_result, validate_result
from yap_server.pools.model_lock import ModelPoolLock
from yap_server.transcript_text import canonical_transcript


class VllmTranscriber(Protocol):
    def verify_ready(self, lock: ModelPoolLock) -> None: ...

    def verify_startup_idle(self) -> None: ...

    def transcribe(
        self,
        *,
        job_id: str,
        encoded_wav: bytes,
        model: str,
        language: str,
        cancellation: threading.Event,
        shutdown: threading.Event,
    ) -> str: ...

    def close(self) -> None: ...


class CohereVllmBatchWorker:
    """Cohere adapter from Yap's bounded batch seam to resident vLLM."""

    def __init__(self, *, lock: ModelPoolLock, client: VllmTranscriber) -> None:
        if lock.pool_id != "cohere-batch":
            raise ValueError("the vLLM batch worker is only valid for Cohere")
        versions = dict(lock.runtime_overlay_packages)
        if "vllm" not in versions:
            raise ValueError("the Cohere vLLM lock must pin the vLLM version")
        self._lock = lock
        self._client = client
        self._shutdown = threading.Event()

    def verify_ready(self) -> None:
        self._client.verify_ready(self._lock)

    def verify_startup_idle(self) -> None:
        self._client.verify_startup_idle()

    def close(self) -> None:
        self._shutdown.set()
        self._client.close()

    def run(
        self,
        job: BatchAsrJob,
        cancellation: threading.Event,
    ) -> dict[str, object]:
        _verify_cohere_route(job, self._lock)
        if self._shutdown.is_set() or cancellation.is_set():
            raise WorkerCancellationAcknowledged(
                "Cohere vLLM request was cancelled"
            )
        try:
            snapshot = read_pcm16_wav_snapshot(job.input_path)
        except (OSError, ValueError) as error:
            raise WorkerExecutionError("Cohere vLLM input is invalid") from error
        if snapshot.audio.sha256 != job.input_sha256:
            raise WorkerExecutionError(
                "Cohere vLLM input identity changed before dispatch"
            )
        transcript = self._client.transcribe(
            job_id=job.job_id,
            encoded_wav=snapshot.encoded_bytes,
            model=self._lock.model_id,
            language=job.route.provider_language,
            cancellation=cancellation,
            shutdown=self._shutdown,
        )
        if self._shutdown.is_set() or cancellation.is_set():
            raise WorkerCancellationAcknowledged(
                "Cohere vLLM request was cancelled"
            )
        try:
            checked_transcript = canonical_transcript(
                " ".join(transcript.split()),
                "Cohere vLLM transcript",
            )
        except (AttributeError, ValueError) as error:
            raise WorkerExecutionError("Cohere vLLM transcript is invalid") from error
        versions = dict(self._lock.runtime_overlay_packages)
        result: dict[str, object] = {
            "schemaVersion": 1,
            "jobId": job.job_id,
            "model": {
                "poolId": self._lock.pool_id,
                "id": self._lock.model_id,
                "revision": self._lock.model_revision,
            },
            "audio": {
                "sha256": snapshot.audio.sha256,
                "durationMs": snapshot.audio.duration_ms,
                "sampleRateHz": snapshot.audio.sample_rate,
            },
            "transcript": {
                "text": checked_transcript,
                "language": job.route.provider_language,
                "punctuation": True,
            },
            "alignment": unavailable_alignment(
                AlignmentUnavailableReason.PROVIDER_UNSUPPORTED
            ),
            "runtime": {
                "device": "cuda",
                "pythonVersion": self._lock.runtime_python_version,
                "torchVersion": self._lock.runtime_torch_version,
                "torchCudaVersion": self._lock.runtime_torch_cuda_version,
                "overlayPackages": versions,
                "dtype": "bfloat16",
                "servingEngine": "vllm",
                "servingEngineVersion": versions["vllm"],
                "requestInterface": "openai-audio-transcriptions",
            },
        }
        validate_result(result, job, self._lock)
        publish_result(job.result_path, result)
        return result


def _verify_cohere_route(job: BatchAsrJob, lock: ModelPoolLock) -> None:
    if (
        job.route.pool_id != lock.pool_id
        or job.route.model_revision != lock.model_revision
        or job.route.provider_language not in lock.supported_languages
    ):
        raise WorkerExecutionError("Cohere vLLM route does not match the model lock")
    if (
        job.route.execution_mode != "fixedBatch"
        or job.utterance_plan_path is not None
    ):
        raise WorkerExecutionError("Cohere vLLM only accepts fixed batch routes")
    if not job.punctuation:
        raise WorkerExecutionError(
            "Cohere vLLM requires punctuation because its pinned decoder uses pnc"
        )
