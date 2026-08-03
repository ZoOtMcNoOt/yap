# Component installability, the AmberNet replacement, and Tiron suitability

**Date:** 2026-08-02
**Status:** evidence and verdicts; every upstream claim below was verified
against the network or the repository on this date, not recalled.

Three questions answered together because their evidence overlaps: what can
ship in the installer, what replaces AmberNet, and whether Tiron is fit to
carry Phase 8's meeting stage.

## 1. Installable components

The product goal is first-run UX: install, open, dictate — no downloads, no
explanations. What stands between here and that, component by component:

| Component | Size | Licence | Verdict |
| --- | --- | --- | --- |
| sherpa-onnx runtime archives | 114.3 MB | Apache-2.0 | **Bundle.** No obstacle. |
| Silero VAD v4 (k2 export) | 0.6 MB | MIT model, Apache-2.0 exporter | **Bundle.** No obstacle. |
| Nemotron streaming ASR int8 (encoder+decoder+joiner+tokens) | 650.6 MB | **Undeclared** on the re-export repo (`csukuangfj2/...`); upstream NVIDIA terms not recorded in this repository | **Blocked on licence provenance**, not on engineering. See below. |
| AmberNet LID int8 | 28.2 MB | NGC ToU §5(e)/(h): no derivatives, no distribution absent a Product Agreement; none is specified for the model | **Do not bundle. Replace** (§2). |
| PowerShell 7.4, WebView2 | — | already handled by installer/runtime | no change |

The surprise was the third row — and it resolved the same day. The re-export
repository declares no licence, but the upstream is
`nvidia/nemotron-3.5-asr-streaming-0.6b`, published under **OpenMDW-1.1**:
"deal in the Model Materials without restriction", commercial use included,
with one condition — the distribution must carry the licence text and the
origin notices. Bundling is therefore permitted. Two cautions for the
implementation: record the full lineage (NVIDIA upstream → sherpa-onnx int8
re-export) in `model-artifacts.lock.json` and carry the OpenMDW text in
`THIRD_PARTY_NOTICES.md`; and do not confuse this model with its near-name
sibling `nemotron-speech-streaming-en-0.6b`, which sits under the more
conditional NVIDIA Open Model License. The owner should eyeball
<https://openmdw.ai/license/1-1/> once before the first bundling release.

Installer arithmetic with every row now clear: 213.6 MB (today's NSIS)
+ 114.3 + 0.6 + 650.6 + 22.4 (the built ECAPA LID) ≈ **1.0 GB**, eliminating
every first-run download.

## 2. The AmberNet replacement

**Verdict: replace AmberNet with `speechbrain/lang-id-voxlingua107-ecapa`,
exported once to int8 QDQ ONNX, served exactly as AmberNet is served today.
Do not bring the SpeechBrain runtime anywhere near the client.**

Evidence, in the order it was found:

- **Licence.** The ECAPA model is Apache-2.0 (verified on the hub, 112k
  downloads). Export, quantisation, and redistribution are permitted with
  attribution — everything NGC ToU §5(e) forbids for AmberNet.
- **History, from the recovered Phase 6 stash**
  (`yap-archive/stash1-speechbrain-resource-gate`, 1,719 lines): the exact
  same model — pinned revision `0253049a` — was Yap's LID before AmberNet.
  What was evaluated and abandoned was not the model but its **runtime**: a
  containerized Torch/SpeechBrain service on the GB10, gated at 1 GB RSS /
  2 GB cgroup / ~4 cores for one small classifier. AmberNet won because it
  arrived as int8 ONNX. The lesson is "no SpeechBrain runtime", not "no ECAPA".
- **The serving seam is already generic.** `ambernet_language_detector.rs`
  drives a raw `ort` session — one input (`processed_signal`), one output
  (`logits`). An ECAPA export lands in the same shape with a different
  feature frontend and label map.
- **Same corpus, superset coverage.** VoxLingua107 is the corpus AmberNet
  itself trained on; all 28 languages in `SUPPORTED_LOCAL_ASR_LOCALES` are in
  its 107. The exact label order gets pinned by the export, as
  `rawNewlineLabelOrderSha256` pins AmberNet's today.
- **Phase 8 synergy.** Tiron's speaker linking pins
  `speechbrain/spkrec-ecapa-voxceleb` (verified in the harness source at the
  locked revision) — the same SpeechBrain ECAPA family. The server stack
  carries SpeechBrain/Torch in Phase 8 regardless, so the one-off export
  environment for the LID conversion is infrastructure Phase 8 needs anyway.

**Executed the same day** (`server/tools/lid-ecapa/`): the export ran, cold,
from the in-repo recipe. Torch/ONNX parity 3.1e-05; int8 QDQ artifact
22.4 MB (smaller than AmberNet's 28.2) at 49 ms per 7.4 s clip on CPU;
weight sidecar bit-reproducible across export runs. Scored on the five
NVIDIA test clips plus the LibriSpeech fixture: ar/de/en/fr and
LibriSpeech-en all correct at >= 0.98 in both precisions; **Spanish resolved
to Galician (0.86 fp32 / 0.94 int8) on the single es clip** — identical in
both precisions, so it is the model, not the quantisation, and it is the
first concrete datapoint the per-locale gate must weigh. Hashes and observed
results are pinned in `ecapa-voxlingua107-lid.lock.json`; a golden parity
fixture for the future Rust fbank frontend is committed beside it.

Remaining work items (bounded, in order): export script (torch + speechbrain, run once,
lineage recorded like AmberNet's `export_classifier_onnx.py`), int8 QDQ
quantisation, frontend spec for ECAPA's fbank input (replacing
`nemo-fixed-3s-v1`), label-map pin, artifact/lock/provenance swap, and an
accuracy comparison against AmberNet on per-locale sample audio **before** the
route flips. The published claims (AmberNet's paper reports an edge over
ECAPA on the full 107) do not answer the 28-language subset; only the
comparison does.

## 3. Tiron for the Phase 8 meeting stage

**Verdict: suitable to proceed exactly as ADR 0027 already frames it — a
development baseline whose production promotion is evidence-gated. Nothing
found today weakens the ADR; several of its pins are now independently
verified; the risk register below is what Phase 8 must burn down.**

**Phase 8 execution update:** the July 21 intake identities below were
superseded before execution by model revision
`90bc0a4d198cd5cf6679b0e478375ba3a0040575`, weight SHA-256
`2e9f644c5eb633d3c387975cf38677d3ffe1a7b98830a735867865ec1bd519b5`,
and runtime revision `d249c5a81fc6e0f1ecd34fd30cf2519f06fe671c`.
The complete runtime/ECAPA/dependency lock and acceptance contract now execute.
A focused offline GB10 image/worker smoke has passed; quality, concurrency,
long-session, and promotion evidence remain open. The table below is preserved
as the original intake snapshot, not current runtime authority.

Verified today against upstream (none of this previously had independent
confirmation):

| ADR claim | Verified |
| --- | --- |
| Model `Trelis/tiron` rev `aed145c7...` | ✅ resolves; repo HEAD has moved (`90bc0a4d...`), so the pin is doing its job |
| Weight 3,087,229,512 bytes, SHA-256 `921e078a...` | ✅ byte-exact via hub paths-info at the pinned revision |
| Harness `TrelisResearch/tiron` rev `5b3766ac...` | ✅ exists, committed 2026-07-21 |
| Apache-2.0 on both | ✅ model card tag and repository LICENSE both check out |
| 8-local/8-global caps, 30 s windows, two-pass default | ✅ `tiron/config.py`: `MAX_LOCAL_SPEAKERS = 8`, `MAX_GLOBAL_SPEAKERS = 8`, `CHUNK_MAX_SEC = 30.0`, `TWO_PASS_DEFAULT = True`, plus `MAX_AUDIO_SECONDS = 10800` (a 3-hour harness ceiling the ADR does not mention — long-meeting work must handle it) |
| Unpinned dependencies | ✅ `pyproject.toml` lists `torch`, `transformers>=4.46`, `speechbrain`, `librosa` — no versions. The Phase 8 lock is real work. |
| ECAPA linking | ✅ `ECAPA_MODEL = "speechbrain/spkrec-ecapa-voxceleb"` — a **runtime hub download** in the reference harness, which the worker lock must convert to a pinned local artifact (the ADR already forbids runtime downloads) |

GB10 feasibility, from what this box already proves: 3.1 GB fp16 weights plus
ECAPA is trivial against 128 GB unified memory, and Torch-on-GB10 is standing
infrastructure here (the nemo/vllm serving scripts in `infra/yap-server-node`).
The genuinely unknown quantities — latency, RTF, concurrency, cancellation,
long-session stability, multilingual quality — are exactly what ADR 0027's
frozen suite exists to measure, and running quality hypotheses **before** the
corpus manifest freeze would violate the ADR's own evidence discipline. That
freeze (implementation step 1) is therefore the first Phase 8 action, not a
formality.

Risk register, ranked by how likely each is to bite:

1. **Dependency lock effort is front-loaded.** Nothing is pinned upstream;
   Torch/SpeechBrain/Transformers on arm64 CUDA have to be locked and
   reviewed before the first qualification run.
2. **English-only published evidence** against Yap's multilingual
   requirement — the largest open product question, unanswerable until the
   suite runs.
3. **The 3-hour harness ceiling and 8-global cap** both need typed degraded
   routes in the product contract, not just scorer awareness.
4. **New-release risk**: eleven days old at ADR time, no independent
   reproduction anywhere yet. Yap's reproduction on GB10 will likely be the
   first.

## Sequencing recommendation

1. ~~Nemotron licence determination~~ — resolved above: OpenMDW-1.1,
   bundleable with notices.
2. Installer bundling implementation (all components now clear), plus the
   ECAPA per-locale comparison before the LID route flips.
3. Complete the sealed private messy-meeting holdout, then run the locked Tiron
   runtime through the remaining Phase 8 integration and evidence sequence.
