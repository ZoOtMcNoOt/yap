# Third-Party Provenance

This page explains Yap's source-reuse and runtime provenance boundaries. The
machine-readable source-adaptation authority is
`THIRD_PARTY_PROVENANCE.json`. The separate lockfile-derived
`SHIPPED_DEPENDENCY_INVENTORY.json` accounts for the packaged desktop
JavaScript and Rust graphs. Shipped notices are in `THIRD_PARTY_NOTICES.md`
and the server runtime license tree.

## Direct source adaptation

Yap currently records two directly adapted source identities:

| Source ID | Upstream | Revision | License | Local scope |
| --- | --- | --- | --- | --- |
| `freeflow-zachlatta` | `zachlatta/freeflow` | `7427ca982c19746770f5357ced16e993f2eb27fd` | MIT | Live overlay/presentation/waveform/reduced-motion files and audio preprocessing listed in the machine manifest. |
| `torchaudio-mel-filterbank` | `pytorch/audio` | `34c52a67e8941bbd8e6adaca0eb0b9eabec11d78` | BSD-2-Clause | Narrow Mel filter-bank compatibility implementation used only by the Cohere vLLM runtime; exact derivative paths and upstream source hash are in the machine manifest. |

The manifest records upstream source hashes, the upstream license hash, every
attributed local derivative path, and each local SHA-256. The release contract
can verify the pinned upstream and rejects an unrecorded local change.

`mrinalwadhwa/freeflow` is a separate Apache-2.0 repository used only as a
reviewed behavior donor. It must never be conflated with the MIT
`zachlatta/freeflow` source identity. Meetily is also a reviewed workflow donor;
the 2026-07-12 audit did not authorize or incorporate donor code. See the
[Freeflow/Meetily reuse audit](../research/2026-07-12-freeflow-meetily-reuse-audit.md).

## Active Phase 8 meeting runtime

ADR 0027 selects `Trelis/tiron` as the server development baseline. Phase 8
locks model revision `90bc0a4d198cd5cf6679b0e478375ba3a0040575`,
the 3,087,229,512-byte weight SHA-256
`2e9f644c5eb633d3c387975cf38677d3ffe1a7b98830a735867865ec1bd519b5`,
upstream whole-meeting runtime revision
`d249c5a81fc6e0f1ecd34fd30cf2519f06fe671c`, and ECAPA revision
`0f99f2d0ebe89ac095bcc5903c4dd8f72b367286`. The pre-execution July 21
model/weight/harness identities remain recorded in the machine lock only as an
explicitly superseded set and are not mixed with this runtime.

The upstream runtime and model repositories declare Apache-2.0, and the public
comparator declares CC-BY-4.0. Exact source, package, image, license-declaration,
and compatibility-patch identities are recorded in
`server/meeting-transcription-runtime.lock.json` and the runtime notices. The
worker forbids downloads and applies one measured, hash-bound patch so
SpeechBrain uses the verified local ECAPA directory rather than repeating its
Hub identifier. Complete model training/adaptation lineage and redistribution
approval remain open promotion requirements; technical access does not invent
that approval.

## Dependency and runtime provenance

- Frontend packages are declared in `desktop/package.json` and frozen by
  `desktop/pnpm-lock.yaml`. The production graph must exactly match the bundled
  `SHIPPED_DEPENDENCY_INVENTORY.json`.
- Rust crates are declared in `desktop/src-tauri/Cargo.toml` and frozen by
  `desktop/src-tauri/Cargo.lock`; the normal Windows dependency graph must
  exactly match the same inventory, and bundled SQLite notice text is shipped.
- Desktop model/runtime artifacts are pinned separately in
  `desktop/model-artifacts.lock.json`. Silero remains an explicit non-bundled
  install. The selected AmberNet 1.12.0 acoustic-language detector is a
  hash-verified, explicit local-file import: Yap neither bundles nor hosts the
  derived ONNX while organizational review of NVIDIA redistribution terms is
  open. The lock records the upstream model, final and intermediate graph,
  exporter/quantizer, label order, frontend, FLEURS calibration revision, and
  the still-open calibration-manifest and conversion-container identities.
- The portable server requires Python 3.12 (`>=3.12,<3.13`).
- The server's opt-in, non-production `evaluation` extra pins
  [RapidFuzz 3.14.5](https://pypi.org/project/RapidFuzz/3.14.5/) (MIT) for bounded
  edit operations and [`regex` 2026.7.10](https://pypi.org/project/regex/2026.7.10/)
  (Apache-2.0 AND CNRI-Python) for Unicode extended-grapheme segmentation. Exact
  distributions and hashes are frozen in `server/uv.lock`; neither package is
  part of the desktop application, ASR worker image, or serving hot path.
- The GPU worker base is an immutable digest of NVIDIA PyTorch 26.06. The image
  build asserts Python 3.12, the expected NVIDIA Torch build, and CUDA version.
- The Cohere serving candidate derives from NVIDIA vLLM 26.06 at the immutable
  ARM64 digest in `server/cohere-vllm-serving.lock.json`. The build asserts
  Python 3.12, Torch/CUDA, vLLM, Transformers, audio-library, and model identity.
  It adds no compiled Python overlay. The only source compatibility addition is
  the attributed BSD-2-Clause TorchAudio Mel filter-bank function recorded in
  `THIRD_PARTY_PROVENANCE.json`; its full license ships in both the repository
  notice and the runtime license tree.
- The worker's resolver-minimal Python overlay uses exact versions and hashes in
  `server/runtime/asr/requirements.lock`.
- Cohere model, runtime, public byte-distribution, licensed fixture, and
  evidence identities are pinned in `server/model-pools.lock.json`. The
  separate Nemotron serving reference identity, its direct canonical
  distribution, 32 enabled out-of-box locales plus explicit auto mode, exact
  runtime artifacts, and OpenMDW-1.1 terms are pinned in
  `server/nemotron-model-pool.lock.json`.
- The executing resident NeMo service is separately frozen by
  `server/nemotron-nemo-serving.lock.json`; its runtime notices ship from
  `server/runtime/nemotron-nemo/THIRD_PARTY_NOTICES.md`.
- The executing server batch-language suggestion is separately frozen by
  `server/lid-component.lock.json`: one exact AmberNet 1.12.0 INT8 QDQ artifact,
  NeMo-compatible frontend/label order, Python 3.12, NumPy, and CPU ONNX Runtime.
  The model is not bundled, mirrored, or fetched; redistribution remains
  unapproved and an operator import is verified under the applicable NGC terms.
  Runtime notices ship from `server/runtime/lid/THIRD_PARTY_NOTICES.md`. The old
  SpeechBrain/Torch component is retained only in history and a recoverable ref.
- Shared full license texts and the Transformers reference-worker notices ship
  from `server/runtime/asr/licenses/` and
  `server/runtime/asr/THIRD_PARTY_NOTICES.md`. The production ASR, NeMo, and LID
  images explicitly remove `yap_server/evaluation`; evaluation dependencies and
  code enter only through the separate opt-in evaluation image or an explicit
  private qualification source mount.

## Evaluation-only candidates not incorporated

These immutable upstream identities were inspected or executed only inside the
disposable private evaluation boundary. They are not Yap dependencies, are not
shipped, and contribute no source or model bytes to the repository or product.

| Candidate | Source revision | Model revision | License boundary | Decision |
| --- | --- | --- | --- | --- |
| CrispASR ECAPA-LID-107 | `CrispStrobe/CrispASR@259e6ad67bd3b324ca6a313cb02e481e683cfa04` with its pinned ggml submodule | `cstr/ecapa-lid-107-GGUF@95fb0613bf78c6e48305fccd9ce023ac15f0b5a6`, model SHA-256 `59db30ba67cec2f36304f794420779c181124332246f75fc66c349f184110340` | CrispASR source is MIT; the evaluated model repository declares Apache-2.0 separately | Rejected on accuracy, latency, peak private memory, and native dependency surface; no incorporation authorized |
| VoxLingua107 ONNX/tract comparator | Apparent exporter `christopherthompson81/vernacula@2b3d42781338a4af619fa55048e4711f4885b508`; Rust probe used `ort` 2.0.0-rc.12 and `ort-tract` 0.3.0/tract 0.22.3 | `christopherthompson81/voxlingua107-lid-onnx@e02e1da805ae49635fe1aa7913c3f1e7f5f5fde6`, model SHA-256 `e2c3c3da39b99e3f9196d15fceef6a65f702320038bbc08813a4f21280255ce8` | Model repository declares Apache-2.0; the apparent exporter does not pin dependencies/upstream model revision, and its scoped repository licenses do not explicitly cover the root Python export scripts | Behavior/runtime comparator only; no source, model, graph, runtime, or raw evidence incorporated; tract route rejected |

## Reuse policy

Before incorporating external source:

1. record the exact repository and immutable revision;
2. verify the license and preserve required notice/license text;
3. identify the smallest source slice and whether behavior reimplementation is
   safer than direct adaptation;
4. record provenance for every resulting local derivative;
5. add a Yap-owned behavior/security test;
6. run the provenance contract with upstream verification; and
7. keep branding, binaries, models, data, and unrelated code out unless each has
   separate authority and license evidence.

Package-manager dependency metadata is not a substitute for direct-source
provenance. Likewise, visual inspiration or behavior comparison must not be
misrepresented as copied source.
