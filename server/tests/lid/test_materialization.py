from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest
import wave

from yap_server.lid.component_lock import load_lid_component_lock
from yap_server.lid.materialization import (
    materialize_lid_worker_request,
    remove_materialized_lid_request,
)
from yap_server.lid.policy import LidProbeSelection, LidProbeWindow
from yap_server.lid.worker_contract import load_lid_worker_request


REPO_ROOT = Path(__file__).resolve().parents[3]
LOCK_PATH = REPO_ROOT / "server" / "lid-component.lock.json"


class LidMaterializationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.lock = load_lid_component_lock(LOCK_PATH)

    def test_extracts_two_continuous_source_windows_without_concatenation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.wav"
            samples = tuple((index % 32_000) - 16_000 for index in range(600_000))
            _write_pcm16_wav(source, samples)
            selection = _selection(
                (16_000, 256_000, 160_000),
                (320_000, 560_000, 144_000),
            )

            materialized = materialize_lid_worker_request(
                source_wav=source,
                destination=root / "request",
                request_id="lid-request-1",
                selection=selection,
                lock=self.lock,
            )

            request = load_lid_worker_request(materialized.request_path, self.lock)
            self.assertEqual(request, materialized.request)
            self.assertEqual(request.source_samples, len(samples))
            self.assertEqual(len(request.probes), 2)
            for probe, expected in zip(
                request.probes,
                ((16_000, 256_000), (320_000, 560_000)),
                strict=True,
            ):
                encoded = (materialized.root / probe.file_name).read_bytes()
                self.assertEqual(
                    hashlib.sha256(encoded).hexdigest(),
                    probe.wav_sha256,
                )
                probe_path = materialized.root / probe.file_name
                with wave.open(str(probe_path), "rb") as reader:
                    self.assertEqual(reader.getnchannels(), 1)
                    self.assertEqual(reader.getsampwidth(), 2)
                    self.assertEqual(reader.getframerate(), 16_000)
                    self.assertEqual(reader.getnframes(), expected[1] - expected[0])
                    actual_pcm = reader.readframes(reader.getnframes())
                self.assertEqual(actual_pcm, _pcm16(samples[slice(*expected)]))

            remove_materialized_lid_request(materialized)
            self.assertFalse(materialized.root.exists())

    def test_rejects_noncanonical_source_and_inconsistent_selection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stereo = root / "stereo.wav"
            with wave.open(str(stereo), "wb") as writer:
                writer.setnchannels(2)
                writer.setsampwidth(2)
                writer.setframerate(16_000)
                writer.writeframes(b"\x00\x00" * 4 * 600_000)

            for selection in (
                _selection((0, 240_000, 128_000), (240_000, 480_000, 128_000)),
                LidProbeSelection(
                    status="selected",
                    reason="two_probes_selected",
                    windows=(LidProbeWindow(0, 0, 240_001, 128_000),),
                ),
            ):
                with self.subTest(selection=selection):
                    with self.assertRaises(ValueError):
                        materialize_lid_worker_request(
                            source_wav=stereo,
                            destination=root / f"request-{len(selection.windows)}",
                            request_id="lid-request-2",
                            selection=selection,
                            lock=self.lock,
                        )

    def test_cancellation_removes_private_staging_and_publishes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.wav"
            _write_pcm16_wav(source, (0,) * 600_000)
            calls = 0

            def ensure_active() -> None:
                nonlocal calls
                calls += 1
                if calls == 3:
                    raise RuntimeError("cancelled")

            destination = root / "request"
            with self.assertRaisesRegex(RuntimeError, "cancelled"):
                materialize_lid_worker_request(
                    source_wav=source,
                    destination=destination,
                    request_id="lid-request-3",
                    selection=_selection(
                        (0, 240_000, 128_000),
                        (300_000, 540_000, 128_000),
                    ),
                    lock=self.lock,
                    ensure_active=ensure_active,
                )

            self.assertFalse(destination.exists())
            self.assertEqual(
                [path.name for path in root.iterdir() if path.name.endswith(".part")],
                [],
            )

    def test_never_replaces_an_existing_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.wav"
            _write_pcm16_wav(source, (0,) * 600_000)
            destination = root / "request"
            destination.mkdir()
            marker = destination / "owned.txt"
            marker.write_text("preserve", encoding="utf-8")

            with self.assertRaises(FileExistsError):
                materialize_lid_worker_request(
                    source_wav=source,
                    destination=destination,
                    request_id="lid-request-4",
                    selection=_selection(
                        (0, 240_000, 128_000),
                        (300_000, 540_000, 128_000),
                    ),
                    lock=self.lock,
                )
            self.assertEqual(marker.read_text(encoding="utf-8"), "preserve")


def _selection(*windows: tuple[int, int, int]) -> LidProbeSelection:
    return LidProbeSelection(
        status="selected",
        reason="two_probes_selected",
        windows=tuple(
            LidProbeWindow(index, start, end, voiced)
            for index, (start, end, voiced) in enumerate(windows)
        ),
    )


def _write_pcm16_wav(path: Path, samples: tuple[int, ...]) -> None:
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(16_000)
        writer.writeframes(_pcm16(samples))


def _pcm16(samples: tuple[int, ...]) -> bytes:
    return b"".join(sample.to_bytes(2, "little", signed=True) for sample in samples)


if __name__ == "__main__":
    unittest.main()
