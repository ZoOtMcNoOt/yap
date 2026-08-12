"""Load one bounded owner-private Scribe qualification corpus."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import stat
from typing import Sequence

from yap_server.agents.transcript_correction import (
    TranscriptCorrectionProposedEdit,
    TranscriptCorrectionRequest,
    TranscriptCorrectionTerminology,
    bind_transcript_correction_request,
    correction_request_sha256,
    parse_transcript_correction_response,
    protected_transcript_fact_values,
    validate_transcript_correction,
)
from yap_server.private_artifact import read_json_object_with_identity

from .transcript_correction_source_evidence import (
    TranscriptCorrectionSourceEvidence,
    load_private_transcript_correction_source_evidence,
)
from .transcript_scoring import score_transcript


_MAXIMUM_CORPUS_BYTES = 8 * 1024 * 1024
_MAXIMUM_CASES = 128
_MAXIMUM_REFERENCE_CHARACTERS = 32_768
_MAXIMUM_CRITICAL_TOKENS = 128
_MAXIMUM_TERM_RECORDS = 256
_MAXIMUM_REVIEWED_CORRECTION_EDITS = 8
_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_KINDS = frozenset({"real-asr", "safety-probe"})
_DISPOSITION_BASES = {
    "corrected": "reviewed-safe-correction",
    "source-preserved": "protected-reference-change",
    "unchanged": "reference-identical",
    "uncertain": "reviewed-unsafe-ambiguity",
}


@dataclass(frozen=True, slots=True)
class TranscriptCorrectionQualificationCase:
    case_id: str
    source_kind: str
    source_evidence_sha256: str | None
    source_evidence_case_id: str | None
    source_audio_sha256: str | None
    owner_id: str
    expected_disposition: str
    expected_disposition_basis: str
    request: TranscriptCorrectionRequest
    reference_text: str
    critical_tokens: tuple[str, ...]
    reviewed_correction_edits: tuple[TranscriptCorrectionProposedEdit, ...]


@dataclass(frozen=True, slots=True)
class TranscriptCorrectionQualificationTerm:
    record_id: str
    owner_id: str
    locale: str
    canonical_form: str
    variants: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TranscriptCorrectionQualificationCorpus:
    corpus_id: str
    corpus_sha256: str
    cases: tuple[TranscriptCorrectionQualificationCase, ...]
    terminology: tuple[TranscriptCorrectionQualificationTerm, ...]


def load_private_transcript_correction_corpus(
    path: Path,
    *,
    expected_sha256: str,
    repository_root: Path,
    source_evidence_paths: Sequence[Path],
) -> TranscriptCorrectionQualificationCorpus:
    """Read one exact private corpus without exposing its transcript content."""

    if _SHA256.fullmatch(expected_sha256) is None:
        raise ValueError("transcript correction corpus digest is invalid")
    root = repository_root.resolve(strict=True)
    requested = Path(path)
    absolute = Path(os.path.abspath(requested))
    if not requested.is_absolute() or requested != absolute or requested.is_symlink():
        raise ValueError("transcript correction corpus path must be absolute")
    resolved = requested.resolve(strict=True)
    if resolved != requested or resolved == root or root in resolved.parents:
        raise ValueError("transcript correction corpus must remain outside the repository")
    _require_private_path(resolved)
    value, identity = read_json_object_with_identity(
        resolved,
        maximum_bytes=_MAXIMUM_CORPUS_BYTES,
        field="transcript correction corpus",
        expected_sha256=expected_sha256,
    )
    if set(value) != {"schemaVersion", "corpusId", "cases", "terminology"}:
        raise ValueError("transcript correction corpus shape differs")
    if value["schemaVersion"] != 3 or isinstance(value["schemaVersion"], bool):
        raise ValueError("transcript correction corpus schema differs")
    corpus_id = _identifier(value["corpusId"], "corpus")
    raw_terms = value["terminology"]
    if not isinstance(raw_terms, list) or len(raw_terms) > _MAXIMUM_TERM_RECORDS:
        raise ValueError("transcript correction corpus terminology count is invalid")
    terminology = tuple(_term(item) for item in raw_terms)
    term_ids = {item.record_id for item in terminology}
    if len(term_ids) != len(terminology):
        raise ValueError("transcript correction corpus terminology is duplicated")
    terms_by_owner: dict[str, list[str]] = {}
    for term in terminology:
        terms_by_owner.setdefault(term.owner_id, []).append(term.canonical_form)
    raw_cases = value["cases"]
    if not isinstance(raw_cases, list) or not 1 <= len(raw_cases) <= _MAXIMUM_CASES:
        raise ValueError("transcript correction corpus case count is invalid")
    cases = tuple(_case(item, terms_by_owner=terms_by_owner) for item in raw_cases)
    case_ids = {item.case_id for item in cases}
    if len(case_ids) != len(cases):
        raise ValueError("transcript correction corpus case identity is duplicated")
    audio_ids = [
        item.source_audio_sha256
        for item in cases
        if item.source_kind == "real-asr"
    ]
    if len(set(audio_ids)) != len(audio_ids):
        raise ValueError("transcript correction real ASR audio identity is duplicated")
    source_evidence = load_private_transcript_correction_source_evidence(
        source_evidence_paths,
        repository_root=root,
    )
    _bind_real_asr_cases(cases, source_evidence)
    owners = {item.owner_id for item in cases}
    if any(item.owner_id not in owners for item in terminology):
        raise ValueError("transcript correction terminology owner is not exercised")
    return TranscriptCorrectionQualificationCorpus(
        corpus_id=corpus_id,
        corpus_sha256=identity,
        cases=cases,
        terminology=terminology,
    )


def _bind_real_asr_cases(
    cases: tuple[TranscriptCorrectionQualificationCase, ...],
    evidence: dict[str, TranscriptCorrectionSourceEvidence],
) -> None:
    real_cases = tuple(item for item in cases if item.source_kind == "real-asr")
    claimed_evidence = {item.source_evidence_sha256 for item in real_cases}
    if claimed_evidence != set(evidence):
        raise ValueError("transcript correction source evidence membership differs")
    for case in real_cases:
        source_file = evidence[str(case.source_evidence_sha256)]
        source = source_file.cases.get(str(case.source_evidence_case_id))
        segments = case.request.segments
        if (
            source is None
            or case.source_audio_sha256 != source.audio_sha256
            or case.request.source_text != source.hypothesis
            or case.reference_text != source.reference
            or case.request.language_bcp47 != source.language_bcp47
            or len(segments) != 1
            or segments[0].start_milliseconds != 0
            or segments[0].end_milliseconds != source.duration_milliseconds
        ):
            raise ValueError("transcript correction real ASR source binding differs")


def _case(
    value: object,
    *,
    terms_by_owner: dict[str, list[str]],
) -> TranscriptCorrectionQualificationCase:
    if not isinstance(value, dict) or set(value) != {
        "caseId",
        "sourceKind",
        "sourceEvidenceSha256",
        "sourceEvidenceCaseId",
        "sourceAudioSha256",
        "ownerId",
        "expectedDisposition",
        "expectedDispositionBasis",
        "request",
        "referenceText",
        "criticalTokens",
        "reviewedCorrectionEdits",
    }:
        raise ValueError("transcript correction corpus case shape differs")
    source_kind = value["sourceKind"]
    disposition = value["expectedDisposition"]
    if source_kind not in _SOURCE_KINDS:
        raise ValueError("transcript correction source kind is invalid")
    if disposition not in _DISPOSITION_BASES:
        raise ValueError("transcript correction disposition is invalid")
    disposition_basis = value["expectedDispositionBasis"]
    if disposition_basis != _DISPOSITION_BASES[disposition]:
        raise ValueError("transcript correction disposition basis differs")
    evidence_sha256 = value["sourceEvidenceSha256"]
    evidence_case_id = value["sourceEvidenceCaseId"]
    source_audio_sha256 = value["sourceAudioSha256"]
    if source_kind == "real-asr":
        if (
            not isinstance(evidence_sha256, str)
            or _SHA256.fullmatch(evidence_sha256) is None
            or not isinstance(evidence_case_id, str)
            or not evidence_case_id
            or len(evidence_case_id) > 128
            or any(character in evidence_case_id for character in "\r\n\0")
            or not isinstance(source_audio_sha256, str)
            or _SHA256.fullmatch(source_audio_sha256) is None
        ):
            raise ValueError("real ASR source evidence identity is invalid")
    elif (
        evidence_sha256 is not None
        or evidence_case_id is not None
        or source_audio_sha256 is not None
    ):
        raise ValueError("safety probe cannot claim real ASR source evidence")
    reference = _text(
        value["referenceText"],
        "reference",
        maximum=_MAXIMUM_REFERENCE_CHARACTERS,
    )
    raw_tokens = value["criticalTokens"]
    if (
        not isinstance(raw_tokens, list)
        or len(raw_tokens) > _MAXIMUM_CRITICAL_TOKENS
    ):
        raise ValueError("transcript correction critical tokens are invalid")
    tokens = tuple(_text(item, "critical token", maximum=512) for item in raw_tokens)
    if len(set(tokens)) != len(tokens):
        raise ValueError("transcript correction critical tokens are duplicated")
    owner_id = _identifier(value["ownerId"], "owner")
    request = TranscriptCorrectionRequest.from_wire(value["request"])
    reviewed_edits = _reviewed_correction_edits(
        value["reviewedCorrectionEdits"],
        source_kind=str(source_kind),
        disposition=str(disposition),
        request=request,
        reference=reference,
        approved_terminology=tuple(terms_by_owner.get(owner_id, ())),
    )
    return TranscriptCorrectionQualificationCase(
        case_id=_identifier(value["caseId"], "case"),
        source_kind=str(source_kind),
        source_evidence_sha256=evidence_sha256,
        source_evidence_case_id=evidence_case_id,
        source_audio_sha256=source_audio_sha256,
        owner_id=owner_id,
        expected_disposition=str(disposition),
        expected_disposition_basis=str(disposition_basis),
        request=request,
        reference_text=reference,
        critical_tokens=tokens,
        reviewed_correction_edits=reviewed_edits,
    )


def _reviewed_correction_edits(
    value: object,
    *,
    source_kind: str,
    disposition: str,
    request: TranscriptCorrectionRequest,
    reference: str,
    approved_terminology: tuple[str, ...],
) -> tuple[TranscriptCorrectionProposedEdit, ...]:
    if (
        not isinstance(value, list)
        or len(value) > _MAXIMUM_REVIEWED_CORRECTION_EDITS
    ):
        raise ValueError("transcript correction reviewed edit count is invalid")
    if source_kind == "real-asr" and disposition not in {
        "corrected",
        "source-preserved",
    }:
        raise ValueError("real ASR disposition is invalid")
    if source_kind == "safety-probe" and disposition not in {
        "unchanged",
        "uncertain",
    }:
        raise ValueError("safety-probe disposition is invalid")
    source = request.source_text
    source_errors = _word_errors(reference, source, request.language_bcp47)
    source_facts = protected_transcript_fact_values(source)
    reference_facts = protected_transcript_fact_values(reference)
    if disposition != "corrected":
        if value:
            raise ValueError("non-corrected case cannot claim reviewed edits")
        if disposition == "source-preserved" and (
            source == reference
            or source_errors == 0
            or source_facts == reference_facts
        ):
            raise ValueError("source-preserved disposition lacks protected mismatch")
        if disposition == "unchanged" and source != reference:
            raise ValueError("unchanged disposition reference differs")
        if disposition == "uncertain" and (
            source == reference
            or source_errors == 0
            or source_facts != reference_facts
        ):
            raise ValueError("uncertain disposition evidence differs")
        return ()
    if not value or source == reference:
        raise ValueError("corrected disposition lacks safe reference evidence")
    bound = bind_transcript_correction_request(
        request,
        TranscriptCorrectionTerminology(
            snapshot_sha256="0" * 64,
            exact_forms=approved_terminology,
        ),
    )
    response = parse_transcript_correction_response(
        {
            "schemaVersion": 2,
            "requestSha256": correction_request_sha256(bound),
            "sourceSha256": request.source_sha256,
            "uncertain": False,
            "edits": value,
        }
    )
    correction = validate_transcript_correction(bound, response)
    corrected_errors = _word_errors(
        reference,
        correction.corrected_text,
        request.language_bcp47,
    )
    if corrected_errors >= source_errors:
        raise ValueError("reviewed correction does not improve word error")
    return response.edits


def _word_errors(reference: str, candidate: str, language_bcp47: str) -> int:
    return score_transcript(
        reference,
        candidate,
        language_bcp47=language_bcp47,
        scoring_profile="word-primary-v1",
    ).normalized_word.errors


def _term(value: object) -> TranscriptCorrectionQualificationTerm:
    if not isinstance(value, dict) or set(value) != {
        "recordId",
        "ownerId",
        "locale",
        "canonicalForm",
        "variants",
    }:
        raise ValueError("transcript correction terminology shape differs")
    raw_variants = value["variants"]
    if not isinstance(raw_variants, list) or not 1 <= len(raw_variants) <= 32:
        raise ValueError("transcript correction terminology variants are invalid")
    variants = tuple(_text(item, "terminology variant", maximum=128) for item in raw_variants)
    if len(set(variants)) != len(variants):
        raise ValueError("transcript correction terminology variants are duplicated")
    return TranscriptCorrectionQualificationTerm(
        record_id=_identifier(value["recordId"], "terminology record"),
        owner_id=_identifier(value["ownerId"], "terminology owner"),
        locale=_text(value["locale"], "terminology locale", maximum=35),
        canonical_form=_text(
            value["canonicalForm"],
            "terminology canonical form",
            maximum=128,
        ),
        variants=variants,
    )


def _identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"transcript correction {field} identity is invalid")
    return value


def _text(value: object, field: str, *, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > maximum
        or "\0" in value
    ):
        raise ValueError(f"transcript correction {field} is invalid")
    return value


def _require_private_path(path: Path) -> None:
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ValueError("transcript correction corpus must be a regular file")
    if os.name != "posix":
        return
    if metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) & 0o077:
        raise ValueError("transcript correction corpus must be owner-private")
    parent = path.parent.lstat()
    if (
        stat.S_ISLNK(parent.st_mode)
        or not stat.S_ISDIR(parent.st_mode)
        or parent.st_uid != os.geteuid()
        or stat.S_IMODE(parent.st_mode) & 0o077
    ):
        raise ValueError("transcript correction corpus parent must be owner-private")


__all__ = [
    "TranscriptCorrectionQualificationCase",
    "TranscriptCorrectionQualificationCorpus",
    "TranscriptCorrectionQualificationTerm",
    "load_private_transcript_correction_corpus",
]
