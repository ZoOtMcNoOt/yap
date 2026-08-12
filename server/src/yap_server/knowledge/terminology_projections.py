from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import PurePosixPath
import re

import yaml

from .terminology_snapshot import TerminologySnapshot


@dataclass(frozen=True, slots=True)
class ProviderTerminology:
    snapshot_sha256: str
    locale: str
    terms: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GrammarPreservationConstraints:
    snapshot_sha256: str
    locale: str
    exact_forms: tuple[str, ...]
    authorized_replacements: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class TerminologyEdit:
    raw_char_start: int
    raw_char_end: int
    original: str
    replacement: str
    snapshot_sha256: str


@dataclass(frozen=True, slots=True)
class TerminologyNormalization:
    raw_text: str
    normalized_text: str
    edits: tuple[TerminologyEdit, ...]


@dataclass(frozen=True, slots=True)
class RenderedGlossaryConcept:
    relative_path: PurePosixPath
    document: str
    permission_relative_path: PurePosixPath
    permission_document: str


def compile_provider_terminology(
    snapshot: TerminologySnapshot,
    *,
    supports_context: bool,
    maximum_entries: int,
    maximum_characters: int,
) -> ProviderTerminology:
    """Compile bounded model input; capability is explicit and fail-closed."""

    if not supports_context:
        raise ValueError("provider does not support terminology context")
    if not 1 <= maximum_entries <= 10_000 or not 1 <= maximum_characters <= 1_000_000:
        raise ValueError("provider terminology bounds are invalid")
    terms = tuple(sorted({item.canonical_form for item in snapshot.entries}))
    if len(terms) > maximum_entries or sum(map(len, terms)) > maximum_characters:
        raise ValueError("terminology snapshot exceeds provider bounds")
    return ProviderTerminology(
        snapshot_sha256=snapshot.snapshot_sha256,
        locale=snapshot.locale,
        terms=terms,
    )


def compile_grammar_preservation_constraints(
    snapshot: TerminologySnapshot,
) -> GrammarPreservationConstraints:
    return GrammarPreservationConstraints(
        snapshot_sha256=snapshot.snapshot_sha256,
        locale=snapshot.locale,
        exact_forms=tuple(sorted({item.canonical_form for item in snapshot.entries})),
        authorized_replacements=tuple(sorted(snapshot.variant_map.items())),
    )


def normalize_with_terminology(
    snapshot: TerminologySnapshot, raw_text: str
) -> TerminologyNormalization:
    """Create a reversible exact-form revision while retaining raw ASR text."""

    if not isinstance(raw_text, str) or len(raw_text) > 10_000_000:
        raise ValueError("terminology normalization input is invalid")
    if not snapshot.variant_map:
        return TerminologyNormalization(raw_text, raw_text, ())
    variants = sorted(snapshot.variant_map, key=lambda item: (-len(item), item))
    pattern = re.compile(
        r"(?<!\w)(?:" + "|".join(re.escape(item) for item in variants) + r")(?!\w)",
        re.IGNORECASE,
    )
    edits: list[TerminologyEdit] = []
    output: list[str] = []
    cursor = 0
    for match in pattern.finditer(raw_text):
        replacement = snapshot.variant_map[match.group(0).casefold()]
        output.extend((raw_text[cursor : match.start()], replacement))
        edits.append(
            TerminologyEdit(
                raw_char_start=match.start(),
                raw_char_end=match.end(),
                original=match.group(0),
                replacement=replacement,
                snapshot_sha256=snapshot.snapshot_sha256,
            )
        )
        cursor = match.end()
    output.append(raw_text[cursor:])
    return TerminologyNormalization(raw_text, "".join(output), tuple(edits))


def render_glossary_concepts(
    snapshot: TerminologySnapshot,
) -> tuple[RenderedGlossaryConcept, ...]:
    """Render approved snapshot entries as permission-governed Google OKF inputs."""

    rendered: list[RenderedGlossaryConcept] = []
    for record in snapshot.entries:
        projection_id = hashlib.sha256(record.record_id.encode("utf-8")).hexdigest()
        concept_path = f"jargon_glossary/{projection_id}"
        frontmatter = {
            "type": "Term",
            "title": record.canonical_form,
            "resource": (
                f"yap://tenant/{record.tenant_id}/terminology/{record.record_id}"
            ),
            "timestamp": record.changed_at,
            "yap_schema": 1,
            "provenance": {
                "source": "terminology-snapshot",
                "source_revision": snapshot.source_revision,
                "snapshot_sha256": snapshot.snapshot_sha256,
            },
            "locale": record.locale,
            "scope": record.scope,
            "owner_id": record.owner_id,
            "sensitivity": record.sensitivity,
            "term_version": record.version,
            "variants": list(record.variants),
        }
        yaml_body = yaml.safe_dump(frontmatter, sort_keys=True, allow_unicode=True)
        document = f"---\n{yaml_body}---\n# {record.canonical_form}\n"
        permission = {
            "path_prefix": f"{concept_path}/",
            "audience": {
                "users": [
                    {
                        "tenant_id": snapshot.tenant_id,
                        "subject_id": snapshot.subject_id,
                    }
                ]
            },
            "purposes": ["knowledge.read"],
            "classification": record.sensitivity,
            "denials": {"users": []},
        }
        rendered.append(
            RenderedGlossaryConcept(
                relative_path=PurePosixPath(f"{concept_path}.md"),
                document=document,
                permission_relative_path=PurePosixPath("permissions")
                / f"jargon-glossary-{projection_id}.yml",
                permission_document=yaml.safe_dump(
                    permission, sort_keys=True, allow_unicode=True
                ),
            )
        )
    return tuple(rendered)


__all__ = [
    "ProviderTerminology",
    "GrammarPreservationConstraints",
    "RenderedGlossaryConcept",
    "TerminologyEdit",
    "TerminologyNormalization",
    "compile_provider_terminology",
    "compile_grammar_preservation_constraints",
    "normalize_with_terminology",
    "render_glossary_concepts",
]
