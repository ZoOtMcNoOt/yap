from __future__ import annotations

import json
from pathlib import Path
import tomllib
import unittest

from yap_server.evaluation.transcript_scoring import (
    aggregate_private_transcript_scores,
    aggregate_transcript_scores,
    critical_token_set_sha256,
    current_scorer_lock,
    score_transcript,
)


def _score(
    reference: str,
    hypothesis: str,
    *,
    language_bcp47: str = "en",
    scoring_profile: str = "word-primary-v1",
    audio_duration_seconds: float | None = None,
    critical_tokens: list[str] | None = None,
    critical_token_set_sha256_value: str | None = None,
):
    return score_transcript(
        reference,
        hypothesis,
        language_bcp47=language_bcp47,
        scoring_profile=scoring_profile,
        audio_duration_seconds=audio_duration_seconds,
        critical_tokens=critical_tokens,
        critical_token_set_sha256=critical_token_set_sha256_value,
    )


class TranscriptScoringTests(unittest.TestCase):
    def test_english_uses_normalized_word_error_as_primary(self) -> None:
        score = _score(
            "Hello, STRASSE!",
            "hello strasse",
            language_bcp47="en-US",
        )

        self.assertEqual(score.primary_metric, "normalizedWordErrorRate")
        self.assertEqual(score.primary_value, 0.0)
        self.assertGreater(score.raw_grapheme.error_rate or 0.0, 0.0)

    def test_punctuation_is_scored_at_its_normalized_word_boundary(self) -> None:
        score = _score(
            "Start, infusion now.",
            "Start infusion, now.",
        )

        self.assertEqual(score.punctuation.reference_marks, 2)
        self.assertEqual(score.punctuation.hypothesis_marks, 2)
        self.assertEqual(score.punctuation.correct_marks, 1)
        self.assertEqual(score.punctuation.precision, 0.5)
        self.assertEqual(score.punctuation.recall, 0.5)
        self.assertEqual(score.punctuation.f1, 0.5)

    def test_punctuation_handles_empty_denominators_and_internal_apostrophes(
        self,
    ) -> None:
        equal = _score("don't stop", "don't stop")
        excess = _score("do not stop", "do not stop!")

        self.assertEqual(equal.punctuation.reference_marks, 0)
        self.assertEqual(equal.punctuation.hypothesis_marks, 0)
        self.assertIsNone(equal.punctuation.precision)
        self.assertIsNone(equal.punctuation.recall)
        self.assertIsNone(equal.punctuation.f1)
        self.assertEqual(excess.punctuation.excess_marks, 1)
        self.assertEqual(excess.punctuation.precision, 0.0)
        self.assertIsNone(excess.punctuation.recall)
        self.assertEqual(excess.punctuation.f1, 0.0)

    def test_punctuation_uses_aligned_boundaries_across_word_edits(self) -> None:
        leading_insertion = _score(
            "Start, infusion now.",
            "Well start, infusion now.",
        )
        middle_deletion = _score(
            "Start, the infusion now.",
            "Start, infusion now.",
        )

        self.assertEqual(leading_insertion.punctuation.correct_marks, 2)
        self.assertEqual(leading_insertion.punctuation.f1, 1.0)
        self.assertEqual(middle_deletion.punctuation.correct_marks, 2)
        self.assertEqual(middle_deletion.punctuation.f1, 1.0)

    def test_critical_tokens_preserve_medically_meaningful_internal_marks(
        self,
    ) -> None:
        policy = ["do not", "2.5 mg/dL", "COVID-19", "780G"]
        policy_sha256 = critical_token_set_sha256(policy)

        score = _score(
            "Do not give 2.5 mg/dL with COVID-19 on 780G.",
            "Give 2.5 mg/dl with covid 19 on 780G.",
            critical_tokens=policy,
            critical_token_set_sha256_value=policy_sha256,
        )

        self.assertIsNotNone(score.critical_tokens)
        assert score.critical_tokens is not None
        self.assertEqual(score.critical_tokens.token_set_sha256, policy_sha256)
        self.assertEqual(score.critical_tokens.reference_occurrences, 4)
        self.assertEqual(score.critical_tokens.hypothesis_occurrences, 2)
        self.assertEqual(score.critical_tokens.matched_occurrences, 2)
        self.assertEqual(score.critical_tokens.missed_occurrences, 2)
        self.assertEqual(score.critical_tokens.excess_occurrences, 0)
        self.assertEqual(score.critical_tokens.precision, 1.0)
        self.assertEqual(score.critical_tokens.recall, 0.5)
        self.assertAlmostEqual(score.critical_tokens.f1 or 0.0, 2 / 3)

        encoded = json.dumps(score.to_evidence(), sort_keys=True)
        self.assertNotIn("do not", encoded)
        self.assertNotIn("covid", encoded)
        self.assertNotIn(policy_sha256, encoded)
        self.assertIn(policy_sha256, json.dumps(score.to_private_evidence()))

    def test_critical_tokens_score_exact_case_and_acronym_surface_separately(
        self,
    ) -> None:
        policy = ["COVID-19", "MRI", "5 mg"]
        score = _score(
            "COVID-19 MRI dose: 5 mg.",
            "covid-19 mri dose: 5 MG.",
            critical_tokens=policy,
            critical_token_set_sha256_value=critical_token_set_sha256(policy),
        )

        assert score.critical_tokens is not None
        self.assertEqual(score.critical_tokens.matched_occurrences, 3)
        self.assertEqual(score.critical_tokens.f1, 1.0)
        self.assertEqual(
            score.critical_tokens.exact_surface.reference_occurrences,
            3,
        )
        self.assertEqual(
            score.critical_tokens.exact_surface.hypothesis_occurrences,
            3,
        )
        self.assertEqual(
            score.critical_tokens.exact_surface.reference_exact_occurrences,
            3,
        )
        self.assertEqual(
            score.critical_tokens.exact_surface.hypothesis_exact_occurrences,
            0,
        )
        self.assertEqual(
            score.critical_tokens.exact_surface.matched_occurrences,
            0,
        )
        self.assertEqual(score.critical_tokens.exact_surface.precision, 0.0)
        self.assertEqual(score.critical_tokens.exact_surface.recall, 0.0)
        self.assertEqual(score.critical_tokens.exact_surface.f1, 0.0)

    def test_critical_token_hash_and_policy_are_pinned_together(self) -> None:
        first_hash = critical_token_set_sha256(["COVID-19", "do not"])
        reordered_hash = critical_token_set_sha256([" do   not ", "COVID-19"])
        changed_surface_hash = critical_token_set_sha256(
            ["do not", "covid-19"]
        )

        self.assertEqual(first_hash, reordered_hash)
        self.assertNotEqual(first_hash, changed_surface_hash)
        with self.assertRaisesRegex(ValueError, "normalized duplicates"):
            critical_token_set_sha256(["COVID-19", "covid-19"])
        with self.assertRaisesRegex(ValueError, "invalid phrase"):
            critical_token_set_sha256(["\ud800"])
        with self.assertRaisesRegex(ValueError, "supplied together"):
            _score("do not", "do not", critical_tokens=["do not"])
        with self.assertRaisesRegex(ValueError, "pinned SHA-256"):
            _score(
                "do not",
                "do not",
                critical_tokens=["do not"],
                critical_token_set_sha256_value="0" * 64,
            )
        with self.assertRaisesRegex(ValueError, "silence scoring"):
            _score(
                "",
                "",
                language_bcp47="und",
                scoring_profile="silence-false-words-v1",
                audio_duration_seconds=30,
                critical_tokens=["do not"],
                critical_token_set_sha256_value=critical_token_set_sha256(
                    ["do not"]
                ),
            )

    def test_critical_tokens_use_boundaries_and_longest_multilingual_matches(
        self,
    ) -> None:
        policy = ["no", "chest pain", "pain", "心臓", "심장"]
        score = _score(
            "No chest pain during 心臓検査 and 심장검사.",
            "not chest pain during 心臓検査 and 심장검사.",
            critical_tokens=policy,
            critical_token_set_sha256_value=critical_token_set_sha256(policy),
        )

        assert score.critical_tokens is not None
        self.assertEqual(score.critical_tokens.reference_occurrences, 4)
        self.assertEqual(score.critical_tokens.hypothesis_occurrences, 3)
        self.assertEqual(score.critical_tokens.matched_occurrences, 3)
        self.assertEqual(score.critical_tokens.missed_occurrences, 1)

    def test_critical_token_order_detects_swapped_number_unit_pairs(self) -> None:
        policy = ["5 mg", "10 mL"]
        score = _score(
            "Give 5 mg then 10 mL.",
            "Give 10 mL then 5 mg.",
            critical_tokens=policy,
            critical_token_set_sha256_value=critical_token_set_sha256(policy),
        )

        assert score.critical_tokens is not None
        self.assertEqual(score.critical_tokens.f1, 1.0)
        self.assertEqual(
            score.critical_tokens.ordered_sequence.reference_units,
            2,
        )
        self.assertEqual(score.critical_tokens.ordered_sequence.error_rate, 1.0)

    def test_nfkc_normalization_is_explicit_and_does_not_replace_raw_scoring(
        self,
    ) -> None:
        score = _score("ＡＢＣ", "abc")

        self.assertEqual(score.normalized_word.error_rate, 0.0)
        self.assertEqual(score.normalized_grapheme.error_rate, 0.0)
        self.assertEqual(score.raw_word.error_rate, 1.0)

    def test_chinese_uses_grapheme_error_instead_of_one_whitespace_word(self) -> None:
        score = _score(
            "你好世界",
            "你好世",
            language_bcp47="zh-Hans",
            scoring_profile="grapheme-primary-v1",
        )

        self.assertEqual(score.primary_metric, "normalizedGraphemeErrorRate")
        self.assertEqual(score.normalized_grapheme.reference_units, 4)
        self.assertEqual(score.normalized_grapheme.deletions, 1)
        self.assertEqual(score.primary_value, 0.25)

    def test_japanese_canonical_combining_sequence_scores_as_equal(self) -> None:
        score = _score(
            "が",
            "か\u3099",
            language_bcp47="ja",
            scoring_profile="grapheme-primary-v1",
        )

        self.assertEqual(score.primary_metric, "normalizedGraphemeErrorRate")
        self.assertEqual(score.raw_grapheme.reference_units, 1)
        self.assertEqual(score.raw_grapheme.error_rate, 0.0)

    def test_extended_grapheme_cluster_is_not_split_at_zwj(self) -> None:
        score = _score(
            "医療👩‍⚕️",
            "医療",
            language_bcp47="ja",
            scoring_profile="grapheme-primary-v1",
        )

        self.assertEqual(score.normalized_grapheme.reference_units, 3)
        self.assertEqual(score.normalized_grapheme.deletions, 1)
        self.assertAlmostEqual(score.primary_value, 1 / 3)

    def test_mixed_script_profile_is_explicit_not_inferred_from_language(self) -> None:
        score = _score(
            "MRI検査を開始",
            "MRI検査を中止",
            language_bcp47="mul",
            scoring_profile="grapheme-primary-v1",
        )

        self.assertEqual(score.primary_metric, "normalizedGraphemeErrorRate")
        self.assertEqual(score.primary_value, 0.25)
        self.assertEqual(score.normalized_word.error_rate, 1.0)

    def test_edit_breakdown_reports_insertions_deletions_and_substitutions(
        self,
    ) -> None:
        inserted = _score("one two", "zero one two extra")
        deleted = _score("one two", "one")
        replaced = _score("one two", "one three")

        self.assertEqual(inserted.normalized_word.insertions, 2)
        self.assertEqual(deleted.normalized_word.deletions, 1)
        self.assertEqual(replaced.normalized_word.substitutions, 1)

    def test_empty_hypothesis_scores_as_all_deletions(self) -> None:
        score = _score("one two", "")

        self.assertEqual(score.normalized_word.deletions, 2)
        self.assertEqual(score.primary_value, 1.0)

    def test_zero_reference_uses_the_explicit_silence_profile(self) -> None:
        quiet = _score(
            "",
            "",
            language_bcp47="und",
            scoring_profile="silence-false-words-v1",
            audio_duration_seconds=30,
        )
        hallucinated = _score(
            "",
            "phantom words",
            language_bcp47="und",
            scoring_profile="silence-false-words-v1",
            audio_duration_seconds=30,
        )

        self.assertIsNone(quiet.normalized_word.error_rate)
        self.assertEqual(quiet.primary_metric, "falseWordsPerMinute")
        self.assertEqual(quiet.primary_value, 0.0)
        self.assertEqual(hallucinated.normalized_word.insertions, 2)
        self.assertEqual(hallucinated.primary_value, 4.0)

    def test_primary_reference_and_profile_must_be_valid(self) -> None:
        with self.assertRaisesRegex(ValueError, "primary reference"):
            _score("!!!", "")
        with self.assertRaisesRegex(ValueError, "silence reference"):
            _score(
                "speech",
                "speech",
                language_bcp47="und",
                scoring_profile="silence-false-words-v1",
                audio_duration_seconds=30,
            )
        with self.assertRaisesRegex(ValueError, "scoring profile"):
            _score("hello", "hello", scoring_profile="automatic")
        with self.assertRaisesRegex(ValueError, "exactly empty"):
            _score(
                "   ",
                "",
                language_bcp47="und",
                scoring_profile="silence-false-words-v1",
                audio_duration_seconds=30,
            )
        with self.assertRaisesRegex(ValueError, "und language"):
            _score(
                "",
                "",
                language_bcp47="en",
                scoring_profile="silence-false-words-v1",
                audio_duration_seconds=30,
            )

    def test_language_and_text_inputs_are_bounded(self) -> None:
        for language in (
            "",
            "english",
            "en_US",
            "en-" + "-".join(["abcdefgh"] * 8),
        ):
            with self.subTest(language=language):
                with self.assertRaisesRegex(ValueError, "language"):
                    _score("hello", "hello", language_bcp47=language)
        with self.assertRaisesRegex(ValueError, "canonical BCP 47"):
            _score("hello", "hello", language_bcp47="en-us")
        with self.assertRaisesRegex(ValueError, "NUL"):
            _score("hello\0", "hello")
        with self.assertRaisesRegex(ValueError, "byte bound"):
            _score("a" * (1024 * 1024 + 1), "a")
        with self.assertRaisesRegex(ValueError, "normalized-text bound"):
            _score("\ufdfa" * 127_101, "a", language_bcp47="ar")
        with self.assertRaisesRegex(ValueError, "work bound"):
            _score("a" * 120_001, "b" * 120_001)

    def test_evidence_contains_reproducible_versions_but_no_transcript_text(
        self,
    ) -> None:
        score = _score(
            "private patient reference",
            "private patient hypothesis",
            language_bcp47="en",
        )

        evidence = score.to_evidence()
        private_evidence = score.to_private_evidence()
        encoded = json.dumps(evidence, ensure_ascii=False, sort_keys=True)
        self.assertEqual(evidence["schemaVersion"], 2)
        self.assertEqual(evidence["privacyScope"], "public-redacted-case")
        self.assertNotIn("inputIdentity", evidence)
        self.assertEqual(private_evidence["privacyScope"], "private-case")
        self.assertEqual(
            private_evidence["inputIdentity"]["referenceSha256"],
            score.reference_sha256,
        )
        self.assertIn("unicodeVersion", evidence["scorer"])
        self.assertIn("regexVersion", evidence["scorer"])
        self.assertIn("rapidfuzzVersion", evidence["scorer"])
        self.assertIn("wordTokenization", evidence["scorer"])
        self.assertIn("graphemeTokenization", evidence["scorer"])
        self.assertEqual(
            evidence["scorer"]["punctuationProfile"],
            "unicode-word-boundary-v1",
        )
        self.assertEqual(
            evidence["scorer"]["criticalTokenProfile"],
            "normalized-and-exact-surface-longest-match-v2",
        )
        self.assertEqual(
            evidence["scorer"]["exactSurfaceProfile"],
            "nfc-case-and-punctuation-sensitive-v1",
        )
        self.assertEqual(evidence["scoringProfile"], "word-primary-v1")
        self.assertEqual(evidence["languageBcp47"], "en")
        self.assertRegex(evidence["scorer"]["sourceSha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(
            evidence["scorer"]["normalizerRevision"],
            "yap-unicode-normalizer-v1",
        )
        self.assertNotIn("private patient reference", encoded)
        self.assertNotIn("private patient hypothesis", encoded)

    def test_micro_aggregation_sums_edits_and_denominators(self) -> None:
        first = _score("one, two.", "one four.")
        second = _score("one two three!", "one two?")

        aggregate = aggregate_transcript_scores([first, second])

        self.assertEqual(aggregate["caseCount"], 2)
        self.assertEqual(aggregate["primaryMicroValue"], 0.4)
        self.assertAlmostEqual(aggregate["primaryMacroMean"], (0.5 + 1 / 3) / 2)
        self.assertEqual(
            aggregate["metrics"]["normalizedWord"]["referenceUnits"],
            5,
        )
        self.assertEqual(
            aggregate["metrics"]["punctuation"]["referenceMarks"],
            3,
        )
        self.assertEqual(
            aggregate["metrics"]["punctuation"]["hypothesisMarks"],
            2,
        )
        self.assertEqual(
            aggregate["metrics"]["punctuation"]["correctMarks"],
            1,
        )
        self.assertEqual(
            aggregate["metrics"]["punctuation"]["precision"],
            0.5,
        )
        self.assertAlmostEqual(
            aggregate["metrics"]["punctuation"]["recall"],
            1 / 3,
        )

    def test_critical_token_aggregation_requires_one_complete_policy(self) -> None:
        policy = ["do not"]
        policy_sha256 = critical_token_set_sha256(policy)
        scored = _score(
            "do not do not",
            "do not",
            critical_tokens=policy,
            critical_token_set_sha256_value=policy_sha256,
        )
        same_policy = _score(
            "ordinary words",
            "ordinary words",
            critical_tokens=policy,
            critical_token_set_sha256_value=policy_sha256,
        )
        unscored = _score("ordinary words", "ordinary words")
        other_policy = ["never"]
        different = _score(
            "never",
            "never",
            critical_tokens=other_policy,
            critical_token_set_sha256_value=critical_token_set_sha256(
                other_policy
            ),
        )

        aggregate = aggregate_transcript_scores([scored, same_policy])
        critical = aggregate["metrics"]["criticalTokens"]
        private_aggregate = aggregate_private_transcript_scores(
            [scored, same_policy]
        )

        self.assertEqual(critical["scoredCaseCount"], 2)
        self.assertEqual(critical["unscoredCaseCount"], 0)
        self.assertNotIn("tokenSetSha256", critical)
        self.assertEqual(
            private_aggregate["metrics"]["criticalTokens"]["tokenSetSha256"],
            policy_sha256,
        )
        self.assertEqual(critical["referenceOccurrences"], 2)
        self.assertEqual(critical["hypothesisOccurrences"], 1)
        self.assertEqual(critical["matchedOccurrences"], 1)
        self.assertEqual(critical["missedOccurrences"], 1)
        self.assertEqual(
            critical["exactSurface"]["referenceOccurrences"],
            2,
        )
        self.assertEqual(
            critical["exactSurface"]["matchedOccurrences"],
            1,
        )
        with self.assertRaisesRegex(ValueError, "every case"):
            aggregate_transcript_scores([scored, unscored])
        with self.assertRaisesRegex(ValueError, "one critical-token policy"):
            aggregate_transcript_scores([scored, different])

    def test_silence_aggregation_uses_total_duration_and_retains_false_words(
        self,
    ) -> None:
        quiet = _score(
            "",
            "",
            language_bcp47="und",
            scoring_profile="silence-false-words-v1",
            audio_duration_seconds=30,
        )
        hallucinated = _score(
            "",
            "phantom words",
            language_bcp47="und",
            scoring_profile="silence-false-words-v1",
            audio_duration_seconds=30,
        )

        aggregate = aggregate_transcript_scores([quiet, hallucinated])

        self.assertEqual(aggregate["primaryMicroValue"], 2.0)
        self.assertEqual(aggregate["audioDurationSeconds"], 60.0)
        self.assertEqual(
            aggregate["metrics"]["normalizedWord"]["zeroReferenceInsertions"],
            2,
        )

    def test_aggregation_does_not_mix_incompatible_scoring_profiles(self) -> None:
        word = _score("hello", "hello")
        grapheme = _score(
            "検査",
            "検査",
            language_bcp47="ja",
            scoring_profile="grapheme-primary-v1",
        )

        with self.assertRaisesRegex(ValueError, "one scoring profile"):
            aggregate_transcript_scores([word, grapheme])

    def test_evaluation_dependencies_are_exactly_pinned(self) -> None:
        server_root = Path(__file__).resolve().parents[2]
        with (server_root / "pyproject.toml").open("rb") as source:
            project = tomllib.load(source)

        self.assertEqual(
            set(project["project"]["optional-dependencies"]["evaluation"]),
            {"rapidfuzz==3.14.5", "regex==2026.7.10"},
        )

    def test_scorer_lock_freezes_the_complete_public_scorer_identity(self) -> None:
        lock = current_scorer_lock()

        self.assertEqual(lock["schemaVersion"], 2)
        self.assertEqual(lock["scorer"]["id"], "yap-transcript-scorer")
        self.assertEqual(lock["scorer"]["version"], 2)
        self.assertRegex(lock["scorer"]["sourceSha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(
            lock["scorer"]["criticalTokenProfile"],
            "normalized-and-exact-surface-longest-match-v2",
        )


if __name__ == "__main__":
    unittest.main()
