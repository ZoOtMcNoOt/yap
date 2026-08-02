# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "torch==2.11.0",
#   "torchaudio==2.11.0",
#   "speechbrain==1.1.0",
#   "onnx",
#   "onnxruntime",
#   "onnxscript",
#   "soundfile",
#   "numpy",
#   "huggingface_hub",
# ]
# [[tool.uv.index]]
# url = "https://download.pytorch.org/whl/cpu"
# ///
"""Build the ECAPA VoxLingua107 LID artifacts that replace AmberNet.

Run once, at build time, with `uv run build_ecapa_lid_artifacts.py`. The
client never sees SpeechBrain or Torch: it serves the int8 ONNX through the
same raw `ort` session shape AmberNet uses (`processed_signal` -> `logits`).
That division is deliberate — the Phase 6 stash
(`yap-archive/stash1-speechbrain-resource-gate`) records this exact model
being abandoned over its containerized Torch runtime, not its quality.

Torch and torchaudio are pinned as a pair because mismatched builds fail at
import with an ABI error, and torch 2.13 has no matching torchaudio.

Outputs, plus a lock block printed at the end for
`ecapa-voxlingua107-lid.lock.json`:

- ecapa-voxlingua107-lid-fp32.onnx (+ .data)  — reference artifact
- ecapa-voxlingua107-lid-int8-qdq.onnx        — the client artifact (~22 MB)
- ecapa-voxlingua107-labels.json              — 107 labels in index order,
  plus the fbank frontend parameters the Rust client must reproduce

The exported graph takes log-mel fbank features ([batch, frames, 60], the
model's own `compute_features` output) and returns log-softmax logits over
the 107 VoxLingua107 labels. Feature extraction stays client-side, exactly as
AmberNet's `nemo-fixed-3s-v1` frontend does today; the parity fixture this
script emits is what the Rust frontend implementation asserts against.

Quantisation covers Conv/MatMul/Gemm only. Quantising everything breaks the
graph's shape machinery at runtime (`Expand: invalid expand shape`), and the
symbolic shape-inference preprocessing pass dies on a Range node — both are
exporter/tooling interactions, not model defects.

Observed on 2026-08-02 (five NVIDIA test clips + the LibriSpeech fixture):
fp32 and int8 agree; ar/de/en/fr and LibriSpeech-en all correct at >=0.98;
Spanish resolves to Galician (0.86 fp32 / 0.94 int8) on the single es clip in
both precisions. That confusion is the exact class of evidence the per-locale
comparison gate must weigh before the route flips — record, do not shrug.
"""
from __future__ import annotations

import json
import sys
import time
from hashlib import sha256
from pathlib import Path

import numpy as np
import onnxruntime
import soundfile
import torch
import torchaudio
from huggingface_hub import HfApi
from onnxruntime.quantization import (
    CalibrationDataReader,
    QuantFormat,
    QuantType,
    quantize_static,
)
from speechbrain.inference.classifiers import EncoderClassifier

MODEL_SOURCE = "speechbrain/lang-id-voxlingua107-ecapa"
# The revision the Phase 6 resource-gate profile pinned; also today's hub HEAD.
REVISION = "0253049ae131d6a4be1c4f0d8b0ff483a0f8c8e9"
OUT = Path(".")

FP32 = OUT / "ecapa-voxlingua107-lid-fp32.onnx"
INT8 = OUT / "ecapa-voxlingua107-lid-int8-qdq.onnx"
LABELS = OUT / "ecapa-voxlingua107-labels.json"
PARITY = OUT / "ecapa-voxlingua107-parity-fixture.json"

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_WAV = REPO_ROOT / "server" / "tests" / "fixtures" / "asr" / "2086-149220-0033.wav"


def main() -> None:
    # SpeechBrain's loader takes no revision; refuse to export drift instead.
    actual = HfApi().model_info(MODEL_SOURCE).sha
    if actual != REVISION:
        raise SystemExit(f"hub moved: {actual} != pinned {REVISION}; re-review before exporting")

    classifier = EncoderClassifier.from_hparams(
        source=MODEL_SOURCE, savedir="./sb-cache", run_opts={"device": "cpu"}
    )
    classifier.eval()

    class LidHead(torch.nn.Module):
        """fbank features -> normalize -> embed -> classify -> log-probs."""

        def __init__(self, embedding_model, classifier_head, normalizer):
            super().__init__()
            self.embedding_model = embedding_model
            self.classifier_head = classifier_head
            self.normalizer = normalizer

        def forward(self, features: torch.Tensor) -> torch.Tensor:
            lengths = torch.ones(features.shape[0], device=features.device)
            x = self.normalizer(features, lengths)
            embedding = self.embedding_model(x, lengths)
            return self.classifier_head(embedding).squeeze(1)

    model = LidHead(
        classifier.mods.embedding_model,
        classifier.mods.classifier,
        classifier.mods.mean_var_norm,
    )
    model.eval()

    def features_for(path: Path) -> np.ndarray:
        wave, rate = soundfile.read(path, dtype="float32")
        if wave.ndim > 1:
            wave = wave.mean(axis=1)
        tensor = torch.from_numpy(wave).unsqueeze(0)
        if rate != 16000:
            tensor = torchaudio.functional.resample(tensor, rate, 16000)
        return classifier.mods.compute_features(tensor).numpy()

    fixture_feats = features_for(FIXTURE_WAV)
    example = torch.from_numpy(fixture_feats)
    with torch.no_grad():
        reference = model(example)

    torch.onnx.export(
        model,
        (example,),
        str(FP32),
        input_names=["processed_signal"],
        output_names=["logits"],
        dynamic_axes={"processed_signal": {0: "batch", 1: "frames"}, "logits": {0: "batch"}},
        opset_version=17,
    )

    session = onnxruntime.InferenceSession(str(FP32))
    onnx_logits = session.run(["logits"], {"processed_signal": fixture_feats})[0]
    drift = float(np.abs(onnx_logits - reference.numpy()).max())
    if drift >= 1e-3:
        raise SystemExit(f"torch/onnx parity failed: {drift}")

    class Reader(CalibrationDataReader):
        def __init__(self) -> None:
            self.items = iter([{"processed_signal": fixture_feats}])

        def get_next(self):
            return next(self.items, None)

    quantize_static(
        str(FP32),
        str(INT8),
        Reader(),
        quant_format=QuantFormat.QDQ,
        activation_type=QuantType.QInt8,
        weight_type=QuantType.QInt8,
        op_types_to_quantize=["Conv", "MatMul", "Gemm"],
    )

    int8_session = onnxruntime.InferenceSession(str(INT8))
    int8_logits = int8_session.run(["logits"], {"processed_signal": fixture_feats})[0]

    encoder = classifier.hparams.label_encoder
    labels = [encoder.ind2lab[i] for i in range(len(encoder.ind2lab))]
    if labels[int(int8_logits[0].argmax())].split(":")[0] != "en":
        raise SystemExit("int8 artifact no longer identifies the English fixture")

    LABELS.write_text(json.dumps({
        "revision": REVISION,
        "labels": labels,
        "frontend": {
            "sampleRateHz": 16000,
            "nMels": int(fixture_feats.shape[2]),
            "framesFor3s": 301,
        },
    }, indent=1))

    # Golden parity fixture for the Rust frontend implementation: the exact
    # features SpeechBrain computes for the in-repo LibriSpeech clip, and the
    # logits both artifacts produce from them.
    PARITY.write_text(json.dumps({
        "wav": "server/tests/fixtures/asr/2086-149220-0033.wav",
        "featuresShape": list(fixture_feats.shape),
        "featuresSha256OfLittleEndianF32": sha256(
            fixture_feats.astype("<f4").tobytes()
        ).hexdigest(),
        "fp32Logits": [round(float(v), 5) for v in onnx_logits[0]],
        "int8Logits": [round(float(v), 5) for v in int8_logits[0]],
    }, indent=1))

    start = time.monotonic()
    for _ in range(20):
        int8_session.run(["logits"], {"processed_signal": fixture_feats})
    latency_ms = (time.monotonic() - start) / 20 * 1000

    print("lock block:")
    print(json.dumps({
        "modelSource": MODEL_SOURCE,
        "modelRevision": REVISION,
        "license": "Apache-2.0",
        "artifacts": {
            path.name: {
                "sha256": sha256(path.read_bytes()).hexdigest(),
                "bytes": path.stat().st_size,
            }
            for path in [FP32, FP32.with_suffix(".onnx.data"), INT8, LABELS, PARITY]
        },
        "parityMaxAbsDrift": drift,
        "int8LatencyMsFor7s4Clip": round(latency_ms, 1),
    }, indent=1))


if __name__ == "__main__":
    sys.exit(main())
