from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Sequence

from yap_server.alignment_contract import (
    MAX_ALIGNMENT_WORDS,
    MAX_ALIGNMENT_WORD_TEXT_BYTES,
    AlignedWordEvidence,
    AlignmentUnavailable,
    AlignmentUnavailableReason,
)
from yap_server.transcript_text import canonical_transcript


ALIGNMENT_ENCODER_FRAME_SAMPLES = 1_280
ALIGNMENT_ENCODER_FRAME_MS = 80
# Frozen on the four LibriSpeech dev fixtures and then checked without
# reselection on the four fixtures in the checked public alignment evidence set.
ALIGNMENT_SELECTED_HEADS = ((0, 5), (1, 6))
ALIGNMENT_MEDIAN_FILTER_WIDTH = 3
MAX_ALIGNMENT_CHUNK_SAMPLES = 35 * 16_000
MAX_ALIGNMENT_TOKENS = 256
MAX_ALIGNMENT_MATRIX_TOKENS = MAX_ALIGNMENT_TOKENS + 32


@dataclass(frozen=True, slots=True)
class _WordTokenSpan:
    text: str
    first_token: int


def valid_encoder_frame_count(source_frame_count: int) -> int:
    if (
        isinstance(source_frame_count, bool)
        or not isinstance(source_frame_count, int)
        or not 1 <= source_frame_count <= MAX_ALIGNMENT_CHUNK_SAMPLES
    ):
        raise AlignmentUnavailable(AlignmentUnavailableReason.SOURCE_LIMIT)
    return (
        source_frame_count + ALIGNMENT_ENCODER_FRAME_SAMPLES - 1
    ) // ALIGNMENT_ENCODER_FRAME_SAMPLES


def align_cohere_word_scores(
    *,
    transcript: str,
    token_pieces: Sequence[str],
    score_matrix: Sequence[Sequence[float]],
    content_token_offset: int,
    source_start_sample: int,
    source_frame_count: int,
    first_word_index: int = 0,
) -> tuple[AlignedWordEvidence, ...]:
    """Convert a checked Cohere token/frame score matrix to raw-word intervals.

    The matrix is already the selected-head, normalized, median-filtered FP32
    evidence. Higher values are better. This function owns the model-free,
    deterministic DTW and exact transcript-reconciliation boundary.
    """

    checked_transcript = canonical_transcript(transcript, "alignment transcript")
    if not checked_transcript:
        raise AlignmentUnavailable(AlignmentUnavailableReason.EMPTY_TRANSCRIPT)
    if (
        isinstance(first_word_index, bool)
        or not isinstance(first_word_index, int)
        or not 0 <= first_word_index < MAX_ALIGNMENT_WORDS
        or isinstance(source_start_sample, bool)
        or not isinstance(source_start_sample, int)
        or source_start_sample < 0
    ):
        raise AlignmentUnavailable(AlignmentUnavailableReason.EVIDENCE_INVALID)

    pieces = _checked_token_pieces(token_pieces)
    spans = _word_spans(pieces, checked_transcript)
    if first_word_index + len(spans) > MAX_ALIGNMENT_WORDS:
        raise AlignmentUnavailable(AlignmentUnavailableReason.WORD_LIMIT)

    encoder_frames = valid_encoder_frame_count(source_frame_count)
    if (
        isinstance(content_token_offset, bool)
        or not isinstance(content_token_offset, int)
        or content_token_offset < 1
        or content_token_offset + len(pieces) >= len(score_matrix)
    ):
        raise AlignmentUnavailable(AlignmentUnavailableReason.EVIDENCE_INVALID)
    matrix = _checked_score_matrix(
        score_matrix,
        encoder_frame_count=encoder_frames,
    )
    token_start_frames = _dtw_token_start_frames(matrix)

    # Round both sides of a chunk boundary in the same direction. Energy-based
    # chunk splits are sample-exact but need not land on a whole millisecond;
    # ceiling both adjacent boundaries prevents an artificial 1 ms overlap when
    # independently aligned chunks are reassembled.
    source_start_ms = _sample_offset_ms(source_start_sample)
    source_end_sample = source_start_sample + source_frame_count
    source_end_ms = _sample_offset_ms(source_end_sample)
    words: list[AlignedWordEvidence] = []
    for index, span in enumerate(spans):
        start_ms = min(
            source_end_ms,
            source_start_ms
            + token_start_frames[content_token_offset + span.first_token]
            * ALIGNMENT_ENCODER_FRAME_MS,
        )
        if index + 1 < len(spans):
            end_ms = min(
                source_end_ms,
                source_start_ms
                + token_start_frames[
                    content_token_offset + spans[index + 1].first_token
                ]
                * ALIGNMENT_ENCODER_FRAME_MS,
            )
        else:
            end_ms = min(
                source_end_ms,
                source_start_ms
                + token_start_frames[content_token_offset + len(pieces)]
                * ALIGNMENT_ENCODER_FRAME_MS,
            )
        if end_ms <= start_ms or (words and start_ms < words[-1].end_ms):
            raise AlignmentUnavailable(AlignmentUnavailableReason.EVIDENCE_INVALID)
        words.append(
            AlignedWordEvidence(
                word_index=first_word_index + index,
                text=span.text,
                start_ms=start_ms,
                end_ms=end_ms,
            )
        )
    return tuple(words)


def _checked_token_pieces(value: Sequence[str]) -> tuple[str, ...]:
    if (
        isinstance(value, (str, bytes, bytearray))
        or not isinstance(value, Sequence)
        or not 1 <= len(value) <= MAX_ALIGNMENT_TOKENS
    ):
        raise AlignmentUnavailable(AlignmentUnavailableReason.TOKEN_LIMIT)
    pieces: list[str] = []
    for piece in value:
        if (
            not isinstance(piece, str)
            or not piece
            or len(piece.encode("utf-8")) > MAX_ALIGNMENT_WORD_TEXT_BYTES
            or piece.startswith("<|")
            or piece in {"<unk>", "<pad>", "<s>", "</s>"}
        ):
            raise AlignmentUnavailable(
                AlignmentUnavailableReason.TOKEN_TRANSCRIPT_DIVERGED
            )
        pieces.append(piece)
    return tuple(pieces)


def _word_spans(
    pieces: Sequence[str],
    transcript: str,
) -> tuple[_WordTokenSpan, ...]:
    spans: list[_WordTokenSpan] = []
    text = ""
    first_token = 0
    for index, piece in enumerate(pieces):
        begins_word = piece.startswith("▁")
        rendered_piece = piece.lstrip("▁") if begins_word else piece
        if index == 0 and not begins_word:
            raise AlignmentUnavailable(
                AlignmentUnavailableReason.TOKEN_TRANSCRIPT_DIVERGED
            )
        if begins_word and index > 0:
            _append_word_span(spans, text, first_token)
            text = ""
            first_token = index
        text += rendered_piece
    _append_word_span(spans, text, first_token)
    if " ".join(span.text for span in spans) != transcript:
        raise AlignmentUnavailable(
            AlignmentUnavailableReason.TOKEN_TRANSCRIPT_DIVERGED
        )
    return tuple(spans)


def _append_word_span(
    spans: list[_WordTokenSpan],
    text: str,
    first_token: int,
) -> None:
    if (
        not text
        or len(text.encode("utf-8")) > MAX_ALIGNMENT_WORD_TEXT_BYTES
        or len(spans) >= MAX_ALIGNMENT_WORDS
    ):
        raise AlignmentUnavailable(AlignmentUnavailableReason.WORD_LIMIT)
    spans.append(
        _WordTokenSpan(
            text=text,
            first_token=first_token,
        )
    )


def _sample_offset_ms(sample_offset: int) -> int:
    return (sample_offset * 1_000 + 16_000 - 1) // 16_000


def _checked_score_matrix(
    value: Sequence[Sequence[float]],
    *,
    encoder_frame_count: int,
) -> tuple[tuple[float, ...], ...]:
    if (
        isinstance(value, (str, bytes, bytearray))
        or not isinstance(value, Sequence)
        or not 3 <= len(value) <= MAX_ALIGNMENT_MATRIX_TOKENS
    ):
        raise AlignmentUnavailable(AlignmentUnavailableReason.EVIDENCE_INVALID)
    rows: list[tuple[float, ...]] = []
    minimum = math.inf
    maximum = -math.inf
    for raw_row in value:
        if (
            isinstance(raw_row, (str, bytes, bytearray))
            or not isinstance(raw_row, Sequence)
            or len(raw_row) != encoder_frame_count
        ):
            raise AlignmentUnavailable(AlignmentUnavailableReason.EVIDENCE_INVALID)
        row: list[float] = []
        for raw_score in raw_row:
            if isinstance(raw_score, bool) or not isinstance(raw_score, (int, float)):
                raise AlignmentUnavailable(
                    AlignmentUnavailableReason.EVIDENCE_INVALID
                )
            score = float(raw_score)
            if not math.isfinite(score):
                raise AlignmentUnavailable(
                    AlignmentUnavailableReason.EVIDENCE_INVALID
                )
            minimum = min(minimum, score)
            maximum = max(maximum, score)
            row.append(score)
        rows.append(tuple(row))
    if maximum - minimum <= 1e-6:
        raise AlignmentUnavailable(AlignmentUnavailableReason.EVIDENCE_INVALID)
    return tuple(rows)


def _dtw_token_start_frames(
    score_matrix: Sequence[Sequence[float]],
) -> tuple[int, ...]:
    token_count = len(score_matrix)
    frame_count = len(score_matrix[0])
    infinity = math.inf
    previous_cost = [infinity] * (frame_count + 1)
    previous_cost[0] = 0.0
    trace = [bytearray([255]) * (frame_count + 1) for _ in range(token_count + 1)]

    for token_index in range(1, token_count + 1):
        current_cost = [infinity] * (frame_count + 1)
        scores = score_matrix[token_index - 1]
        for frame_index in range(1, frame_count + 1):
            diagonal = previous_cost[frame_index - 1]
            vertical = previous_cost[frame_index]
            horizontal = current_cost[frame_index - 1]
            if diagonal < vertical and diagonal < horizontal:
                prior = diagonal
                direction = 0
            elif vertical < diagonal and vertical < horizontal:
                prior = vertical
                direction = 1
            else:
                prior = horizontal
                direction = 2
            current_cost[frame_index] = -scores[frame_index - 1] + prior
            trace[token_index][frame_index] = direction
        previous_cost = current_cost

    token_index = token_count
    frame_index = frame_count
    reverse_path: list[tuple[int, int]] = []
    while token_index > 0 or frame_index > 0:
        reverse_path.append((token_index - 1, frame_index - 1))
        if token_index == 0:
            frame_index -= 1
            continue
        if frame_index == 0:
            token_index -= 1
            continue
        direction = trace[token_index][frame_index]
        if direction == 0:
            token_index -= 1
            frame_index -= 1
        elif direction == 1:
            token_index -= 1
        elif direction == 2:
            frame_index -= 1
        else:
            raise AlignmentUnavailable(AlignmentUnavailableReason.EVIDENCE_INVALID)

    path = reversed(reverse_path)
    starts: list[int] = []
    previous_token: int | None = None
    for aligned_token, aligned_frame in path:
        if aligned_token != previous_token:
            starts.append(aligned_frame)
            previous_token = aligned_token
    if (
        len(starts) != token_count
        or any(not 0 <= frame < frame_count for frame in starts)
        or any(later < earlier for earlier, later in zip(starts, starts[1:]))
    ):
        raise AlignmentUnavailable(AlignmentUnavailableReason.EVIDENCE_INVALID)
    return tuple(starts)
