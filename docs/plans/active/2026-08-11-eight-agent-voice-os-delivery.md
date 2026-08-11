# Complete eight-agent Voice OS delivery

**Status:** Active; Slice A exact-head lifecycle, private qualification, and
aggregate evidence passed; hosted review/merge and later slices pending.

**Branch:** `feat/phase10-agent-service-profiles` for the first executable
slice. Later slices use focused branches and merge only after their exact heads
are reviewed and hosted-green.

**Base:** merged Phase 10 Slice 10.1 and documentation closure at
`4f194c2d0a9fde619c7d9793ec19fdd1feffc203`.

**Applied decisions:** [ADR 0031](../../adr/0031-eight-agent-voice-os-roster.md),
[ADR 0030](../../adr/0030-rust-supervised-provider-service-lifecycle.md),
[ADR 0029](../../adr/0029-vllm-agent-reasoning-runtime.md),
[ADR 0028](../../adr/0028-model-independent-terminology-authority.md),
[ADR 0022](../../adr/0022-google-okf-permission-safe-projections.md), and
[ADR 0016](../../adr/0016-auth-identity-bridge.md).

## Objective

Ship Scribe, Archivist, Student, Curator, Auditor, Librarian, Analyst, and
Coordinator as complete bounded product workflows through the amended
private-server architecture, while preserving raw/local operation and keeping
production, capacity, and enterprise claims evidence-gated.

## Global acceptance boundary

- Every role has one functional owner, trigger, authenticated purpose, bounded
  input/output contract, cancellation behavior, persistence rule, and visible
  failure outcome.
- Rust owns model-service readiness and fair bounded admission. Python owns
  knowledge, authorization, tools, audit, and publication. The native desktop
  connector owns credentials; the renderer owns none.
- Qwen rapid and Gemma complex remain explicit separate routes with no fallback.
- The multi-user target keeps both route services warm behind bounded fair
  admission; request handling never cold-starts a model. Enabling both services
  still requires simultaneous-residency and sustained-capacity evidence. If one
  node cannot satisfy that evidence, the routes use separate owned service nodes
  rather than swapping models or silently falling back.
- Raw ASR and reviewed sources are never overwritten by agent output.
- Remote failure never disables local capture, playback, raw transcript access,
  export, deletion, or offline controls.
- Each slice lands only after focused tests, repository checks, exact-head
  review, hosted CI, and documentation reconciliation.

## Slice A — exact supervised agent services

- [x] Add immutable rapid and complex service profiles bound to the candidate
  lock, distinct loopback endpoints, container identities, model revisions,
  parsers, output protocol, resource limits, and exact vLLM arguments.
- [x] Make the Rust supervisor bind the exact profile hash, route, endpoint,
  model, and candidate-lock identity; require full semantic profile validation
  in the immutable child before Docker mutation; publish profile identity in
  private state.
- [x] Add one hardened foreground agent-vLLM launcher that consumes only an
  admitted exact profile plus private runtime inputs and reuses the existing
  immutable container/loopback-proxy owner.
- [x] Install two explicit systemd instances without enabling or starting them.
- [x] Prove identity mismatch, changed profile bytes, port/name collision,
  startup, cancellation, restart, and zero-residue teardown without requiring a
  GPU for the portable contract lane.

Exact lifecycle head `4b103c1bd8b393b7cabf6d219071fa8ba37bda09`
passed both sequential Qwen/Gemma start/readiness/restart/stop lifecycles with
public-safe evidence SHA-256
`9b6a34f6d4f099123894212bbabda79463b73c1a954bbd04a71a7dfb1d88f27d`.
Exact private qualification head
`4d6232123520dd85202f7095c156c766c7dd2ee0` returned
`required-workload-routes-qualified` with public-safe evidence SHA-256
`4a856f3e4fcdb3ed8bb79310646cbd8df5c12533ce91f5049190daa7379ca8d8`.
Public-lock successor `0471b158ac34f97c0f2be7323433470fe5de7fa4`
then returned `governed-knowledge-gate-passed` with public-safe evidence SHA-256
`008d748bfe88b5eb68b2c8abbecd682e0a4aceb6634872ead077e0993a2455b2`.
The gate ran 157 portable tests across 26 modules, Ruff, and 17 zero-skip
Postgres tests across four modules; proved real restart/retrieval/stale-
generation/successor behavior; preserved the unchanged desktop boundary; and
proved all teardown predicates. This is sequential lifecycle and semantic
evidence, not simultaneous residency, multi-user capacity, or production
promotion.

## Slice B — authenticated admission and adapters

- [ ] Add typed agent-work requests bound to tenant, subject, purpose, role,
  source identity, route, deadline, and cancellation token.
- [ ] Admit work only to already-warm route services; model startup and swapping
  are lifecycle/operations concerns, never per-request behavior.
- [ ] Implement HOT, INTERACTIVE, BACKGROUND_IO, BACKGROUND_LLM, and IDLE_ONLY
  admission with bounded queues, fair owner limits, typed overload, and no route
  substitution.
- [ ] Add bounded native-to-server and Rust-to-Python adapters; keep bearer
  tokens and provider credentials out of the renderer and Python domain payloads.
- [ ] Prove cancellation acknowledgement, deadline inclusion of queue time,
  provider restart/unready behavior, owner fairness, and local-control survival.

## Slice C — Scribe

- [ ] Replace unrestricted whole-transcript polishing with finalized,
  source-hashed segment input and structured edit output.
- [ ] Validate source coverage, edit bounds, ordering/timing, terminology, names,
  numbers, dates, units, medication-like terms, negation, deletion, and invented
  content before accepting a correction.
- [ ] Save a separate immutable correction revision and show a visible diff;
  preserve and export raw ASR.
- [ ] Remove the development renderer-to-Ollama path when the authenticated
  native/server Scribe route is complete.
- [ ] Qualify representative real ASR mistakes for correction benefit,
  preservation, hallucination/deletion, uncertainty, timeout, and p95 latency.

## Slice D — source and review agents

- [ ] Archivist consumes only durable reviewed-source admissions and owns
  deterministic compilation/staging outcomes without an LLM.
- [ ] Student creates bounded cited questions from permission-safe admitted
  conversations and never mutates source or knowledge.
- [ ] Curator consumes reviewed answers and source citations, writes governed
  proposals only, and cannot directly activate knowledge.
- [ ] Prove restart read-back, duplicate/idempotent transitions, cross-owner
  rejection, cancellation, invalid output, and no-success-after-failure audit.

## Slice E — knowledge and coordination agents

- [ ] Librarian returns a permission-safe evidence pack pinned to one active
  generation for the transaction lifetime and never invokes an LLM.
- [ ] Analyst produces a bounded cited answer from that frozen pack or an exact
  evidence-unavailable response.
- [ ] Coordinator produces source-cited plans/proposals from authorized
  cross-conversation inputs and never performs autonomous mutations.
- [ ] Auditor runs only by authorized manual trigger or bounded schedule while
  idle, publishes source-cited findings, and never mutates authority.
- [ ] Prove revocation, hidden-node/link rejection, stale generation,
  cancellation, overload, idle admission, and audit/publication behavior.

## Slice F — product integration and promotion evidence

- [ ] Expose the roster through authenticated server endpoints and native Tauri
  commands with role-specific UI states, retry/cancel controls, and graceful
  degradation.
- [ ] Run portable, database, lifecycle, private-model, mixed-route,
  simultaneous-residency, sustained-capacity, security, accessibility, and
  aggregate exact-head gates.
- [ ] Publish only public-safe hashes, counts, outcomes, and bounded qualitative
  facts; keep prompts, outputs, credentials, paths, database content, and raw
  private measurements private.
- [ ] Reconcile architecture/status/ADR/roadmap/runbooks, open focused PRs, wait
  for hosted-green exact heads, merge, and complete the post-delivery checkpoint.

## Prohibited shortcuts

- No eight-prompt facade, generic agent framework, renderer-owned provider call,
  bearer token in TypeScript, silent model fallback, unrestricted transcript
  rewrite, direct agent knowledge mutation, invented identity/network approval,
  or unmeasured TPS/production claim.
- No compatibility path for the development Polish implementation after Scribe
  replaces it.
- No checking completion boxes from documentation alone.
