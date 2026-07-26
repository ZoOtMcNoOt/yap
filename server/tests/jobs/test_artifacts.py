from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from yap_server.jobs.artifacts import (
    MAX_STATE_BYTES,
    PcmChunkSource,
    publish_json,
    publish_wav,
    read_regular_file,
    unlink_owned_artifact_temporaries,
)
from yap_server.limits import MAX_TRANSCRIPT_BYTES


class ArtifactSafetyTests(unittest.TestCase):
    def test_cleanup_removes_only_owned_crash_temporaries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            owned = (
                ".input-a1.wav.part",
                ".utterance-plan-b2.json.part",
                ".result-c3",
                ".worker-result.json.d4.tmp",
            )
            for name in owned:
                (root / name).write_bytes(b"private")
            unrelated = root / ".input-user.txt"
            unrelated.write_bytes(b"keep")

            unlink_owned_artifact_temporaries(root)

            self.assertTrue(unrelated.is_file())
            self.assertTrue(all(not (root / name).exists() for name in owned))

    def test_dynamic_result_bound_preserves_a_maximum_utf8_transcript_twice(self) -> None:
        transcript = "é" * (MAX_TRANSCRIPT_BYTES // len("é".encode("utf-8")))
        payload = {
            "transcript": transcript,
            "languageSegments": [{"text": transcript}],
        }
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "result-revision.json"

            publish_json(destination, payload)

            encoded = destination.read_bytes()
            self.assertLessEqual(len(encoded), MAX_STATE_BYTES)
            self.assertNotIn(b"\\u00e9", encoded)
            self.assertEqual(json.loads(encoded), payload)

    def test_json_publication_rejects_an_artifact_its_reader_cannot_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "state.json"

            with self.assertRaisesRegex(ValueError, "readable byte limit"):
                publish_json(destination, {"value": "x" * MAX_STATE_BYTES})

            self.assertFalse(destination.exists())
            self.assertEqual(list(root.glob(".result-*")), [])

    def test_regular_file_read_rechecks_growth_after_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / "state.json"
            artifact.write_bytes(b"{}")
            original_lstat = Path.lstat
            grew = False

            def grow_after_metadata(path: Path):  # type: ignore[no-untyped-def]
                nonlocal grew
                metadata = original_lstat(path)
                if path == artifact and not grew:
                    grew = True
                    artifact.write_bytes(b"x" * 9)
                return metadata

            with patch.object(Path, "lstat", grow_after_metadata):
                with self.assertRaisesRegex(ValueError, "unsafe or oversized"):
                    read_regular_file(artifact, 8)

    def test_regular_file_read_accepts_content_at_the_exact_bound(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / "chunk.pcm"
            artifact.write_bytes(b"12345678")

            self.assertEqual(read_regular_file(artifact, 8), b"12345678")

    def test_wav_publication_revalidates_declared_chunk_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            chunk = tmp_path / "chunk.pcm"
            original = b"\x00\x00\x01\x00"
            chunk.write_bytes(original)
            source = PcmChunkSource(
                path=chunk,
                byte_length=len(original),
                sha256=hashlib.sha256(original).hexdigest(),
            )
            chunk.write_bytes(b"\x02\x00\x03\x00")
            destination = tmp_path / "input.wav"

            with self.assertRaisesRegex(ValueError, "no longer matches"):
                publish_wav(destination, [source])

            self.assertFalse(destination.exists())
            self.assertEqual(list(tmp_path.glob(".input-*.wav.part")), [])
