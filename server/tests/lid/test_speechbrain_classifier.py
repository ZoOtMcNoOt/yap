from __future__ import annotations

from contextlib import nullcontext
import os
from pathlib import Path
import sys
import tempfile
from types import ModuleType
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from yap_server.lid.speechbrain_classifier import SpeechBrainClassifier
from yap_server.lid.worker_contract import ProbeAudio


class _Vector:
    def __init__(self, values: list[float]) -> None:
        self._values = values

    def detach(self) -> _Vector:
        return self

    def cpu(self) -> _Vector:
        return self

    def tolist(self) -> list[float]:
        return self._values


class _Matrix:
    ndim = 2

    def __init__(self, values: list[float]) -> None:
        self.shape = (1, len(values))
        self._values = values

    def __getitem__(self, index: int) -> _Vector:
        if index != 0:
            raise IndexError(index)
        return _Vector(self._values)


class _Waveform:
    def __init__(self) -> None:
        self.dtype: object | None = None
        self.divisor: float | None = None

    def to(self, *, dtype: object) -> _Waveform:
        self.dtype = dtype
        return self

    def div_(self, divisor: float) -> _Waveform:
        self.divisor = divisor
        return self


class _LabelEncoder:
    def __init__(self, label_count: int) -> None:
        self._label_count = label_count
        self.expected_counts: list[int] = []

    def __len__(self) -> int:
        return self._label_count

    def expect_len(self, expected_count: int) -> None:
        self.expected_counts.append(expected_count)


class _Engine:
    def __init__(self, label_count: int = 3) -> None:
        self.waveform: _Waveform | None = None
        self.hparams = SimpleNamespace(
            label_encoder=_LabelEncoder(label_count),
        )

    def classify_batch(self, waveform: _Waveform):
        self.waveform = waveform
        return _Matrix([-2.0, -0.25, -1.5]), None, None, ["fr: French"]


class SpeechBrainClassifierTests(unittest.TestCase):
    def test_loads_only_from_the_local_model_on_cpu_with_network_disabled(
        self,
    ) -> None:
        calls: list[dict[str, object]] = []
        engine = _Engine()

        class FakeEncoderClassifier:
            @classmethod
            def from_hparams(cls, **kwargs):
                calls.append(kwargs)
                return engine

        fetch_calls: list[dict[str, object]] = []

        class FakeFetchConfig:
            def __init__(self, **kwargs) -> None:
                fetch_calls.append(kwargs)

        class FakeLocalStrategy:
            NO_LINK = "NO_LINK"

        fake_torch = ModuleType("torch")
        fake_torch.int16 = "int16"
        fake_torch.float32 = "float32"
        fake_torch.frombuffer = lambda *_args, **_kwargs: _Waveform()
        fake_torch.inference_mode = nullcontext
        classifiers = ModuleType("speechbrain.inference.classifiers")
        classifiers.EncoderClassifier = FakeEncoderClassifier
        fetching = ModuleType("speechbrain.utils.fetching")
        fetching.FetchConfig = FakeFetchConfig
        fetching.LocalStrategy = FakeLocalStrategy
        modules = {
            "torch": fake_torch,
            "speechbrain": ModuleType("speechbrain"),
            "speechbrain.inference": ModuleType("speechbrain.inference"),
            "speechbrain.inference.classifiers": classifiers,
            "speechbrain.utils": ModuleType("speechbrain.utils"),
            "speechbrain.utils.fetching": fetching,
        }

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(sys.modules, modules),
            patch.dict(os.environ, clear=False),
        ):
            model_dir = Path(directory).resolve()
            classifier = SpeechBrainClassifier.load(model_dir, 3)
            self.assertEqual(os.environ["HF_HUB_OFFLINE"], "1")
            self.assertEqual(os.environ["TRANSFORMERS_OFFLINE"], "1")

        self.assertIsInstance(classifier, SpeechBrainClassifier)
        self.assertEqual(
            fetch_calls,
            [{"allow_network": False, "allow_updates": False}],
        )
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["source"], str(model_dir))
        self.assertEqual(calls[0]["savedir"], str(model_dir))
        self.assertEqual(calls[0]["hparams_file"], "hyperparams.yaml")
        self.assertEqual(
            calls[0]["overrides"],
            {"pretrained_path": str(model_dir)},
        )
        self.assertEqual(calls[0]["run_opts"], {"device": "cpu"})
        self.assertEqual(calls[0]["local_strategy"], "NO_LINK")
        self.assertEqual(engine.hparams.label_encoder.expected_counts, [3])

    def test_rejects_a_label_encoder_that_differs_from_the_locked_count(self) -> None:
        engine = _Engine(label_count=2)

        class FakeEncoderClassifier:
            @classmethod
            def from_hparams(cls, **_kwargs):
                return engine

        class FakeFetchConfig:
            def __init__(self, **_kwargs) -> None:
                pass

        class FakeLocalStrategy:
            NO_LINK = "NO_LINK"

        fake_torch = ModuleType("torch")
        classifiers = ModuleType("speechbrain.inference.classifiers")
        classifiers.EncoderClassifier = FakeEncoderClassifier
        fetching = ModuleType("speechbrain.utils.fetching")
        fetching.FetchConfig = FakeFetchConfig
        fetching.LocalStrategy = FakeLocalStrategy
        modules = {
            "torch": fake_torch,
            "speechbrain": ModuleType("speechbrain"),
            "speechbrain.inference": ModuleType("speechbrain.inference"),
            "speechbrain.inference.classifiers": classifiers,
            "speechbrain.utils": ModuleType("speechbrain.utils"),
            "speechbrain.utils.fetching": fetching,
        }

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(sys.modules, modules),
        ):
            with self.assertRaisesRegex(RuntimeError, "label count"):
                SpeechBrainClassifier.load(Path(directory), 3)

    def test_converts_pcm16_and_derives_uncalibrated_top_two_evidence(self) -> None:
        engine = _Engine()
        fake_torch = ModuleType("torch")
        fake_torch.int16 = "int16"
        fake_torch.float32 = "float32"
        waveform = _Waveform()
        fake_torch.frombuffer = lambda *_args, **_kwargs: waveform
        fake_torch.inference_mode = nullcontext
        classifier = SpeechBrainClassifier(
            engine=engine,
            torch_module=fake_torch,
            expected_label_count=3,
        )

        result = classifier.classify(
            ProbeAudio(
                pcm_bytes=b"\0\0" * 16,
                frame_count=16,
                wav_sha256="a" * 64,
            )
        )

        self.assertIs(engine.waveform, waveform)
        self.assertEqual(waveform.dtype, "float32")
        self.assertEqual(waveform.divisor, 32768.0)
        self.assertEqual(result.raw_label, "fr: French")
        self.assertEqual(result.top_score, -0.25)
        self.assertEqual(result.score_margin, 1.25)

    def test_rejects_malformed_model_outputs(self) -> None:
        fake_torch = ModuleType("torch")
        fake_torch.int16 = "int16"
        fake_torch.float32 = "float32"
        fake_torch.frombuffer = lambda *_args, **_kwargs: _Waveform()
        fake_torch.inference_mode = nullcontext
        audio = ProbeAudio(b"\0\0", 1, "a" * 64)

        for scores, labels in (([-0.2], ["en: English"]), ([-0.2, -1.0], [])):
            with self.subTest(scores=scores, labels=labels):
                engine = _Engine()
                engine.classify_batch = lambda _waveform: (
                    _Matrix(scores),
                    None,
                    None,
                    labels,
                )
                classifier = SpeechBrainClassifier(
                    engine=engine,
                    torch_module=fake_torch,
                    expected_label_count=3,
                )
                with self.assertRaisesRegex(RuntimeError, "malformed"):
                    classifier.classify(audio)


if __name__ == "__main__":
    unittest.main()
