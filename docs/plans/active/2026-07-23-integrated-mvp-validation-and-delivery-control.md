# Integrated MVP Validation and Delivery Control

**Status:** Active delivery-order control for the remaining roadmap. This
document does not replace the
[roadmap](../../roadmap/ROADMAP.md),
[Voice OS architecture](../../VOICE-OS-ARCHITECTURE.md), accepted ADRs, or the
detailed
[audio preprocessing and language routing plan](2026-07-16-audio-preprocessing-and-language-routing.md).
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

- Phases 1–5 and Architecture Checkpoint A are merged at baseline
  `a80934d844a068110e7f86b30b6e29d35146db57`.
- Phase 6 remains on `feat/phase6-preprocessing-pipeline`.
- The last executable head before this control document is
  `16ef0827b3688b90dd66c4c560b0db8508be80f6`.
- The model-neutral Cohere vLLM and Nemotron NeMo candidate-safety lifecycle
  already passed on GB10 at `a21964c19e56648e9fddcb5200de419e59a7687c`.
  Neither provider is promoted.
- Tiron is a Phase 8 replacement candidate. Phase 6 will not run a broad Cohere
  quality, locale, long-duration, percentile, or rollback campaign.
- The full Codex Security scan remains deferred to the private Phase 10 gate.

## Phase 6 completion definition

Phase 6 is ready to merge when one clean exact head proves all of the following:

1. Local dictation remains usable with no server or default network route,
   preserves the primary-language fallback, and safely contains the optional
   AmberNet language-switching Preview.
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

Only these six actions remain on the Phase 6 critical path.

### 1. Finish connected pre-gate preparation

- [ ] Reuse the existing desktop/private-server ASR vertical-slice gate. Add
      only missing assertions needed to prove the executing Phase 6
      preprocessing and language-decision path; do not create a second
      end-to-end harness.
- [ ] Lock rights, provenance, and hashes for only the fixtures admitted to the
      Phase 6 gate.
- [ ] Run focused checks for any final assertion, accessibility, documentation,
      or gate-harness correction while the candidate is still changing.
- [ ] Remove stale completion wording. Do not add broad Cohere, Tiron, or
      AmberNet research to Phase 6.

### 2. Run one bounded offline Windows session

- [ ] While connected, verify the clean head, cached dependencies, installed
      Nemotron/Silero/AmberNet artifacts, private evidence paths, and licensed
      acoustic stimulus.
- [ ] Launch the self-contained local collectors before changing connectivity.
- [ ] Disconnect only the Windows target's Wi-Fi/default route for the actual
      offline proof. The direct no-gateway private Ethernet link may remain.
- [ ] Run the 12-cycle native resource/restart collector, the nine-case
      250-ms-through-30-second prepared-audio boundary profile, and the single
      15-minute physical-microphone/rendered-UI soak.
- [ ] Reconnect immediately after the local collectors finish, then inspect
      their private evidence while connected.

The current checked gate intentionally requires a host with no default gateway.
Do not disconnect the machine for ordinary development, server validation, or
model research. Do not weaken the offline claim by substituting an unverified
process-only block merely to keep the connection open.

### 3. Validate the integrated MVP while connected

- [ ] Run the existing checked-head desktop/private-server ASR gate through the
      real SSH-forwarded GB10 route.
- [ ] Confirm import, durable preprocessing, fixed language decision, upload,
      server processing, authoritative result publication, History rendering,
      interruption, reconnect, and cleanup in one observed workflow.
- [ ] Treat a failure here as architecture or product evidence. Fix the narrow
      cause before considering provider optimization.

### 4. Freeze the Phase 6 candidate

- [ ] Review the complete Phase 6 diff and all remaining unchecked plan items.
- [ ] Classify each item as already evidenced, required for the candidate,
      deferred to its named later phase, or an explicit external handoff.
- [ ] Reconcile ADR implementation scores, current architecture, Voice OS,
      roadmap, status, plans, OpenAPI, and runbooks with executable truth.
- [ ] Commit the clean candidate and record its exact SHA. No executable change
      may occur after this point without an explicit gate-invalidating decision.

### 5. Run the complete Phase 6 matrix exactly once

- [ ] Run the applicable frontend, native Rust, server, release, disposable
      Windows, integrated desktop/private-server, and GB10 checks on the same
      frozen head.
- [ ] Verify cancellation, retry, restart, recovery, immutable identity,
      resource bounds, model/process/listener teardown, and private-evidence
      handling.
- [ ] Record only public-safe aggregate evidence in repository documentation.

### 6. Review, PR, and merge

- [ ] Review the exact checked SHA and resulting Phase 6 diff.
- [ ] Open one focused Phase 6 PR.
- [ ] Require hosted CI, CodeQL, and applicable Windows checks to be green on
      that exact head, or explicitly disclose a genuinely unavailable check
      with equivalent local evidence.
- [ ] Resolve blocking review findings, repeat only invalidated gates when
      necessary, and merge only the reviewed green SHA.

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
