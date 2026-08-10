from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from yap_server.auth.principal import PrincipalKey
from yap_server.knowledge.okf_compiler import compile_okf_bundle
from yap_server.knowledge.reviewed_meeting_knowledge import (
    KnowledgeSourceReview,
    render_reviewed_meeting_concept,
    result_revision_sha256,
)

from tests.jobs.service_fixtures import _published_result


class ReviewedMeetingKnowledgeTests(unittest.TestCase):
    def test_authoritative_reviewed_result_compiles_with_review_identity(self) -> None:
        job = {
            "sessionId": "session-1",
            "captureManifest": {"sha256": "a" * 64},
        }
        result = _published_result(job)
        review = KnowledgeSourceReview(
            reviewer=PrincipalKey("tenant-a", "alice"),
            job_id="job-1",
            title="Architecture review",
            reviewed_at_utc="2026-08-09T13:00:00Z",
            result_revision_sha256=result_revision_sha256(result),
            decision="accepted",
        )
        concept = render_reviewed_meeting_concept(
            result,
            projection=job,
            tenant_id="tenant-a",
            owner=PrincipalKey("tenant-a", "alice"),
            review=review,
        )

        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "index.md").write_text(
                "---\nokf_version: '0.1'\n---\n# Knowledge\n",
                encoding="utf-8",
            )
            (root / "meetings").mkdir()
            (root / "meetings" / "job-1.md").write_text(concept, encoding="utf-8")
            (root / "permissions").mkdir()
            (root / "permissions" / "meetings.yml").write_text(
                """path_prefix: meetings/
audience: {users: [{tenant_id: tenant-a, subject_id: alice}]}
purposes: [knowledge.read]
classification: confidential
denials: {users: []}
""",
                encoding="utf-8",
            )
            generation = compile_okf_bundle(
                root,
                tenant_id="tenant-a",
                source_revision="commit-a",
            )

        self.assertEqual(len(generation.concepts), 1)
        self.assertEqual(generation.concepts[0].concept_id, "meetings/job-1")
        self.assertIn(
            "crash-safe private transcript",
            " ".join(chunk.text for chunk in generation.chunks).casefold(),
        )
        self.assertEqual(
            generation.concepts[0].frontmatter["provenance"]["result_sha256"],
            review.result_revision_sha256,
        )
        self.assertEqual(
            generation.concepts[0].frontmatter["provenance"]["review_sha256"],
            review.review_sha256,
        )

        unauthorized_review = KnowledgeSourceReview(
            reviewer=PrincipalKey("tenant-a", "bob"),
            job_id="job-1",
            title="Architecture review",
            reviewed_at_utc="2026-08-09T13:00:00Z",
            result_revision_sha256=result_revision_sha256(result),
            decision="accepted",
        )
        with self.assertRaisesRegex(PermissionError, "owning principal"):
            render_reviewed_meeting_concept(
                result,
                projection=job,
                tenant_id="tenant-a",
                owner=PrincipalKey("tenant-a", "alice"),
                review=unauthorized_review,
            )


if __name__ == "__main__":
    unittest.main()
