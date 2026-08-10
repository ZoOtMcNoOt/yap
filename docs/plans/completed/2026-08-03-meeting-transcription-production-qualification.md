# Meeting transcription production qualification

**Status:** Completed with `unadvertised-baseline`. PR #144 merged the sole
source-time meeting route as `b5b52bfd297edf1e95d93e120a8e59c206f7ab77`
from implementation head `bc9b57141702bb1dd6ab7df3ebc18f045fb60ee8`.
Exact qualification candidate `3ddb930268b544d2cae80d4389f12ef315b35ded`
then consumed the one Phase 8 production gate. The Phase 8 private matrix
remains historical evidence and was not rerun. [PR #150](https://github.com/mcnatg1/yap/pull/150)
passed all hosted CI and CodeQL checks at exact head
`2ab33ae6bd27b2002a539a6cb89dd55eb16eac6b` and merged as `599a0d0b`.

## Outcome

Make the existing meeting-only Tiron route eligible for an evidence-based
production decision without weakening the local fallback or claiming Phase 10
enterprise operations. Production status is earned only by the frozen
acceptance contract. Missing or failed evidence produces an explicit
`unadvertised-baseline` decision; it never silently changes the default model
catalog.

For one-speaker meetings, retain the immutable speaker-attributed result but
project the ordinary clean transcript in History. Two or more speakers retain
speaker labels, timestamps, overlap groups, and bounded pagination.

## Implementation slices

- [x] Project a one-speaker result as the canonical plain transcript without
  mutating or discarding its speaker-result companion.
- [x] Separate Tiron's eight-speaker decode-window limit from Yap's
  32-speaker session target and 64-speaker safety ceiling.
- [x] Add a source-time epoch adapter around the public whole-meeting Tiron API.
  Reconcile only unambiguous ECAPA evidence across epochs, preserve
  cannot-link constraints inside an epoch, and emit `Unknown` rather than a
  forced match after ambiguity or the safety ceiling.
- [x] Keep the released whole-meeting aggregate route as an evaluation-only
  reproduction boundary. Its strict public-result validator is shared by each
  epoch in the one product route; it is not a second runtime or fallback.
- [x] Add an executable exact-candidate qualification decision. With no
  configured private cache or independent holdout, it deterministically emits
  `unadvertised-baseline` before runtime preparation. It accepts no caller-
  selected outcome and publishes only fixed reason codes and hashes.
- [x] Evaluate whether exact locale and duration claims, cold/warm RTF and memory,
  bounded `c1/c2/c4/c8` admission, cancellation, cross-request isolation,
  restart, teardown, and long-session stability were admissible. They were not:
  the required independent holdout and trust anchors were absent, so the gate
  stopped before model or GPU execution rather than manufacturing evidence.
- [x] Record exactly one applicable outcome: `narrow-route-promotion` or
  `unadvertised-baseline`. Update the committed catalog only for a passed,
  reviewed outcome bound to the exact head and immutable runtime artifacts.
  The recorded outcome is `unadvertised-baseline`; both catalogs remain
  unchanged. `general-promotion` was removed from this meeting-only contract.

Tiron is the one server meeting-inference implementation in this promotion
closure. A failed quality, capacity, or runtime gate leaves it unpromoted and
retains the source for later reprocessing; Yap does not build or operate a
second ASR-plus-diarization stack merely to compare two implementations. The
existing local Nemotron fallback remains independent local/offline ASR and is
not a meeting diarizer.

## Evidence boundary

The public AMI/ICSI/NOTSOFAR comparator remains useful reproduction evidence
but is known-exposed and cannot promote the model. Independent promotion still
requires the private-cache holdout frozen before hypotheses, at least six
natural meetings and 7,200 seconds, allowed model-exposure evidence, two
independent listeners, and independent adjudication. Private audio,
transcripts, per-case scores, paths, process records, and detailed receipts
remain outside Git and hosted CI artifacts.

Neither the workstation nor the GB10 qualification environment had a configured
`YAP_EVAL_CACHE`. The exact gate therefore recorded
`private-cache-unconfigured` and did not claim production promotion.

## Verification and closure

- Use focused TypeScript, Rust, Python, contract, and container tests while the
  implementation changes.
- Do not rerun or relabel the consumed Phase 8 private matrix.
- After code, configuration, documentation, and model identities freeze, run
  the production-promotion gate exactly once on the checked head.
- Perform the requested architecture, native, server, race-condition, docs,
  and local-first antagonist review after implementation. Resolve every P0-P2
  correctness or security finding before the gate.
- Open a focused PR and merge only after the reviewed exact head has green
  applicable hosted checks. If hosted checks are unavailable, disclose them
  and attach equivalent non-sensitive local evidence; never invent a pass.

## Recorded closure evidence

- Qualification candidate: `3ddb930268b544d2cae80d4389f12ef315b35ded`
- Outcome: `unadvertised-baseline`
- Reason: `private-cache-unconfigured`
- Transcript-free evidence SHA-256:
  `36b45ddb929fab49ab97a215154a3fcc8e6dab099db1cbdcd6a9d047c7eaff22`
- Protected private receipt SHA-256:
  `170df14b48c4e95aeb3d54ff6f662258279c008501bbee55d2dc3d7eb75fd55f`
- The receipt is mode `0600` outside Git. No audio, transcript, private path,
  scorer output, or process ledger was committed or uploaded.
- No checked runtime image was prepared and no GPU inference ran because the
  independent-holdout admission prerequisite failed first.

## Explicit exclusions

Persistent multi-tenant production supervision, sustained enterprise mixed-
user capacity, full Codex Security scanning, SSO policy, DNS, certificates,
ZPA, firewall policy, managed deployment, and production authorization remain
Phase 10 or explicit IT/security handoffs. This branch may validate bounded
runtime concurrency and isolation without claiming those external controls.
