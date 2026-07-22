# ADR 0027: Tiron joint speaker-attributed meeting transcription

**Date:** 2026-07-22
**Status:** Accepted (canonical Phase 8 server baseline; production promotion pending)
**Amends:** [ADR 0014](0014-server-tier-compute-topology.md), [ADR 0020](0020-meeting-capture-diarization-authority.md), and [ADR 0025](0025-provider-specific-asr-serving.md)
**Implementation status:** Decision and immutable upstream source identities are documented. No Tiron worker, dependency lock, meeting scorer, production result path, or GB10 qualification evidence exists in Yap yet.

## Context

Yap's accepted meeting architecture separates source-aware capture, transcript
authority, anonymous speaker evidence, and purpose-authorized identity. It did
not yet select the server model that produces the first authoritative
speaker-attributed transcript.

A conventional pipeline transcribes a mixed recording, estimates speaker
turns separately, aligns words, and intersects the two outputs. That remains a
useful fallback, but errors compound when people overlap: the ASR may delete one
speaker before a later diarizer has any words to attribute, and independent
boundaries require more reconciliation code.

Trelis released `Trelis/tiron` on 2026-07-21. The model adapts the Whisper
large-v3 architecture to emit timestamp and speaker tokens together. Its
reference harness decodes fixed 30-second windows, supports up to eight
window-local speaker slots, and links those slots across a meeting with ECAPA
embeddings. A staggered second pass is enabled by default to calibrate linking
for each meeting and prevent speakers known to overlap from being merged.

This is a promising match for Yap, but it is new evidence, not an already
qualified product runtime. Published AMI, ICSI, and NOTSOFAR-1 cpWER results are
self-reported and English-only. The model card does not disclose complete
training/adaptation lineage, and the reference harness does not pin Torch,
SpeechBrain, or most other runtime dependencies. No published result establishes
DGX Spark latency, memory, concurrency, cancellation, long-session stability,
or Yap's multilingual requirements.

The model's eight-speaker limit is local to one 30-second inference window. It
must not be confused with the number of people in a meeting. ADR 0020 retains a
dynamic session roster with an initial target of 32 anonymous speakers and a
safety ceiling of 64.

## Decision

### 1. Select Tiron as the Phase 8 server development baseline

Phase 8 will implement joint speaker-attributed meeting transcription around
`Trelis/tiron` first. This is the chosen server development baseline, not one
more unprioritized research candidate.

The selection is deliberately narrow:

- Tiron is server-only and processes meeting recordings on the private GPU
  tier.
- It does not replace local Nemotron dictation, the local anonymous-speaker
  baseline, or the Phase 6 Cohere/Nemotron provider routes.
- It does not own durable job identity, capture history, user corrections,
  authentication, admission, cancellation, or result publication.
- It is not advertised or made authoritative until the frozen Phase 8 gate
  passes.

Rust remains the orchestration and validation owner. Tiron is an isolated,
provider-specific Python worker behind Yap's model-independent meeting-result
contract.

### 2. Pin upstream identity before integration

The initial source lock is:

| Artifact | Immutable identity |
| --- | --- |
| Model | `Trelis/tiron` revision `aed145c7d6cc5cbd381a0e87b6d0089bcc76a1fc` |
| Weight | 3,087,229,512 bytes; SHA-256 `921e078a8e89000ccb467c5f9bce8a46c9e484c52b63e3ddddaa571c34306a2e` |
| Reference harness | `TrelisResearch/tiron` revision `5b3766ac64ff3a8d98443e0a850d1ce569952520` |
| Public metadata | Apache-2.0 for the model repository and harness |

Phase 8 must create a complete runtime lock before executing the worker. It
must pin and review the model, harness, ECAPA checkpoint, Torch, Transformers,
SpeechBrain, audio libraries, transitive native dependencies, and every
applicable license. Runtime network downloads are forbidden. Python 3.12 and
DGX Spark GB10 are the initial qualification environment unless a later ADR
changes the checked NVIDIA worker baseline.

Upstream code may be wrapped or selectively adapted with provenance and
attribution. Yap will not paste the reference harness's large pipeline modules
into its Rust or server domains unchanged. The Phase 8 implementation should
keep decoding, linking, scoring, and Yap orchestration as separately testable
owners.

### 3. Preserve source time and publish only validated revisions

The worker receives bounded views over the retained canonical source; it never
becomes the audio source of truth. Initial behavior follows the released model:

1. derive fixed 30-second windows with exact source offsets and explicit gaps;
2. use grammar-constrained decoding for speaker/timestamp token validity;
3. run the released staggered second pass unless measured evidence rejects it;
4. link window-local slots into anonymous session speakers;
5. return segments, source timestamps, window-local speaker evidence,
   language, and degradation diagnostics to Rust; and
6. let Rust validate bounds, ordering, overlap, capture-manifest identity,
   model provenance, and result revision before publication.

Model segment timestamps are not silently promoted to word-level alignment.
Words receive source-time intervals only through a separately validated timing
path. Named identity remains a later, purpose-authorized reconciliation step;
an ECAPA similarity cannot manufacture a person's name.

### 4. Treat window capacity and meeting capacity separately

Tiron may represent at most eight distinct speaker slots in one 30-second
decode window. A meeting may still contain 15, 32, or more participants when
only a subset speaks in each window; the cross-window linker is responsible for
reusing stable session identities as people leave, return, or first speak late.

Phase 8 must explicitly test and report:

- meetings with more than 15 global speakers;
- late arrivals and long gaps before a speaker returns;
- windows containing one through eight distinct talkers; and
- pressure cases with more than eight distinct talkers inside one window.

Staggered windows provide useful cross-evidence but do not prove that an
over-capacity region was decoded completely. Reaching or plausibly exceeding
the local cap produces a typed degraded/partial region and preserves source
audio for fallback or reprocessing. Yap must not merge, drop, or invent a
speaker merely to stay under the cap.

### 5. Promote against a frozen messy-meeting acceptance suite

The Phase 8 corpus manifest, scoring policy, slice thresholds, and baseline/
fallback configurations are frozen before Tiron hypotheses are inspected. The suite has
two evidence classes:

- **Public comparators:** immutable, rights-reviewed subsets of AMI, ICSI, and
  the open NOTSOFAR-1 material. Because Tiron publishes results on those
  corpora, they diagnose regressions and reproduce upstream claims but cannot
  independently promote the route.
- **Independent acceptance evidence:** a sealed, license-clear,
  Yap-adjudicated messy-meeting holdout whose source audio, transcript, speaker
  timeline, known defects, reviewer disagreement, transformations, and hashes
  are retained in the private evaluation cache. Private audio, references,
  hypotheses, and raw receipts never enter Git or hosted CI.

The suite covers close-talk and far-field audio, natural and constructed
overlap, interruptions and sub-1.6-second turns, mumbling and disfluency,
noise/reverb/echo/clipping, virtual-meeting codec/jitter/drop transformations,
late arrivals, repeated speakers across distant windows, silence, and long
meetings. It includes one/two/four/eight-speaker windows, more-than-eight
pressure windows, more-than-15-person sessions, and every locale the route
would advertise.

Accuracy reporting includes at least cpWER, time-constrained or
speaker-attributed WER as appropriate to the reference, overlap-region
deletion/recall, DER/JER where compatible, speaker-count error, timestamp
error, speaker fragmentation/merge error, and per-locale results. Runtime
reporting includes cold/warm latency, real-time factor, VRAM/RAM, c1/c2/c4/c8
admission and tail latency, cancellation, cross-request isolation, restart,
teardown, and long-meeting memory/identity stability.

Production promotion requires every frozen absolute gate, no failed required
slice, and a documented product-relevant improvement over Yap's separately
scored ASR-plus-diarization fallback. A favorable macro average cannot erase a
failed overlap, locale, capacity, isolation, or lifecycle gate.

### 6. Keep the fallback and replacement boundary real

The accepted ASR-plus-diarization design remains a fallback for unsupported
locales, capacity pressure, worker failure, and comparative evidence. It also
keeps the architecture replaceable if Tiron later loses on quality,
maintainability, licensing, or runtime cost.

The canonical output remains Yap's revisioned transcript/speaker contract, not
Tiron token syntax or ECAPA cluster IDs. Replacing the model must not rewrite
capture history, durable ownership, user corrections, or client UI state.

### 7. Preserve the ordered roadmap

This ADR authorizes planning and Phase 8 implementation only. It adds no Tiron
runtime to the active Phase 6 branch and does not pull Phase 8 into Phase 7.
Phase 7 supplies authenticated ownership and purpose-grant foundations. Phase
8 implements and qualifies meeting inference. Phase 10 owns persistent
supervision, sustained mixed-user capacity, full security scanning, external
networking, and enterprise deployment handoffs.

## Consequences

### Positive

- Joint decoding can retain words from overlapping speakers that a flat ASR
  transcript may delete before downstream diarization.
- Speaker, timestamp, and transcript evidence originate from one decoding
  grammar, reducing fragile cross-model intersection surfaces.
- Window-local identities remain compatible with ADR 0020's larger dynamic
  session roster and immutable result revisions.
- The chosen baseline focuses Phase 8 engineering while preserving a real
  fallback and model-replacement seam.

### Negative

- Tiron is a very new release with limited adoption and no independent Yap
  reproduction yet.
- Two-pass decoding and ECAPA linking add latency, memory, dependency, and
  lifecycle work beyond a plain Whisper invocation.
- Published quality evidence is currently English-only, while Yap requires
  global language evidence.
- Eight window-local speaker slots create a real degraded-result case that the
  product and scorer must expose.
- The reference harness is not a production service and requires substantial
  decomposition, dependency locking, concurrency control, and cancellation
  hardening.

### Neutral

- Local offline meeting evidence continues to use the lightweight anonymous
  path selected by ADR 0020; Tiron is not an i5 client dependency.
- Purpose-authorized named identity remains separate from anonymous speaker
  linking.
- Public benchmark wins are useful comparator evidence but do not replace the
  independent messy-meeting holdout.

## Alternatives considered

### Keep ASR plus diarization as the only server path

Rejected as the primary Phase 8 approach. It remains the fallback, but it
cannot recover a second speaker's words after mixed-speech ASR has already
deleted them and it requires more cross-model alignment.

### Run Tiron on the client

Rejected for the initial product. The multi-gigabyte model, two-pass decode,
and ECAPA dependency do not fit the accepted i5 local resource boundary.

### Adopt the hosted Trelis service

Rejected as the architecture baseline. Yap's server profile requires
org-controlled compute and explicit enterprise networking/approval; a hosted
endpoint cannot silently replace that trust boundary.

### Continue model research without selecting a baseline

Rejected. Tiron is sufficiently aligned with the Phase 8 problem to focus the
implementation. Evidence still controls production promotion and can later
replace the model behind the stable contract.

## Implementation sequence

1. Freeze the messy-meeting manifest, rights/provenance ledger, scorer versions,
   thresholds, and private holdout before model output is revealed.
2. Lock the complete Tiron/ECAPA/Python 3.12 runtime and reproduce upstream
   public-comparator behavior on GB10.
3. Implement a bounded provider-specific worker with cancellation, teardown,
   capacity diagnostics, and no runtime downloads.
4. Add the Rust adapter and validated immutable meeting-result revision path.
5. Run focused contract/runtime work while developing, then the complete
   frozen Phase 8 matrix once.
6. Perform the required post-phase adversarial/refactor checkpoint before
   Phase 9 begins.

## References

- [Trelis/tiron model card](https://huggingface.co/Trelis/tiron)
- [TrelisResearch/tiron reference harness](https://github.com/TrelisResearch/tiron)
- [ASR evaluation corpus and runtime matrix](../research/2026-07-17-asr-evaluation-corpus-and-runtime-matrix.md)
- [Source-aware diarization design](../specs/source-aware-diarization.md)
- [Testing strategy](../specs/testing-strategy.md)
