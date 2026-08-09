from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from yap_server.evaluation.meeting_acceptance_plan import (
    load_meeting_acceptance_plan,
)


SERVER_ROOT = Path(__file__).resolve().parents[2]
ACCEPTANCE_PLAN = SERVER_ROOT / "meeting-transcription-acceptance.json"


class MeetingAcceptancePlanTests(unittest.TestCase):
    def test_repository_plan_freezes_non_promotional_public_and_private_evidence(
        self,
    ) -> None:
        plan = load_meeting_acceptance_plan(ACCEPTANCE_PLAN)

        self.assertEqual(
            plan.runtime_lock_sha256,
            "a5eeedf04339d3d2e53cdc1ed3e695102494a6f3fd9cb7718f2b2f0c6b5cbdd6",
        )
        self.assertEqual(
            plan.public_comparator.revision,
            "500809d7e9ae643d3cc945f6c91e7ed0693456bd",
        )
        self.assertEqual(plan.public_comparator.exposure_status, "known-exposed")
        self.assertFalse(plan.public_comparator.promotion_eligible)
        self.assertEqual(
            plan.public_comparator.meeting_ids,
            (
                "ES2004a",
                "IS1009a",
                "TS3003a",
                "EN2002a",
                "Bmr013",
                "Bmr018",
                "Bro021",
                "MTG_32040",
                "MTG_32063",
                "MTG_32072",
                "MTG_32074",
                "MTG_32092",
                "MTG_32179",
                "MTG_32185",
                "MTG_32256",
                "MTG_32257",
                "MTG_32322",
            ),
        )
        self.assertEqual(plan.private_holdout.manifest_schema_version, 2)
        self.assertTrue(plan.private_holdout.sealed_before_hypotheses)
        self.assertTrue(plan.private_holdout.independent_promotion_required)
        self.assertFalse(plan.private_holdout.repository_fallback)
        self.assertEqual(plan.private_holdout.cache_environment, "YAP_EVAL_CACHE")
        self.assertEqual(plan.private_holdout.minimum_natural_meeting_count, 6)
        self.assertEqual(plan.private_holdout.minimum_natural_duration_seconds, 7_200)
        self.assertEqual(
            set(plan.evidence_classes),
            {"public-comparator", "independent-holdout", "constructed-controls"},
        )

    def test_plan_freezes_every_required_pressure_axis_and_scorer_policy(self) -> None:
        plan = load_meeting_acceptance_plan(ACCEPTANCE_PLAN)

        self.assertEqual(
            set(plan.pressure_axes),
            {
                "acoustic",
                "speech",
                "overlap",
                "attendance-roster",
                "speaking-roster",
                "window-roster",
                "transport",
                "duration",
                "language",
            },
        )
        self.assertIn("more-than-8-in-30-seconds", plan.pressure_axes["window-roster"])
        self.assertIn("two-hours", plan.pressure_axes["duration"])
        self.assertEqual(plan.scoring.diarization_collar_seconds, 0.0)
        self.assertTrue(plan.scoring.score_overlap)
        self.assertEqual(plan.scoring.speaker_mapping, "optimal-permutation")
        self.assertEqual(plan.scoring.timestamp_resolution_seconds, 0.02)
        self.assertEqual(plan.scoring.public_cpwer_scorer, "tiron-published-cpwer")
        self.assertEqual(plan.scoring.acceptance_cpwer_scorer, "meeteval-0.4.3")
        self.assertTrue(plan.promotion.require_every_mandatory_slice)
        self.assertTrue(plan.promotion.forbid_macro_compensation)
        self.assertGreater(plan.promotion.minimum_overlap_cpwer_improvement_percent, 0)
        self.assertEqual(plan.promotion.maximum_worker_memory_bytes, 17_179_869_184)
        self.assertEqual(
            plan.promotion.maximum_concurrent_eight_p95_realtime_factor, 0.5
        )

    def test_plan_rejects_public_promotion_missing_pressure_and_overlap_exclusion(
        self,
    ) -> None:
        payload = json.loads(ACCEPTANCE_PLAN.read_text(encoding="utf-8"))
        cases = (
            (
                ("evidence", "publicComparator", "promotionEligible"),
                True,
                "public comparator must remain non-promotional",
            ),
            (
                ("scoring", "scoreOverlap"),
                False,
                "overlap must remain scored",
            ),
        )
        for path, value, message in cases:
            with self.subTest(path=path):
                changed = deepcopy(payload)
                target = changed
                for segment in path[:-1]:
                    target = target[segment]
                target[path[-1]] = value
                with tempfile.TemporaryDirectory() as temporary:
                    plan_path = Path(temporary) / "plan.json"
                    plan_path.write_text(json.dumps(changed), encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, message):
                        load_meeting_acceptance_plan(plan_path)

        changed = deepcopy(payload)
        del changed["pressureAxes"]["overlap"]
        with tempfile.TemporaryDirectory() as temporary:
            plan_path = Path(temporary) / "plan.json"
            plan_path.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "pressure axes"):
                load_meeting_acceptance_plan(plan_path)

    def test_meeting_route_cannot_claim_general_promotion(self) -> None:
        payload = json.loads(ACCEPTANCE_PLAN.read_text(encoding="utf-8"))
        payload["promotion"]["allowedOutcomes"] = [
            "general-promotion",
            "narrow-route-promotion",
            "unadvertised-baseline",
        ]
        with tempfile.TemporaryDirectory() as temporary:
            plan_path = Path(temporary) / "plan.json"
            plan_path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "promotion outcomes"):
                load_meeting_acceptance_plan(plan_path)


if __name__ == "__main__":
    unittest.main()
