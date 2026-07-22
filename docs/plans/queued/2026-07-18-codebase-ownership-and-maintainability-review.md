# Codebase Ownership and Maintainability Review Plan

**Status:** Queued and not yet active. Activate only after the focused Phase 6 PR passes its
one-time exact-head gate, hosted review, and merge. This plan does not authorize
Checkpoint B work in the Phase 6 worktree.

**Planned branch:** `refactor/codebase-ownership-and-maintainability`

**Base:** The reviewed Phase 6 merge commit, recorded when Phase 6 closes.

**Scope:** Review and simplify the complete executable Phase 1–6 system without
adding Phase 7 identity, authorization, or enterprise-network functionality.
Mirror Architecture Checkpoint A's evidence-driven ownership, decomposition,
maintainability, and documentation standard while adding the Phase 6 language,
preprocessing, evaluation, model-serving, timing, and GPU-resource surfaces.

## Governing outcomes

1. One explicit owner for every durable state, runtime lifecycle, model pool,
   language decision, source-time span, stage attempt, and result revision.
2. Correctness, security, privacy, provenance, cancellation, and resource-
   containment findings are resolved before dependent cleanup.
3. No duplicate UI, window, capture, language, job, connector, retry, result,
   model, preprocessing, or evaluation authority.
4. Dead, superseded, speculative, and YAGNI machinery is removed rather than
   moved behind a new generic abstraction.
5. Mixed or oversized production and test surfaces are decomposed or receive a
   written cohesion justification. Checkpoint A's 350-line inspection threshold
   remains a review trigger, not an automatic refactor quota.
6. Dependency direction is one-way and trust boundaries are bounded, redacted,
   fail-closed, and consistent with the ADR ownership map.
7. Efficiency claims are backed by measurement or demonstrable work removal;
   concurrency, memory, GPU residency, cancellation, and teardown remain
   explicit evidence rather than inferred benefits.
8. Current, normative, active, completed, historical, runbook, roadmap, and
   evidence documents remain distinguishable and cross-linked. The Voice OS
   architecture remains the long-term frame of reference and is not silently
   rewritten.
9. One exact checkpoint head passes the complete applicable matrix once and
   merges through a focused reviewed PR before Phase 7 begins.
10. Runtime filenames, symbols, configuration, container identities, fixtures,
    and contract revisions name their behavior and owner. Phase numbers remain
    only in roadmap/delivery prose, immutable historical provenance, branch
    lineage, or explicitly documented backward-compatibility tokens; they are
    not runtime or test-artifact identities.

## Multi-subagent antagonistic review

After the Checkpoint B branch is created, the primary agent will launch exactly
three independent read-only reviewers in parallel. Each reviewer must use repository
state, executable contracts, and observed behavior rather than trusting status
claims. At minimum, the review covers:

- state/persistence/retry/restart correctness and backward compatibility;
- concurrency, race, cancellation, backpressure, retention, process/container,
  GPU/CPU memory, listener, and teardown failure paths;
- security, privacy, path/file handling, bounded inputs/outputs, redacted
  observability, dependency/license/provenance, and trust-boundary behavior;
- architecture ownership, dependency direction/cycles, duplicate authority,
  module cohesion, test-harness design, dead code, speculative abstractions, and
  human comprehensibility; and
- UX/accessibility projection, keyboard/focus/reduced-motion behavior, visible
  limitations/errors, and the single tray-owned window boundary.

Reviewers report concrete evidence with file/line anchors, severity, executable
failure scenarios, and proposed verification. They do not edit concurrently
during discovery. The primary agent deduplicates and adjudicates findings before
ordered implementation begins.

## Quality lenses

Use the same non-certification review lenses as Checkpoint A: ISO/IEC 25010,
ISO/IEC 5055, ISO/IEC 25023, NIST SSDF, and CMU SEI scenario-driven architecture
evaluation. Add Phase 6-specific scenarios for language ambiguity, source-time
span continuity, provider/model replacement, long recordings, dynamic result
size, vLLM continuous-batching isolation, NeMo stream/cache state, cancellation,
GPU pressure, model teardown, private evaluation evidence, and unavailable timing.

## Ordered checkpoint slices

- [ ] Create the checkpoint branch from the reviewed Phase 6 merge and record
      the exact base.
- [ ] Inventory changed modules, tests, docs, dependencies, generated/runtime
      artifacts, model locks, evaluation manifests, and Git/object state.
- [ ] Run the parallel antagonistic review and publish a public-safe findings
      register, ownership map, file inventory, and verification plan.
- [ ] Resolve correctness/security/privacy/provenance/resource findings before
      structural refactors that depend on them.
- [ ] Remove duplicate/dead/speculative machinery and decompose mixed owners,
      oversized modules, and catch-all test harnesses without adding Phase 7
      behavior.
- [ ] Reconcile architecture, ADR implementation status, current status,
      roadmap, runbooks, active/completed plans, and evidence classifications
      with the refactored executable system.
- [ ] Run focused verification throughout each affected slice.
- [ ] Freeze one checkpoint candidate and run the complete applicable local,
      native, server, release, disposable-Windows, and GB10 matrix exactly once.
- [ ] Open a focused PR, require green exact-head hosted checks and review, and
      merge only the checked SHA.

## Phase 7 cadence

Phase 7 begins only after Checkpoint B merges. Its implementation remains on a
separate phase branch and uses the same cadence: focused development checks,
normal in-phase review, exact-head phase gate and reviewed PR, followed by a
separate antagonistic architecture/refactor checkpoint before Phase 8. Each
checkpoint stays behavior-preserving for already accepted scope and may not
smuggle in the next phase.

## Prohibited scope

- No Phase 7 Entra/MSAL, token-derived ownership, authorization, revocation, or
  audit implementation during Checkpoint B.
- No Phase 8 speaker identity, Phase 9 knowledge/agents/MCP, or Phase 10
  enterprise deployment/networking work.
- No full Codex Security plugin scan before the accepted private Phase 10 gate;
  focused security-aware review remains required.
- No private audio, transcripts, scan output, raw benchmark output, host paths,
  credentials, or enterprise configuration in Git, PRs, or hosted logs.
- No broad dependency upgrades, model replacement, quality-claim promotion, or
  ADR score inflation without direct executable evidence.
