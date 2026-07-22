from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
import wave

from yap_server.pools.batch_contract import (
    AsrRouteDecision,
    BatchAsrJob,
    WorkerExecutionError,
)
from yap_server.pools.cohere_vllm_worker import CohereVllmBatchWorker

from .batch_asr_fixtures import test_lock as _test_lock


def _write_wav(path: Path) -> bytes:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16_000)
        output.writeframes(b"\x00\x00" * 1_600)
    return path.read_bytes()


class _FakeVllmClient:
    def __init__(self, transcript: str = "hello world") -> None:
        self.transcript = transcript
        self.ready_locks: list[object] = []
        self.requests: list[dict[str, object]] = []
        self.closed = False

    def verify_ready(self, lock: object) -> None:
        self.ready_locks.append(lock)

    def transcribe(self, **values: object) -> str:
        self.requests.append(values)
        return self.transcript

    def close(self) -> None:
        self.closed = True


class CohereVllmBatchWorkerTests(unittest.TestCase):
    def test_publishes_one_checked_cohere_result_through_the_batch_worker_seam(
        self,
    ) -> None:
        lock = replace(
            _test_lock(),
            runtime_image="nvcr.io/nvidia/vllm",
            runtime_overlay_packages=(
                ("transformers", "5.6.0"),
                ("vllm", "0.22.1+test"),
            ),
        )
        client = _FakeVllmClient(" hello\nworld ")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "speech.wav"
            encoded = _write_wav(input_path)
            digest = hashlib.sha256(encoded).hexdigest()
            result_path = root / "result.json"
            cancellation = threading.Event()
            job = BatchAsrJob(
                job_id="job-1",
                input_path=input_path,
                result_path=result_path,
                language="en",
                input_sha256=digest,
                route=AsrRouteDecision(
                    provider_id="cohere",
                    pool_id=lock.pool_id,
                    execution_mode="fixedBatch",
                    model_revision=lock.model_revision,
                    provider_language="en",
                ),
            )
            worker = CohereVllmBatchWorker(lock=lock, client=client)

            worker.verify_ready()
            result = worker.run(job, cancellation)

            self.assertEqual(client.ready_locks, [lock])
            self.assertEqual(len(client.requests), 1)
            request = client.requests[0]
            self.assertEqual(request["encoded_wav"], encoded)
            self.assertEqual(request["model"], lock.model_id)
            self.assertEqual(request["language"], "en")
            self.assertIs(request["cancellation"], cancellation)
            self.assertEqual(result["transcript"]["text"], "hello world")
            self.assertEqual(
                result["alignment"]["reason"],
                "ALIGNMENT_PROVIDER_UNSUPPORTED",
            )
            self.assertEqual(result["runtime"]["servingEngine"], "vllm")
            self.assertEqual(
                result["runtime"]["servingEngineVersion"],
                "0.22.1+test",
            )
            self.assertEqual(
                json.loads(result_path.read_text(encoding="utf-8")),
                result,
            )

        worker.close()
        self.assertTrue(client.closed)

    def test_fails_closed_for_punctuation_off_and_non_cohere_routes(self) -> None:
        lock = replace(
            _test_lock(),
            runtime_image="nvcr.io/nvidia/vllm",
            runtime_overlay_packages=(("vllm", "0.22.1+test"),),
        )
        client = _FakeVllmClient()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "speech.wav"
            encoded = _write_wav(input_path)
            digest = hashlib.sha256(encoded).hexdigest()
            job = BatchAsrJob(
                job_id="job-1",
                input_path=input_path,
                result_path=root / "result.json",
                language="en",
                input_sha256=digest,
                route=AsrRouteDecision(
                    provider_id="cohere",
                    pool_id=lock.pool_id,
                    execution_mode="fixedBatch",
                    model_revision=lock.model_revision,
                    provider_language="en",
                ),
                punctuation=False,
            )
            worker = CohereVllmBatchWorker(lock=lock, client=client)

            with self.assertRaisesRegex(WorkerExecutionError, "punctuation"):
                worker.run(job, threading.Event())

        nemotron_lock = replace(lock, pool_id="nemotron-batch")
        with self.assertRaisesRegex(ValueError, "Cohere"):
            CohereVllmBatchWorker(lock=nemotron_lock, client=client)


if __name__ == "__main__":
    unittest.main()
