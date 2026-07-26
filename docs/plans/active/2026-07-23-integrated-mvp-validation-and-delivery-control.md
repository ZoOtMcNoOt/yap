# Integrated MVP Validation and Delivery Control

**Status:** Active delivery-order control for the remaining roadmap. This
document does not replace the
[roadmap](../../roadmap/ROADMAP.md),
[Voice OS architecture](../../VOICE-OS-ARCHITECTURE.md), accepted ADRs, or the
detailed
[completed audio preprocessing and language routing plan](../completed/2026-07-16-audio-preprocessing-and-language-routing.md).
It provides one short answer to: _what must happen next, what proves the system
works together, and what is deliberately deferred?_

## Delivery rule

Get the integrated MVP working and observed before optimizing replaceable
models or restructuring code around unvalidated assumptions.

Before the integrated MVP gates pass, work blocks delivery only when it affects:

- correctness, data durability, privacy, provenance, accessibility, or security;
- cancellation, retry, restart, teardown, or bounded resource safety;
- a user-visible failure in the supported local or server workflow; or
- the ability to replace a model behind the existing provider-neutral contract.

Broad model research, speculative abstractions, production capacity tuning, and
non-blocking cleanup remain recorded work, but they do not delay the next
integrated validation point. Architecture reviews may inspect broadly; their
pre-MVP change sets remain limited to concrete blockers and obvious accidental
complexity.

## Current position

- Phases 1–6 and Architecture Checkpoint A are merged at baseline
  `87c8654250cba8b9eafa5007bf719c52e4749cdf`.
- Checkpoint B is active on `chore/codebase-maintainability-review`.
- Exact executable candidate
  `a92f338546a2f8bbaded96b04f8987f0ac475c88`
  passed the frozen one-attempt 30-child Phase 6 matrix. Manifest SHA-256
  `46832f4605a92262917c0afbdeef9608270f9c56cd25a553ab6c6a5e5f7fdb52`
  plus its independently validated exact-head 30-child candidate receipt bind
  the current local/private evidence. The receipt SHA-256 is
  `74f183041082c77d05a0633202fa1052222d6a77bd9bef5ce2706546bf3e9647`.
  Hosted CI, CodeQL, and stock-NSIS passed at first attempt on final reviewed
  head `50f0f9e5e3cf288f41efa3745514dd08c9ee1929`. PR #67 merged as
  `87c8654250cba8b9eafa5007bf719c52e4749cdf`.
- Its target-client channel passed twelve paced native cycles, all nine
  250-ms-through-30-second prepared-audio cases, and the unattended 30-second
  release-mode microphone/UI lifecycle with no retained recording, model
  snapshot, Yap/driver process, or port-18765 listener.
- Its GB10 channel passed all 18 Cohere vLLM/Nemotron NeMo candidate-safety
  children with public-safe aggregate SHA-256
  `98cdc087b574f35a0e12b386a5d8c4c576a9ada548afe88101d1442868e96deb`.
  Neither provider is promoted.
- Its connected channel preserved one immutable Windows desktop job across a
  tunnel interruption, verified durable preprocessing, completed the advertised
  Cohere `en-US` route, retired the job into History, opened the verified
  server-authoritative result, and left no owned local or remote runtime.
- Runtime images are now prepared before admission from digest-pinned bases and
  pinned dependencies and emit private receipts after a second clean-head
  check. The admitted gates verify each frozen receipt hash, exact prepared
  ARM64 image ID, checked-head revision, base digest, and runtime identity by
  inspection, then launch and record that receipt-bound ID. They cannot build,
  pull, reconnect, or substitute an image.
- Tiron is a Phase 8 replacement candidate. Phase 6 will not run a broad Cohere
  quality, locale, long-duration, percentile, or rollback campaign.
- The full Codex Security scan remains deferred to the private Phase 10 gate.

## Phase 6 completion definition

Phase 6 is ready to merge when one clean exact head proves all of the following:

1. Local dictation remains usable in a fresh isolated profile with no
   configured or listening server, preserves the primary-language fallback,
   and safely contains the optional AmberNet language-switching Preview.
2. The real desktop imports a licensed recording and carries it through durable
   preprocessing, the loopback SSH-forwarded private server, ASR, result
   publication, and the History UI, including one network interruption and
   recovery.
3. The currently advertised fixed `en-US` server route satisfies contract and
   lifecycle checks. This is not a Cohere quality or production-promotion claim.
4. The guarded batch-language preflight either produces a user-confirmed
   suggestion or falls back visibly to manual selection. Phase 6 makes no broad
   AmberNet accuracy claim.
5. Every admitted fixture has an exact rights/provenance record, and private
   audio, transcripts, paths, raw metrics, and host evidence remain outside Git
   and hosted logs.
6. The complete applicable matrix runs exactly once on the frozen candidate,
   the exact PR head passes hosted CI/CodeQL and applicable Windows checks, and
   that reviewed head merges.

## Ordered Phase 6 closeout checklist

These six actions define the Phase 6 critical path. Only unchecked items remain.

### 1. Finish connected gate preparation

- [x] Reuse the existing desktop/private-server ASR vertical-slice gate. Add
      only missing assertions needed to prove the executing Phase 6
      preprocessing and language-decision path; do not create a second
      end-to-end harness.
- [x] Lock rights, provenance, and hashes for only the fixtures admitted to the
      Phase 6 gate.
- [x] Run focused checks for any final assertion, accessibility, documentation,
      or gate-harness correction while the candidate is still changing.
- [x] Remove stale completion wording. Do not add broad Cohere, Tiron, or
      AmberNet research to Phase 6.

### 2. Run one bounded automated Windows session

- [x] Verify the clean head, cached dependencies, installed
      Nemotron/Silero/AmberNet artifacts, private evidence paths, licensed
      acoustic stimulus, and absence of a listener at the admitted numeric-
      loopback server origin.
- [x] Run the 12-cycle native resource/restart collector and the nine-case
      250-ms-through-30-second prepared-audio boundary profile.
- [x] Run the 30-second unattended release-mode default-microphone/rendered-UI
      lifecycle smoke while the launcher plays the licensed stimulus through
      the current Windows output device. Keep speech/transcription assertions
      at the preceding prepared-audio boundary.
- [x] Verify the isolated app profile has no configured server, the local route
      remains authoritative, and no recording, model snapshot, process, or
      listener remains.
- [x] Inspect the private evidence without requiring a Wi-Fi state change or
      manual stimulus control.

This is the integrated-MVP boundary, not representative hardware
certification. Numeric-loopback server absence plus an isolated disabled-server
profile proves that the observed local path did not use the connected private
server; the direct native collector has no server client. A longer manual
physical-device soak and matched battery/thermal work remain required before
default-on or Phase 10 release certification. Keeping Wi-Fi connected does not
turn this evidence into an enterprise-networking or production-online claim.

### 3. Validate the integrated MVP while connected

- [x] Run the existing checked-head desktop/private-server ASR gate through the
      real SSH-forwarded GB10 route.
- [x] Confirm import, durable preprocessing, fixed language decision, upload,
      server processing, authoritative result publication, History rendering,
      interruption, reconnect, and cleanup in one observed workflow.
- [x] Treat a failure here as architecture or product evidence. Fix the narrow
      cause before considering provider optimization.

The focused run exposed and closed two integration blockers: retryable advisory
VAD evidence incorrectly prevented preserved audio from advancing, and the gate
incorrectly expected completed jobs to remain in the recoverable queue. The
fixes preserve the documented owners: required language stages remain
fail-closed, advisory VAD remains non-authoritative, and verified History plus
the immutable result artifact are terminal truth.

### 4. Freeze the Phase 6 candidate

- [x] Review the complete Phase 6 diff and all remaining unchecked plan items
      with three independent read-only adversarial reviewers.
- [x] Classify each item as already evidenced, required for the candidate,
      deferred to its named later phase, or an explicit external handoff.
- [x] Reconcile ADR implementation scores, current architecture, Voice OS,
      roadmap, status, plans, OpenAPI, and runbooks with executable truth.
- [x] Commit the repaired clean replacement and record its exact SHA. Executable
      candidate `a92f338546a2f8bbaded96b04f8987f0ac475c88` is frozen. No
      executable change may occur after this point without an explicit
      gate-invalidating decision.
- [x] Complete a focused three-reviewer read-back of the repairs before freezing
      that replacement.

Candidate `97b63be46b05dffa21595f2fd081b8467bb95798` passed its admitted
matrix, but final review found concrete restart/cleanup, normative OpenAPI,
hosted-closure, evidence-bound, and phase-derived persisted-vocabulary defects.
Executable repair explicitly invalidated that SHA as merge authority. Its
receipt remains historical evidence and is not reused for the replacement.

Replacement `0ed2037dbbb8c3df9350dbc37aeddc633f567a40` also passed its
admitted matrix, but hosted Windows checks exposed that release-contract test
fixtures inherited GitHub Runner's redirected temporary parent. The
test-only canonical-temporary-root correction therefore invalidated that SHA
as merge authority. Replacement
`c82fe47a683dabd72231ffca377095ff16f2d4f5` rebuilt the checked runtime images
and passed the admitted target-client, GB10, connected, teardown, and complete
30-child channels. Hosted Windows then reported 3.015 seconds against the old
two-second assertion. Because that fixture could exit naturally after 2.5
seconds and the marker assertion followed the failed timing assertion, the run
did not prove forced termination or grandchild absence. The corrected contract
delays natural exit to 15 seconds, requires termination within ten seconds, and
then verifies the independent grandchild-survival marker remains absent. That
executable correction invalidated `c82fe47...`. Candidate
`72c089f42c1358f4f0b86c793af39a8e762d6137` then passed the target-client and
18-child GB10 channels but failed connected readiness because its controller
selected an AmberNet directory with unexpected artifacts; cleanup passed and
the admission remains failed. Exact candidate
`a92f338546a2f8bbaded96b04f8987f0ac475c88` verified the precise AmberNet model
root, rebuilt all three checked runtime receipts, and reran every admitted
channel and all 30 children without reusing or relabeling prior evidence,
including the corrected termination and grandchild-absence contract.

The same review also recorded non-blocking Checkpoint B inputs without pulling
them into this phase: remove the server worker-to-engine dependency cycle,
restore the desktop language-to-STT dependency direction under one composite
routing-revision owner, and consolidate duplicate server request fixtures. The
Phase 6 ownership-map omission was documentation truth and is corrected here,
not deferred.

### 5. Run the complete Phase 6 matrix exactly once per frozen replacement

- [x] Run every replacement-candidate child frozen by the machine-validated
      [integrated preprocessing and language-routing gate](../../runbooks/integrated-preprocessing-language-routing-gate.md)
      on the same frozen head.
- [x] Validate first-attempt hosted CI/CodeQL/disposable-Windows closure on
      docs-only review head
      `cee13f819a85417ea43a3c63e263be85f0570838`.
- [x] Validate the same hosted closure on final reviewed head
      `50f0f9e5e3cf288f41efa3745514dd08c9ee1929`.
- [x] Verify cancellation, retry, restart, recovery, immutable identity,
      resource bounds, model/process/listener teardown, and private-evidence
      handling.
- [x] Record only public-safe aggregate evidence in repository documentation.

### 6. Review, PR, and merge

- [x] Review the exact checked SHA and resulting Phase 6 diff.
- [x] Open one focused Phase 6 PR: [PR #67](https://github.com/mcnatg1/yap/pull/67).
- [x] Require hosted CI, CodeQL, and applicable Windows checks to be green on
      review head `cee13f819a85417ea43a3c63e263be85f0570838`.
- [x] Require those checks to be green again on final reviewed head
      `50f0f9e5e3cf288f41efa3745514dd08c9ee1929`.
- [x] Resolve blocking review findings, repeat only invalidated gates when
      necessary, and merge only the reviewed green SHA. PR #67 merged as
      `87c8654250cba8b9eafa5007bf719c52e4749cdf`.

## What is deliberately deferred

The following work is not required to close Phase 6:

- broad Cohere quality, locale, long-duration, percentile, capacity, or rollback
  qualification;
- deciding whether Tiron replaces meeting-only Cohere work, broader batch work,
  or neither;
- representative low-end battery and thermal certification for enabling the
  local language-switching Preview by default;
- production quantization selection, sustained mixed-user capacity, or service
  supervision;
- non-blocking architecture cleanup and speculative abstraction work; and
- the full-repository Codex Security scan.

## Roadmap after Phase 6

| Order | Deliverable | Validation before moving on |
| --- | --- | --- |
| Checkpoint B | Broad read-only inspection with exactly three independent antagonistic reviewers; narrow fixes for concrete correctness, ownership, resource, privacy, security, naming, or comprehensibility blockers. Record non-blocking optimization instead of turning the checkpoint into an open-ended rewrite. | Focused checks, one exact checkpoint matrix, reviewed PR, merge. |
| Phase 7 | Authenticated identity/access seam, token-derived ownership, purpose grants, authorization/revocation, and multi-owner contract behavior. Use synthetic/mock identity for developer-owned validation until IT provides an approved Entra environment. | Integrated authenticated client/server workflow plus phase gate, PR, and merge. |
| Post-Phase-7 checkpoint | Review the new identity boundary and affected earlier owners. Fix blockers; defer optional polish. | Checkpoint gate, PR, and merge. |
| Phase 8 | Implement the pinned Tiron meeting baseline and model-independent speaker/result contracts. Compare Tiron with only the still-relevant fallback/provider routes on frozen meeting and long-batch controls. | This is the model/meeting architecture decision point: keep, replace, or narrow providers from observed end-to-end evidence. |
| Post-Phase-8 checkpoint | Reconcile the architecture with the measured model decision and remove obsolete implementation paths. | Checkpoint gate, PR, and merge. |
| Phase 9 | Governed terminology, OKF compilation, permission-safe retrieval, agents/RAG/MCP, and evidence-selected SGLang model. | Permission-isolated integrated workflows, phase gate, PR, and merge. |
| Post-Phase-9 checkpoint | Review knowledge, tool, model, and permission boundaries. | Checkpoint gate, PR, and merge. |
| Phase 10 | Production supervision, mixed-user capacity, observability, release governance, full maintainability audit, private full security scan, deployment evidence, and explicit IT/security/network handoffs. | Final exact-head matrix, hosted checks, reviewed PR, and merge; external enterprise conformance remains a named handoff when unavailable. |

The system is not re-architected merely because a benchmark is interesting.
Architectural assumptions change only after the relevant integrated validation
shows that the current boundary is wrong, too slow, unsafe, or unnecessarily
complex.
