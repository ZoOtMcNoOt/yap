from __future__ import annotations

import json
import math
from pathlib import Path
import tempfile
import threading
from typing import Callable
import unittest
from unittest.mock import patch

from yap_server.evaluation.duration_tracks import LoadedDurationTrack
from yap_server.evaluation.provider_runtime_observations import QualificationRequest
from yap_server.evaluation.provider_runtime_qualification import (
    VllmQualificationMetricsObserver,
    run_provider_load_case,
    run_resident_provider_load_case,
    validate_resident_provider_lock,
)
from yap_server.evaluation.runtime_plan import load_runtime_evaluation_plan
from yap_server.evaluation.vllm_runtime_metrics import (
    VllmHistogramSnapshot,
    VllmMetricsSnapshot,
)
from yap_server.pools.batch_contract import AsrRouteDecision, BatchAsrJob
from yap_server.pools.model_lock import load_model_pool_lock


SERVER_ROOT = Path(__file__).resolve().parents[2]


class _Worker:
    def __init__(
        self,
        transcript_for_job: Callable[[str], str] | None = None,
    ) -> None:
        self.ready = False
        self.closed = False
        self.transcript_for_job = transcript_for_job or (
            lambda _job_id: "private transcript"
        )

    def verify_ready(self) -> None:
        self.ready = True

    def close(self) -> None:
        self.closed = True

    def run(
        self,
        job: BatchAsrJob,
        _cancellation: threading.Event,
    ) -> dict[str, object]:
        result: dict[str, object] = {
            "jobId": job.job_id,
            "transcript": {"text": self.transcript_for_job(job.job_id)},
            "runtime": {"queueMs": 1, "inferenceMs": 2, "batchSize": 1},
        }
        job.result_path.write_text(json.dumps(result), encoding="utf-8")
        return result


class ProviderServingLockTests(unittest.TestCase):
    def test_only_the_matching_serving_lock_is_admitted(self) -> None:
        validate_resident_provider_lock(
            "vllm-cohere-batch",
            load_model_pool_lock(SERVER_ROOT / "cohere-vllm-serving.lock.json"),
        )
        validate_resident_provider_lock(
            "nemo-nemotron-finalized",
            load_model_pool_lock(SERVER_ROOT / "nemotron-nemo-serving.lock.json"),
        )

        for system_id, lock_name in (
            ("vllm-cohere-batch", "model-pools.lock.json"),
            ("nemo-nemotron-finalized", "nemotron-model-pool.lock.json"),
            ("vllm-cohere-batch", "nemotron-nemo-serving.lock.json"),
            ("nemo-nemotron-finalized", "cohere-vllm-serving.lock.json"),
        ):
            with self.subTest(system_id=system_id, lock_name=lock_name):
                with self.assertRaisesRegex(ValueError, "provider-serving lock"):
                    validate_resident_provider_lock(
                        system_id,
                        load_model_pool_lock(SERVER_ROOT / lock_name),
                    )


class _Factory:
    def __init__(self, root: Path) -> None:
        self.root = root

    def create(
        self,
        *,
        load_case_id: str,
        concurrency: int,
        ordinal: int,
        duration_samples: int,
    ) -> QualificationRequest:
        job_id = f"{load_case_id}-c{concurrency}-{ordinal}"
        return QualificationRequest(
            job=BatchAsrJob(
                job_id=job_id,
                input_path=self.root / "input.wav",
                result_path=self.root / f"{job_id}.json",
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
            audio_samples=duration_samples,
        )


class _MetricsClient:
    def __init__(self, snapshots: list[VllmMetricsSnapshot]) -> None:
        self.snapshots = snapshots

    def snapshot(self) -> VllmMetricsSnapshot:
        return self.snapshots.pop(0)


class ProviderRuntimeQualificationTests(unittest.TestCase):
    def test_executes_each_planned_concurrency_and_emits_public_safe_evidence(
        self,
    ) -> None:
        plan = load_runtime_evaluation_plan(
            SERVER_ROOT / "asr-evaluation-plan.json"
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            qualification = run_provider_load_case(
                _Worker(),
                _Factory(root),
                plan,
                load_case_id="nemo-finalized-long-windows",
                timeout_seconds_per_wave=1,
            )
            evidence = qualification.public_evidence()

        runs = evidence["runs"]
        self.assertIsInstance(runs, list)
        assert isinstance(runs, list)
        self.assertEqual([run["concurrency"] for run in runs], [2])
        self.assertTrue(all(run["minimumCompletionsMet"] for run in runs))
        self.assertTrue(all(run["expectationMet"] for run in runs))
        self.assertTrue(evidence["passed"])
        encoded = json.dumps(evidence)
        self.assertNotIn(str(root), encoded)
        self.assertNotIn("private transcript", encoded)
        self.assertNotIn("fixed-auto-parity-c", encoded)
        self.assertRegex(str(evidence["evidenceSha256"]), r"^[0-9a-f]{64}$")

    def test_standard_load_requires_lexical_not_rendering_stability(self) -> None:
        plan = load_runtime_evaluation_plan(
            SERVER_ROOT / "asr-evaluation-plan.json"
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            punctuation = run_provider_load_case(
                _Worker(
                    lambda job_id: (
                        "Private, transcript."
                        if job_id.endswith(("0", "2"))
                        else "private transcript"
                    )
                ),
                _Factory(root),
                plan,
                load_case_id="vllm-long-waves",
                timeout_seconds_per_wave=1,
            )
        self.assertTrue(punctuation.passed)
        self.assertEqual(punctuation.runs[0]["transcriptIdentityCount"], 2)
        self.assertEqual(
            punctuation.runs[0]["lexicalTranscriptIdentityCount"],
            1,
        )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lexical_drift = run_provider_load_case(
                _Worker(
                    lambda job_id: (
                        "private altered transcript"
                        if job_id.endswith("3")
                        else "private transcript"
                    )
                ),
                _Factory(root),
                plan,
                load_case_id="vllm-long-waves",
                timeout_seconds_per_wave=1,
            )
        self.assertFalse(lexical_drift.passed)
        self.assertEqual(
            lexical_drift.runs[0]["lexicalTranscriptIdentityCount"],
            2,
        )

    def test_refuses_to_misreport_a_specialized_scenario_as_a_plain_load(self) -> None:
        plan = load_runtime_evaluation_plan(
            SERVER_ROOT / "asr-evaluation-plan.json"
        )
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "specialized"):
                run_provider_load_case(
                    _Worker(),
                    _Factory(Path(directory)),
                    plan,
                    load_case_id="nemo-finalized-cancelled-sibling",
                    timeout_seconds_per_wave=1,
                )

    def test_composes_a_standard_resident_load_from_private_tracks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / "private-cache"
            cache.mkdir()
            audio = cache / "fifteen-minute.wav"
            audio.write_bytes(b"private-placeholder")
            track = LoadedDurationTrack(
                audio_path=audio.resolve(),
                manifest={
                    "audio": {
                        "durationSamples": 14_400_000,
                        "sha256": "a" * 64,
                    }
                },
            )
            worker = _Worker()
            with (
                patch(
                    "yap_server.evaluation.provider_runtime_qualification."
                    "load_exact_tracks",
                    return_value={14_400_000: track},
                ),
                patch(
                    "yap_server.evaluation.provider_runtime_qualification."
                    "build_resident_worker",
                    return_value=worker,
                ),
                patch(
                    "yap_server.evaluation.provider_runtime_qualification."
                    "_resident_metrics_observer",
                    return_value=None,
                ),
            ):
                qualification = run_resident_provider_load_case(
                    plan_path=SERVER_ROOT / "asr-evaluation-plan.json",
                    load_case_id="vllm-long-waves",
                    model_lock_path=SERVER_ROOT / "cohere-vllm-serving.lock.json",
                    track_manifest_paths=(cache / "manifest.json",),
                    endpoint="http://127.0.0.1:18000",
                    catalog_language="en-US",
                    provider_language="en",
                    output_root=cache / "qualification",
                    timeout_seconds_per_wave=1,
                    environ={
                        "YAP_EVAL_CACHE": str(cache),
                        "YAP_COHERE_VLLM_API_KEY": "private-test-key",
                    },
                )

        self.assertTrue(worker.ready)
        self.assertTrue(worker.closed)
        self.assertTrue(qualification.passed)
        self.assertEqual(qualification.runs[0]["requestCount"], 4)

    def test_resident_runner_rejects_specialized_cases_before_execution(self) -> None:
        with self.assertRaisesRegex(ValueError, "specialized"):
            run_resident_provider_load_case(
                plan_path=SERVER_ROOT / "asr-evaluation-plan.json",
                load_case_id="nemo-finalized-fixed-auto-parity",
                model_lock_path=SERVER_ROOT / "nemotron-nemo-serving.lock.json",
                track_manifest_paths=(Path("unused"),),
                endpoint="http://127.0.0.1:18001",
                catalog_language="und",
                provider_language="auto",
                output_root=Path("unused"),
                timeout_seconds_per_wave=1,
                environ={},
            )

    def test_vllm_metrics_must_match_the_exact_completed_request_count(self) -> None:
        plan = load_runtime_evaluation_plan(
            SERVER_ROOT / "asr-evaluation-plan.json"
        )
        with tempfile.TemporaryDirectory() as directory:
            qualification = run_provider_load_case(
                _Worker(),
                _Factory(Path(directory)),
                plan,
                load_case_id="vllm-long-waves",
                timeout_seconds_per_wave=1,
                metrics_observer=VllmQualificationMetricsObserver(
                    _MetricsClient(  # type: ignore[arg-type]
                        [_metrics_snapshot(0), _metrics_snapshot(4)]
                    )
                ),
            )

        self.assertTrue(qualification.passed)
        provider_metrics = qualification.runs[0]["providerMetrics"]
        self.assertTrue(provider_metrics["engineRequestCountAcceptable"])
        self.assertEqual(provider_metrics["successfulEngineRequests"], 4)

        with tempfile.TemporaryDirectory() as directory:
            qualification = run_provider_load_case(
                _Worker(),
                _Factory(Path(directory)),
                plan,
                load_case_id="vllm-long-waves",
                timeout_seconds_per_wave=1,
                metrics_observer=VllmQualificationMetricsObserver(
                    _MetricsClient(  # type: ignore[arg-type]
                        [_metrics_snapshot(0), _metrics_snapshot(3)]
                    )
                ),
            )
        self.assertFalse(qualification.passed)

        long_observer = VllmQualificationMetricsObserver(
            _MetricsClient(  # type: ignore[arg-type]
                [_metrics_snapshot(0), _metrics_snapshot(4)]
            )
        )
        token = long_observer.before_run(concurrency=1)
        long_evidence = long_observer.after_run(
            token,
            completed_requests=1,
            maximum_audio_samples=1_920_000,
        )
        self.assertTrue(long_evidence["engineRequestCountAcceptable"])
        self.assertEqual(long_evidence["engineRequestsPerCompletedApiRequest"], 4.0)

        short_observer = VllmQualificationMetricsObserver(
            _MetricsClient(  # type: ignore[arg-type]
                [_metrics_snapshot(0), _metrics_snapshot(4)]
            )
        )
        token = short_observer.before_run(concurrency=1)
        short_evidence = short_observer.after_run(
            token,
            completed_requests=1,
            maximum_audio_samples=480_000,
        )
        self.assertFalse(short_evidence["engineRequestCountAcceptable"])


def _metrics_snapshot(count: int) -> VllmMetricsSnapshot:
    histogram = VllmHistogramSnapshot(
        count=count,
        total_seconds=count * 0.1,
        cumulative_buckets=((0.1, count), (math.inf, count)),
    )
    return VllmMetricsSnapshot(
        running_requests=0,
        waiting_requests=0,
        successful_requests=count,
        finished_requests={
            "stop": count,
            "length": 0,
            "abort": 0,
            "error": 0,
            "repetition": 0,
        },
        histograms={
            "vllm:e2e_request_latency_seconds": histogram,
            "vllm:request_inference_time_seconds": histogram,
            "vllm:request_queue_time_seconds": histogram,
        },
    )


if __name__ == "__main__":
    unittest.main()
