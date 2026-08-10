from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from yap_server.auth.principal import PrincipalKey
from yap_server.knowledge.terminology_projections import (
    compile_grammar_preservation_constraints,
    compile_provider_terminology,
    normalize_with_terminology,
    render_glossary_concepts,
)
from yap_server.knowledge.terminology_snapshot import (
    TerminologyRecord,
    freeze_terminology_snapshot,
)
from yap_server.knowledge.okf_compiler import compile_okf_bundle


class TerminologySnapshotTests(unittest.TestCase):
    def test_freezes_precedence_locale_and_deletion_into_one_snapshot(self) -> None:
        records = (
            _record("org-okf", "organization", "tenant-a", "OKF", ("okf",)),
            _record("team-okf", "team", "team-1", "OpenKF", ("okf",)),
            _record(
                "personal-okf", "personal", "alice", "Open Knowledge Format", ("okf",)
            ),
            _record(
                "deleted", "personal", "alice", "Legacy", ("legacy",), deleted=True
            ),
        )

        snapshot = freeze_terminology_snapshot(
            records,
            principal=PrincipalKey("tenant-a", "alice"),
            team_ids=("team-1",),
            locale="en-US",
            source_revision="terminology-revision-7",
        )
        repeated = freeze_terminology_snapshot(
            records,
            principal=PrincipalKey("tenant-a", "alice"),
            team_ids=("team-1",),
            locale="en-US",
            source_revision="terminology-revision-7",
        )

        self.assertEqual(snapshot, repeated)
        self.assertEqual(snapshot.variant_map, {"okf": "Open Knowledge Format"})
        self.assertNotIn("legacy", snapshot.variant_map)

    def test_one_snapshot_drives_bounded_hints_normalization_and_glossary(self) -> None:
        snapshot = freeze_terminology_snapshot(
            (
                _record(
                    "org-tavi",
                    "organization",
                    "tenant-a",
                    "TAVI",
                    ("tavi", "transcatheter aortic valve implantation"),
                ),
            ),
            principal=PrincipalKey("tenant-a", "alice"),
            team_ids=(),
            locale="en-US",
            source_revision="terminology-revision-8",
        )

        hints = compile_provider_terminology(
            snapshot,
            supports_context=True,
            maximum_entries=4,
            maximum_characters=100,
        )
        normalized = normalize_with_terminology(snapshot, "tavi planning")
        grammar = compile_grammar_preservation_constraints(snapshot)
        glossary = render_glossary_concepts(snapshot)

        self.assertEqual(hints.terms, ("TAVI",))
        self.assertEqual(hints.snapshot_sha256, snapshot.snapshot_sha256)
        self.assertEqual(normalized.raw_text, "tavi planning")
        self.assertEqual(normalized.normalized_text, "TAVI planning")
        self.assertEqual(normalized.edits[0].replacement, "TAVI")
        self.assertEqual(grammar.exact_forms, ("TAVI",))
        self.assertEqual(grammar.snapshot_sha256, snapshot.snapshot_sha256)
        self.assertEqual(len(glossary), 1)
        self.assertIn("type: Term", glossary[0].document)
        self.assertIn(snapshot.snapshot_sha256, glossary[0].document)

        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "index.md").write_text(
                "---\nokf_version: '0.1'\n---\n# Knowledge\n", encoding="utf-8"
            )
            (root / "jargon_glossary").mkdir()
            (root / glossary[0].relative_path).write_text(
                glossary[0].document, encoding="utf-8"
            )
            (root / "permissions").mkdir()
            (root / glossary[0].permission_relative_path).write_text(
                glossary[0].permission_document,
                encoding="utf-8",
            )
            generation = compile_okf_bundle(
                root,
                tenant_id="tenant-a",
                source_revision="terminology-revision-8",
            )
        self.assertEqual(generation.concepts[0].frontmatter["type"], "Term")
        self.assertEqual(generation.permissions[0].classification, "internal")
        self.assertEqual(
            generation.permissions[0].audience,
            (PrincipalKey("tenant-a", "alice"),),
        )

    def test_rejects_equal_precedence_conflicts_and_unsupported_provider_context(
        self,
    ) -> None:
        records = (
            _record("one", "personal", "alice", "First", ("same",)),
            _record("two", "personal", "alice", "Second", ("same",)),
        )
        with self.assertRaisesRegex(ValueError, "conflicting terminology"):
            freeze_terminology_snapshot(
                records,
                principal=PrincipalKey("tenant-a", "alice"),
                team_ids=(),
                locale="en-US",
                source_revision="terminology-revision-9",
            )

        snapshot = freeze_terminology_snapshot(
            (_record("one", "personal", "alice", "First", ("first",)),),
            principal=PrincipalKey("tenant-a", "alice"),
            team_ids=(),
            locale="en-US",
            source_revision="terminology-revision-10",
        )
        with self.assertRaisesRegex(ValueError, "does not support terminology"):
            compile_provider_terminology(
                snapshot,
                supports_context=False,
                maximum_entries=4,
                maximum_characters=100,
            )


def _record(
    record_id: str,
    scope: str,
    owner_id: str,
    canonical_form: str,
    variants: tuple[str, ...],
    *,
    deleted: bool = False,
) -> TerminologyRecord:
    return TerminologyRecord(
        record_id=record_id,
        tenant_id="tenant-a",
        scope=scope,
        owner_id=owner_id,
        locale="en-US",
        canonical_form=canonical_form,
        variants=variants,
        sensitivity="internal",
        version=1,
        deleted=deleted,
        audit_revision=f"audit-{record_id}",
        changed_at="2026-08-09T12:00:00Z",
    )


if __name__ == "__main__":
    unittest.main()
