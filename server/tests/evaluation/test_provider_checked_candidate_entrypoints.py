from __future__ import annotations

from contextlib import redirect_stdout
import io
from pathlib import Path
import unittest
from unittest import mock

from yap_server.evaluation import (
    provider_cancellation_qualification,
    provider_capacity_qualification,
    provider_language_parity_qualification,
    provider_resource_observations,
    provider_runtime_qualification,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SERVER_ROOT = REPOSITORY_ROOT / "server"
PLAN_PATH = SERVER_ROOT / "asr-evaluation-plan.json"
MODEL_LOCK_PATH = SERVER_ROOT / "model-pools.lock.json"
CHECKED_HEAD = "a" * 40


class ProviderCheckedCandidateEntrypointTests(unittest.TestCase):
    def test_every_provider_load_case_entrypoint_binds_a_checked_candidate(
        self,
    ) -> None:
        cases = (
            (
                provider_runtime_qualification,
                "run_resident_provider_load_case",
                [
                    "--timeout-seconds-per-wave",
                    "30",
                    "--concurrency",
                    "8",
                    "--repeat-count",
                    "8",
                ],
            ),
            (
                provider_capacity_qualification,
                "run_resident_provider_capacity_case",
                ["--timeout-seconds", "30"],
            ),
            (
                provider_cancellation_qualification,
                "run_resident_provider_cancellation_case",
                ["--timeout-seconds", "30"],
            ),
            (
                provider_language_parity_qualification,
                "run_resident_provider_language_parity_case",
                [
                    "--fixed-catalog-language",
                    "en-US",
                    "--fixed-provider-language",
                    "en-US",
                    "--automatic-catalog-language",
                    "und",
                    "--timeout-seconds-per-wave",
                    "30",
                ],
            ),
        )
        for module, run_name, extra_arguments in cases:
            with self.subTest(module=module.__name__):
                candidate = mock.Mock()
                output_root = Path("C:/private") / module.__name__.rsplit(".", 1)[-1]
                exact_tracks = {480_000: mock.sentinel.loaded_track}
                duration_tracks = mock.Mock(
                    manifest_paths=(output_root / "track.json",),
                )
                duration_tracks.indexed_tracks.return_value = exact_tracks
                qualification = mock.Mock(passed=True)
                qualification.public_evidence.return_value = {
                    "schemaVersion": 1,
                    "passed": True,
                    "evidenceSha256": "0" * 64,
                }
                arguments = [
                    "--plan",
                    str(PLAN_PATH),
                    "--checked-head",
                    CHECKED_HEAD,
                    "--repository-root",
                    str(REPOSITORY_ROOT),
                    "--load-case",
                    "test-case",
                    "--model-lock",
                    str(MODEL_LOCK_PATH),
                    "--duration-suite",
                    str(output_root / "suite.json"),
                    "--duration-suite-sha256",
                    "b" * 64,
                    "--endpoint",
                    "http://127.0.0.1:18000",
                    "--output-root",
                    str(output_root),
                    *extra_arguments,
                ]
                if module is not provider_language_parity_qualification:
                    arguments.extend(
                        [
                            "--catalog-language",
                            "en",
                            "--provider-language",
                            "en",
                        ]
                    )

                with (
                    mock.patch.object(
                        module,
                        "admit_checked_candidate",
                        return_value=candidate,
                    ) as admit,
                    mock.patch.object(
                        module,
                        run_name,
                        return_value=qualification,
                    ) as run,
                    mock.patch.object(
                        module,
                        "load_provider_load_case_tracks",
                        return_value=duration_tracks,
                    ) as load_tracks,
                    mock.patch.object(
                        module,
                        "bind_provider_load_case_tracks",
                        return_value={
                            "schemaVersion": 1,
                            "passed": True,
                            "durationSuite": {"sha256": "b" * 64},
                        },
                    ) as bind_tracks,
                    mock.patch.object(
                        module,
                        "verify_provider_load_case_tracks_unchanged",
                    ) as verify_tracks,
                    mock.patch.object(
                        module,
                        "bind_checked_candidate_evidence",
                        return_value={"schemaVersion": 1, "passed": True},
                    ) as bind,
                    mock.patch.object(module, "write_private_evidence") as write,
                    redirect_stdout(io.StringIO()),
                ):
                    exit_code = module.main(arguments)

                self.assertEqual(exit_code, 0)
                admit.assert_called_once_with(
                    repository_root=REPOSITORY_ROOT,
                    checked_head=CHECKED_HEAD,
                    input_paths=(
                        PLAN_PATH.resolve(strict=True),
                        MODEL_LOCK_PATH.resolve(strict=True),
                    ),
                )
                candidate.verify_unchanged.assert_called_once_with()
                duration_tracks.indexed_tracks.assert_called_once_with()
                self.assertIs(run.call_args.kwargs["tracks"], exact_tracks)
                if module is provider_runtime_qualification:
                    self.assertEqual(
                        run.call_args.kwargs["selected_concurrencies"],
                        (8,),
                    )
                    self.assertEqual(run.call_args.kwargs["repeat_count"], 8)
                load_tracks.assert_called_once_with(
                    suite_path=output_root / "suite.json",
                    expected_suite_sha256="b" * 64,
                    plan_path=PLAN_PATH.resolve(strict=True),
                    load_case_id="test-case",
                )
                verify_tracks.assert_called_once_with(
                    duration_tracks,
                    plan_path=PLAN_PATH.resolve(strict=True),
                )
                bind_tracks.assert_called_once_with(
                    qualification.public_evidence.return_value,
                    duration_tracks,
                )
                bind.assert_called_once_with(
                    {
                        "schemaVersion": 1,
                        "passed": True,
                        "durationSuite": {"sha256": "b" * 64},
                    },
                    candidate,
                )
                write.assert_called_once_with(
                    output_root / "evidence.json",
                    {"schemaVersion": 1, "passed": True},
                )

    def test_resource_qualification_binds_the_same_checked_candidate(self) -> None:
        candidate = mock.Mock()
        output = Path("C:/private/resources/evidence.json")
        with (
            mock.patch.object(
                provider_resource_observations,
                "admit_checked_candidate",
                return_value=candidate,
            ) as admit,
            mock.patch.object(
                provider_resource_observations,
                "_private_cache_root",
                return_value=Path("C:/private"),
            ),
            mock.patch.object(
                provider_resource_observations,
                "load_private_resource_samples",
                return_value=(),
            ),
            mock.patch.object(
                provider_resource_observations,
                "summarize_provider_resources",
                return_value={"schemaVersion": 1},
            ),
            mock.patch.object(
                provider_resource_observations,
                "load_runtime_evaluation_plan",
                return_value={},
            ),
            mock.patch.object(
                provider_resource_observations,
                "select_runtime_resource_profile",
                return_value=object(),
            ),
            mock.patch.object(
                provider_resource_observations,
                "qualify_provider_resources",
                return_value={"schemaVersion": 1, "passed": True},
            ),
            mock.patch.object(
                provider_resource_observations,
                "bind_checked_candidate_evidence",
                return_value={"schemaVersion": 1, "passed": True},
            ) as bind,
            mock.patch.object(
                provider_resource_observations,
                "_private_output",
                return_value=output,
            ),
            mock.patch.object(
                provider_resource_observations,
                "write_private_evidence",
            ) as write,
            redirect_stdout(io.StringIO()),
        ):
            exit_code = provider_resource_observations.main(
                [
                    "--samples",
                    "C:/private/resources.jsonl",
                    "--workload-start-ms",
                    "1000",
                    "--workload-end-ms",
                    "2000",
                    "--output",
                    str(output),
                    "--plan",
                    str(PLAN_PATH),
                    "--system-id",
                    "vllm-cohere-batch",
                    "--completed-request-count",
                    "1600",
                    "--concurrency",
                    "8",
                    "--checked-head",
                    CHECKED_HEAD,
                    "--repository-root",
                    str(REPOSITORY_ROOT),
                    "--provider-serving-lock",
                    str(SERVER_ROOT / "cohere-vllm-serving.lock.json"),
                ]
            )

        self.assertEqual(exit_code, 0)
        admit.assert_called_once_with(
            repository_root=REPOSITORY_ROOT,
            checked_head=CHECKED_HEAD,
            input_paths=(
                PLAN_PATH.resolve(strict=True),
                (SERVER_ROOT / "cohere-vllm-serving.lock.json").resolve(strict=True),
            ),
        )
        candidate.verify_unchanged.assert_called_once_with()
        bind.assert_called_once_with(
            {"schemaVersion": 1, "passed": True},
            candidate,
        )
        write.assert_called_once_with(
            output,
            {"schemaVersion": 1, "passed": True},
        )


if __name__ == "__main__":
    unittest.main()
