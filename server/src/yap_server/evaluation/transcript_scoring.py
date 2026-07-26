from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import hashlib
import hmac
import json
import math
from pathlib import Path
import unicodedata

import rapidfuzz
from rapidfuzz.distance import Levenshtein
import regex

from yap_server.language_tags import canonical_bcp47


_MAX_TEXT_BYTES = 1024 * 1024
_MAX_DERIVED_TEXT_BYTES = 4 * _MAX_TEXT_BYTES
_MAX_UNITS = 250_000
_MAX_ALIGNMENT_BLOCK_WORK = 200_000_000
_MAX_TOTAL_ALIGNMENT_BLOCK_WORK = 250_000_000
_MAX_AGGREGATE_CASES = 100_000
_MAX_AUDIO_DURATION_SECONDS = 4 * 60 * 60
_MAX_CRITICAL_TOKEN_SET_BYTES = 512 * 1024
_MAX_CRITICAL_TOKEN_PHRASES = 4_096
_MAX_CRITICAL_TOKEN_PHRASE_BYTES = 512
_MAX_CRITICAL_TOKEN_PHRASE_GRAPHEMES = 64
_MAX_CRITICAL_TEXT_GRAPHEMES = 2 * _MAX_UNITS + 1
_SCORER_REVISION = "yap-transcript-scorer-v2"
_NORMALIZER_REVISION = "yap-unicode-normalizer-v1"
_PUNCTUATION_PROFILE = "unicode-word-boundary-v1"
_CRITICAL_TOKEN_PROFILE = "normalized-and-exact-surface-longest-match-v2"
_EXACT_SURFACE_PROFILE = "nfc-case-and-punctuation-sensitive-v1"
_SCORER_SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_SCORING_PROFILES = frozenset(
    {
        "word-primary-v1",
        "grapheme-primary-v1",
        "silence-false-words-v1",
    }
)
_WORD_TOKEN = regex.compile(
    r"[\p{Alphabetic}\p{M}\p{Nd}]+(?:['’][\p{Alphabetic}\p{M}\p{Nd}]+)*",
    flags=regex.VERSION1,
)
_GRAPHEME = regex.compile(r"\X", flags=regex.VERSION1)
_WORDLIKE_GRAPHEME = regex.compile(
    r"[\p{Alphabetic}\p{M}\p{Nd}]",
    flags=regex.VERSION1,
)
_BOUNDARYLESS_GRAPHEME = regex.compile(
    r"[\p{Han}\p{Hiragana}\p{Katakana}\p{Hangul}\p{Thai}\p{Lao}"
    r"\p{Khmer}\p{Myanmar}]",
    flags=regex.VERSION1,
)
_SHA256 = regex.compile(r"[0-9a-f]{64}", flags=regex.VERSION1)


@dataclass(frozen=True, slots=True)
class EditScore:
    reference_units: int
    hypothesis_units: int
    insertions: int
    deletions: int
    substitutions: int
    error_rate: float | None

    @property
    def errors(self) -> int:
        return self.insertions + self.deletions + self.substitutions

    def to_evidence(self) -> dict[str, object]:
        return {
            "referenceUnits": self.reference_units,
            "hypothesisUnits": self.hypothesis_units,
            "insertions": self.insertions,
            "deletions": self.deletions,
            "substitutions": self.substitutions,
            "errors": self.errors,
            "errorRate": self.error_rate,
        }


@dataclass(frozen=True, slots=True)
class PunctuationScore:
    reference_marks: int
    hypothesis_marks: int
    correct_marks: int
    precision: float | None
    recall: float | None
    f1: float | None

    @property
    def missing_marks(self) -> int:
        return self.reference_marks - self.correct_marks

    @property
    def excess_marks(self) -> int:
        return self.hypothesis_marks - self.correct_marks

    def to_evidence(self) -> dict[str, object]:
        return {
            "profile": _PUNCTUATION_PROFILE,
            "referenceMarks": self.reference_marks,
            "hypothesisMarks": self.hypothesis_marks,
            "correctMarks": self.correct_marks,
            "missingMarks": self.missing_marks,
            "excessMarks": self.excess_marks,
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
        }


@dataclass(frozen=True, slots=True)
class ExactSurfaceScore:
    reference_occurrences: int
    hypothesis_occurrences: int
    reference_exact_occurrences: int
    hypothesis_exact_occurrences: int
    matched_occurrences: int
    precision: float | None
    recall: float | None
    f1: float | None

    @property
    def missed_occurrences(self) -> int:
        return self.reference_occurrences - self.matched_occurrences

    @property
    def excess_occurrences(self) -> int:
        return self.hypothesis_occurrences - self.matched_occurrences

    def to_evidence(self) -> dict[str, object]:
        return {
            "profile": _EXACT_SURFACE_PROFILE,
            "referenceOccurrences": self.reference_occurrences,
            "hypothesisOccurrences": self.hypothesis_occurrences,
            "referenceExactOccurrences": self.reference_exact_occurrences,
            "hypothesisExactOccurrences": self.hypothesis_exact_occurrences,
            "matchedOccurrences": self.matched_occurrences,
            "missedOccurrences": self.missed_occurrences,
            "unmatchedHypothesisOccurrences": self.excess_occurrences,
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
        }


@dataclass(frozen=True, slots=True)
class CriticalTokenScore:
    token_set_sha256: str
    reference_occurrences: int
    hypothesis_occurrences: int
    matched_occurrences: int
    ordered_sequence: EditScore
    exact_surface: ExactSurfaceScore
    precision: float | None
    recall: float | None
    f1: float | None

    @property
    def missed_occurrences(self) -> int:
        return self.reference_occurrences - self.matched_occurrences

    @property
    def excess_occurrences(self) -> int:
        return self.hypothesis_occurrences - self.matched_occurrences

    def to_evidence(
        self,
        *,
        include_private_identity: bool = False,
    ) -> dict[str, object]:
        evidence: dict[str, object] = {
            "profile": _CRITICAL_TOKEN_PROFILE,
            "referenceOccurrences": self.reference_occurrences,
            "hypothesisOccurrences": self.hypothesis_occurrences,
            "matchedOccurrences": self.matched_occurrences,
            "missedOccurrences": self.missed_occurrences,
            "excessOccurrences": self.excess_occurrences,
            "orderedSequence": self.ordered_sequence.to_evidence(),
            "exactSurface": self.exact_surface.to_evidence(),
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
        }
        if include_private_identity:
            evidence["tokenSetSha256"] = self.token_set_sha256
        return evidence


@dataclass(frozen=True, slots=True)
class _CriticalPhrase:
    normalized: tuple[str, ...]
    surface: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _CriticalTokenPolicy:
    token_set_sha256: str
    phrases: tuple[_CriticalPhrase, ...]


@dataclass(slots=True)
class _CriticalTrieNode:
    children: dict[str, _CriticalTrieNode] = field(default_factory=dict)
    matched_phrase: tuple[str, ...] | None = None
    identity: tuple[str, ...] | None = None


@dataclass(frozen=True, slots=True)
class TranscriptScore:
    language_bcp47: str
    scoring_profile: str
    primary_metric: str
    primary_value: float
    audio_duration_seconds: float | None
    reference_sha256: str
    hypothesis_sha256: str
    punctuation: PunctuationScore
    critical_tokens: CriticalTokenScore | None
    raw_word: EditScore
    normalized_word: EditScore
    raw_grapheme: EditScore
    normalized_grapheme: EditScore

    @property
    def primary_error_rate(self) -> float:
        if self.primary_metric == "falseWordsPerMinute":
            raise RuntimeError(
                "silence scoring has no reference error-rate denominator"
            )
        return self.primary_value

    def to_evidence(self) -> dict[str, object]:
        """Serialize a redacted case; public release should prefer aggregates."""

        return self._evidence(include_private_identities=False)

    def to_private_evidence(self) -> dict[str, object]:
        """Serialize case identities for the private external evaluation cache."""

        return self._evidence(include_private_identities=True)

    def _evidence(self, *, include_private_identities: bool) -> dict[str, object]:
        evidence: dict[str, object] = {
            "schemaVersion": 2,
            "privacyScope": (
                "private-case"
                if include_private_identities
                else "public-redacted-case"
            ),
            "scorer": _scorer_evidence(),
            "languageBcp47": self.language_bcp47,
            "scoringProfile": self.scoring_profile,
            "primaryMetric": self.primary_metric,
            "primaryValue": self.primary_value,
            "audioDurationSeconds": self.audio_duration_seconds,
            "metrics": {
                "punctuation": self.punctuation.to_evidence(),
                "criticalTokens": (
                    None
                    if self.critical_tokens is None
                    else self.critical_tokens.to_evidence(
                        include_private_identity=include_private_identities
                    )
                ),
                "rawWord": self.raw_word.to_evidence(),
                "normalizedWord": self.normalized_word.to_evidence(),
                "rawGrapheme": self.raw_grapheme.to_evidence(),
                "normalizedGrapheme": self.normalized_grapheme.to_evidence(),
            },
            "silence": (
                None
                if self.scoring_profile != "silence-false-words-v1"
                else {
                    "falseWords": self.normalized_word.hypothesis_units,
                    "falseGraphemes": self.normalized_grapheme.hypothesis_units,
                    "falseWordsPerMinute": self.primary_value,
                    "falseGraphemesPerMinute": _per_minute(
                        self.normalized_grapheme.hypothesis_units,
                        self.audio_duration_seconds,
                    ),
                }
            ),
        }
        if include_private_identities:
            evidence["inputIdentity"] = {
                "referenceSha256": self.reference_sha256,
                "hypothesisSha256": self.hypothesis_sha256,
            }
        return evidence


def critical_token_set_sha256(critical_tokens: list[str]) -> str:
    """Return the surface-bound hash for a private critical-token policy."""

    return _canonical_critical_token_policy(critical_tokens).token_set_sha256


def current_scorer_lock() -> dict[str, object]:
    """Return the exact scorer identity that promotion must hash and pin."""

    return {
        "schemaVersion": 2,
        "scorer": _scorer_evidence(),
    }


def score_transcript(
    reference: str,
    hypothesis: str,
    *,
    language_bcp47: str,
    scoring_profile: str,
    audio_duration_seconds: float | None = None,
    critical_tokens: list[str] | None = None,
    critical_token_set_sha256: str | None = None,
) -> TranscriptScore:
    """Score one bounded transcript without returning transcript or token text."""

    language = canonical_bcp47(language_bcp47, "scoring languageBcp47")
    profile = _validated_scoring_profile(scoring_profile)
    duration_seconds = _validated_duration(audio_duration_seconds)
    critical_policy = _critical_token_policy(
        critical_tokens,
        critical_token_set_sha256,
    )
    if profile == "silence-false-words-v1" and critical_policy is not None:
        raise ValueError("silence scoring cannot use a critical-token policy")
    reference_hash = _validated_text_sha256(reference, "reference")
    hypothesis_hash = _validated_text_sha256(hypothesis, "hypothesis")
    raw_reference = _raw_text(reference, "raw reference")
    raw_hypothesis = _raw_text(hypothesis, "raw hypothesis")
    normalized_reference = _normalized_text(reference)
    normalized_hypothesis = _normalized_text(hypothesis)
    critical_score = (
        None
        if critical_policy is None
        else _score_critical_tokens(
            raw_reference=raw_reference,
            raw_hypothesis=raw_hypothesis,
            normalized_reference=normalized_reference,
            normalized_hypothesis=normalized_hypothesis,
            policy=critical_policy,
        )
    )
    unit_pairs = {
        "raw word": (
            _word_units(raw_reference, "raw reference word"),
            _word_units(raw_hypothesis, "raw hypothesis word"),
        ),
        "normalized word": (
            _word_units(normalized_reference, "normalized reference word"),
            _word_units(normalized_hypothesis, "normalized hypothesis word"),
        ),
        "raw grapheme": (
            _grapheme_units(
                raw_reference,
                filter_punctuation=False,
                field="raw reference grapheme",
            ),
            _grapheme_units(
                raw_hypothesis,
                filter_punctuation=False,
                field="raw hypothesis grapheme",
            ),
        ),
        "normalized grapheme": (
            _grapheme_units(
                normalized_reference,
                filter_punctuation=True,
                field="normalized reference grapheme",
            ),
            _grapheme_units(
                normalized_hypothesis,
                filter_punctuation=True,
                field="normalized hypothesis grapheme",
            ),
        ),
    }
    if sum(_alignment_work(*pair) for pair in unit_pairs.values()) > (
        _MAX_TOTAL_ALIGNMENT_BLOCK_WORK
    ):
        raise ValueError(
            "aggregate transcript alignment exceeds the work bound; "
            "score source-time segments"
        )
    normalized_word_opcodes = Levenshtein.opcodes(
        *unit_pairs["normalized word"]
    )
    punctuation = _score_punctuation(
        normalized_reference,
        normalized_hypothesis,
        normalized_word_opcodes,
    )
    raw_word = _score_units(*unit_pairs["raw word"], metric="raw word")
    normalized_word = _score_units(
        *unit_pairs["normalized word"],
        metric="normalized word",
        edit_operations=normalized_word_opcodes.as_editops(),
    )
    raw_grapheme = _score_units(
        *unit_pairs["raw grapheme"],
        metric="raw grapheme",
    )
    normalized_grapheme = _score_units(
        *unit_pairs["normalized grapheme"],
        metric="normalized grapheme",
    )
    if profile == "word-primary-v1":
        primary_metric = "normalizedWordErrorRate"
        primary = normalized_word
    elif profile == "grapheme-primary-v1":
        primary_metric = "normalizedGraphemeErrorRate"
        primary = normalized_grapheme
    else:
        if reference != "":
            raise ValueError("silence reference must be exactly empty")
        if language != "und":
            raise ValueError("silence scoring requires und language")
        if duration_seconds is None:
            raise ValueError("silence scoring requires audio duration")
        primary_metric = "falseWordsPerMinute"
        primary = None
    if primary is not None and primary.reference_units == 0:
        raise ValueError(
            "primary reference contains no scoreable units; use the silence profile"
        )
    primary_value = (
        _per_minute(normalized_word.hypothesis_units, duration_seconds)
        if primary is None
        else _required_error_rate(primary)
    )
    return TranscriptScore(
        language_bcp47=language,
        scoring_profile=profile,
        primary_metric=primary_metric,
        primary_value=primary_value,
        audio_duration_seconds=duration_seconds,
        reference_sha256=reference_hash,
        hypothesis_sha256=hypothesis_hash,
        punctuation=punctuation,
        critical_tokens=critical_score,
        raw_word=raw_word,
        normalized_word=normalized_word,
        raw_grapheme=raw_grapheme,
        normalized_grapheme=normalized_grapheme,
    )


def _validated_scoring_profile(value: object) -> str:
    if not isinstance(value, str) or value not in _SCORING_PROFILES:
        raise ValueError("scoring profile is invalid")
    return value


def _validated_duration(value: object) -> float | None:
    if value is None:
        return None
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0 < value <= _MAX_AUDIO_DURATION_SECONDS
    ):
        raise ValueError("audio duration is invalid")
    return float(value)


def aggregate_transcript_scores(
    scores: list[TranscriptScore],
) -> dict[str, object]:
    """Return a public aggregate without low-entropy case or policy hashes."""

    return _aggregate_transcript_scores(
        scores,
        include_private_identities=False,
    )


def aggregate_private_transcript_scores(
    scores: list[TranscriptScore],
) -> dict[str, object]:
    """Return a private aggregate that retains its critical-policy identity."""

    return _aggregate_transcript_scores(
        scores,
        include_private_identities=True,
    )


def _aggregate_transcript_scores(
    scores: list[TranscriptScore],
    *,
    include_private_identities: bool,
) -> dict[str, object]:
    """Micro-aggregate bounded case scores without averaging unit denominators."""

    if not isinstance(scores, list) or not 1 <= len(scores) <= _MAX_AGGREGATE_CASES:
        raise ValueError("transcript-score aggregate requires a bounded nonempty list")
    if not all(isinstance(score, TranscriptScore) for score in scores):
        raise ValueError("transcript-score aggregate contains an invalid case")
    profile = scores[0].scoring_profile
    if any(score.scoring_profile != profile for score in scores):
        raise ValueError("transcript-score aggregate requires one scoring profile")
    metrics = {
        "punctuation": _aggregate_punctuation_scores(
            [score.punctuation for score in scores]
        ),
        "criticalTokens": _aggregate_critical_token_scores(
            scores,
            include_private_identity=include_private_identities,
        ),
        "rawWord": _aggregate_edit_scores([score.raw_word for score in scores]),
        "normalizedWord": _aggregate_edit_scores(
            [score.normalized_word for score in scores]
        ),
        "rawGrapheme": _aggregate_edit_scores(
            [score.raw_grapheme for score in scores]
        ),
        "normalizedGrapheme": _aggregate_edit_scores(
            [score.normalized_grapheme for score in scores]
        ),
    }
    primary_metric = scores[0].primary_metric
    if any(score.primary_metric != primary_metric for score in scores):
        raise ValueError("transcript-score aggregate primary metrics differ")
    if profile == "silence-false-words-v1":
        durations = [score.audio_duration_seconds for score in scores]
        if any(duration is None for duration in durations):
            raise ValueError("silence aggregate is missing an audio duration")
        total_duration = sum(float(duration) for duration in durations)
        primary_micro = _per_minute(
            sum(score.normalized_word.hypothesis_units for score in scores),
            total_duration,
        )
    else:
        total_duration = None
        primary_key = (
            "normalizedGrapheme"
            if profile == "grapheme-primary-v1"
            else "normalizedWord"
        )
        primary_error = metrics[primary_key]["errorRate"]
        if not isinstance(primary_error, float):
            raise RuntimeError("aggregate primary metric has no denominator")
        primary_micro = primary_error
    return {
        "schemaVersion": 2,
        "privacyScope": (
            "private-aggregate"
            if include_private_identities
            else "public-aggregate"
        ),
        "scorer": _scorer_evidence(),
        "caseCount": len(scores),
        "languagesBcp47": sorted({score.language_bcp47 for score in scores}),
        "scoringProfile": profile,
        "primaryMetric": primary_metric,
        "primaryMicroValue": primary_micro,
        "primaryMacroMean": sum(score.primary_value for score in scores) / len(scores),
        "audioDurationSeconds": total_duration,
        "metrics": metrics,
    }


def _aggregate_punctuation_scores(
    scores: list[PunctuationScore],
) -> dict[str, object]:
    reference_marks = sum(score.reference_marks for score in scores)
    hypothesis_marks = sum(score.hypothesis_marks for score in scores)
    correct_marks = sum(score.correct_marks for score in scores)
    precision, recall, f1 = _precision_recall_f1(
        correct=correct_marks,
        reference_total=reference_marks,
        hypothesis_total=hypothesis_marks,
    )
    return {
        "profile": _PUNCTUATION_PROFILE,
        "referenceMarks": reference_marks,
        "hypothesisMarks": hypothesis_marks,
        "correctMarks": correct_marks,
        "missingMarks": reference_marks - correct_marks,
        "excessMarks": hypothesis_marks - correct_marks,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def _aggregate_critical_token_scores(
    scores: list[TranscriptScore],
    *,
    include_private_identity: bool,
) -> dict[str, object] | None:
    critical_scores = [
        score.critical_tokens
        for score in scores
        if score.critical_tokens is not None
    ]
    if not critical_scores:
        return None
    if len(critical_scores) != len(scores):
        raise ValueError(
            "critical-token aggregation requires a policy on every case"
        )
    token_set_sha256_values = {
        score.token_set_sha256 for score in critical_scores
    }
    if len(token_set_sha256_values) != 1:
        raise ValueError(
            "critical-token aggregation requires one critical-token policy"
        )
    reference_occurrences = sum(
        score.reference_occurrences for score in critical_scores
    )
    hypothesis_occurrences = sum(
        score.hypothesis_occurrences for score in critical_scores
    )
    matched_occurrences = sum(
        score.matched_occurrences for score in critical_scores
    )
    precision, recall, f1 = _precision_recall_f1(
        correct=matched_occurrences,
        reference_total=reference_occurrences,
        hypothesis_total=hypothesis_occurrences,
    )
    evidence: dict[str, object] = {
        "profile": _CRITICAL_TOKEN_PROFILE,
        "scoredCaseCount": len(critical_scores),
        "unscoredCaseCount": 0,
        "referenceOccurrences": reference_occurrences,
        "hypothesisOccurrences": hypothesis_occurrences,
        "matchedOccurrences": matched_occurrences,
        "missedOccurrences": reference_occurrences - matched_occurrences,
        "excessOccurrences": hypothesis_occurrences - matched_occurrences,
        "orderedSequence": _aggregate_edit_scores(
            [score.ordered_sequence for score in critical_scores]
        ),
        "exactSurface": _aggregate_exact_surface_scores(
            [score.exact_surface for score in critical_scores]
        ),
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }
    if include_private_identity:
        evidence["tokenSetSha256"] = next(iter(token_set_sha256_values))
    return evidence


def _aggregate_exact_surface_scores(
    scores: list[ExactSurfaceScore],
) -> dict[str, object]:
    reference_occurrences = sum(score.reference_occurrences for score in scores)
    hypothesis_occurrences = sum(score.hypothesis_occurrences for score in scores)
    matched_occurrences = sum(score.matched_occurrences for score in scores)
    precision, recall, f1 = _precision_recall_f1(
        correct=matched_occurrences,
        reference_total=reference_occurrences,
        hypothesis_total=hypothesis_occurrences,
    )
    return {
        "profile": _EXACT_SURFACE_PROFILE,
        "referenceOccurrences": reference_occurrences,
        "hypothesisOccurrences": hypothesis_occurrences,
        "referenceExactOccurrences": sum(
            score.reference_exact_occurrences for score in scores
        ),
        "hypothesisExactOccurrences": sum(
            score.hypothesis_exact_occurrences for score in scores
        ),
        "matchedOccurrences": matched_occurrences,
        "missedOccurrences": reference_occurrences - matched_occurrences,
        "unmatchedHypothesisOccurrences": (
            hypothesis_occurrences - matched_occurrences
        ),
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def _aggregate_edit_scores(scores: list[EditScore]) -> dict[str, object]:
    scored = [score for score in scores if score.reference_units > 0]
    zero_reference = [score for score in scores if score.reference_units == 0]
    reference_units = sum(score.reference_units for score in scored)
    insertions = sum(score.insertions for score in scored)
    deletions = sum(score.deletions for score in scored)
    substitutions = sum(score.substitutions for score in scored)
    errors = insertions + deletions + substitutions
    return {
        "scoredCaseCount": len(scored),
        "zeroReferenceCaseCount": len(zero_reference),
        "referenceUnits": reference_units,
        "hypothesisUnits": sum(score.hypothesis_units for score in scores),
        "insertions": insertions,
        "deletions": deletions,
        "substitutions": substitutions,
        "errors": errors,
        "errorRate": None if reference_units == 0 else errors / reference_units,
        "zeroReferenceInsertions": sum(
            score.hypothesis_units for score in zero_reference
        ),
    }


def _scorer_evidence() -> dict[str, object]:
    return {
        "id": "yap-transcript-scorer",
        "version": 2,
        "sourceRevision": _SCORER_REVISION,
        "sourceSha256": _SCORER_SOURCE_SHA256,
        "normalizerRevision": _NORMALIZER_REVISION,
        "punctuationProfile": _PUNCTUATION_PROFILE,
        "criticalTokenProfile": _CRITICAL_TOKEN_PROFILE,
        "exactSurfaceProfile": _EXACT_SURFACE_PROFILE,
        "unicodeVersion": unicodedata.unidata_version,
        "regexVersion": regex.__version__,
        "rapidfuzzVersion": rapidfuzz.__version__,
        "rawNormalization": "NFC+unicode-whitespace-collapse",
        "normalizedNormalization": (
            "NFKC+casefold+NFKC+unicode-whitespace-collapse+punctuation-filter"
        ),
        "wordTokenization": (
            "Unicode alphabetic, mark, and decimal runs with internal apostrophes"
        ),
        "graphemeTokenization": "regex-VERSION1-extended-grapheme-cluster",
    }


def _required_error_rate(score: EditScore) -> float:
    if score.error_rate is None:
        raise RuntimeError("primary transcript score has no denominator")
    return score.error_rate


def _per_minute(units: int, duration_seconds: float | None) -> float:
    if duration_seconds is None or duration_seconds <= 0:
        raise RuntimeError("per-minute metric is missing an audio duration")
    return units * 60 / duration_seconds


def _validated_text_sha256(value: str, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} transcript must be text")
    if "\0" in value:
        raise ValueError(f"{field} transcript cannot contain NUL")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError(f"{field} transcript contains invalid Unicode") from error
    if len(encoded) > _MAX_TEXT_BYTES:
        raise ValueError(f"{field} transcript exceeds the byte bound")
    return hashlib.sha256(encoded).hexdigest()


def _collapse_whitespace(value: str) -> str:
    return " ".join(value.split())


def _raw_text(value: str, field: str) -> str:
    return _bounded_derived_text(
        _collapse_whitespace(unicodedata.normalize("NFC", value)),
        field,
    )


def _normalized_text(value: str) -> str:
    compatibility = unicodedata.normalize("NFKC", value)
    return _bounded_derived_text(
        _collapse_whitespace(
            unicodedata.normalize("NFKC", compatibility.casefold())
        ),
        "normalized transcript",
    )


def _critical_token_policy(
    critical_tokens: list[str] | None,
    expected_sha256: str | None,
) -> _CriticalTokenPolicy | None:
    if critical_tokens is None and expected_sha256 is None:
        return None
    if critical_tokens is None or expected_sha256 is None:
        raise ValueError(
            "critical tokens and critical-token set SHA-256 must be supplied together"
        )
    if not isinstance(expected_sha256, str) or _SHA256.fullmatch(
        expected_sha256
    ) is None:
        raise ValueError("critical-token set SHA-256 is invalid")
    policy = _canonical_critical_token_policy(critical_tokens)
    if not hmac.compare_digest(policy.token_set_sha256, expected_sha256):
        raise ValueError("critical-token policy differs from its pinned SHA-256")
    return policy


def _canonical_critical_token_policy(
    critical_tokens: list[str],
) -> _CriticalTokenPolicy:
    if (
        not isinstance(critical_tokens, list)
        or not 1 <= len(critical_tokens) <= _MAX_CRITICAL_TOKEN_PHRASES
    ):
        raise ValueError("critical-token policy must be a bounded nonempty list")
    phrases: list[_CriticalPhrase] = []
    raw_total_bytes = 0
    total_bytes = 0
    for value in critical_tokens:
        if not isinstance(value, str) or "\0" in value:
            raise ValueError("critical-token policy contains an invalid phrase")
        try:
            raw_bytes = len(value.encode("utf-8"))
        except UnicodeEncodeError as error:
            raise ValueError(
                "critical-token policy contains an invalid phrase"
            ) from error
        raw_total_bytes += raw_bytes
        if (
            raw_bytes > _MAX_CRITICAL_TOKEN_PHRASE_BYTES
            or raw_total_bytes > _MAX_CRITICAL_TOKEN_SET_BYTES
        ):
            raise ValueError("critical-token policy exceeds the byte bound")
        surface = _raw_text(value, "critical-token surface phrase")
        normalized = _normalized_text(value)
        encoded_bytes = len(normalized.encode("utf-8"))
        total_bytes += encoded_bytes
        normalized_graphemes = tuple(_GRAPHEME.findall(normalized))
        surface_graphemes = tuple(_GRAPHEME.findall(surface))
        if (
            not normalized
            or encoded_bytes > _MAX_CRITICAL_TOKEN_PHRASE_BYTES
            or len(normalized_graphemes) > _MAX_CRITICAL_TOKEN_PHRASE_GRAPHEMES
            or len(surface_graphemes) > _MAX_CRITICAL_TOKEN_PHRASE_GRAPHEMES
            or not any(
                _is_wordlike_grapheme(unit) for unit in normalized_graphemes
            )
        ):
            raise ValueError("critical-token policy contains an invalid phrase")
        phrases.append(
            _CriticalPhrase(
                normalized=normalized_graphemes,
                surface=surface_graphemes,
            )
        )
    if total_bytes > _MAX_CRITICAL_TOKEN_SET_BYTES:
        raise ValueError("critical-token policy exceeds the byte bound")
    if len({phrase.normalized for phrase in phrases}) != len(phrases):
        raise ValueError("critical-token policy contains normalized duplicates")
    canonical_phrases = tuple(
        sorted(phrases, key=lambda phrase: (phrase.normalized, phrase.surface))
    )
    payload = json.dumps(
        {
            "schemaVersion": 2,
            "normalizerRevision": _NORMALIZER_REVISION,
            "matchingProfile": _CRITICAL_TOKEN_PROFILE,
            "phrases": [
                {
                    "normalized": "".join(phrase.normalized),
                    "surface": "".join(phrase.surface),
                }
                for phrase in canonical_phrases
            ],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _CriticalTokenPolicy(
        token_set_sha256=hashlib.sha256(payload).hexdigest(),
        phrases=canonical_phrases,
    )


def _bounded_derived_text(value: str, field: str) -> str:
    if len(value.encode("utf-8")) > _MAX_DERIVED_TEXT_BYTES:
        raise ValueError(f"{field} exceeds the normalized-text bound")
    return value


def _word_units(value: str, field: str) -> list[str]:
    units: list[str] = []
    for match in _WORD_TOKEN.finditer(value):
        units.append(match.group())
        if len(units) > _MAX_UNITS:
            raise ValueError(f"{field} unit count exceeds the scoring bound")
    return units


def _grapheme_units(
    value: str,
    *,
    filter_punctuation: bool,
    field: str,
) -> list[str]:
    units: list[str] = []
    for cluster in _GRAPHEME.findall(value):
        if cluster.isspace():
            continue
        if filter_punctuation and _is_punctuation_cluster(cluster):
            continue
        units.append(cluster)
        if len(units) > _MAX_UNITS:
            raise ValueError(f"{field} unit count exceeds the scoring bound")
    return units


def _is_punctuation_cluster(value: str) -> bool:
    bases = [
        unicodedata.category(character)
        for character in value
        if unicodedata.category(character) not in {"Mn", "Me", "Cf"}
    ]
    return bool(bases) and all(category[0] in {"P", "Z"} for category in bases)


def _score_punctuation(
    reference: str,
    hypothesis: str,
    word_opcodes: object,
) -> PunctuationScore:
    reference_events = Counter(_punctuation_events(reference))
    hypothesis_events = _punctuation_events(hypothesis)
    boundary_map = _aligned_hypothesis_boundaries(word_opcodes)
    candidates: list[tuple[int, tuple[tuple[int, int, str], ...]]] = []
    for index, (boundary, ordinal, mark) in enumerate(hypothesis_events):
        keys = tuple(
            (reference_boundary, ordinal, mark)
            for reference_boundary in boundary_map[boundary]
            if reference_events[(reference_boundary, ordinal, mark)] > 0
        )
        candidates.append((index, keys))
    remaining = reference_events.copy()
    correct = 0
    for _, keys in sorted(candidates, key=lambda item: (len(item[1]), item[0])):
        for key in keys:
            if remaining[key] > 0:
                remaining[key] -= 1
                correct += 1
                break
    precision, recall, f1 = _precision_recall_f1(
        correct=correct,
        reference_total=sum(reference_events.values()),
        hypothesis_total=len(hypothesis_events),
    )
    return PunctuationScore(
        reference_marks=sum(reference_events.values()),
        hypothesis_marks=len(hypothesis_events),
        correct_marks=correct,
        precision=precision,
        recall=recall,
        f1=f1,
    )


def _aligned_hypothesis_boundaries(
    word_opcodes: object,
) -> tuple[tuple[int, ...], ...]:
    destination_length = getattr(word_opcodes, "dest_len", None)
    if not isinstance(destination_length, int) or destination_length < 0:
        raise RuntimeError("RapidFuzz returned invalid opcodes")
    boundaries: list[set[int]] = [set() for _ in range(destination_length + 1)]
    for operation in word_opcodes:  # type: ignore[union-attr]
        reference_count = operation.src_end - operation.src_start
        hypothesis_count = operation.dest_end - operation.dest_start
        if operation.tag == "equal" or (
            operation.tag == "replace" and reference_count == hypothesis_count
        ):
            for offset in range(hypothesis_count + 1):
                boundaries[operation.dest_start + offset].add(
                    operation.src_start + offset
                )
        elif operation.tag == "insert":
            for boundary in range(operation.dest_start, operation.dest_end + 1):
                boundaries[boundary].add(operation.src_start)
        elif operation.tag == "delete":
            boundaries[operation.dest_start].update(
                {operation.src_start, operation.src_end}
            )
        elif operation.tag == "replace":
            boundaries[operation.dest_start].add(operation.src_start)
            boundaries[operation.dest_end].add(operation.src_end)
        else:
            raise RuntimeError("RapidFuzz returned an unknown opcode")
    return tuple(tuple(sorted(boundary)) for boundary in boundaries)


def _score_critical_tokens(
    *,
    raw_reference: str,
    raw_hypothesis: str,
    normalized_reference: str,
    normalized_hypothesis: str,
    policy: _CriticalTokenPolicy,
) -> CriticalTokenScore:
    normalized_trie = _critical_token_trie(
        tuple(
            (phrase.normalized, phrase.normalized)
            for phrase in policy.phrases
        )
    )
    surface_trie = _critical_token_trie(
        tuple((phrase.surface, phrase.normalized) for phrase in policy.phrases)
    )
    reference_sequence = _critical_occurrences(
        normalized_reference,
        normalized_trie,
    )
    hypothesis_sequence = _critical_occurrences(
        normalized_hypothesis,
        normalized_trie,
    )
    reference_exact_sequence = _critical_occurrences(raw_reference, surface_trie)
    hypothesis_exact_sequence = _critical_occurrences(raw_hypothesis, surface_trie)
    reference_occurrences = Counter(reference_sequence)
    hypothesis_occurrences = Counter(hypothesis_sequence)
    matched = sum((reference_occurrences & hypothesis_occurrences).values())
    reference_total = sum(reference_occurrences.values())
    hypothesis_total = sum(hypothesis_occurrences.values())
    precision, recall, f1 = _precision_recall_f1(
        correct=matched,
        reference_total=reference_total,
        hypothesis_total=hypothesis_total,
    )
    exact_matched = sum(
        (
            Counter(reference_exact_sequence)
            & Counter(hypothesis_exact_sequence)
        ).values()
    )
    exact_precision, exact_recall, exact_f1 = _precision_recall_f1(
        correct=exact_matched,
        reference_total=reference_total,
        hypothesis_total=hypothesis_total,
    )
    return CriticalTokenScore(
        token_set_sha256=policy.token_set_sha256,
        reference_occurrences=reference_total,
        hypothesis_occurrences=hypothesis_total,
        matched_occurrences=matched,
        ordered_sequence=_score_units(
            list(reference_sequence),
            list(hypothesis_sequence),
            metric="ordered critical-token sequence",
        ),
        exact_surface=ExactSurfaceScore(
            reference_occurrences=reference_total,
            hypothesis_occurrences=hypothesis_total,
            reference_exact_occurrences=len(reference_exact_sequence),
            hypothesis_exact_occurrences=len(hypothesis_exact_sequence),
            matched_occurrences=exact_matched,
            precision=exact_precision,
            recall=exact_recall,
            f1=exact_f1,
        ),
        precision=precision,
        recall=recall,
        f1=f1,
    )


def _critical_token_trie(
    phrases: tuple[
        tuple[tuple[str, ...], tuple[str, ...]],
        ...,
    ],
) -> _CriticalTrieNode:
    root = _CriticalTrieNode()
    for matched_phrase, identity in phrases:
        node = root
        for grapheme in matched_phrase:
            node = node.children.setdefault(grapheme, _CriticalTrieNode())
        node.matched_phrase = matched_phrase
        node.identity = identity
    return root


def _critical_occurrences(
    value: str,
    root: _CriticalTrieNode,
) -> list[tuple[str, ...]]:
    graphemes = _GRAPHEME.findall(value)
    if len(graphemes) > _MAX_CRITICAL_TEXT_GRAPHEMES:
        raise ValueError("critical-token transcript exceeds the scoring bound")
    occurrences: list[tuple[str, ...]] = []
    start = 0
    while start < len(graphemes):
        node = root
        cursor = start
        longest: tuple[tuple[str, ...], int] | None = None
        while cursor < len(graphemes):
            child = node.children.get(graphemes[cursor])
            if child is None:
                break
            node = child
            cursor += 1
            if (
                node.matched_phrase is not None
                and node.identity is not None
                and _critical_match_has_boundaries(
                    graphemes,
                    start,
                    cursor,
                    node.matched_phrase,
                )
            ):
                longest = (node.identity, cursor)
        if longest is None:
            start += 1
        else:
            occurrences.append(longest[0])
            start = longest[1]
    return occurrences


def _critical_match_has_boundaries(
    transcript: list[str],
    start: int,
    end: int,
    phrase: tuple[str, ...],
) -> bool:
    wordlike = [unit for unit in phrase if _is_wordlike_grapheme(unit)]
    if not wordlike:
        raise RuntimeError("critical-token phrase contains no wordlike grapheme")
    if (
        not _is_boundaryless_grapheme(wordlike[0])
        and start > 0
        and _is_wordlike_grapheme(transcript[start - 1])
    ):
        return False
    return not (
        not _is_boundaryless_grapheme(wordlike[-1])
        and end < len(transcript)
        and _is_wordlike_grapheme(transcript[end])
    )


def _is_wordlike_grapheme(value: str) -> bool:
    return _WORDLIKE_GRAPHEME.search(value) is not None


def _is_boundaryless_grapheme(value: str) -> bool:
    return _BOUNDARYLESS_GRAPHEME.search(value) is not None


def _punctuation_events(value: str) -> list[tuple[int, int, str]]:
    words = list(_WORD_TOKEN.finditer(value))
    word_index = 0
    ordinal_by_boundary: dict[int, int] = {}
    events: list[tuple[int, int, str]] = []
    for match in _GRAPHEME.finditer(value):
        start, end = match.span()
        while word_index < len(words) and words[word_index].end() <= start:
            word_index += 1
        if (
            word_index < len(words)
            and words[word_index].start() <= start
            and end <= words[word_index].end()
        ):
            continue
        cluster = match.group()
        if cluster.isspace() or not _is_punctuation_cluster(cluster):
            continue
        ordinal = ordinal_by_boundary.get(word_index, 0)
        events.append((word_index, ordinal, cluster))
        ordinal_by_boundary[word_index] = ordinal + 1
    return events


def _precision_recall_f1(
    *,
    correct: int,
    reference_total: int,
    hypothesis_total: int,
) -> tuple[float | None, float | None, float | None]:
    precision = None if hypothesis_total == 0 else correct / hypothesis_total
    recall = None if reference_total == 0 else correct / reference_total
    if precision is None and recall is None:
        f1 = None
    elif precision is None or recall is None or precision + recall == 0:
        f1 = 0.0
    else:
        f1 = 2 * precision * recall / (precision + recall)
    return precision, recall, f1


def _score_units(
    reference: list[object],
    hypothesis: list[object],
    *,
    metric: str,
    edit_operations: object | None = None,
) -> EditScore:
    if len(reference) > _MAX_UNITS or len(hypothesis) > _MAX_UNITS:
        raise ValueError(f"{metric} unit count exceeds the scoring bound")
    estimated_work = _alignment_work(reference, hypothesis)
    if estimated_work > _MAX_ALIGNMENT_BLOCK_WORK:
        raise ValueError(
            f"{metric} alignment exceeds the work bound; score source-time segments"
        )
    counts = {"insert": 0, "delete": 0, "replace": 0}
    operations = (
        Levenshtein.editops(reference, hypothesis)
        if edit_operations is None
        else edit_operations
    )
    for operation in operations:  # type: ignore[union-attr]
        if operation.tag not in counts:
            raise RuntimeError("RapidFuzz returned an unknown edit operation")
        counts[operation.tag] += 1
    errors = counts["insert"] + counts["delete"] + counts["replace"]
    return EditScore(
        reference_units=len(reference),
        hypothesis_units=len(hypothesis),
        insertions=counts["insert"],
        deletions=counts["delete"],
        substitutions=counts["replace"],
        error_rate=None if not reference else errors / len(reference),
    )


def _alignment_work(reference: list[object], hypothesis: list[object]) -> int:
    short = min(len(reference), len(hypothesis))
    long = max(len(reference), len(hypothesis))
    return math.ceil(short / 64) * long if short else 0
