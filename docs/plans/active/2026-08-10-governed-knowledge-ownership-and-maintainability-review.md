# Governed knowledge ownership and maintainability review

**Status:** Active on `feat/governed-knowledge-maintainability`.

**Base:** merged governed-knowledge delivery
`ae81ff067c73a64528eecc14403765562726f2fe` from
[PR #152](https://github.com/mcnatg1/yap/pull/152).

**Scope:** Review and simplify the whole accumulated first-party executable
system through merged Phase 9, not merely the Phase 9 diff. Earlier phase and
checkpoint acceptance is evidence, not an exemption from review. Do not add
Phase 10 production-service, capacity, enterprise-network,
security-certification, or deployment behavior.
The [Voice OS architecture](../../VOICE-OS-ARCHITECTURE.md) remains the protected
long-term frame of reference. Any proposed change to that target requires
explicit product-owner review rather than a silent checkpoint rewrite.

## Governing outcomes

1. One explicit owner exists for every reviewed source, immutable capture,
   terminology record/snapshot, compiled generation, permission view, result,
   proposal, agent route, runtime lifecycle, and evidence decision.
2. Correctness, security, privacy, provenance, authorization, cancellation,
   concurrency, restart, partial-publication, and resource-containment findings
   are resolved before dependent structural cleanup.
3. No duplicate source, identity, permission, terminology, generation,
   retrieval, proposal, route-selection, model-lifecycle, retry, cancellation,
   or publication authority remains.
4. Dead, superseded, speculative, and YAGNI machinery is removed instead of
   hidden behind compatibility layers, fallbacks, or generic abstractions.
5. Mixed or oversized production and test surfaces are decomposed or receive a
   written cohesion justification. The established 350-line threshold remains
   a review trigger, not an automatic refactor quota.
6. Dependencies remain one-way; trust boundaries are bounded, redacted,
   fail-closed, and consistent with the executable ownership map and ADRs.
7. Efficiency claims require measurement or demonstrable work removal. Model
   throughput, concurrency, memory, cache behavior, cancellation, and teardown
   are not inferred from framework marketing or synthetic labels.
8. Runtime files, symbols, fixtures, configuration, receipts, and containers use
   functional owner/behavior names. Phase numbers remain delivery prose only.
9. Current, normative, active, completed, historical, runbook, roadmap, and
   evidence documents remain distinguishable and linked; private evidence stays
   outside Git and hosted artifacts.
10. One exact checkpoint head passes its complete applicable matrix once and
    merges through one focused reviewed PR before Phase 10 begins.

## Quality lenses

The repository-specific brief and executable behavior are the acceptance test.
Use ISO/IEC 25010, ISO/IEC 5055, ISO/IEC 25023, NIST SSDF 1.1, and CMU SEI
scenario-driven architecture evaluation only as review lenses, not as a
certification claim. Apply them to comprehensibility, modularity, analyzability,
testability, reliability, security, privacy, performance efficiency,
replaceability, and operational failure behavior.

## Three-lens antagonistic review

Exactly three independent read-only reviewers inspect the merged base before
the primary agent edits findings:

1. **Knowledge authority and persistence:** source admission, tenant/subject/
   purpose authority, terminology, generation atomicity, permissions,
   retrieval, citations, proposals, restart/recovery, retention, and SQL paths.
2. **Agent runtime and evidence:** tool contracts, prompt/context boundaries,
   route selection, model/runtime identity, batching/isolation, cancellation,
   resource observation, teardown, private evidence admission, and false-green
   gate paths.
3. **Architecture and human maintainability:** dependency direction, duplicate
   ownership, module/test cohesion, names, dead/speculative code, documentation
   taxonomy, local/offline non-regression, and Phase 10/IT handoff boundaries.

Every finding requires severity, exact file/line evidence, an executable failure
scenario, and the smallest sound verification. Reviewers do not edit during
discovery. P0-P2 findings block the checkpoint; optional optimization is
recorded rather than converted into open-ended research.

## Coverage protocol

Before proposing structural edits, inventory every active first-party source,
test, configuration, migration, script, dependency declaration, lock, fixture,
container/runtime contract, and governing-document area. Exclude generated
output, package caches, vendored code, binaries, model weights, and private
evidence with an explicit reason. Review dependencies and lockfiles only for
necessity, consistency, reproducibility, supported-runtime compatibility,
license/provenance, security relevance, and duplicate or obsolete paths.

Produce a concise ownership/dependency map and trace the critical workflows end
to end: desktop capture/local fallback, durable remote batch, preprocessing and
language evidence, authenticated ownership/admission, meeting evidence,
governed knowledge compilation/retrieval, agent routing, and each associated
cancellation/retry/restart/publication/teardown path. Record each active area as
reviewed, deeply reviewed because of risk/coupling/churn/size, or excluded with
a reason.

Deep line-level inspection covers every high-risk or ambiguous owner, critical
workflow/trust boundary, broad fan-in/fan-out surface, suspicious wrapper or
generic helper, and every hand-written file at or above 250 lines. A file at or
above 350 lines must be decomposed or receive a concrete cohesion justification;
the threshold is a trigger, not a quota. Use the deletion test for shallow
wrappers and require every retained interface to represent a real seam.

The resulting public-safe checkpoint record must contain the coverage
inventory, ownership/dependency map, findings and dispositions, production/test
LOC baselines by domain, removable-LOC estimates and actual results, retained
cohesion justifications, critical failure scenarios, focused verification,
documentation reconciliation, and exact candidate/checked-head evidence. It
must also record a thirty-minute comprehension assessment: whether a new senior
engineer can locate durable truth, lifecycle owners, critical workflows,
failure boundaries, provenance validation, and their tests without tribal
knowledge.

## Ordered checkpoint slices

- [x] Create the functionally named checkpoint branch from exact merge
  `ae81ff067c73a64528eecc14403765562726f2fe`.
- [x] Archive the governed-knowledge delivery plan with exact PR/head/merge
  evidence and establish this separate checkpoint plan.
- [x] Inventory changed production modules, tests, dependencies, locks,
  fixtures, runtime/gate owners, documents, and Git state from the merged base;
  inventory the earlier active system as required by the whole-codebase scope.
- [x] Run exactly three read-only antagonistic reviews at anchor
  `e2fff1f5b087cc05a549588ea41aae71a6806024` and adjudicate the deduplicated
  public-safe findings register. Initial discovery contained no P0, four P1,
  eleven P2, and bounded P3 observations. Remediation re-review upgraded the
  source-admission defect to P1 and found the separate canonical-generation
  integrity P1. Final pre-gate review then found the route-admission
  self-protection P1, so the accepted register now contains seven P1 and ten P2
  without expanding the checkpoint into Phase 10.
- [ ] Resolve every P0-P2 correctness, security, privacy, authorization,
  provenance, race, cancellation, resource, lifecycle, naming, architecture,
  and maintainability finding.
- [x] Remove duplicate/dead/speculative machinery and decompose only mixed
  owners or unjustified oversized surfaces; do not create a generic evidence or
  repository framework.
- [x] Record every reviewed area's disposition, LOC baseline/removal result,
  cohesion justification, failure-scenario coverage, and the thirty-minute
  comprehension assessment in a public-safe checkpoint record.
- [x] Reconcile the executable ownership map, ADR implementation status,
  current status, roadmap, runbooks, and Voice OS summaries without silently
  changing the approved long-term target.
- [ ] Use focused verification for each repair; freeze one exact candidate only
  after code, tests, provenance, documentation, and three-lens review are clean.
- [ ] Run the complete applicable checkpoint matrix exactly once, preserving
  any still-valid immutable private predecessor evidence by explicit identity
  rather than rerunning unrelated model research.
- [ ] Open one focused PR, require green hosted checks on its exact head, and
  merge before Phase 10 begins.

## Explicit exclusions and handoffs

- No new Phase 10 production service, simultaneous model residency, sustained
  mixed-route/multi-owner capacity, SLO, observability, backup, deployment, or
  external-network capability.
- No model replacement, benchmark retuning, generic 200+ TPS claim, or new
  training/evaluation research merely because a checkpoint is available.
- No full Codex Security scan before the accepted private Phase 10 gate;
  security-aware code review remains mandatory here.
- No developer-owned substitute for IT-controlled Entra policy, certificates,
  DNS, ZPA, firewall, monitoring, hosting authorization, or deployment.
- No broad dependency/tool upgrades, UI redesign, backwards-compatibility
  layer, or speculative repository split unrelated to a concrete finding.
- No private paths, raw model outputs, prompts, retrieved content, credentials,
  database rows, transcripts, metrics, or scan artifacts in Git, PRs, or hosted
  logs.
