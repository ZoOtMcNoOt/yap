from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

from yap_server.evaluation.provider_runtime_observations import (
    QualificationRequest,
)
from yap_server.evaluation.resident_provider_duration_qualification import (
    run_provider_duration_plan,
    select_provider_duration_plan,
)
from yap_server.evaluation.runtime_plan import load_runtime_evaluation_plan
from yap_server.pools.batch_contract import AsrRouteDecision, BatchAsrJob


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SERVER_ROOT = REPOSITORY_ROOT / "server"
PLAN_PATH = SERVER_ROOT / "asr-evaluation-plan.json"
CHECKED_HEAD = "a" * 40


class _Worker:
    def __init__(self, transcript: str = "private transcript") -> None:
        self.transcript = transcript

    def run(
        self,
        job: BatchAsrJob,
        _cancellation: threading.Event,
    ) -> dict[str, object]:
        result: dict[str, object] = {
            "jobId": job.job_id,
            "transcript": {"text": self.transcript},
            "runtime": {"queueMs": 1, "inferenceMs": 2, "batchSize": 1},
        }
        job.result_path.write_text(json.dumps(result), encoding="utf-8")
        return result


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
                input_sha256="b" * 64,
                route=AsrRouteDecision(
                    provider_id="cohere",
                    pool_id="cohere-batch",
                    execution_mode="fixedBatch",
                    model_revision="c" * 40,
                    provider_language="en",
                ),
            ),
            audio_samples=duration_samples,
        )


class ResidentProviderDurationQualificationTests(unittest.TestCase):
    def test_executes_the_batch_ladder_and_exact_maximum_once(self) -> None:
        plan = load_runtime_evaluation_plan(PLAN_PATH)
        selected = select_provider_duration_plan(
            plan,
            system_id="vllm-cohere-batch",
            ladder_id="batch-file",
            include_exact_maximum=True,
        )
        with tempfile.TemporaryDirectory() as temporary:
            qualification = run_provider_duration_plan(
                _Worker(),
                _Factory(Path(temporary)),
                selected,
                timeout_seconds_per_duration=1,
            )
            evidence = qualification.public_evidence()

        self.assertTrue(qualification.passed)
        self.assertEqual(len(qualification.runs), 8)
        self.assertEqual(
            qualification.runs[-1]["durationSamples"],
            230_400_000,
        )
        self.assertEqual(evidence["completedRequestCount"], 8)
        self.assertTrue(evidence["exactMaximumIncluded"])
        self.assertEqual(
            evidence["qualificationScope"],
            "duration-transport-and-lifecycle",
        )
        self.assertEqual(evidence["sourceEvidenceKind"], "natural-and-deterministic")
        self.assertIs(evidence["representativeAccuracyClaim"], False)
        encoded = json.dumps(evidence)
        self.assertNotIn("private transcript", encoded)
        self.assertRegex(str(evidence["evidenceSha256"]), r"^[0-9a-f]{64}$")

    def test_duration_transport_accepts_a_valid_empty_asr_result(self) -> None:
        selected = select_provider_duration_plan(
            load_runtime_evaluation_plan(PLAN_PATH),
            system_id="nemo-nemotron-finalized",
            ladder_id="server-finalized-utterance",
            include_exact_maximum=False,
        )
        with tempfile.TemporaryDirectory() as temporary:
            qualification = run_provider_duration_plan(
                _Worker(""),
                _Factory(Path(temporary)),
                selected,
                timeout_seconds_per_duration=1,
            )

        self.assertTrue(qualification.passed)
        self.assertEqual(len(qualification.runs), 9)
        self.assertTrue(
            all(run["outcomes"]["completed"] == 1 for run in qualification.runs)
        )
        self.assertTrue(
            all(run["nonemptyTranscriptCount"] == 0 for run in qualification.runs)
        )

    def test_rejects_a_ladder_or_maximum_outside_the_provider_contract(self) -> None:
        plan = load_runtime_evaluation_plan(PLAN_PATH)
        with self.assertRaisesRegex(ValueError, "does not include the resident provider"):
            select_provider_duration_plan(
                plan,
                system_id="vllm-cohere-batch",
                ladder_id="server-finalized-utterance",
                include_exact_maximum=False,
            )
        with self.assertRaisesRegex(ValueError, "exact maximum requires the batch ladder"):
            select_provider_duration_plan(
                plan,
                system_id="nemo-nemotron-finalized",
                ladder_id="server-finalized-utterance",
                include_exact_maximum=True,
            )

    def test_entrypoint_binds_suite_candidate_and_post_run_readback(self) -> None:
        from yap_server.evaluation import resident_provider_duration_qualification as module

        candidate = mock.Mock()
        suite = mock.Mock()
        suite.indexed_tracks_for.return_value = {480_000: mock.sentinel.track}
        qualification = mock.Mock(passed=True)
        qualification.public_evidence.return_value = {
            "schemaVersion": 1,
            "passed": True,
            "evidenceSha256": "0" * 64,
        }
        output_root = Path("C:/private/provider-duration")
        arguments = [
            "--plan",
            str(PLAN_PATH),
            "--checked-head",
            CHECKED_HEAD,
            "--repository-root",
            str(REPOSITORY_ROOT),
            "--system-id",
            "vllm-cohere-batch",
            "--duration-ladder",
            "batch-file",
            "--include-exact-maximum",
            "--model-lock",
            str(SERVER_ROOT / "cohere-vllm-serving.lock.json"),
            "--duration-suite",
            str(output_root / "suite.json"),
            "--duration-suite-sha256",
            "d" * 64,
            "--endpoint",
            "http://127.0.0.1:18000",
            "--catalog-language",
            "en",
            "--provider-language",
            "en",
            "--output-root",
            str(output_root),
            "--timeout-seconds-per-duration",
            "30",
        ]
        with (
            mock.patch.object(
                module,
                "admit_checked_candidate",
                return_value=candidate,
            ),
            mock.patch.object(
                module,
                "load_provider_duration_suite",
                return_value=suite,
            ) as load_suite,
            mock.patch.object(
                module,
                "run_resident_provider_duration_plan",
                return_value=qualification,
            ) as run,
            mock.patch.object(
                module,
                "verify_provider_duration_suite_unchanged",
            ) as verify_suite,
            mock.patch.object(
                module,
                "bind_provider_duration_suite",
                return_value={"schemaVersion": 1, "passed": True},
            ),
            mock.patch.object(
                module,
                "bind_checked_candidate_evidence",
                return_value={"schemaVersion": 1, "passed": True},
            ),
            mock.patch.object(module, "write_private_evidence") as write,
            redirect_stdout(io.StringIO()),
        ):
            exit_code = module.main(arguments)

        self.assertEqual(exit_code, 0)
        selected = select_provider_duration_plan(
            load_runtime_evaluation_plan(PLAN_PATH),
            system_id="vllm-cohere-batch",
            ladder_id="batch-file",
            include_exact_maximum=True,
        )
        load_suite.assert_called_once_with(
            suite_path=output_root / "suite.json",
            expected_sha256="d" * 64,
            plan_path=PLAN_PATH.resolve(strict=True),
            required_duration_samples=selected.duration_samples,
        )
        self.assertIs(run.call_args.kwargs["tracks"][480_000], mock.sentinel.track)
        verify_suite.assert_called_once_with(
            suite,
            duration_samples=selected.duration_samples,
            plan_path=PLAN_PATH.resolve(strict=True),
        )
        candidate.verify_unchanged.assert_called_once_with()
        write.assert_called_once_with(
            output_root / "evidence.json",
            {"schemaVersion": 1, "passed": True},
        )


if __name__ == "__main__":
    unittest.main()
