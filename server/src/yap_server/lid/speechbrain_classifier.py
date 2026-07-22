from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any

from .worker_contract import LidClassification, ProbeAudio


_OFFLINE_ENVIRONMENT = {
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "DO_NOT_TRACK": "1",
}


class SpeechBrainClassifier:
    """Small adapter around the pinned SpeechBrain EncoderClassifier API."""

    def __init__(
        self,
        *,
        engine: Any,
        torch_module: Any,
        expected_label_count: int,
    ) -> None:
        if (
            isinstance(expected_label_count, bool)
            or not isinstance(expected_label_count, int)
            or expected_label_count < 2
        ):
            raise ValueError("expected_label_count must be an integer of at least two")
        self._engine = engine
        self._torch = torch_module
        self._expected_label_count = expected_label_count

    @classmethod
    def load(
        cls,
        model_dir: Path,
        expected_label_count: int,
    ) -> SpeechBrainClassifier:
        """Load only hash-staged local weights on CPU with fetching disabled."""

        if (
            isinstance(expected_label_count, bool)
            or not isinstance(expected_label_count, int)
            or expected_label_count < 2
        ):
            raise ValueError("expected_label_count must be an integer of at least two")

        try:
            root = model_dir.resolve(strict=True)
        except FileNotFoundError as error:
            raise RuntimeError("the staged LID model directory is missing") from error
        if not root.is_dir():
            raise RuntimeError("the staged LID model path is not a directory")

        for name, value in _OFFLINE_ENVIRONMENT.items():
            os.environ[name] = value

        import torch
        from speechbrain.inference.classifiers import EncoderClassifier
        from speechbrain.utils.fetching import FetchConfig, LocalStrategy

        local_path = str(root)
        engine = EncoderClassifier.from_hparams(
            source=local_path,
            hparams_file="hyperparams.yaml",
            savedir=local_path,
            overrides={"pretrained_path": local_path},
            run_opts={"device": "cpu"},
            local_strategy=LocalStrategy.NO_LINK,
            fetch_config=FetchConfig(
                allow_network=False,
                allow_updates=False,
            ),
        )
        hparams = getattr(engine, "hparams", None)
        label_encoder = getattr(hparams, "label_encoder", None)
        expect_len = getattr(label_encoder, "expect_len", None)
        if label_encoder is None or not callable(expect_len):
            raise RuntimeError("SpeechBrain returned a malformed label encoder")
        try:
            expect_len(expected_label_count)
            actual_label_count = len(label_encoder)
        except Exception as error:
            raise RuntimeError("SpeechBrain label count validation failed") from error
        if actual_label_count != expected_label_count:
            raise RuntimeError("SpeechBrain label count validation failed")
        return cls(
            engine=engine,
            torch_module=torch,
            expected_label_count=expected_label_count,
        )

    def classify(self, audio: ProbeAudio) -> LidClassification:
        """Return raw uncalibrated log-posterior evidence for one probe."""

        buffer = bytearray(audio.pcm_bytes)
        waveform = self._torch.frombuffer(buffer, dtype=self._torch.int16)
        waveform = waveform.to(dtype=self._torch.float32).div_(32768.0)
        with self._torch.inference_mode():
            out_prob, _score, _index, text_labels = self._engine.classify_batch(
                waveform
            )
        if (
            getattr(out_prob, "ndim", None) != 2
            or len(out_prob.shape) != 2
            or out_prob.shape[0] != 1
            or out_prob.shape[1] != self._expected_label_count
            or not isinstance(text_labels, (list, tuple))
            or len(text_labels) != 1
            or not isinstance(text_labels[0], str)
        ):
            raise RuntimeError("SpeechBrain returned malformed classifier output")
        raw_scores = out_prob[0].detach().cpu().tolist()
        if not isinstance(raw_scores, list) or len(raw_scores) != out_prob.shape[1]:
            raise RuntimeError("SpeechBrain returned malformed classifier output")
        scores: list[float] = []
        for value in raw_scores:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise RuntimeError("SpeechBrain returned malformed classifier output")
            score = float(value)
            if not math.isfinite(score):
                raise RuntimeError("SpeechBrain returned malformed classifier output")
            scores.append(score)
        top_score, second_score = sorted(scores, reverse=True)[:2]
        return LidClassification(
            raw_label=text_labels[0],
            top_score=top_score,
            score_margin=top_score - second_score,
        )
