from __future__ import annotations

from dataclasses import dataclass
import hashlib

from .transcript_correction import (
    BoundTranscriptCorrectionRequest,
    TranscriptCorrectionProtectedSpan,
    TranscriptCorrectionRequest,
    TranscriptCorrectionResponse,
    bind_transcript_correction_request,
    correction_request_sha256,
    parse_transcript_correction_response,
    protected_transcript_spans,
)


_VISIBLE_PLACEHOLDERS = (
    "~",
    "^",
    "@",
    "#",
    "=",
    "_",
    "+",
    "|",
    "%",
    "&",
    "*",
    "!",
)


@dataclass(frozen=True, slots=True)
class _MaskedFact:
    token: str
    raw_start: int
    raw_end: int
    masked_start: int
    masked_end: int
    raw_text: str


@dataclass(frozen=True, slots=True)
class _MaskedSegment:
    segment_id: str
    raw_text: str
    raw_sha256: str
    masked_text: str
    masked_sha256: str
    facts: tuple[_MaskedFact, ...]

    def raw_boundary(self, masked_index: int) -> int:
        if not 0 <= masked_index <= len(self.masked_text):
            raise ValueError("transcript correction masked span is invalid")
        raw_cursor = 0
        masked_cursor = 0
        for fact in self.facts:
            if masked_index <= fact.masked_start:
                return raw_cursor + (masked_index - masked_cursor)
            if masked_index < fact.masked_end:
                raise ValueError("transcript correction edit split a protected fact")
            raw_cursor = fact.raw_end
            masked_cursor = fact.masked_end
        return raw_cursor + (masked_index - masked_cursor)


@dataclass(frozen=True, slots=True)
class MaskedTranscriptCorrectionRequest:
    request: BoundTranscriptCorrectionRequest
    segments: tuple[_MaskedSegment, ...]
    placeholder_character: str
    placeholders: tuple[str, ...]


def mask_transcript_correction_request(
    request: BoundTranscriptCorrectionRequest,
) -> MaskedTranscriptCorrectionRequest:
    spans_by_segment: dict[str, list[TranscriptCorrectionProtectedSpan]] = {}
    for span in protected_transcript_spans(request):
        spans_by_segment.setdefault(span.segment_id, []).append(span)
    occupied_source = "\0".join(
        (request.source_text, *request.approved_terminology)
    )
    placeholder_character = _new_placeholder_character(occupied_source)
    masked_segments: list[_MaskedSegment] = []
    placeholders: list[str] = []
    wire_segments: list[dict[str, object]] = []
    global_start = 0
    for segment in request.segments:
        raw_cursor = 0
        masked_cursor = 0
        parts: list[str] = []
        facts: list[_MaskedFact] = []
        for span in spans_by_segment.get(segment.segment_id, []):
            token = placeholder_character * len(span.text)
            plain = segment.text[raw_cursor : span.start_character]
            parts.extend((plain, token))
            masked_cursor += len(plain)
            facts.append(
                _MaskedFact(
                    token=token,
                    raw_start=span.start_character,
                    raw_end=span.end_character,
                    masked_start=masked_cursor,
                    masked_end=masked_cursor + len(token),
                    raw_text=span.text,
                )
            )
            placeholders.append(token)
            masked_cursor += len(token)
            raw_cursor = span.end_character
        parts.append(segment.text[raw_cursor:])
        masked_text = "".join(parts)
        masked_sha256 = _sha256_text(masked_text)
        masked_segments.append(
            _MaskedSegment(
                segment_id=segment.segment_id,
                raw_text=segment.text,
                raw_sha256=segment.text_sha256,
                masked_text=masked_text,
                masked_sha256=masked_sha256,
                facts=tuple(facts),
            )
        )
        wire_segments.append(
            {
                "segmentId": segment.segment_id,
                "startCharacter": global_start,
                "endCharacter": global_start + len(masked_text),
                "startMilliseconds": segment.start_milliseconds,
                "endMilliseconds": segment.end_milliseconds,
                "languageBcp47": segment.language_bcp47,
                "text": masked_text,
                "textSha256": masked_sha256,
            }
        )
        global_start += len(masked_text)
    masked_source = "".join(segment.masked_text for segment in masked_segments)
    masked_source_sha256 = _sha256_text(masked_source)
    masked_revision_sha256 = hashlib.sha256(
        (
            "masked-transcript-correction-v1\0"
            + request.source_revision_sha256
            + "\0"
            + masked_source_sha256
        ).encode("utf-8")
    ).hexdigest()
    source = TranscriptCorrectionRequest.from_wire(
        {
            "schemaVersion": 1,
            "sourceRevisionSha256": masked_revision_sha256,
            "sourceSha256": masked_source_sha256,
            "segments": wire_segments,
        }
    )
    return MaskedTranscriptCorrectionRequest(
        request=bind_transcript_correction_request(source, request.terminology),
        segments=tuple(masked_segments),
        placeholder_character=placeholder_character,
        placeholders=tuple(placeholders),
    )


def restore_masked_transcript_correction_response(
    request: BoundTranscriptCorrectionRequest,
    masked: MaskedTranscriptCorrectionRequest,
    response: TranscriptCorrectionResponse,
) -> TranscriptCorrectionResponse:
    if (
        response.request_sha256 != correction_request_sha256(masked.request)
        or response.source_sha256 != masked.request.source_sha256
    ):
        raise ValueError("transcript correction masked response binding differs")
    segments = {segment.segment_id: segment for segment in masked.segments}
    raw_edits: list[dict[str, object]] = []
    for edit in response.edits:
        segment = segments.get(edit.segment_id)
        if segment is None or edit.segment_sha256 != segment.masked_sha256:
            raise ValueError("transcript correction masked segment binding differs")
        start = segment.masked_text.find(edit.source_text)
        if start < 0 or segment.masked_text.find(edit.source_text, start + 1) >= 0:
            raise ValueError("transcript correction edit source must occur exactly once")
        end = start + len(edit.source_text)
        raw_start = segment.raw_boundary(start)
        raw_end = segment.raw_boundary(end)
        expected_facts = tuple(
            fact
            for fact in segment.facts
            if start <= fact.masked_start and fact.masked_end <= end
        )
        observed_runs = _placeholder_runs(
            edit.replacement_text,
            masked.placeholder_character,
        )
        if tuple(length for _start, _end, length in observed_runs) != tuple(
            len(fact.token) for fact in expected_facts
        ):
            raise ValueError("transcript correction changed a protected placeholder")
        replacement_parts: list[str] = []
        replacement_cursor = 0
        for fact, (run_start, run_end, _length) in zip(
            expected_facts,
            observed_runs,
            strict=True,
        ):
            replacement_parts.append(edit.replacement_text[replacement_cursor:run_start])
            replacement_parts.append(fact.raw_text)
            replacement_cursor = run_end
        replacement_parts.append(edit.replacement_text[replacement_cursor:])
        replacement = "".join(replacement_parts)
        if masked.placeholder_character in replacement:
            raise ValueError("transcript correction invented a protected placeholder")
        raw_edits.append(
            {
                "segmentId": edit.segment_id,
                "segmentSha256": segment.raw_sha256,
                "sourceText": segment.raw_text[raw_start:raw_end],
                "replacementText": replacement,
            }
        )
    return parse_transcript_correction_response(
        {
            "schemaVersion": 2,
            "requestSha256": correction_request_sha256(request),
            "sourceSha256": request.source_sha256,
            "uncertain": response.uncertain,
            "edits": raw_edits,
        }
    )


def _new_placeholder_character(source: str) -> str:
    for candidate in _VISIBLE_PLACEHOLDERS:
        if candidate not in source:
            return candidate
    raise ValueError("transcript correction source exhausts protected placeholders")


def _placeholder_runs(
    value: str,
    placeholder: str,
) -> tuple[tuple[int, int, int], ...]:
    runs: list[tuple[int, int, int]] = []
    start = 0
    while True:
        start = value.find(placeholder, start)
        if start < 0:
            break
        end = start + 1
        while end < len(value) and value[end] == placeholder:
            end += 1
        runs.append((start, end, end - start))
        start = end
    return tuple(runs)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


__all__ = [
    "MaskedTranscriptCorrectionRequest",
    "mask_transcript_correction_request",
    "restore_masked_transcript_correction_response",
]
