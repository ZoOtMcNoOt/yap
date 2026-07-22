# Dynamic language detection evaluation

**Date:** 2026-07-16

**Status:** Decision amended 2026-07-18; development-host resource evidence
updated 2026-07-21: a bounded resident local acoustic-LID
component and language diarization are required in Phase 6. Whisper tiny is the
hash-pinned native comparator, not the selected production detector; its frozen
`en-US`/`es-US` narrow-route qualification also failed. Native
CrispASR ECAPA, the official-checkpoint SpeechBrain global-top-label route, and
SpeechFlow LID13 have been measured and rejected. Whisper base global-top
routing also failed the production-window comparator, and the official base and
tiny Q5_1 `whisper.cpp` releases failed the required client throughput preflight
before an accuracy run completed. FireRedLID fails client payload preflight.
AmberNet 1.12.0 was then acquired under the user's explicit evaluation
authorization and independently exported. Its native INT8 route failed the
original zero-false natural/noisy switching gate, after which the product owner
explicitly accepted that exact artifact as a bounded, abstaining route with
visible primary fallback rather than continuing open-ended model research. The
exact native runtime and local-import lifecycle now execute, but redistribution
obligations remain unreviewed. The selection boundary remains restricted to
immutable released checkpoints; custom training or distillation is not the
Phase 6 solution. No automatic route has passed the complete Phase 6 promotion
gate.

**Decision owner:** [ADR 0024](../adr/0024-global-language-routing.md)

## Question

Can Yap dynamically identify language without forcing every user to choose a
language before every recording, including mixed-language recordings?

The answer depends on the temporal claim:

1. **Clip-level LID** returns one language for an input clip.
2. **Finalized-segment LID** returns one language for each VAD/endpointed
   utterance and may change only between finalized segments.
3. **Language diarization** locates language switches inside one utterance at
   frame, token, word, or span resolution.

These are not interchangeable capabilities.

## Current decision

ADR 0024 now defines three explicit, composable paths:

- fixed work uses the confirmed primary/manual language, with SpeechBrain only
  as an optional long-recording suggestion; and
- local dynamic work uses one bounded resident acoustic-LID component to emit
  source-time language spans and drive the single Nemotron ASR through
  exact-once bounded holdback/finalize/reset transitions while offline; and
- server dynamic work uses Nemotron 3.5 `target_lang=auto` on bounded finalized
  VAD segments as independent evidence.

Nemotron is the current server candidate whose documented output directly fits
the third contract: its 600M streaming model appends one detected locale tag
to each utterance, and its 32 transcription-ready or broad-coverage locales
work out of the box. The eight adaptation-ready locales remain excluded. This
does **not** establish the second contract: a terminal utterance tag is not
within-utterance language diarization.

No dynamic capability enters Yap's executable catalog until its immutable
runtime/model lock, public multilingual fixtures, tag parser, unknown-tag
behavior, resource ceiling, cancellation/restart behavior, and exact evidence
revision pass the Phase 6 gate.

## Candidate comparison

| Candidate | What it documents | Fit for Yap | Decision |
| --- | --- | --- | --- |
| NVIDIA Nemotron 3.5 ASR 0.6B | Optional automatic detection; one terminal locale tag per utterance; 19 transcription-ready, 13 broad-coverage, and 8 adaptation-ready locales | Direct match for bounded finalized-segment detection; same transcription pass supplies text and tag | Phase 6 dynamic candidate; benchmark and lock before advertising |
| Qwen3-ASR 1.7B and 0.6B | One parsed language plus transcription per input; 30 languages and 22 Chinese dialects; offline and streaming; Apache-2.0 | Strong server batch/coverage challengers, but the documented contract is one language per input rather than span labels. Current streaming is vLLM-only, single-stream, unbatched, timestamp-free, and re-feeds accumulated audio | Benchmark 1.7B first for server batch; do not call either model language diarization |
| Microsoft VibeVoice-ASR | 9B BF16; 51 languages; up to 60-minute input; speaker, timestamp, transcript output; claims native code-switch handling; MIT | Promising long-form batch challenger, but much heavier and its documented structured output does not establish per-span language labels | Benchmark for mixed long-form transcription; not the LID component |
| SAGE-LD | Research architecture produces fine-grained language diarization from 25 ms features and reports gains on language-diarization benchmarks | It addresses the correct within-utterance problem | Research comparator only: official repository has no release, published checkpoint, or visible license |
| SpeechBrain VoxLingua107 | One clip-level language estimate | Useful bounded suggestion for longer fixed-language imports; a native export would need a fully pinned feature pipeline and desktop resource gate | Python runtime is not a continuous local route; native-format challenger remains unpromoted |
| TalTech VoxLingua107 EPACA-TDNN | First-party Apache-2.0 release covering 107 languages; a distinct direct-cosine classifier/checkpoint with publisher-reported 7% error on the 33-language volunteer-validated VoxLingua107 development set | Same approximate FP32 payload class as the rejected SpeechBrain ECAPA route, but materially different weights and classifier head made it a legitimate released-checkpoint challenger | Rejected at the bounded public behavior preflight: 73/84 case pluralities and 1,098/1,539 windows did not beat the 77/84 and 1,101/1,539 official SpeechBrain baseline; no policy sweep, export, packaging, or holdout followed |
| Whisper-base CommonLanguage audio classifier | Apache-2.0 encoder-only 45-language release with publisher-reported 75.25% evaluation accuracy; an 83 MB community ONNX conversion also exists | Better runtime shape than decoder-based Whisper LID, but narrower coverage, incomplete model-card detail, and weak reported accuracy | Lower-priority challenger; do not acquire or trust the community export unless the first-party checkpoint first clears a behavior preflight |
| DistilHuBERT CommonLanguage classifier | Apache-2.0 45-language release with a roughly 95 MB checkpoint | Publisher-reported 27.97% evaluation accuracy is below a credible production preflight | Rejected from acquisition at model-card accuracy preflight |
| SpeechBrain CommonLanguage ECAPA | Official Apache-2.0 45-language checkpoint with publisher-reported 85% test accuracy | Released and reproducible, but does not match the desired global coverage and does not reduce the ECAPA payload/runtime class | Retain as a lower-coverage research comparator; do not spend a promotion holdout |
| sherpa-onnx Whisper tiny LID | Acoustic clip-level LID in the desktop's existing native runtime | Avoids a second framework, but the measured resident-memory increase is not negligible beside the dictation model | Retained as the native comparator baseline; rejected for broad automatic switching after only 56/84 correct cases and 767/1,539 correct production-sized windows, then rejected for the narrow `en-US`/`es-US` route after its frozen disjoint gate missed natural switch segments and boundaries |
| sherpa-onnx Whisper base INT8 proxy | Released community conversion of Whisper base in Yap's existing native runtime | Useful behavior proxy, but its two ONNX files total 159,792,560 bytes and global-top routing still systematically confuses related languages | Rejected for broad switching after 64/84 correct case pluralities and 886/1,539 correct production-sized windows; conversion provenance is not promotion-grade |
| official `whisper.cpp` Whisper tiny Q5_1 | MIT release with a 32,152,673-byte Q5_1 model and the enabled-set probability API missing from the Sherpa comparator | Materially different scoring interface and smaller than the base Q5_1 route, but still a second native inference runtime | Rejected at one-thread client throughput preflight: 0.820 speech windows/second, only 41.0% of the two windows/second required by the 500-ms hop; no accuracy or holdout work was run |
| official `whisper.cpp` Whisper base Q5_1 | MIT release with a 59,707,625-byte Q5_1 model and a C API that exposes all language probabilities | Full probabilities could implement the explicit enabled-language set, so this was materially different from merely requantizing the global-top proxy | Rejected at one-thread client throughput preflight: 314 windows took 770.1 seconds, only 20.4% of the throughput required by the 500-ms hop; the incomplete sequential prefix supports no accuracy claim |
| CrispASR ECAPA-LID-107 GGUF | Native C++/ggml clip-level classifier covering 107 labels | Avoids Python, but the evaluated CPU implementation was slower, less accurate than the ONNX ECAPA comparator on whole clips, and committed excessive private memory; the minimal target also carried a large native source surface | Rejected; do not add CrispASR or its ECAPA conversion to the desktop |
| SpeechFlow LID13 | Apache-2.0, approximately 1.05 million parameters, 13 named languages plus `other`, and a 5,428,476-byte release | Excellent footprint and CPU latency, but the released global classifier is strongly asymmetric on Yap's English/Spanish client-shaped development data; enabled-pair calibration did not generalize to natural switching | Rejected before qualification; do not spend an independent promotion holdout or add TensorFlow/native conversion |
| FireRedLID | Apache-2.0 release covering more than 100 languages and 20 Chinese dialects, with publisher-reported 97.18% FLEURS 82-language utterance accuracy | Broad coverage is relevant, but the immutable published checkpoint payload is 3,550,103,418 bytes and no independently documented small client artifact or runtime footprint exists | Rejected at client payload preflight; weights were not downloaded and archive size is not represented as runtime memory |
| NVIDIA LangID AmberNet | Dedicated 107-language spoken classifier with a 116,049,920-byte `.nemo` release; the publisher reports 5.22% error only on its 1,609-utterance/33-language verified VoxLingua107 evaluation set | Exact native preprocessing plus a 29,613,392-byte static QDQ INT8 graph was fast and strong on clean development clips, but this utterance classifier did not generalize to Yap's original natural/noisy switch boundary. A later frozen 58-clip holdout produced 54 correct alternate decisions, one abstention, three wrong alternates, and zero false alternates when the primary was correct under the three-observation/`0.40`-margin policy. | Failed the original zero-false transition gate, then explicitly accepted by the product owner as a bounded route with visible primary fallback. The holdout was consumed once after threshold selection and cannot be tuned against. Exact native runtime and local-import lifecycle are implemented; the artifact is not bundled or network-downloaded, and NGC redistribution obligations remain open. |
| ESPnet MMS-1B plus ECAPA | CC-BY-4.0, 107-language release with publisher-reported 95.8% FLEURS accuracy | Relevant server/research accuracy comparator, but its selected checkpoint is 3,887,806,641 bytes before runtime overhead | Rejected at resident-client payload preflight |
| SenseVoiceSmall | MIT, low-latency released checkpoint with ASR and LID | The broader research describes 50-plus languages, but the released checkpoint supports only Mandarin, Cantonese, English, Japanese, and Korean | Insufficient released language coverage for Yap's global local route |
| 3D-Speaker CAM++ LID | Apache-2.0 released acoustic classifier | The released LID model covers Mandarin and English | Insufficient released language coverage; training recipes are not a released global checkpoint |
| Gladia realtime multilingual ASR router | MIT reference implementation combining Silero VAD, SpeechBrain VoxLingua107, progressive LID windows, per-language Zipformer streams, bounded audio retention, and rollback/re-inference | Useful orchestration comparator, but it uses the already-rejected resident SpeechBrain family, preloads separate ASR models, covers only 11 ASR languages, has no published release, and does not publish reproducible benchmark scripts or a frozen evaluation manifest | Do not adopt as a runtime or detector; retain only the state-machine, stale-result, enabled-set, and evaluation lessons described below |
| Deprecated Silero language classifier | Historical compact spoken-language classifier | Its upstream language-classification path is deprecated and its licensing tier is not suitable evidence for client redistribution | Rejected at maintenance/license preflight |
| fastText or CLD3 text LID | Very small text classifiers with broad language labels | Cannot select an acoustic language before ASR; a wrong-language transcript corrupts their input | Review hint only, never acoustic-routing authority |

## Local footprint decision

The smallest native acoustic candidate that reused Yap's existing
`sherpa-onnx` runtime was measured rather than assumed. The public Whisper tiny
LID export was frozen at revision
`65176e2deb88badc814a94058666cadccc29b61c`:

- `tiny-encoder.int8.onnx`: 12,937,772 bytes, SHA-256
  `d24fb083ae3b1041fc24e97971d60e280c9342201fbb67b0ab428a8b4a51a434`;
- `tiny-decoder.int8.onnx`: 89,855,401 bytes, SHA-256
  `d2fece8dd42771f1df975c6c0445770d0c292bf7547c2cae04a6c0cc57540925`;
  and
- combined model size: 102,793,173 bytes, approximately 98.0 MiB.

In one Windows process with the installed Nemotron fallback already resident,
loading this classifier added approximately 108.4 MiB working set and 108.9 MiB
private bytes immediately. After two public English/Japanese probes, the
observed increase over the ASR-only baseline was approximately 191.5 MiB working
set and 258.2 MiB private bytes. Load took 569 ms; the 7.152-second English and
7.200-second Japanese probes returned `en` and `ja` in 345 ms and 379 ms. Two
correct clips establish API viability only, not accuracy.

A later bounded comparator used the exact production two-second window and
500-ms hop over 84 hash-verified FLEURS clips spanning 28 language families.
Whisper tiny produced only 56/84 correct case pluralities (66.7%) and
767/1,539 correct windows (49.8%); all 84 clips contained at least one
speech-qualified window. The measured repeat took 154 ms mean, 186 ms p95,
and 193 ms p99 per evaluated window, with 0.077 RTF relative to the overlapping
window audio. The standalone debug test process peaked at approximately 242
MiB working set and 281 MiB private bytes. Those totals are not an incremental
measurement beside Nemotron. CPU time approximately equaled elapsed time in the
accelerated batch probe, demonstrating one-core saturation while queued work
was continuously available. Windows whole-package power was indistinguishable
from the noisy pre-run host baseline and exposed no live thermal-zone instance,
so this run supplies neither calibrated process energy nor thermal evidence.
Raw output remains outside Git under the private `%LOCALAPPDATA%\\YapEval`
evidence root.

A focused private-path diagnostic then drove the same pinned Whisper/Silero
component through Yap's real 2-second-window, 500-ms-hop routing pipeline using
a constructed six-second English plus six-second Japanese input. The accepted
`en-US` to `ja-JP` boundary was sample 100,000 versus the constructed boundary
at sample 96,000, or 250 ms absolute error, and the routing actions covered all
192,000 source samples exactly once. Its first run found and motivated a real
overlap-retention fix; a model-free regression now protects that case. This is
useful implementation evidence but remains a concatenated monolingual fixture,
not natural within-utterance code-switch promotion evidence.

That footprint is too large to call negligible, and the representative
production-window accuracy is too low for broad automatic switching. Whisper
tiny remains the measured native comparator baseline but is rejected as the
broad production route. Phase 6 must compare a better licensed native candidate
or define a narrowly advertised allowlist that passes the same accuracy,
switch-boundary, latency, incremental-memory, CPU/energy, packaging, restart,
and teardown gates. The dictation model must remain the dominant local resident
model.

### Whisper-tiny narrow English/Spanish route — rejected

The same immutable Whisper-tiny INT8 and Silero artifacts were subsequently
evaluated as a deliberately narrow `en-US`/`es-US` automatic route under the
frozen primary-biased initial selector and sustained-switch policy. This was a
single disjoint qualification run, not threshold-development data. It retained
the configured primary with zero false routes across 60 monolingual cases and
correctly selected the opposite primary on 56/60 cases. It produced the correct
second language on 54/60 constructed switches, no wrong-language transitions,
three boundaries outside tolerance, a 2,250 ms boundary p95, and no duplicated
or dropped source audio.

The natural switch gate still failed: the candidate emitted three of five
expected language-order segments and matched only two boundaries, below the
frozen minimums of four segments and three boundaries. Its matched-boundary p95
was 1,175 ms, with no unrelated routes or source-audio loss. Thirteen frozen
gates passed and two failed, so the directed `en-US` to `es-US` and `es-US` to
`en-US` routes are not promoted. The qualification is not reused for tuning or
for a replacement candidate; raw cases, audio, logs, and host paths remain
private and outside Git.

### Released Whisper base variants — rejected

A development-only behavior proxy used the released
`csukuangfj/sherpa-onnx-whisper-base` conversion at immutable revision
`bb53ee204431c90d314c1cc08d28d23e5b7927cc`. Its 29,120,534-byte INT8
encoder and 130,672,026-byte INT8 decoder total 159,792,560 bytes. The same
Silero speech mask, two-second window, 500-ms hop, one CPU thread, and 84-case
public FLEURS comparator produced 64/84 correct case pluralities (76.2%) and
886/1,539 correct windows (57.6%). Mean/p95/p99 observation latency was
144/172/179 ms with 0.072 evaluated-window RTF. It improved over tiny but still
failed all three Ukrainian, Norwegian Bokmål, and Estonian cases and remained
systematically unsafe for broad global-top switching. The proxy's conversion
lineage is also not sufficient for promotion.

The official MIT `ggerganov/whisper.cpp` Q5_1 release warranted a separate
resource preflight because `whisper.cpp` exposes every language probability,
which could support Yap's primary-plus-explicit-alternates policy rather than
only a global top label. The preflight pinned runtime tag `v1.9.1` at commit
`f049fff95a089aa9969deb009cdd4892b3e74916`, the 7,982,101-byte Windows x64
release asset at SHA-256
`7d8be46ecd31828e1eb7a2ecdd0d6b314feafd82163038ab6092594b0a063539`,
and `ggml-base-q5_1.bin` at model revision
`5359861c739e955e79d9a303bcbc70fb988958b1e`, 59,707,625 bytes, SHA-256
`422f1ae452ade6f30a004d7e5c6a43195e4433bc370bf23fac9cc591f01a8898`.
Yap retained canonical `nb` and mapped only the model's legacy internal `no`
token at the adapter boundary.

The one-thread CPU run was terminated after 314/1,539 windows because those
windows took 770.1 seconds: 2.453 seconds per observation, 0.408 windows per
second, 1.226 RTF relative to the evaluated two-second windows, and only 20.4%
of the two-windows-per-second throughput required by the production 500-ms
hop. At termination the evaluation process had consumed 769.62 CPU seconds and
held approximately 316.6 MB working set and 817.8 MB private memory. Those
process values include Python, the evaluation bridge, Silero, and `whisper.cpp`;
they are not claimed as incremental native-product memory. The prefix covered
only the first 314 sequential windows, so it is deliberately retained as
private, nonrepresentative latency evidence and is not scored for accuracy.
The failed throughput gate makes threshold tuning, a full accuracy pass, and a
second product-native inference runtime unjustified.

The smaller official Whisper-tiny Q5_1 artifact was then evaluated as a distinct
released candidate because its full language-probability API could restrict
decisions to the user's enabled set, unlike the Sherpa global-top-label adapter.
The preflight pinned `ggml-tiny-q5_1.bin` at the same immutable model revision:
32,152,673 bytes, SHA-256
`818710568da3ca15689e31a743197b520007872ff9576237bda97bd1b469c3d7`.
It reused the already-verified `whisper.cpp` v1.9.1 CPU runtime and performed no
accuracy or qualification inference.

Across 32 speech-qualified production-shaped two-second windows, one thread
averaged 1,219 ms per observation with 1,241 ms p95 and delivered only 0.820
windows per second. That is 41.0% of the two-windows-per-second budget required
by the 500-ms hop. Model load took 108 ms; the evaluation process peaked near
241 MB working set, which includes Python, Silero, the bridge, and `whisper.cpp`
and is not incremental product memory. The throughput failure rejects the
candidate before accuracy, threshold, natural-switch, packaging, or holdout
work. Raising the resident thread count would change the frozen CPU and ASR-
interference budget rather than rescue this candidate silently. Aggregate
evidence is recorded here; raw runtime output remains private and outside Git.

### CrispASR ECAPA native challenger — rejected

A separate disposable native probe evaluated CrispASR commit
`259e6ad67bd3b324ca6a313cb02e481e683cfa04` with its pinned ggml submodule and
the `cstr/ecapa-lid-107-GGUF` model at revision
`95fb0613bf78c6e48305fccd9ce023ac15f0b5a6`. The 42,838,944-byte model had
SHA-256 `59db30ba67cec2f36304f794420779c181124332246f75fc66c349f184110340`.
No upstream source or model bytes were copied into Yap.

On the same 84 hash-verified FLEURS clips, arbitrary first two-second windows
were correct for only 33/84 cases (39.3%). That window shape includes leading
silence and is therefore descriptive rather than directly interchangeable with
the production sliding-window score. Whole clips were correct for 71/84 exact
labels (84.5%), or 74/84 (88.1%) after only the standards-valid `no` to `nb`
alias; the previously measured ECAPA ONNX comparator reached 77/84 (91.7%).
Mean/p95/p99 latency for the first two-second windows was 250/280/298 ms, while
whole-clip inference averaged 1,261 ms with 1,836 ms p95.

A 100-repeat two-second process probe peaked near 69 MiB working set and 848 MiB
private bytes. The smallest isolated native build still compiled 34 C/C++
translation units totaling about 56,304 physical lines with ggml. CrispASR's
source also documents this ECAPA path as CPU-only for correctness, with its
pooling head remaining a hotspot. Those accuracy, latency, memory, and
maintainability costs defeat the intended small resident-detector role. Raw
runtime output and disposable source/build material remain outside Git under
the private evaluation boundary.

### ECAPA ONNX behavior and native-runtime constraint

An evaluation-only end-to-end ONNX conversion of the same SpeechBrain model
showed the strongest client-shaped behavior so far: 77/84 case pluralities
(91.7%) and 1,101/1,539 correct two-second windows (71.5%), with 62 ms mean,
76 ms p95, and 87 ms p99 inference using four ONNX Runtime CPU threads. Model
load took 141 ms. Relative to the already-loaded Python probe process, the
100-repeat run added about 145 MiB working set and 154 MiB private bytes at
peak. This is comparator evidence, not an artifact or runtime promotion.

The evaluated conversion is in
`christopherthompson81/voxlingua107-lid-onnx` commit
`e02e1da805ae49635fe1aa7913c3f1e7f5f5fde6`, model SHA-256
`e2c3c3da39b99e3f9196d15fceef6a65f702320038bbc08813a4f21280255ce8`.
Its apparent exporter source aligns by timestamp with Vernacula commit
`2b3d42781338a4af619fa55048e4711f4885b508`, but that exporter leaves its
dependencies and upstream model revision unpinned. At that revision the
repository's license declaration covers `Vernacula.Base` and `Vernacula.CLI`,
not the root Python export scripts. Yap therefore cannot copy those scripts or
treat the published conversion as reproducibly authorized provenance.

A disposable pure-Rust runtime probe also rejected the hoped-for easy tract
path. The dynamic graph failed tract parsing on symbolic dimension arithmetic.
After specializing a private copy to Yap's exact 32,000-sample live window and
performing only standard ONNX Runtime basic graph optimization, `ort` 2.0.0-rc.12
with `ort-tract` 0.3.0/tract 0.22.3 did reproduce the ONNX Runtime class and
score, but 20 warm runs averaged 459 ms with 473 ms p95. The process peaked near
255 MiB working set and 250 MiB private bytes; the static executable was about
15.8 MiB before the 81.9 MiB optimized model. This is materially slower than
ONNX Runtime and supplies no resident-memory advantage. The specialized graph,
probe source/binary, and raw results remain private and are not Yap artifacts.

The remaining defensible route is narrower: obtain or independently produce a
revision-pinned, explicitly licensed export from the official SpeechBrain
checkpoint, then measure a pinned ONNX Runtime Rust boundary against the same
frozen switch/resource gate. Until both halves pass, ECAPA remains a behavioral
comparator and no new desktop dependency is justified.

### Official-checkpoint export and routing-policy correction

That narrower experiment was completed on 2026-07-18 without copying the
third-party exporter. An independently authored exporter pinned the official
SpeechBrain checkpoint at revision
`0253049ae131d6a4be1c4f0d8b0ff483a0f8c8e9` and produced a deterministic
fixed-two-second ONNX graph with SHA-256
`16f1dd6c087759ad6c3ac61a609e217604fd20aa4a550744fb4a6b870307797d`.
A native Rust probe used `ort` 2.0.0-rc.12 against the official ONNX Runtime
1.27.1 Windows library. The standalone detector loaded in about 238 ms, warm
inference averaged about 80 ms, and the process peaked near 167 MiB working
set. A same-process Nemotron plus ONNX Runtime probe peaked near 952 MiB. Those
figures make the candidate session-resident rather than negligible.

A development-only post-training quantization probe then tested whether the
official two-second graph could meet the weaker-client footprint target without
changing behavior. The FP32 graph produced 989/990 correct enabled English/
Spanish decisions on the clean development windows, but only 49/58 on exact
natural pure-language windows. Two calibrated QDQ INT8 graphs shrank from
86,010,473 bytes to approximately 22.8 MB and reduced mean inference from
61.8 ms to 39.4/42.7 ms on the development host, but collapsed to 365/990 and
399/990 correct clean enabled-pair decisions. Neither retained a non-empty
zero-wrong natural threshold. Because Q8 already fails behavior, Yap will not
blindly derive Q4 from this graph. The quantized artifacts remain private
diagnostics and are rejected.

The first corpus-independent routing gate rejected the original one-policy
design. Across 84 disjoint FLEURS cases, 66 exact constructed joins, and 90
ASCEND utterances, it detected 60/66 exact joins with zero wrong join routes,
but falsely switched two monolingual FLEURS cases and routed only 8/30 natural
Mandarin utterances away from an English primary. Most missed Mandarin clips
were shorter than the four-observation sustained-switch decision. This is an
architecture error: fast initial utterance selection and conservative
mid-utterance switching cannot share one threshold policy.

The rejected corpus is now development data. A pair-restricted two-stage policy
was frozen from it before acquiring a second disjoint corpus:

- initial routing considers only the confirmed primary plus explicitly enabled
  alternates and requires one voiced two-second observation with margin `0.30`;
- sustained switching uses the same explicit language set, four observations,
  and margin `0.50`; and
- any unenabled or unsupported classifier label is abstention, never an
  implicit route.

On development data that policy produced 79/81 correct FLEURS initial routes,
26/30 natural Mandarin initial routes, 54/66 exact sustained switches, zero
wrong routes, and zero monolingual false switches across every tested
current/alternate pairing. Those numbers selected the second candidate; they
did not promote it.

The second disjoint behavior gate also rejected the candidate. It produced
81/81 correct non-English FLEURS initial routes, 28/30 natural Mandarin initial
routes, 58/66 exact constructed switches, zero wrong routes, and zero sustained
monolingual false switches. It nevertheless emitted four false Mandarin routes
across 30 natural English ASCEND clips, violating the frozen zero-false-route
criterion. Two were genuine early false selections; two were later transient
observations that a latched startup selector must never apply.

Both rejected corpora are now development data. A bounded, primary-biased,
latched selector search found no policy that simultaneously retained at least
90% FLEURS alternate coverage, at least 80% natural Mandarin coverage, and zero
primary-language false routes. The strongest zero-false candidate reached only
137/162 FLEURS alternate cases (84.6%), 53/60 natural Mandarin cases (88.3%),
and a four-second p95 selection time. The global-top-label adapter is therefore
not promotable. A subsequent development-only enabled-language posterior search
evaluated 26,460 bounded policies and found no candidate that met the complete
threshold set. Its best thin pair-matrix result is diagnostic rather than
certification: some ordered pairs had only three examples per direction, so it
cannot justify consuming another holdout. A materially different released
checkpoint may reuse the development harness, but it must first exceed 77/84
public comparator cases and produce at least one zero-primary-false policy with
90% FLEURS alternate coverage, 80% natural Mandarin coverage, and no worse than
the existing four-second p95 selection boundary. Failure stops the candidate
before ONNX export, product packaging, or a third disjoint holdout. Any candidate
that passes still requires that holdout plus native lifecycle, artifact-
distribution, and resource gates.

### TalTech EPACA released-checkpoint preflight — rejected

The next bounded challenger is the first-party
`TalTechNLP/voxlingua107-epaca-tdnn` Apache-2.0 release at immutable revision
`1b1adeee7e07b911799d204ab06f2db5b40a1322`. It covers the same 107-language
family but is not a duplicate of the rejected SpeechBrain checkpoint: its
embedding weights differ and its direct cosine classifier head is materially
smaller and structurally different from SpeechBrain's extra fully connected
classifier. The publisher reports 7% error on its 33-language volunteer-
validated development set and explicitly notes weaker small-language, female,
foreign-accent, child, and speech-disorder behavior. The training recipe is not
published with the release, so provenance risk remains part of the decision.

Only already-development public fixtures were used. The exact 84-case,
1,539-window public comparator produced 73 correct case pluralities (86.9%) and
1,098 correct two-second windows (71.3%). The rejected official SpeechBrain
checkpoint reached 77/84 cases and 1,101/1,539 windows on the same shape. The
TalTech checkpoint therefore failed the predeclared behavior stop rule despite
an adequate direct PyTorch CPU preflight of 57.9 ms mean, 62.7 ms p95, and
68.8 ms p99 with four threads. Model load took 134 ms, and the embedding plus
classifier checkpoints total 84,590,662 bytes.

The candidate is rejected before an enabled-language policy sweep, ONNX export,
product packaging, native-runtime work, or independent holdout consumption.
Its 59/60 result on an accidentally selected English/Spanish development slice
is retained privately as smoke evidence only and is not decision evidence.
Publisher accuracy remains context, not Yap promotion evidence.

### Bounded released-candidate screen

The follow-on released-checkpoint screen did not identify another artifact that
clears Yap's combined global-coverage, commercial-license, provenance, and
resident-client payload preflights:

- `TalTechNLP/voxlingua107-epaca-tdnn-ce` is byte-for-byte the already rejected
  official SpeechBrain embedding and classifier. `AkshaySg/langid` is
  byte-for-byte the rejected TalTech EPACA candidate above. Neither duplicate
  warrants another inference run or holdout.
- `Pablex/whisper_tiny_fleurs` is a small Apache-2.0 checkpoint, but its released
  classifier covers only Spanish, English, Portuguese, Basque, Catalan, and
  Galician. It cannot satisfy Yap's global automatic-routing requirement.
- `onecxi/vakgyata-tiny` is a 12-language Indian specialist. The broader
  `onecxi/open-vakgyata` remains regional and uses a noncommercial license.
- `UBC-NLP/Simba-SLID-49` is a 49-African-language regional specialist with an
  approximately 378 MB checkpoint. It is useful future regional research, not
  one global resident route.
- `TalTechNLP/voxlingua107-xls-r-300m-wav2vec` has an approximately 1.26 GB
  released checkpoint. ESPnet GeoLID and MMS-ECAPA variants are approximately
  3.9 GB. Their payloads fail the local resident-client preflight before
  accuracy or lifecycle evaluation.
- The released 45-language Whisper-base, DistilHuBERT, and SpeechBrain
  CommonLanguage classifiers either have insufficient coverage or already
  publisher-reported behavior below the current broad candidates. They remain
  lower-priority comparators rather than promotion candidates.
- `parakeet-rs` 0.3.6 is a released MIT/Apache-2.0 Rust runtime that can execute
  the same multilingual Nemotron model. Its adapter identifies language-tag
  token IDs internally, but its public streaming, accumulated, and offline
  transcript methods deliberately filter those IDs and expose no detected-
  language result. Using it for Yap's route would therefore require an
  unreleased fork or a second decoder API, a separately sourced community ONNX
  export, and replacement of the already checked local frontend. It fails API
  and provenance preflight before model acquisition or behavior evaluation.

This is a bounded screen of plausible released candidates under the current
requirements, not a claim that no future model can work. It closes duplicate
and obviously ineligible acquisition work. Automatic promotion remains blocked
until a materially different candidate or an explicit product tradeoff exists.

### NVIDIA AmberNet candidate and license boundary

NVIDIA's public `langid_ambernet` catalog entry is a relevant challenger: exact
version `1.12.0` is a dedicated 107-language spoken-LID `.nemo` checkpoint,
116,049,920 bytes, with publisher-reported 94.78% accuracy on the verified
VoxLingua107 evaluation set. The catalog is available to guests but states that
downloading accepts the NGC terms. NVIDIA's April 15, 2026 AI Product Terms
classify public NGC software as Community Products and contain customer-product
service and distribution grants subject to the agreement, notice/reporting and
other obligations. The May 7, 2026 Software License Agreement says the accepting
party must have authority to bind the represented entity. This corrects the
earlier overstatement that AmberNet simply lacked redistribution permission; it
does not constitute legal approval. The user subsequently authorized private
evaluation acquisition, which allowed the checkpoint trial recorded below. No
organizational product legal/obligation review is recorded for Yap, so that
evaluation authorization must not be treated as approval to redistribute or
ship the checkpoint. Publisher accuracy is not substitute evidence.

A July 20 disposable GB10 preflight, run before that evaluation authorization,
narrowed the reference-tooling question without acquiring the model. The exact
approved NVIDIA PyTorch 26.06 base provided
Python 3.12.3, NVIDIA Torch `2.13.0a0+8145d630e8.nv26.06`, CUDA 13.3, and ONNX
1.21, but not NeMo or ONNX Runtime. In a labeled temporary container, a current
`nemo_toolkit` 2.7.3 overlay successfully imported
`EncDecSpeakerLabelModel` and listed NVIDIA's immutable AmberNet 1.12.0 URL.
That overlay is not suitable for the production ASR worker: its resolved
Transformers 4.57.6 would replace the worker's checked Transformers 5.13.1, and
its protobuf 5.29.6 requirement conflicts with the base image's
`grpcio-tools` requirement. Any authorized trial therefore needs a separately
hash-locked disposable export image with only the dependencies required for
restore, golden-tensor capture, and export. That preflight did not restore or
infer the checkpoint and its container was removed afterward; the later
authorized acquisition used the separate disposable path described below.

#### Intended AmberNet to Nemotron role and bounded trial

AmberNet is not a Nemotron submodel: the released checkpoint predates Nemotron
3.5, and NVIDIA documents it as a compact acoustic-LID model that can serve as
the first step for ASR generally. That is nevertheless the right companion
contract to evaluate for Yap. Silero first excludes non-speech; overlapping
bounded AmberNet observations then supply acoustic-language evidence to the
already implemented selector and hysteresis policy; an accepted base language
is mapped to one of the user's explicitly enabled BCP 47 locales; and the same
local Nemotron ASR is started or reset with that explicit language prompt.
Nemotron's own automatic terminal tag remains separate server or verification
evidence, not the desktop switching mechanism.

AmberNet identifies languages, not regional locale preferences. For languages
with multiple enabled Nemotron locales, such as English, Spanish, French, or
Portuguese, Yap must retain the user's confirmed regional locale instead of
inventing one from AmberNet's base-language result. A label outside the enabled
Nemotron set, ambiguous evidence, silence, or a failed inference remains
`Unknown` or visibly falls back to the confirmed primary according to the
existing policy; a closed-set top label is never treated as calibrated
confidence.

The research results also bound what may be inferred before Yap runs the
checkpoint. The reported 29-million-parameter model was trained on non-
overlapping three-second clips represented as 80-bin log-mel spectrograms with
a 25-ms window and 10-ms stride. Its published VoxLingua107 error was 7.5% for
clips shorter than five seconds versus 5.2% for five-to-twenty-second clips.
The same VoxLingua107-trained model reached only 77.9% macro accuracy over the
82 FLEURS languages it had seen; the higher 88.2% and 93.8% FLEURS results came
after separate fine-tuning and do not describe the released 107-label
checkpoint. This makes a three-second observation the evidence-centered
starting point, while one-, two-, and five-second windows remain measured
challengers rather than assumed equivalents. Related-language confusions called
out by the authors, including Urdu/Hindi, Norwegian/Nynorsk, and
Spanish/Galician, must remain in the false-route gate.

After authorized NGC acceptance and product-obligation review are recorded, the
trial is deliberately staged and stops at the first failed boundary:

1. Hash-lock the original `.nemo` artifact, labels, feature configuration, and
   reference NeMo outputs on the existing private fixtures.
2. Export a reproducible FP32 ONNX graph and prove raw-waveform-to-all-logits
   parity. NeMo 1.12's `EncDecSpeakerLabelModel` export surface accepts processed
   features and deliberately exports the encoder/decoder without the audio
   preprocessor, returning both logits and embeddings. A bare `model.export()`
   is therefore not a deployable Yap artifact. The trial must either export a
   verified wrapper containing the checkpoint's exact feature preprocessor or
   pair the classifier graph with a native feature implementation whose
   intermediate tensors match NeMo golden tensors. NeMo, Python, and Torch are
   reference/export dependencies only; the shipped desktop path must remain
   native and Rust-owned. The historical NeMo 1.12 release advertised Python
   3.8/3.9, so the trial first restores and exports in Yap's pinned Python 3.12
   NVIDIA environment and stops if compatibility cannot be proved rather than
   introducing an old production runtime. Evaluate Q8 and, only if useful, Q4
   without going below the project's four-bit floor.
3. Run the existing development comparator at one-, two-, three-, and five-
   second evidence durations, then the frozen natural/noisy/muttered and
   constructed/real switch-point gates. Preserve the full 107-way score vector.
   A candidate must map to an explicitly enabled base language and clear frozen
   absolute-evidence and strongest-global-competitor margins; scores for disabled
   languages must not be discarded and the enabled set must not be renormalized
   into a forced answer. The reusable Rust boundary now validates labels and the
   locale map once at load, then applies the same validated speech, score, and
   margin gates to initial selection and sustained switching without allocating
   a label set on every observation.
4. Measure load time, warm p50/p95/p99 CPU latency, incremental resident and
   private memory beside Nemotron, sustained CPU/package power, thermal behavior,
   ASR interference, restart, cancellation, and teardown on the representative
   i5-class client boundary.

The checkpoint is promoted only if native parity, locale mapping, false-route
safety, natural within-utterance boundary accuracy, packaging/redistribution,
and the client resource gate all pass. The publisher's whole-utterance score and
the model's approximately 116 MB download make AmberNet a serious next
candidate, not a predetermined selection. Weight dtypes, uncompressed tensors,
and resident memory are measured after authorized acquisition rather than
inferred from the archive size.

### SpeechFlow LID13 lightweight challenger — rejected before qualification

The Apache-2.0 `SpeechFlow/spoken_language_identification` release was inspected
at immutable model revision
`d800dffd5066a63295797c1e52ba3fcf0d9dd330` and source revision
`9366e9019426f882d470eda7b3ccc0076f29524c`. Its SavedModel files total
5,428,476 bytes and contain 1,047,440 parameters. The released vocabulary is
Chinese, English, French, German, Indonesian, Italian, Japanese, Korean,
Portuguese, Russian, Spanish, Turkish, Vietnamese, plus `other`. An independently
implemented feature pipeline reproduced the release's top probability within
`1.25e-6`; no SpeechFlow code or model bytes were added to Yap.

On 1,395 already-development two-second windows with one CPU thread, inference
averaged 22.021 ms with 24.952 ms p95 and 25.974 ms p99. Speed and size therefore
passed preflight. Behavior did not. On 990 FLEURS development windows, the best
strict abstaining threshold retained 354 correct and 11 wrong decisions while
abstaining on 625: 96.99% precision at only 36.87% coverage. On 56 exact natural
English/Spanish windows, the corresponding strict search retained eight correct
and one wrong decision while abstaining on 47. The raw classifier was also
materially stronger for Spanish than English.

Longer windows improved raw enabled-pair accuracy from 789/990 at two seconds to
799/913 at three seconds and 732/801 at four seconds, but no bounded startup
policy met the frozen English safety and alternate-coverage requirements. A
grouped five-fold, regularized linear calibration feasibility test over all 14
logits reached 768/801 correct FLEURS four-second decisions. Zero wrong FLEURS
decisions required abstaining on 320/801 windows; on the small exact natural
four-second slice it produced nine correct and two wrong decisions, and zero
wrong decisions retained only 2/11 windows. This is development evidence, not a
promotion estimate, but it is sufficient to reject the candidate before
acquiring or consuming another independent holdout. Raw outputs remain outside
Git under the private evaluation boundary.

### FireRedLID payload preflight — rejected for the resident client role

The Apache-2.0 `FireRedTeam/FireRedLID` model was inspected at immutable revision
`1bb4d285c8456429385d9c0810300df4297bc11b`; its official source was inspected at
commit `4e7d9aaf4482a47cec1724807026b9b151926eb5`. The publisher reports support for
more than 100 languages and 20 Chinese dialects and 97.18% utterance-level
accuracy over 82 FLEURS languages. Those are publisher claims, not Yap evidence.

The published `model.pth.tar` object is 3,550,103,418 bytes with LFS SHA-256
`7dee2a280e9b11d5241a0e3d4fa60ee1520a036a2e8385f17960371cfea10093`.
That archive may include state not needed by an optimized inference artifact, so
its byte size is not presented as parameter count or resident memory. It is
nevertheless far outside the negligible client payload preflight, and the
release provides no independently documented small native client artifact.
Yap did not download the weights or spend evaluation data on it. Server-side
support in another inference framework does not make this a client CPU route.

### NVIDIA AmberNet 1.12.0 native evaluation — failed the original gate; accepted as a bounded product tradeoff

The user explicitly authorized evaluation acquisition of the public AmberNet
1.12.0 release. The official 116,049,920-byte checkpoint has SHA-256
`2f92d645b9ea5824d7663584fecb9ecc52557d0d700e24266747f38a61ba1681`,
28,926,299 parameters, and 107 labels. NVIDIA reports 5.22% error on the
1,609-utterance verified VoxLingua107 evaluation set covering 33 languages.
That publisher result is not a Yap result and is not generalized to all 107
training labels or to code-switch boundaries.

The reference evaluation restored the checkpoint under a disposable Python
3.12/NeMo 2.7.3 overlay on the pinned NVIDIA PyTorch 26.06 image. Yap then
reproduced the exact 16 kHz NeMo feature contract in an independent Rust probe,
verified FP32 classifier parity, and produced a static QDQ INT8 classifier:

- 29,613,392 bytes, SHA-256
  `ef1006c7637803540e12ab01021e442382857689cbe0b1909d3128acf66a0a3e`;
- 33.90 ms median and 38.83 ms p95 end-to-end for a three-second window on the
  development Windows host; this is not yet i5-class interference evidence;
- 323/340 whole-clip decisions on the out-of-training-domain FLEURS development
  comparator, including 276/280 supported cases; and
- an abstaining development policy with 265/280 correct supported routes, zero
  wrong routes, 15 abstentions, at least 80% coverage for every supported
  language, and all 60 related/unsupported controls held.

Those strong clean-clip results did not survive the required temporal boundary:

- constructed clean, one-second-silence, and one-second-overlap switches reached
  24/24, 12/12, and 12/12 respectively, but deterministic 15 dB SNR switches
  reached only 7/12;
- the first natural English/Spanish development recording produced zero of four
  expected transitions under the native route; the original FP32 NeMo model also
  produced zero transitions across one-, two-, three-, and five-second windows,
  ruling out export drift and window duration as the cause; and
- on a second natural recording, a full-vector enabled-pair development search
  found zero policy satisfying clean-pair accuracy, zero unrelated-language
  routes, natural order, and boundary tolerance together. The best natural
  candidate caught two of three transitions, only one within tolerance, had
  33.14-second p95 boundary error, and falsely routed two unrelated-language
  clips.

Those results rejected AmberNet against the original zero-false natural/noisy
transition gate. They remain negative evidence and are not relabeled as a pass.
The product owner subsequently chose to stop the open-ended model search and
accepted the exact AmberNet 1.12.0 QDQ INT8 artifact as a pragmatic bounded
resident component. The implementation requires three consistent observations,
a `0.40` softmax-probability margin, explicit user-selected regional locales,
and fail-visible retention of the primary locale on ambiguity or failure.

Threshold selection used only a 29-clip calibration partition. A distinct
58-clip FLEURS test-partition holdout was then inferred once. The accepted INT8
policy produced 54 correct alternate decisions, one abstention, three wrong
alternate decisions, and zero false alternate decisions when the configured
primary was correct. Mean-logit whole-clip classification was 57/58; the one
error was Croatian classified as Bosnian. First-window accuracy was only
47/58, reinforcing the three-observation rule rather than supporting immediate
one-window switching. This holdout is now consumed and may not be used to tune
the policy.

Yap now contains the exact native frontend, one-thread static-ORT runtime,
107-label order and alias boundary, and verified local-import lifecycle. The
29,613,392-byte artifact is not bundled and the product has no network download
path for it. Evaluation authorization still does not establish permission to
redistribute the checkpoint; NGC product terms and packaging obligations remain
an explicit review boundary.

### Accepted detector boundary and remaining qualification

The required local engine, explicit locale-set ownership, startup and sustained
three-observation policies, exact-once handoff, source-time span contract, and
accepted AmberNet detector now exist under focused tests. Automatic routing is
bounded to the intersection of AmberNet base-language labels and user-selected
Nemotron regional locales. Acoustic evidence never invents a region, and
ambiguity, silence, unsupported labels, corrupt artifacts, or detector failure
retain the explicit primary locale visibly.

The current selection route is released-checkpoint-only. Training, fine-tuning,
or distilling a new classifier may remain a later research option, but it is not
an implicit Phase 6 escape hatch and no training dataset or custom derivative is
being selected here.

Local quantization has a four-bit precision floor: no Q3/Q2 derivative may be
promoted. Q4 is not mandatory when Q8 or a higher-precision artifact is required
for accuracy and still meets the measured CPU/memory budget. The current local
Nemotron ASR remains its tested INT8 artifact; its bit width is not silently
changed as part of the LID search.

A focused release-mode development-host profile then ran the exact resident
Nemotron plus AmberNet/Silero client stack against 37.175 seconds of licensed
English fixture audio. On a Windows Intel Core i7-13850HX host, Nemotron alone
completed in 5.551 seconds (`0.149` RTF); the combined routing path completed in
12.959 seconds (`0.349` RTF), routed all 594,800 source samples exactly once, and
remained faster than real time. Loading the language pipeline added 38,563,840
working-set bytes (about 36.8 MiB) and 52,621,312 private bytes (about 50.2 MiB)
beside warm Nemotron. After pipeline teardown, the process remained 5,517,312
working-set bytes (about 5.3 MiB) and 7,831,552 private bytes (about 7.5 MiB)
above the Nemotron-only snapshot. The private aggregate JSON remains outside Git
and has SHA-256
`76dc85c9f9a375d8a04012b82be622676dadd06603415860e8d24445f2703c2d`.

That profile establishes development-host lifecycle, exact-source routing, and
under-real-time interference evidence only. It is not target-i5 qualification,
contains no language transition, and supplies no calibrated energy or thermal
evidence.

The explicit tradeoff has now been made. Phase 6 no longer requires another
model search, but it still requires representative target-i5 incremental memory,
CPU/latency, ASR-interference, sustained-session, cancellation/restart, and
natural/noisy transition evidence for the accepted route. The rejected
Whisper-tiny English/Spanish qualification may not be retuned or reused. Until
the complete checked-head gate passes, fixed-primary operation remains the
visible safe fallback whenever the optional AmberNet artifact is unavailable or
uncertain, and Phase 6 must not claim universal or zero-error switching.

Text LID does not solve this routing problem. It can cheaply flag a completed
transcript for review, but it cannot recover the intended acoustic language when
the ASR produced corrupted text under the wrong prompt.

### Gladia router architecture comparator — policy lessons only

The public `gladiaio/realtime-multilingual-asr-router` repository was inspected
at commit `4e25d6489624db46dca627a59c35ad0222c2636b`. It is an architecture
prototype rather than another released detector candidate. Its coordinator
transcribes immediately with the currently selected monolingual Zipformer,
runs SpeechBrain LID asynchronously over progressive one-, two-, three-, and
five-second windows, rejects stale results by source-sample boundary, and
replays retained source audio through a replacement ASR stream when a switch is
accepted. Its sample-count clock, bounded source-audio retention, stale-result
guard, one-switch-per-segment rule, and explicit user-enabled language set are
useful review inputs for Yap's Rust-owned state machine.

The repository is MIT licensed. This review reuses no Gladia source code or
model artifact; it records only independently implemented control-policy
lessons, so the repository is provenance for the comparison rather than a Yap
runtime dependency.

The prototype does not close Yap's detector or product gate:

- it uses the same VoxLingua107 ECAPA family that failed Yap's resident-client
  behavior/resource gates and imports Torch, TorchAudio, TorchCodec, and a
  SpeechBrain `develop` commit;
- its default three Zipformer languages require about 450 MB of model payload,
  while its complete advertised ASR set is about 1.6 GB and only 11 languages;
- it renormalizes scores over the enabled language set without an independent
  out-of-set/unknown test, so an unrelated language can receive artificial
  closed-set confidence;
- its first progressive result can bypass the configured confidence threshold,
  which is incompatible with Yap's confirmed-primary, fail-closed startup
  policy;
- its audio buffer logs gaps but concatenates the available bytes, which can
  collapse missing source time and is not acceptable for Yap's exact-source
  contract;
- each session owns a separate inference lock around a shared classifier, so it
  is not evidence for bounded concurrent server inference; and
- the repository publishes benchmark charts but no benchmark runner, frozen
  manifest, reference hashes, or checked model-backed CI. Its hosted CI excludes
  both `integration` and `slow` tests.

Its reported WER also exposes the boundary of the approach: approximately
13.2% on synthetic inter-utterance switching but 41.0% on Bangor-Miami
intra-utterance code switching. The authors explicitly attribute the gap to
mid-sentence switches outrunning VAD boundaries. These numbers are comparator
claims, not Yap promotion evidence, but they reinforce that pause-boundary
rollback is not proof of within-utterance language diarization.

Yap should therefore keep the reusable control ideas without importing the
Python server or model stack: make detector work non-blocking; score only the
confirmed primary plus explicit alternates while preserving an unknown/
abstention signal; advance progressive evidence only while uncertain; bind
every observation to a source-time generation; and revise one provisional
utterance identity rather than append duplicate text. The currently implemented
exact-once bounded holdback remains the default. Rollback/replay becomes a
candidate only if the representative continuity gate proves that holdback
cannot meet latency or quality requirements.

## Native Nemotron interface finding

Source inspection was originally frozen against `k2-fsa/sherpa-onnx` commit
`8e7ca3cdfae616420b951ce063dc53dbcf2cc572` and was rechecked against the
currently pinned released tag `v1.13.4` at commit
`142807252687d81b40d6315f23470a1512a00de3`, then against upstream `master` at
`2d8286d12c67b634e93a61473556ca5d7279e509`. The native stream accepts an exact
BCP 47 `language` option, and focused Yap tests prove that the selected locale
survives stream reset. However, both the release and current upstream Nemotron
recognizer still call `FilterLanguageTags` before constructing the public
result, and `OnlineRecognizerResult` still exposes no detected-language field.

A private, hash-pinned diagnostic then changed only the display strings for the
exact export's 39 concrete locale-token rows while preserving every token ID
and all model bytes. This prevented sherpa's tag-shaped-token filter from
recognizing the rows and proved that the public token/timestamp vectors can
carry otherwise hidden tags without a native fork. It did not close the
behavior gap. Across the three valid natural German-English-German development
recordings, complete and incrementally sampled streaming results emitted no
English tag during the labeled English spans; only German tags appeared at
utterance boundaries. The isolated English spans transcribed intelligibly, but
three emitted no initial language token. One separately discovered invalid
annotation was excluded from this conclusion. Raw audio, derivative token
table, and diagnostic reports remain outside Git.

The same-model route is therefore rejected for Phase 6 within-utterance
switching: making tags visible is an interface workaround, while the required
alternate-language evidence is absent. It would also require a model-package
derivative and transcript-token sanitation despite supplying no acceptable
span behavior.

Consequently, the local runtime can execute a fixed confirmed language prompt
but cannot truthfully expose Nemotron's automatic detected tag. Yap will not
carry a private sherpa fork merely to manufacture that field. Phase 6 instead
adds one separately pinned acoustic-LID component behind the existing
`LiveRuntime` owner; the component must pass the full resource and behavior gate
before local dynamic detection is advertised. A future released upstream API
paired with materially improved, representative per-span model behavior may
compete as a same-model candidate; merely preserving the current tags or carrying
an unreleased local patch may not.

## Qwen3-ASR server challenger

Official Qwen3-ASR source inspection was frozen at repository commit
`7c6daf77a2421100f5fb066495372c00129d39ff`. The 1.7B model is the more serious
server challenger because the publisher reports 4.90 WER over the FLEURS base
12-language grouping, 6.62 over eight additional languages, 12.60 over the
hardest additional ten, and 97.9% average LID accuracy. Those are publisher
benchmarks, not Yap promotion evidence.

The toolkit also proves useful terminology and duration contracts: offline and
streaming requests accept a context/system prompt, a language may be fixed in
that prompt, ordinary ASR accepts up to 1,200 seconds per internal chunk, inputs
under 0.5 seconds are padded, and longer files use low-energy splitting. Current
streaming is vLLM-only with two-second chunks by default, no timestamps, no
batching, one stream per call, and repeated inference over the accumulated audio.
It is therefore a server batch and multilingual-coverage challenger, not yet a
drop-in replacement for Nemotron's cache-aware low-latency live path.

Promotion requires exact GB10 transcript quality, terminology retention,
duration, cold/warm latency, p95/p99, concurrency, GPU-memory, cancellation, and
teardown evidence behind Yap's existing worker contract. Its vLLM service also
remains distinct from the planned SGLang agent/LLM plane.

## Required dynamic fixtures

A promotion benchmark must contain at least:

- every advertised out-of-box locale with multiple speakers and acoustic
  conditions;
- related-language confusions and unsupported/adaptation-ready speech;
- silence, music, noise, extremely short utterances, and missing tags;
- language changes at VAD boundaries, with exact source-time provenance;
- same-speaker intra-utterance switches with exact source-time reference spans,
  boundary error, language-span accuracy, transcript duplication/deletion, and
  false-switch assertions; and
- restart, cancellation, retry, memory, latency, and clean-teardown evidence on
  the locked GB10 runtime.

The Phase 6 decision is accepted, but only a released, licensed model and frozen
switch-point benchmark can promote the implementation. Concatenating monolingual
clips or observing two utterance tags is insufficient evidence.

## Primary sources

- [NVIDIA Nemotron 3.5 ASR Streaming 0.6B model card](https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b)
- [Qwen3-ASR 1.7B model card](https://huggingface.co/Qwen/Qwen3-ASR-1.7B)
- [Qwen3-ASR official repository](https://github.com/QwenLM/Qwen3-ASR)
- [Qwen3-ASR technical report](https://arxiv.org/abs/2601.21337)
- [Microsoft VibeVoice-ASR model card](https://huggingface.co/microsoft/VibeVoice-ASR)
- [SAGE-LD paper](https://arxiv.org/abs/2510.00582)
- [SAGE-LD official code appendix](https://github.com/sanghyang00/sage-ld)
- [NVIDIA LangID AmberNet model card](https://catalog.ngc.nvidia.com/orgs/nvidia/teams/nemo/models/langid_ambernet)
- [NVIDIA AmberNet research summary](https://research.nvidia.com/publication/2022-10_compact-end-end-model-local-and-global-context-spoken-language-identification)
- [NVIDIA NeMo AmberNet model documentation](https://docs.nvidia.com/nemo/speech/nightly/asr/speech_classification/models.html#ambernet-lang-id)
- [NVIDIA AI Product Terms](https://www.nvidia.com/en-us/agreements/enterprise-software/product-specific-terms-for-ai-products/)
- [NVIDIA Software License Agreement](https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-software-license-agreement/)
- [SpeechFlow spoken-language-identification model](https://huggingface.co/SpeechFlow/spoken_language_identification)
- [SpeechFlow official source](https://github.com/SpeechFlow/spoken_language_identification)
- [FireRedLID model](https://huggingface.co/FireRedTeam/FireRedLID)
- [FireRedASR2S and FireRedLID official source](https://github.com/FireRedTeam/FireRedASR2S)
- [FireRedLID paper](https://arxiv.org/abs/2603.10420)
- [Silero model history](https://github.com/snakers4/silero-vad/wiki/Version-history-and-Available-Models)
- [Silero model licensing tiers](https://github.com/snakers4/silero-models/wiki/Licensing-and-Tiers)
- [SpeechBrain VoxLingua107 ECAPA](https://huggingface.co/speechbrain/lang-id-voxlingua107-ecapa)
- [TalTech VoxLingua107 EPACA-TDNN](https://huggingface.co/TalTechNLP/voxlingua107-epaca-tdnn)
- [TalTech VoxLingua107 EPACA-TDNN-CE](https://huggingface.co/TalTechNLP/voxlingua107-epaca-tdnn-ce)
- [Pablex Whisper-tiny FLEURS language classifier](https://huggingface.co/Pablex/whisper_tiny_fleurs)
- [Vakgyata-tiny](https://huggingface.co/onecxi/vakgyata-tiny)
- [Open Vakgyata](https://huggingface.co/onecxi/open-vakgyata)
- [Simba-SLID-49](https://huggingface.co/UBC-NLP/Simba-SLID-49)
- [TalTech VoxLingua107 XLS-R 300M](https://huggingface.co/TalTechNLP/voxlingua107-xls-r-300m-wav2vec)
- [ESPnet GeoLID VoxLingua107](https://huggingface.co/espnet/geolid_vl107only_shared_trainable)
- [SpeechBrain CommonLanguage ECAPA](https://huggingface.co/speechbrain/lang-id-commonlanguage_ecapa)
- [Whisper-base CommonLanguage audio classifier](https://huggingface.co/sanchit-gandhi/whisper-base-ft-common-language-id)
- [DistilHuBERT CommonLanguage classifier](https://huggingface.co/anton-l/distilhubert-ft-common-language)
- [CrispASR source](https://github.com/CrispStrobe/CrispASR)
- [CrispASR ECAPA implementation](https://github.com/CrispStrobe/CrispASR/blob/main/src/ecapa_lid.cpp)
- [CrispASR ECAPA-LID-107 GGUF model](https://huggingface.co/cstr/ecapa-lid-107-GGUF)
- [Evaluation-only VoxLingua107 ONNX conversion](https://huggingface.co/christopherthompson81/voxlingua107-lid-onnx)
- [SpeechBrain ONNX support tracker](https://github.com/speechbrain/speechbrain/issues/2661)
- [`whisper.cpp` v1.9.1 release](https://github.com/ggml-org/whisper.cpp/releases/tag/v1.9.1)
- [`whisper.cpp` language-probability C API](https://github.com/ggml-org/whisper.cpp/blob/v1.9.1/include/whisper.h)
- [Official `whisper.cpp` model release](https://huggingface.co/ggerganov/whisper.cpp)
- [ESPnet MMS-ECAPA spoken-LID release](https://huggingface.co/espnet/lid_voxlingua107_mms_ecapa)
- [SenseVoice official release scope](https://github.com/FunAudioLLM/SenseVoice)
- [3D-Speaker official language-identification releases](https://github.com/modelscope/3D-Speaker)
- [Gladia realtime multilingual ASR router](https://github.com/gladiaio/realtime-multilingual-asr-router)
- [Gladia router MIT license](https://github.com/gladiaio/realtime-multilingual-asr-router/blob/4e25d6489624db46dca627a59c35ad0222c2636b/LICENSE)
- [Gladia router dependency declaration](https://github.com/gladiaio/realtime-multilingual-asr-router/blob/main/pyproject.toml)
- [Gladia router CI workflow](https://github.com/gladiaio/realtime-multilingual-asr-router/blob/main/.github/workflows/ci.yml)
- [`parakeet-rs` Nemotron adapter](https://github.com/altunenes/parakeet-rs/blob/7deba612fc9a30c4a7182f4eaa53554cb2fa42c8/src/nemotron.rs)
- [`parakeet-rs` release repository](https://github.com/altunenes/parakeet-rs)
- [`ort` Rust ONNX Runtime binding](https://github.com/pykeio/ort)
- [sherpa-onnx spoken-language identification models](https://k2-fsa.github.io/sherpa/onnx/spoken-language-identification/pretrained_models.html)
- [sherpa-onnx source](https://github.com/k2-fsa/sherpa-onnx)
- [sherpa-onnx multilingual Nemotron implementation](https://github.com/k2-fsa/sherpa-onnx/pull/3671)
- [fastText language identification](https://fasttext.cc/docs/en/language-identification.html)
- [Google CLD3 archive](https://github.com/google/cld3)
