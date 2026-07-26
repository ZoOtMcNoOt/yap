from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from yap_server.evaluation.runtime_plan import (
    load_runtime_evaluation_plan,
    plan_summary,
    select_runtime_load_case,
    select_runtime_resource_profile,
    validate_runtime_evaluation_plan,
)


SERVER_ROOT = Path(__file__).resolve().parents[2]
PLAN_PATH = SERVER_ROOT / "asr-evaluation-plan.json"


class RuntimeEvaluationPlanTests(unittest.TestCase):
    def test_selects_a_typed_provider_load_case(self) -> None:
        load = select_runtime_load_case(
            load_runtime_evaluation_plan(PLAN_PATH),
            "nemo-finalized-active-capacity",
        )

        self.assertEqual(load.system_id, "nemo-nemotron-finalized")
        self.assertEqual(load.concurrencies, (9,))
        self.assertEqual(load.minimum_completions, 8)
        self.assertEqual(load.mix[0].duration_samples, 14_400_000)

    def test_committed_plan_covers_duration_load_and_exact_boundaries(self) -> None:
        plan = load_runtime_evaluation_plan(PLAN_PATH)
        summary = plan_summary(PLAN_PATH)
        self.assertEqual(plan["schemaVersion"], 5)

        ladders = {
            item["id"]: item["durationSamples"]
            for item in plan["durationLadders"]  # type: ignore[union-attr]
        }
        boundaries = {
            item["id"]: item["values"]
            for item in plan["boundaryCases"]  # type: ignore[union-attr]
        }
        systems = {
            item["id"]: item
            for item in plan["systems"]  # type: ignore[union-attr]
        }
        boundary_expectations = {
            item["id"]: item["expected"]
            for item in plan["boundaryCases"]  # type: ignore[union-attr]
        }
        short_utterance_ladder = [
            4_000,
            8_000,
            12_000,
            16_000,
            17_920,
            32_000,
            80_000,
            160_000,
            480_000,
        ]
        self.assertEqual(ladders["live-endpoint"], short_utterance_ladder)
        self.assertEqual(
            ladders["server-finalized-utterance"],
            short_utterance_ladder,
        )
        self.assertEqual(
            ladders["batch-file"],
            [
                480_000,
                1_920_000,
                4_800_000,
                14_400_000,
                28_800_000,
                57_600_000,
                115_200_000,
            ],
        )
        self.assertEqual(boundaries["batch-maximum-exact"], [230_400_000])
        self.assertEqual(boundaries["batch-maximum-plus-one"], [230_400_001])
        self.assertEqual(
            boundary_expectations["vllm-concurrent-request-admission"],
            "independent-requests-use-vllm-continuous-batching",
        )
        self.assertEqual(
            boundaries["vllm-concurrent-request-admission"],
            [1, 2, 4, 8],
        )
        self.assertEqual(boundaries["worker-result-envelope"], [4_194_304, 4_194_305])
        self.assertEqual(
            systems["local-live-nemotron"]["measurementBoundary"],
            "desktop-prepared-audio-frame-to-final",
        )
        self.assertEqual(summary["systemCount"], 5)
        self.assertEqual(summary["durationLadderCount"], 4)
        self.assertEqual(summary["resourceProfileCount"], 2)
        self.assertRegex(summary["sha256"], r"^[0-9a-f]{64}$")
        self.assertTrue(
            all(
                system["terminologyContextSupport"] == "none"
                for system in systems.values()
                if system["status"] in {"executable", "reference"}
            )
        )

    def test_selects_frozen_gb10_resource_contracts(self) -> None:
        plan = load_runtime_evaluation_plan(PLAN_PATH)
        vllm = select_runtime_resource_profile(plan, "vllm-cohere-batch")
        nemo = select_runtime_resource_profile(plan, "nemo-nemotron-finalized")

        self.assertEqual(vllm.load_case_id, "vllm-short-tail")
        self.assertEqual(vllm.completed_request_count, 1_600)
        self.assertEqual(vllm.maximum_memory_current_bytes, 6 * 1024**3)
        self.assertEqual(vllm.maximum_container_entrypoint_thread_count, 128)
        self.assertEqual(nemo.load_case_id, "nemo-finalized-short-tail")
        self.assertEqual(
            nemo.maximum_container_entrypoint_virtual_data_bytes,
            14 * 1024**3,
        )
        self.assertEqual(
            nemo.maximum_absolute_tail_virtual_data_window_median_growth_bytes,
            64 * 1024**2,
        )

    def test_nemo_finalized_boundary_is_executable_without_claiming_live_transport(
        self,
    ) -> None:
        plan = load_runtime_evaluation_plan(PLAN_PATH)
        systems = {
            item["id"]: item
            for item in plan["systems"]  # type: ignore[union-attr]
        }

        nemo = systems["nemo-nemotron-finalized"]
        self.assertEqual(nemo["status"], "executable")
        self.assertEqual(
            nemo["mode"],
            "serverFinalizedUtterance",
        )
        self.assertEqual(
            nemo["measurementBoundary"],
            "resident-loopback-release-to-result",
        )
        self.assertEqual(nemo["terminologyContextSupport"], "none")

    def test_cancellation_cases_match_each_runtime_boundary(self) -> None:
        plan = load_runtime_evaluation_plan(PLAN_PATH)
        load_cases = {
            item["id"]: item
            for item in plan["loadCases"]  # type: ignore[union-attr]
        }
        cancellation = load_cases["vllm-cancelled-sibling"]

        self.assertEqual(
            cancellation["mix"],
            [
                {"durationSamples": 524_287, "count": 1},
                {"durationSamples": 262_144, "count": 1},
                {"durationSamples": 16_000, "count": 1},
            ],
        )
        self.assertEqual(cancellation["concurrencies"], [2])
        self.assertEqual(cancellation["minimumCompletions"], 2)
        self.assertEqual(
            cancellation["expected"],
            "cancel-dispatched-follower-record-server-outcome-leader-and-"
            "recovery-singletons",
        )
        nemotron_cancellation = load_cases[
            "nemotron-reference-cancelled-window"
        ]
        self.assertEqual(nemotron_cancellation["mix"], cancellation["mix"])
        self.assertEqual(nemotron_cancellation["concurrencies"], [2])
        native = load_cases["nemo-finalized-cancelled-sibling"]
        self.assertEqual(native["mix"], cancellation["mix"])
        self.assertEqual(native["concurrencies"], [2])
        self.assertEqual(
            native["expected"],
            "cancel-one-preserve-sibling-and-immediate-recovery",
        )

    def test_validator_rejects_a_weakened_cancellation_wave(self) -> None:
        plan = load_runtime_evaluation_plan(PLAN_PATH)
        changed = deepcopy(plan)
        load_cases = changed["loadCases"]
        cancellation = next(
            item
            for item in load_cases  # type: ignore[union-attr]
            if item["id"] == "vllm-cancelled-sibling"
        )
        cancellation["mix"][1]["count"] = 2

        with self.assertRaisesRegex(ValueError, "load cases"):
            validate_runtime_evaluation_plan(changed)

    def test_validator_freezes_every_load_case_shape(self) -> None:
        plan = load_runtime_evaluation_plan(PLAN_PATH)
        changed = deepcopy(plan)
        load_cases = changed["loadCases"]
        ordinary = next(
            item
            for item in load_cases  # type: ignore[union-attr]
            if item["id"] == "vllm-long-waves"
        )
        ordinary["concurrencies"] = [1, 2]

        with self.assertRaisesRegex(ValueError, "load cases"):
            validate_runtime_evaluation_plan(changed)

    def test_validator_fails_closed_if_a_required_duration_disappears(self) -> None:
        plan = load_runtime_evaluation_plan(PLAN_PATH)
        changed = deepcopy(plan)
        ladders = changed["durationLadders"]
        durations = ladders[3]["durationSamples"]  # type: ignore[index,union-attr]
        durations.remove(115_200_000)

        with self.assertRaisesRegex(ValueError, "duration ladders"):
            validate_runtime_evaluation_plan(changed)

    def test_validator_rejects_an_inflated_local_measurement_boundary(self) -> None:
        plan = load_runtime_evaluation_plan(PLAN_PATH)
        changed = deepcopy(plan)
        local = next(
            item
            for item in changed["systems"]  # type: ignore[union-attr]
            if item["id"] == "local-live-nemotron"
        )
        local["measurementBoundary"] = "desktop-microphone-to-final"

        with self.assertRaisesRegex(ValueError, "runtime systems"):
            validate_runtime_evaluation_plan(changed)

    def test_validator_rejects_a_batch_ladder_that_omits_nemotron(self) -> None:
        plan = load_runtime_evaluation_plan(PLAN_PATH)
        changed = deepcopy(plan)
        batch_ladder = changed["durationLadders"][3]  # type: ignore[index]
        batch_ladder["systemIds"].remove("transformers-nemotron-reference")

        with self.assertRaisesRegex(ValueError, "ladder systems"):
            validate_runtime_evaluation_plan(changed)

    def test_validator_rejects_a_batch_ladder_that_omits_native_nemo(self) -> None:
        plan = load_runtime_evaluation_plan(PLAN_PATH)
        changed = deepcopy(plan)
        batch_ladder = changed["durationLadders"][3]  # type: ignore[index]
        batch_ladder["systemIds"].remove("nemo-nemotron-finalized")

        with self.assertRaisesRegex(ValueError, "ladder systems"):
            validate_runtime_evaluation_plan(changed)

    def test_validator_rejects_a_weakened_boundary_expectation(self) -> None:
        plan = load_runtime_evaluation_plan(PLAN_PATH)
        changed = deepcopy(plan)
        boundaries = changed["boundaryCases"]
        singleton = next(
            item
            for item in boundaries  # type: ignore[union-attr]
            if item["id"] == "vllm-concurrent-request-admission"
        )
        singleton["expected"] = "some-batching"

        with self.assertRaisesRegex(ValueError, "boundary expectations"):
            validate_runtime_evaluation_plan(changed)

    def test_validator_rejects_duplicate_contract_entries(self) -> None:
        for field, error in (
            ("durationLadders", "duration ladder IDs must be unique"),
            ("boundaryCases", "boundary case IDs must be unique"),
        ):
            with self.subTest(field=field):
                changed = deepcopy(load_runtime_evaluation_plan(PLAN_PATH))
                entries = changed[field]
                entries.append(deepcopy(entries[0]))  # type: ignore[union-attr]

                with self.assertRaisesRegex(ValueError, error):
                    validate_runtime_evaluation_plan(changed)

        changed = deepcopy(load_runtime_evaluation_plan(PLAN_PATH))
        metrics = changed["requiredMetrics"]
        metrics.append(metrics[0])  # type: ignore[union-attr]
        with self.assertRaisesRegex(ValueError, "required metrics must be unique"):
            validate_runtime_evaluation_plan(changed)

    def test_validator_freezes_ladder_execution_and_boundary_units(self) -> None:
        changes = (
            ("durationLadders", 0, "pacing", "unpaced", "ladder execution"),
            (
                "durationLadders",
                0,
                "evidenceKind",
                "deterministic",
                "ladder execution",
            ),
            ("boundaryCases", 0, "unit", "seconds", "boundary units"),
        )
        for collection, index, field, value, error in changes:
            with self.subTest(field=field):
                changed = deepcopy(load_runtime_evaluation_plan(PLAN_PATH))
                changed[collection][index][field] = value  # type: ignore[index]

                with self.assertRaisesRegex(ValueError, error):
                    validate_runtime_evaluation_plan(changed)

    def test_loader_rejects_repository_fallback_and_oversized_input(self) -> None:
        plan = load_runtime_evaluation_plan(PLAN_PATH)
        plan["privateCache"]["repositoryFallback"] = True  # type: ignore[index]
        with self.assertRaisesRegex(ValueError, "outside the repository"):
            validate_runtime_evaluation_plan(plan)

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "plan.json"
            path.write_bytes(b" " * (64 * 1024 + 1))
            with self.assertRaisesRegex(ValueError, "size"):
                load_runtime_evaluation_plan(path)

    def test_manifest_contains_no_audio_paths_or_reference_text(self) -> None:
        raw = PLAN_PATH.read_text(encoding="utf-8")
        parsed = json.loads(raw)

        self.assertNotIn(".wav", raw.lower())
        self.assertNotIn("goldenTranscript", raw)
        self.assertEqual(parsed["privateCache"]["environment"], "YAP_EVAL_CACHE")


if __name__ == "__main__":
    unittest.main()
