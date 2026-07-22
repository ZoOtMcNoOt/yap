from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import threading
import time
from typing import Callable
import unittest

from yap_server.evaluation.provider_runtime_observations import (
    QualificationRequest,
    canonical_evidence_sha256,
    run_bounded_load,
    run_concurrent_wave,
    summarize_runtime_load,
    summarize_runtime_wave,
)
from yap_server.pools.batch_contract import (
    AsrRouteDecision,
    BatchAsrJob,
    ProviderCapacityUnavailable,
)


class _Worker:
    def __init__(
        self,
        *,
        delay_seconds: float = 0.01,
        transcript_for_job: Callable[[str], str] | None = None,
    ) -> None:
        self.delay_seconds = delay_seconds
        self.transcript_for_job = transcript_for_job or (
            lambda _job_id: "stable public fixture output"
        )
        self.active = 0
        self.maximum_active = 0
        self.lock = threading.Lock()

    def run(
        self,
        job: BatchAsrJob,
        cancellation: threading.Event,
    ) -> dict[str, object]:
        with self.lock:
            self.active += 1
            self.maximum_active = max(self.maximum_active, self.active)
            observed_batch = self.maximum_active
        try:
            deadline = time.monotonic() + self.delay_seconds
            while time.monotonic() < deadline:
                if cancellation.is_set():
                    raise RuntimeError("cancelled")
                time.sleep(0.001)
            result = {
                "schemaVersion": 1,
                "jobId": job.job_id,
                "transcript": {"text": self.transcript_for_job(job.job_id)},
                "runtime": {
                    "queueMs": 2,
                    "inferenceMs": 5,
                    "batchSize": observed_batch,
                    "memory": {
                        "allocatedMiB": 100 + int(job.job_id.rsplit("-", 1)[-1]),
                        "reservedMiB": 200,
                        "peakAllocatedMiB": 150,
                        "peakReservedMiB": 250,
                    },
                },
            }
            job.result_path.write_text(json.dumps(result), encoding="utf-8")
            return result
        finally:
            with self.lock:
                self.active -= 1


class _BusyWorker:
    def run(
        self,
        _job: BatchAsrJob,
        _cancellation: threading.Event,
    ) -> dict[str, object]:
        raise ProviderCapacityUnavailable("provider admission is full")


class ProviderRuntimeObservationTests(unittest.TestCase):
    def test_wave_releases_independent_requests_and_emits_only_aggregate_evidence(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            requests = tuple(_request(root, index) for index in range(4))
            worker = _Worker()

            wave = run_concurrent_wave(worker, requests, timeout_seconds=1)
            summary = summarize_runtime_wave(wave)

        self.assertEqual(worker.maximum_active, 4)
        self.assertEqual(summary["requestCount"], 4)
        self.assertEqual(summary["outcomes"]["completed"], 4)  # type: ignore[index]
        self.assertEqual(summary["resultPublishedCount"], 4)
        self.assertEqual(summary["transcriptIdentityCount"], 1)
        self.assertEqual(summary["lexicalTranscriptIdentityCount"], 1)
        self.assertEqual(
            summary["transcriptStabilityByAudioDuration"],
            [
                {
                    "audioDurationSamples": 480_000,
                    "completedCount": 4,
                    "exactIdentityCount": 1,
                    "lexicalIdentityCount": 1,
                }
            ],
        )
        self.assertEqual(summary["queueMs"]["p99"], 2)  # type: ignore[index]
        self.assertEqual(summary["inferenceMs"]["p95"], 5)  # type: ignore[index]
        self.assertEqual(summary["maximumObservedModelBatch"], 4)
        self.assertEqual(
            summary["providerReportedMemoryMiB"],
            {
                "observationCount": 4,
                "allocated": {
                    "count": 4,
                    "minimum": 100,
                    "p50": 101,
                    "p95": 103,
                    "p99": 103,
                    "maximum": 103,
                },
                "reserved": {
                    "count": 4,
                    "minimum": 200,
                    "p50": 200,
                    "p95": 200,
                    "p99": 200,
                    "maximum": 200,
                },
                "peakAllocated": {
                    "count": 4,
                    "minimum": 150,
                    "p50": 150,
                    "p95": 150,
                    "p99": 150,
                    "maximum": 150,
                },
                "peakReserved": {
                    "count": 4,
                    "minimum": 250,
                    "p50": 250,
                    "p95": 250,
                    "p99": 250,
                    "maximum": 250,
                },
            },
        )
        encoded = json.dumps(summary)
        self.assertNotIn("job-", encoded)
        self.assertNotIn("stable public fixture output", encoded)
        self.assertNotIn(
            hashlib.sha256(b"stable public fixture output").hexdigest(),
            encoded,
        )

    def test_summary_separates_rendering_variance_from_lexical_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            punctuation = run_concurrent_wave(
                _Worker(
                    transcript_for_job=lambda job_id: (
                        "Stable, public fixture output."
                        if job_id.endswith(("0", "2"))
                        else "stable public fixture output"
                    )
                ),
                tuple(_request(root, index) for index in range(4)),
                timeout_seconds=1,
            )
            drift = run_concurrent_wave(
                _Worker(
                    transcript_for_job=lambda job_id: (
                        "stable altered fixture output"
                        if job_id.endswith("3")
                        else "stable public fixture output"
                    )
                ),
                tuple(_request(root, index + 10) for index in range(4)),
                timeout_seconds=1,
            )

        punctuation_summary = summarize_runtime_wave(punctuation)
        self.assertEqual(punctuation_summary["transcriptIdentityCount"], 2)
        self.assertEqual(punctuation_summary["lexicalTranscriptIdentityCount"], 1)
        drift_summary = summarize_runtime_wave(drift)
        self.assertEqual(drift_summary["transcriptIdentityCount"], 2)
        self.assertEqual(drift_summary["lexicalTranscriptIdentityCount"], 2)

    def test_wave_cancels_and_contains_requests_that_exceed_the_deadline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            request = _request(Path(directory), 0)
            wave = run_concurrent_wave(
                _Worker(delay_seconds=0.2),
                (request,),
                timeout_seconds=0.02,
            )

        self.assertEqual(wave.observations[0].outcome, "cancelled")
        self.assertFalse(wave.observations[0].result_published)

    def test_wave_classifies_typed_provider_backpressure_without_leaking_details(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            request = _request(Path(directory), 0)
            wave = run_concurrent_wave(
                _BusyWorker(),
                (request,),
                timeout_seconds=1,
            )

        self.assertEqual(wave.observations[0].outcome, "busy")
        self.assertNotIn("provider admission", json.dumps(summarize_runtime_wave(wave)))

    def test_bounded_load_uses_synchronized_waves_at_the_requested_concurrency(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            worker = _Worker()
            load = run_bounded_load(
                worker,
                tuple(_request(root, index) for index in range(10)),
                concurrency=4,
                timeout_seconds_per_wave=1,
            )
            summary = summarize_runtime_load(load)

        self.assertEqual(worker.maximum_active, 4)
        self.assertEqual(summary["concurrency"], 4)
        self.assertEqual(summary["waveCount"], 3)
        self.assertEqual(summary["requestCount"], 10)
        self.assertEqual(summary["outcomes"]["completed"], 10)  # type: ignore[index]
        self.assertNotIn("job-", json.dumps(summary))

    def test_request_and_evidence_identity_validation_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            request = _request(Path(directory), 0)
            with self.assertRaisesRegex(ValueError, "qualification request"):
                QualificationRequest(job=request.job, audio_samples=0)

        first = canonical_evidence_sha256({"b": 2, "a": 1})
        second = canonical_evidence_sha256({"a": 1, "b": 2})
        self.assertEqual(first, second)
        self.assertRegex(first, r"^[0-9a-f]{64}$")


def _request(root: Path, index: int) -> QualificationRequest:
    job_id = f"job-{index}"
    return QualificationRequest(
        job=BatchAsrJob(
            job_id=job_id,
            input_path=root / "input.wav",
            result_path=root / f"{job_id}.json",
            language="en",
            input_sha256="a" * 64,
            route=AsrRouteDecision(
                provider_id="cohere",
                pool_id="cohere-batch",
                execution_mode="fixedBatch",
                model_revision="b" * 40,
                provider_language="en",
            ),
        ),
        audio_samples=480_000,
    )


if __name__ == "__main__":
    unittest.main()
