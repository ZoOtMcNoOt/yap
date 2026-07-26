from __future__ import annotations

from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from yap_server.evaluation import fleurs_corpus
from yap_server.evaluation.fleurs_corpus import (
    _float32_to_pcm16_le,
    _float32_to_pcm16_le_portable,
    fleurs_config_to_bcp47,
    inspect_fleurs_release,
    load_fleurs_release_lock,
)
from tests.evaluation.fleurs_fixture import (
    FLEURS_REVISION,
    build_fleurs_release,
)


class FleursCorpusTests(unittest.TestCase):
    def test_float32_conversion_matches_the_desktop_pcm16_boundary(self) -> None:
        body = b"".join(
            struct.pack("<f", sample)
            for sample in (-2.0, -1.0, -0.5, 0.0, 0.5, 1.0, 2.0)
        )
        expected = (-32768, -32768, -16384, 0, 16384, 32767, 32767)

        self.assertEqual(struct.unpack("<7h", _float32_to_pcm16_le(body)), expected)
        self.assertEqual(
            struct.unpack("<7h", _float32_to_pcm16_le_portable(body)),
            expected,
        )
        with self.assertRaisesRegex(ValueError, "non-finite"):
            _float32_to_pcm16_le(struct.pack("<f", float("nan")))

    def test_dataset_config_maps_to_canonical_locale_without_changing_region(self) -> None:
        self.assertEqual(fleurs_config_to_bcp47("es_419"), "es-419")
        self.assertEqual(fleurs_config_to_bcp47("cmn_hans_cn"), "cmn-Hans-CN")

        for invalid in ("es-419", "es_ES", "ES_419", "es_1234", "../es_419"):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ValueError, "FLEURS config"):
                    fleurs_config_to_bcp47(invalid)

    def test_repository_lock_freezes_exact_es_419_test_release(self) -> None:
        lock = load_fleurs_release_lock(
            Path(__file__).resolve().parents[2] / "fleurs-es-419-test.lock.json"
        )

        self.assertEqual(lock.dataset_id, "google/fleurs")
        self.assertEqual(lock.dataset_revision, FLEURS_REVISION)
        self.assertEqual(lock.dataset_config, "es_419")
        self.assertEqual(lock.locale_bcp47, "es-419")
        self.assertEqual(lock.split, "test")
        self.assertEqual(lock.expected_case_count, 908)
        self.assertEqual(lock.license_id, "CC-BY-4.0")
        self.assertEqual(lock.audio_archive.size, 582_112_372)
        self.assertEqual(
            lock.audio_archive.sha256,
            "981802f6c828fd214fcf8bfc1036d80c9184b6eeb5650b3f7882f8affec046c9",
        )
        self.assertEqual(lock.metadata.size, 599_882)
        self.assertEqual(
            lock.metadata.sha256,
            "d107a93a4f54a18ac25cd470bb4cdadce14fb075b0c1d1542258e274d209ec09",
        )
        self.assertEqual(
            lock.metadata.git_blob_oid,
            "cdec7d5980706c7f354b89a4a4d31949b65c100f",
        )

    def test_inspection_accepts_matching_release_without_exposing_references(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            lock_path, archive_path, metadata_path = build_fleurs_release(
                Path(temporary)
            )
            lock = load_fleurs_release_lock(lock_path)

            inspection = inspect_fleurs_release(
                lock=lock,
                archive_path=archive_path,
                metadata_path=metadata_path,
                environ={"YAP_EVAL_CACHE": temporary},
            )

        self.assertEqual(inspection.case_count, 2)
        self.assertEqual(inspection.locale_bcp47, "es-419")
        self.assertEqual(inspection.total_duration_samples, 480)
        self.assertEqual(inspection.minimum_duration_samples, 160)
        self.assertEqual(inspection.maximum_duration_samples, 320)
        self.assertNotIn("Uno", repr(inspection))
        self.assertNotIn("Dos", repr(inspection))

    def test_inspection_rejects_changed_source_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            lock_path, archive_path, metadata_path = build_fleurs_release(
                Path(temporary)
            )
            metadata_path.write_bytes(metadata_path.read_bytes() + b"\n")

            with self.assertRaisesRegex(ValueError, "metadata size differs"):
                inspect_fleurs_release(
                    lock=load_fleurs_release_lock(lock_path),
                    archive_path=archive_path,
                    metadata_path=metadata_path,
                    environ={"YAP_EVAL_CACHE": temporary},
                )

    def test_inspection_rejects_unsafe_or_link_archive_members(self) -> None:
        for member_name, link_target in (
            ("../100.wav", None),
            ("test/100.wav", "test/200.wav"),
        ):
            with self.subTest(member_name=member_name, link_target=link_target):
                with tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    lock_path, archive_path, metadata_path = build_fleurs_release(
                        root,
                        first_member_name=member_name,
                        first_link_target=link_target,
                    )

                    with self.assertRaisesRegex(ValueError, "archive member"):
                        inspect_fleurs_release(
                            lock=load_fleurs_release_lock(lock_path),
                            archive_path=archive_path,
                            metadata_path=metadata_path,
                            environ={"YAP_EVAL_CACHE": temporary},
                        )

    def test_inspection_rejects_archive_and_metadata_membership_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lock_path, archive_path, metadata_path = build_fleurs_release(
                root,
                second_member_name="test/300.wav",
            )

            with self.assertRaisesRegex(ValueError, "membership differs"):
                inspect_fleurs_release(
                    lock=load_fleurs_release_lock(lock_path),
                    archive_path=archive_path,
                    metadata_path=metadata_path,
                    environ={"YAP_EVAL_CACHE": temporary},
                )

    def test_inspection_requires_the_external_private_cache_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            lock_path, archive_path, metadata_path = build_fleurs_release(
                Path(temporary)
            )

            with self.assertRaisesRegex(ValueError, "YAP_EVAL_CACHE"):
                inspect_fleurs_release(
                    lock=load_fleurs_release_lock(lock_path),
                    archive_path=archive_path,
                    metadata_path=metadata_path,
                    environ={},
                )

    def test_private_cache_accepts_a_shallow_source_mount_without_a_repository(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cache = root / "cache"
            cache.mkdir()
            mounted_module = (
                root / "src" / "yap_server" / "evaluation" / "fleurs_corpus.py"
            )

            with patch.object(fleurs_corpus, "__file__", str(mounted_module)):
                resolved = fleurs_corpus._private_cache_root(
                    {"YAP_EVAL_CACHE": str(cache)}
                )

        self.assertEqual(resolved, cache.resolve())

    def test_private_cache_rejects_the_actual_repository_root(self) -> None:
        repository = Path(__file__).resolve().parents[3]

        with self.assertRaisesRegex(ValueError, "outside the repository"):
            fleurs_corpus._private_cache_root(
                {"YAP_EVAL_CACHE": str(repository)}
            )
if __name__ == "__main__":
    unittest.main()
