from __future__ import annotations

import json
import math
from pathlib import Path
import tempfile
import threading
import time
import unittest

from yap_server.evaluation.provider_cancellation_qualification import (
    VllmCancellationMetricsObserver,
    run_provider_cancellation_case,
)
from yap_server.evaluation.provider_runtime_observations import QualificationRequest
from yap_server.evaluation.runtime_plan import load_runtime_evaluation_plan
from yap_server.evaluation.vllm_runtime_metrics import (
    VllmHistogramSnapshot,
    VllmMetricsSnapshot,
)
from yap_server.pools.batch_contract import (
    AsrRouteDecision,
    BatchAsrJob,
    WorkerCancellationAcknowledged,
    WorkerExecutionError,
)


SERVER_ROOT = Path(__file__).resolve().parents[2]


class _Factory:
    def __init__(self, root: Path) -> None:
        self._root = root

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
                input_path=self._root / f"input-{ordinal}.wav",
                result_path=self._root / f"result-{ordinal}.json",
                language="und",
                input_sha256="a" * 64,
                route=AsrRouteDecision(
                    provider_id="nemotron",
                    pool_id="nemotron-batch",
                    execution_mode="dynamicBatch",
                    model_revision="b" * 40,
                    provider_language="auto",
                ),
                utterance_plan_path=self._root / f"plan-{ordinal}.json",
                utterance_plan_sha256="c" * 64,
            ),
            audio_samples=duration_samples,
        )


class _CancellationWorker:
    def __init__(self, *, generic_target_failure: bool = False) -> None:
        self._generic_target_failure = generic_target_failure
        self._lock = threading.Lock()
        self._active = 0
        self._target_finished = threading.Event()
        self.dispatched: dict[str, threading.Event] = {}

    def verify_ready(self) -> None:
        return

    def close(self) -> None:
        return

    def active_requests(self) -> int:
        with self._lock:
            return self._active

    def wait_until_dispatched(
        self,
        job_id: str,
        *,
        timeout_seconds: float,
    ) -> bool:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            with self._lock:
                dispatched = self.dispatched.get(job_id)
            if dispatched is not None:
                return dispatched.wait(max(0.0, deadline - time.monotonic()))
            time.sleep(0.005)
        return False

    def run(
        self,
        job: BatchAsrJob,
        cancellation: threading.Event,
    ) -> dict[str, object]:
        ordinal = int(job.job_id.rsplit("-", 1)[1])
        with self._lock:
            self._active += 1
            dispatched = self.dispatched.setdefault(job.job_id, threading.Event())
            dispatched.set()
        try:
            if ordinal == 0:
                if not self._target_finished.wait(timeout=1):
                    raise AssertionError("target did not finish")
            elif ordinal == 1:
                if not cancellation.wait(timeout=1):
                    raise AssertionError("target was not cancelled")
                self._target_finished.set()
                if self._generic_target_failure:
                    raise WorkerExecutionError("generic failure")
                raise WorkerCancellationAcknowledged("cancelled")
            result: dict[str, object] = {
                "jobId": job.job_id,
                "transcript": {"text": "private transcript"},
            }
            job.result_path.write_text(json.dumps(result), encoding="utf-8")
            return result
        finally:
            with self._lock:
                self._active -= 1


class _MetricsClient:
    def __init__(self, snapshots: list[VllmMetricsSnapshot]) -> None:
        self._snapshots = snapshots

    def snapshot(self) -> VllmMetricsSnapshot:
        return self._snapshots.pop(0)


class ProviderCancellationQualificationTests(unittest.TestCase):
    def test_requires_typed_target_acknowledgement_and_immediate_recovery(self) -> None:
        plan = load_runtime_evaluation_plan(SERVER_ROOT / "asr-evaluation-plan.json")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            worker = _CancellationWorker()
            qualification = run_provider_cancellation_case(
                worker,  # type: ignore[arg-type]
                _Factory(root),
                worker,
                worker,
                plan,
                load_case_id="nemo-finalized-cancelled-sibling",
                timeout_seconds=1,
            )
            evidence = qualification.public_evidence()

        self.assertTrue(qualification.passed)
        self.assertEqual(
            evidence["outcomes"],
            {"leader": "completed", "target": "cancelled", "recovery": "completed"},
        )
        self.assertEqual(
            evidence["resultPublished"],
            {"leader": True, "target": False, "recovery": True},
        )
        self.assertTrue(evidence["providerIdleBeforeRecovery"])
        self.assertTrue(evidence["providerIdleAfterRecovery"])
        encoded = json.dumps(evidence)
        self.assertNotIn(str(root), encoded)
        self.assertNotIn("private transcript", encoded)
        self.assertNotIn("-c2-", encoded)

    def test_generic_failure_after_cancel_intent_does_not_pass(self) -> None:
        plan = load_runtime_evaluation_plan(SERVER_ROOT / "asr-evaluation-plan.json")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            worker = _CancellationWorker(generic_target_failure=True)
            qualification = run_provider_cancellation_case(
                worker,  # type: ignore[arg-type]
                _Factory(root),
                worker,
                worker,
                plan,
                load_case_id="nemo-finalized-cancelled-sibling",
                timeout_seconds=1,
            )

        self.assertFalse(qualification.passed)
        self.assertEqual(qualification.run["outcomes"]["target"], "failed")  # type: ignore[index]
        self.assertIsNone(
            qualification.run["cancellationIntentToAcknowledgementMs"]
        )

    def test_vllm_metrics_accept_external_disconnect_abort_accounting(self) -> None:
        observer = VllmCancellationMetricsObserver(
            _MetricsClient(  # type: ignore[arg-type]
                [
                    _snapshot(0, stop=0, abort=0),
                    _snapshot(1, stop=1, abort=0),
                    _snapshot(2, stop=2, abort=0),
                ]
            )
        )

        token = observer.begin()
        token, pair = observer.after_cancelled_pair(token)
        recovery = observer.after_recovery(token)

        self.assertEqual(
            pair["targetProviderOutcome"], "aborted-on-client-disconnect"
        )
        self.assertTrue(pair["metricsConsistent"])
        self.assertEqual(pair["successfulEngineRequests"], 1)
        self.assertTrue(recovery["metricsConsistent"])

    def test_vllm_metrics_accept_counted_abort_finish_reason(self) -> None:
        observer = VllmCancellationMetricsObserver(
            _MetricsClient(  # type: ignore[arg-type]
                [
                    _snapshot(0, stop=0, abort=0),
                    _snapshot(2, stop=1, abort=1),
                    _snapshot(3, stop=2, abort=1),
                ]
            )
        )

        token = observer.begin()
        token, pair = observer.after_cancelled_pair(token)
        recovery = observer.after_recovery(token)

        self.assertEqual(
            pair["targetProviderOutcome"],
            "aborted-with-engine-finish-reason",
        )
        self.assertTrue(pair["metricsConsistent"])
        self.assertEqual(pair["engineFinishReasons"]["abort"], 1)  # type: ignore[index]
        self.assertTrue(recovery["metricsConsistent"])
        self.assertEqual(recovery["successfulEngineRequests"], 1)

    def test_vllm_metrics_reject_ambiguous_pair_accounting(self) -> None:
        observer = VllmCancellationMetricsObserver(
            _MetricsClient(  # type: ignore[arg-type]
                [
                    _snapshot(0, stop=0, abort=0),
                    _snapshot(3, stop=3, abort=0),
                ]
            )
        )

        token = observer.begin()
        _token, pair = observer.after_cancelled_pair(token)

        self.assertEqual(
            pair["targetProviderOutcome"], "ambiguous-provider-accounting"
        )
        self.assertFalse(pair["metricsConsistent"])


def _snapshot(
    count: int,
    *,
    stop: int,
    abort: int,
) -> VllmMetricsSnapshot:
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
            "stop": stop,
            "length": 0,
            "abort": abort,
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
