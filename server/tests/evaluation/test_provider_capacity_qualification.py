from __future__ import annotations

import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

from yap_server.evaluation.provider_capacity_qualification import (
    run_nemo_service_capacity_case,
    run_vllm_pool_capacity_case,
)
from yap_server.evaluation.provider_runtime_observations import QualificationRequest
from yap_server.evaluation.runtime_plan import load_runtime_evaluation_plan
from yap_server.jobs.contract_values import MAX_JOB_PCM_BYTES
from yap_server.pools.batch_contract import (
    AsrRouteDecision,
    BatchAsrJob,
    ProviderCapacityUnavailable,
)
from yap_server.pools.batch_pool import BatchAsrPool


SERVER_ROOT = Path(__file__).resolve().parents[2]


class _Factory:
    def __init__(self, root: Path, *, system_id: str) -> None:
        self._root = root
        self._system_id = system_id

    def create(
        self,
        *,
        load_case_id: str,
        concurrency: int,
        ordinal: int,
        duration_samples: int,
    ) -> QualificationRequest:
        nemo = self._system_id == "nemo-nemotron-finalized"
        job_id = f"{load_case_id}-c{concurrency}-{ordinal}"
        return QualificationRequest(
            job=BatchAsrJob(
                job_id=job_id,
                input_path=self._root / f"input-{ordinal}.wav",
                result_path=self._root / f"result-{ordinal}.json",
                language="und" if nemo else "en-US",
                input_sha256="a" * 64,
                route=AsrRouteDecision(
                    provider_id="nemotron" if nemo else "cohere",
                    pool_id="nemotron-batch" if nemo else "cohere-batch",
                    execution_mode="dynamicBatch" if nemo else "fixedBatch",
                    model_revision="b" * 40,
                    provider_language="auto" if nemo else "en",
                ),
                utterance_plan_path=(
                    self._root / f"plan-{ordinal}.json" if nemo else None
                ),
                utterance_plan_sha256="c" * 64 if nemo else None,
            ),
            audio_samples=duration_samples,
        )


class _PublishingWorker:
    def __init__(self) -> None:
        self.closed = False

    def verify_ready(self) -> None:
        return

    def close(self) -> None:
        self.closed = True

    def run(
        self,
        job: BatchAsrJob,
        _cancellation: threading.Event,
    ) -> dict[str, object]:
        result: dict[str, object] = {
            "jobId": job.job_id,
            "transcript": {"text": "private transcript"},
        }
        job.result_path.write_text(json.dumps(result), encoding="utf-8")
        return result


class _BoundedNemoWorker(_PublishingWorker):
    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self._active = 0
        self._release = threading.Event()

    def active_requests(self) -> int:
        with self._lock:
            return self._active

    def run(
        self,
        job: BatchAsrJob,
        cancellation: threading.Event,
    ) -> dict[str, object]:
        with self._lock:
            if self._active >= 8:
                capacity_full = True
            else:
                capacity_full = False
                self._active += 1
        if capacity_full:
            time.sleep(0.05)
            self._release.set()
            raise ProviderCapacityUnavailable("admission is full")
        try:
            if not self._release.wait(timeout=1):
                raise AssertionError("capacity overflow was not observed")
            return super().run(job, cancellation)
        finally:
            with self._lock:
                self._active -= 1


class ProviderCapacityQualificationTests(unittest.TestCase):
    def test_vllm_slot_and_pcm_limits_reject_then_recover_at_the_pool_owner(
        self,
    ) -> None:
        plan = load_runtime_evaluation_plan(SERVER_ROOT / "asr-evaluation-plan.json")
        for load_case_id in ("vllm-slot-capacity", "vllm-pcm-capacity"):
            with self.subTest(load_case_id=load_case_id), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                worker = _PublishingWorker()
                pool = BatchAsrPool(
                    worker,
                    route_resolver=lambda _language: AsrRouteDecision(
                        provider_id="cohere",
                        pool_id="cohere-batch",
                        execution_mode="fixedBatch",
                        model_revision="b" * 40,
                        provider_language="en",
                    ),
                    asr_catalog_revision="d" * 64,
                    max_workers=8,
                    max_queued=8,
                    max_inflight_pcm_bytes=MAX_JOB_PCM_BYTES,
                )
                try:
                    qualification = run_vllm_pool_capacity_case(
                        pool,
                        _Factory(root, system_id="vllm-cohere-batch"),
                        plan,
                        load_case_id=load_case_id,
                        timeout_seconds=2,
                    )
                    evidence = qualification.public_evidence()
                finally:
                    pool.shutdown()

                self.assertTrue(qualification.passed, qualification.run)
                self.assertEqual(evidence["initialRetryableBusyCount"], 1)
                self.assertFalse(evidence["rejectedResultPublished"])
                self.assertEqual(evidence["recoveryOutcome"], "completed")
                self.assertNotIn(str(root), json.dumps(evidence))

    def test_nemo_requires_eight_active_one_typed_busy_and_recovery(self) -> None:
        plan = load_runtime_evaluation_plan(SERVER_ROOT / "asr-evaluation-plan.json")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            worker = _BoundedNemoWorker()
            qualification = run_nemo_service_capacity_case(
                worker,  # type: ignore[arg-type]
                _Factory(root, system_id="nemo-nemotron-finalized"),
                worker,
                plan,
                load_case_id="nemo-finalized-active-capacity",
                timeout_seconds=2,
            )
            evidence = qualification.public_evidence()

        self.assertTrue(qualification.passed)
        self.assertEqual(evidence["initialCompletedCount"], 8)
        self.assertEqual(evidence["initialRetryableBusyCount"], 1)
        self.assertEqual(evidence["maximumActiveRequestsObserved"], 8)
        self.assertEqual(evidence["recoveryOutcome"], "completed")
        self.assertNotIn(str(root), json.dumps(evidence))


if __name__ == "__main__":
    unittest.main()
