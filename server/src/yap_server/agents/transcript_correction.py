from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import hashlib
import json
import re
from typing import Sequence


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SEGMENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_BCP47 = re.compile(
    r"^(?:und|[a-z]{2,3}(?:-[A-Z][a-z]{3})?(?:-(?:[A-Z]{2}|\d{3}))?"
    r"(?:-(?:[A-Za-z0-9]{5,8}|\d[A-Za-z0-9]{3}))*)$"
)
_NUMBER_OR_DATE = re.compile(r"(?<!\w)\d(?:[\d.,:/-]*\d)?(?!\w)")
_MEASUREMENT_UNIT = re.compile(
    r"(?<!\w)(?:mmol/L|mEq/L|mmHg|mcg|[\u00b5\u03bc]g|mg|kg|mL|IU|bpm|cm|mm|"
    r"units?|g|L|%|\u00b0[CF])(?!\w)",
    re.IGNORECASE,
)
_WORD = re.compile(r"[^\W\d_]+(?:[-'][^\W\d_]+)*", re.UNICODE)
_MAXIMUM_SEGMENTS = 64
_MAXIMUM_SEGMENT_CHARACTERS = 32_768
_MAXIMUM_SOURCE_CHARACTERS = 32_768
_MAXIMUM_EDITS = 128
_MAXIMUM_EDIT_SOURCE_CHARACTERS = 1_024
_MAXIMUM_EDIT_REPLACEMENT_CHARACTERS = 2_048
_SUPPORTED_LANGUAGE_BASES = frozenset({"en", "es"})
_NEGATIONS = frozenset(
    {
        "ain't",
        "cannot",
        "can't",
        "didn't",
        "doesn't",
        "don't",
        "hadn't",
        "hasn't",
        "haven't",
        "isn't",
        "never",
        "neither",
        "nor",
        "no",
        "not",
        "jamás",
        "jamas",
        "nadie",
        "ningún",
        "ningun",
        "ninguna",
        "nunca",
        "sin",
        "tampoco",
        "wasn't",
        "weren't",
        "won't",
        "wouldn't",
    }
)
_NUMBER_DATE_UNIT_WORDS = frozenset(
    {
        # English number words and scales.
        "zero",
        "one",
        "two",
        "three",
        "four",
        "five",
        "six",
        "seven",
        "eight",
        "nine",
        "ten",
        "eleven",
        "twelve",
        "thirteen",
        "fourteen",
        "fifteen",
        "sixteen",
        "seventeen",
        "eighteen",
        "nineteen",
        "twenty",
        "thirty",
        "forty",
        "fifty",
        "sixty",
        "seventy",
        "eighty",
        "ninety",
        "hundred",
        "thousand",
        "million",
        "millions",
        "billion",
        "billions",
        # Spanish number words and scales, including common unaccented ASR forms.
        "cero",
        "uno",
        "una",
        "dos",
        "tres",
        "cuatro",
        "cinco",
        "seis",
        "siete",
        "ocho",
        "nueve",
        "diez",
        "once",
        "doce",
        "trece",
        "catorce",
        "quince",
        "dieciséis",
        "dieciseis",
        "diecisiete",
        "dieciocho",
        "diecinueve",
        "veinte",
        "treinta",
        "cuarenta",
        "cincuenta",
        "sesenta",
        "setenta",
        "ochenta",
        "noventa",
        "cien",
        "ciento",
        "mil",
        "millón",
        "millon",
        "millones",
        "billón",
        "billon",
        "billones",
        # Calendar words are immutable because they can carry dates.
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
        "january",
        "february",
        "march",
        "april",
        "may",
        "june",
        "july",
        "august",
        "september",
        "october",
        "november",
        "december",
        "lunes",
        "martes",
        "miércoles",
        "miercoles",
        "jueves",
        "viernes",
        "sábado",
        "sabado",
        "domingo",
        "enero",
        "febrero",
        "marzo",
        "abril",
        "mayo",
        "junio",
        "julio",
        "agosto",
        "septiembre",
        "octubre",
        "noviembre",
        "diciembre",
        # Spoken measurement units.
        "gram",
        "grams",
        "milligram",
        "milligrams",
        "kilogram",
        "kilograms",
        "liter",
        "liters",
        "litre",
        "litres",
        "milliliter",
        "milliliters",
        "millilitre",
        "millilitres",
        "centimeter",
        "centimeters",
        "millimeter",
        "millimeters",
        "percent",
        "percentage",
        "degree",
        "degrees",
        "unit",
        "units",
        "gramo",
        "gramos",
        "miligramo",
        "miligramos",
        "kilogramo",
        "kilogramos",
        "litro",
        "litros",
        "mililitro",
        "mililitros",
        "centímetro",
        "centimetro",
        "centímetros",
        "centimetros",
        "milímetro",
        "milimetro",
        "milímetros",
        "milimetros",
        "porcentaje",
        "grado",
        "grados",
        "unidad",
        "unidades",
    }
)
_FILLER_WORDS = frozenset({"ah", "er", "hmm", "uh", "um"})
_MEDICATION_SUFFIXES = (
    "azole",
    "caine",
    "cillin",
    "cycline",
    "mab",
    "mycin",
    "nib",
    "olol",
    "oxetine",
    "prazole",
    "pril",
    "sartan",
    "statin",
    "vir",
    "zepam",
    "zolam",
)
_NON_NAME_CAPITALIZED_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "as",
        "at",
        "be",
        "been",
        "being",
        "but",
        "did",
        "do",
        "does",
        "for",
        "from",
        "he",
        "i",
        "in",
        "is",
        "it",
        "no",
        "not",
        "of",
        "on",
        "or",
        "she",
        "that",
        "the",
        "these",
        "they",
        "this",
        "those",
        "to",
        "uh",
        "um",
        "we",
        "were",
        "was",
        "with",
        "without",
        "you",
    }
)


@dataclass(frozen=True, slots=True)
class TranscriptCorrectionSegment:
    segment_id: str
    start_character: int
    end_character: int
    start_milliseconds: int
    end_milliseconds: int
    language_bcp47: str
    text: str
    text_sha256: str

    @classmethod
    def from_wire(cls, value: object) -> TranscriptCorrectionSegment:
        if not isinstance(value, dict) or set(value) != {
            "segmentId",
            "startCharacter",
            "endCharacter",
            "startMilliseconds",
            "endMilliseconds",
            "languageBcp47",
            "text",
            "textSha256",
        }:
            raise ValueError("transcript correction segment shape differs")
        segment_id = _bounded_text(value["segmentId"], "segment identity", 64)
        if _SEGMENT_ID.fullmatch(segment_id) is None:
            raise ValueError("transcript correction segment identity is invalid")
        start_character = _integer(value["startCharacter"], "segment start", minimum=0)
        end_character = _integer(value["endCharacter"], "segment end", minimum=1)
        text = _source_text(value["text"], "segment text", _MAXIMUM_SEGMENT_CHARACTERS)
        if end_character <= start_character or end_character - start_character != len(text):
            raise ValueError("transcript correction segment span differs")
        text_sha256 = _lower_sha256(value["textSha256"], "segment hash")
        if _sha256_text(text) != text_sha256:
            raise ValueError("transcript correction segment hash differs")
        language_bcp47 = _bounded_text(value["languageBcp47"], "segment language", 35)
        if _BCP47.fullmatch(language_bcp47) is None:
            raise ValueError("transcript correction segment language is invalid")
        start_milliseconds = _integer(
            value["startMilliseconds"], "segment start time", minimum=0
        )
        end_milliseconds = _integer(
            value["endMilliseconds"], "segment end time", minimum=1
        )
        if end_milliseconds <= start_milliseconds:
            raise ValueError("transcript correction segment timing differs")
        return cls(
            segment_id=segment_id,
            start_character=start_character,
            end_character=end_character,
            start_milliseconds=start_milliseconds,
            end_milliseconds=end_milliseconds,
            language_bcp47=language_bcp47,
            text=text,
            text_sha256=text_sha256,
        )

    def to_wire(self) -> dict[str, object]:
        return {
            "segmentId": self.segment_id,
            "startCharacter": self.start_character,
            "endCharacter": self.end_character,
            "startMilliseconds": self.start_milliseconds,
            "endMilliseconds": self.end_milliseconds,
            "languageBcp47": self.language_bcp47,
            "text": self.text,
            "textSha256": self.text_sha256,
        }


@dataclass(frozen=True, slots=True)
class TranscriptCorrectionRequest:
    source_revision_sha256: str
    source_sha256: str
    segments: tuple[TranscriptCorrectionSegment, ...]

    @property
    def source_text(self) -> str:
        return "".join(segment.text for segment in self.segments)

    @classmethod
    def from_wire(cls, value: object) -> TranscriptCorrectionRequest:
        if not isinstance(value, dict) or set(value) != {
            "schemaVersion",
            "sourceRevisionSha256",
            "sourceSha256",
            "segments",
        }:
            raise ValueError("transcript correction request shape differs")
        if value["schemaVersion"] != 1 or isinstance(value["schemaVersion"], bool):
            raise ValueError("transcript correction request schema differs")
        source_revision_sha256 = _lower_sha256(
            value["sourceRevisionSha256"],
            "source revision hash",
        )
        source_sha256 = _lower_sha256(value["sourceSha256"], "source hash")
        raw_segments = value["segments"]
        if (
            not isinstance(raw_segments, list)
            or not 1 <= len(raw_segments) <= _MAXIMUM_SEGMENTS
        ):
            raise ValueError("transcript correction segment count is invalid")
        segments = tuple(
            TranscriptCorrectionSegment.from_wire(segment) for segment in raw_segments
        )
        _validate_segment_sequence(segments)
        if any(
            segment.language_bcp47.split("-", 1)[0]
            not in _SUPPORTED_LANGUAGE_BASES
            for segment in segments
        ):
            raise ValueError("transcript correction language is unsupported")
        source_text = "".join(segment.text for segment in segments)
        if len(source_text) > _MAXIMUM_SOURCE_CHARACTERS:
            raise ValueError("transcript correction source is too large")
        if _sha256_text(source_text) != source_sha256:
            raise ValueError("transcript correction source hash differs")
        return cls(
            source_revision_sha256,
            source_sha256,
            segments,
        )

    def to_wire(self) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "sourceRevisionSha256": self.source_revision_sha256,
            "sourceSha256": self.source_sha256,
            "segments": [segment.to_wire() for segment in self.segments],
        }

    @property
    def language_bcp47(self) -> str:
        languages = {segment.language_bcp47 for segment in self.segments}
        return next(iter(languages)) if len(languages) == 1 else "und"


@dataclass(frozen=True, slots=True)
class TranscriptCorrectionTerminology:
    snapshot_sha256: str
    exact_forms: tuple[str, ...]

    def __post_init__(self) -> None:
        _lower_sha256(self.snapshot_sha256, "terminology snapshot hash")
        _validated_terminology(self.exact_forms)


@dataclass(frozen=True, slots=True)
class BoundTranscriptCorrectionRequest:
    source: TranscriptCorrectionRequest
    terminology: TranscriptCorrectionTerminology

    @property
    def source_revision_sha256(self) -> str:
        return self.source.source_revision_sha256

    @property
    def source_sha256(self) -> str:
        return self.source.source_sha256

    @property
    def source_text(self) -> str:
        return self.source.source_text

    @property
    def segments(self) -> tuple[TranscriptCorrectionSegment, ...]:
        return self.source.segments

    @property
    def approved_terminology(self) -> tuple[str, ...]:
        return self.terminology.exact_forms

    def to_wire(self) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "sourceRevisionSha256": self.source_revision_sha256,
            "sourceSha256": self.source_sha256,
            "terminologySnapshotSha256": self.terminology.snapshot_sha256,
            "approvedTerminology": list(self.approved_terminology),
            "segments": [segment.to_wire() for segment in self.segments],
        }


def bind_transcript_correction_request(
    request: TranscriptCorrectionRequest,
    terminology: TranscriptCorrectionTerminology,
) -> BoundTranscriptCorrectionRequest:
    if not isinstance(request, TranscriptCorrectionRequest):
        raise TypeError("transcript correction request type is invalid")
    if not isinstance(terminology, TranscriptCorrectionTerminology):
        raise TypeError("transcript correction terminology type is invalid")
    return BoundTranscriptCorrectionRequest(request, terminology)


@dataclass(frozen=True, slots=True)
class TranscriptCorrectionEdit:
    segment_id: str
    segment_sha256: str
    start_character: int
    end_character: int
    source_text: str
    replacement_text: str


@dataclass(frozen=True, slots=True)
class TranscriptCorrectionResponse:
    request_sha256: str
    source_sha256: str
    uncertain: bool
    edits: tuple[TranscriptCorrectionEdit, ...]


@dataclass(frozen=True, slots=True)
class ValidatedTranscriptCorrection:
    request_sha256: str
    uncertain: bool
    edits: tuple[TranscriptCorrectionEdit, ...]
    corrected_text: str


def correction_request_sha256(request: BoundTranscriptCorrectionRequest) -> str:
    if not isinstance(request, BoundTranscriptCorrectionRequest):
        raise TypeError("transcript correction request type is invalid")
    return hashlib.sha256(
        json.dumps(
            request.to_wire(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def parse_transcript_correction_response(
    value: object,
) -> TranscriptCorrectionResponse:
    if not isinstance(value, dict) or set(value) != {
        "schemaVersion",
        "requestSha256",
        "sourceSha256",
        "uncertain",
        "edits",
    }:
        raise ValueError("transcript correction response shape differs")
    if value["schemaVersion"] != 1 or isinstance(value["schemaVersion"], bool):
        raise ValueError("transcript correction response schema differs")
    uncertain = value["uncertain"]
    if not isinstance(uncertain, bool):
        raise TypeError("transcript correction uncertain flag must be boolean")
    raw_edits = value["edits"]
    if not isinstance(raw_edits, list) or len(raw_edits) > _MAXIMUM_EDITS:
        raise ValueError("transcript correction edit count is invalid")
    edits = tuple(_parse_edit(edit) for edit in raw_edits)
    if uncertain and edits:
        raise ValueError("transcript correction uncertain response must not contain edits")
    return TranscriptCorrectionResponse(
        request_sha256=_lower_sha256(value["requestSha256"], "request hash"),
        source_sha256=_lower_sha256(value["sourceSha256"], "source hash"),
        uncertain=uncertain,
        edits=edits,
    )


def validate_transcript_correction(
    request: BoundTranscriptCorrectionRequest,
    response: TranscriptCorrectionResponse,
) -> ValidatedTranscriptCorrection:
    if not isinstance(request, BoundTranscriptCorrectionRequest) or not isinstance(
        response,
        TranscriptCorrectionResponse,
    ):
        raise TypeError("transcript correction validation types are invalid")
    request_sha256 = correction_request_sha256(request)
    if (
        response.request_sha256 != request_sha256
        or response.source_sha256 != request.source_sha256
    ):
        raise ValueError("transcript correction response identity differs")
    terminology = request.approved_terminology
    segments_by_id = {segment.segment_id: segment for segment in request.segments}
    segment_order = {
        segment.segment_id: index for index, segment in enumerate(request.segments)
    }
    previous_key: tuple[int, int] | None = None
    previous_end_by_segment: dict[str, int] = {}
    changed_source_characters = 0
    for edit in response.edits:
        segment = segments_by_id.get(edit.segment_id)
        if segment is None or edit.segment_sha256 != segment.text_sha256:
            raise ValueError("transcript correction edit segment identity differs")
        if (
            edit.end_character > len(segment.text)
            or segment.text[edit.start_character : edit.end_character]
            != edit.source_text
        ):
            raise ValueError("transcript correction edit source differs")
        if not _is_bounded_correction(edit, terminology):
            raise ValueError("transcript correction edit is not a bounded correction")
        if not _preserves_medication_like_terms(edit, terminology):
            raise ValueError("transcript correction changed protected transcript facts")
        key = (segment_order[edit.segment_id], edit.start_character)
        if previous_key is not None and key < previous_key:
            raise ValueError("transcript correction edits must be ordered and non-overlapping")
        if edit.start_character < previous_end_by_segment.get(edit.segment_id, 0):
            raise ValueError("transcript correction edits must be ordered and non-overlapping")
        previous_key = key
        previous_end_by_segment[edit.segment_id] = edit.end_character
        changed_source_characters += len(edit.source_text)
    maximum_changed_characters = max(32, len(request.source_text) // 4)
    if changed_source_characters > maximum_changed_characters:
        raise ValueError("transcript correction edit coverage is too large")
    corrected_text = _apply_edits(request, response.edits)
    if _protected_facts(request.source_text) != _protected_facts(corrected_text):
        raise ValueError("transcript correction changed protected transcript facts")
    for term in terminology:
        if corrected_text.count(term) < request.source_text.count(term):
            raise ValueError("transcript correction changed protected transcript facts")
    return ValidatedTranscriptCorrection(
        request_sha256=request_sha256,
        uncertain=response.uncertain,
        edits=response.edits,
        corrected_text=corrected_text,
    )


def apply_validated_transcript_correction(
    request: BoundTranscriptCorrectionRequest,
    correction: ValidatedTranscriptCorrection,
) -> str:
    if not isinstance(request, BoundTranscriptCorrectionRequest) or not isinstance(
        correction,
        ValidatedTranscriptCorrection,
    ):
        raise TypeError("validated transcript correction types are invalid")
    if correction.request_sha256 != correction_request_sha256(request):
        raise ValueError("validated transcript correction source changed")
    return request.source_text if correction.uncertain else correction.corrected_text


def transcript_correction_response_schema() -> dict[str, object]:
    sha = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schemaVersion",
            "requestSha256",
            "sourceSha256",
            "uncertain",
            "edits",
        ],
        "properties": {
            "schemaVersion": {"type": "integer", "const": 1},
            "requestSha256": sha,
            "sourceSha256": sha,
            "uncertain": {"type": "boolean"},
            "edits": {
                "type": "array",
                "maxItems": _MAXIMUM_EDITS,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "segmentId",
                        "segmentSha256",
                        "startCharacter",
                        "endCharacter",
                        "sourceText",
                        "replacementText",
                    ],
                    "properties": {
                        "segmentId": {"type": "string", "maxLength": 64},
                        "segmentSha256": sha,
                        "startCharacter": {"type": "integer", "minimum": 0},
                        "endCharacter": {"type": "integer", "minimum": 1},
                        "sourceText": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": _MAXIMUM_EDIT_SOURCE_CHARACTERS,
                        },
                        "replacementText": {
                            "type": "string",
                            "maxLength": _MAXIMUM_EDIT_REPLACEMENT_CHARACTERS,
                        },
                    },
                },
            },
        },
    }


def validate_approved_terminology(values: Sequence[str]) -> tuple[str, ...]:
    return _validated_terminology(values)


def _parse_edit(value: object) -> TranscriptCorrectionEdit:
    if not isinstance(value, dict) or set(value) != {
        "segmentId",
        "segmentSha256",
        "startCharacter",
        "endCharacter",
        "sourceText",
        "replacementText",
    }:
        raise ValueError("transcript correction edit shape differs")
    segment_id = _bounded_text(value["segmentId"], "edit segment identity", 64)
    if _SEGMENT_ID.fullmatch(segment_id) is None:
        raise ValueError("transcript correction edit segment identity is invalid")
    start_character = _integer(value["startCharacter"], "edit start", minimum=0)
    end_character = _integer(value["endCharacter"], "edit end", minimum=1)
    if end_character <= start_character:
        raise ValueError("transcript correction edit span is invalid")
    source_text = _source_text(
        value["sourceText"],
        "edit source text",
        _MAXIMUM_EDIT_SOURCE_CHARACTERS,
    )
    if len(source_text) != end_character - start_character:
        raise ValueError("transcript correction edit span differs")
    replacement_text = value["replacementText"]
    if (
        not isinstance(replacement_text, str)
        or len(replacement_text) > _MAXIMUM_EDIT_REPLACEMENT_CHARACTERS
        or "\x00" in replacement_text
        or replacement_text == source_text
    ):
        raise ValueError("transcript correction replacement is invalid")
    if len(replacement_text) > len(source_text) * 2 + 32:
        raise ValueError("transcript correction replacement is too large")
    return TranscriptCorrectionEdit(
        segment_id=segment_id,
        segment_sha256=_lower_sha256(value["segmentSha256"], "edit segment hash"),
        start_character=start_character,
        end_character=end_character,
        source_text=source_text,
        replacement_text=replacement_text,
    )


def _validate_segment_sequence(
    segments: tuple[TranscriptCorrectionSegment, ...],
) -> None:
    expected_character = 0
    previous_end_milliseconds: int | None = None
    identities: set[str] = set()
    for segment in segments:
        if segment.segment_id in identities:
            raise ValueError("transcript correction segment identity is duplicated")
        identities.add(segment.segment_id)
        if segment.start_character != expected_character:
            raise ValueError("transcript correction segments must be contiguous")
        expected_character = segment.end_character
        if previous_end_milliseconds is not None and (
            segment.start_milliseconds < previous_end_milliseconds
        ):
            raise ValueError("transcript correction segment timing must be ordered")
        previous_end_milliseconds = segment.end_milliseconds


def _apply_edits(
    request: BoundTranscriptCorrectionRequest,
    edits: tuple[TranscriptCorrectionEdit, ...],
) -> str:
    edits_by_segment: dict[str, list[TranscriptCorrectionEdit]] = {}
    for edit in edits:
        edits_by_segment.setdefault(edit.segment_id, []).append(edit)
    corrected_segments: list[str] = []
    for segment in request.segments:
        position = 0
        corrected: list[str] = []
        for edit in edits_by_segment.get(segment.segment_id, []):
            corrected.append(segment.text[position : edit.start_character])
            corrected.append(edit.replacement_text)
            position = edit.end_character
        corrected.append(segment.text[position:])
        corrected_segments.append("".join(corrected))
    return "".join(corrected_segments)


def _protected_facts(
    text: str,
) -> tuple[
    tuple[str, ...],
    tuple[str, ...],
    tuple[str, ...],
    tuple[str, ...],
    tuple[str, ...],
]:
    numbers = tuple(match.group(0) for match in _NUMBER_OR_DATE.finditer(text))
    units = tuple(match.group(0) for match in _MEASUREMENT_UNIT.finditer(text))
    words = tuple(match.group(0) for match in _WORD.finditer(text))
    negations = tuple(word.casefold() for word in words if word.casefold() in _NEGATIONS)
    number_date_units = tuple(
        word.casefold()
        for word in words
        if word.casefold() in _NUMBER_DATE_UNIT_WORDS
    )
    names = tuple(
        word
        for word in words
        if word[0].isupper() and word.casefold() not in _NON_NAME_CAPITALIZED_WORDS
    )
    return numbers, units, negations, names, number_date_units


def _is_bounded_correction(
    edit: TranscriptCorrectionEdit,
    terminology: tuple[str, ...],
) -> bool:
    source = _lexical_identity(edit.source_text)
    replacement = _lexical_identity(edit.replacement_text)
    if source == replacement:
        return True
    source_words = tuple(word.casefold() for word in _WORD.findall(edit.source_text))
    replacement_words = tuple(
        word.casefold() for word in _WORD.findall(edit.replacement_text)
    )
    if not replacement:
        return not source_words or all(word in _FILLER_WORDS for word in source_words)
    if not source:
        return False
    similarity = SequenceMatcher(None, source, replacement, autojunk=False).ratio()
    approved_replacements = {_lexical_identity(term) for term in terminology}
    approved_replacement = replacement in approved_replacements
    if similarity < (0.35 if approved_replacement else 0.5) or len(
        replacement_words
    ) > len(source_words):
        return False
    word_changes = SequenceMatcher(
        None,
        source_words,
        replacement_words,
        autojunk=False,
    )
    for operation, source_start, source_end, replacement_start, replacement_end in (
        word_changes.get_opcodes()
    ):
        if operation == "equal":
            continue
        source_part = source_words[source_start:source_end]
        replacement_part = replacement_words[replacement_start:replacement_end]
        if operation == "delete":
            if not source_part or any(word not in _FILLER_WORDS for word in source_part):
                return False
            continue
        if operation == "insert" or len(source_part) != len(replacement_part):
            return False
        if any(
            SequenceMatcher(None, before, after, autojunk=False).ratio()
            < (0.35 if approved_replacement else 0.7)
            for before, after in zip(source_part, replacement_part, strict=True)
        ):
            return False
    return True


def _preserves_medication_like_terms(
    edit: TranscriptCorrectionEdit,
    terminology: tuple[str, ...],
) -> bool:
    source_terms = _medication_like_terms(edit.source_text)
    replacement_terms = _medication_like_terms(edit.replacement_text)
    if source_terms == replacement_terms:
        return True
    approved_replacements = {_lexical_identity(term) for term in terminology}
    return _lexical_identity(edit.replacement_text) in approved_replacements


def _medication_like_terms(value: str) -> tuple[str, ...]:
    return tuple(
        word.casefold()
        for word in _WORD.findall(value)
        if len(word) >= 5 and word.casefold().endswith(_MEDICATION_SUFFIXES)
    )


def _lexical_identity(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _validated_terminology(values: Sequence[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise TypeError("approved terminology must be a sequence")
    if len(values) > 128:
        raise ValueError("approved terminology is too large")
    result: list[str] = []
    for value in values:
        term = _bounded_text(value, "approved terminology", 128)
        if "\x00" in term or term in result:
            raise ValueError("approved terminology is invalid")
        result.append(term)
    return tuple(result)


def _source_text(value: object, field: str, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > maximum
        or "\x00" in value
    ):
        raise ValueError(f"transcript correction {field} is invalid")
    return value


def _bounded_text(value: object, field: str, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > maximum
        or value.strip() != value
        or not value.isprintable()
    ):
        raise ValueError(f"transcript correction {field} is invalid")
    return value


def _lower_sha256(value: object, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"transcript correction {field} is invalid")
    return value


def _integer(value: object, field: str, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"transcript correction {field} is invalid")
    return value


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


__all__ = [
    "BoundTranscriptCorrectionRequest",
    "TranscriptCorrectionEdit",
    "TranscriptCorrectionRequest",
    "TranscriptCorrectionResponse",
    "TranscriptCorrectionSegment",
    "TranscriptCorrectionTerminology",
    "ValidatedTranscriptCorrection",
    "apply_validated_transcript_correction",
    "bind_transcript_correction_request",
    "correction_request_sha256",
    "parse_transcript_correction_response",
    "transcript_correction_response_schema",
    "validate_approved_terminology",
    "validate_transcript_correction",
]
