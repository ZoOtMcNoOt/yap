from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from yap_server.meeting_transcription.runtime_provenance import (
    RepositorySource,
    load_meeting_runtime_provenance,
    verify_repository_source_directory,
    verify_meeting_runtime_repository_files,
)
from yap_server.artifact_identity import ArtifactIdentity


SERVER_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_LOCK = SERVER_ROOT / "meeting-transcription-runtime.lock.json"


class MeetingRuntimeProvenanceTests(unittest.TestCase):
    def test_external_source_directory_must_match_the_complete_lock(self) -> None:
        source = RepositorySource(
            identifier="example/runtime",
            revision="a" * 40,
            source="https://example.invalid/runtime",
            license_spdx="Apache-2.0",
            artifacts=(
                ArtifactIdentity(
                    path="README.md",
                    size=4,
                    sha256=(
                        "9f86d081884c7d659a2feaa0c55ad015"
                        "a3bf4f1b2b0b822cd15d6c15b0f00a08"
                    ),
                ),
                ArtifactIdentity(
                    path="runtime/engine.py",
                    size=6,
                    sha256=(
                        "6ca13d52ca70c883e0f0bb101e425a89"
                        "e8624de51db2d2392593af6a84118090"
                    ),
                ),
            ),
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "runtime").mkdir()
            (root / "README.md").write_bytes(b"test")
            (root / "runtime" / "engine.py").write_bytes(b"abc123")

            self.assertEqual(
                verify_repository_source_directory(source, root),
                root.resolve(),
            )

            (root / "unexpected.txt").write_text("no", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unexpected artifacts"):
                verify_repository_source_directory(source, root)

    def test_repository_lock_selects_the_current_upstream_whole_meeting_runtime(
        self,
    ) -> None:
        provenance = load_meeting_runtime_provenance(RUNTIME_LOCK)

        self.assertEqual(provenance.runtime_authority, "upstream-tiron-harness")
        self.assertEqual(
            provenance.model.revision,
            "90bc0a4d198cd5cf6679b0e478375ba3a0040575",
        )
        self.assertEqual(
            provenance.model.artifact("model.safetensors").sha256,
            "2e9f644c5eb633d3c387975cf38677d3ffe1a7b98830a735867865ec1bd519b5",
        )
        self.assertEqual(
            provenance.harness.revision,
            "d249c5a81fc6e0f1ecd34fd30cf2519f06fe671c",
        )
        self.assertEqual(
            provenance.harness.artifact("eval/scoring.py").sha256,
            "88dd4cbb67019c04fd79cba04072661084c1cb06cddfef60e86cb4b763cbd965",
        )
        self.assertEqual(
            provenance.harness.compatibility_patches[0].identifier,
            "local-ecapa-artifact-path",
        )
        self.assertEqual(
            provenance.speaker_encoder.revision,
            "0f99f2d0ebe89ac095bcc5903c4dd8f72b367286",
        )
        self.assertEqual(provenance.base_runtime.python_version, "3.12.3")
        self.assertEqual(provenance.base_runtime.platform, "linux/arm64")
        self.assertFalse(provenance.execution.network_downloads_allowed)
        self.assertFalse(provenance.execution.production_default)

        verify_meeting_runtime_repository_files(
            provenance,
            repository_root=SERVER_ROOT.parent,
        )

    def test_lock_rejects_the_superseded_checkpoint_and_missing_runtime_source(
        self,
    ) -> None:
        payload = json.loads(RUNTIME_LOCK.read_text(encoding="utf-8"))
        cases = (
            (
                ("model", "revision"),
                "aed145c7d6cc5cbd381a0e87b6d0089bcc76a1fc",
                "current Tiron model revision",
            ),
            (
                ("harness", "revision"),
                "5b3766ac64ff3a8d98443e0a850d1ce569952520",
                "current Tiron harness revision",
            ),
        )
        for path, value, message in cases:
            with self.subTest(path=path):
                changed = deepcopy(payload)
                changed[path[0]][path[1]] = value
                with tempfile.TemporaryDirectory() as temporary:
                    lock_path = Path(temporary) / "runtime.lock.json"
                    lock_path.write_text(json.dumps(changed), encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, message):
                        load_meeting_runtime_provenance(lock_path)

        changed = deepcopy(payload)
        changed["harness"]["artifacts"] = [
            artifact
            for artifact in changed["harness"]["artifacts"]
            if artifact["path"] != "tiron/pipeline.py"
        ]
        with tempfile.TemporaryDirectory() as temporary:
            lock_path = Path(temporary) / "runtime.lock.json"
            lock_path.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "harness artifact paths"):
                load_meeting_runtime_provenance(lock_path)

    def test_lock_rejects_downloads_duplicate_keys_and_changed_requirements(
        self,
    ) -> None:
        body = RUNTIME_LOCK.read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            duplicate = root / "duplicate.json"
            duplicate.write_text(
                body.replace(
                    '"schemaVersion": 1,',
                    '"schemaVersion": 1, "schemaVersion": 1,',
                    1,
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
                load_meeting_runtime_provenance(duplicate)

            payload = json.loads(body)
            payload["execution"]["networkDownloadsAllowed"] = True
            downloads = root / "downloads.json"
            downloads.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "network downloads"):
                load_meeting_runtime_provenance(downloads)

            requirements = root / "server/runtime/tiron/requirements.lock"
            requirements.parent.mkdir(parents=True)
            requirements.write_text("changed", encoding="utf-8")
            payload = json.loads(body)
            changed = root / "changed.json"
            changed.write_text(json.dumps(payload), encoding="utf-8")
            provenance = load_meeting_runtime_provenance(changed)
            with self.assertRaisesRegex(ValueError, "requirements lock SHA-256"):
                verify_meeting_runtime_repository_files(
                    provenance,
                    repository_root=root,
                )


if __name__ == "__main__":
    unittest.main()
