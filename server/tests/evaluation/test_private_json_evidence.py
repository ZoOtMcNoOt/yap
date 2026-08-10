from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from yap_server.evaluation.private_json_evidence import (
    write_new_private_json_evidence,
)


class PrivateJsonEvidenceTests(unittest.TestCase):
    def test_publishes_canonical_owner_private_create_once_json(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.json"
            write_new_private_json_evidence(path, {"z": 1, "a": "é"})

            self.assertEqual(path.read_bytes(), b'{"a":"\xc3\xa9","z":1}\n')
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["z"], 1)
            if os.name == "posix":
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaisesRegex(ValueError, "must be new"):
                write_new_private_json_evidence(path, {})

    def test_rejects_linked_parent(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            real = root / "real"
            real.mkdir()
            linked = root / "linked"
            try:
                linked.symlink_to(real, target_is_directory=True)
            except OSError:
                self.skipTest("directory links are unavailable")
            with self.assertRaisesRegex(ValueError, "must be new"):
                write_new_private_json_evidence(linked / "evidence.json", {})


if __name__ == "__main__":
    unittest.main()
