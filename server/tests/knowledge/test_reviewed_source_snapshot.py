from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from yap_server.knowledge.knowledge_publication_service import (
    build_knowledge_publication_service,
)
from yap_server.knowledge.reviewed_source_snapshot import load_reviewed_source_snapshot
from yap_server.knowledge.okf_compiler import compile_okf_bundle
from tests.knowledge.test_postgres_generation_ledger import _tamper_bundle


class ReviewedSourceSnapshotTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.bundle = self.root / "reviewed-bundle"
        self.bundle.mkdir()
        _tamper_bundle(self.bundle, "tenant-a")
        self.generation = compile_okf_bundle(
            self.bundle, tenant_id="tenant-a", source_revision="reviewed-revision"
        )
        self.manifest = {
            "schemaVersion": 1,
            "tenantId": "tenant-a",
            "bundleRoot": str(self.bundle),
            "repositoryRevision": "reviewed-revision",
            "sourcePath": "knowledge/reviewed-bundle",
            "generationSha256": self.generation.generation_sha256,
        }
        self.path = self.root / "source.json"

    def write(self, value=None, *, raw=None):
        body = (
            raw
            if raw is not None
            else json.dumps(self.manifest if value is None else value).encode()
        )
        self.path.write_bytes(body)
        return hashlib.sha256(body).hexdigest()

    def test_actual_read_only_cli_bytes_digest_and_source_loading(self):
        before = {
            path.relative_to(self.bundle): path.read_bytes()
            for path in self.bundle.rglob("*")
            if path.is_file()
        }
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "yap_server.knowledge.reviewed_source_snapshot",
                "--bundle-root",
                str(self.bundle),
                "--tenant-id",
                "tenant-a",
                "--repository-revision",
                "reviewed-revision",
                "--source-path",
                "knowledge/reviewed-bundle",
            ],
            capture_output=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), self.manifest)
        self.assertIn(hashlib.sha256(result.stdout).hexdigest().encode(), result.stderr)
        self.assertIn(b"does not verify Git review or approval", result.stderr)
        self.path.write_bytes(result.stdout)
        snapshot = load_reviewed_source_snapshot(
            str(self.path), hashlib.sha256(result.stdout).hexdigest()
        )
        self.assertEqual(snapshot.compile(), self.generation)
        self.assertEqual(
            {
                path.relative_to(self.bundle): path.read_bytes()
                for path in self.bundle.rglob("*")
                if path.is_file()
            },
            before,
        )

    def test_cli_invalid_private_source_is_redacted_without_output(self):
        source = self.bundle / "projects/voiceos.md"
        source.write_text(
            "---\ntype: Private failure\ntype: Sensitive detail\n---\nPrivate source body."
        )
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "yap_server.knowledge.reviewed_source_snapshot",
                "--bundle-root",
                str(self.bundle),
                "--tenant-id",
                "tenant-a",
                "--repository-revision",
                "reviewed-revision",
                "--source-path",
                "knowledge/reviewed-bundle",
            ],
            capture_output=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        self.assertNotIn(b"Private", result.stderr)
        self.assertNotIn(b"Sensitive", result.stderr)
        self.assertNotIn(str(self.bundle).encode(), result.stderr)

    def test_manifest_digest_binds_loaded_configuration_without_reload(self):
        digest = self.write()
        snapshot = load_reviewed_source_snapshot(str(self.path), digest)
        self.path.write_bytes(b"changed deployment file")
        self.assertEqual(snapshot.compile(), self.generation)
        with self.assertRaises(ValueError):
            load_reviewed_source_snapshot(str(self.path), digest)

    def test_actual_fifo_replacement_between_stat_and_open_refuses_without_hanging(
        self,
    ):
        digest = self.write()
        if not hasattr(os, "mkfifo"):
            self.assertEqual(
                load_reviewed_source_snapshot(str(self.path), digest).compile(),
                self.generation,
            )
            return
        script = textwrap.dedent("""
            import os
            from pathlib import Path
            import stat
            import sys
            from yap_server import private_artifact
            from yap_server.knowledge.reviewed_source_snapshot import load_reviewed_source_snapshot

            path = Path(sys.argv[1])
            original_open = os.open
            replaced = False
            def replace_before_open(requested, flags, *args, **kwargs):
                global replaced
                if Path(requested) == path and not replaced:
                    path.unlink()
                    os.mkfifo(path)
                    replaced = True
                return original_open(requested, flags, *args, **kwargs)
            private_artifact.os.open = replace_before_open
            try:
                load_reviewed_source_snapshot(str(path), sys.argv[2])
            except ValueError:
                assert replaced and stat.S_ISFIFO(path.lstat().st_mode)
                print("actual FIFO replacement refused without blocking")
            else:
                raise AssertionError("replaced file was accepted")
        """)
        result = subprocess.run(
            [sys.executable, "-c", script, str(self.path), digest],
            capture_output=True,
            timeout=2,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout, b"actual FIFO replacement refused without blocking\n"
        )

    def test_source_drift_cannot_match_the_pinned_generation(self):
        snapshot = load_reviewed_source_snapshot(str(self.path), self.write())
        path = self.bundle / "projects/voiceos.md"
        path.write_bytes(path.read_bytes() + b"\nChanged source.\n")
        with self.assertRaisesRegex(ValueError, "deployment snapshot"):
            snapshot.compile()

    def test_strict_manifest_fields_paths_versions_and_generation(self):
        mutations = (
            {**self.manifest, "schemaVersion": True},
            {**self.manifest, "schemaVersion": 2},
            {**self.manifest, "generationSha256": "F" * 64},
            {**self.manifest, "bundleRoot": "relative"},
            {**self.manifest, "bundleRoot": " " + str(self.bundle)},
            {**self.manifest, "sourcePath": "../outside"},
            {**self.manifest, "sourcePath": "."},
            {**self.manifest, "tenantId": ""},
            {**self.manifest, "repositoryRevision": ""},
            {**self.manifest, "approved": True},
            {key: value for key, value in self.manifest.items() if key != "sourcePath"},
        )
        for value in mutations:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    load_reviewed_source_snapshot(str(self.path), self.write(value))

    def test_manifest_bounds_duplicate_keys_and_real_files(self):
        for body in (
            b"x" * 4097,
            b'{"schemaVersion":1,"schemaVersion":1}',
            b"[]",
            b'{"private":\xff}',
        ):
            with self.subTest(body=body[:32]):
                with self.assertRaises(ValueError):
                    load_reviewed_source_snapshot(str(self.path), self.write(raw=body))
        digest = self.write()
        for path in (
            "relative.json",
            " " + str(self.path),
            str(self.root / "missing.json"),
        ):
            with self.assertRaises(ValueError):
                load_reviewed_source_snapshot(path, digest)
        if os.name == "posix":
            linked = self.root / "linked.json"
            linked.symlink_to(self.path)
            with self.assertRaises(ValueError):
                load_reviewed_source_snapshot(str(linked), digest)
            fifo = self.root / "source.fifo"
            os.mkfifo(fifo)
            with self.assertRaises(ValueError):
                load_reviewed_source_snapshot(str(fifo), digest)

    def test_configuration_requires_explicit_publication_mode_and_auth_without_io(self):
        with patch(
            "yap_server.knowledge.knowledge_publication_service.load_reviewed_source_snapshot",
            side_effect=AssertionError("unexpected source IO"),
        ):
            for config, authenticated in (
                ({"YAP_KNOWLEDGE_REVIEWED_SOURCE_FILE": str(self.path)}, True),
                (
                    {
                        "YAP_KNOWLEDGE_PUBLICATION_RUNTIME": "disabled",
                        "YAP_KNOWLEDGE_REVIEWED_SOURCE_SHA256": "a" * 64,
                    },
                    True,
                ),
                (
                    {
                        "YAP_KNOWLEDGE_PUBLICATION_RUNTIME": "postgres",
                        "YAP_KNOWLEDGE_PUBLICATION_DSN_FILE": str(
                            self.root / "private.dsn"
                        ),
                        "YAP_KNOWLEDGE_REVIEWED_SOURCE_FILE": str(self.path),
                    },
                    False,
                ),
            ):
                with self.assertRaises(ValueError):
                    build_knowledge_publication_service(
                        config, authenticated_team_mode=authenticated
                    )

    def test_missing_or_invalid_manifest_pair_fails_with_redacted_configuration(self):
        common = {
            "YAP_KNOWLEDGE_PUBLICATION_RUNTIME": "postgres",
            "YAP_KNOWLEDGE_PUBLICATION_DSN_FILE": str(self.root / "private.dsn"),
        }
        for extra in (
            {"YAP_KNOWLEDGE_REVIEWED_SOURCE_FILE": str(self.path)},
            {"YAP_KNOWLEDGE_REVIEWED_SOURCE_SHA256": "a" * 64},
            {
                "YAP_KNOWLEDGE_REVIEWED_SOURCE_FILE": str(self.path),
                "YAP_KNOWLEDGE_REVIEWED_SOURCE_SHA256": "a" * 64,
            },
        ):
            with self.assertRaisesRegex(
                ValueError, "^reviewed source deployment configuration is unavailable$"
            ):
                build_knowledge_publication_service(
                    {**common, **extra}, authenticated_team_mode=True
                )
