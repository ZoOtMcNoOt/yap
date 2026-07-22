from __future__ import annotations

from io import BytesIO
import unittest
import zipfile

from yap_server.evaluation.european_parliament_reference import (
    parse_european_parliament_reference,
)


_DOCUMENT = """<?xml version="1.0" encoding="utf-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p>
      <w:r><w:rPr><w:b/></w:rPr><w:t>Speaker</w:t></w:r>
      <w:r><w:t xml:space="preserve"> – </w:t></w:r>
      <w:r><w:t>Spoken words.</w:t></w:r>
    </w:p>
    <w:p><w:r><w:t>Second paragraph.</w:t></w:r></w:p>
  </w:body>
</w:document>
"""


def _docx(document_xml: str = _DOCUMENT, *, unsafe_name: str | None = None) -> bytes:
    body = BytesIO()
    with zipfile.ZipFile(body, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("_rels/.rels", "<Relationships/>")
        archive.writestr("word/document.xml", document_xml)
        if unsafe_name is not None:
            archive.writestr(unsafe_name, "unsafe")
    return body.getvalue()


class EuropeanParliamentReferenceTests(unittest.TestCase):
    def test_parser_removes_structural_speaker_prefix_and_preserves_body(self) -> None:
        reference = parse_european_parliament_reference(_docx())

        self.assertEqual(reference.paragraph_count, 2)
        self.assertEqual(reference.speaker_prefix_characters, 9)
        self.assertEqual(
            reference.paragraphs,
            ("Spoken words.", "Second paragraph."),
        )
        self.assertEqual(reference.text, "Spoken words.\n\nSecond paragraph.")

    def test_parser_rejects_archive_path_escape(self) -> None:
        with self.assertRaisesRegex(ValueError, "entry is invalid"):
            parse_european_parliament_reference(_docx(unsafe_name="../escape"))

    def test_parser_rejects_active_xml_declarations(self) -> None:
        document = _DOCUMENT.replace(
            '<w:document',
            '<!DOCTYPE w:document [<!ENTITY x "unsafe">]><w:document',
        )

        with self.assertRaisesRegex(ValueError, "declarations are unsafe"):
            parse_european_parliament_reference(_docx(document))

    def test_parser_rejects_unstructured_speaker_prefix(self) -> None:
        not_bold = _DOCUMENT.replace("<w:rPr><w:b/></w:rPr>", "")
        without_separator = _DOCUMENT.replace(" – ", ": ")

        with self.assertRaisesRegex(ValueError, "speaker prefix is missing"):
            parse_european_parliament_reference(_docx(not_bold))
        with self.assertRaisesRegex(ValueError, "speaker separator is missing"):
            parse_european_parliament_reference(_docx(without_separator))


if __name__ == "__main__":
    unittest.main()
