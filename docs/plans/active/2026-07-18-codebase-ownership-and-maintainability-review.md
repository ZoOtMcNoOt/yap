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
- [x] Freeze one merge-authority checkpoint candidate and run the complete applicable local,
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

## Gate attempt history

Exact candidate `79956ec67eee59f26d1f9845df28d8a5e2a21bf0` was admitted
once and failed closed during GB10 preflight before any provider started. The
controller placed the planned provider evidence beside, rather than beneath,
the declared private evaluation cache. The concurrent Windows collector was
stopped, and independent read-back found no retained local or remote process,
listener, container, or network. That attempt remains failed private evidence
and must not be resumed, retried, or relabeled.

Exact candidate `8fdb0057e73f7b3a31f09c3cd11756e043557d59` was admitted
once and failed closed before the GB10 lifecycle script started. The Windows
controller passed a CRLF-terminated script path through standard input, so Bash
resolved the target as `resident-provider-lifecycle-gate.sh\r`. The concurrent
Windows collector was stopped, and independent read-back found no retained
local process or remote provider container, private network, or listener. That
attempt remains failed private evidence and must not be resumed, retried, or
relabeled. The replacement controller must normalize its generated remote
script to LF before invoking Bash.

Exact candidate `307c8a5c08827b36c7f54cc1453498ed6e7f5623` was admitted
once and failed closed in both hardware preflight lanes. PowerShell's native
process pipeline re-encoded the already-normalized remote script as CRLF, so
the GB10 lifecycle script again did not start. Independently, the Windows
native collector rejected its private Nemotron staging as `ModelCorrupt`
before inference began. The source artifacts subsequently matched their pinned
sizes and hashes, but the staging also retained load snapshots from the
forcibly stopped prior collector. Read-back found no retained local process or
remote provider container, private network, or listener. This attempt remains
failed private evidence and must not be resumed, retried, or relabeled. A new
candidate requires a fresh model staging without retained load snapshots and
an LF-only SSH input file that is validated before admission.

Exact candidate `b697055c0243799f2a9041e5025a0c436c17822a` was admitted once
after both hardware preflights passed. Its Windows native resource lane passed
all 12 cycles, its prepared short-boundary duration evidence passed all 9
cases, its release build passed, and both rendered UI scenarios passed. The
final production tray action then left the desktop process alive beyond its
10-second exit contract after a real local session. The concurrent GB10 lane
was stopped, and independent read-back found no retained local or remote
process, provider container, private network, or listener. This attempt remains
failed private evidence and must not be resumed, retried, or relabeled.

Exact candidate `a89c9c3610b8b0bdf9fb511471312668fa60fe8e` was admitted once
after its local, remote, runtime-preparation, model, duration-suite, and
controller preflights passed. Before either hardware lane started, the Windows
controller-generation command failed on a PowerShell quoting error while
replacing the target-client Cargo invocation. No target-client or GB10 evidence
destination was written. Independent read-back found no retained local or
remote process, provider container, private network, listener, or transient
service. This attempt remains failed private evidence and must not be resumed,
retried, or relabeled. Replacement candidates must fully materialize and parse
both hardware controllers before admission.

Exact candidate `726256bd48cfde68226c2c6b7c196a53e88fae3e` was admitted once
after both materialized hardware controllers passed PowerShell or Bash syntax
validation and a separate no-op transient-service probe passed. Its GB10
transient service then failed before the lifecycle wrapper started because the
controller file had no executable shebang; Bash syntax validation did not
exercise the direct `execve` boundary. The Windows lane never started, no
hardware evidence destination was written, the collected transient unit
disappeared, and independent read-back found no retained process, provider
container, private network, or listener. This attempt remains failed private
evidence and must not be resumed, retried, or relabeled. Replacement preflight
must execute the actual controller through the same transient-service boundary.

Exact candidate `bbd4f40d0460d7f706bdc455eec8c084cce3266c` was admitted once
after the exact GB10 controller passed the transient-service executable
boundary in preflight-only mode. Its complete Windows target-client lane
passed, including the repaired real-session tray exit. Its sequential Cohere
and Nemotron GB10 lifecycle also completed with status zero and the transient
unit was collected. The subsequent independent process-absence verifier then
failed because its `pgrep` expression matched the verifier's own command line,
before the bounded GB10 aggregate was copied to the Windows plan destination.
A separate audit-only read-back with explicit self and parent exclusion found
no retained local or remote process, provider container, private network, or
listener. This admission remains failed private evidence and must not be
resumed, retried, or relabeled. Replacement absence checks must enumerate
processes while excluding the verifier identities rather than searching their
own command line.

Exact executable candidate
`f3f2f910c2340bbab016f98c51438414415b7206` passed its single admitted
checkpoint gate. The independently validated candidate receipt binds that
exact head, 31 children, and frozen manifest SHA-256
`1cb5a7e165f50e6a2c6746c00169e1c68c9d154fe8fdab0ab3a0bf78042696e5`.
The target-client channel passed all 12 native cycles, nine prepared-audio
boundaries, release build, both rendered UI scenarios, and production
real-session tray exit. The sequential GB10 channel passed the complete Cohere
and Nemotron lifecycle and the corrected independent absence verifier. The
connected channel passed the real tunneled import, verified History result,
interruption-safe ownership, and exact local/remote teardown. The integrated
matrix passed the frozen frontend, native, server, release, provenance,
dependency, WDIO, Python 3.12, Ruff, and private external cells. Private audio,
transcripts, raw metrics, process ledgers, host paths, logs, and receipts remain
outside Git and hosted artifacts. Final read-back, hosted exact-head closure,
review, and merge were not claimed by this receipt.

Final read-back found concrete blockers after that execution: native cleanup and
batch-worker containment could still retain a server process; generic atomic
publication and provider/test seams retained duplicate or backward ownership;
the unused router and stale current-state claims remained; dependency notices
were not bound per shipped package; the unfocused tool-window overlay lacked a
native keyboard acquisition route; second-launch activation trusted an untyped
marker; and the checkpoint evidence still carried the Phase 6 gate identity.
These findings invalidate `f3f2f910...` as merge authority without changing
what its passing receipt proves. A repaired exact candidate requires its own
single complete admission after focused verification.

The repaired tree now fail-stops both native NeMo cleanup and Python executor
containment at bounded process boundaries; removes the unused router and
duplicate request/PCM/job-ID owners; consolidates durable text publication at
the crate root; binds every shipped dependency to exact notice documents or a
reviewed own-source exemption; adds a reserved, settings-visible native shortcut
that acquires the overlay from another foreground process; hardens the
versioned app-data activation signal against stale, wrong-type, and redirected
entries; linearizes second-launch activation with primary shutdown; preserves
native keyboard activation on child overlay controls; makes executor teardown,
retention deletion, expired-job recovery, and deletion-debt admission
deterministically bounded; and gives maintainability checkpoints their own
manifest/runbook identity while preserving the Phase 6 manifest bytes. Focused
server, Rust, frontend, release-contract, installer-contract, and
external-foreground WDIO verification pass. Three independent final read-backs
found no remaining P0-P2 issue at exact executable head
`e4c1eb5d614182ba942ddbf7947794276636871e`.

That exact head was then admitted once after fresh local, GB10, runtime-image,
model, duration-suite, controller, transient-service, and ownership-zero
preflights passed. No target-client, GB10, connected, or integrated workload
started. The operator's immediate display-only admission read-back expected
two fields that are not part of the admission schema and returned nonzero after
the valid admission had already been created. The one-attempt rule therefore
consumes this admission even though no evidence destination was written.
Independent read-back found no retained local or remote process, provider
container, private network, listener, or transient service. The admission must
not be resumed, retried, or relabeled; a docs-only successor requires fresh
runtime receipts, private destinations, controller preflights, and admission.

Docs-only successor
`76b43784cc4ae19dc121503b4555efb84e27fc6c` then passed its complete
target-client, sequential GB10, connected desktop/private-server, and exact
teardown lanes. The integrated command matrix passed its Node runtime,
dependency installation, and dependency-audit children, then failed its
release-contract child because the keyboard-accessibility repair had changed
`live-overlay.tsx` without refreshing that reviewed local file's exact hash in
`THIRD_PARTY_PROVENANCE.json`. The runner marked the attempt failed before later
command children ran. Independent read-back found no retained local or remote
process, provider container, private network, listener, or transient service.
This admission must not be resumed, retried, or relabeled. A successor must
bind the corrected exact local provenance hash and repeat every private lane
and command child from fresh evidence.

Provenance-corrected successor
`e8d3a0579cf3ccf252376324330d13b97e3173ff` then passed its complete
target-client, sequential GB10, connected desktop/private-server, and exact
teardown lanes. The integrated command matrix passed its frontend runtime,
dependency, audit, release-contract, provenance, unit, build, Chromium, and
browser-workflow children; its native format, Clippy, test, connector,
Windows-dependency, and audit children; and its desktop WDIO build. The
required desktop WDIO child then found that keyboard activation could return
focus to the main window while leaving the idle overlay expanded. Later
operations therefore inherited the prior expanded surface instead of a
collapsed island. The runner marked the attempt failed before later command
children ran. Independent read-back found no retained local or remote process,
provider container, private network, listener, or transient service. This
admission must not be resumed, retried, or relabeled. A successor must make
focus-loss collapse explicit, prove that transition directly, refresh the
reviewed local provenance hash, and repeat every private lane and command child
from fresh evidence.

Exact repaired candidate
`66267af0abf38af0a6b8d3d2fac76543673c0331` passed its single admitted
checkpoint gate. Independent validation bound that exact head, all 31 children,
and frozen manifest SHA-256
`2641f613a2a8dfbf0d2e1c7989b37c3af7e85aab732c3ae20381b52c1d144ac2`;
the private candidate receipt has SHA-256
`21977f50ccf18ff9a342575f2f8f1ab8162951da3ebad5bf86c1d7f7eb2254b7`.
The target-client, sequential GB10, connected desktop/private-server, exact
teardown, frontend, native, required desktop WDIO, Python 3.12, and Ruff cells
all passed. The required desktop suite directly proved that keyboard focus
retains the expanded overlay through pointer exit and that focus transfer back
to the main window then collapses it. Independent final read-back found no
retained local or remote process, provider container, private network,
listener, or transient service. Private audio, transcripts, raw metrics,
process ledgers, host paths, logs, and receipts remain outside Git and hosted
artifacts. Hosted exact-head closure, PR review, and merge remain pending.

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
