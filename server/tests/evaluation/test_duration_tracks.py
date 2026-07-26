from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import wave

from yap_server.evaluation import duration_tracks
from yap_server.evaluation.duration_tracks import (
    DurationTrackSpec,
    build_duration_track,
    build_duration_track_collection,
    load_duration_track,
)


def _write_source(path: Path, samples: list[int], *, channels: int = 1) -> None:
    body = b"".join(sample.to_bytes(2, "little", signed=True) for sample in samples)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(2)
        output.setframerate(16_000)
        output.writeframes(body * channels)


class DurationTrackTests(unittest.TestCase):
    def test_builds_an_exact_looped_track_without_paths_or_accuracy_inflation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cache = root / "private-cache"
            source = root / "source.wav"
            _write_source(source, list(range(10)))

            manifest = build_duration_track(
                case_id="batch-25-samples",
                duration_samples=25,
                source_paths=[source],
                environ={"YAP_EVAL_CACHE": str(cache)},
            )

            output = cache / "runtime-tracks" / "batch-25-samples" / "audio.wav"
            with wave.open(str(output), "rb") as audio:
                self.assertEqual(audio.getnframes(), 25)
                pcm = audio.readframes(25)
            self.assertEqual(manifest["runtimeControlKind"], "looped")
            self.assertEqual(manifest["accuracySampleIncrement"], 0)
            self.assertEqual(len(manifest["segments"]), 3)  # type: ignore[arg-type]
            self.assertEqual(
                manifest["audio"]["decodedPcmSha256"],  # type: ignore[index]
                hashlib.sha256(pcm).hexdigest(),
            )
            encoded = json.dumps(manifest, sort_keys=True)
            self.assertNotIn(str(source), encoded)
            self.assertNotIn("transcript", encoded.lower())
            loaded = load_duration_track(
                cache / "runtime-tracks" / "batch-25-samples" / "manifest.json"
            )
            self.assertEqual(loaded.audio_path, output)
            self.assertEqual(loaded.manifest, manifest)

    def test_case_ids_are_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.wav"
            _write_source(source, [1, 2, 3])
            environ = {"YAP_EVAL_CACHE": str(root / "cache")}
            build_duration_track(
                case_id="immutable-case",
                duration_samples=3,
                source_paths=[source],
                environ=environ,
            )

            with self.assertRaisesRegex(ValueError, "already exists"):
                build_duration_track(
                    case_id="immutable-case",
                    duration_samples=3,
                    source_paths=[source],
                    environ=environ,
                )

    def test_cache_cannot_default_or_resolve_inside_the_repository(self) -> None:
        source = Path(__file__).resolve().parents[1] / "fixtures" / "asr" / "2086-149220-0033.wav"
        with self.assertRaisesRegex(ValueError, "required"):
            build_duration_track(
                case_id="missing-cache",
                duration_samples=1,
                source_paths=[source],
                environ={},
            )
        repository = Path(__file__).resolve().parents[3]
        with self.assertRaisesRegex(ValueError, "outside the repository"):
            build_duration_track(
                case_id="repo-cache",
                duration_samples=1,
                source_paths=[source],
                environ={"YAP_EVAL_CACHE": str(repository / ".eval-cache")},
            )

    def test_rejects_noncanonical_source_audio(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "stereo.wav"
            _write_source(source, [1, 2, 3], channels=2)
            with self.assertRaisesRegex(ValueError, "mono PCM16"):
                build_duration_track(
                    case_id="stereo-source",
                    duration_samples=3,
                    source_paths=[source],
                    environ={"YAP_EVAL_CACHE": str(root / "cache")},
                )

    def test_segment_manifest_is_bounded_before_output_creation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "one-sample.wav"
            _write_source(source, [1])
            cache = root / "cache"

            with self.assertRaisesRegex(ValueError, "segment count"):
                build_duration_track(
                    case_id="too-many-segments",
                    duration_samples=4_097,
                    source_paths=[source],
                    environ={"YAP_EVAL_CACHE": str(cache)},
                )
            self.assertFalse((cache / "runtime-tracks" / "too-many-segments").exists())

    def test_loader_rejects_audio_or_manifest_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.wav"
            _write_source(source, [1, 2, 3])
            cache = root / "cache"
            build_duration_track(
                case_id="tamper-case",
                duration_samples=3,
                source_paths=[source],
                environ={"YAP_EVAL_CACHE": str(cache)},
            )
            case = cache / "runtime-tracks" / "tamper-case"
            audio_path = case / "audio.wav"
            audio_path.write_bytes(audio_path.read_bytes() + b"x")
            with self.assertRaisesRegex(ValueError, "differs"):
                load_duration_track(case / "manifest.json")

            manifest = json.loads((case / "manifest.json").read_text(encoding="utf-8"))
            manifest["referenceText"] = "private"
            (case / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "fields differ"):
                load_duration_track(case / "manifest.json")

    def test_collection_inspects_sources_once_and_publishes_all_tracks_atomically(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cache = root / "cache"
            first_source = root / "first.wav"
            second_source = root / "second.wav"
            _write_source(first_source, [1, 2, 3])
            _write_source(second_source, [4, 5])
            captured_manifests: dict[str, dict[str, object]] = {}

            def suite_manifest(
                manifests: dict[str, dict[str, object]],
            ) -> tuple[str, bytes]:
                captured_manifests.update(manifests)
                return "suite.json", b'{"schemaVersion":1}\n'

            with mock.patch.object(
                duration_tracks,
                "_inspect_source",
                wraps=duration_tracks._inspect_source,
            ) as inspect_source:
                destination = build_duration_track_collection(
                    collection_id="local-duration-suite",
                    tracks=[
                        DurationTrackSpec("short-case", 4),
                        DurationTrackSpec("long-case", 12),
                    ],
                    source_paths=[first_source, second_source],
                    manifest_factory=suite_manifest,
                    environ={"YAP_EVAL_CACHE": str(cache)},
                )

            self.assertEqual(inspect_source.call_count, 2)
            self.assertEqual(set(captured_manifests), {"short-case", "long-case"})
            self.assertEqual(
                destination,
                cache / "runtime-tracks" / "local-duration-suite",
            )
            self.assertEqual(
                (destination / "suite.json").read_bytes(),
                b'{"schemaVersion":1}\n',
            )
            for case_id in captured_manifests:
                self.assertTrue((destination / case_id / "audio.wav").is_file())
                self.assertTrue((destination / case_id / "manifest.json").is_file())
            self.assertEqual(
                [path for path in destination.parent.iterdir() if path.name.startswith(".")],
                [],
            )

    def test_collection_rejects_duplicate_case_ids_before_output_creation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.wav"
            _write_source(source, [1, 2, 3])
            cache = root / "cache"

            with self.assertRaisesRegex(ValueError, "must be unique"):
                build_duration_track_collection(
                    collection_id="duplicate-suite",
                    tracks=[
                        DurationTrackSpec("same-case", 2),
                        DurationTrackSpec("same-case", 3),
                    ],
                    source_paths=[source],
                    manifest_factory=lambda _: ("suite.json", b"{}"),
                    environ={"YAP_EVAL_CACHE": str(cache)},
                )

            self.assertFalse(
                (cache / "runtime-tracks" / "duplicate-suite").exists()
            )

    def test_collection_rejects_a_source_changed_while_tracks_are_built(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.wav"
            _write_source(source, [1, 2, 3])
            cache = root / "cache"
            original_copy = duration_tracks._copy_source_frames
            changed = False

            def copy_then_change(*args: object, **kwargs: object) -> int:
                nonlocal changed
                copied = original_copy(*args, **kwargs)  # type: ignore[arg-type]
                if not changed:
                    _write_source(source, [4, 5, 6])
                    changed = True
                return copied

            with mock.patch.object(
                duration_tracks,
                "_copy_source_frames",
                side_effect=copy_then_change,
            ), self.assertRaisesRegex(ValueError, "changed during track construction"):
                build_duration_track_collection(
                    collection_id="changing-source-suite",
                    tracks=[DurationTrackSpec("looped-case", 6)],
                    source_paths=[source],
                    manifest_factory=lambda _: ("suite.json", b"{}"),
                    environ={"YAP_EVAL_CACHE": str(cache)},
                )

            self.assertFalse(
                (cache / "runtime-tracks" / "changing-source-suite").exists()
            )
            self.assertEqual(
                [
                    path
                    for path in (cache / "runtime-tracks").iterdir()
                    if path.name.startswith(".changing-source-suite.")
                ],
                [],
            )

    def test_collection_discards_unpublished_tracks_for_invalid_manifests(self) -> None:
        invalid_manifests: list[tuple[object, object]] = [
            ("../suite.json", b"{}"),
            ("suite.txt", b"{}"),
            ("suite.json", b""),
            ("suite.json", b"x" * (64 * 1024 + 1)),
            ("suite.json", "not-bytes"),
        ]
        for index, (manifest_name, manifest_bytes) in enumerate(invalid_manifests):
            with self.subTest(index=index), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source = root / "source.wav"
                _write_source(source, [1, 2, 3])
                cache = root / "cache"
                collection_id = f"invalid-suite-{index}"

                with self.assertRaisesRegex(ValueError, "manifest is invalid"):
                    build_duration_track_collection(
                        collection_id=collection_id,
                        tracks=[DurationTrackSpec("short-case", 2)],
                        source_paths=[source],
                        manifest_factory=lambda _, name=manifest_name, body=manifest_bytes: (
                            name,
                            body,
                        ),  # type: ignore[return-value]
                        environ={"YAP_EVAL_CACHE": str(cache)},
                    )

                runtime_tracks = cache / "runtime-tracks"
                self.assertFalse((runtime_tracks / collection_id).exists())
                self.assertEqual(
                    [
                        path
                        for path in runtime_tracks.iterdir()
                        if path.name.startswith(f".{collection_id}.")
                    ],
                    [],
                )


if __name__ == "__main__":
    unittest.main()
