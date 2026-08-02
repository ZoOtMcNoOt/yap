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

The surprise is the third row. The 28 MB AmberNet question consumed this
week's licence attention while the **650 MB primary local ASR** ships from a
Hugging Face re-export repository that declares no licence at all, and this
repository records dataset licences in detail but not the model's. Nemotron
models are NVIDIA-published; whether the applicable terms are an open model
licence or NGC-ToU-shaped decides whether the installer may carry the model or
must fetch it on first run with terms acceptance. That determination is the
single blocking item for the "everything in the installer" goal and needs the
same treatment AmberNet got: read the governing document for the exact
artifact lineage, record it in `model-artifacts.lock.json`, and have the owner
sign it.

Installer arithmetic if all three model rows clear: 213.6 MB (today's NSIS)
+ 114.3 + 0.6 + 650.6 + ~25 (replacement LID) ≈ **1.0 GB**, eliminating every
first-run download. If Nemotron cannot be redistributed, the honest UX is one
explicit "download speech model (650 MB)" step on first run, hash-verified
against the existing pins — the plumbing for which (`stt/model.rs`,
hash-verified HF fetch) already exists and is what runs today.

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

Work items (bounded, in order): export script (torch + speechbrain, run once,
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

1. Nemotron licence determination (blocks §1's goal; smallest effort,
   largest UX consequence either way).
2. ECAPA export + comparison (unblocks bundling LID; independent of Phase 8).
3. Phase 8 step 1 — freeze the messy-meeting manifest — then the Tiron
   runtime lock, per ADR 0027's own sequence.
