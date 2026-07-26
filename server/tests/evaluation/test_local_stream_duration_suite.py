from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from yap_server.evaluation import local_stream_duration_suite
from yap_server.evaluation.local_stream_duration_suite import (
    build_local_stream_duration_suite,
    select_local_stream_duration_cases,
)
from yap_server.evaluation.runtime_plan import load_runtime_evaluation_plan


SERVER_ROOT = Path(__file__).resolve().parents[2]
PLAN_PATH = SERVER_ROOT / "asr-evaluation-plan.json"


class LocalStreamDurationSuiteTests(unittest.TestCase):
    def test_selects_short_boundaries_without_duplicate_realtime_soak(self) -> None:
        cases = select_local_stream_duration_cases(
            load_runtime_evaluation_plan(PLAN_PATH),
            qualification_profile="short-boundaries",
        )

        self.assertEqual(len(cases), 9)
        self.assertEqual(cases[0].case_id, "live-endpoint-4000-samples")
        self.assertEqual(cases[4].duration_samples, 17_920)
        self.assertEqual(cases[8].case_id, "live-endpoint-480000-samples")

    def test_complete_profile_retains_both_local_ladders_in_frozen_order(
        self,
    ) -> None:
        cases = select_local_stream_duration_cases(
            load_runtime_evaluation_plan(PLAN_PATH),
            qualification_profile="complete-local-duration-ladders",
        )

        self.assertEqual(len(cases), 15)
        self.assertEqual(cases[9].case_id, "live-session-480000-samples")
        self.assertEqual(cases[-1].duration_samples, 115_200_000)

    def test_builder_binds_plan_track_hashes_order_and_text_expectations(self) -> None:
        captured: dict[str, object] = {}
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "local-stream-short-boundaries-v1"

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

            expected_text_case = "live-endpoint-4000-samples"
            with mock.patch.object(
                local_stream_duration_suite,
                "build_duration_track_collection",
                side_effect=fake_build_collection,
            ):
                result = build_local_stream_duration_suite(
                    source_paths=[Path("licensed-source.wav")],
                    expect_text_case_ids=frozenset({expected_text_case}),
                    qualification_profile="short-boundaries",
                    plan_path=PLAN_PATH,
                    environ={"YAP_EVAL_CACHE": str(Path(temporary) / "cache")},
                )

        manifest_bytes = captured["manifest_bytes"]
        self.assertIsInstance(manifest_bytes, bytes)
        suite = json.loads(manifest_bytes)
        tracks = captured["tracks"]
        self.assertEqual(
            captured["collection_id"],
            "local-stream-short-boundaries-v1",
        )
        self.assertEqual(captured["manifest_name"], "suite.json")
        self.assertEqual(
            set(suite),
            {
                "schemaVersion",
                "qualificationProfile",
                "planSha256",
                "cases",
            },
        )
        self.assertEqual(suite["schemaVersion"], 2)
        self.assertEqual(
            suite["qualificationProfile"],
            "short-boundaries",
        )
        self.assertNotIn("licensed-source.wav", manifest_bytes.decode("utf-8"))
        self.assertNotIn("transcript", manifest_bytes.decode("utf-8").lower())
        self.assertEqual(len(tracks), 9)  # type: ignore[arg-type]
        self.assertEqual(
            [case["caseId"] for case in suite["cases"]],
            [track.case_id for track in tracks],  # type: ignore[union-attr]
        )
        self.assertEqual(
            [case["expectText"] for case in suite["cases"]].count(True),
            1,
        )
        self.assertTrue(suite["cases"][0]["expectText"])
        self.assertEqual(
            suite["cases"][0]["trackManifestSha256"],
            hashlib.sha256(
                local_stream_duration_suite._canonical_json_bytes(
                    {
                        "schemaVersion": 1,
                        "caseId": expected_text_case,
                        "durationSamples": 4_000,
                    }
                )
            ).hexdigest(),
        )
        self.assertEqual(result.suite_path, destination / "suite.json")
        self.assertEqual(
            result.suite_sha256,
            hashlib.sha256(manifest_bytes).hexdigest(),
        )
        self.assertEqual(result.case_count, 9)
        self.assertEqual(
            result.qualification_profile,
            "short-boundaries",
        )

    def test_unknown_text_expectation_fails_before_track_creation(self) -> None:
        with mock.patch.object(
            local_stream_duration_suite,
            "build_duration_track_collection",
        ) as build_collection:
            with self.assertRaisesRegex(ValueError, "not in the local duration plan"):
                build_local_stream_duration_suite(
                    source_paths=[Path("licensed-source.wav")],
                    expect_text_case_ids=frozenset({"unknown-case"}),
                    qualification_profile="short-boundaries",
                    plan_path=PLAN_PATH,
                    environ={"YAP_EVAL_CACHE": "C:\\private"},
                )

        build_collection.assert_not_called()

    def test_unknown_qualification_profile_fails_before_track_creation(
        self,
    ) -> None:
        with mock.patch.object(
            local_stream_duration_suite,
            "build_duration_track_collection",
        ) as build_collection:
            with self.assertRaisesRegex(
                ValueError,
                "unsupported local duration qualification profile",
            ):
                build_local_stream_duration_suite(
                    source_paths=[Path("licensed-source.wav")],
                    qualification_profile="phase-six",
                    plan_path=PLAN_PATH,
                    environ={"YAP_EVAL_CACHE": "C:\\private"},
                )

        build_collection.assert_not_called()


if __name__ == "__main__":
    unittest.main()
