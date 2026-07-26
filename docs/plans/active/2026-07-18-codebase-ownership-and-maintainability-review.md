# Codebase Ownership and Maintainability Review Plan

**Status:** Active on `chore/codebase-maintainability-review`. Phase 6 merged in
[PR #67](https://github.com/mcnatg1/yap/pull/67) as
`87c8654250cba8b9eafa5007bf719c52e4749cdf`; this checkpoint remains a separate
reviewable change and does not authorize Phase 7 product work.

**Branch:** `chore/codebase-maintainability-review`

**Base:** Reviewed Phase 6 merge
`87c8654250cba8b9eafa5007bf719c52e4749cdf`.

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

After the Checkpoint B branch was created, the primary agent launched exactly
three independent read-only reviewers in parallel. Their completed reviews use
repository state, executable contracts, and observed behavior rather than
trusting status claims. At minimum, the review covers:

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

- [x] Create the checkpoint branch from the reviewed Phase 6 merge and record
      the exact base.
- [x] Inventory changed modules, tests, docs, dependencies, generated/runtime
      artifacts, model locks, evaluation manifests, and Git/object state.
- [x] Run the parallel antagonistic review and publish a public-safe findings
      register, ownership map, file inventory, and verification plan.
- [x] Resolve correctness/security/privacy/provenance/resource findings before
      structural refactors that depend on them.
- [x] Remove duplicate/dead/speculative machinery and decompose mixed owners,
      oversized modules, and catch-all test harnesses without adding Phase 7
      behavior.
- [x] Break the server worker-to-engine dependency cycle. Accept only a
      one-way provider protocol/adapter dependency, retain the same runtime
      contract and lifecycle behavior, and add an import/dependency check that
      fails if the cycle returns.
- [x] Restore desktop language-routing-to-STT dependency direction under one
      composite routing-revision owner. Remove reverse/cross-owner state access
      while preserving the accepted local decision, span, fallback, and model
      replacement behavior in focused tests.
- [x] Consolidate duplicate server request fixtures behind behavior-named
      builders without weakening endpoint-specific assertions. The resulting
      fixtures must keep immutable request identities explicit and must not
      become one catch-all mutable test object.
- [x] Reconcile architecture, ADR implementation status, current status,
      roadmap, runbooks, active/completed plans, and evidence classifications
      with the refactored executable system.
- [x] Run focused verification throughout each affected slice.
- [ ] Freeze one checkpoint candidate and run the complete applicable local,
      native, server, release, disposable-Windows, and GB10 matrix exactly once.
- [ ] Open a focused PR, require green exact-head hosted checks and review, and
      merge only the checked SHA.

## Implemented checkpoint repairs

- Correctness and lifecycle repairs now cover retention reconciliation, fail-stop
  NeMo teardown, desktop quit ordering, Windows file identity, language-routing
  ownership, accessible overlay/main-window activation, and same-process
  second-launch recovery.
- Provider engines depend on a neutral PCM module; an AST contract prevents a
  return to the executable-worker dependency cycle.
- `RecordingJobService` receives the real `BatchAsrPool` owner directly. The
  removed wrapper added an immediate enqueue/dequeue hop but no independent
  fairness, capacity, or lifecycle behavior.
- Shared API/job request fixtures use behavior-named builders, while
  endpoint-specific assertions remain local.
- Generic bounded desktop logging is crate-root diagnostics infrastructure.
  STT retains only ASR-specific log ownership.
- Python 3.12 linting is pinned in the locked `uv` environment and enforced in
  hosted CI with a deliberately narrow correctness baseline (`E4`, `E7`, `E9`,
  and `F`). Ruff formatting is available but is not mass-applied in this mixed
  behavioral checkpoint; a repository-wide formatter baseline remains a
  separately reviewable mechanical change.
- The complete gate calls the broad Playwright surface
  `frontend.browser-workflows` and records Ruff separately as `server.lint`;
  neither label claims accessibility coverage that its command does not prove.

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
