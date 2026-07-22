from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
from pathlib import PurePosixPath
from xml.etree import ElementTree
import zipfile


_MAX_DOCX_BYTES = 2 * 1024 * 1024
_MAX_ARCHIVE_ENTRIES = 128
_MAX_ARCHIVE_UNCOMPRESSED_BYTES = 8 * 1024 * 1024
_MAX_DOCUMENT_XML_BYTES = 4 * 1024 * 1024
_MAX_PARAGRAPHS = 4_096
_MAX_REFERENCE_CHARACTERS = 262_144
_WORD_NAMESPACE = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_WORD = f"{{{_WORD_NAMESPACE}}}"
_SPEAKER_SEPARATOR = "\N{EN DASH}"
_MAX_SPEAKER_PREFIX_CHARACTERS = 128


@dataclass(frozen=True, slots=True)
class EuropeanParliamentReference:
    """Revised Parliament text with its non-spoken speaker label removed."""

    paragraph_count: int
    speaker_prefix_characters: int
    paragraphs: tuple[str, ...] = field(repr=False)

    @property
    def text(self) -> str:
        return "\n\n".join(self.paragraphs)


def parse_european_parliament_reference(
    document: bytes,
) -> EuropeanParliamentReference:
    """Extract bounded revised speech text from one source DOCX artifact."""

    if (
        not isinstance(document, bytes)
        or not 1 <= len(document) <= _MAX_DOCX_BYTES
    ):
        raise ValueError("European Parliament reference DOCX size is invalid")
    try:
        with zipfile.ZipFile(BytesIO(document)) as archive:
            members = archive.infolist()
            _validate_archive_members(members)
            names = {member.filename for member in members}
            required = {"[Content_Types].xml", "_rels/.rels", "word/document.xml"}
            if not required.issubset(names):
                raise ValueError(
                    "European Parliament reference DOCX structure is invalid"
                )
            document_member = archive.getinfo("word/document.xml")
            if not 1 <= document_member.file_size <= _MAX_DOCUMENT_XML_BYTES:
                raise ValueError(
                    "European Parliament reference document XML size is invalid"
                )
            document_xml = archive.read(document_member)
    except (zipfile.BadZipFile, KeyError, RuntimeError, EOFError) as error:
        raise ValueError("European Parliament reference DOCX is invalid") from error

    upper_xml = document_xml.upper()
    if b"<!DOCTYPE" in upper_xml or b"<!ENTITY" in upper_xml:
        raise ValueError("European Parliament reference XML declarations are unsafe")
    try:
        root = ElementTree.fromstring(document_xml)
    except ElementTree.ParseError as error:
        raise ValueError("European Parliament reference XML is invalid") from error

    paragraph_elements = tuple(root.iter(_WORD + "p"))
    if not 1 <= len(paragraph_elements) <= _MAX_PARAGRAPHS:
        raise ValueError("European Parliament reference paragraph count is invalid")
    paragraphs = tuple(
        text
        for paragraph in paragraph_elements
        if (text := _paragraph_text(paragraph).strip())
    )
    if not paragraphs:
        raise ValueError("European Parliament reference contains no speech text")
    body_first, prefix_characters = _remove_speaker_prefix(
        paragraph_elements[0],
        paragraphs[0],
    )
    body = (body_first, *paragraphs[1:])
    total_characters = sum(len(paragraph) for paragraph in body)
    if not 1 <= total_characters <= _MAX_REFERENCE_CHARACTERS:
        raise ValueError("European Parliament reference text size is invalid")
    return EuropeanParliamentReference(
        paragraph_count=len(body),
        speaker_prefix_characters=prefix_characters,
        paragraphs=body,
    )


def _validate_archive_members(members: list[zipfile.ZipInfo]) -> None:
    if not 1 <= len(members) <= _MAX_ARCHIVE_ENTRIES:
        raise ValueError("European Parliament reference DOCX entry count is invalid")
    seen: set[str] = set()
    total_size = 0
    for member in members:
        name = member.filename
        path = PurePosixPath(name)
        folded = name.casefold()
        if (
            not name
            or "\\" in name
            or path.is_absolute()
            or ".." in path.parts
            or folded in seen
            or member.flag_bits & 0x1
            or member.file_size < 0
            or member.compress_size < 0
        ):
            raise ValueError("European Parliament reference DOCX entry is invalid")
        seen.add(folded)
        total_size += member.file_size
        if total_size > _MAX_ARCHIVE_UNCOMPRESSED_BYTES:
            raise ValueError(
                "European Parliament reference DOCX expands beyond the bound"
            )


def _paragraph_text(paragraph: ElementTree.Element) -> str:
    parts: list[str] = []
    for element in paragraph.iter():
        if element.tag == _WORD + "t":
            parts.append(element.text or "")
        elif element.tag == _WORD + "tab":
            parts.append("\t")
        elif element.tag in {_WORD + "br", _WORD + "cr"}:
            parts.append("\n")
    return "".join(parts)


def _remove_speaker_prefix(
    first_paragraph: ElementTree.Element,
    text: str,
) -> tuple[str, int]:
    first_run = first_paragraph.find(_WORD + "r")
    if first_run is None or not _run_is_bold(first_run):
        raise ValueError("European Parliament reference speaker prefix is missing")
    separator_index = text.find(_SPEAKER_SEPARATOR)
    if not 1 <= separator_index < _MAX_SPEAKER_PREFIX_CHARACTERS:
        raise ValueError("European Parliament reference speaker separator is missing")
    prefix_characters = separator_index + len(_SPEAKER_SEPARATOR)
    body = text[prefix_characters:].strip()
    if not body:
        raise ValueError("European Parliament reference contains no speech body")
    return body, prefix_characters


def _run_is_bold(run: ElementTree.Element) -> bool:
    bold = run.find(f"{_WORD}rPr/{_WORD}b")
    if bold is None:
        return False
    value = bold.get(_WORD + "val")
    return value is None or value.casefold() not in {"0", "false", "off", "no"}
