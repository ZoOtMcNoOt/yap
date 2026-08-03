from __future__ import annotations

from concurrent.futures import Future
from copy import deepcopy
import hashlib
import threading
from typing import Any

from yap_server.pools.batch_asr import BatchAsrJob
from yap_server.pools.batch_contract import BatchJobFactory

from tests.asr_route_fixtures import TEST_ASR_CATALOG_REVISION, test_asr_route


class ImmediateReservation:
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


class ReservableProcessor:
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
    ) -> ImmediateReservation:
        if pcm_byte_length < 1:
            raise ValueError("test PCM reservation must be positive")
        return ImmediateReservation(self, job_id)


class ControlledJobProcessor(ReservableProcessor):
    def __init__(self) -> None:
        self.jobs: list[BatchAsrJob] = []
        self.reserved_pcm_bytes: list[int] = []
        self.future: Future[dict[str, object]] = Future()

    def reserve(
        self,
        job_id: str,
        *,
        pcm_byte_length: int,
    ) -> ImmediateReservation:
        self.reserved_pcm_bytes.append(pcm_byte_length)
        return super().reserve(job_id, pcm_byte_length=pcm_byte_length)

    def submit(self, job: BatchAsrJob) -> Future[dict[str, object]]:
        self.jobs.append(job)
        return self.future


def service_recording_job_request(
    *,
    session_id: str = "s-batch-create",
    retention_expires_at_utc: str | None = "2026-08-13T21:00:00Z",
) -> dict[str, object]:
    return _recording_job_request(
        display_name="Batch transcription vertical slice",
        session_id=session_id,
        origin="imported_file",
        track_source={"kind": "imported", "provenance": "unknown"},
        started_at_utc="2026-07-14T21:00:00Z",
        utc_offset_minutes_at_start=-300,
        country_code_hint="US",
        privacy_policy_version="development-only",
        retention_expires_at_utc=retention_expires_at_utc,
        chunk_sha256=hashlib.sha256(bytes(320)).hexdigest(),
    )


def batch_api_recording_job_request() -> dict[str, object]:
    request = service_recording_job_request(session_id="s-batch-api")
    request["displayName"] = "Batch API fixture"
    return request


def provenance_contract_job_request(
    origin: str,
    track_source: dict[str, Any],
) -> dict[str, Any]:
    return _recording_job_request(
        display_name="Provenance contract test",
        session_id="s-provenance-test",
        origin=origin,
        track_source=track_source,
        started_at_utc="2026-07-12T16:00:00Z",
        utc_offset_minutes_at_start=None,
        country_code_hint=None,
        privacy_policy_version="unconfigured",
        retention_expires_at_utc="2026-08-11T16:00:00Z",
        chunk_sha256="b" * 64,
    )


def _recording_job_request(
    *,
    display_name: str,
    session_id: str,
    origin: str,
    track_source: dict[str, Any],
    started_at_utc: str,
    utc_offset_minutes_at_start: int | None,
    country_code_hint: str | None,
    privacy_policy_version: str,
    retention_expires_at_utc: str | None,
    chunk_sha256: str,
) -> dict[str, Any]:
    track_id = "track-1"
    return {
        "displayName": display_name,
        "metadata": {
            "sessionId": session_id,
            "mode": "meeting",
            "origin": origin,
            "triggerMode": "toggle",
            "startedAtUtc": started_at_utc,
            "utcOffsetMinutesAtStart": utc_offset_minutes_at_start,
            "localeHintBcp47": "en-US",
            "countryCodeHint": country_code_hint,
            "preferredLanguagesBcp47": ["en-US"],
            "appVersion": "0.1.0",
            "platform": "windows",
            "privacyPolicyVersion": privacy_policy_version,
            "retentionExpiresAtUtc": retention_expires_at_utc,
        },
        "languageDecision": {
            "mode": "fixed",
            "languageBcp47": "en-US",
            "disposition": "primary",
        },
        "asrCatalogRevision": TEST_ASR_CATALOG_REVISION,
        "tracks": [
            {
                "trackId": track_id,
                "source": deepcopy(track_source),
                "deviceId": None,
                "originalSampleRateHz": 16000,
                "originalChannels": 1,
            }
        ],
        "route": "server_batch",
        "captureManifest": {
            "schemaVersion": 2,
            "sessionId": session_id,
            "sha256": "a" * 64,
            "byteLength": 4096,
        },
        "preprocessingEvidence": {
            "schemaVersion": 2,
            "normalization": {
                "status": "complete",
                "componentId": "yap-imported-audio-normalizer",
                "componentRevision": "canonical-pcm16-normalization-v1",
                "method": "canonical_pcm16_identity",
                "inputSourceSha256": chunk_sha256,
                "sourcePcmSha256": chunk_sha256,
                "outputPcmSha256": chunk_sha256,
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
                    "sha256": chunk_sha256,
                    "byteLength": 320,
                },
                "audioCodec": "pcm_s16le",
                "sampleRateHz": 16000,
                "channels": 1,
                "startMs": 0,
                "durationMs": 10,
            }
        ],
    }
