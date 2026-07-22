from __future__ import annotations

import unittest

from yap_server.lid.policy import (
    LidObservation,
    SourceVadInterval,
    resolve_lid_suggestion,
    select_lid_probe_windows,
)


MINIMUM_SOURCE = 480_000
MAXIMUM_WINDOW = 96_000
MINIMUM_VOICED = 51_200
PROBE_COUNT = 5


def _select(
    source_samples: int,
    intervals: tuple[SourceVadInterval, ...],
):
    return select_lid_probe_windows(
        source_samples=source_samples,
        vad_intervals=intervals,
        minimum_source_samples=MINIMUM_SOURCE,
        maximum_windows=PROBE_COUNT,
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
        source_start_sample=index * MAXIMUM_WINDOW,
        source_end_sample=(index + 1) * MAXIMUM_WINDOW,
        raw_label=label,
        top_score=top_score,
        score_margin=score_margin,
    )


def _observations(label: str, **score_overrides: float) -> tuple[LidObservation, ...]:
    return tuple(
        _observation(index, label, **score_overrides)
        for index in range(PROBE_COUNT)
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

    def test_exactly_30_seconds_selects_five_contiguous_six_second_regions(
        self,
    ) -> None:
        selection = _select(
            MINIMUM_SOURCE,
            (SourceVadInterval(0, MINIMUM_SOURCE),),
        )

        self.assertEqual(selection.status, "selected")
        self.assertEqual(selection.reason, "five_stratified_probes_selected")
        self.assertEqual(len(selection.windows), PROBE_COUNT)
        self.assertEqual(
            [
                (window.source_start_sample, window.source_end_sample)
                for window in selection.windows
            ],
            [
                (0, 96_000),
                (96_000, 192_000),
                (192_000, 288_000),
                (288_000, 384_000),
                (384_000, 480_000),
            ],
        )

    def test_long_recording_regions_include_the_exact_tail(self) -> None:
        source_samples = 16_000 * 4 * 60 * 60
        selection = _select(
            source_samples,
            (SourceVadInterval(0, source_samples),),
        )

        starts = [window.source_start_sample for window in selection.windows]
        self.assertEqual(starts[0], 0)
        self.assertEqual(starts[-1], source_samples - MAXIMUM_WINDOW)
        self.assertEqual(starts, sorted(starts))
        self.assertTrue(
            all(
                first.source_end_sample <= second.source_start_sample
                for first, second in zip(selection.windows, selection.windows[1:])
            )
        )

    def test_any_region_without_enough_speech_fails_closed(self) -> None:
        selection = _select(
            MINIMUM_SOURCE,
            (
                SourceVadInterval(0, 192_000),
                SourceVadInterval(288_000, MINIMUM_SOURCE),
            ),
        )

        self.assertEqual(selection.status, "manual")
        self.assertEqual(selection.reason, "stratified_region_unavailable")
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
    def test_five_supported_mapped_labels_prefill_but_never_auto_confirm(
        self,
    ) -> None:
        decision = resolve_lid_suggestion(
            _observations("fr"),
            enabled_fixed_locales=("en-US", "fr-FR"),
        )

        self.assertEqual(decision.status, "suggestion")
        self.assertEqual(decision.reason, "mapped_language_agreement")
        self.assertEqual(decision.suggested_locale, "fr-FR")
        self.assertTrue(decision.user_confirmation_required)

    def test_one_disagreeing_tail_region_opens_the_manual_picker(self) -> None:
        observations = list(_observations("en"))
        observations[-1] = _observation(PROBE_COUNT - 1, "fr")

        decision = resolve_lid_suggestion(
            observations,
            enabled_fixed_locales=("en-US", "fr-FR"),
        )

        self.assertEqual(decision.status, "manual")
        self.assertEqual(decision.reason, "language_disagreement")
        self.assertIsNone(decision.suggested_locale)

    def test_unsupported_ambiguous_and_zero_margin_evidence_fail_closed(self) -> None:
        cases = (
            (_observations("el"), ("en-US",), "unsupported_language"),
            (_observations("en"), ("en-GB", "en-US"), "ambiguous_locale"),
            (
                _observations("en", score_margin=0.0),
                ("en-US",),
                "ambiguous_model_output",
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

    def test_aliases_normalize_at_the_model_boundary(self) -> None:
        observations = list(_observations("he"))
        observations[0] = _observation(0, "iw")
        decision = resolve_lid_suggestion(
            observations,
            enabled_fixed_locales=("he-IL",),
        )

        self.assertEqual(decision.status, "suggestion")
        self.assertEqual(decision.suggested_locale, "he-IL")

    def test_invalid_label_or_missing_region_fails_closed(self) -> None:
        invalid = list(_observations("he"))
        invalid[0] = _observation(0, "not-a-model-label")
        decision = resolve_lid_suggestion(
            invalid,
            enabled_fixed_locales=("he-IL",),
        )
        self.assertEqual(decision.reason, "invalid_model_label")

        missing = resolve_lid_suggestion(
            _observations("he")[:-1],
            enabled_fixed_locales=("he-IL",),
        )
        self.assertEqual(missing.reason, "five_probes_required")

    def test_rejects_invalid_score_evidence(self) -> None:
        observations = list(_observations("en"))
        observations[0] = _observation(0, "en", top_score=0.1)
        with self.assertRaises(ValueError):
            resolve_lid_suggestion(
                observations,
                enabled_fixed_locales=("en-US",),
            )


if __name__ == "__main__":
    unittest.main()
