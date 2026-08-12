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
1,184 server tests with 30 declared platform skips, Ruff, 367 desktop unit tests,
the production build, 41 browser scenarios, and both Rust workspaces with strict
lint. The private corpus freezes 24 bilingual/safety cases across eight distinct
owners and real ASR source evidence; its raw inputs, outputs, measurements, and
paths remain outside Git. This paragraph records implementation readiness, not a
qualification or production-capacity result.

Exact candidate `a53333a577534148b11a49f6f8625ce4ac9b2d00` is terminal
rejected evidence, not a resumable attempt. Its public-safe decision SHA-256 is
`80718c6c8ad2fedd6bec5300c99a2a0af8ae71473c2457313a79b9138f5d8415`.
The multi-owner, warm-generation, broker, terminal, and teardown contracts held,
but the model was asked to generate a request digest rather than copy one exact
trusted binding, so all responses failed closed and no correction was applied.
The binding repair at exact head `b89fd9f118b881d107cc2025b9b8a41e51b9db37`
also returned terminal `deterministic-no-scribe`, with public-safe decision
SHA-256
`0c37120a03d3bcd7434c908ca24a086ccf785678b7c5e9ec49ec6fc051f81c74`.
It proved the exact request/source bindings and began admitting valid unchanged
responses, but edited structured responses exhausted the Scribe-specific
256-token allowance before completing the JSON response. Exact successor
`21559371db2a869e2c8b7ae3cd589f80c189d0cd` raised only that workload allowance
to 512 and returned terminal `deterministic-no-scribe`, with public-safe decision
SHA-256
`a103144c66940ff55d8390c227bc73e6379cbfa6f73a199a9818839adaf48e2b`.
All 24 cases completed across eight owners and 16 unique real-audio items; warm
generation, broker identity, queue-inclusive latency, preservation/no-regression,
database teardown, and runtime teardown held. Complete edited JSON then exposed
model-authored offsets that did not exactly bind their quoted source. The next
protected candidate bumps only the model response from schema 1 to schema 2:
the model supplies segment identity, segment hash, exact source quote, and
replacement; the server accepts the quote only when it occurs exactly once and
derives the Unicode span. Missing or ambiguous source fails closed. It does not
change the warm model, 512-token allowance, owner-fair broker, retry policy,
timeout, queue-inclusive deadline, validators, or qualification thresholds, and
it must run a complete fresh qualification before this slice can close.

Exact schema-v2 head `cbd7335a26bd7700106b331827756af19c34e38a`
passed public verification. Its bounded private smoke proved the exact quote and
derived-span repair, plus exact cleanup. A prior invalid-output real case then
reached the protected-fact validator but proposed an unauthorized name change
that was neither approved terminology nor present in the frozen reference; a
safety response was also not stable across repeated cold diagnostic runs. The
validator remains unchanged. Exact prompt-grounding head
`e62d33e41d2d85154a07da1d7a1254ea642a5638` then retained safety and exact
cleanup but repeated the unauthorized name edit in its bounded real-case smoke,
so instruction-only grounding is rejected as insufficient. The current
protected successor at `b80fe0b46c8a511b93dd2c85f8ed053d24648663`
masked every detected immutable source span with equal-length private-use
markers, but its bounded real response was an invalid replacement and its safety
disposition did not pass; teardown remained exact. Visible-block head
`5bc8d10e8a3059941b00fa662dc2a4fbbff816a6` also contained exactly but returned
malformed JSON and missed both bounded dispositions. The current successor uses
an ASCII equal-length block. Exact head
`7d546163dd08fd3cb6eafce91c64419c84df9f2d` returned valid structured output but
marked the representative correction uncertain and missed the safety probe's
required unchanged disposition; teardown remained exact. The current successor
at exact head `92554be304d5061c84ee04a7eeb9829829705102` fixed the safety
disposition but left the representative single-word ASR substitution unchanged;
teardown remained exact. Exact head `e3ab6b6af6c7757b987a6b8fcc4ef213c4706bc9`
explicitly permitted that correction but also returned it unchanged; safety and
teardown passed. The current successor states that missing audio is expected and
uses linguistic context for one contextually obvious nonprotected ASR word
substitution while treating
placeholders and instruction-like content as expected data and reserving
uncertainty for a possible error that cannot be expressed safely. It retains
exact block-run restoration, 256-character edit fields, shortest unique quotes,
and byte-identical no-op normalization. There is still no retry and no model,
512-token allowance, timeout/deadline, route, validator, or acceptance-threshold
change. One complete fresh qualification remains required.

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
