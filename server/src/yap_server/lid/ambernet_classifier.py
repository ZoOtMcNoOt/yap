"""Bounded ONNX adapter for the hash-locked AmberNet LID graph."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np

from .ambernet_frontend import (
    AmberNetFeatureExtractor,
    MEL_BINS,
    PADDED_FRAMES,
    WINDOW_SAMPLES,
)
from .worker_contract import LidClassification, ProbeAudio


MODEL_FILE = "ambernet-1.12.0-classifier-int8-qdq.onnx"
_REGION_SAMPLES = WINDOW_SAMPLES * 2

AMBERNET_LABEL_ORDER = (
    "ab", "af", "am", "ar", "as", "az", "ba", "be", "bg", "bn", "bo", "br", "bs", "ca", "ceb",
    "cs", "cy", "da", "de", "el", "en", "eo", "es", "et", "eu", "fa", "fi", "fo", "fr", "gl", "gn",
    "gu", "gv", "ha", "haw", "hi", "hr", "ht", "hu", "hy", "ia", "id", "is", "it", "iw", "ja",
    "jw", "ka", "kk", "km", "kn", "ko", "la", "lb", "ln", "lo", "lt", "lv", "mg", "mi", "mk", "ml",
    "mn", "mr", "ms", "mt", "my", "ne", "nl", "nn", "no", "oc", "pa", "pl", "ps", "pt", "ro", "ru",
    "sa", "sco", "sd", "si", "sk", "sl", "sn", "so", "sq", "sr", "su", "sv", "sw", "ta", "te",
    "tg", "th", "tk", "tl", "tr", "tt", "uk", "ur", "uz", "vi", "war", "yi", "yo", "zh",
)


class AmberNetClassifier:
    """Run exactly two fixed AmberNet windows for one six-second region."""

    def __init__(
        self,
        *,
        session: Any,
        frontend: AmberNetFeatureExtractor,
        expected_label_count: int,
    ) -> None:
        if expected_label_count != len(AMBERNET_LABEL_ORDER):
            raise ValueError("AmberNet label count differs from its locked order")
        self._session = session
        self._frontend = frontend
        self._expected_label_count = expected_label_count

    @classmethod
    def load(
        cls,
        model_dir: Path,
        expected_label_count: int,
    ) -> AmberNetClassifier:
        if expected_label_count != len(AMBERNET_LABEL_ORDER):
            raise ValueError("AmberNet label count differs from its locked order")
        try:
            root = model_dir.resolve(strict=True)
            model_path = (root / MODEL_FILE).resolve(strict=True)
            model_path.relative_to(root)
        except (FileNotFoundError, ValueError) as error:
            raise RuntimeError("the staged AmberNet model is missing") from error
        if not root.is_dir() or not model_path.is_file():
            raise RuntimeError("the staged AmberNet model is invalid")

        import onnxruntime as ort

        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        options.enable_mem_pattern = True
        session = ort.InferenceSession(
            str(model_path),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )
        cls._validate_graph_contract(session, expected_label_count)
        return cls(
            session=session,
            frontend=AmberNetFeatureExtractor(),
            expected_label_count=expected_label_count,
        )

    @staticmethod
    def _validate_graph_contract(session: Any, label_count: int) -> None:
        inputs = session.get_inputs()
        outputs = session.get_outputs()
        if (
            len(inputs) != 1
            or inputs[0].name != "processed_signal"
            or inputs[0].shape != [1, MEL_BINS, PADDED_FRAMES]
            or inputs[0].type != "tensor(float)"
            or len(outputs) != 1
            or outputs[0].name != "logits"
            or outputs[0].shape != [1, label_count]
            or outputs[0].type != "tensor(float)"
            or session.get_providers() != ["CPUExecutionProvider"]
        ):
            raise RuntimeError("AmberNet graph contract is invalid")

    def classify(self, audio: ProbeAudio) -> LidClassification:
        if (
            audio.frame_count != _REGION_SAMPLES
            or len(audio.pcm_bytes) != _REGION_SAMPLES * 2
        ):
            raise RuntimeError("AmberNet requires one exact six-second region")
        samples = np.frombuffer(audio.pcm_bytes, dtype="<i2").astype(np.float32)
        samples /= np.float32(32768.0)

        logits: list[np.ndarray] = []
        for start in (0, WINDOW_SAMPLES):
            features = self._frontend.process(samples[start : start + WINDOW_SAMPLES])
            result = self._session.run(
                ["logits"],
                {"processed_signal": features},
            )
            if (
                not isinstance(result, list)
                or len(result) != 1
                or not isinstance(result[0], np.ndarray)
                or result[0].shape != (1, self._expected_label_count)
                or not np.isfinite(result[0]).all()
            ):
                raise RuntimeError("AmberNet returned malformed classifier output")
            logits.append(np.asarray(result[0][0], dtype=np.float64))

        averaged = (logits[0] + logits[1]) / 2.0
        maximum = float(np.max(averaged))
        log_sum = maximum + math.log(float(np.exp(averaged - maximum).sum()))
        log_probabilities = averaged - log_sum
        order = np.argsort(-log_probabilities, kind="stable")
        top_index = int(order[0])
        second_index = int(order[1])
        return LidClassification(
            raw_label=AMBERNET_LABEL_ORDER[top_index],
            top_score=float(log_probabilities[top_index]),
            score_margin=float(
                log_probabilities[top_index] - log_probabilities[second_index]
            ),
        )


__all__ = [
    "AMBERNET_LABEL_ORDER",
    "AmberNetClassifier",
    "AmberNetFeatureExtractor",
    "MODEL_FILE",
]
