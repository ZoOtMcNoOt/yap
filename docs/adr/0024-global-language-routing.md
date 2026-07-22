# ADR 0024: Global language routing and timing evidence

**Date:** 2026-07-16; amended 2026-07-22
**Status:** Accepted decision; the local detector lifecycle, bounded dynamic
routing, source-time switch evidence, visible primary fallback, pinned server
Nemotron reference routes, provider-specific Cohere vLLM and resident NeMo
adapters, and fail-
closed English Cohere timing implementation now execute under focused tests. A
contained GB10 lifecycle proof exercised the current timing source without
promoting it. The accepted local route is exposed on the active branch only as
an explicit, default-off **Preview**: its consumed representative natural-switch
quality target failed and remains a visible limitation rather than a
qualification claim. Target-i5 resource/lifecycle evidence, per-locale quality
evidence, the frozen Cohere vLLM comparison, the separate Nemotron NeMo
streaming gate, and the complete Phase 6 gate remain incomplete.
SpeechFlow LID13 and FireRedLID have now failed behavior and payload preflight;
Whisper base also failed broad global-top behavior, and both official base and
tiny Q5_1 routes failed client throughput preflight. The frozen narrow
`en-US`/`es-US` Whisper-tiny route also failed its disjoint natural-switch gate.
After the AmberNet research candidate likewise missed the original zero-false
natural/noisy transition threshold, the product owner explicitly accepted the
exact AmberNet 1.12.0 static QDQ INT8 artifact as Yap's bounded resident
acoustic-evidence component. That amendment accepts imperfect switching rather
than claiming the failed threshold passed: three observations, a `0.40` softmax
margin, and visible primary-locale fallback remain mandatory. The artifact is
verified local-import only until redistribution review is complete. A later
58-clip frozen holdout was consumed once after threshold selection and produced
54 correct alternate decisions, one abstention, three wrong decisions, and zero
false alternates when the primary was correct. A focused eight-logical-CPU
affinity proxy on the i7-13850HX development host proved the exact-source
combined path below real time and exposed four-thread native oversubscription.
The executable local Nemotron default is now two inference threads: the
controlled combined path improved to `0.431` RTF and about 1.61 logical-core
equivalents over continuous source time. One thread remained below real time at
`0.484` RTF but loaded materially more slowly. A source-paced follow-on then
accepted all 3,840 ten-millisecond frames with no loss through the bounded
64-frame local-ASR queue, reached a 42-frame high-water mark, drained 864 ms
after 38.4 seconds of source, averaged 1.765 logical cores (22.066% of the
eight-CPU budget), and measured 0.752 ms p95/6.966 ms maximum scheduler wake
delay. A four-logical-CPU repeat also lost no frames, reached 45/64 queued
frames, drained in 911 ms, averaged 1.773 cores during source-paced input, and
measured 8.023 ms p95/45.864 ms maximum scheduler wake delay. Its accelerated
combined pass used 3.71 of four cores and is not an interactive-use claim. This
is not target-i5, rendered-UI, energy, or thermal evidence; those gates,
sustained lifecycle evidence, and the complete Phase 6 gate remain open. The
natural/noisy transition result is a completed failure accepted only under the
Preview boundary, not an unfinished pass claim. The
released `parakeet-rs` Nemotron adapter still hides
the emitted tag from every public transcript API, so it does not provide a
released same-model escape hatch.
**Deciders:** Yap product owner and implementation owner
**Builds on:** [ADR 0003](0003-long-term-voice-architecture.md),
[ADR 0004](0004-background-diarization-okf-agents.md),
[ADR 0006](0006-silero-agents-state-machine.md),
[ADR 0007](0007-forced-alignment-engine.md),
[ADR 0008](0008-speechbrain-lid-gate.md), and
[ADR 0014](0014-server-tier-compute-topology.md)
**Amends:** ADR 0003's English-only future-language description, ADR 0007's
historical Canary/Wav2Vec2 engine choice, ADR 0008's fixed confidence threshold,
raw-window strategy, and desktop-side delivery assumption, and ADR 0019's
prohibition on any second local audio-inference component only as needed for one
bounded non-ASR acoustic-LID component; ADR 0019's single local ASR and no-ASR-
router decisions remain intact
**Constrained by:** [ADR 0019](0019-local-streaming-model-selection.md),
[ADR 0020](0020-meeting-capture-diarization-authority.md), and
[ADR 0023](0023-bounded-live-priority.md)
**Amended by:** [ADR 0025](0025-provider-specific-asr-serving.md) and
[ADR 0026](0026-ambernet-batch-language-preflight.md)

## Context

The merged Phase 5 path requires one explicit language and sends every accepted
recording to the locked Cohere batch worker. That is a valid narrow vertical
slice, but it is not the intended global product:

- Cohere covers 14 languages and remains the accuracy-first batch choice where
  it is supported.
- NVIDIA Nemotron 3.5 ASR Streaming 0.6B exposes 19 transcription-ready and 13
  broad-coverage locales out of the box, supports streaming and batch use, and
  can emit language tags in `target_lang=auto` mode.
- Nemotron lists eight additional locales as adaptation-ready. Those require
  fine-tuning and are not current Yap capabilities.
- Short snippets do not contain enough speech for dependable language
  identification. Silence, meeting prompts, hold audio, mixed-language virtual
  recordings, and closely related languages also make a start-only classifier
  unsafe.
- The checked Nemotron reference image is `nvcr.io/nvidia/pytorch:26.06-py3`,
  with Python 3.12 and NVIDIA PyTorch 2.13 alpha. The independently pinned
  Cohere serving candidate uses NVIDIA vLLM 26.06, also on Python 3.12, and
  keeps its runtime dependency set separate from the Nemotron reference path.
- The server retains raw Transformers/BF16 reference workers for correctness
  comparison. The Cohere vLLM request adapter, locked image contract, and
  loopback launcher now execute under focused tests. A dirty-head GB10 service
  proof preserved exact reference output through c2/c4/c8 and observed engine
  abort, recovery, and teardown, but the checked-head representative lifecycle
  and capacity gate has not promoted it. A resident NeMo worker,
  cache-aware scheduler, authenticated adapter, image, and launcher also execute
  under focused tests; it remains a candidate rather than a selected live
  service.
- Source-exact focused GB10 smokes at executable commit
  `fcccf21e785b116b92cd8e46150a36b9b5ee91db` ran the locked Cohere and Nemotron
  models through Yap's real vLLM and NeMo adapters and cleaned up their
  containers/listeners. A separate source-exact run at
  `04266c4bbffd0fd31eaf2afd0bcce42e0248344f` exercised the now-superseded
  SpeechBrain CPU image through the real `ContainerLidWorker` over both bounded
  probes. That receipt remains historical evidence. These close only the named
  image/model/adapter execution prerequisites; frozen current-runtime resource,
  representative, duration, concurrency, and promotion gates remain open.
- Cohere does not return dependable word timestamps. Downstream meeting
  evidence needs timing, but invented or structurally invalid word intervals
  are worse than an explicit unavailable result.

The product therefore needs separate decisions for the user's default language,
long-recording language suggestions, explicit dynamic-language transcription,
provider selection, and timing evidence. A single opaque "auto" switch would
conflate all five.

## Decision

### 1. Make language and timing support data-driven capabilities

The server owns a versioned capability catalog. The desktop renders that catalog
and may retain a last-known verified snapshot for offline explanation, but it
does not hard-code a permanent model/language matrix.

Each provider revision records at least:

- provider and immutable model revision;
- BCP 47 locale;
- mode: local live, server live, fixed-language batch, or dynamic batch;
- quality tier: `transcriptionReady`, `broadCoverage`, or `preview`;
- whether language suggestion, per-segment language tags, and word alignment
  are available;
- license/provenance identity; and
- the benchmark/evidence revision that promoted the capability.

For fixed-language work, provider choice happens only after a user language
decision. Dynamic work requires an equally explicit mode choice. Models remain
replaceable behind the capability and worker contracts; changing a model must
not change durable job, result, or UI ownership.

For fixed-language batch work, prefer Cohere for its supported languages when
the user selects accuracy-first processing. Use Nemotron for enabled locales
outside Cohere's matrix and for an explicit fast/broad-coverage choice. An
automatic/mixed-language job stays on Nemotron for its complete lifetime; Yap
does not silently switch ASR providers between utterances.

On a fixed Nemotron route, the immutable user/LID-selected prompt remains the
language authority. The model may emit a different known locale tag for an
accent, regional variant, or short code-switched span; Yap validates and strips
that metadata but neither lets it rewrite the fixed route nor fails the whole
transcription. An unknown or malformed tag still fails closed. Only explicit
automatic mode retains valid emitted tags as ordered language evidence.

Serving-engine choice is provider-specific under ADR 0025:

- Cohere batch uses the digest-pinned NVIDIA vLLM 26.06 candidate. vLLM lists
  the exact `CohereAsrForConditionalGeneration` architecture and exposes it
  through the standard transcription API. The adapter, loopback/API-key
  boundary, and thin compatibility layer execute under focused tests; the
  frozen GB10 lifecycle and capacity gate remains required before promotion.
- Nemotron 3.5 is cache-aware FastConformer-RNNT. Its exact current DGX Spark
  correctness route is the pinned Transformers reference. The model-native
  resident NeMo candidate now executes bounded finalized jobs behind Yap's
  provider-neutral contract, but its separate frozen streaming/representative-
  workload gate remains open. Current vLLM does not list this RNNT architecture,
  and Nemotron cannot inherit Cohere's vLLM gate.
  NVIDIA NIM remains ineligible until its DGX Spark support and exact model
  identity are unambiguous and separately verified.

Phase 6 may add one pinned Nemotron reference worker and route/correctness/
resource evidence. It does not promote authenticated ownership, persistent warm
model residency, multiple production workers, or mixed live/batch capacity.

The production serving target does not change those Phase 6 model decisions.
Phase 6 measures Cohere's vLLM runtime against the raw Transformers reference
and keeps Nemotron's NeMo streaming promotion gate independent. SGLang is
reserved for compatible Phase 9 agent/LLM models and is not an ASR provider.
Rust-owned orchestration and durable contracts remain independent of every
runtime so providers can be replaced without rewriting job identity, language
decisions, cancellation, or result authority.

### 2. Expose the honest global language catalog

Nemotron's 32 out-of-box locales are eligible for the Phase 6 catalog:

| Tier | Locales |
| --- | --- |
| Transcription-ready | `en-US`, `en-GB`, `es-US`, `es-ES`, `fr-FR`, `fr-CA`, `it-IT`, `pt-BR`, `pt-PT`, `nl-NL`, `de-DE`, `tr-TR`, `ru-RU`, `ar-AR`, `hi-IN`, `ja-JP`, `ko-KR`, `vi-VN`, `uk-UA` |
| Broad-coverage | `pl-PL`, `sv-SE`, `cs-CZ`, `nb-NO`, `da-DK`, `bg-BG`, `fi-FI`, `hr-HR`, `sk-SK`, `zh-CN`, `hu-HU`, `ro-RO`, `et-EE` |

Cohere adds accuracy-first overlap and one useful non-overlapping current
capability, Greek (`el-GR`). The resulting catalog can represent 33 locale
entries across 29 language families. Availability is not the same as an
enterprise accuracy certification: broad-coverage entries must retain their
visible tier until Yap's own fixtures justify promotion.

The following Nemotron adaptation-ready locales are intentionally excluded:
`el-GR`, `lt-LT`, `lv-LV`, `mt-MT`, `sl-SI`, `he-IL`, `th-TH`, and `nn-NO`.
Greek remains available only through Cohere. Yap does not build a fine-tuning
pipeline, advertise these eight as Nemotron support, or infer support from a
tokenizer/prompt dictionary.

### 3. Require a primary language during setup

Setup asks the user to confirm one primary language/locale from the current
capability list. The OS locale may preselect a suggestion, but it is not saved
as the user's decision until confirmed. The setting remains editable.

- Outside explicit dynamic mode, recordings under the accepted batch-preflight
  duration or speech-evidence bounds use the primary/manual language and do not
  run the separate LID component.
- Local live warmup loads the confirmed primary locale, validates it against the
  exact 32-locale out-of-box Nemotron allowlist, and applies it to every native
  stream, including streams recreated after reset. Unsupported locales fail
  visibly before model loading rather than falling back to English or auto mode.
- The 1.12-second Nemotron chunk is a preferred decode increment, not a minimum
  recording duration. Stop flushes a shorter buffered tail, adds the bounded
  1.5-second decoder-finalization silence, and marks the stream finished. A
  sub-window correction stays on the confirmed primary locale rather than
  waiting for or fabricating automatic LID evidence. Exact 250 ms through
  two-second natural-speech quality and release-to-final latency remain an
  explicit promotion gate.
- Changing the primary locale first retires any idle warm stream and blocks a
  concurrent live start. Active capture must stop before the change can commit.
- Every imported job has a visible language override. Recent and favorite
  languages may be placed near the top of the picker.
- A per-job override or detected suggestion never rewrites the saved primary
  language.
- Country/locale is never inferred from IP address or physical location.

### 4. Use AmberNet only for bounded batch preflight

[ADR 0026](0026-ambernet-batch-language-preflight.md) now owns the exact model,
runtime, artifact-delivery, probe-selection, and score semantics for this
boundary. In summary:

1. The server verifies one explicitly imported AmberNet 1.12.0 INT8 QDQ ONNX
   artifact; it neither bundles nor downloads the NGC-governed model.
2. A CPU-only Python 3.12/NumPy/ONNX Runtime worker runs networkless, non-root,
   one-threaded, and without an ASR GPU slot.
3. Recordings under 30 seconds use the primary/manual route. Longer recordings
   require five exact six-second regions stratified from source start through
   the exact tail, with at least 3.2 seconds of VAD speech in every region.
4. Each region runs as two independent fixed three-second inferences. Yap
   averages logits only inside that region; it never concatenates requests or
   pads one user's input with another user's audio.
5. All five normalized labels must agree, every margin must be strictly
   positive, and the language must map to exactly one enabled fixed locale.
   Every other outcome opens the manual picker.
6. Store the immutable component identity, raw label, mapped locale, source
   offsets, probe digest, log score, margin, and user disposition. Never call
   the score calibrated confidence.
7. A supported suggestion only pre-fills the picker. The user confirms it before
   a fixed-language ASR job commits, and the saved primary is never rewritten.

This preserves ADR 0008's user-gate principle while superseding its SpeechBrain,
download, two-window, and fixed-threshold details.

### 5. Add bounded client-local language diarization and offline switching

Phase 6 adds one pinned acoustic-LID component alongside the single local
Nemotron ASR. The component is resident while local live inference is warm or
active, not merely for one window and not unconditionally from application
boot. It exists so offline live dictation can switch languages without waiting
for a server and so both local and server workflows can exchange the same
source-time language evidence.

- `LiveRuntime` remains the only local inference lifecycle owner. It loads and
  retires the LID component, enforces its incremental memory/CPU/energy budget,
  and owns all Nemotron stream creation, finalization, reset, and bounded
  source-audio retention. The detector-history and ASR-commit cursors share the
  same `Arc`-backed frames but advance independently: overlapping LID windows
  cannot discard future detector input, and detector history cannot replay ASR.
- The LID component owns only bounded acoustic observations and a deterministic
  temporal decision policy. It cannot publish transcript text, mutate the saved
  primary locale, select among ASR providers, or own durable job/session state.
- Automatic routing is a closed user-intent set: the confirmed primary language
  plus explicitly enabled alternates from the executable Nemotron catalog. A
  classifier label outside that set is abstention. Yap does not expose an
  unsafe "all languages" switch or infer likely alternates from geography.
- Initial utterance selection and a mid-utterance switch are separate policies.
  Initial selection may act on one sufficiently strong voiced window before
  transcript commitment; sustained switching requires repeated evidence and
  bounded lookahead. One scalar threshold cannot safely own both decisions.
- Enabling Preview alternates can delay initial partial text while Yap gathers
  the first three-second detector window. Stopping before a complete detector
  window flushes the entire held utterance through the confirmed primary
  locale. Users prioritizing the fastest short corrections leave alternates
  off and retain the ordinary primary-language streaming path.
- Its output is an ordered, monotonic, source-bounded `LanguageSpan` sequence
  carrying locale, start/end source samples, model/artifact revision, raw score
  and margin when available, and decision revision. Scores are evidence, not
  calibrated confidence.
- VAD supplies a speech mask but cannot remove source audio. Overlapping bounded
  LID windows, minimum-duration evidence, hysteresis, and lookahead prevent one
  noisy frame from changing the ASR prompt. Silence, ambiguity, an unsupported
  locale, or component failure holds or visibly returns to the confirmed
  primary locale rather than guessing.
- A confirmed switch partitions the bounded held source audio at the accepted
  boundary, feeds every source sample exactly once to the matching Nemotron
  stream, finalizes the old stream, and creates one new stream with the selected
  supported locale. Yap does not replay overlapping audio or depend on
  unavailable token timing; finalized segment text is appended immutably.
- Within-utterance language spans and best-effort switching are a Phase 6
  outcome, but the route is default-off and visibly labeled **Preview**. The
  consumed natural-switch target failed, so availability does not certify a
  locale, boundary, or natural code-switch accuracy. Phase 6 release still
  requires exact source custody, primary fallback, bounded holdback, transcript
  continuity, target resource behavior, restart, and cancellation evidence.
  Removing the Preview label or making stronger quality claims requires new,
  independently frozen natural/noisy evidence. Seeing two clip labels is not
  proof.

The exact LID model and inference format are selected by the Phase 6 evidence
gate rather than by model-card popularity. The measured native Whisper-tiny
path is the valid runtime comparator but is rejected for broad switching by its
production-window accuracy. A released Whisper-base INT8 proxy improved global-
top case accuracy to 64/84 but still failed broad related-language behavior.
The official 59,707,625-byte Whisper-base Q5_1 model exposed the enabled-set
probabilities the product policy needs, but its one-thread `whisper.cpp` path
processed only 0.408 windows per second, 20.4% of the 500-ms-hop requirement;
the incomplete sequential prefix is not accuracy evidence. The distinct
32,152,673-byte Whisper-tiny Q5_1 full-probability route then produced 0.820
speech windows per second, 41.0% of the same one-thread requirement, and was
also rejected before accuracy or holdout work. A separately frozen
disjoint qualification then rejected the narrower `en-US`/`es-US` Whisper-tiny
route: 13 gates passed, but it emitted only three of five expected natural
language-order segments and matched two natural boundaries, below minimums of
four and three. Its zero monolingual false routes, zero wrong constructed
transitions, and exact audio custody remain implementation evidence, not grounds
for retuning or promotion. Native CrispASR
ECAPA-LID-107 is also rejected: it
was slower, less accurate than the ECAPA ONNX comparator on whole clips,
committed excessive private memory, and added an unjustified native dependency
surface. An independently exported official SpeechBrain ECAPA graph passed its
  deterministic export and native-runtime probes but failed both held-out routing
  gates. Its pair-restricted two-stage policy preserved sustained-switch safety
  but produced four false Mandarin initial routes across 30 natural English clips;
  it is not selected. A subsequent 26,460-policy enabled-language development
  search found no candidate satisfying the complete zero-false, coverage, and
  latency thresholds; thin pair-matrix cells are not certification. The distinct
  first-party TalTech VoxLingua107 EPACA release then failed its bounded public
  behavior preflight: 73/84 case pluralities and 1,098/1,539 windows did not beat
  the rejected official SpeechBrain baseline of 77/84 and 1,101/1,539. The stop
  rule prevented an enabled-language policy sweep, export, packaging, or third
  holdout. The bounded released-candidate follow-on screen rejected duplicate
  SpeechBrain/TalTech weights without rerunning them, narrow Whisper/Vakgyata
  regional releases, and approximately 378 MB to 3.9 GB Simba/XLS-R/ESPnet
  payloads for the resident-client role. The released `parakeet-rs` 0.3.6
  Nemotron adapter also strips language-tag tokens from its public result and
  would require an unreleased fork plus a separate community ONNX export.
  The user then explicitly authorized evaluation acquisition of NVIDIA AmberNet
  1.12.0. An exact native feature stage and static QDQ INT8 classifier passed
  export/parity, clean-clip, abstention, and latency development checks, but the
  candidate failed the original natural/noisy switch boundary: zero of four
  natural transitions on one recording, only 7/12 constructed 15 dB SNR
  transitions, and no safe enabled-pair policy on a second natural recording.
  That remains valid negative evidence. The product owner subsequently accepted
  the exact artifact as a pragmatic bounded route rather than continuing model
  research. Thresholds were frozen on a 29-clip calibration partition before a
  distinct 58-clip holdout was inferred once; the selected policy produced 54
  correct alternate decisions, one abstention, three wrong decisions, and zero
  false alternates when the primary was correct. Yap now contains the exact
  native frontend/runtime and a verified local-import lifecycle, while ambiguity
  or failure retains the explicit primary locale. Evaluation authorization does
  not establish product redistribution rights: the artifact is neither bundled
  nor network-downloaded, and NGC packaging obligations remain an explicit
  review boundary. Suitable licensed challengers may compete only if
  their feature pipeline, artifact provenance, packaging, supported-language
  mapping, resource behavior, and switch evidence are fully pinned. The shared
  Rust output boundary now validates the locked label-to-locale map once at
  component load and applies explicit speech, absolute-score, and global-margin
  abstention gates consistently to both initial and sustained decisions. Custom
  training or distillation is outside the current released-
checkpoint-only selection route. No private `sherpa-onnx` fork is required for
this design.

### 6. Use Nemotron auto mode for explicit server dynamic detection

Dynamic detection is a separate user-selected mode. The server Nemotron worker
uses `target_lang=auto` and preserves the emitted BCP 47 language tag on each
finalized speech segment.

- VAD/endpointing defines bounded server utterance candidates. Nemotron's
  terminal tag provides independent server evidence; it is reconciled with any
  client `LanguageSpan` input rather than silently replacing client history.
- Nemotron auto mode may evaluate a short finalized utterance because its tag is
  produced by the same transcription pass. The separate batch-preflight
  duration/speech thresholds are not applied to this path, and Yap does not describe the emitted
  tag as calibrated confidence.
- Missing, disabled, adaptation-ready, or structurally invalid tags produce an
  `Unknown` language segment and visible review state.
- The result retains per-segment language provenance and derives display text
  without discarding those tags.
- Users may correct a detected or unknown segment through History. Yap stores
  each change as a separate strict-schema, sequential, hash-chained revision
  bound to the exact immutable server result, session, source span, and original
  label. It never rewrites retained audio, `result.json`, or `transcript.txt`;
  restoring the source label appends another revision.
- Native correction writes are serialized and require the caller's expected
  revision. Stale, concurrent, no-op, noncanonical, future-schema, tampered, or
  path-unsafe artifacts fail closed. History derives effective labels only
  after the complete correction chain verifies.
- The primary language remains a visible manual re-run/fallback choice. Yap does
  not silently relabel an unknown dynamic segment as the primary language, and
  dynamic mode does not alter the saved setting.
- Server utterance tags alone do not prove within-utterance diarization. The
  shared `LanguageSpan` contract and the client-local span gate in Decision 5
  carry that Phase 6 claim.

The shared span schema is version 1 over the canonical 16 kHz sample timeline.
It requires contiguous complete coverage, monotonic decision revisions,
canonical BCP 47 tags, and explicit boundary authority. Local evidence uses
`clientDecision`; server results use `serverUtterance`, bind every span to the
immutable model and utterance-plan revisions, and link each lossless text
fragment through `sourceSpanIndex`. A mixed or incomplete server utterance is
`serverUnknown`/`und`; Yap does not manufacture token-level source boundaries
from terminal language tags. Both the isolated-worker and durable-result
boundaries validate this relationship, and the desktop revalidates it before a
dynamic result can enter History.

The current local `sherpa-onnx` 1.13.4 path has two distinct contracts. Its native
stream accepts an exact BCP 47 `language` option, so fixed live work can execute
the confirmed primary-language prompt. However, the Nemotron recognizer filters
automatic language-tag tokens before constructing its public result, and that
result exposes no detected-language field. This was rechecked at released tag
`v1.13.4`, commit `142807252687d81b40d6315f23470a1512a00de3`; upgrading to the
already pinned release does not create a same-model detector seam. Phase 6
therefore uses the separately pinned acoustic-LID component for local decisions
and keeps Nemotron fixed to the selected locale. It does not carry a private
sherpa fork. ADR 0019's one-local-ASR/no-ASR-router rule remains intact.

### 7. Align raw transcripts and fail closed by capability

ADR 0007's raw-text alignment principle remains accepted. Its historical
Canary/Wav2Vec2 engine choice is not.

The implemented candidate derives Cohere word boundaries from its decoder
cross-attention without adding another alignment model:

- run ordinary BF16 generation, then one bounded teacher pass over only the
  generated rows that still have valid alignment metadata;
- keep the model's configured attention backend unchanged and intercept only
  the selected decoder cross-attention inputs;
- reconstruct FP32 query/key logits for zero-based heads `(0, 5)` and `(1, 6)`;
- apply finite checks, normalization, median filtering, and monotonic DTW; and
- reconcile every emitted word with the raw transcript before publication.

The worker/result contracts and durable alignment stage now execute this path
and fail closed. The public capability catalog intentionally remains
`wordAlignment: false` until the frozen Phase 6 head meets boundary error,
monotonicity, coverage, transcript-reconciliation, latency, and memory promotion
gates. English is the first focused candidate. Unsupported or failed provider/
language pairs publish `alignedWords: []` plus an explicit unavailable reason;
they never fabricate even spacing, confidence, or speaker attribution.

Qwen3 ForcedAligner remains a benchmark challenger for its supported languages.
MMS 300M is rejected as the enterprise baseline because its current model
license is non-commercial. Nemotron decoder durations are not treated as forced
alignment for a Cohere transcript.

### 8. Keep the pipeline durable and source-authoritative

Normalization, VAD, LID preflight, user confirmation, ASR, alignment, and result
publication are distinct durable stages. Each stage records an input fingerprint,
provider revision, attempt, terminal outcome, and retryability. Retrying one stage
does not rewrite capture history or re-authorize a language choice.

For live capture, a persisted language-evidence record is complete only when its
source end equals the exact PCM extent already committed by the recording owner.
The owner rejects prefix-only or mismatched evidence, and a language-evidence
queue timeout or disconnect degrades the recording to a recoverable partial
capture. Logging and discarding the persistence failure is not an allowed
completion path.

Client VAD remains advisory under ADR 0020. The server may recompute boundaries
from retained source audio. False-negative VAD decisions never remove bytes from
the official ASR/reprocessing input. New server work preserves ADR 0023's
bounded live-preference and per-owner scheduling contract, but the executing
development runtime still dispatches through one fixed `development-loopback`
owner. Phase 7 owns authenticated tenant/user derivation. Phase 10 owns
persistent supervised model services, warm/multi-worker and mixed live/batch
capacity promotion, production observability, and enterprise deployment.

## Measured decision evidence

All audio fixtures used for this decision were public. Raw benchmark output and
host-specific paths remain outside Git; the numbers below are aggregate design
evidence, not language certification.

| Candidate | Result on the same public fixture shape | Resource observation |
| --- | --- | --- |
| Nemotron automatic LID | 78/84 correct across 28 out-of-box language families; 23/28 perfect | Mean 134 ms/probe; 1.293 GiB peak GPU allocation; emitted no calibrated confidence |
| SpeechBrain VoxLingua107 | 77/84 correct across the same 28 families, plus 3/3 Greek | CPU-only mean 179 ms and p95 234 ms per probe; about 760 MiB peak RSS, 1.1 GiB environment, and 82 MiB model |
| SpeechBrain probe length | 2 s: 39.3%; 3 s: 71.4%; 5 s: 86.9%; 8 s: 94.0% on this small sample | Supports an eight-voiced-second minimum; does not prove a universal optimum |
| Native Whisper tiny LID | Correctly identified one public English and one Japanese smoke clip, then passed a constructed `en-US` to `ja-JP` exact-once switch within 250 ms. The representative production-window comparator subsequently produced only 56/84 correct case pluralities and 767/1,539 correct windows across 28 FLEURS language families, rejecting it for broad automatic switching. Its frozen narrow `en-US`/`es-US` qualification retained 60/60 same-primary cases and produced 54/60 correct constructed second-language transitions with no wrong transition or audio loss, but emitted only 3/5 expected natural language-order segments and matched 2 natural boundaries; 13 frozen gates passed and 2 failed, so the narrow route is also rejected. | 98.0 MiB model; about 108 MiB immediate resident/private increase beside loaded Nemotron; the standalone comparator process peaked near 242 MiB working set/281 MiB private bytes with 154 ms mean, 186 ms p95, 193 ms p99, and 0.077 evaluated-window RTF. Package power was not process-attributable and thermal data was unavailable. |
| Released Whisper base INT8 proxy | Global-top behavior reached 64/84 correct case pluralities and 886/1,539 correct windows, but failed every Ukrainian, Norwegian Bokmål, and Estonian case. | Two ONNX files total 159,792,560 bytes; one-thread mean/p95/p99 was 144/172/179 ms with 0.072 evaluated-window RTF. Conversion provenance is not promotion-grade; rejected for broad switching. |
| Official Whisper tiny Q5_1 plus `whisper.cpp` v1.9.1 | The full-probability API could represent the explicit enabled set, but the candidate failed throughput before any accuracy, threshold, natural-switch, or holdout evaluation. | The 32,152,673-byte Q5_1 model averaged 1,219 ms with 1,241 ms p95 across 32 speech-qualified production-shaped windows: 0.820 windows/second and only 41.0% of required one-thread throughput. The evaluation process peaked near 241 MB working set, including Python/VAD/bridge overhead; rejected at resource preflight. |
| Official Whisper base Q5_1 plus `whisper.cpp` v1.9.1 | The full-probability API could represent the explicit two-language enabled set, but the accuracy run was stopped after a sequential 314/1,539-window prefix and that prefix is not scored. | The 59,707,625-byte Q5_1 model took 770.1 seconds for 314 windows: 2.453 seconds/window, 0.408 windows/second, and only 20.4% of required 500-ms-hop throughput. The process used 769.62 CPU seconds; its 316.6 MB working set/817.8 MB private snapshot includes the Python/VAD evaluation harness and is not incremental product memory. Rejected at resource preflight. |
| Native CrispASR ECAPA-LID-107 | 33/84 correct arbitrary first two-second windows; 71/84 whole clips exact or 74/84 after only `no` to `nb`, below the ECAPA ONNX comparator's 77/84 | About 250 ms mean for first two-second windows and 1,261 ms whole-clip mean; roughly 848 MiB peak private bytes; minimal native target compiled about 56,304 physical C/C++ lines with ggml; rejected |
| Evaluation-only ECAPA ONNX | 77/84 correct case pluralities and 1,101/1,539 correct two-second windows; strongest measured local behavior, but the third-party export is not promotion provenance | Four-thread ONNX Runtime mean 62 ms/p95 76 ms. The unpinned exporter lacks explicit root-script license coverage; fixed-window `ort-tract` reproduced output but averaged 459 ms/p95 473 ms and peaked near 255 MiB working set. Comparator only. |
| Independently exported official SpeechBrain ECAPA ONNX | The first disjoint one-policy gate detected 60/66 exact joins with zero wrong joins, but made two monolingual false switches and routed only 8/30 natural Mandarin utterances from an English primary. The frozen pair-restricted two-stage policy then passed every second-gate threshold except natural English startup safety: 81/81 non-English FLEURS initial routes, 28/30 natural Mandarin initial routes, 58/66 exact sustained switches, zero wrong/sustained-monolingual routes, but four false Mandarin initial routes across 30 English ASCEND clips. A primary-biased latched search across both rejected corpora could achieve zero false routes only at 84.6% FLEURS coverage and four-second p95 selection. | Deterministic 86,010,473-byte graph; native load about 238 ms, warm inference about 80 ms, standalone peak near 167 MiB working set, and same-process Nemotron plus ONNX Runtime peak near 952 MiB. The global-top-label adapter is rejected; enabled-set score calibration remains development-only and would require a third disjoint gate. Distribution and lifecycle remain unpromoted. |
| Official SpeechBrain ECAPA QDQ INT8 diagnostics | FP32 produced 989/990 correct clean enabled-pair development decisions and 49/58 exact natural decisions. The U8S8 and S8S8 QDQ graphs collapsed to 365/990 and 399/990 clean decisions and retained no non-empty zero-wrong natural threshold. | Each INT8 graph was approximately 22.8 MB and averaged 39.4/42.7 ms versus FP32 61.8 ms on the development host. Both are rejected; Q8 failure is not evidence that a Q4 derivative would work. |
| SpeechFlow LID13 | The 13-language-plus-`other` release passed size/latency preflight but failed behavior preflight. At the best strict two-second development threshold, FLEURS retained 354 correct/11 wrong/625 abstentions and natural English/Spanish retained 8 correct/1 wrong/47 abstentions. Four-second grouped linear calibration reached 768/801 FLEURS decisions but produced 9 correct/2 wrong on the small exact natural slice; zero wrong retained only 2/11 natural windows. | Apache-2.0, 5,428,476-byte release, 1,047,440 parameters, and one-thread 22.021 ms mean/24.952 ms p95/25.974 ms p99 two-second inference. Rejected before qualification; no product runtime or model added. |
| FireRedLID | Publisher reports more than 100 languages, 20-plus Chinese dialects, and 97.18% utterance accuracy over 82 FLEURS languages; Yap did not run inference. | Apache-2.0, but the published checkpoint payload is 3,550,103,418 bytes and no documented small native client artifact exists. Rejected at client payload preflight; archive size is not claimed as runtime memory. |
| NVIDIA LangID AmberNet | The official FP32 model reached 322/340 whole-clip decisions on Yap's out-of-training-domain FLEURS development comparator. The exact native frontend plus static INT8 graph reached 323/340, including 276/280 supported cases; that one-case difference is parity/noise, not evidence that INT8 is more accurate. A frozen abstaining development policy routed 265/280 supported cases with zero wrong routes and held all 60 controls, but the same candidate detected 0/4 natural transitions on one recording and only 7/12 constructed 15 dB SNR transitions. A second natural recording plus clean/control development search found no policy satisfying the original zero-false transition gate. The later accepted `0.40`-margin/three-observation policy was frozen on 29 calibration clips and then consumed a distinct 58-clip holdout once: 54 correct alternates, one abstention, three wrong alternates, and zero false alternates when the primary was correct. A separately frozen clean German-English product-route set then passed exact source coverage and primary fallback but detected 0/4 required natural alternate spans and matched neither boundary. The exact implemented-detector post-failure diagnostic saw 68 speech-qualified alternate-region windows, only five alternate top labels, and one alternate observation above the `0.40` margin; the earlier FP32 diagnostic also misclassified three spans. This is a deliberate bounded product tradeoff and a model/domain limitation, not a quantization regression or a retroactive pass of the earlier natural/noisy gate. | Official 116,049,920-byte/28,926,299-parameter `.nemo`; exact 29,613,392-byte static QDQ INT8 classifier; native three-second-window median/p95 33.90/38.83 ms on the development Windows host. Yap implements the exact native frontend, one-thread ORT session, 107-label boundary map, and verified local-import lifecycle. This is not target-i5 ASR-interference evidence. The artifact is not bundled or network-downloaded, and NGC redistribution obligations remain open. |
| Cohere attention alignment | Held-out English start MAE 74.71 ms, end MAE 68.53 ms, minimum exact-word transcript coverage 93.33%; zero-based heads `(0, 5)` and `(1, 6)` with reflected median width 3 | A contained, non-promotion GB10 lifecycle proof on current source produced WER 0.0, 23 source-bounded words, identical transcript/alignment hashes across two runs, stable `sdpa`, 2,306/159 ms wall time, and 4,190,281,728-byte peak allocation; English-only evidence |

SpeechBrain confidently confused examples of Russian/Belarusian,
Czech/Slovak, Bokmål/Nynorsk, and Croatian/Bosnian. It also emitted arbitrary
language labels for silence and noise. Nemotron sometimes emitted no tag and
made one related-language error in the same small set. These observations are
why speech presence, multiple windows, explicit tiers, and user confirmation
are architectural requirements.

The first constructed-switch run exposed an overlap-retention defect: ASR had
committed audio that the next 2-second/500-ms-hop detector window still needed.
The pipeline now keeps independent bounded detector-history and ASR-commit
cursors over shared frames. A model-free focused regression covers the overlap,
and the pinned-model diagnostic then passed. Natural code switches, noise,
related languages, false-switch pressure, transcript continuity, and the full
resource matrix remain required for a replacement or explicitly narrowed
candidate before promotion.

The existing English ASR comparison also remains relevant: Cohere used about
3.85 GiB and produced 1.302% mean WER on eight fixtures; Nemotron used about
1.19 GiB and produced 5.446% mean WER while loading much faster. That evidence
supports provider choice rather than replacing either model with the other.

## Options considered

### Primary language plus guarded LID and explicit dynamic mode — accepted

This gives short audio a deterministic path, long single-language recordings an
assistive suggestion, and multilingual traffic a model designed to emit tags.
It costs one isolated CPU LID component and a second server ASR pool, both behind
existing boundaries.

### Unbounded raw SpeechBrain window switching — rejected

VoxLingua107 is an utterance classifier, not a calibrated streaming or
code-switching router. Re-running its global top label on overlapping windows
would add flicker and would still confidently label silence/noise and related
languages. Any bounded SpeechBrain-derived challenger must instead restrict
evidence to the explicit user-owned language set, latch startup selection, use a
separate sustained-switch policy, and pass a new disjoint behavior gate.

### Nemotron auto mode for every request — rejected

Short utterances and Greek need different handling, auto mode has no calibrated
confidence, and Cohere retains a material accuracy advantage on its supported
batch languages. The user's chosen primary language is a stronger prior for
short snippets.

### Two-model voting on every probe — deferred

Agreement can raise precision, but it makes a lightweight batch hint depend on a
GPU model and complicates Cohere-only languages. Add it only if a larger
benchmark proves a material product benefit.

### Bounded sliding-window language diarization — accepted for Phase 6

True within-utterance code switching is a language-diarization problem, not an
utterance-labeling option. Phase 6 therefore implements a bounded source-time
span engine with explicit smoothing and ASR handoff instead of treating one
utterance label as diarization. The production model remains evidence-selected:
it must have a released, compatible license and pass multilingual switch-point,
overlap, noise, latency, memory, energy, and packaging gates before the feature
is advertised.

### Manual language only — retained as fallback, rejected as the only UX

Manual selection is always available and is the failure-safe behavior. It does
not by itself serve global users handling long or unknown recordings.

### Whisper or MMS LID/alignment stack — rejected for the current local route

The smallest native Whisper tiny LID export reused the existing sherpa runtime,
but its measured resident/private-memory increase beside loaded Nemotron was not
negligible, so it cannot be promoted merely because it reuses the native runtime.
Its frozen narrow English/Spanish qualification also missed required natural
segments and boundaries and is final rather than tunable development data. It
remains a measurable comparator. Whisper base improved global-top behavior
but remained unsafe across related languages, while both the official tiny and
base Q5_1 runtimes failed the 500-ms-hop throughput preflight even before a
representative accuracy decision. The ESPnet MMS-1B/ECAPA release is CC-BY-4.0 but its selected
checkpoint is 3,887,806,641 bytes, far outside the resident-client payload
boundary. The examined Meta MMS alignment/LID weights are also too large for
this role and their current non-commercial license is incompatible with the
enterprise baseline.

### Local quantization floor — accepted

No local model derivative below Q4 may be promoted. Q4 is the most aggressive
allowed quantization, not a blanket requirement to replace a more accurate Q8,
INT8, FP16, or FP32 artifact that still passes the target CPU and memory gate.
The current local Nemotron ASR remains the tested INT8 sherpa-onnx artifact.
Every future format must pass model-specific accuracy, i5-class CPU latency,
resident-memory, battery/thermal, packaging, and rollback evidence.

## Consequences

### Positive

- Yap can expose broad global capability without claiming unmeasured quality.
- Short snippets remain stable and fast.
- Offline language changes retain one ASR model, one lifecycle owner, and
  reviewable source-time span boundaries.
- The NVIDIA ASR image remains internally consistent.
- Models, aligners, and language catalogs can evolve without changing ownership
  or durable job identity.
- vLLM, NeMo, and SGLang remain replaceable serving implementations without
  becoming new session, job, language-decision, or result authorities.
- Missing timing remains truthful and recoverable.

### Negative

- Phase 6 adds an isolated server CPU runtime, one bounded resident desktop LID
  artifact, and another pinned reference-worker model lock.
- Broad-coverage languages require much more representative quality gates.
- The UI must explain fixed, suggested, dynamic, unsupported, and timing-
  unavailable states without implying certainty.
- Dynamic local fallback adds measurable resident memory, CPU/energy work,
  lookahead, bounded holdback, and stream-transition complexity.

### Neutral

- Phase 7 authentication, Phase 8 speaker diarization/identity, Phase 9
  knowledge, and Phase 10 enterprise networking/repo split are unchanged.
- Authenticated ownership is not a Phase 6 claim. Neither are persistent warm
  service, multi-worker/mixed-load capacity, or production observability; those
  remain Phase 10 promotion gates after the Phase 7 identity baseline.
- This ADR changes no IT-controlled DNS, certificate, firewall, ZPA, identity,
  or deployment requirement.

## Action items

1. [x] Implement the bounded versioned provider/language/timing capability
       catalog, separate endpoint, and verified last-known projection.
2. [x] Add explicit primary-language confirmation, condition/reset local live
       streams with that locale, invalidate stale warm state on preference
       changes, and freeze the primary/manual disposition into each imported job.
3. [ ] Enable a real selectable per-job alternate locale after a second fixed
       route passes its promotion gate.
4. [x] Produce advisory Silero VAD segments without deleting source audio.
5. [x] Replace the superseded SpeechBrain component with the verify-only
       AmberNet 1.12.0 INT8 QDQ artifact, five-region client/server contract,
       and small CPU ONNX Runtime image. Retain the historical SpeechBrain
       receipt. Exact executable commit
       `c6862262fa36a83bcd40a7bffa65ec6429ec097e` passed the focused ARM64
       image/resource/teardown smoke; keep its final frozen-head repetition,
       representative promotion, and complete phase evidence in the final
       Phase 6 gate.
6. [x] Preserve Whisper-tiny and the other released candidates as measured
       comparators; implement the accepted AmberNet 1.12.0 QDQ INT8 component
       with exact frontend/label/runtime identity and a verified local-import
       lifecycle that neither bundles nor downloads the artifact.
7. [ ] Finish release-safety evidence for the implemented `LiveRuntime`-owned,
       default-off Preview language-span engine, deterministic smoothing,
       exact-once bounded Nemotron handoff, visible fallback, and restart/
       cancellation behavior.
       The measured native Whisper, Whisper-base, official ECAPA, and SpeechFlow
       routes remain rejected for broad behavior or client resources, while
       FireRedLID fails payload preflight. AmberNet remains below the original
       natural/noisy transition threshold, but the product owner accepted its
       exact abstaining route with visible primary fallback after a distinct
       frozen holdout was consumed once. The frozen narrow English/Spanish
       Whisper-tiny route remains rejected and cannot be retuned. The later
       natural German-English product-route target also completed and failed;
       that failure fixes the Preview quality boundary and is not rerun or
       converted into a pass criterion. Deterministic Rust-owner safety now
       covers short flush, rapid/ambiguous evidence, exact-once handoff,
       detector failure, holdback exhaustion, pending-state reset across
       cancelled or restarted sessions, and missing-artifact fallback under
       focused tests. Target-i5 interference, sustained installed-artifact
       lifecycle and resource evidence, and the complete checked-head gate remain
       required for the accepted AmberNet route instead of another open-ended
       model search. Those are explicit Phase 6 blockers; removing Preview
       requires a future independent quality gate.
       The deterministic local duration runner is implemented at the narrower
       prepared-audio-frame-to-final boundary with exact checked-head, plan,
       private-suite, manifest, WAV, PCM, bounded-queue, and decoded-sample
       accounting. Its companion builder derives all ordered cases from the
       validated plan and atomically publishes the private collection from
       vetted external PCM16 sources. Its multi-hour run and the physical
       microphone/rendered-UI/target-i5 gate remain unconsumed, so this item and
       the ADR score stay open.
8. [x] Add reference fixed-language Cohere/Nemotron routes and explicit Nemotron
       auto mode without claiming a persistent production pool.
9. [ ] Finish the provider-specific serving gates from ADR 0025. For Cohere,
       prove the digest-pinned vLLM 26.06 image, exact model/output parity,
       duration and c1/c2/c4/c8 behavior, continuous-batching isolation,
       cancellation/recovery, bounded admission, memory, and clean teardown
       against the Transformers reference. For Nemotron, preserve the pinned
       Transformers fixed/automatic correctness reference and run the
       implemented resident NeMo candidate's separate frozen locale/duration/
       cache-state/concurrency/lifecycle gate before promotion. The retired Triton
       experiment remains negative evidence: cross-request tensor batching
       changed a Cohere transcript, and the parity-preserving singleton profile
       serialized model execution without a demonstrated throughput gain.
10. [x] Extend local/session and server/result contracts with source-bounded,
        revisioned language-span evidence and deterministic reconciliation.
        The server envelope is utterance-bound and model/plan-bound; it does not
        claim client acoustic switch boundaries.
11. [x] Implement fail-closed Cohere attention alignment and typed unavailable
        results behind per-language gates. Keep catalog `wordAlignment: false`
        until the frozen-head accuracy/latency/memory promotion gate passes.
12. [ ] Validate every advertised locale/tier on representative public and
       approved private-domain fixtures before changing a quality claim. The
       fail-closed case-level human-reference registry contract now executes,
       including authorized independent roles, blind-assignment proof, exact
       human exact-locale basis, reviewed rights/defects, and separate artifact
       hashes. No real second-locale receipt or private trust anchor exists yet,
       so this item and the ADR score remain open.
13. [ ] Run the complete Phase 6 local/native/server/GB10 matrix exactly once on
       the ready head, then require hosted exact-head review before merge.

## References

- [Nemotron 3.5 ASR Streaming 0.6B](https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b)
- [NVIDIA NeMo ASR inference](https://docs.nvidia.com/nemo/speech/nightly/asr/inference.html)
- [SpeechBrain VoxLingua107 ECAPA](https://huggingface.co/speechbrain/lang-id-voxlingua107-ecapa)
- [`whisper.cpp` v1.9.1](https://github.com/ggml-org/whisper.cpp/releases/tag/v1.9.1)
- [Official `whisper.cpp` model artifacts](https://huggingface.co/ggerganov/whisper.cpp)
- [ESPnet MMS-ECAPA spoken LID](https://huggingface.co/espnet/lid_voxlingua107_mms_ecapa)
- [Cohere Transcribe 03-2026](https://huggingface.co/CohereLabs/cohere-transcribe-03-2026)
- [vLLM 0.22.1 supported transcription models](https://docs.vllm.ai/en/v0.22.1/models/supported_models/#transcription)
- [vLLM 0.25.1 CUDA dependency pin](https://raw.githubusercontent.com/vllm-project/vllm/v0.25.1/requirements/cuda.txt)
- [Open vLLM 0.19 Cohere load issue](https://github.com/vllm-project/vllm/issues/39252)
- [Nemotron ASR Streaming NIM deployment](https://docs.nvidia.com/nim/speech/latest/asr/deploy-asr-models/nemotron-asr-streaming.html)
- [NVIDIA ASR NIM support matrix](https://docs.nvidia.com/nim/speech/latest/reference/support-matrix/asr.html)
- [NVIDIA ASR NIM performance tables](https://docs.nvidia.com/nim/speech/latest/reference/performances/asr/performance.html)
- [SGLang 0.5.12.post1 Parakeet encoder component](https://github.com/sgl-project/sglang/blob/v0.5.12.post1/python/sglang/srt/models/parakeet.py)
- [NVIDIA Triton Inference Server architecture](https://docs.nvidia.com/deeplearning/triton-inference-server/user-guide/docs/index.html)
- [NVIDIA Triton Inference Server 26.06 release](https://docs.nvidia.com/deeplearning/triton-inference-server/release-notes/rel-26-06.html)
- [NVIDIA Triton Model Analyzer](https://docs.nvidia.com/deeplearning/triton-inference-server/user-guide/docs/user_guide/model_analyzer.html)
- [SGLang serving project](https://github.com/sgl-project/sglang)
- [Dynamic-language candidate and local-footprint evaluation](../research/2026-07-16-dynamic-language-detection-evaluation.md)
- [Qwen3 ForcedAligner 0.6B](https://huggingface.co/Qwen/Qwen3-ForcedAligner-0.6B-hf)
- [Dynamic language detection evaluation](../research/2026-07-16-dynamic-language-detection-evaluation.md)
- [Local audio preprocessing stack](../specs/local-audio-preprocessing-stack.md)
- [Testing strategy](../specs/testing-strategy.md)
