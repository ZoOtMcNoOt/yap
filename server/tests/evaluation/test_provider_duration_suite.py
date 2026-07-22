from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from yap_server.evaluation import provider_duration_suite
from yap_server.evaluation.provider_duration_suite import (
    build_provider_duration_suite,
    select_provider_duration_requirements,
)
from yap_server.evaluation.runtime_plan import load_runtime_evaluation_plan


SERVER_ROOT = Path(__file__).resolve().parents[2]
PLAN_PATH = SERVER_ROOT / "asr-evaluation-plan.json"


class ProviderDurationSuiteTests(unittest.TestCase):
    def test_selects_every_resident_provider_duration_once(self) -> None:
        selection = select_provider_duration_requirements(
            load_runtime_evaluation_plan(PLAN_PATH)
        )

        self.assertEqual(
            [requirement.duration_samples for requirement in selection.tracks],
            [
                4_000,
                8_000,
                12_000,
                16_000,
                17_920,
                32_000,
                80_000,
                160_000,
                480_000,
                1_920_000,
                4_800_000,
                14_400_000,
                28_800_000,
                57_600_000,
                115_200_000,
                524_287,
                262_144,
                230_400_000,
            ],
        )
        self.assertEqual(selection.rejection_boundary_samples, (230_400_001,))
        thirty_seconds = next(
            requirement
            for requirement in selection.tracks
            if requirement.duration_samples == 480_000
        )
        self.assertIn("duration-ladder:server-finalized-utterance", thirty_seconds.required_by)
        self.assertIn("duration-ladder:batch-file", thirty_seconds.required_by)
        self.assertIn("load-case:vllm-short-tail", thirty_seconds.required_by)
        self.assertIn("load-case:nemo-finalized-short-tail", thirty_seconds.required_by)
        maximum = selection.tracks[-1]
        self.assertEqual(maximum.required_by, ("boundary-case:batch-maximum-exact",))

    def test_builder_binds_plan_track_hashes_and_requirement_provenance(self) -> None:
        captured: dict[str, object] = {}
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "resident-provider-duration-suite-v1"

            def fake_build_collection(**arguments: object) -> Path:
                captured.update(arguments)
                tracks = arguments["tracks"]
                manifests = {
                    track.case_id: {
                        "schemaVersion": 1,
                        "caseId": track.case_id,
                        "durationSamples": track.duration_samples,
                    }
                    for track in tracks  # type: ignore[union-attr]
                }
                manifest_name, manifest_bytes = arguments["manifest_factory"](
                    manifests
                )  # type: ignore[operator]
                captured["manifest_name"] = manifest_name
                captured["manifest_bytes"] = manifest_bytes
                return destination

            with mock.patch.object(
                provider_duration_suite,
                "build_duration_track_collection",
                side_effect=fake_build_collection,
            ):
                result = build_provider_duration_suite(
                    source_paths=[Path("licensed-source.wav")],
                    plan_path=PLAN_PATH,
                    environ={"YAP_EVAL_CACHE": str(Path(temporary) / "cache")},
                )

        manifest_bytes = captured["manifest_bytes"]
        self.assertIsInstance(manifest_bytes, bytes)
        suite = json.loads(manifest_bytes)
        tracks = captured["tracks"]
        self.assertEqual(captured["manifest_name"], "suite.json")
        self.assertEqual(
            set(suite),
            {
                "schemaVersion",
                "planSha256",
                "providerSystemIds",
                "rejectionBoundarySamples",
                "cases",
            },
        )
        serialized = manifest_bytes.decode("utf-8")
        self.assertNotIn("licensed-source.wav", serialized)
        self.assertNotIn("transcript", serialized.lower())
        self.assertEqual(len(tracks), 18)  # type: ignore[arg-type]
        self.assertEqual(
            [case["caseId"] for case in suite["cases"]],
            [track.case_id for track in tracks],  # type: ignore[union-attr]
        )
        self.assertEqual(
            suite["cases"][0]["trackManifestSha256"],
            hashlib.sha256(
                provider_duration_suite._canonical_json_bytes(
                    {
                        "schemaVersion": 1,
                        "caseId": "provider-duration-4000-samples",
                        "durationSamples": 4_000,
                    }
                )
            ).hexdigest(),
        )
        self.assertIn(
            "duration-ladder:server-finalized-utterance",
            suite["cases"][8]["requiredBy"],
        )
        self.assertEqual(result.suite_path, destination / "suite.json")
        self.assertEqual(
            result.suite_sha256,
            hashlib.sha256(manifest_bytes).hexdigest(),
        )
        self.assertEqual(result.track_count, 18)

    def test_selection_rejects_a_plan_without_the_exact_maximum_boundary(self) -> None:
        plan = load_runtime_evaluation_plan(PLAN_PATH)
        plan["boundaryCases"] = [
            case
            for case in plan["boundaryCases"]  # type: ignore[index]
            if case["id"] != "batch-maximum-exact"
        ]

        with self.assertRaisesRegex(ValueError, "exact batch maximum"):
            select_provider_duration_requirements(plan)

    def test_selection_rejects_a_malformed_boundary_collection_cleanly(self) -> None:
        plan = load_runtime_evaluation_plan(PLAN_PATH)
        plan["boundaryCases"] = None

        with self.assertRaisesRegex(ValueError, "batch maximum boundaries"):
            select_provider_duration_requirements(plan)


if __name__ == "__main__":
    unittest.main()
