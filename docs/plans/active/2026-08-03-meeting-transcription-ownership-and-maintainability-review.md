# Meeting transcription ownership and maintainability review

**Status:** Active on `refactor/meeting-transcription-maintainability` from the
Phase 8 merge `4201c5e7f1674dc0b15e76241bc308c49a5719bb`.

## Outcome

Review and simplify the merged meeting-transcription Preview without adding
Phase 9 behavior or changing the checked Tiron candidate. Preserve one owner
for server result publication, native artifact verification, History detail
loading, runtime lifecycle, and private evaluation tooling. The disabled-by-
default Preview and its Phase 8 qualification evidence remain unchanged.

## Scope and implementation

- [x] Keep generic server job/result ownership independent from the selected
  meeting worker profile; decode durable meeting bundles after restart even
  when the current runtime profile no longer admits new Tiron work.
- [x] Enforce result-companion policy before publication and accept only the
  current persisted server and native request/result schemas.
- [x] Keep request-time runtime images free of evaluation code while retaining
  Tiron scorer/corpus tooling behind the explicit private evaluation boundary.
- [x] Share silence-snapped meeting-window policy and close batch/LID worker
  lifecycles deterministically.
- [x] Make native publication and cancellation one mutation boundary, with
  deterministic cancel-after-crash and restart-between-publication-and-ledger-
  commit regressions.
- [x] Keep History catalog work metadata-bounded; hash, parse, and source-bind
  the speaker companion only when its exact result identity is selected.
- [x] Serialize selected speaker-detail reads, discard superseded requests,
  retain canonical turn identity, and paginate bounded turn projections.
- [x] Label plain-text Copy/Open actions truthfully and preserve the exact
  eight-speaker fallback-not-run disclosure.
- [x] Use behavior/owner names instead of phase-number runtime names.
- [x] Resolve the final architecture, native, and server antagonist re-review before
  the checkpoint gate.

## Evidence boundary

The Phase 8 application/runtime candidate
`1c69b61cf2902c9cfda50c6158168890974f969f`, immutable ARM64 image
`sha256:19ffb7fbadb95e8332a92ee82ed6a4554e090eeec3d5c680d133c8787dfb4330`,
and protected aggregate receipt SHA-256
`9f647b3a968ae31ab4b7f869bda160177b665747a3be5deecdde11399919e154`
remain the historical Phase 8 model and Preview qualification authority. The
checkpoint's request-time Dockerfile changed, so that old image cannot qualify
the new executable head. After code and documentation freeze, prepare, inspect,
and qualify one new immutable exact-head Tiron image as checkpoint lifecycle
evidence. Do not relabel that evidence as new model-quality, capacity, or
production-promotion qualification. Private audio, transcripts, metrics,
paths, process records, and receipts remain outside Git and hosted artifacts.
The behavior-named
[meeting-transcription maintainability checkpoint](../../runbooks/meeting-transcription-maintainability-checkpoint.md)
uses a licensed 65-second multi-window fixture to verify Tiron execution,
speaker-result publication and History rendering, active cancellation, and
exact teardown. Tiron's pinned upstream scorer remains reserved for the
separate private messy-meeting model-acceptance corpus.

## Verification and closure

- [x] Use focused TypeScript, Rust, Python, Dockerfile-contract, and lifecycle
  tests while resolving findings.
- [x] Complete the required architecture/native/server adversarial review and
  resolve every P0-P2 finding.
- [ ] On the replacement candidate, pass the canonical MSVC plus NASM desktop
  build preflight with `AWS_LC_SYS_NO_ASM` absent before creating an admission.
  Admitted head `4ab13497b19ef74ff54e3bc96b9718058f3b1e11` was consumed before
  WDIO or audio submission when stale generated AWS-LC archives from a prior
  no-assembly build contaminated the native link. Its exact remote server
  startup and cleanup passed, but that admission is failed historical evidence
  and cannot be retried or relabeled.
  Replacement head `d944670841945bed3b5c22ac9a435b3800e72118` passed the
  canonical build and exact remote preflight, then exposed a meeting-gate
  driver defect: its 65-second import correctly entered ADR 0026's explicit
  manual language review because the meeting-only server does not advertise
  AmberNet, but the driver never performed the required confirmation. The
  stopped run produced no vertical, cancellation, or independent product
  teardown receipt. The remote controller reported cleanup success, and direct
  post-stop inspection observed no retained local listener/application or
  remote listener/container/process, but those observations are diagnostic
  evidence rather than a passed product-teardown receipt. That admission is
  also failed historical evidence. The repaired driver bounds and validates
  this confirmation before either meeting path can wait on inference.
  Candidate `bbbd93f8cc05c1f6cbb2c39d119f6aec4cce3d30` passed the
  canonical build, exact image preparation, server-only lifecycle preflight,
  and admission, then failed before WDIO or audio submission because the
  operator pre-created the planned lifecycle directory. WDIO correctly rejected
  the existing destination instead of reusing it. Remote cleanup reported one
  exact pass and direct inspection found no retained local or remote owner, but
  the empty lifecycle directory contains no gate context and no vertical,
  cancellation, or teardown receipt. That admission is failed historical
  evidence. The runbook now requires every product destination to remain absent
  until its exclusive producer creates it.
- [ ] Freeze code and documentation, then run the complete applicable
  checkpoint matrix exactly once on one candidate.
- [ ] Prepare and inspect the request-time-only Tiron image for that exact head,
  then use the receipt-bound immutable image in the GB10 lifecycle lane.
- [ ] Record the candidate and private receipt identity without committing
  sensitive evidence.
- [ ] Open one focused PR and merge only after hosted checks are green on the
  reviewed exact head. If a hosted check is unavailable, disclose the missing
  check and equivalent local evidence instead of inventing a pass.
- [ ] Begin Phase 9 only after this checkpoint merges.

The full Codex Security plugin scan remains intentionally deferred to the Phase
10 enterprise gate. This checkpoint still resolves correctness, privacy,
security-boundary, provenance, lifecycle, and maintainability findings found by
ordinary implementation review.
