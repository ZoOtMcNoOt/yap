from __future__ import annotations

from dataclasses import replace
import hashlib
from pathlib import Path
import tempfile
import unittest

from yap_server.lid.component_lock import (
    LidComponentArtifactError,
    LockedLidArtifact,
    load_lid_component_lock,
)
from yap_server.lid.model_assets import verify_lid_model_import


REPO_ROOT = Path(__file__).resolve().parents[3]
COMPONENT_LOCK = REPO_ROOT / "server" / "lid-component.lock.json"


class LidModelAssetTests(unittest.TestCase):
    def test_verify_only_import_accepts_exact_bytes_and_rejects_changes(self) -> None:
        lock = load_lid_component_lock(COMPONENT_LOCK)
        content = b"explicitly-imported-ambernet"
        artifact = LockedLidArtifact(
            path=lock.model.artifacts[0].path,
            size=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
        )
        test_lock = replace(
            lock,
            model=replace(lock.model, artifacts=(artifact,)),
        )

        with tempfile.TemporaryDirectory() as directory:
            model_dir = Path(directory)
            model_path = model_dir / artifact.path
            model_path.write_bytes(content)
            verify_lid_model_import(test_lock, model_dir)

            (model_dir / "unexpected.txt").write_text("not part of the lock")
            with self.assertRaisesRegex(
                LidComponentArtifactError,
                "unexpected artifacts",
            ):
                verify_lid_model_import(test_lock, model_dir)
            (model_dir / "unexpected.txt").unlink()

            model_path.write_bytes(content + b"changed")
            with self.assertRaises(LidComponentArtifactError):
                verify_lid_model_import(test_lock, model_dir)

    def test_lock_keeps_distribution_outside_the_application(self) -> None:
        lock = load_lid_component_lock(COMPONENT_LOCK)

        self.assertEqual(lock.model.distribution_policy, "verify-only-import")
        self.assertEqual(lock.model.redistribution_approval, "not-approved")
        self.assertEqual(len(lock.model.artifacts), 1)


if __name__ == "__main__":
    unittest.main()
