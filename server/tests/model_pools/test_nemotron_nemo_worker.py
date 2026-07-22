from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
import wave

from yap_server.alignment_contract import (
    AlignmentUnavailableReason,
    unavailable_alignment,
)
from yap_server.pools.batch_contract import AsrRouteDecision, BatchAsrJob
from yap_server.pools.nemotron_nemo_worker import NemotronNemoBatchWorker

from .batch_asr_fixtures import test_lock as _test_lock


class _FakeClient:
    def __init__(self, result: dict[str, object]) -> None:
        self.result = result
        self.ready_locks: list[object] = []
        self.requests: list[object] = []
        self.closed = False

    def verify_ready(self, lock: object) -> None:
        self.ready_locks.append(lock)

    def transcribe(self, request, **_values: object) -> dict[str, object]:
        self.requests.append(request)
        return self.result

    def close(self) -> None:
        self.closed = True


class NemotronNemoBatchWorkerTests(unittest.TestCase):
    def test_publishes_a_checked_result_through_the_provider_worker_seam(self) -> None:
        lock = replace(
            _test_lock(),
            pool_id="nemotron-batch",
            engine="nemo",
            model_id="nvidia/nemotron-3.5-asr-streaming-0.6b",
            supported_languages=("auto", "en-US"),
            runtime_overlay_packages=(("nemo_toolkit", "3.1.0+test"),),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "input.wav"
            with wave.open(str(input_path), "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(16_000)
                output.writeframes(b"\0\0" * 1_600)
            input_sha256 = hashlib.sha256(input_path.read_bytes()).hexdigest()
            plan_path = root / "utterance-plan.json"
            plan_path.write_text("{}", encoding="utf-8")
            plan_sha256 = hashlib.sha256(plan_path.read_bytes()).hexdigest()
            result_path = root / "result.json"
            job = BatchAsrJob(
                job_id="job-1",
                input_path=input_path,
                result_path=result_path,
                language="en-US",
                input_sha256=input_sha256,
                route=AsrRouteDecision(
                    provider_id="nemotron",
                    pool_id=lock.pool_id,
                    execution_mode="fixedBatch",
                    model_revision=lock.model_revision,
                    provider_language="en-US",
                ),
                utterance_plan_path=plan_path,
                utterance_plan_sha256=plan_sha256,
            )
            result = {
                "schemaVersion": 1,
                "jobId": job.job_id,
                "model": {
                    "poolId": lock.pool_id,
                    "id": lock.model_id,
                    "revision": lock.model_revision,
                },
                "audio": {
                    "sha256": input_sha256,
                    "durationMs": 100,
                    "sampleRateHz": 16_000,
                },
                "transcript": {
                    "text": "hello",
                    "language": "en-US",
                    "punctuation": True,
                },
                "alignment": unavailable_alignment(
                    AlignmentUnavailableReason.RUNTIME_FAILED
                ),
                "runtime": {
                    "device": "cuda",
                    "dtype": "bfloat16",
                    "pythonVersion": "3.12.3",
                    "torchVersion": lock.runtime_torch_version,
                    "torchCudaVersion": lock.runtime_torch_cuda_version,
                    "overlayPackages": dict(lock.runtime_overlay_packages),
                },
            }
            client = _FakeClient(result)
            worker = NemotronNemoBatchWorker(lock=lock, client=client)

            worker.verify_ready()
            observed = worker.run(job, threading.Event())

            self.assertEqual(client.ready_locks, [lock])
            self.assertEqual(observed, result)
            self.assertEqual(len(client.requests), 1)
            request = client.requests[0]
            self.assertEqual(request.input_path, str(input_path.resolve()))
            self.assertEqual(request.utterance_plan_path, str(plan_path.resolve()))
            self.assertEqual(request.language, "en-US")
            self.assertEqual(
                json.loads(result_path.read_text(encoding="utf-8")),
                result,
            )

            worker.close()
            self.assertTrue(client.closed)


if __name__ == "__main__":
    unittest.main()
