# VoiceOS/Yap decision, evidence, and future-work queue

**Date:** 2026-07-17

**Status:** Living routing register. This document prevents design discussions,
open questions, and evidence obligations from disappearing into chat history. It
is not implementation proof and does not supersede an ADR, the ordered roadmap,
or the active phase plan.

**Current implementation authority:** repository state, executable tests, and
observed runtime behavior.

**Current delivery authority:** [roadmap](../../roadmap/ROADMAP.md),
[ADR 0024](../../adr/0024-global-language-routing.md), and the
[audio preprocessing and language routing plan](2026-07-16-audio-preprocessing-and-language-routing.md).

## How to use this queue

- `Accepted` records a boundary that should not be reopened without contrary
  evidence or an ADR amendment.
- `Open` names a decision and the evidence required to close it.
- `Deferred` records a real requirement whose owning phase has not started.
- `External handoff` means Yap can prepare artifacts and tests but cannot invent
  enterprise authority or infrastructure.
- A checked task means the named executable evidence exists on the current
  branch. Discussion, source inspection, a model card, or a successful smoke
  clip is not enough.
- Future rows do not authorize mixing phases. They move into a phase plan only
  when that separate branch begins.
- Private audio, transcripts, scans, credentials, host paths, and raw benchmark
  output stay outside Git and public CI artifacts.

## Discussion-to-authority register

| ID | Topic | Current direction | State and owning phase | Authoritative home |
| --- | --- | --- | --- | --- |
| D-01 | Replaceable ASR models | Rust-owned job/session contracts and the versioned capability catalog remain stable while Cohere, Nemotron, Qwen, or another provider is replaced behind a worker adapter. No model owns durable job identity or UI state. | Accepted; Phases 6 and 10 | ADR 0014, ADR 0024, Phase 6 plan |
| D-02 | Python and GPU base | Use Python 3.12 for checked NVIDIA workers. Phase 4/5 Transformers references use the pinned NVIDIA PyTorch 26.06 environment. Cohere's separate Phase 6 candidate uses digest-pinned `nvcr.io/nvidia/vllm:26.06-py3`, whose executable GB10 identity is Python 3.12, NVIDIA Torch 2.13 alpha/CUDA 13.3, and vLLM 0.22.1. Do not drift to Python 3.13/3.14 or mix packages across the two images without a new gate. | Accepted; Phase 6 | ADR 0014, ADR 0025, Phase 6 plan |
| D-03 | Serving split | Cohere batch uses vLLM, Nemotron retains a Transformers reference and evaluates NeMo for server streaming, SGLang is reserved for compatible agent/LLM reasoning and structured tool output, and Rust owns orchestration, admission, state, cancellation, and validation. Triton is retired from the current ASR plane. | Accepted target; prove vLLM and NeMo independently in Phase 6, SGLang in Phase 9, production integration in Phase 10 | ADR 0025, roadmap |
| D-04 | GPU versus CPU | ASR performance work belongs on GPU. CPU-only isolation is intentional only for bounded light preprocessing such as Silero VAD and the proposed SpeechBrain batch suggestion; it is not a plan to run the main server ASR on CPU. | Accepted; Phase 6 | ADR 0024, Phase 6 plan |
| D-05 | Concurrent users | Reference-worker concurrency is measured now, including c1/c2/c4/c8, queueing, tail latency, cancellation isolation, memory, and duration buckets. Authenticated multi-owner fairness and production mixed live/batch capacity require Phase 7 identity and the Phase 10 service gate. | Accepted split; Phases 6, 7, and 10 | ADR 0023, ADR 0024, roadmap |
| D-06 | Fixed live language | Setup/Settings owns one confirmed primary locale. Local Nemotron applies that exact supported locale to native stream creation and reset; unsupported locales fail visibly. It never silently falls back to English or automatic detection. | Implemented on active Phase 6 branch; gate pending | ADR 0024, current architecture |
| D-07 | Local dynamic language detection | Phase 6 must add one bounded acoustic-LID model that remains resident while local live inference is warm/active, automatic offline switching, and within-utterance source-time language spans. `LiveRuntime` remains the sole lifecycle owner and continues to use one local Nemotron ASR; the LID component owns evidence only, not transcript, capture, or durable state. Initial selection and sustained switching use the accepted three-observation, `0.40`-margin policy over the confirmed primary plus explicit alternates. Current selection is restricted to immutable released checkpoints. | Accepted bounded candidate implemented with AmberNet 1.12.0 QDQ INT8 as an explicit, default-off Preview. The representative natural-switch quality target completed and failed; target-i5 resource/interference, lifecycle safety, and checked-head gates remain open. Removing Preview requires new independent quality evidence. | ADR 0019 amendment, ADR 0024, dynamic-language evaluation |
| D-08 | Server language detection | SpeechBrain remains a bounded, user-confirmed suggestion for longer fixed-language imports. Server Nemotron automatic tags now execute as independent finalized-utterance evidence. The shared versioned span contract distinguishes `clientDecision` from `serverUtterance`, binds server spans to the model/utterance plan, and links text fragments without claiming terminal tags are within-utterance language diarization. | Implemented contract; representative/frozen promotion gates remain open in Phase 6 | ADR 0024 |
| D-09 | Global language coverage | Advertise only exact out-of-box, benchmarked locales. Nemotron's eight adaptation-ready locales are not planned capabilities. Broad coverage remains visibly lower-confidence until locale-specific evidence promotes it. | Accepted; Phase 6 | ADR 0024 |
| D-10 | Client/server preprocessing | The client owns capture/source admission, deterministic normalization, source identity, optional advisory VAD, bounded local acoustic LID, source-time language spans, and durable client evidence. The server owns heavyweight verification, ASR, alignment, and official result production. Redundant server validation may reconcile or reject evidence but must not create a second client-state authority or erase client history. | Accepted boundary; Phase 6 | ADR 0020, ADR 0024, current architecture |
| D-11 | Terminology | Present terminology under Dictation/Personalization, but store it in one model-independent terminology domain. Compile one versioned session snapshot into ASR hints/context first, deterministic casing/acronym normalization second, grammar-SLM preservation constraints third, and later OKF glossary projections. The SLM must not be the source of truth or reconstruct terms lost during decoding. | Boundary accepted; schema, scope, privacy, and delivery phase remain open | Section below; Phase 9 ADR amendment required before implementation |
| D-12 | Evaluation coverage | Separate natural transcript quality from deterministic runtime-duration/load tests. Cover short mumbling, clean/noisy spontaneous speech, accents, every advertised locale, meetings/overlap, virtual transport, terminology/numbers, silence, 15-minute live, 30-second-to-two-hour batch, and supported maximum duration. | Accepted; Phase 6 corpus/gate work incomplete | ASR evaluation corpus and runtime qualification |
| D-13 | Training/test exposure | Public corpora named in a model's training or evaluation are comparators, not independent promotion evidence. Use provenance locks, exposure classification, sealed post-freeze adjudicated holdouts, and exact audio/reference hashes. | Accepted; Phase 6 and later release gates | ASR evaluation corpus and runtime qualification |
| D-14 | Model challengers | Keep Cohere as the checked accuracy-first batch baseline and Nemotron as the cache-aware low-latency live/dynamic baseline until evidence changes that. Qwen3-ASR-1.7B, VibeVoice, Riva/NIM, and other challengers require a later provider review; none is promoted by a model card or blocks the frozen Phase 6 routes. | Queued after Phase 6; revisit in the appropriate Phase 9/10 provider and deployment work | Dynamic-language evaluation, later roadmap |
| D-15 | Quantization | Never promote a local derivative below Q4. Treat Q4 as the most aggressive allowed format, not a blanket replacement for a passing Q8/INT8 or higher-precision artifact. Choose per exact model, target CPU, duration, and quality/latency/memory/battery gate. | Floor accepted; per-provider evidence remains open in Phases 6 and 10 | Phase 6 plan and ADR 0024 |
| D-16 | NIM/Riva and DGX Spark | A serving product is usable only when its exact model/hardware support matrix and license/deployment contract include DGX Spark. Conflicting marketing/performance data does not override the support matrix. | Deferred challenger; do not block Phase 6 reference work | Phase 5 runtime evaluation, Phase 6 plan |
| D-17 | UI fluidity and ownership | Visual polish and motion can change later without replacing the backbone, but there must remain one tray-owned island/window and one state owner per domain. Invisible hit regions, duplicate state, accessibility regressions, or slow hot paths are correctness issues rather than cosmetic debt. | Accepted; focused UX closure in each phase, release polish in Phase 10 | Voice OS architecture, roadmap |
| D-18 | Maintainability review | Prefer comprehensible modules, explicit domain owners, bounded state machines, focused adversarial/race review, and executable contracts. Do not use a full security-plugin scan as a substitute for code review. | Accepted continuous rule | Checkpoint A evidence, phase plans |
| D-19 | Security scan cadence | Keep focused correctness/security/dependency/privacy review in every phase. Do not run another full-repository Codex Security plugin scan until Phase 10 unless a concrete new risk requires it. Keep scan artifacts private. | Accepted working rule; full scan Phase 10 | Roadmap working rules and Phase 10 queue |
| D-20 | GLib/platform warnings | GLib is not a Yap application architecture choice; it may enter through platform/native dependencies. Do not edit a lockfile merely to hide warnings. Classify each warning as a real supported-target defect, upstream-only warning, or missing native-platform gate, then fix/pin/patch only with reproducible evidence. | Open platform-debt audit; current phase closure or exact affected phase | P6-10 below |
| D-21 | LAN, SSH, Wi-Fi, and enterprise networking | Preserve LAN/loopback development and the SSH-tunnel rehearsal. DNS, certificates, ZPA, firewall policy, conditional access, production hosting, and deployment remain explicit IT/security handoffs. | Accepted; developer rehearsal now, external handoff Phase 10 | ADR 0021, roadmap |
| D-22 | Security and enterprise readiness | Secure coding, bounded inputs, provenance, privacy, cancellation, and fail-closed contracts are product work now. Enterprise certification, production access policy, formal deployment approval, and managed network controls cannot be claimed early. | Accepted split; every phase plus Phase 10 handoff | Roadmap |

## Current Phase 6 implementation queue

The Phase 6 plan remains canonical. These work packages decompose its unchecked
items into reviewable evidence units.

### P6-01 — Capability-catalog hardening

- [x] Reject duplicate provider/locale/mode identities in Python production and
  Rust projection paths.
- [x] Reject invalid or non-canonical BCP 47 tags, unknown quality tiers/modes,
  mutable revisions, oversized strings, and oversized catalogs.
- [x] Prove all eight Nemotron adaptation-ready locales remain excluded.
- [x] Bind every advertised route to an exact runtime/model/artifact lock and
  promotion-evidence revision.
- [x] Use the canonical valid catalog example across OpenAPI, Python, Rust, and
  TypeScript; use one shared invalid mutation registry across OpenAPI and the
  native trust boundary. Keep TypeScript as a projection of native-validated
  state rather than a duplicate raw-catalog validator. Prove fail-closed
  last-known behavior separately from current availability.

Focused verification on 2026-07-20 passed 27 Python contract/catalog tests,
8 native catalog tests, 20 TypeScript projection/preference tests, 6 native
snapshot tests, and 14 native language-preference tests. Four shared mutations
fail the OpenAPI schema. Credential-bearing model-source URLs and a stale
catalog fingerprint remain schema-valid but fail at the stricter native trust
boundary; a verified origin-bound snapshot can explain offline state but cannot
authorize a language choice.

### P6-02 — Primary language and real alternate-locale UX

- [x] Require an explicitly confirmed primary locale before local live warmup.
- [x] Apply the exact supported locale to every local stream and reset.
- [x] Reject unsupported local locales before model loading with actionable copy.
- [x] Retire idle warm state and block concurrent starts while changing the
  primary locale; reject the change during active capture.
- [x] Add an explicit local-live automatic-routing selector for zero or more
  catalog-supported alternate languages. Default to primary-only, persist one
  native-owned ordered set, and explain that enabled alternates trade broader
  switching for more ambiguity; do not conflate this with a server batch
  provider's fixed-locale catalog.
- [ ] Promote a second fixed-batch locale through exact model/runtime/catalog
  evidence.
- [ ] Enable the catalog-derived per-job locale picker only after that promotion.
- [x] Display fixed, broad-coverage, unsupported, suggested, dynamic, and unknown
  states without hiding provider or evidence limitations.

Focused verification on 2026-07-20 passed 11 native live-routing preference
tests and 29 settings, accessibility, recording-queue, language-display, and
transcript-summary tests. An empty promoted alternate set remains a truthful
zero-choice state rather than inferred model support.

### P6-03 — Preprocessing authority and SpeechBrain suggestion

- [x] Preserve full source bytes and source-time identity through normalization
  and advisory Silero VAD.
- [x] Persist bounded client-stage attempts and typed failure evidence.
- [x] Freeze the SpeechBrain 1.1.0/Python 3.12/CPU Torch-TorchAudio component,
  model revision, hashes, license, mapping table, and networkless image.
- [x] Admit only hash-verified source windows derived from durable VAD evidence.
- [x] Select at most two continuous windows of at most 15 seconds with at least
  eight voiced seconds; preserve exact source offsets.
- [x] Persist raw label, mapped locale, score, margin, component revision, and
  window evidence without calling the score calibrated confidence.
- [x] Route silence, disagreement, unsupported/ambiguous labels, timeout,
  cancellation, and component failure to the manual picker.
- [x] Require user confirmation before commit; never mutate the saved primary.
- [x] Prove by immutable runtime contract that the LID component is CPU-only and
  cannot consume an ASR GPU slot; bound duration, queue, cancellation, cleanup,
  and teardown in focused tests.
- [ ] Measure checked-head peak RSS and sustained CPU on GB10 inside the final
  Phase 6 resource gate.

Focused 2026-07-22 evidence first built the dirty-source ARM64 image as
`yap-lid:focused-4e36c3-v2`, enforced the immutable 107-label encoder/output
contract, and completed a hardened networkless real-checkpoint worker smoke
without SpeechBrain's prior inferred-label-count warning. Twenty directly
affected Python 3.12 tests passed. A later source-exact GB10 run at executable
commit `04266c4bbffd0fd31eaf2afd0bcce42e0248344f` built the platform-manifest-
pinned image and exercised the real `ContainerLidWorker` over two bounded
eight-second probes; both returned the expected English raw label and teardown
left no owned container or listener. The owner-restricted receipt remains
outside Git. This closes image execution only: checked-head peak RSS, sustained
CPU, target-i5 behavior, representative promotion, and the complete resource
gate remain open.

### P6-04 — Local language spans and fixed/dynamic ASR

- [x] Establish the licensed Whisper-tiny INT8 ONNX acoustic-LID comparator and
  lock its exact model, inference format, artifacts, hashes, locale mapping,
  and measured behavior. It remains historical comparator evidence rather than
  a product lifecycle.
- [x] Reject native CrispASR ECAPA-LID-107 on measured short-window/whole-clip
  accuracy, latency, private-memory commitment, and native dependency surface;
  keep its source, model, build, and raw evidence outside the product and Git.
- [x] Retain the faster/more-accurate ECAPA ONNX result as comparator evidence
  only. Reject the pure-Rust tract route on graph-specialization burden,
  459 ms mean/473 ms p95 two-second inference, and no memory advantage; do not
  reuse the unpinned exporter scripts without explicit license authority.
- [x] Independently export the pinned official SpeechBrain checkpoint, reproduce
  the graph deterministically, and prove a native ONNX Runtime boundary without
  adopting the third-party exporter. Record the roughly 167 MiB standalone and
  952 MiB combined Nemotron/runtime peaks as non-negligible.
- [x] Reject the shared initial/sustained threshold after its first independent
  gate produced two monolingual false switches and only 8/30 natural Mandarin
  initial routes. Convert that corpus to development data and freeze a pair-
  restricted two-stage candidate before acquiring disjoint validation B.
- [x] Reject the frozen two-stage startup candidate after disjoint validation B
  passed every threshold except natural English safety: four false Mandarin
  initial routes across 30 English clips. Its sustained four-window/`0.50`
  behavior remains useful evidence, not a promoted implementation.
- [x] Reject SpeechFlow LID13 before qualification. Its 5.43 MB/1.05-million-
  parameter release and roughly 22 ms one-thread two-second inference pass the
  footprint/latency preflight, but strict and grouped-calibrated English/Spanish
  development behavior cannot preserve zero false natural routes at useful
  coverage.
- [x] Reject FireRedLID at resident-client payload preflight without downloading
  its 3,550,103,418-byte checkpoint; do not misstate archive size as runtime
  memory. After the user explicitly authorized AmberNet evaluation acquisition,
  retain its failed original natural/noisy gate as negative evidence, then
  record the later explicit product decision to accept the exact QDQ INT8 route
  with three observations, a `0.40` margin, and visible primary fallback. The
  distinct 58-clip holdout was consumed once after threshold freeze; keep NGC
  redistribution obligations open and the artifact import-only. Reject the
  deprecated Silero classifier on maintenance/license grounds.
- [x] Reject the official ECAPA QDQ INT8 diagnostics: shrinking the graph to
  approximately 22.8 MB reduced latency but collapsed clean enabled-pair
  development correctness from 989/990 FP32 to 365/990 and 399/990. Do not infer
  Q4 viability from a Q8 failure.
- [x] Reject released Whisper-base global-top routing after the pinned INT8
  behavior proxy reached only 64/84 case pluralities and 886/1,539 production-
  shaped windows, including complete misses for several related-language
  families. Keep the proxy private and unpromoted because its conversion
  lineage is also insufficient.
- [x] Reject the official Whisper-base Q5_1 plus `whisper.cpp` v1.9.1 route at
  client throughput preflight. Its full probability vector could represent the
  explicit enabled-language set, but one CPU thread completed only 0.408
  windows/second, 20.4% of the 500-ms-hop requirement. Do not score the stopped
  314-window sequential prefix or add a second native runtime.
- [x] Reject the materially distinct official Whisper-tiny Q5_1 full-probability
  route at the same one-thread throughput preflight. Its 32 speech-qualified
  production-shaped windows averaged 1,219 ms with 1,241 ms p95 and delivered
  0.820 windows/second, only 41.0% of the required rate. Do not run accuracy or
  holdout work, add a second native runtime, or silently expand the resident CPU
  budget to rescue it.
- [x] Reject the frozen narrow Whisper-tiny `en-US`/`es-US` route after its one
  disjoint qualification passed 13 gates but emitted only three of five expected
  natural language-order segments and matched two natural boundaries, below
  frozen minimums of four and three. Preserve the zero monolingual false routes,
  zero wrong constructed transitions, and exact source-audio custody as useful
  implementation evidence, but do not retune on or reuse this qualification.
- [x] Exhaust the official SpeechBrain enabled-language development search:
  26,460 bounded policies produced no candidate meeting the complete zero-false,
  coverage, and latency thresholds. Do not promote thin pair-matrix cells or
  spend a third holdout on that checkpoint.
- [x] Reject the distinct first-party TalTech VoxLingua107 EPACA release at its
  bounded public behavior preflight. It reached 73/84 case pluralities and
  1,098/1,539 windows versus the rejected official SpeechBrain baseline's 77/84
  and 1,101/1,539. Honor the stop rule: no enabled-language policy sweep, export,
  packaging, or holdout follows.
- [x] Complete the bounded released-checkpoint follow-on screen. Do not rerun
  byte-identical TalTech-CE, SpeechBrain, or Akshay artifacts. Reject the
  six-language Whisper and 12-language Vakgyata releases as narrow, retain
  Simba-SLID-49 only as regional research, and reject the approximately
  378 MB-3.9 GB Simba/XLS-R/GeoLID/MMS artifacts for the one-resident-client role.
- [x] Reject `parakeet-rs` 0.3.6 as a same-model tag-reuse route at API and
  provenance preflight. It recognizes Nemotron language-tag tokens internally
  but strips them from every released public transcript method. Do not replace
  the checked local runtime with an unreleased fork and separate community ONNX
  export merely to recover the hidden tag.
- [x] Reject an evaluation-only token-label exposure of Nemotron's own automatic
  tags as the local switching detector. Preserving token IDs while renaming the
  exact export's 39 concrete locale rows made sherpa return hidden tags without
  a runtime fork, but three valid natural German-English-German recordings
  emitted no English tag in either final or live-partial results during their
  labeled English spans. Visibility does not create within-utterance evidence;
  keep the derivative token table and raw diagnostics private and out of the
  product.
- [x] Select and lock the accepted AmberNet 1.12.0 static QDQ INT8 resident
  detector. The product artifact, exact NeMo-compatible native frontend,
  one-thread static-ORT session, immutable 107-label order/aliases, full-logit
  abstention behavior, three-observation/`0.40`-margin policy, and user-selected
  Nemotron regional-locale intersection are versioned together. This is a
  bounded product tradeoff, not a claim that the earlier zero-false
  natural/noisy transition threshold passed. No further model search is needed
  for Phase 6 unless the accepted route fails a remaining release-blocking gate.
- [ ] Measure the accepted AmberNet/Silero route's incremental resident/private
  memory, CPU, energy, load time, window latency, and ASR interference beside
  the loaded Nemotron model on the target i5-class Windows profile. Development-
  host latency and prior Whisper measurements remain comparators, not target
  evidence.

  A private release-mode development proxy now restricts the process to eight
  logical CPUs and records aggregate metrics without retaining transcript text
  or the source path. On 38.4 seconds of source, four configured Nemotron
  threads were oversubscribed. Two threads improved the combined route to
  `0.431` RTF, 61.844 CPU-seconds, 3.74 processing-period core equivalents, and
  about 1.61 core equivalents over continuous real-time source arrival. One
  thread used about one core while processing and remained below real time at
  `0.484` RTF, but model load increased from 3.718 to 10.918 seconds. The
  executable default is now two threads as the current latency/headroom
  candidate. A source-paced follow-on accepted all 3,840 ten-millisecond frames
  without loss through the bounded 64-frame local-ASR queue, reached a 42-frame
  high-water mark, drained 864 ms after 38.4 seconds of source, averaged 1.765
  logical cores (22.066% of the eight-CPU budget), and measured 0.752 ms
  p95/6.966 ms maximum scheduler wake delay. The language path added about
  58.64 MB of private memory and left about 7.92 MB after teardown. A four-
  logical-CPU repeat also lost no frames, reached 45/64 queued frames, drained
  in 911 ms, averaged 1.773 cores during paced input, and measured 8.023 ms
  p95/45.864 ms maximum scheduler wake delay. Its accelerated combined pass
  used 3.71 of four cores. These proxies do not close the item: actual
  i5-1135G7 rendered UI/audio
  interference, energy, thermal, and sustained-session evidence remain
  required.
- [x] Implement one `LiveRuntime`-owned language engine with bounded speech-
  masked windows, deterministic smoothing, minimum evidence, hysteresis,
  lookahead, and visible primary-locale fallback.
- [x] Emit monotonic, source-bounded, revisioned `LanguageSpan` evidence without
  inventing calibrated confidence or creating another capture/session owner.
- [x] Partition bounded held source audio exactly once on confirmed switches,
  finalize/recreate the single Nemotron stream, and append finalized segment
  output without rewriting it. A pinned-model constructed English-to-Japanese
  diagnostic closed an overlapping-window retention defect, accepted the
  boundary within 250 ms, and routed all 192,000 samples exactly once;
  representative continuity proof remains below.
- [x] Prove the deterministic Rust-owner safety layer for offline switching and
  within-utterance spans: exact-once constructed handoff, short-speech flush,
  rapid/false-switch and ambiguity hold, weak/no-speech and unsupported-label
  fallback, overlapping detector retention, detector-failure drain, transactional
  holdback-exhaustion fallback, pending-state cancellation/restart isolation, and
  visible primary operation when detector artifacts are unavailable. Focused
  verification passed 123 language-related tests with eight real-model/private
  collectors intentionally ignored.
- [ ] Complete target-i5 installed-artifact offline execution, sustained-session
  restart/cancellation, rendered-UI/capture interference, energy/thermal, and
  resource-teardown evidence. Preserve the completed natural, constructed,
  related-language, noise, silence, and overlap results as-is; the failed natural
  quality target remains the Preview limitation and is not rerun.
- [x] Carry one versioned span contract into server work. Independent server
  evidence may be reconciled or rejected but cannot silently mutate the client
  decision history.

- [x] Preserve the exact Cohere baseline and its 14-language fixed contract.
- [x] Select and pin the exact DGX Spark Nemotron reference implementation,
  dependencies, hashes, license, and networkless runtime.
- [x] Implement fixed-language Nemotron requests behind the existing worker seam.
- [x] Implement explicit automatic mode only for bounded finalized utterances.
- [x] Parse and validate terminal BCP 47 tags before display text removes them.
- [x] Persist provider/model/language provenance per finalized segment.
- [x] Mark missing, malformed, disabled, or adaptation-ready tags `Unknown` and
  require visible review; never relabel them with the primary locale.
- [x] Keep one provider for the whole automatic job and preserve source order,
  cancellation, retry, and one-result publication.
- [x] Queue Qwen3-ASR-1.7B for a later provider review; do not pull its current
  vLLM streaming limitations into the Phase 6 closure gate.
- [x] Queue VibeVoice for later licensed long-form/mixed-meeting evaluation; do
  not infer language-diarization support from speaker/timestamp output.

### P6-05 — Provider-specific ASR serving gates

- [x] Freeze `nvcr.io/nvidia/vllm:26.06-py3` by immutable ARM64 digest and
  record Python 3.12, Torch/CUDA, vLLM, Transformers, audio dependencies, model
  artifacts, source adaptation, notices, and licenses.
- [x] Implement the bounded Cohere transcription adapter, exact readiness/model
  identity checks, numeric-loopback/API-key boundary, cancellation
  acknowledgement, containment fence, and checked launcher behind `BatchWorker`.
- [x] Retire the Triton backend/client/scheduler/benchmark implementation while
  retaining its private results as negative decision evidence.
- [ ] Run the full locked Cohere model through the checked vLLM image on GB10;
  prove exact reference output, residency, lifecycle, failure behavior, and
  clean teardown before comparing speed.
- [ ] Freeze representative duration/load waves and measure cold/warm latency,
  queue time, p50/p95/p99, audio-seconds/second, GPU/CPU/private memory,
  cancellation/recovery, and isolation at c1/c2/c4/c8. vLLM owns continuous
  batching; Yap must not concatenate or pad audio across requests.
- [x] Implement the separate Nemotron NeMo streaming adapter and lifecycle path
  without inheriting Cohere or retired Triton evidence.
- [ ] Prove frozen Nemotron NeMo correctness, cache/finalization semantics,
  cancellation, concurrency, memory, lifecycle, and teardown on GB10.
- [ ] Promote each runtime only on its own frozen checked-head evidence with
  rollback proof; keep Yap/Rust authoritative for jobs, sessions, routes,
  retry, admission, and validation.

Focused source-exact GB10 integration at executable commit
`fcccf21e785b116b92cd8e46150a36b9b5ee91db` ran the full locked Cohere model
through `VllmTranscriptionClient` and the full locked Nemotron model through
`NemotronNemoBatchWorker`. Both returned bounded hash-receipted results and left
no owned container or listener. The Cohere image also ran as the intended
non-root runtime identity. Receipts remain in owner-restricted evidence outside
Git. These smokes close basic checked-image/model/adapter execution only; they do
not close the still-unchecked reference, representative, percentile, resource,
capacity, failure, rollback, or promotion requirements above.

#### Retired Triton evidence

The following dirty-development evidence explains the rejected universal ASR
plane. It is historical and does not describe the current runtime plan.

Focused current-source GB10 parity on 2026-07-20 matched independent references
for Cohere fixed English, Nemotron fixed `en-US`, and Nemotron dynamic `und`.
The dynamic route also matched the complete-source utterance-plan, ordered
language-segment, and versioned source-span evidence identities. Raw results and
transcript text remain in the restricted private workspace, and exact teardown
left no matching container or network. The source was still a dirty
`4e36c3199ea9ee8d74932220504ad7391a17461a` overlay, so this closes a development
correctness gap but does not check off the frozen checked-head parity item.

Focused exact-30-second c2/c4 evidence on July 21 invalidated the current
performance candidate before a frozen matrix was spent. Cohere c2 produced one
authoritative identity across 200 requests, but c4 produced a singleton identity
that exactly matched the transient reference and a different, internally stable
batched identity with four word substitutions. Nemotron's small c2/c4 control
showed Triton scheduler batches while every backend result retained engine batch
size one; throughput stayed flat as p50 doubled. The two-model server cgroup
peaked at 7,379,800,064 bytes, teardown completed in 6,452 ms, and no owned
container, network, or matching GPU process remained. Raw outputs stay private.
The benchmark now hashes the complete authoritative result and exits nonzero on
same-input drift; parity now compares alignment as well as transcript/language.
Do not promote or spend the full frozen Triton matrix on this configuration.

### P6-06 — Timing and transcript truth

- [x] Implement the Cohere attention-alignment candidate behind an explicit
  provider/locale capability gate.
- [x] Align raw ASR text before deterministic normalization or SLM correction.
- [x] Validate monotonic, non-overlapping, source-bounded word intervals and
  transcript reconciliation.
- [x] Bound audio duration, token/word counts, runtime, memory, cancellation, and
  artifact size.
- [x] Publish an empty aligned-word list plus a typed unavailable reason when any
  gate fails; never synthesize evenly spaced words or confidence.
- [x] Keep Qwen3 ForcedAligner as a later, separately licensed/measured
  challenger. No Qwen artifact, runtime, or code enters Phase 6.

Focused verification on 2026-07-20 passed 14 Python language-span, Nemotron
worker, alignment-contract, and Cohere-alignment tests; two Rust locale-catalog
tests; and 10 primary-language/transcript-summary projection tests. These prove
the implemented contract slices, not the unchecked frozen-head resource gate.

### P6-07 — Quality, duration, and concurrency evidence

- [x] Freeze and inspect the first exact public comparator source: FLEURS
  `es_419` test at immutable revision
  `70bb2e84b976b7e960aa89f1c648e09c59f894dd`, canonical locale `es-419`,
  908 hash-verified float32 WAV cases, CC BY 4.0 legal-code identity, and a
  transcript-free source-specific parser. Keep provider code `es` separate and
  do not infer `es-US`/`es-ES` promotion from this comparator.
- [x] Run the locked Cohere FLEURS comparator privately on GB10: a 20-case
  screen followed by all 908 cases under Python 3.12.3, NVIDIA PyTorch 26.06,
  Torch 2.13/CUDA 13.3/BF16, and true batches of at most eight. Preserve only
  transcript-free aggregates in repository documentation; keep case evidence
  and the exact execution receipt in owner-restricted external caches.
- [ ] Freeze a rights/provenance registry and exact manifests for every admitted
  public or approved-private fixture.
- [x] Separate comparator-only corpora from independent promotion evidence and
  record model training/evaluation exposure.
- [ ] Add natural single-speaker mumbling, spontaneous dictation, accents,
  clean/noisy/far-field speech, silence/non-speech, terminology, names, numbers,
  units, and unspoken-continuation negatives.
- [ ] Add close/far multi-speaker meetings, overlap, speaker-attributed scoring,
  and virtual-meeting codec/jitter/drop transformations with exact source gaps.
- [ ] Cover every advertised locale individually; a macro average cannot hide a
  failed locale or broad-coverage tier.
- [ ] Run deterministic local-live endpoints at 250 ms, 500 ms, 750 ms, one
  second, the 1.12-second Nemotron chunk boundary, two seconds, and through 30
  seconds. Record shortcut-release-to-final-text latency, blank-result rate,
  leading/trailing phoneme clipping, and raw accuracy for natural quick
  corrections. Then run real-time local-live sessions from 30 seconds through
  two hours and batch inputs from 30 seconds through two hours plus the exact
  supported maximum.
- [ ] Include 15-minute continuous live, 15-minute batch, 30-second batch, and
  two-hour batch cases explicitly in the machine-validated matrix.
- [ ] Exercise c1/c2/c4/c8 compatible and mixed loads, queue/capacity edges,
  restart, retry, cancellation, and teardown.
- [ ] Lower any advertised four-hour ceiling that the frozen candidate does not
  actually prove.

The client-side deterministic duration runner now exists at the honest
`desktop-prepared-audio-frame-to-final` boundary. It consumes the exact two
local ladders from the machine plan, streams hash-verified PCM in
ten-millisecond frames through the production bounded adapter and single live
worker, cycles finalization between cases, and keeps transcripts and paths out
of evidence. It requires a full checked-head SHA plus a separately hash-bound
private suite and track manifests. A companion Python builder now derives all
15 ordered cases from the validated plan and atomically publishes the private
collection from caller-supplied vetted sources. The builder rechecks source
identity before publication, and the runtime-plan validator freezes every load
cell plus its pacing, evidence, unit, and metric semantics. Four native runner
contract tests, 13 Python builder/track tests, 16 runtime-plan tests, and the
59-test runtime lifecycle slice pass; the ignored multi-hour evidence run has
not been consumed. Physical
microphone/rendered-UI behavior, target-i5 resources, and natural
quick-correction accuracy therefore remain open and this checklist is not
promoted.

Focused Python 3.12.13 verification on 2026-07-22 passed 22 corpus-manifest
tests, including private-trust-registry enforcement. Unknown, training-exposed,
evaluation-exposed, derived, or
repeated public cases remain comparator-only; an independent claim requires a
private out-of-band-pinned registry, exact candidate/freeze/exposure artifacts,
natural source audio recorded after the frozen model where applicable, and a
case-bound scoring policy. The real rights registry and exact admitted-corpus
manifests remain open until their candidate locks, releases, licenses, hashes,
and private evidence actually exist. Schema support for a condition or suite is
not evidence that its required natural cases have been admitted or passed.

Focused verification also passed 17 FLEURS source/comparator/evaluation-runtime
tests and inspected the full private 908-case `es-419` test archive without
emitting transcripts or paths. The 178,017,600 source samples span 4.92 to 30.30
seconds per case. The private GB10 run then completed the frozen all-case Cohere
route in 61.455 measured seconds at 181.04 audio seconds per wall second with
3.5549% normalized word error rate. It used 113 batches of eight and one batch
of four under the locked Python 3.12.3/NVIDIA Torch/CUDA/BF16 runtime. This
closes one exact public comparator execution, not the real rights registry,
second fixed-locale promotion, representative corpus matrix, independent
Reality Set, Cohere vLLM parity, long-duration correctness, or concurrency/capacity
gate.

### P6-08 — Review UI and model-independent terminology hooks

- [x] Complete keyboard, focus, label, contrast, reduced-motion, and narrow-
  island behavior for language choice and review states.
- [x] Keep React as a projection of native preference/job/catalog truth; do not
  add localStorage or a second routing owner.
- [x] Preserve one tray-owned window and exact hit bounds while improving motion
  and fluidity.
- [x] Represent provider terminology/context support in benchmark evidence
  without shipping a provider-specific glossary store in Phase 6.
- [x] Score terminology retention, exact casing/acronyms, critical-token order,
  numbers, and units before promoting a challenger.

Focused verification on 2026-07-20 passed 24 language/settings/review unit
tests, both focused Chromium accessibility tests, and 6 native overlay geometry
and visible-region tests. The browser checks proved documented Arrow-key
selection, native confirmation invocation, focus return, and the 390-by-760
layout. Windows page-file pressure prevented Playwright from terminating its
Vite process tree automatically after the passing assertions; the exact child
tree was cleaned explicitly. This was focused development evidence, not the
one-time Phase 6 gate.

Focused Python 3.12.13 verification on 2026-07-20 passed 54 transcript-scorer,
private manifest/trust, and runtime-plan tests. Scorer/evidence schema v2 now
reports normalized critical-term retention and order separately from exact NFC
case/punctuation surface fidelity, with a surface-bound private policy hash.
The private inference-result lock records either no terminology context or a
provider-native source-policy/request identity with bounded counts and no term
text. The frozen runtime plan marks every current Cohere/Nemotron path as
`none` and the deferred live-server path as `unverified`; language and attention
prompts are not misreported as terminology support. Exact number/unit phrases
are covered, while general semantic medical equivalence remains explicitly
unimplemented and cannot be claimed by Phase 6.

### P6-09 — Contract migration and recovery

- [x] Complete backward-readable desktop/server migrations for new language,
  preprocessing, timing, and provider evidence.
- [x] Prove retries change only the failed stage, never source identity,
  confirmed language authority, accepted result revision, or job ID.
- [x] Prove restart and concurrent cancellation cannot resurrect stale selection,
  playback, warm-model, upload, or result-publication authority.
- [x] Bound retention and delete only verified Yap-owned derivatives; an expired
  confirmed preflight cannot be rebound to changed external source bytes.

Focused verification on 2026-07-20 passed 14 native ledger-migration tests,
29 native legacy-compatibility and app-data recovery tests, 11 native automatic-
routing persistence tests, and 35 server state/contract/recovery/admission
tests. Compatible prior records upgrade without replacing source or decisions;
invalid upgrades roll back atomically, and future schemas remain untouched and
unavailable.

### P6-10 — Review, platform debt, evidence freeze, and merge

- [x] Run exactly three read-only adversarial reviews covering maintainability,
  race/cancellation, security/privacy, dependency/license/provenance, evidence,
  and architecture boundaries; resolve every release-blocking finding before
  the immutable gate.
- [x] Classify every remaining GLib/native warning by supported target and prove
  whether it is a product defect, upstream warning, or missing platform gate;
  update pins/patches only when reproducible evidence requires it.
- [ ] Reconcile ADR 0024, the active plan, current architecture, Voice OS,
  roadmap, status, OpenAPI, and this queue with executable behavior.
- [ ] Update completion scores only after the supporting tests/runtime evidence
  exist.
- [ ] Freeze one exact Phase 6 head and run the complete local/native/server/GB10
  matrix exactly once.
- [ ] Open a focused PR, require green hosted checks on that exact head, resolve
  review findings, and merge only the checked SHA.

Focused July 20 evidence classified the recurring native warning without
speculative dependency churn. The exact locked Windows graph contained 994
package lines and zero reachable `glib` packages; the default host reverse graph
also contained none. The target-all graph reaches advisory-affected `glib`
0.18.5 through GTK/WebKitGTK/Wry under Tauri 2.11.5, so the open issue is an
upstream Linux-path warning and an explicit future Linux release gate, not a
Windows product defect. Locked Windows `cargo check` completed cleanly, and the
focused workflow contract passed 8/8 while proving CI fails closed if any
`glib` version becomes Windows-reachable. No direct pin, patch, or lockfile edit
is justified by the observed graph.

Exactly three read-only adversarial reviews then covered concurrency and
containment, architecture and maintainability, and evidence/provenance. Their
release-blocking findings were corrected before the immutable gate: NeMo
shutdown now reports containment failure without dereferencing an absent
connection; a failed provider startup closes earlier acquired workers; complete
language evidence is bound to the committed PCM extent and persistence loss is
durably degraded; production images exclude the evaluation package; artifact
no-bundle enforcement uses a strict resource allowlist; and the runtime/provenance
documents and neutral Apache license name match what executes. Focused
verification passed 68 server tests with one expected skip, 75 recording tests,
five language-evidence tests, three model-provenance contracts, and nine release-
workflow contracts. These focused results do not replace the one final Phase 6
matrix.

## Queued post-Phase-6 checkpoint

The reviewed Phase 6 merge activates
[codebase ownership and maintainability review](../queued/2026-07-18-codebase-ownership-and-maintainability-review.md).
It runs a parallel multi-subagent antagonistic review and the same
ownership/decomposition/maintainability checkpoint used after Phase 5, on a
separate refactor branch with no Phase 7 behavior. It must gate and merge before
Phase 7 starts. Phase 7 then uses the same phase -> adversarial checkpoint ->
next-phase cadence.

## Later-phase queue

### Phase 7 — Identity and ownership

- Replace the fixed development owner with token-derived `(tid, oid)` identity.
- Implement Entra/MSAL client flow, Yap API audience validation, secure token
  storage, revocation, authorization, purpose grants, and audit events.
- Prove identity reaches batch/live admission without making UI state or a model
  the authorization authority.

### Phase 8 — Meeting evidence

- Promote licensed multi-speaker/overlap evaluation sets and exact meeting
  metrics before selecting diarization components.
- Add revisioned anonymous speaker evidence, source-time word/speaker
  intersection, reconciliation, and purpose-authorized naming.
- Keep audio/transcript authority and user corrections revisioned; do not infer
  biometric identity from a display name or contact list.

### Phase 9 — Terminology, knowledge, and agents

- Write or amend an ADR for one terminology domain with personal, team, and
  organization scopes, locale, ownership, sensitivity, precedence, versioning,
  deletion, audit, and conflict rules.
- Put the user interface under Dictation/Personalization while keeping the data
  model independent of Nemotron, Cohere, Qwen, or a grammar SLM.
- Freeze one terminology snapshot per session/job so ASR, normalizer, SLM, and
  result evidence agree on the same revision.
- Compile provider-specific ASR hints/context/word boosts with explicit length,
  token, locale, injection, and unsupported-capability bounds.
- Apply deterministic exact-form normalization only where acoustic evidence and
  configured variants justify it; retain raw text and edit evidence.
- Supply the same terms to the grammar SLM as preservation constraints. The SLM
  may not silently invent, delete, or semantically rewrite critical terms.
- Project approved terminology into the Google OKF glossary/compiler with
  permission-safe retrieval; glossary/agent suggestions require user-governed
  acceptance.
- Select and benchmark the actual SGLang-compatible reasoning/tool model; prefix
  caching is useful only after correctness, isolation, memory, and multi-user
  evidence.

### Phase 10 — Production services, security, and enterprise handoff

- Integrate supervised provider-specific ASR and SGLang agent/LLM services with Yap-owned
  Rust orchestration, health, backpressure, cancellation, restart, and metrics.
- Prove authenticated multi-owner live/batch fairness, sustained capacity,
  p95/p99 SLOs, GPU/CPU memory ceilings, overload behavior, and service recovery.
- Run the next full-repository Codex Security scan privately, remediate confirmed
  findings, and keep scan identifiers/raw output out of public artifacts.
- Complete publication governance, SBOM/provenance, backup/deletion,
  observability, disaster-recovery, and deploy/rollback evidence.
- Hand DNS, certificates, ZPA, firewall policy, conditional access, production
  hosting authorization, monitoring integration, and enterprise deployment to
  the accountable IT/security owners; record unresolved items as blockers.
- Split repositories only after the deployable boundaries and access model are
  real, not to simulate enterprise separation early.

## Open decision register

| ID | Question | Evidence required before closure | Default while open |
| --- | --- | --- | --- |
| OQ-01 | Which exact acoustic-LID model and native format should power required local switching? | Immutable released artifact, compatible commercial use and explicit redistribution boundary, exact locale mapping, representative span accuracy and boundary error, packaging, CPU latency, incremental memory/energy, and ASR interference beside Nemotron | **Selected for the Phase 6 candidate:** NVIDIA AmberNet 1.12.0 static QDQ INT8, exact 29,613,392-byte graph and NeMo-compatible native frontend, three observations, `0.40` margin, full-label abstention, and user-selected Nemotron regional locales. The original natural/noisy gate failed; the product owner deliberately accepted that limitation instead of continuing model research. A distinct 58-clip holdout was consumed once after policy freeze and produced 54 correct alternates, one abstention, three wrong alternates, and zero false alternates when the primary was correct. A later frozen clean German-English product-route set preserved exact source coverage and primary fallback but detected 0/4 required natural alternate spans and matched neither boundary. Post-failure diagnosis found only five alternate labels and one above-margin observation across 68 speech-qualified alternate-region windows; earlier FP32 behavior and 322/340 versus 323/340 whole-clip parity show this is not an INT8 regression. Do not retune against the consumed set. The original aggregate, owner-restricted ACL, and hash receipt remain private; an audit-only native test revalidated the recorded aggregate without audio or model inference. All native gate collectors now use one no-clobber publisher that applies private permissions before writing evidence bytes. The artifact is verified local-import only while NGC redistribution review remains open. The local control is therefore explicit, default-off Preview behavior. Target-i5 resource/interference, lifecycle safety, and complete checked-head evidence still gate Phase 6; the completed failed natural result blocks only stronger quality claims or removal of Preview. |

The completed AmberNet trial started from original waveform, preserved the
checkpoint feature configuration and all 107 logits, treated disabled-language
scores as abstention competitors, and proved parity in the selected Python 3.12
export environment before the Rust-owned native comparator ran. That correct
execution still failed the original natural/noisy switching gate. The later
product decision accepts, rather than erases, that limitation.

The reusable Rust output contract now enforces that policy before any candidate
runtime is selected: it validates the locked full-label shape and locale map
once at component load, ranks all logits before locale filtering, abstains on
global ties or disabled winners, and preserves the user's selected region for
an accepted base language. One validated evidence-threshold object now applies
speech, absolute-score, and global-margin gates consistently to startup and
sustained switching, and malformed probability evidence is rejected at
admission. Focused classification, exact-frontend, label-map, diarization,
pipeline, lifecycle, and exact-once router tests pass. Phase-level promotion is
still withheld pending the remaining resource, representative-route, and
checked-head gates.

The approved Python 3.12/NVIDIA 26.06 base restored and exported AmberNet under a
disposable NeMo 2.7.3 overlay. That overlay cannot share the production ASR
worker environment because it resolves an incompatible Transformers/protobuf
set. The private reference/export path remains separate; only the exact static
graph and Rust-native runtime contract enter the desktop dependency graph.

| OQ-02 | Does Qwen3-ASR-1.7B replace Cohere or Nemotron for server batch? | Exact GB10 WER/CER, terminology, locale, duration, p95/p99, concurrency, memory, cancellation, timestamps/alignment, license and worker-contract parity | Keep existing gated routes; challenger only |
| OQ-03 | Which quantization is promoted per model? | Same fixtures and representative i5-class/GB10 hardware across quality, latency, throughput, memory, battery/thermal, cold load, long duration, and concurrency | Never use below Q4. Preserve the checked format unless a Q4-or-higher candidate wins its model-specific gate; current local Nemotron stays INT8. |
| OQ-04 | When should terminology ship? | ADR-defined scope/authority/privacy plus model-independent API and ASR/normalizer/SLM/OKF contract tests | Benchmark provider hooks in Phase 6; implement canonical domain in its approved later phase |
| OQ-05 | Does the accepted initial-route and sustained-switch policy pass its remaining promotion gates? | Disjoint short/long switch fixtures, false-switch rate, boundary error, ASR latency/stability, noise/silence/related-language pressure, CPU/energy, and exact-once holdback tests | Use the implemented three-observation/`0.40`-margin policy for both initial and sustained decisions over three-second windows at a 500-ms hop. Never switch from one observation; keep the primary locale on abstention or insufficient evidence. |
| OQ-06 | Does the implemented exact-once holdback handoff remain preferable after representative switch-point testing? | Source-time holdback bound, finalize/reset ordering, duplicate/drop detection, finalized-segment continuity, restart and cancellation races | Keep finalized text immutable and partition held audio once; introduce replay/provisional replacement only if evidence proves the simpler contract insufficient |
| OQ-07 | Do Cohere vLLM and Nemotron NeMo earn promotion for their own workloads? | Separate frozen parity/correctness and GB10 duration c1/c2/c4/c8 results, tail latency, memory, cancellation semantics, teardown, cache/streaming behavior, and rollback | Transformers references remain baselines; provider evidence is not transferable |
| OQ-08 | Which model powers SGLang agents? | Phase 9 task/tool quality, structured-output validity, terminology preservation, prefix-cache isolation, concurrency, latency, memory, license and governance | No production agent model selected |
| OQ-09 | What is the longest supported recording? | End-to-end exact-duration evidence including preprocessing, upload, inference, alignment, result publication, cancellation/restart and memory | Do not advertise beyond the longest frozen passing case |
| OQ-10 | Which GLib/native warnings require action? | Reproduction on the actual supported OS/toolchain, dependency provenance, upstream status, and proof of runtime/build impact | Do not churn lockfiles or add platform dependencies speculatively |
| OQ-11 | How are local spans and independent server language evidence reconciled? | Versioned contract, clock/source identity, conflict states, deterministic precedence, audit trail, retry/re-run behavior, and tests proving neither side silently erases the other | Preserve both evidence sets and require visible review for unresolved conflicts |
| OQ-12 | Should automatic detection search all 32 Nemotron locales or a user-prioritized subset? | Per-locale confusion matrix, primary/additional-language setup UX, search-cost measurements, travel/global-use cases, and unsupported-language behavior | Search the confirmed primary plus explicit additional languages first; broaden only with measured evidence and visible status |
| OQ-13 | What happens on ambiguity, silence, noise, or an unsupported local language? | False-positive/false-switch limits, unknown-state UX, manual correction, offline behavior, and recovery tests | Hold the current/primary locale, retain `Unknown` evidence, and never guess the nearest supported locale |
| OQ-14 | Which preprocessing stages execute locally, on the server, or redundantly? | Latency, privacy, offline capability, CPU/GPU cost, source-authority rules, contract size, and conflict/retry evidence | Keep capture, normalization, advisory VAD, and local live LID client-side; keep heavyweight official inference server-side; duplicate only validation with explicit reconciliation |
| OQ-15 | Which terminology slice belongs in Phase 6 versus Phase 9? | Model-independent schema/authority, privacy/scopes, exact session snapshot, provider hint support, deterministic normalization, SLM preservation, and OKF projection tests | Benchmark hooks and define the seam in Phase 6; defer canonical personal/team/org storage and agents until the approved ADR/phase |
| OQ-16 | What is the model replacement and rollback contract? | Capability/version migration, immutable artifacts, result provenance, canary/rollback, cached-model cleanup, offline fallback, and backward-readable jobs | Keep durable job/result contracts model-independent and retain the last known-good compatible artifact until replacement passes the full route gate |
| OQ-17 | When is quantization considered a Phase 6 route decision versus a Phase 10 production lock? | Exact-model quality/latency/memory/concurrency/duration comparison plus production capacity and rollback evidence | Select a checked Phase 6 candidate format; defer final fleet-wide capacity lock to Phase 10 |
| OQ-18 | How do evaluation rights and training exposure affect promotion evidence? | Corpus license/provenance, base/adaptation training lineage, comparator classification, post-freeze holdout, audio/reference hashes, and private handling | Treat known or unknown exposure as comparator-only; promotion requires provenance-locked independent evidence |
| OQ-19 | How are virtual meetings and system-loopback audio represented without losing source time? | Supported OS capture path, channel/mix identity, codec/jitter/drop fixtures, gaps, privacy, and end-to-end meeting tests | Preserve source/channel/gap evidence; do not simulate supported capture merely with clean concatenated clips |
| OQ-20 | How are very long batch inputs chunked and reconciled, and what maximum is advertised? | Exact 30-second through multi-hour runs, boundary overlap, ordering/deduplication, memory, cancellation/restart, alignment, and result publication | Advertise only the longest frozen end-to-end pass; four hours is a candidate ceiling, not a claim |
| OQ-21 | What GPU scheduling and fairness policy is safe before and after authenticated ownership? | c1/c2/c4/c8 mixed durations, queue delay, tail latency, head-of-line blocking, memory, cancellation isolation, overload, and Phase 7 owner identity | Preserve bounded development admission now; do not claim multi-owner fairness before token-derived ownership and the production capacity gate |
| OQ-22 | Which UI fluidity changes are safe to defer? | Frame/input latency, exact hit testing, one-window/state ownership, keyboard/focus/reduced-motion coverage, and user testing | Cosmetic motion may move later; invisible hit regions, duplicate ownership, inaccessible focus, and hot-path stalls remain current defects |
| OQ-23 | What battery, thermal, and CPU ceilings apply to the live-session-resident local LID? | Idle and active package power, sustained CPU, wake frequency, memory, thermal throttling, laptop battery impact, and ASR latency under representative sessions | Keep application-idle work zero or timer-free, load through `LiveRuntime`, and disable automatic switching visibly if the bounded active budget cannot be met |
| OQ-24 | How are LID/ASR artifacts installed, updated, and recovered? | Signed/hash-verified manifest, atomic install, disk bounds, interrupted update, rollback, legacy migration, no-follow/path safety, redistribution authority, and offline startup | Use explicit hash-verified download only for artifacts approved for Yap distribution; otherwise require an explicit hash-verified local import, as AmberNet does. Activate atomically, perform no implicit runtime fetch, and never delete the last known-good compatible model. |
| OQ-25 | How are medical terms, acronyms, numbers, doses, and units scored and corrected? | Raw and normalized references, ordered critical-token metrics, locale-aware number/unit equivalence, negation protection, terminology snapshot, and correction audit | Preserve raw ASR, apply only deterministic proven normalization, and never let a grammar model silently invent or alter critical meaning |
| OQ-26 | What is the authority split between raw ASR text and later grammar/SLM output? | Revisioned result schema, provenance, user-visible comparison/undo, terminology constraints, latency, hallucination/deletion tests, and retention policy | Raw transcript remains immutable evidence; polished text is a separate reversible revision |
| OQ-27 | What must work when the server, network, or a model artifact is unavailable? | Offline setup/state matrix, local fallback, queued batch behavior, retry/backoff, user copy, model-corruption recovery, and no-data-loss tests | Keep live dictation local when its verified artifacts exist, durably queue server work, and fail visibly without destructive fallback |
| OQ-28 | What diagnostic evidence can be retained without leaking private audio or transcripts? | Redaction schema, bounded metrics, event correlation, local retention/deletion, crash evidence, hosted-log review, and user controls | Record hashes, counts, timings, typed states, and model revisions; keep raw audio/transcripts and private scan output outside Git and hosted artifacts |
| OQ-29 | Which networking work is developer-owned versus an IT/security handoff? | LAN and SSH-tunnel rehearsal, authenticated API contract, threat model, DNS/certificate/ZPA/firewall/conditional-access ownership, and deployment approvals | Preserve loopback/LAN/tunnel development; record enterprise controls as explicit Phase 10 handoffs or blockers |
| OQ-30 | How do language spans interact with Phase 8 speaker diarization and overlap? | Independent source-time contracts, span intersection rules, overlap representation, revision precedence, and multilingual multi-speaker fixtures | Keep language and speaker evidence separate and composable; neither model may infer the other's identity or erase overlapping evidence |

## Closed discussion items

- Phases 1–5 and Architecture Checkpoint A are merged; do not restart them or
  duplicate landed commits.
- The custom Phase 3 installer/process-containment path was replaced by canonical
  app-data plus stock NSIS while genuine runtime process safety remained.
- Python 3.12 is the chosen NVIDIA worker baseline; Python 3.14 is not in scope.
- Parakeet is not Yap's selected ASR model.
- A later UI-polish pass is feasible because domain/state ownership is separate
  from presentation, but correctness/accessibility ownership stays gated now.
- Adaptation-ready Nemotron languages are excluded rather than advertised as a
  future fine-tuning promise.
- Automatic offline language switching, one bounded live-session-resident local acoustic-LID
  model, and within-utterance source-time language spans are required Phase 6
  outcomes. Their exact candidate and thresholds remain evidence-gated, not
  deferred to later phases.
- A full-repository security-plugin scan is deferred to Phase 10; focused review
  and private handling remain mandatory in every phase.
