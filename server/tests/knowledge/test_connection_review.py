from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from yap_server.knowledge.connection_review import verify_connection_review_package
from yap_server.knowledge.okf_compiler import compile_okf_bundle


FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures/okf/pinned-v0.1"
QUOTE = "知識🦀 approved café"


class ConnectionReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory(prefix="yap-review-check-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bundle = self.root / "bundle"
        shutil.copytree(FIXTURE_ROOT, self.bundle)
        original = self.bundle / "projects/voiceos.md"
        original.write_text(
            original.read_text(encoding="utf-8") + f"\n{QUOTE}\n", encoding="utf-8"
        )
        other = self.bundle / "projects/interface.md"
        other.write_text(
            original.read_text(encoding="utf-8")
            .replace(
                "resource: yap://tenant/fixture-tenant/project/voiceos",
                "resource: yap://tenant/fixture-tenant/project/interface",
            )
            .replace("title: VoiceOS", "title: Interface"),
            encoding="utf-8",
        )
        self.generation = compile_okf_bundle(
            self.bundle,
            tenant_id="fixture-tenant",
            source_revision="reviewed-1",
        )
        sources = []
        for concept in self.generation.concepts:
            start = concept.body.index(QUOTE)
            sources.append(
                {
                    "node": {
                        "conceptId": concept.concept_id,
                        "type": concept.frontmatter["type"],
                        "title": concept.frontmatter["title"],
                        "sourcePath": concept.source_path,
                        "sourceRevision": "reviewed-1",
                        "contentSha256": concept.content_sha256,
                    },
                    "citation": {
                        "conceptId": concept.concept_id,
                        "sourceRevision": "reviewed-1",
                        "contentSha256": concept.content_sha256,
                        "charStart": start,
                        "charEnd": start + len(QUOTE),
                    },
                    "text": QUOTE,
                }
            )
        self.package = {
            "schemaVersion": 1,
            "kind": "connection-review",
            "status": "proposed",
            "proposalId": "d" * 64,
            "generationSha256": self.generation.generation_sha256,
            "candidate": {
                "schemaVersion": 1,
                "sourceConceptId": sources[0]["node"]["conceptId"],
                "targetConceptId": sources[1]["node"]["conceptId"],
                "relationshipType": "supports",
                "rationale": "The cited sources support this proposal.",
            },
            "sources": sources,
        }
        self.path = self.root / "review.json"
        self.write_package(self.package)

    def write_package(self, value: object) -> None:
        self.path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    def verify(self, **context: str) -> dict[str, str | int]:
        return verify_connection_review_package(
            self.path,
            self.bundle,
            tenant_id=context.get("tenant_id", "fixture-tenant"),
            source_revision=context.get("source_revision", "reviewed-1"),
        )

    def snapshot(self) -> dict[str, bytes]:
        return {
            path.relative_to(self.root).as_posix(): path.read_bytes()
            for path in self.root.rglob("*")
            if path.is_file()
        }

    def test_exact_unicode_sources_return_content_free_receipt_without_mutation(
        self,
    ) -> None:
        before = self.snapshot()
        receipt = self.verify()
        self.assertEqual(
            receipt,
            {
                "schemaVersion": 1,
                "kind": "connection-review-validation",
                "status": "source-matched",
                "packageSha256": hashlib.sha256(self.path.read_bytes()).hexdigest(),
                "proposalId": "d" * 64,
                "generationSha256": self.generation.generation_sha256,
                "sourceCount": 2,
            },
        )
        self.assertNotIn(QUOTE, json.dumps(receipt, ensure_ascii=False))
        self.assertEqual(self.snapshot(), before)
        concept = self.generation.concepts[0]
        self.assertNotEqual(
            concept.content_sha256, hashlib.sha256(concept.body.encode()).hexdigest()
        )

    def test_unsupported_status_extra_fields_duplicate_keys_and_bad_identity_fail(
        self,
    ) -> None:
        for change in [
            {"status": "approved"},
            {"schemaVersion": True},
            {"schemaVersion": 2},
            {"kind": "published-connection"},
            {"proposalId": "D" * 64},
            {"permissionHash": "a" * 64},
            {"ownerId": "forged"},
        ]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.write_package({**self.package, **change})
                self.verify()
        self.path.write_text('{"schemaVersion":1,"schemaVersion":1}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.verify()

    def test_candidate_and_sources_must_describe_exactly_two_distinct_endpoints(
        self,
    ) -> None:
        for change in [
            {"schemaVersion": True},
            {"canonical": True},
            {"relationshipType": "has spaces"},
            {"sourceConceptId": "foreign"},
            {"targetConceptId": self.package["candidate"]["sourceConceptId"]},
        ]:
            value = copy.deepcopy(self.package)
            value["candidate"].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.write_package(value)
                self.verify()
        for sources in [
            [],
            self.package["sources"][:1],
            [self.package["sources"][0]] * 2,
            self.package["sources"] + self.package["sources"][:1],
        ]:
            with self.subTest(sources=sources), self.assertRaises(ValueError):
                self.write_package({**self.package, "sources": sources})
                self.verify()

    def test_metadata_hash_revision_unicode_span_and_quote_cannot_be_substituted(
        self,
    ) -> None:
        for section, field, replacement in [
            ("node", "title", "Forged title"),
            ("node", "sourcePath", "../../outside.md"),
            ("node", "contentSha256", "f" * 64),
            ("node", "type", "Other"),
            ("citation", "sourceRevision", "different"),
            ("citation", "contentSha256", "f" * 64),
            ("citation", "charStart", True),
            ("citation", "charEnd", 1_000_001),
            (
                "citation",
                "charEnd",
                self.package["sources"][0]["citation"]["charEnd"] + 1,
            ),
            ("citation", "authority", "human_confirmed"),
        ]:
            value = copy.deepcopy(self.package)
            value["sources"][0][section][field] = replacement
            with (
                self.subTest(section=section, field=field),
                self.assertRaises(ValueError),
            ):
                self.write_package(value)
                self.verify()
        value = copy.deepcopy(self.package)
        value["sources"][0]["text"] = "different quote"
        self.write_package(value)
        with self.assertRaises(ValueError):
            self.verify()

    def test_complete_bundle_including_frontmatter_and_policy_must_match_generation(
        self,
    ) -> None:
        for relative in ["projects/voiceos.md", "permissions/projects.yml"]:
            path = self.bundle / relative
            original = path.read_bytes()
            replacement = (
                original.replace(b"title: VoiceOS", b"title: Changed")
                if relative.endswith(".md")
                else original.replace(
                    b"classification: internal", b"classification: confidential"
                )
            )
            path.write_bytes(replacement)
            with (
                self.subTest(relative=relative),
                self.assertRaisesRegex(ValueError, "generation"),
            ):
                self.verify()
            path.write_bytes(original)
        path = self.bundle / "projects/voiceos.md"
        path.write_text(
            path.read_text(encoding="utf-8") + "\nChanged source body.\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "generation"):
            self.verify()

    def test_explicit_tenant_revision_and_bounded_regular_package_are_required(
        self,
    ) -> None:
        for context in [{"tenant_id": "foreign"}, {"source_revision": "different"}]:
            with self.subTest(context=context), self.assertRaises(ValueError):
                self.verify(**context)
        for payload in [
            b"x" * 65_537,
            b"\xff",
            b'{"nested":' + b"[" * 2_000 + b"]" * 2_000 + b"}",
        ]:
            self.path.write_bytes(payload)
            with self.subTest(size=len(payload)), self.assertRaises(ValueError):
                self.verify()
        self.path.unlink()
        self.path.mkdir()
        with self.assertRaises(ValueError):
            self.verify()

    def test_missing_and_linked_source_trees_are_refused(self) -> None:
        source = self.bundle / "projects/interface.md"
        saved = source.read_bytes()
        source.unlink()
        with self.assertRaises(ValueError):
            self.verify()
        source.write_bytes(saved)
        alias = self.bundle / "linked"
        if os.name == "nt":
            subprocess.run(
                [
                    "cmd.exe",
                    "/d",
                    "/c",
                    "mklink",
                    "/J",
                    str(alias),
                    str(self.bundle / "projects"),
                ],
                check=True,
                capture_output=True,
                timeout=10,
            )
        else:
            alias.symlink_to(self.bundle / "projects", target_is_directory=True)
        with self.assertRaises(ValueError):
            self.verify()
        # Remove the directory alias before TemporaryDirectory cleanup on Windows.
        if os.name == "nt":
            alias.rmdir()
        else:
            alias.unlink()
            source.unlink()
            source.symlink_to(self.bundle / "projects/voiceos.md")
            with self.assertRaises(ValueError):
                self.verify()

    def test_actual_operator_command_reports_match_or_safe_refusal(self) -> None:
        command = [
            sys.executable,
            "-m",
            "yap_server.knowledge.connection_review",
            str(self.path),
            "--bundle-root",
            str(self.bundle),
            "--tenant-id",
            "fixture-tenant",
            "--source-revision",
            "reviewed-1",
        ]
        before = self.snapshot()
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=20, check=False
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), self.verify())
        self.assertEqual(result.stderr, "")
        self.assertEqual(self.snapshot(), before)
        value = copy.deepcopy(self.package)
        value["candidate"]["rationale"] = QUOTE * 200
        self.write_package(value)
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=20, check=False
        )
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("could not be matched", result.stderr)
        self.assertNotIn(QUOTE, result.stderr)


if __name__ == "__main__":
    unittest.main()
