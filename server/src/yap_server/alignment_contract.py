from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping, Sequence

from yap_server.transcript_text import canonical_transcript


ALIGNMENT_COMPONENT_REVISION = "cohere-attention-en-v1"
COHERE_ATTENTION_ALIGNMENT_CANDIDATE_REVISION = (
    "cohere-attention-alignment-candidate-v1"
)
JOINT_SEGMENT_TIMING_REVISION = "joint-segment-timing-v1"
MAX_ALIGNMENT_WORDS = 16_384
MAX_ALIGNMENT_WORD_TEXT_BYTES = 512


class AlignmentUnavailableReason(StrEnum):
    EMPTY_TRANSCRIPT = "ALIGNMENT_EMPTY_TRANSCRIPT"
    PROVIDER_UNSUPPORTED = "ALIGNMENT_PROVIDER_UNSUPPORTED"
    LANGUAGE_UNSUPPORTED = "ALIGNMENT_LANGUAGE_UNSUPPORTED"
    TOKEN_LIMIT = "ALIGNMENT_TOKEN_LIMIT"
    WORD_LIMIT = "ALIGNMENT_WORD_LIMIT"
    SOURCE_LIMIT = "ALIGNMENT_SOURCE_LIMIT"
    TOKEN_TRANSCRIPT_DIVERGED = "ALIGNMENT_TOKEN_TRANSCRIPT_DIVERGED"
    EVIDENCE_INVALID = "ALIGNMENT_EVIDENCE_INVALID"
    RESULT_LIMIT = "ALIGNMENT_RESULT_LIMIT"
    RUNTIME_FAILED = "ALIGNMENT_RUNTIME_FAILED"


class AlignmentUnavailable(ValueError):
    def __init__(self, reason: AlignmentUnavailableReason) -> None:
        super().__init__(reason.value)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class AlignedWordEvidence:
    word_index: int
    text: str
    start_ms: int
    end_ms: int

    def to_result(self) -> dict[str, object]:
        return {
            "wordIndex": self.word_index,
            "text": self.text,
            "startMs": self.start_ms,
            "endMs": self.end_ms,
            "turnId": None,
            "attribution": {"kind": "unknown"},
            "confidence": None,
        }


def unavailable_alignment(
    reason: AlignmentUnavailableReason,
    *,
    component_revision: str = ALIGNMENT_COMPONENT_REVISION,
) -> dict[str, object]:
    return {
        "status": "unavailable",
        "reason": reason.value,
        "componentRevision": component_revision,
        "alignedWords": [],
    }


def available_alignment(
    words: Sequence[AlignedWordEvidence],
) -> dict[str, object]:
    if not words or len(words) > MAX_ALIGNMENT_WORDS:
        raise AlignmentUnavailable(AlignmentUnavailableReason.WORD_LIMIT)
    checked: list[dict[str, object]] = []
    previous_end = 0
    for index, word in enumerate(words):
        if (
            not isinstance(word, AlignedWordEvidence)
            or word.word_index != index
            or not isinstance(word.text, str)
            or not word.text
            or any(character.isspace() for character in word.text)
            or _utf8_size(word.text) > MAX_ALIGNMENT_WORD_TEXT_BYTES
            or isinstance(word.start_ms, bool)
            or not isinstance(word.start_ms, int)
            or isinstance(word.end_ms, bool)
            or not isinstance(word.end_ms, int)
            or word.start_ms < previous_end
            or word.end_ms <= word.start_ms
        ):
            raise AlignmentUnavailable(AlignmentUnavailableReason.EVIDENCE_INVALID)
        checked.append(word.to_result())
        previous_end = word.end_ms
    return {
        "status": "available",
        "reason": None,
        "componentRevision": ALIGNMENT_COMPONENT_REVISION,
        "alignedWords": checked,
    }


def validate_alignment_payload(
    value: object,
    *,
    transcript: str,
    maximum_end_ms: int | None = None,
) -> None:
    checked_transcript = canonical_transcript(transcript, "alignment transcript")
    if maximum_end_ms is not None and (
        isinstance(maximum_end_ms, bool)
        or not isinstance(maximum_end_ms, int)
        or maximum_end_ms < 1
    ):
        raise ValueError("alignment source duration is invalid")
    if not isinstance(value, Mapping) or set(value) != {
        "status",
        "reason",
        "componentRevision",
        "alignedWords",
    }:
        raise ValueError("alignment result shape is invalid")
    status = value.get("status")
    reason = value.get("reason")
    component_revision = value.get("componentRevision")
    aligned_words = value.get("alignedWords")
    if component_revision not in {
        ALIGNMENT_COMPONENT_REVISION,
        COHERE_ATTENTION_ALIGNMENT_CANDIDATE_REVISION,
        JOINT_SEGMENT_TIMING_REVISION,
    }:
        raise ValueError("alignment component revision is invalid")
    if status == "unavailable":
        try:
            AlignmentUnavailableReason(reason)
        except (TypeError, ValueError) as error:
            raise ValueError("alignment unavailable reason is invalid") from error
        if aligned_words != []:
            raise ValueError("unavailable alignment contains words")
        return
    if (
        status != "available"
        or reason is not None
        or component_revision != ALIGNMENT_COMPONENT_REVISION
        or not isinstance(aligned_words, list)
        or not 1 <= len(aligned_words) <= MAX_ALIGNMENT_WORDS
    ):
        raise ValueError("available alignment metadata is invalid")

    rendered: list[str] = []
    previous_end = 0
    for index, raw_word in enumerate(aligned_words):
        if not isinstance(raw_word, Mapping) or set(raw_word) != {
            "wordIndex",
            "text",
            "startMs",
            "endMs",
            "turnId",
            "attribution",
            "confidence",
        }:
            raise ValueError("aligned word shape is invalid")
        word = raw_word.get("text")
        start_ms = raw_word.get("startMs")
        end_ms = raw_word.get("endMs")
        attribution = raw_word.get("attribution")
        if (
            raw_word.get("wordIndex") != index
            or not isinstance(word, str)
            or not word
            or any(character.isspace() for character in word)
            or _utf8_size(word) > MAX_ALIGNMENT_WORD_TEXT_BYTES
            or isinstance(start_ms, bool)
            or not isinstance(start_ms, int)
            or isinstance(end_ms, bool)
            or not isinstance(end_ms, int)
            or start_ms < previous_end
            or end_ms <= start_ms
            or (maximum_end_ms is not None and end_ms > maximum_end_ms)
            or raw_word.get("turnId") is not None
            or attribution != {"kind": "unknown"}
            or raw_word.get("confidence") is not None
        ):
            raise ValueError("aligned word content is invalid")
        rendered.append(word)
        previous_end = end_ms
    if " ".join(rendered) != checked_transcript:
        raise ValueError("aligned words do not preserve the raw transcript")


def _utf8_size(value: str) -> int:
    try:
        return len(value.encode("utf-8"))
    except UnicodeEncodeError as error:
        raise AlignmentUnavailable(
            AlignmentUnavailableReason.EVIDENCE_INVALID
        ) from error
