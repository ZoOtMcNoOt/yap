from __future__ import annotations

from concurrent.futures import Future
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

    def close(self) -> None:
        pass


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

    def close(self) -> None:
        pass


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

    def close(self) -> None:
        self.release_cleanup.set()


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
        "alignment": {
            "status": "unavailable",
            "reason": "ALIGNMENT_RUNTIME_FAILED",
            "componentRevision": "cohere-attention-alignment-candidate-v1",
        },
        "alignedWords": [],
        "modelProvenance": [
            {
                "modelId": "private-asr",
                "revision": "revision-1",
                "calibrationRevision": "asr-not-applicable",
            }
        ],
    }
