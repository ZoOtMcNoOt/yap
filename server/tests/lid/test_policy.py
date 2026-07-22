from __future__ import annotations

import unittest

from yap_server.lid.policy import (
    LidObservation,
    SourceVadInterval,
    resolve_lid_suggestion,
    select_lid_probe_windows,
)


MINIMUM_SOURCE = 480_000
MAXIMUM_WINDOW = 240_000
MINIMUM_VOICED = 128_000


def _select(
    source_samples: int,
    intervals: tuple[SourceVadInterval, ...],
):
    return select_lid_probe_windows(
        source_samples=source_samples,
        vad_intervals=intervals,
        minimum_source_samples=MINIMUM_SOURCE,
        maximum_windows=2,
        maximum_window_samples=MAXIMUM_WINDOW,
        minimum_voiced_samples=MINIMUM_VOICED,
    )


def _observation(
    index: int,
    label: str,
    *,
    top_score: float = -0.2,
    score_margin: float = 1.0,
) -> LidObservation:
    return LidObservation(
        index=index,
        source_start_sample=index * 240_000,
        source_end_sample=(index + 1) * 240_000,
        raw_label=label,
        top_score=top_score,
        score_margin=score_margin,
    )


class LidProbeSelectionTests(unittest.TestCase):
    def test_recordings_below_30_seconds_do_not_run_assistive_lid(self) -> None:
        selection = _select(
            MINIMUM_SOURCE - 1,
            (SourceVadInterval(0, MINIMUM_SOURCE - 1),),
        )

        self.assertEqual(selection.status, "manual")
        self.assertEqual(selection.reason, "short_recording")
        self.assertEqual(selection.windows, ())

    def test_exactly_30_seconds_selects_two_disjoint_continuous_windows(self) -> None:
        selection = _select(
            MINIMUM_SOURCE,
            (SourceVadInterval(0, MINIMUM_SOURCE),),
        )

        self.assertEqual(selection.status, "selected")
        self.assertEqual(selection.reason, "two_probes_selected")
        self.assertEqual(len(selection.windows), 2)
        self.assertEqual(
            selection.windows[0].source_start_sample,
            0,
        )
        self.assertEqual(
            selection.windows[0].source_end_sample,
            MAXIMUM_WINDOW,
        )
        self.assertEqual(
            selection.windows[1].source_start_sample,
            MAXIMUM_WINDOW,
        )
        self.assertEqual(
            selection.windows[1].source_end_sample,
            MINIMUM_SOURCE,
        )
        self.assertLessEqual(
            selection.windows[0].source_end_sample,
            selection.windows[1].source_start_sample,
        )

    def test_uses_earliest_usable_speech_then_the_middle_nearest_window(self) -> None:
        source_samples = 1_600_000
        selection = _select(
            source_samples,
            (
                SourceVadInterval(10_000, 50_000),
                SourceVadInterval(100_000, 230_000),
                SourceVadInterval(700_000, 850_000),
                SourceVadInterval(1_300_000, 1_500_000),
            ),
        )

        self.assertEqual(selection.status, "selected")
        first, second = selection.windows
        self.assertEqual(first.source_start_sample, 10_000)
        self.assertEqual(first.voiced_samples, 170_000)
        self.assertEqual(second.source_start_sample, 680_000)
        self.assertEqual(second.voiced_samples, 150_000)

    def test_does_not_classify_when_two_usable_windows_cannot_be_proven(self) -> None:
        selection = _select(
            960_000,
            (SourceVadInterval(0, 160_000),),
        )

        self.assertEqual(selection.status, "manual")
        self.assertEqual(selection.reason, "second_probe_unavailable")
        self.assertEqual(selection.windows, ())

    def test_rejects_invalid_or_overlapping_vad_evidence(self) -> None:
        invalid = (
            (SourceVadInterval(20, 10),),
            (SourceVadInterval(0, 200_000), SourceVadInterval(199_999, 400_000)),
            (SourceVadInterval(0, 960_001),),
        )
        for intervals in invalid:
            with self.subTest(intervals=intervals):
                with self.assertRaises(ValueError):
                    _select(960_000, intervals)


class LidSuggestionResolutionTests(unittest.TestCase):
    def test_two_supported_mapped_labels_prefill_but_never_auto_confirm(self) -> None:
        decision = resolve_lid_suggestion(
            (
                _observation(0, "fr: French", top_score=-9.0, score_margin=0.0),
                _observation(1, "fr: French", top_score=-8.0, score_margin=0.0),
            ),
            enabled_fixed_locales=("en-US", "fr-FR"),
        )

        self.assertEqual(decision.status, "suggestion")
        self.assertEqual(decision.reason, "mapped_language_agreement")
        self.assertEqual(decision.suggested_locale, "fr-FR")
        self.assertTrue(decision.user_confirmation_required)

    def test_disagreement_unsupported_and_ambiguous_locales_open_manual_picker(
        self,
    ) -> None:
        cases = (
            (
                (_observation(0, "en: English"), _observation(1, "fr: French")),
                ("en-US", "fr-FR"),
                "language_disagreement",
            ),
            (
                (_observation(0, "el: Greek"), _observation(1, "el: Greek")),
                ("en-US",),
                "unsupported_language",
            ),
            (
                (_observation(0, "en: English"), _observation(1, "en: English")),
                ("en-GB", "en-US"),
                "ambiguous_locale",
            ),
        )
        for observations, locales, reason in cases:
            with self.subTest(reason=reason):
                decision = resolve_lid_suggestion(
                    observations,
                    enabled_fixed_locales=locales,
                )
                self.assertEqual(decision.status, "manual")
                self.assertEqual(decision.reason, reason)
                self.assertIsNone(decision.suggested_locale)
                self.assertTrue(decision.user_confirmation_required)

    def test_aliases_agree_but_an_invalid_label_or_missing_probe_fails_closed(
        self,
    ) -> None:
        aliased = resolve_lid_suggestion(
            (_observation(0, "iw: Hebrew"), _observation(1, "he: Hebrew")),
            enabled_fixed_locales=("he-IL",),
        )
        self.assertEqual(aliased.status, "suggestion")
        self.assertEqual(aliased.suggested_locale, "he-IL")

        invalid = resolve_lid_suggestion(
            (_observation(0, "not-a-model-label"), _observation(1, "he: Hebrew")),
            enabled_fixed_locales=("he-IL",),
        )
        self.assertEqual(invalid.status, "manual")
        self.assertEqual(invalid.reason, "invalid_model_label")

        missing = resolve_lid_suggestion(
            (_observation(0, "he: Hebrew"),),
            enabled_fixed_locales=("he-IL",),
        )
        self.assertEqual(missing.status, "manual")
        self.assertEqual(missing.reason, "two_probes_required")

    def test_rejects_invalid_score_evidence_instead_of_treating_it_as_confidence(
        self,
    ) -> None:
        with self.assertRaises(ValueError):
            resolve_lid_suggestion(
                (
                    _observation(0, "en: English", top_score=0.1),
                    _observation(1, "en: English"),
                ),
                enabled_fixed_locales=("en-US",),
            )


if __name__ == "__main__":
    unittest.main()
