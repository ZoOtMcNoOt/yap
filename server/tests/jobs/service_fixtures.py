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
from yap_server.pools.batch_contract import BatchJobFactory

from tests.asr_route_fixtures import TEST_ASR_CATALOG_REVISION, test_asr_route


class _ImmediateReservation:
    def __init__(self, processor: object, job_id: str) -> None:
        self._processor = processor
        self._job_id = job_id
        self._aborted = False

    def start(self, factory: BatchJobFactory) -> Future[dict[str, object]]:
        if self._aborted:
            raise RuntimeError("test reservation was aborted")
        job = factory(threading.Event())
        if job.job_id != self._job_id:
            raise AssertionError("test reservation identity changed")
        return self._processor.submit(job)

    def abort(self) -> None:
        self._aborted = True


class _ReservableProcessor:
    @property
    def asr_catalog_revision(self) -> str:
        return TEST_ASR_CATALOG_REVISION

    def resolve_route(self, catalog_language_bcp47: str):
        return test_asr_route(catalog_language_bcp47)

    def reserve(
        self,
        job_id: str,
        *,
        pcm_byte_length: int,
    ) -> _ImmediateReservation:
        if pcm_byte_length < 1:
            raise ValueError("test PCM reservation must be positive")
        return _ImmediateReservation(self, job_id)


class _Processor(_ReservableProcessor):
    def submit(self, job: BatchAsrJob) -> Future[dict[str, object]]:
        raise AssertionError(f"job {job.job_id} must not dispatch before commit")


class _ControlledProcessor(_ReservableProcessor):
    def __init__(self) -> None:
        self.jobs: list[BatchAsrJob] = []
        self.reserved_pcm_bytes: list[int] = []
        self.future: Future[dict[str, object]] = Future()

    def reserve(
        self,
        job_id: str,
        *,
        pcm_byte_length: int,
    ) -> _ImmediateReservation:
        self.reserved_pcm_bytes.append(pcm_byte_length)
        return super().reserve(job_id, pcm_byte_length=pcm_byte_length)

    def submit(self, job: BatchAsrJob) -> Future[dict[str, object]]:
        self.jobs.append(job)
        return self.future


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


def _create_request(
    *,
    session_id: str = "s-batch-create",
    retention_expires_at_utc: str | None = "2026-08-13T21:00:00Z",
) -> dict[str, object]:
    track_id = "track-1"
    chunk = bytes(320)
    return {
        "displayName": "Batch transcription vertical slice",
        "metadata": {
            "sessionId": session_id,
            "mode": "meeting",
            "origin": "imported_file",
            "triggerMode": "toggle",
            "startedAtUtc": "2026-07-14T21:00:00Z",
            "utcOffsetMinutesAtStart": -300,
            "localeHintBcp47": "en-US",
            "countryCodeHint": "US",
            "preferredLanguagesBcp47": ["en-US"],
            "appVersion": "0.1.0",
            "platform": "windows",
            "privacyPolicyVersion": "development-only",
            "retentionExpiresAtUtc": retention_expires_at_utc,
        },
        "languageDecision": {
            "mode": "fixed",
            "languageBcp47": "en-US",
            "disposition": "primary",
        },
        "tracks": [
            {
                "trackId": track_id,
                "source": {"kind": "imported", "provenance": "unknown"},
                "deviceId": None,
                "originalSampleRateHz": 16000,
                "originalChannels": 1,
            }
        ],
        "route": "server_batch",
        "captureManifest": {
            "schemaVersion": 1,
            "sessionId": session_id,
            "sha256": "a" * 64,
            "byteLength": 4096,
        },
        "chunks": [
            {
                "replayKey": {
                    "schemaVersion": 1,
                    "sessionId": session_id,
                    "trackId": track_id,
                    "sequenceStart": 0,
                    "sequenceEnd": 159,
                },
                "contentIdentity": {
                    "sha256": hashlib.sha256(chunk).hexdigest(),
                    "byteLength": len(chunk),
                },
                "audioCodec": "pcm_s16le",
                "sampleRateHz": 16000,
                "channels": 1,
                "startMs": 0,
                "durationMs": 10,
            }
        ],
    }


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
