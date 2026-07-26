from __future__ import annotations

import json
from pathlib import Path
import struct
import tempfile
import unittest

from yap_server.evaluation.fleurs_cohere_comparator import (
    run_fleurs_cohere_comparator,
)
from yap_server.evaluation.fleurs_comparator_plan import (
    load_fleurs_cohere_comparator_plan,
)
from tests.evaluation.fleurs_fixture import (
    FLEURS_REVISION,
    build_fleurs_release,
    sha256_file,
)


SERVER_ROOT = Path(__file__).resolve().parents[2]
MODEL_LOCK_PATH = SERVER_ROOT / "model-pools.lock.json"
MODEL_ID = "CohereLabs/cohere-transcribe-03-2026"
MODEL_REVISION = "b1eacc2686a3d08ceaae5f24a88b1d519620bc09"


class _FakeCohereEngine:
    def __init__(self, *, wrong_route: bool = False) -> None:
        self.call_sizes: list[int] = []
        self.first_pcm: bytes | None = None
        self._wrong_route = wrong_route

    def transcribe_batch(self, requests: list[object]) -> list[dict[str, object]]:
        self.call_sizes.append(len(requests))
        if self.first_pcm is None:
            self.first_pcm = requests[0].audio.pcm_bytes
        results: list[dict[str, object]] = []
        for request in requests:
            index = int(request.job_id.rsplit("-", 1)[1])
            transcript = ("Uno.", "Dos.")[index]
            results.append(
                {
                    "schemaVersion": 1,
                    "jobId": request.job_id,
                    "model": {
                        "poolId": "cohere-batch",
                        "id": MODEL_ID,
                        "revision": MODEL_REVISION,
                    },
                    "audio": {
                        "sha256": request.audio.sha256,
                        "durationMs": request.audio.duration_ms,
                        "sampleRateHz": request.audio.sample_rate,
                    },
                    "transcript": {
                        "text": transcript,
                        "language": "fr" if self._wrong_route else request.language,
                        "punctuation": request.punctuation,
                    },
                    "runtime": {
                        "device": "cuda",
                        "deviceName": "fake GB10",
                        "computeCapability": [12, 1],
                        "pythonVersion": "3.12.13",
                        "torchVersion": "2.13.0a0+8145d630e8.nv26.06",
                        "torchCudaVersion": "13.3",
                        "overlayPackages": {
                            "audioread": "3.1.0",
                            "joblib": "1.5.3",
                            "lazy-loader": "0.5",
                            "librosa": "0.11.0",
                            "msgpack": "1.2.1",
                            "narwhals": "2.24.0",
                            "pooch": "1.9.0",
                            "scikit-learn": "1.9.0",
                            "sentencepiece": "0.2.1",
                            "soundfile": "0.14.0",
                            "soxr": "1.1.0",
                            "threadpoolctl": "3.6.0",
                            "tokenizers": "0.22.2",
                            "transformers": "5.13.1",
                        },
                        "dtype": "bfloat16",
                        "modelLoadMs": 1,
                        "batchSize": len(requests),
                        "inferenceMs": 1,
                    },
                }
            )
        return results


class FleursCohereComparatorTests(unittest.TestCase):
    def test_repository_plan_freezes_source_candidate_route_and_two_run_shapes(
        self,
    ) -> None:
        plan = load_fleurs_cohere_comparator_plan(
            SERVER_ROOT / "fleurs-cohere-comparator.plan.json"
        )

        self.assertEqual(
            plan.source_release_lock_sha256,
            sha256_file(SERVER_ROOT / "fleurs-es-419-test.lock.json"),
        )
        self.assertEqual(plan.model_lock_sha256, sha256_file(MODEL_LOCK_PATH))
        self.assertEqual(plan.evaluation_locale_bcp47, "es-419")
        self.assertEqual(plan.provider_language, "es")
        self.assertFalse(plan.promotion_eligible)
        self.assertEqual(plan.batch_size, 8)
        self.assertEqual(plan.warmup_cases, 1)
        self.assertEqual(
            [(selection.identifier, selection.case_count) for selection in plan.selections],
            [("screen", 20), ("full", 908)],
        )

    def test_screen_uses_one_warm_engine_and_writes_only_private_case_text(self) -> None:
        samples = (-1.0, -0.5, 0.0, 0.5, 1.0)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lock_path, archive_path, metadata_path = build_fleurs_release(
                root,
                first_samples=samples,
                second_samples=(0.0, 0.25),
            )
            plan_path = _write_plan(root, lock_path, case_count=2)
            result_dir = root / "results" / "screen-1"
            engine = _FakeCohereEngine()

            aggregate = run_fleurs_cohere_comparator(
                plan_path=plan_path,
                release_lock_path=lock_path,
                model_lock_path=MODEL_LOCK_PATH,
                archive_path=archive_path,
                metadata_path=metadata_path,
                selection_id="screen",
                result_dir=result_dir,
                engine=engine,
                environ={"YAP_EVAL_CACHE": temporary},
            )

            private = json.loads(
                (result_dir / "case-evidence.json").read_text(encoding="utf-8")
            )
            stored_aggregate = json.loads(
                (result_dir / "aggregate.json").read_text(encoding="utf-8")
            )

        self.assertEqual(engine.call_sizes, [1, 2])
        self.assertEqual(
            struct.unpack("<5h", engine.first_pcm),
            (-32768, -16384, 0, 16384, 32767),
        )
        self.assertEqual(aggregate, stored_aggregate)
        self.assertEqual(aggregate["source"]["caseCount"], 2)
        self.assertEqual(aggregate["route"]["evaluationLocaleBcp47"], "es-419")
        self.assertEqual(aggregate["route"]["providerLanguage"], "es")
        self.assertEqual(aggregate["quality"]["primaryMicroValue"], 0.0)
        self.assertEqual(
            set(aggregate["implementation"]["moduleSha256"]),
            {
                "fleurs_cohere_comparator",
                "fleurs_cohere_result",
                "fleurs_comparator_plan",
                "fleurs_corpus",
            },
        )
        self.assertNotIn("Uno", json.dumps(aggregate))
        self.assertNotIn("Dos", json.dumps(aggregate))
        self.assertEqual(
            [case["hypothesis"] for case in private["cases"]],
            ["Uno.", "Dos."],
        )
        self.assertEqual(
            [case["reference"] for case in private["cases"]],
            ["Uno.", "Dos."],
        )

    def test_result_contract_failure_discards_the_unpublished_run(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lock_path, archive_path, metadata_path = build_fleurs_release(root)
            plan_path = _write_plan(root, lock_path, case_count=2)
            result_dir = root / "results" / "bad-route"

            with self.assertRaisesRegex(ValueError, "provider language"):
                run_fleurs_cohere_comparator(
                    plan_path=plan_path,
                    release_lock_path=lock_path,
                    model_lock_path=MODEL_LOCK_PATH,
                    archive_path=archive_path,
                    metadata_path=metadata_path,
                    selection_id="screen",
                    result_dir=result_dir,
                    engine=_FakeCohereEngine(wrong_route=True),
                    environ={"YAP_EVAL_CACHE": temporary},
                )

            self.assertFalse(result_dir.exists())

    def test_source_lock_and_result_directory_are_bound_before_inference(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lock_path, archive_path, metadata_path = build_fleurs_release(root)
            plan_path = _write_plan(root, lock_path, case_count=2)
            lock_path.write_text(
                lock_path.read_text(encoding="utf-8") + "\n",
                encoding="utf-8",
            )
            engine = _FakeCohereEngine()

            with self.assertRaisesRegex(ValueError, "release lock"):
                run_fleurs_cohere_comparator(
                    plan_path=plan_path,
                    release_lock_path=lock_path,
                    model_lock_path=MODEL_LOCK_PATH,
                    archive_path=archive_path,
                    metadata_path=metadata_path,
                    selection_id="screen",
                    result_dir=root / "results" / "changed-source",
                    engine=engine,
                    environ={"YAP_EVAL_CACHE": temporary},
                )
            with self.assertRaisesRegex(ValueError, "inside YAP_EVAL_CACHE"):
                run_fleurs_cohere_comparator(
                    plan_path=plan_path,
                    release_lock_path=lock_path,
                    model_lock_path=MODEL_LOCK_PATH,
                    archive_path=archive_path,
                    metadata_path=metadata_path,
                    selection_id="screen",
                    result_dir=SERVER_ROOT / "changed-source",
                    engine=engine,
                    environ={"YAP_EVAL_CACHE": temporary},
                )

        self.assertEqual(engine.call_sizes, [])


def _write_plan(root: Path, release_lock_path: Path, *, case_count: int) -> Path:
    plan_path = root / "fleurs-cohere.plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "purpose": "locked-public-comparator",
                "promotionEligible": False,
                "exposureStatus": "unknown",
                "source": {
                    "releaseLockSha256": sha256_file(release_lock_path),
                    "datasetId": "google/fleurs",
                    "datasetRevision": FLEURS_REVISION,
                    "datasetConfig": "es_419",
                    "split": "test",
                    "evaluationLocaleBcp47": "es-419",
                },
                "candidate": {
                    "modelLockSha256": sha256_file(MODEL_LOCK_PATH),
                    "poolId": "cohere-batch",
                    "modelId": MODEL_ID,
                    "modelRevision": MODEL_REVISION,
                },
                "route": {"providerLanguage": "es", "punctuation": True},
                "execution": {
                    "batchSize": 8,
                    "warmupCases": 1,
                    "selections": [
                        {
                            "id": "screen",
                            "caseCount": case_count,
                            "selection": "metadata-prefix-v1",
                        },
                        {
                            "id": "full",
                            "caseCount": case_count,
                            "selection": "all-cases-v1",
                        },
                    ],
                },
                "scoring": {
                    "profile": "word-primary-v1",
                    "qualityDecision": "descriptive-baseline-only",
                    "promotionThresholds": None,
                },
                "privacy": {
                    "cacheEnvironment": "YAP_EVAL_CACHE",
                    "repositoryFallback": False,
                    "terminalOutput": "aggregate-only",
                    "caseEvidence": "private-only",
                },
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return plan_path


if __name__ == "__main__":
    unittest.main()
