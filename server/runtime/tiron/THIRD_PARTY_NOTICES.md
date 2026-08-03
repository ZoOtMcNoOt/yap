# Tiron meeting runtime notices

The meeting worker is based on NVIDIA's digest-pinned PyTorch 26.06 Linux ARM64
container. NVIDIA container use remains governed by the applicable NVIDIA
software license and product-specific terms. The exact image, Python, Torch,
CUDA, package, and source identities are recorded in
`server/meeting-transcription-runtime.lock.json`.

## Meeting model and runtime

- `Trelis/tiron` is consumed from the immutable July 23, 2026 revision in the
  runtime lock. The model card declares Apache-2.0. The model card does not
  disclose complete training/adaptation lineage, so Yap records that limitation
  and does not infer an external redistribution approval from technical access.
- `TrelisResearch/tiron` is the upstream whole-meeting runtime, not example code
  copied into Yap. Revision
  `d249c5a81fc6e0f1ecd34fd30cf2519f06fe671c` is installed as the runtime's
  verified source dependency. Its pinned Apache-2.0 source owns 30-second chunking,
  constrained decoding, the staggered second pass, ECAPA linking, and output
  formatting. Yap adds a thin isolated worker boundary around that dependency.
- The pinned runtime repeats its ECAPA Hub identifier inside the SpeechBrain
  hyperparameters, which would attempt a download even after a verified local ECAPA
  directory is selected. Yap applies one fail-closed Apache-2.0-compatible
  build patch that overrides that existing field with the configured source.
  No decoding, chunking, linking, clustering, or output behavior is replaced.
- `speechbrain/spkrec-ecapa-voxceleb` is the pinned anonymous speaker-embedding
  checkpoint used by the upstream runtime. Its model card declares Apache-2.0.
- `speechbrain` 1.1.0 and `HyperPyYAML` 1.2.3 are Apache-2.0. The exact Apache
  license text already retained at `server/runtime/asr/licenses/APACHE-2.0.txt`
  has SHA-256
  `c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4`.
- `ruamel.yaml` 0.18.16 and `ruamel.yaml.clib` 0.2.14 are MIT. Their selected
  wheel hashes are in `requirements.lock`; the embedded license payload hashes
  are `0ce9ad6a9d4f0829296a72c77d07795dd67f42751e2922be56c051d39ae1c011`
  and `99f72489621ceea1254f9f0ea7c6e8a5e8e38b62edd1d983e6e1cb20d533f0a6`.
- TorchAudio is built from pinned upstream `v2.11.0` source under BSD-2-Clause
  against the NVIDIA Torch build with CUDA audio operators disabled. This avoids
  installing the PyPI wheel compiled for a different CUDA release. The retained
  license text is
  `server/runtime/cohere-vllm/licenses/TORCHAUDIO-BSD-2-Clause.txt`; the exact
  upstream license bytes and hash are recorded in the runtime lock.

## Shared Python overlay

The remaining resolver-minimal distributions and licenses are the same pinned
artifacts inventoried in `SHARED_PYTHON_THIRD_PARTY_NOTICES.md`, which is copied
into this image beside this notice. That inventory includes the ISC-licensed
`librosa` package and the LGPL-2.1-or-later `soxr`/bundled-audio-library closure.
Their exact ARM64 wheel hashes are repeated in this runtime's `requirements.lock`
so the meeting image does not depend on another image or a mutable resolver
result. Wheel-bundled license and notice files remain installed with the wheels.

The worker must run without network access and from verified local model,
speaker-encoder, and harness artifacts. Public benchmark audio, private meeting
audio, references, hypotheses, and raw receipts are evaluation inputs and are
not distributed in the runtime image.
