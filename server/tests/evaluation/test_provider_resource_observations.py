from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import tempfile
import unittest

from yap_server.evaluation.provider_resource_observations import (
    ProviderResourceSample,
    load_private_resource_samples,
    qualify_provider_resources,
    summarize_provider_resources,
)
from yap_server.evaluation.runtime_plan import (
    load_runtime_evaluation_plan,
    select_runtime_resource_profile,
)


SERVER_ROOT = Path(__file__).resolve().parents[2]
PLAN_PATH = SERVER_ROOT / "asr-evaluation-plan.json"


class ProviderResourceObservationTests(unittest.TestCase):
    def test_summarizes_private_cgroup_series_without_paths(self) -> None:
        samples = tuple(
            ProviderResourceSample(
                elapsed_ms=index * 1_000,
                memory_current_bytes=1_000_000 + min(index, 4) * 1_000,
                memory_peak_bytes=1_010_000 + min(index, 4) * 1_000,
                cgroup_anon_bytes=500_000 + min(index, 4) * 800,
                cgroup_file_bytes=300_000 + min(index, 4) * 100,
                cgroup_kernel_bytes=200_000 + min(index, 4) * 100,
                process_resident_bytes=410_000 + min(index, 4) * 800,
                process_resident_anon_bytes=300_000 + min(index, 4) * 800,
                process_resident_file_bytes=100_000,
                process_resident_shared_bytes=10_000,
                process_virtual_data_bytes=800_000 + min(index, 4) * 1_000,
                process_thread_count=5,
                memory_high_events=0,
                memory_max_events=0,
                memory_oom_events=0,
                memory_oom_kill_events=0,
                cpu_usage_usec=index * 400_000,
                task_count=3 + (index % 2),
            )
            for index in range(11)
        )

        evidence = summarize_provider_resources(
            samples,
            workload_start_ms=1_000,
            workload_end_ms=9_000,
        )

        self.assertEqual(evidence["observationBoundary"], "container-cgroup-v2")
        self.assertEqual(evidence["workloadSampleCount"], 9)
        self.assertEqual(evidence["memoryGrowthBytesDuringWorkload"], 3_000)
        self.assertEqual(
            evidence["tailMemoryTrend"]["endpointGrowthBytes"],  # type: ignore[index]
            0,
        )
        self.assertEqual(
            evidence["tailMemoryTrend"][  # type: ignore[index]
                "linearRegressionSlopeBytesPerMinute"
            ],
            0,
        )
        self.assertEqual(
            evidence["tailMemoryTrend"]["windowMedianGrowthBytes"],  # type: ignore[index]
            0,
        )
        self.assertEqual(evidence["cpu"]["averageCoreUtilization"], 0.4)  # type: ignore[index]
        self.assertEqual(
            evidence["memoryCompositionBytes"]["cgroupAnon"][  # type: ignore[index]
                "growthDuringWorkload"
            ],
            2_400,
        )
        self.assertEqual(
            evidence["containerEntrypointProcess"][  # type: ignore[index]
                "maximumThreadCount"
            ],
            5,
        )
        self.assertEqual(
            evidence["memoryEventsDuringWorkload"],
            {"high": 0, "max": 0, "oom": 0, "oomKill": 0},
        )
        self.assertNotIn("path", json.dumps(evidence).lower())

    def test_reports_positive_tail_growth_without_selecting_threshold(self) -> None:
        samples = tuple(
            ProviderResourceSample(
                elapsed_ms=index * 1_000,
                memory_current_bytes=2_000_000 + index * 10_000,
                memory_peak_bytes=2_000_000 + index * 10_000,
                cgroup_anon_bytes=1_000_000 + index * 5_000,
                cgroup_file_bytes=600_000 + index * 3_000,
                cgroup_kernel_bytes=400_000 + index * 2_000,
                process_resident_bytes=810_000 + index * 5_000,
                process_resident_anon_bytes=600_000 + index * 5_000,
                process_resident_file_bytes=200_000,
                process_resident_shared_bytes=10_000,
                process_virtual_data_bytes=1_600_000 + index * 5_000,
                process_thread_count=4,
                memory_high_events=index,
                memory_max_events=0,
                memory_oom_events=0,
                memory_oom_kill_events=0,
                cpu_usage_usec=index * 100_000,
                task_count=2,
            )
            for index in range(11)
        )

        evidence = summarize_provider_resources(
            samples,
            workload_start_ms=1_000,
            workload_end_ms=9_000,
        )

        self.assertEqual(
            evidence["tailMemoryTrend"][  # type: ignore[index]
                "linearRegressionSlopeBytesPerMinute"
            ],
            600_000,
        )
        self.assertEqual(
            evidence["tailMemoryTrend"]["windowMedianGrowthBytes"],  # type: ignore[index]
            40_000,
        )
        self.assertNotIn("passed", evidence)

    def test_applies_a_predeclared_resource_profile_without_content_evidence(
        self,
    ) -> None:
        samples = tuple(
            ProviderResourceSample(
                elapsed_ms=index * 1_000,
                memory_current_bytes=2_000_000 + min(index, 4) * 10_000,
                memory_peak_bytes=2_100_000,
                cgroup_anon_bytes=1_000_000 + min(index, 4) * 5_000,
                cgroup_file_bytes=600_000,
                cgroup_kernel_bytes=400_000,
                process_resident_bytes=810_000 + min(index, 4) * 5_000,
                process_resident_anon_bytes=600_000 + min(index, 4) * 5_000,
                process_resident_file_bytes=200_000,
                process_resident_shared_bytes=10_000,
                process_virtual_data_bytes=1_600_000 + min(index, 4) * 5_000,
                process_thread_count=4,
                memory_high_events=0,
                memory_max_events=0,
                memory_oom_events=0,
                memory_oom_kill_events=0,
                cpu_usage_usec=index * 100_000,
                task_count=8,
            )
            for index in range(11)
        )
        summary = summarize_provider_resources(
            samples,
            workload_start_ms=1_000,
            workload_end_ms=9_000,
        )
        profile = replace(
            select_runtime_resource_profile(
                load_runtime_evaluation_plan(PLAN_PATH),
                "vllm-cohere-batch",
            ),
            completed_request_count=8,
            concurrency=2,
            minimum_tail_duration_ms=4_000,
            minimum_tail_sample_count=5,
        )

        evidence = qualify_provider_resources(
            summary,
            profile=profile,
            completed_request_count=8,
            concurrency=2,
        )

        self.assertTrue(evidence["passed"])
        self.assertTrue(all(evidence["checks"].values()))  # type: ignore[union-attr]
        self.assertRegex(str(evidence["evidenceSha256"]), r"^[0-9a-f]{64}$")
        self.assertNotIn("transcript", json.dumps(evidence).lower())

        failed = qualify_provider_resources(
            summary,
            profile=replace(profile, maximum_memory_current_bytes=1),
            completed_request_count=8,
            concurrency=2,
        )
        self.assertFalse(failed["passed"])
        self.assertFalse(failed["checks"]["memoryCurrentCeiling"])  # type: ignore[index]

    def test_loads_strict_owner_private_json_lines(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory).resolve()
            samples_path = cache / "resources.jsonl"
            samples_path.write_text(
                "".join(
                    json.dumps(
                        {
                            "elapsedMs": index * 100,
                            "memoryCurrentBytes": 100 + index,
                            "memoryPeakBytes": 200 + index,
                            "cgroupAnonBytes": 40 + index,
                            "cgroupFileBytes": 30,
                            "cgroupKernelBytes": 30,
                            "processResidentBytes": 75 + index,
                            "processResidentAnonBytes": 45 + index,
                            "processResidentFileBytes": 20,
                            "processResidentSharedBytes": 10,
                            "processVirtualDataBytes": 300 + index,
                            "processThreadCount": 2,
                            "memoryHighEvents": 0,
                            "memoryMaxEvents": 0,
                            "memoryOomEvents": 0,
                            "memoryOomKillEvents": 0,
                            "cpuUsageUsec": index * 10,
                            "taskCount": 1,
                        }
                    )
                    + "\n"
                    for index in range(5)
                ),
                encoding="utf-8",
            )
            if os.name == "posix":
                os.chmod(cache, 0o700)
                os.chmod(samples_path, 0o600)

            loaded = load_private_resource_samples(
                samples_path,
                environ={"YAP_EVAL_CACHE": str(cache)},
            )

        self.assertEqual(len(loaded), 5)
        self.assertEqual(loaded[-1].elapsed_ms, 400)

    def test_rejects_nonmonotonic_or_incomplete_series(self) -> None:
        valid = [
            ProviderResourceSample(
                elapsed_ms=index * 1_000,
                memory_current_bytes=1_000,
                memory_peak_bytes=2_000,
                cgroup_anon_bytes=500,
                cgroup_file_bytes=300,
                cgroup_kernel_bytes=200,
                process_resident_bytes=410,
                process_resident_anon_bytes=300,
                process_resident_file_bytes=100,
                process_resident_shared_bytes=10,
                process_virtual_data_bytes=800,
                process_thread_count=3,
                memory_high_events=0,
                memory_max_events=0,
                memory_oom_events=0,
                memory_oom_kill_events=0,
                cpu_usage_usec=index * 100,
                task_count=1,
            )
            for index in range(5)
        ]
        nonmonotonic = [*valid]
        nonmonotonic[-1] = ProviderResourceSample(
            elapsed_ms=3_000,
            memory_current_bytes=1_000,
            memory_peak_bytes=2_000,
            cgroup_anon_bytes=500,
            cgroup_file_bytes=300,
            cgroup_kernel_bytes=200,
            process_resident_bytes=410,
            process_resident_anon_bytes=300,
            process_resident_file_bytes=100,
            process_resident_shared_bytes=10,
            process_virtual_data_bytes=800,
            process_thread_count=3,
            memory_high_events=0,
            memory_max_events=0,
            memory_oom_events=0,
            memory_oom_kill_events=0,
            cpu_usage_usec=500,
            task_count=1,
        )

        with self.assertRaisesRegex(ValueError, "not monotonic"):
            summarize_provider_resources(
                nonmonotonic,
                workload_start_ms=0,
                workload_end_ms=4_000,
            )
        with self.assertRaisesRegex(ValueError, "do not cover"):
            summarize_provider_resources(
                valid,
                workload_start_ms=1_000,
                workload_end_ms=10_000,
            )


if __name__ == "__main__":
    unittest.main()
