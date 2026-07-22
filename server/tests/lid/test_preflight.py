from __future__ import annotations

from pathlib import Path
import tempfile
import threading
import unittest
import wave

from yap_server.lid.component_lock import load_lid_component_lock
from yap_server.lid.policy import SourceVadInterval
from yap_server.lid.preflight import LidPreflightEngine, run_source_lid_preflight


REPO_ROOT = Path(__file__).resolve().parents[3]
LOCK_PATH = REPO_ROOT / "server" / "lid-component.lock.json"


class _Worker:
    def __init__(self, labels: tuple[str, ...]) -> None:
        self.labels = labels
        self.calls = 0

    def run(
        self,
        request: object,
        _request_root: Path,
        cancellation: threading.Event | None = None,
    ) -> dict[str, object]:
        self.calls += 1
        if cancellation is not None and cancellation.is_set():
            raise RuntimeError("cancelled")
        return {
            "schemaVersion": 1,
            "requestId": request.request_id,
            "componentId": "ambernet-batch-language-preflight",
            "model": {
                "id": "nvidia/nemo/langid_ambernet",
                "revision": "1.12.0",
            },
            "policyRevision": "ambernet-stratified-five-region-v1",
            "scoreSemantics": "mean-logit-log-softmax",
            "sourceSamples": request.source_samples,
            "observations": [
                {
                    "index": probe.index,
                    "probeSha256": probe.wav_sha256,
                    "sourceStartSample": probe.source_start_sample,
                    "sourceEndSample": probe.source_end_sample,
                    "voicedSamples": probe.voiced_samples,
                    "rawLabel": self.labels[probe.index],
                    "topScore": -0.1,
                    "scoreMargin": 1.1,
                }
                for probe in request.probes
            ],
        }


class LidPreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        self.lock = load_lid_component_lock(LOCK_PATH)

    def test_agreement_returns_only_an_unconfirmed_picker_suggestion(self) -> None:
        worker = _Worker(("fr",) * 5)
        engine = LidPreflightEngine(
            lock=self.lock,
            worker=worker,
            enabled_fixed_locales=("en-US", "fr-FR"),
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.wav"
            _source(source, 600_000)
            result = run_source_lid_preflight(
                engine=engine,
                lock=self.lock,
                source_wav=source,
                work_root=root,
                request_id="lid-preflight-1",
                vad_intervals=(SourceVadInterval(0, 600_000),),
            )

            self.assertEqual(result["status"], "suggestion")
            self.assertEqual(result["suggestedLocale"], "fr-FR")
            self.assertTrue(result["userConfirmationRequired"])
            self.assertEqual(
                [item["mappedLocale"] for item in result["observations"]],
                ["fr-FR"] * 5,
            )
            self.assertEqual(result["component"]["runtime"]["cpuOnly"], True)
            self.assertFalse((root / "lid-preflight-1").exists())

    def test_short_recording_uses_manual_primary_path_without_inference(self) -> None:
        worker = _Worker(("en",) * 5)
        engine = LidPreflightEngine(
            lock=self.lock,
            worker=worker,
            enabled_fixed_locales=("en-US",),
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "short.wav"
            _source(source, 479_999)
            result = run_source_lid_preflight(
                engine=engine,
                lock=self.lock,
                source_wav=source,
                work_root=root,
                request_id="lid-preflight-short",
                vad_intervals=(SourceVadInterval(0, 479_999),),
            )

        self.assertEqual(result["status"], "manual")
        self.assertEqual(result["reason"], "short_recording")
        self.assertEqual(result["observations"], [])
        self.assertEqual(worker.calls, 0)

    def test_disagreeing_tail_fails_closed_and_keeps_all_raw_labels(self) -> None:
        worker = _Worker(("en", "en", "en", "en", "fr"))
        engine = LidPreflightEngine(
            lock=self.lock,
            worker=worker,
            enabled_fixed_locales=("en-US", "fr-FR"),
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.wav"
            _source(source, 600_000)
            result = run_source_lid_preflight(
                engine=engine,
                lock=self.lock,
                source_wav=source,
                work_root=root,
                request_id="lid-preflight-disagreement",
                vad_intervals=(SourceVadInterval(0, 600_000),),
            )

        self.assertEqual(result["status"], "manual")
        self.assertEqual(result["reason"], "language_disagreement")
        self.assertIsNone(result["suggestedLocale"])
        self.assertEqual(
            [item["rawLabel"] for item in result["observations"]],
            ["en", "en", "en", "en", "fr"],
        )


def _source(path: Path, frames: int) -> None:
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(16_000)
        writer.writeframes(b"\x00\x00" * frames)


if __name__ == "__main__":
    unittest.main()
