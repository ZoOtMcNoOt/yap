# Joint speaker-attributed meeting transcription plan

**Date:** 2026-07-22

**Status:** Completed Preview delivery. Reviewed head
`ec4e4ab46234c35555136a75da530c6d73a042d8` passed hosted checks and
[PR #142](https://github.com/mcnatg1/yap/pull/142) merged as
`4201c5e7f1674dc0b15e76241bc308c49a5719bb`. The separate
[meeting-transcription ownership and maintainability review](../active/2026-08-03-meeting-transcription-ownership-and-maintainability-review.md)
is active before Phase 9.

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
Exact application/runtime head
`1c69b61cf2902c9cfda50c6158168890974f969f` passed one supported-launcher
development-loopback roundtrip from licensed client import through the real HTTP
route and pinned upstream Tiron harness to a separately hash-bound speaker
result and speaker-attributed History UI. It also passed the one admitted
local/native/server/GB10 Preview matrix, including the exact immutable image
`sha256:19ffb7fbadb95e8332a92ee82ed6a4554e090eeec3d5c680d133c8787dfb4330`
and a real two-window GB10 run. Reviewed descendant
`9ff06d7d3f66faea92276000d58fa9b94154682b` changes only test/gate mechanics;
it does not change the shipped product, runtime, or image. The protected
aggregate receipt remains outside Git and has SHA-256
`9f647b3a968ae31ab4b7f869bda160177b665747a3be5deecdde11399919e154`.
This qualifies the disabled-by-default Preview baseline, not production
promotion. The executing contract conservatively makes an exactly-eight-label
upstream aggregate terminal `partial`, binds one meeting-global saturation
record to the complete source, and states that fallback reprocessing was
recommended but not run.

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

## Delivery boundary

The merged branch closes the smallest honest Phase 8 product layer: an explicitly
enabled, meeting-only Preview candidate that is absent from the committed
default catalog. It does not production-promote Tiron. The remaining Preview
promotion work is separate from the active post-phase maintainability
checkpoint. The typed global-cap behavior, three-lens adversarial review,
supported exact-candidate roundtrip, one admitted Phase 8
local/native/server/GB10 matrix, and execution-truth reconciliation are closed.

The private holdout, public-score reproduction, larger-roster speaker epochs,
exact window-cap localization, automatic fallback execution, and broad
accuracy/resource/concurrency promotion campaign remain required before a
future production-promotion decision. They are recorded below but are not
blockers to merging the disabled-by-default Preview baseline.

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
- [x] Store only public-safe manifests, source identities, licenses, hashes,
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
- [x] Publish a typed terminal `partial` result when the public upstream
  aggregate exposes exactly eight global speaker labels; bind one meeting-wide
  degradation record to the exact source and say fallback was not run.
- [ ] Qualify the broader timeout, OOM, window-cap, fallback-execution, and
  resource-pressure outcome matrix before production promotion.

### 3. Integrate through Yap-owned contracts

- [x] Preserve the Phase 7 principal boundary: validated token authority in
  Entra mode or the fixed principal in explicit development-loopback mode;
  neither the request nor model output can select an owner.
- [x] Contract-compose work through the existing authenticated job/router
  boundary and Rust native connector with focused server/native tests.
- [x] Execute the same aggregate through the supported launcher, real HTTP
  route, and native publication/History path on the frozen candidate.
- [x] Bind every result to tenant, owner, job, capture-manifest hash, model and
  harness revisions, runtime lock, language decision, and source-time plan.
- [x] Validate segment bounds, ordering, overlap groups, speaker slots, exact
  transcript reconstruction, capture binding, companion hash, and revision
  ancestry before publication/reopen.
- [x] Translate the upstream meeting-global anonymous labels into canonical
  session-speaker IDs without exposing raw model token syntax to the client.
- [ ] Translate or reconcile window-local speaker evidence only after an
  accepted upstream evidence API exposes it; the current public aggregate does
  not.
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
- [x] Detect the observable selected-route global cap and publish a typed
  meeting-scoped partial result; do not invent unavailable source regions.
- [ ] Obtain exact local-window saturation evidence from an accepted upstream
  boundary before claiming window-cap localization.
- [ ] Retain source audio and schedule fallback/reprocessing without silently
  dropping, merging, or inventing speakers.
- [ ] Prove bounded memory and speaker state at the three-hour candidate limit
  with the separate 64-speaker synthetic pressure control.

### 5. Deferred production promotion: compare quality and runtime on the same source

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
  production promotion; otherwise retain Tiron as an explicit Preview or
  narrower route absent from the committed default catalog, without changing
  result authority.

### 6. Close the phase cleanly

- [x] Use focused unit, contract, worker, integration, and selected real-model
  checks while implementation changes.
- [x] Freeze the exact Preview candidate only after code, locks, docs, and
  private evidence paths are ready; promotion-corpus thresholds remain
  deferred promotion work.
- [x] Run the complete applicable local/native/server/GB10 Phase 8 matrix once
  on that exact candidate.
- [x] Reconcile ADR implementation scores and architecture/status claims only
  from executable evidence.
- [x] Open one focused Phase 8 PR and merge only after checked-head hosted CI is
  green. Reviewed head `ec4e4ab46234c35555136a75da530c6d73a042d8`
  passed hosted CI and CodeQL before PR #142 merged as `4201c5e7...`.
- [x] After merge, activate the required separate
  [multi-lens ownership and maintainability checkpoint](../active/2026-08-03-meeting-transcription-ownership-and-maintainability-review.md)
  before Phase 9 begins.

The frozen implementation candidate is
`1c69b61cf2902c9cfda50c6158168890974f969f`. Its runtime-preparation,
supported native roundtrip, and GB10 two-window receipt hashes are respectively
`957b4b402320eab70b4dbd474467ec6f58322fc5fc3f2eb9edc2b51021a74abd`,
`cfa0e8e6348437805d1719406656bb6d8e1a09164e2295f1ec913554c231fcab`,
and `fddc9c8f63a7cdf1f11ec04ad6f9bfd24f2f11fe0f6e33965fc2cc8b6072eaa4`.
The protected aggregate receipt binds those artifacts, the exact image, the
passed lane counts, and runner-only descendant `9ff06d7d...`; no raw audio,
transcript, private path, or command log is committed.

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

The Phase 8 Preview PR must record the exact checked head, artifact hashes,
private receipt hashes, focused and complete gate evidence, known failures,
enabled locale/duration bounds, and clean teardown. It must explicitly say
that Tiron remains an operator-enabled Preview candidate, absent from the
committed default catalog and not production-promoted. A later promotion PR
must additionally record public comparator results, independent aggregate
results, resource/capacity results, and an explicit meeting-only,
broader-replacement, or rejection decision.
