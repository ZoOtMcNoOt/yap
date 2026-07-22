# Yap native NeMo Nemotron runtime notices

This non-production reference worker is built from these immutable identities:

- NVIDIA PyTorch 26.06 for Linux ARM64 at the digest recorded in
  `server/nemotron-nemo-serving.lock.json`, under the NVIDIA Software License
  Agreement and Product-Specific Terms for NVIDIA AI Products.
- NVIDIA NeMo source commit
  `ba2cd63ef8de8a3183a3c02b310c66d616b9a991`, built without local source
  changes under Apache-2.0. The complete Apache 2.0 text ships in the image.
- `nvidia/nemotron-3.5-asr-streaming-0.6b` revision
  `f3d333391852ba876df169dcc9ba902d25b6ab0b`, consumed as the canonical `.nemo`
  checkpoint under OpenMDW-1.1. The complete model agreement ships in the
  image; the model itself is mounted and hash-verified at runtime.

## Hash-locked Python overlay

Exact versions and ARM64 wheel SHA-256 hashes are authoritative in
`requirements.lock`. The installed wheels retain their bundled license and
notice files. License metadata and upstream records were reviewed in these
groups:

| License | Distributions |
|---|---|
| Apache-2.0 | `intervaltree`, `kaldialign`, `lhotse`, `lightning`, `lightning-utilities`, `msgpack`, `nv-one-logger-core`, `nv-one-logger-pytorch-lightning-integration`, `nv-one-logger-training-telemetry`, `overrides`, `pytorch-lightning`, `sacrebleu`, `sentencepiece`, `sortedcontainers`, `tenacity`, `tokenizers`, `torchmetrics`, `transformers` |
| BSD-2-Clause | `wrapt` |
| BSD-3-Clause | `cloudpickle`, `colorama`, `cytoolz`, `fsspec`, `joblib`, `lazy-loader`, `lxml`, `msgspec`, `pooch`, `portalocker`, `scikit-learn`, `soundfile`, `threadpoolctl`, `toolz`, `webdataset` |
| MIT | `aistore`, `audioread`, `braceexpand`, `humanize`, `hydra-core`, `indic-numtowords`, `more-itertools`, `narwhals`, `smart-open`, `StrEnum`, `toml`, `whisper-normalizer` |
| Apache-2.0 OR BSD-2-Clause | `packaging` |
| ISC | `librosa` |
| LGPL-2.1-or-later | `soxr` |
| Artistic License | `text-unidecode` |

The `soundfile` wheel contains libsndfile and its LGPL notice. The `soxr` wheel
contains the libsoxr LGPL notice and bundled PFFFT notice. The pinned NVIDIA
base supplies Torch, CUDA, NumPy, OmegaConf, Hugging Face Hub, Safetensors, and
other already-installed dependencies under its included notices and terms.

The worker and model remain evaluation candidates. Yap does not imply
endorsement by NVIDIA, Hugging Face, OpenSLR, or the LibriSpeech authors.
