from __future__ import annotations

from concurrent.futures import Future
from copy import deepcopy
import hashlib
import threading

from yap_server.pools.batch_asr import (
    BatchAsrJob,
    PoolBackpressure,
    WorkerContainmentError,
    WorkerExecutionError,
)

from tests.recording_job_fixtures import (
    ControlledJobProcessor,
    ImmediateReservation,
    ReservableProcessor,
    service_recording_job_request as create_recording_job_request,
)


_ImmediateReservation = ImmediateReservation
_ReservableProcessor = ReservableProcessor
_ControlledProcessor = ControlledJobProcessor
_create_request = create_recording_job_request


class _Processor(_ReservableProcessor):
    def submit(self, job: BatchAsrJob) -> Future[dict[str, object]]:
        raise AssertionError(f"job {job.job_id} must not dispatch before commit")


class _BusyProcessor(_ReservableProcessor):
    def reserve(
        self,
        job_id: str,
        *,
        pcm_byte_length: int,
    ) -> _ImmediateReservation:
        raise PoolBackpressure(f"capacity unavailable for {job_id}")

    def submit(self, job: BatchAsrJob) -> Future[dict[str, object]]:
        raise PoolBackpressure(f"capacity unavailable for {job.job_id}")


class _UnstoppableProcessor(_ReservableProcessor):
    def __init__(self) -> None:
        self.future: Future[dict[str, object]] = Future()

    def submit(self, _job: BatchAsrJob) -> Future[dict[str, object]]:
        self.future.set_running_or_notify_cancel()
        return self.future

    def cancel(self, _job_id: str) -> bool:
        return False


class _ActiveCancellationWorker:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.stopped = threading.Event()

    def run(
        self,
        job: BatchAsrJob,
        cancellation: threading.Event,
    ) -> dict[str, object]:
        self.started.set()
        if not cancellation.wait(timeout=5):
            raise AssertionError(f"active job {job.job_id} was not cancelled")
        self.stopped.set()
        raise WorkerExecutionError("isolated ASR worker was cancelled")


class _UnverifiedCleanupWorker:
    def __init__(self) -> None:
        self.started = threading.Event()

    def run(
        self,
        job: BatchAsrJob,
        cancellation: threading.Event,
    ) -> dict[str, object]:
        self.started.set()
        if not cancellation.wait(timeout=5):
            raise AssertionError(f"active job {job.job_id} was not cancelled")
        raise WorkerContainmentError("owned container cleanup could not be verified")


class _DelayedCancellationWorker:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.cancellation_received = threading.Event()
        self.release_cleanup = threading.Event()

    def run(
        self,
        job: BatchAsrJob,
        cancellation: threading.Event,
    ) -> dict[str, object]:
        self.started.set()
        if not cancellation.wait(timeout=5):
            raise AssertionError(f"active job {job.job_id} was not cancelled")
        self.cancellation_received.set()
        if not self.release_cleanup.wait(timeout=5):
            raise AssertionError(f"active job {job.job_id} cleanup was not released")
        raise WorkerExecutionError("isolated ASR worker was cancelled")


def _request_with_preprocessing_evidence() -> dict[str, object]:
    request = deepcopy(_create_request())
    request["captureManifest"]["schemaVersion"] = 2
    request["asrCatalogRevision"] = "c" * 64
    request["preprocessingEvidence"] = {
        "schemaVersion": 1,
        "normalization": {
            "status": "complete",
            "componentId": "yap-imported-audio-normalizer",
            "componentRevision": "canonical-pcm16-normalization-v1",
            "method": "canonical_pcm16_identity",
            "inputSourceSha256": "b" * 64,
            "sourcePcmSha256": hashlib.sha256(bytes(320)).hexdigest(),
            "outputPcmSha256": hashlib.sha256(bytes(320)).hexdigest(),
            "audioCodec": "pcm_s16le",
            "sampleRateHz": 16000,
            "channels": 1,
            "sourceSampleCount": 160,
            "outputSampleCount": 160,
            "paddingSamples": 0,
            "gainAppliedMilliDb": 0,
            "samplesModified": 0,
            "sourceTimePreserved": True,
        },
        "vad": {
            "status": "complete",
            "component": {
                "id": "sherpa-onnx-silero-vad",
                "revision": "sherpa-onnx-1.13.4",
                "modelId": "k2-fsa/silero_vad.onnx",
                "modelRevision": "github-release-asset-271935959",
                "artifactSha256": (
                    "9e2449e1087496d8d4caba907f23e0bd3f78d91fa552479bb9c23ac09cbb1fd6"
                ),
            },
            "sourceSampleCount": 160,
            "intervals": [
                {
                    "startSample": 0,
                    "endSampleExclusive": 160,
                    "startMs": 0,
                    "endMs": 10,
                }
            ],
        },
    }
    return request


def _published_result(job: dict[str, object]) -> dict[str, object]:
    return {
        "sessionId": job["sessionId"],
        "revision": 1,
        "authority": "server_authoritative",
        "createdAtUtc": "2026-07-14T21:20:00Z",
        "captureManifestSha256": job["captureManifest"]["sha256"],
        "previousResultSha256": None,
        "status": "complete",
        "language": {"languageBcp47": "en", "confidence": None},
        "transcript": "Crash-safe private transcript.",
        "alignedWords": [],
        "modelProvenance": [
            {
                "modelId": "private-asr",
                "revision": "revision-1",
                "calibrationRevision": "asr-not-applicable",
            }
        ],
    }
