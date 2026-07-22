from __future__ import annotations

import json
from pathlib import Path
import tempfile
import threading
import unittest

from yap_server.evaluation.provider_language_parity_qualification import (
    run_provider_language_parity_case,
)
from yap_server.evaluation.provider_runtime_observations import QualificationRequest
from yap_server.evaluation.runtime_plan import load_runtime_evaluation_plan
from yap_server.language_span_contract import (
    ServerUtteranceLanguageObservation,
    build_server_language_span_evidence,
)
from yap_server.pools.batch_contract import AsrRouteDecision, BatchAsrJob
from yap_server.pools.model_lock import ModelPoolLock, load_model_pool_lock


SERVER_ROOT = Path(__file__).resolve().parents[2]


class _Factory:
    def __init__(self, root: Path, *, automatic: bool) -> None:
        self._root = root
        self._automatic = automatic

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
                result_path=self._root / f"result-c{concurrency}-{ordinal}.json",
                language="und" if self._automatic else "en-US",
                input_sha256="a" * 64,
                route=AsrRouteDecision(
                    provider_id="nemotron",
                    pool_id="nemotron-batch",
                    execution_mode=(
                        "dynamicBatch" if self._automatic else "fixedBatch"
                    ),
                    model_revision="b" * 40,
                    provider_language="auto" if self._automatic else "en-US",
                ),
                utterance_plan_path=self._root / "plan.json",
                utterance_plan_sha256="c" * 64,
            ),
            audio_samples=duration_samples,
        )


class _ParityWorker:
    def __init__(
        self,
        lock: ModelPoolLock,
        *,
        drift_automatic: bool = False,
        format_automatic: bool = False,
    ) -> None:
        self._lock = lock
        self._drift_automatic = drift_automatic
        self._format_automatic = format_automatic

    def verify_ready(self) -> None:
        return

    def close(self) -> None:
        return

    def run(
        self,
        job: BatchAsrJob,
        _cancellation: threading.Event,
    ) -> dict[str, object]:
        automatic = job.route.execution_mode == "dynamicBatch"
        text = "private transcript"
        if automatic and self._drift_automatic:
            text = "private transcript drift"
        elif automatic and self._format_automatic:
            text = "Private, transcript."
        transcript: dict[str, object] = {
            "text": text,
            "language": job.route.provider_language,
            "punctuation": True,
        }
        if automatic:
            segments = [
                {
                    "text": text,
                    "status": "detected",
                    "languageBcp47": "en-US",
                    "rawLanguageTag": "en-US",
                    "reason": None,
                    "sourceSpanIndex": 0,
                }
            ]
            transcript["languageSegments"] = segments
            transcript["languageSpanEvidence"] = build_server_language_span_evidence(
                source_end_sample=480_000,
                provider_id="nemotron",
                pool_id=self._lock.pool_id,
                model_id=self._lock.model_id,
                model_revision=self._lock.model_revision,
                utterance_plan_sha256="c" * 64,
                utterances=(
                    ServerUtteranceLanguageObservation(
                        start_sample=0,
                        end_sample=480_000,
                        language_segments=segments,
                    ),
                ),
            )
        result: dict[str, object] = {
            "jobId": job.job_id,
            "model": {
                "poolId": self._lock.pool_id,
                "id": self._lock.model_id,
                "revision": self._lock.model_revision,
            },
            "audio": {
                "sha256": job.input_sha256,
                "durationMs": 30_000,
                "sampleRateHz": 16_000,
            },
            "transcript": transcript,
        }
        job.result_path.write_text(json.dumps(result), encoding="utf-8")
        return result


class ProviderLanguageParityQualificationTests(unittest.TestCase):
    def test_requires_lexical_parity_and_distinct_language_contracts(self) -> None:
        plan = load_runtime_evaluation_plan(SERVER_ROOT / "asr-evaluation-plan.json")
        lock = load_model_pool_lock(SERVER_ROOT / "nemotron-nemo-serving.lock.json")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixed_root = root / "fixed"
            automatic_root = root / "automatic"
            fixed_root.mkdir()
            automatic_root.mkdir()
            qualification = run_provider_language_parity_case(
                _ParityWorker(lock),  # type: ignore[arg-type]
                _Factory(fixed_root, automatic=False),
                _Factory(automatic_root, automatic=True),
                plan,
                load_case_id="nemo-finalized-fixed-auto-parity",
                fixed_provider_language="en-US",
                lock=lock,
                timeout_seconds_per_wave=1,
            )
            evidence = qualification.public_evidence()

        self.assertTrue(qualification.passed)
        self.assertEqual([run["concurrency"] for run in evidence["runs"]], [1, 8])  # type: ignore[index]
        self.assertTrue(
            all(run["exactTextParityCount"] == 8 for run in evidence["runs"])  # type: ignore[index]
        )
        self.assertTrue(
            all(run["lexicalParityCount"] == 8 for run in evidence["runs"])  # type: ignore[index]
        )
        self.assertTrue(
            all(
                run["languageContractParityCount"] == 8
                for run in evidence["runs"]  # type: ignore[index]
            )
        )
        encoded = json.dumps(evidence)
        self.assertNotIn(str(root), encoded)
        self.assertNotIn("private transcript", encoded)

    def test_accepts_deterministic_casing_and_punctuation_differences(self) -> None:
        plan = load_runtime_evaluation_plan(SERVER_ROOT / "asr-evaluation-plan.json")
        lock = load_model_pool_lock(SERVER_ROOT / "nemotron-nemo-serving.lock.json")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixed_root = root / "fixed"
            automatic_root = root / "automatic"
            fixed_root.mkdir()
            automatic_root.mkdir()
            qualification = run_provider_language_parity_case(
                _ParityWorker(lock, format_automatic=True),  # type: ignore[arg-type]
                _Factory(fixed_root, automatic=False),
                _Factory(automatic_root, automatic=True),
                plan,
                load_case_id="nemo-finalized-fixed-auto-parity",
                fixed_provider_language="en-US",
                lock=lock,
                timeout_seconds_per_wave=1,
            )

        self.assertTrue(qualification.passed)
        self.assertTrue(
            all(run["exactTextParityCount"] == 0 for run in qualification.runs)
        )
        self.assertTrue(
            all(run["lexicalParityCount"] == 8 for run in qualification.runs)
        )

    def test_rejects_automatic_text_drift_even_when_both_modes_complete(self) -> None:
        plan = load_runtime_evaluation_plan(SERVER_ROOT / "asr-evaluation-plan.json")
        lock = load_model_pool_lock(SERVER_ROOT / "nemotron-nemo-serving.lock.json")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixed_root = root / "fixed"
            automatic_root = root / "automatic"
            fixed_root.mkdir()
            automatic_root.mkdir()
            qualification = run_provider_language_parity_case(
                _ParityWorker(lock, drift_automatic=True),  # type: ignore[arg-type]
                _Factory(fixed_root, automatic=False),
                _Factory(automatic_root, automatic=True),
                plan,
                load_case_id="nemo-finalized-fixed-auto-parity",
                fixed_provider_language="en-US",
                lock=lock,
                timeout_seconds_per_wave=1,
            )

        self.assertFalse(qualification.passed)
        self.assertTrue(
            all(run["lexicalParityCount"] == 0 for run in qualification.runs)
        )


if __name__ == "__main__":
    unittest.main()
