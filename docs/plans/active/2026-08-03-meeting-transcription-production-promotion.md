# Meeting transcription production promotion

**Status:** Active on `feat/meeting-transcription-production-promotion` from
merged Preview/checkpoint head `8fb511ad2fd7217a87e95ddba31d74dfa474fac2`.
The Phase 8 private matrix is historical evidence and will not be rerun. This
change uses focused development checks and one new production-promotion gate
after the candidate is frozen.

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
- [ ] Turn the frozen acceptance JSON into an executable promotion evaluator.
  It must derive its decision from the complete bounded, hash-bound private
  evidence tree: clean checked candidate, prepared immutable image receipt,
  independent review/adjudication, required scorer/slice outputs, constructed
  controls, and runtime children. Caller-authored aggregate booleans are not
  promotion evidence. Only transcript-free hashes and summaries may leave the
  private boundary.
- [ ] Qualify exact locale and duration claims, cold/warm RTF and memory,
  bounded `c1/c2/c4/c8` admission, cancellation, cross-request isolation,
  restart, teardown, and long-session stability on GB10.
- [ ] Record exactly one applicable outcome: `narrow-route-promotion` or
  `unadvertised-baseline`. Update the committed catalog only for a passed,
  reviewed outcome bound to the exact head and immutable runtime artifacts.
  `general-promotion` remains a policy-level outcome for a future broader
  decision and is not available to this meeting-only evaluator.

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

The current workstation has no configured `YAP_EVAL_CACHE`. Implementation and
public/constructed qualification may proceed, but the branch cannot honestly
record a production promotion until the independently reviewed holdout is
available through that boundary.

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

## Explicit exclusions

Persistent multi-tenant production supervision, sustained enterprise mixed-
user capacity, full Codex Security scanning, SSO policy, DNS, certificates,
ZPA, firewall policy, managed deployment, and production authorization remain
Phase 10 or explicit IT/security handoffs. This branch may validate bounded
runtime concurrency and isolation without claiming those external controls.
