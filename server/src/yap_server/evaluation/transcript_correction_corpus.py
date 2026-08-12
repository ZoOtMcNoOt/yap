"""Load one bounded owner-private Scribe qualification corpus."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import stat
from typing import Sequence

from yap_server.agents.transcript_correction import TranscriptCorrectionRequest
from yap_server.private_artifact import read_json_object_with_identity

from .transcript_correction_source_evidence import (
    TranscriptCorrectionSourceEvidence,
    load_private_transcript_correction_source_evidence,
)


_MAXIMUM_CORPUS_BYTES = 8 * 1024 * 1024
_MAXIMUM_CASES = 128
_MAXIMUM_REFERENCE_CHARACTERS = 32_768
_MAXIMUM_CRITICAL_TOKENS = 128
_MAXIMUM_TERM_RECORDS = 256
_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_KINDS = frozenset({"real-asr", "safety-probe"})
_DISPOSITIONS = frozenset({"corrected", "unchanged", "uncertain"})


@dataclass(frozen=True, slots=True)
class TranscriptCorrectionQualificationCase:
    case_id: str
    source_kind: str
    source_evidence_sha256: str | None
    source_evidence_case_id: str | None
    source_audio_sha256: str | None
    owner_id: str
    expected_disposition: str
    request: TranscriptCorrectionRequest
    reference_text: str
    critical_tokens: tuple[str, ...]


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
    if value["schemaVersion"] != 2 or isinstance(value["schemaVersion"], bool):
        raise ValueError("transcript correction corpus schema differs")
    corpus_id = _identifier(value["corpusId"], "corpus")
    raw_cases = value["cases"]
    if not isinstance(raw_cases, list) or not 1 <= len(raw_cases) <= _MAXIMUM_CASES:
        raise ValueError("transcript correction corpus case count is invalid")
    cases = tuple(_case(item) for item in raw_cases)
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
    raw_terms = value["terminology"]
    if not isinstance(raw_terms, list) or len(raw_terms) > _MAXIMUM_TERM_RECORDS:
        raise ValueError("transcript correction corpus terminology count is invalid")
    terminology = tuple(_term(item) for item in raw_terms)
    term_ids = {item.record_id for item in terminology}
    if len(term_ids) != len(terminology):
        raise ValueError("transcript correction corpus terminology is duplicated")
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


def _case(value: object) -> TranscriptCorrectionQualificationCase:
    if not isinstance(value, dict) or set(value) != {
        "caseId",
        "sourceKind",
        "sourceEvidenceSha256",
        "sourceEvidenceCaseId",
        "sourceAudioSha256",
        "ownerId",
        "expectedDisposition",
        "request",
        "referenceText",
        "criticalTokens",
    }:
        raise ValueError("transcript correction corpus case shape differs")
    source_kind = value["sourceKind"]
    disposition = value["expectedDisposition"]
    if source_kind not in _SOURCE_KINDS:
        raise ValueError("transcript correction source kind is invalid")
    if disposition not in _DISPOSITIONS:
        raise ValueError("transcript correction disposition is invalid")
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
    return TranscriptCorrectionQualificationCase(
        case_id=_identifier(value["caseId"], "case"),
        source_kind=str(source_kind),
        source_evidence_sha256=evidence_sha256,
        source_evidence_case_id=evidence_case_id,
        source_audio_sha256=source_audio_sha256,
        owner_id=_identifier(value["ownerId"], "owner"),
        expected_disposition=str(disposition),
        request=TranscriptCorrectionRequest.from_wire(value["request"]),
        reference_text=reference,
        critical_tokens=tokens,
    )


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
