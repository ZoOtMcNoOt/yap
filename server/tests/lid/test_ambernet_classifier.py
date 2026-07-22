from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
from types import ModuleType, SimpleNamespace
import sys
import unittest
from unittest.mock import patch

import numpy as np

from yap_server.lid.ambernet_classifier import (
    AMBERNET_LABEL_ORDER,
    AmberNetClassifier,
    AmberNetFeatureExtractor,
    MODEL_FILE,
)
from yap_server.lid.worker_contract import ProbeAudio


class _FakeFrontend:
    def __init__(self) -> None:
        self.windows: list[np.ndarray] = []

    def process(self, signal: np.ndarray) -> np.ndarray:
        self.windows.append(signal.copy())
        return np.full((1, 80, 304), len(self.windows), dtype=np.float32)


class _FakeSession:
    def __init__(self, logits: list[np.ndarray]) -> None:
        self._logits = iter(logits)
        self.feeds: list[dict[str, np.ndarray]] = []

    def run(self, outputs: list[str], feed: dict[str, np.ndarray]):
        if outputs != ["logits"]:
            raise AssertionError(outputs)
        self.feeds.append(feed)
        return [next(self._logits)]


class AmberNetClassifierTests(unittest.TestCase):
    def test_label_order_is_the_locked_107_language_contract(self) -> None:
        encoded = "\n".join(AMBERNET_LABEL_ORDER).encode("utf-8")

        self.assertEqual(len(AMBERNET_LABEL_ORDER), 107)
        self.assertEqual(
            hashlib.sha256(encoded).hexdigest(),
            "9c64d2027a37ed72852eea368a7c81eff62efb3c39e72a1567dad35fb83d2e50",
        )

    def test_classifies_one_six_second_region_as_two_fixed_windows(self) -> None:
        first = np.full((1, 107), -5.0, dtype=np.float32)
        second = np.full((1, 107), -5.0, dtype=np.float32)
        first[0, 20] = 3.0  # en
        first[0, 28] = 1.0  # fr
        second[0, 20] = 1.0
        second[0, 28] = 5.0
        frontend = _FakeFrontend()
        session = _FakeSession([first, second])
        classifier = AmberNetClassifier(
            session=session,
            frontend=frontend,
            expected_label_count=107,
        )
        samples = np.concatenate(
            (
                np.full(48_000, 1, dtype="<i2"),
                np.full(48_000, 2, dtype="<i2"),
            )
        )

        result = classifier.classify(
            ProbeAudio(samples.tobytes(), 96_000, "a" * 64)
        )

        self.assertEqual([window.shape for window in frontend.windows], [(48_000,), (48_000,)])
        self.assertAlmostEqual(float(frontend.windows[0][0]), 1.0 / 32768.0)
        self.assertAlmostEqual(float(frontend.windows[1][0]), 2.0 / 32768.0)
        self.assertEqual(result.raw_label, "fr")
        self.assertLessEqual(result.top_score, 0.0)
        self.assertAlmostEqual(result.score_margin, 1.0, places=6)
        self.assertEqual(len(session.feeds), 2)

    def test_rejects_any_probe_other_than_exactly_six_seconds(self) -> None:
        classifier = AmberNetClassifier(
            session=_FakeSession([]),
            frontend=_FakeFrontend(),
            expected_label_count=107,
        )

        with self.assertRaisesRegex(RuntimeError, "six-second"):
            classifier.classify(ProbeAudio(b"\0\0" * 95_999, 95_999, "a" * 64))

    def test_loads_exact_graph_contract_with_single_thread_cpu_runtime(self) -> None:
        calls: list[tuple[str, object, list[str]]] = []

        class FakeSessionOptions:
            pass

        class FakeInferenceSession:
            def __init__(self, path: str, *, sess_options: object, providers: list[str]) -> None:
                calls.append((path, sess_options, providers))

            def get_inputs(self):
                return [SimpleNamespace(name="processed_signal", shape=[1, 80, 304], type="tensor(float)")]

            def get_outputs(self):
                return [SimpleNamespace(name="logits", shape=[1, 107], type="tensor(float)")]

            def get_providers(self):
                return ["CPUExecutionProvider"]

        fake_ort = ModuleType("onnxruntime")
        fake_ort.SessionOptions = FakeSessionOptions
        fake_ort.InferenceSession = FakeInferenceSession
        fake_ort.ExecutionMode = SimpleNamespace(ORT_SEQUENTIAL="sequential")
        fake_ort.GraphOptimizationLevel = SimpleNamespace(ORT_ENABLE_ALL="all")

        with tempfile.TemporaryDirectory() as directory, patch.dict(
            sys.modules, {"onnxruntime": fake_ort}
        ):
            model = Path(directory) / MODEL_FILE
            model.write_bytes(b"locked-model")
            classifier = AmberNetClassifier.load(Path(directory), 107)

        self.assertIsInstance(classifier, AmberNetClassifier)
        self.assertEqual(calls[0][0], str(model.resolve()))
        self.assertEqual(calls[0][2], ["CPUExecutionProvider"])
        options = calls[0][1]
        self.assertEqual(options.intra_op_num_threads, 1)
        self.assertEqual(options.inter_op_num_threads, 1)
        self.assertEqual(options.execution_mode, "sequential")
        self.assertEqual(options.graph_optimization_level, "all")

    def test_frontend_matches_the_independent_nemo_golden(self) -> None:
        signal = (
            ((np.arange(48_000, dtype=np.int64) * 37) % 257 - 128).astype(np.float32)
            / 16_384.0
        )

        features = AmberNetFeatureExtractor().process(signal).reshape(-1)

        expected = {
            0: 15.338389,
            1: -0.16945785,
            37: 0.21455626,
            299: 2.0586839,
            304: 3.5221226,
            1216: -3.5400543,
            9728: 1.1953392,
            24000: -0.23114203,
            24315: -0.1886418,
        }
        self.assertEqual(features.shape, (80 * 304,))
        self.assertTrue(np.isfinite(features).all())
        for index, value in expected.items():
            self.assertAlmostEqual(float(features[index]), value, delta=5.0e-4)


if __name__ == "__main__":
    unittest.main()
