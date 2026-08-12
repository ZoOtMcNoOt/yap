# Complete eight-agent Voice OS delivery

**Status:** Active; Slice A merged through PR #157 and Slice B merged through
PR #158 as `84d95842950860e3f8d5cc70895aaae9243abe9c`. Slice C Scribe
implementation and its public matrix are complete; private bilingual/multi-owner
qualification, aggregate gate, hosted merge, and later role slices remain open.

**Current branch:** `agent/phase10-scribe-transcript-correction` for Slice C.
Later slices use focused branches and merge only after their exact heads are
reviewed and hosted-green.

**Base:** merged Slice B / Phase 10 Slice 10.3 at
`84d95842950860e3f8d5cc70895aaae9243abe9c` from hosted-green head
`cf1e69a45be15e6663d096f486d0363726638382` and PR #158.

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

- [x] Add typed agent-work requests bound to tenant, subject, purpose, role,
  source identity, route, deadline, and cancellation token.
- [x] Admit work only to already-warm route services; model startup and swapping
  are lifecycle/operations concerns, never per-request behavior.
- [x] Implement HOT, INTERACTIVE, BACKGROUND_IO, BACKGROUND_LLM, and IDLE_ONLY
  admission with bounded queues, fair owner limits, typed overload, and no route
  substitution.
- [x] Add bounded native-to-server and Rust-to-Python adapters; keep bearer
  tokens and provider credentials out of the renderer and Python domain
  payloads. Slice C supplies the authenticated native HTTP integration.
- [x] Prove cancellation acknowledgement, deadline inclusion of queue time,
  provider restart/unready behavior, and owner fairness at the broker boundary.
- [x] Prove local-control survival through the first authenticated native/server
  role workflow in unit, native, and Playwright coverage. Private Scribe and
  aggregate admission remain separate unchecked evidence below.

Exact protected executable head
`7bd93dc624e6d8651dffc710026ca144909b2399`
implements the eight-role request map, one conservative active slot per route,
a 64-request global pending bound, a four-active-plus-pending per-owner bound,
owner round-robin scheduling, weighted class admission, idle-only exclusion,
queue-inclusive deadlines, token-bound completion/cancellation, provider-
generation disruption, and a private Unix-socket broker. The broker never
starts either provider, never swaps or substitutes a route, never replaces an
existing socket owner, and does not automatically restart after losing its
in-memory lease state. Windows and Linux Rust format/lint/all-target tests, the
Linux socket lifecycle, the exact 169-test portable matrix across 28 modules,
and Ruff pass. Replacement qualification returned
`required-workload-routes-qualified` with public-safe evidence SHA-256
`a75500c344eaa7546695ab1e7415466c031ccf394620ed442ca618ea1ede8c06`;
both routes were admitted and Qwen's proposal evidence comprised 24
independently scored samples under unchanged 160-token and 10-second bounds.
Public-lock successor `135cc2ba...` then returned
`governed-knowledge-gate-passed` with public-safe evidence SHA-256
`350c13a5569cfc7237174d1f7e2132857ffb3aaf28b6afd2eca03aa1999aea79`.
It ran the 169-test portable matrix, Ruff, 17 zero-skip Postgres tests across
four modules, real restart/retrieval/stale/successor checks, the unchanged
desktop dependency boundary, and exact teardown. These checks prove the
admission substrate, not an exposed workflow, simultaneous residency,
sustained capacity, or production availability. A prior exact
`c4b5e084...` qualification remains terminal rejected evidence; its raw output,
measurements, and private location remain unpublished.

## Slice C — Scribe

- [x] Replace unrestricted whole-transcript polishing with finalized,
  source-hashed segment input and structured edit output.
- [x] Validate source coverage, edit bounds, ordering/timing, terminology, names,
  numbers, dates, units, medication-like terms, negation, deletion, and invented
  content before accepting a correction.
- [x] Save a separate immutable correction revision and show a visible diff;
  preserve and export raw ASR.
- [x] Remove the development renderer-to-Ollama path when the authenticated
  native/server Scribe route is complete.
- [ ] Qualify representative real ASR mistakes for correction benefit,
  preservation, hallucination/deletion, uncertainty, timeout, and p95 latency.

The implementation consumes only the merged already-warm rapid route. It adds
authenticated asynchronous POST/status/cancel APIs, strict source/terminology/
model validation, queue-inclusive 60-second completion, 64 server in-flight and
256 retained-terminal bounds, trusted native source re-read before publication,
one separately revisioned user acceptance, and a manual visible-diff UI. Old
timingless raw transcripts are deliberately ineligible. The public matrix passes
1,178 server tests with 30 declared platform skips, Ruff, 367 desktop unit tests,
the production build, 41 browser scenarios, and both Rust workspaces with strict
lint. The private corpus freezes 24 bilingual/safety cases across eight distinct
owners and real ASR source evidence; its raw inputs, outputs, measurements, and
paths remain outside Git. This paragraph records implementation readiness, not a
qualification or production-capacity result.

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
