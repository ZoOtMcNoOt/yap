from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
import unittest

from yap_server.agents.auditor import (
    AuditorEvidencePack,
    AuditorRequest,
    build_auditor_report,
    validate_auditor_report,
)
from yap_server.agents.auditor_model import AuditorDecision, AuditorFindingSelection
from yap_server.agents.librarian import LibrarianEvidenceItem


def _item(index: int) -> LibrarianEvidenceItem:
    text = f"Reviewed statement {index}."
    return LibrarianEvidenceItem(
        concept_id=f"concept-{index}",
        source_revision="revision-1",
        content_sha256=f"{index + 1:064x}",
        char_start=0,
        char_end=len(text),
        text=text,
    )


def _evidence() -> AuditorEvidencePack:
    return AuditorEvidencePack.create(
        generation_sha256="a" * 64,
        source_admission_sha256="b" * 64,
        permission_hash="c" * 64,
        authorization_hash="d" * 64,
        items=(_item(0), _item(1), _item(2)),
        output_budget_exhausted=False,
    )


class AuditorDomainTests(unittest.TestCase):
    def test_request_wire_is_exact_and_server_owned_fields_are_absent(self) -> None:
        request = AuditorRequest.from_wire(
            {
                "schemaVersion": 1,
                "focus": "release policy conflict",
                "maximumFindings": 2,
                "expectedGenerationSha256": None,
            }
        )
        self.assertEqual(
            request.to_wire(),
            {
                "schemaVersion": 1,
                "focus": "release policy conflict",
                "maximumFindings": 2,
                "expectedGenerationSha256": None,
            },
        )
        for field in ("tenantId", "subjectId", "route", "purpose", "citations"):
            with self.subTest(field=field):
                wire = request.to_wire() | {field: "forged"}
                with self.assertRaises(ValueError):
                    AuditorRequest.from_wire(wire)

    def test_evidence_binds_current_source_admission_and_exact_items(self) -> None:
        evidence = _evidence()
        self.assertEqual(evidence.source_admission_sha256, "b" * 64)
        self.assertEqual(len(evidence.items), 3)
        with self.assertRaises(ValueError):
            replace(evidence, source_admission_sha256="e" * 64)
        with self.assertRaises(ValueError):
            replace(evidence, items=(evidence.items[0], evidence.items[0]))

    def test_server_canonicalizes_pairs_and_derives_review_only_findings(self) -> None:
        request = AuditorRequest("release policy conflict", 3, "a" * 64)
        evidence = _evidence()
        decision = AuditorDecision(
            "report",
            (
                AuditorFindingSelection(2, 0),
                AuditorFindingSelection(2, 1),
            ),
        )
        report = build_auditor_report(request, evidence, decision)
        self.assertIsNotNone(report)
        assert report is not None
        self.assertEqual(
            tuple(
                tuple(evidence.items.index(item) for item in finding.citations)
                for finding in report.findings
            ),
            ((0, 2), (1, 2)),
        )
        self.assertTrue(
            all(
                finding.kind == "potential-contradiction" for finding in report.findings
            )
        )
        self.assertTrue(all(finding.requires_review for finding in report.findings))
        self.assertFalse(report.canonical)
        self.assertTrue(report.requires_review)
        self.assertNotIn("reasoning", report.to_wire())
        validate_auditor_report(request, evidence, report)

    def test_unavailable_has_no_report_and_forged_or_duplicate_pairs_reject(
        self,
    ) -> None:
        request = AuditorRequest("release policy conflict", 2, None)
        evidence = _evidence()
        self.assertIsNone(
            build_auditor_report(
                request,
                evidence,
                AuditorDecision("evidence-unavailable", ()),
            )
        )
        for pairs in (
            (SimpleNamespace(left_evidence_index=0, right_evidence_index=0),),
            (
                AuditorFindingSelection(0, 1),
                AuditorFindingSelection(1, 0),
            ),
            (SimpleNamespace(left_evidence_index=0, right_evidence_index=8),),
        ):
            with self.subTest(pairs=pairs):
                with self.assertRaises(ValueError):
                    build_auditor_report(
                        request,
                        evidence,
                        type(
                            "Decision",
                            (),
                            {"outcome": "report", "finding_pairs": pairs},
                        )(),
                    )


if __name__ == "__main__":
    unittest.main()
