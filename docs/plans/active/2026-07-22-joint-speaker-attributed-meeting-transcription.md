# Joint speaker-attributed meeting transcription plan

**Date:** 2026-07-22

**Status:** Active on `feat/joint-meeting-transcription`

**Decision authority:**
[ADR 0020](../../adr/0020-meeting-capture-diarization-authority.md) and
[ADR 0027](../../adr/0027-tiron-joint-speaker-attributed-meeting-transcription.md)

**Implementation truth:** Exact current upstream runtime and model identities,
dependency hashes, and the messy-meeting acceptance policy have executable
validators. A digest-pinned ARM64 image and thin source-bound worker execute
offline on GB10; focused short and two-window smokes pass. Explicit candidate
startup now verifies both locked model roots and the private receipt for the
checked Tiron image. Focused Python and Rust tests compose the existing
authenticated job route, three-hour admission, separate hash-bound transcript
and anonymous-speaker revisions, native publication, and History projection.
A real supported-launcher HTTP/native roundtrip remains a gate item. This is an
executable candidate contract path, not production promotion or complete Phase
8 qualification.

## Outcome

Deliver one server-authoritative, revisioned meeting-transcription path using a
pinned Tiron joint speaker-attributed ASR worker, while retaining the local
anonymous-speaker path and ASR-plus-diarization fallback. The result must remain
source-aware, bounded, replaceable, cancellable, private, and correct under
overlap and long multi-participant meetings.

## Required predecessors

- Phase 6 provider/language/timing work and its checkpoint are merged.
- Phase 7 token-derived tenant/owner authority, purpose grants, and its
  checkpoint are merged.
- The existing capture manifest, exact gaps, durable job ledger, immutable
  result revisions, and correction history remain authoritative.
- The Tiron decision does not change enterprise networking, persistent service
  supervision, or deployment ownership; those remain Phase 10 work.

## Non-goals

- Running Tiron on the i5 client.
- Replacing local Nemotron dictation or local anonymous speaker evidence.
- Claiming named biometric identity from Tiron or ECAPA output.
- Promoting every Whisper language because a tokenizer exposes its tag.
- Hiding either Tiron's eight-speaker window cap or the released harness's
  eight-speaker global cap through arbitrary chunking.
- Reimplementing or vendoring the upstream inference runtime inside Yap; the
  pinned harness runs as a third-party dependency behind a thin Yap wrapper.
- Shipping a persistent production service or enterprise deployment in Phase 8.

## Work slices

### 1. Freeze provenance and the messy-meeting gate

- [x] Create immutable model, weight, harness, ECAPA, dependency, container,
  license, and source hashes from the identities accepted by ADR 0027.
- [ ] Resolve model/adaptation lineage and the exact redistribution/deployment
  boundary before promotion.
- [x] Pin scorer implementations and document normalization, collar, overlap,
  permutation, timestamp, and speaker-count policies.
- [x] Freeze the public comparator list and mark AMI, ICSI, and NOTSOFAR-1 as
  exposure-known comparator evidence for Tiron.
- [ ] Freeze a separate private, independently adjudicated messy-meeting
  holdout before hypotheses are visible.
- [ ] Store only public-safe manifests, source identities, licenses, hashes,
  aggregate thresholds, and transcript-free receipts in Git. Keep audio,
  references, hypotheses, review records, and raw output in the private cache.

The required suite contains:

| Slice | Required pressure |
| --- | --- |
| Acoustic | close-talk, far-field, room reverb, echo, clipping, AGC, noise, silence |
| Speech | mumbling/reduced speech, false starts, interruptions, short turns, long monologues |
| Overlap | no overlap, brief overlap, sustained two-speaker overlap, three-or-more overlap |
| Attendance roster | 16/32/64 attendees with no more than eight actual talkers; no invented acoustic identities |
| Speaking roster | 1/2/4/8 and 9/16/32 distinct talkers, including late arrivals, long-gap returns, and at most eight per ordinary window |
| Window roster | 1–8 distinct talkers and explicit more-than-8 pressure inside 30 seconds |
| Transport | clean source plus fixed codec, sample-rate, jitter, drop, and gap transformations |
| Duration | short correction-sized excerpts, 15/30-minute meetings, 2-hour meeting, and the explicit 3-hour candidate maximum |
| Language | every advertised locale, fixed-language meetings, and separately scored code switching |

### 2. Run the upstream runtime behind bounded Yap ownership

- [x] Run the pinned Tiron harness as the whole-meeting runtime. It owns model
  decode, constrained-token grammar, 30-second windows, the staggered second
  pass, ECAPA linking, and its native output rendering.
- [x] Keep Yap's wrapper thin: the Python server owns verified artifact paths,
  offline execution, request isolation, transport, admission, cancellation,
  source time, and authoritative result validation; Rust independently binds
  the returned aggregate to its persisted capture request and local History.
- [x] Do not port or rewrite upstream pipeline pieces without a measured defect,
  focused regression evidence, and explicit patch provenance.
- [ ] Use fixed 30-second source-time windows and retain exact gap/source
  lineage rather than concatenating missing intervals.
- [x] Keep grammar-constrained decode on by default; reject malformed token,
  timestamp, speaker-slot, or language output.
- [ ] Run the staggered second pass by default initially and expose its
  diagnostics so the gate can compare one-pass and two-pass behavior.
- [ ] Preserve window-local speaker nodes and bounded ECAPA evidence so a later
  session reconciler does not depend on already-capped global labels.
- [x] Pin the ECAPA artifact locally and forbid implicit network fetches.
- [x] Bound request audio to three hours and bound decoded windows, segments,
  speakers, queue depth, worker resources, and result bytes.
- [ ] Measure and qualify embedding/exemplar, thread, GPU, and temporary-artifact
  bounds across the frozen duration/concurrency matrix.
- [ ] Implement typed cancellation, timeout, OOM, malformed-output,
  capacity-pressure, partial-result, and teardown outcomes.

### 3. Integrate through Yap-owned contracts

- [x] Preserve the Phase 7 principal boundary: validated token authority in
  Entra mode or the fixed principal in explicit development-loopback mode;
  neither the request nor model output can select an owner.
- [x] Contract-compose work through the existing authenticated job/router
  boundary and Rust native connector with focused server/native tests.
- [ ] Execute the same aggregate through the supported launcher, real HTTP
  route, and native publication/History path on the frozen candidate.
- [ ] Bind every result to tenant, owner, job, capture-manifest hash, model and
  harness revisions, runtime lock, language decision, and source-time plan.
- [x] Validate segment bounds, ordering, overlap groups, speaker slots, exact
  transcript reconstruction, capture binding, companion hash, and revision
  ancestry before publication/reopen.
- [x] Translate window-local slots into anonymous session speakers without
  exposing raw model token syntax to the client.
- [ ] Preserve user corrections and publish improvements as new immutable
  revisions.
- [x] Keep named identity and profile adaptation behind independent purpose
  grants; anonymous linking alone cannot publish a name.

### 4. Make participant scale explicit

- [ ] Preserve ADR 0020's dynamic session target of 32 speakers and safety
  ceiling of 64 independently from Tiron's eight slots per window and the
  pinned harness's eight-identity global cap.
- [ ] Reproduce the unmodified eight-window/eight-global baseline before
  implementing any larger-roster extension.
- [ ] Implement a separately switchable, bounded speaker-epoch reconciler that
  groups source windows at explicit timeline boundaries and cross-references
  only high-confidence anonymous embeddings across epochs.
- [ ] Freeze deterministic epoch duration, silence-boundary, overlap-guard,
  candidate-pruning, and confidence policies before inspecting hypotheses; keep
  embeddings/exemplars request-scoped and discard them after validation.
- [ ] Preserve overlap cannot-link evidence, leave ambiguous cross-epoch
  matches separate/`Unknown`, and never use the attendee list as acoustic
  evidence.
- [ ] Verify linking when a participant returns after long gaps or speaks in
  non-adjacent epochs.
- [ ] Use staggered views as evidence, not as proof that a cap-pressure region
  is complete.
- [ ] Detect a reached or plausibly exceeded local slot cap or selected-route
  global cap and publish a typed degraded/partial region.
- [ ] Retain source audio and schedule fallback/reprocessing without silently
  dropping, merging, or inventing speakers.
- [ ] Prove bounded memory and speaker state at the three-hour candidate limit
  with the separate 64-speaker synthetic pressure control.

### 5. Compare quality and runtime on the same source

- [ ] Run the pinned Tiron harness, Yap speaker-epoch extension, and
  ASR-plus-diarization fallback from byte-identical source audio and the same
  gap/timeline manifest.
- [ ] Report cpWER and time-constrained/speaker-attributed WER, overlap word
  deletion/recall, DER/JER where compatible, speaker-count error, timestamp
  error, speaker merge/split/fragmentation, and per-locale slices.
- [ ] Report cold/warm latency, RTF, VRAM/RAM, CPU, c1/c2/c4/c8 admission,
  throughput, p50/p95/p99, cancellation isolation, cross-request isolation,
  restart recovery, teardown, and duration-dependent memory slope.
- [ ] Require no failed mandatory slice. A macro average cannot offset a wrong
  tenant, leaked speaker state, failed overlap slice, unsupported advertised
  locale, missing participant, or dirty teardown.
- [ ] Require a documented product-relevant benefit over the fallback before
  production promotion; otherwise retain Tiron as an unadvertised or narrower
  route without changing result authority.

### 6. Close the phase cleanly

- [ ] Use focused unit, contract, scorer, worker, integration, and selected
  real-model checks while implementation changes.
- [ ] Freeze the exact candidate only after code, locks, corpus policy,
  thresholds, docs, and private evidence paths are ready.
- [ ] Run the complete applicable local/native/server/GB10 Phase 8 matrix once
  on that exact candidate.
- [ ] Reconcile ADR implementation scores and architecture/status claims only
  from executable evidence.
- [ ] Open one focused Phase 8 PR and merge only after checked-head hosted CI is
  green, or disclose equivalent local evidence if a hosted check is unavailable.
- [ ] After merge, run the required separate multi-lens antagonist/refactor
  checkpoint before Phase 9 begins.

## Required review lenses

- Architecture and ownership: model output never becomes job, audio, identity,
  or UI authority.
- Concurrency and isolation: no cross-request audio, language, speaker,
  embedding, cache, cancellation, or result leakage.
- Evidence and contamination: comparator exposure cannot become independent
  promotion evidence; thresholds and holdout remain frozen.
- Privacy and identity: anonymous clustering, contact labels, enrollment,
  matching, and adaptation remain separate operations.
- Maintainability: no copied monolith, phase-number runtime names, duplicate
  state owners, or implicit download/runtime configuration.

## Promotion record

The phase PR must record the exact checked head, artifact hashes, private
receipt hashes, public comparator results, independent aggregate results,
resource/capacity results, known failures, advertised locales/durations, and
clean teardown. It must say explicitly whether Tiron is promoted generally,
promoted for a narrower route, or retained as an unadvertised implementation
baseline.
