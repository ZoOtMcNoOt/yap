# Complete eight-agent Voice OS delivery

**Status:** Active; Slices A and B merged through PRs #157/#158. Slice C Scribe
merged through PR #164. Slice D Archivist merged through PR #165 as
`2a7ec819edbf03a4f3fd3fe8de92ddad5bfd71f9`. Student's source-grounding repair
is complete-portable-test green on the unchanged full Qwen rapid profile; replacement
private qualification, hosted review/merge, Curator, shared product
integration, simultaneous-capacity evidence, and later role slices remain
open.

**Current branch:** `agent/phase10-student` for the second Slice D workflow.
Later slices use focused branches and merge only after their exact heads are
reviewed and hosted-green.

**Base:** merged Archivist slice at
`2a7ec819edbf03a4f3fd3fe8de92ddad5bfd71f9` from hosted-green head
`e1899db7312643a32ae67cfdf196aa3c1d40a298` and PR #165.

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
- [x] Qualify representative real ASR mistakes for correction benefit,
  preservation, hallucination/deletion, uncertainty, timeout, and p95 latency.

The implementation consumes only the merged already-warm rapid route. It adds
authenticated asynchronous POST/status/cancel APIs, strict source/terminology/
model validation, queue-inclusive 60-second completion, 64 server in-flight and
256 retained-terminal bounds, trusted native source re-read before publication,
one separately revisioned user acceptance, and a manual visible-diff UI. Old
timingless raw transcripts are deliberately ineligible. The public matrix passes
1,198 server tests with 30 declared platform skips, Ruff, 367 desktop unit tests,
the production build, 41 browser scenarios, and both Rust workspaces with strict
lint. The private corpus freezes 24 bilingual/safety cases across eight distinct
owners and real ASR source evidence; its raw inputs, outputs, measurements, and
paths remain outside Git.

Exact source-lock head `e585842485a7cd38b2935cc8f79314b19b37f7fd`
passed the complete private gate as `scribe-transcript-correction-qualified`
with public-safe semantic evidence SHA-256
`5e187ed4f33e7a84c53824afb5a2af4b5ad0afcb3b7b7b36cb0b01692c74b3cb`.
The untouched final corpus produced 24 terminal outcomes across eight owners and
16 unique real-audio inputs: eight English, eight Spanish, eight safety, eight
corrected references, eight source-preserved references, six unchanged
outcomes, and two uncertainty outcomes. Correction benefit, protected-fact and
no-regression checks, bounded raw fallback, queue-inclusive p95, one unchanged
warm rapid generation, broker identity, database teardown, and complete owned
runtime teardown all passed. Exact server-authorized terminology normalization
is now one correction authority; independently validated model edits remain
bounded and uncertainty returns raw ASR. See the
[public verification record](../../evidence/scribe-transcript-correction/VERIFICATION.md).
Hosted-green head `bc9a88bc3d3ee3fd767dbfee1497b6bc61733ce6`
passed all 12 required checks and PR #164 merged Scribe as
`ec3af506da68bbb7a0ce855369dd09c8a791742d`. Production/capacity promotion
remained open; Archivist later merged and Student's first nominally green
receipt was invalidated by adversarial review as recorded below.

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
at that point it still required a complete fresh qualification.

Exact schema-v2 head `cbd7335a26bd7700106b331827756af19c34e38a`
passed public verification. Its bounded private smoke proved the exact quote and
derived-span repair, plus exact cleanup. A prior invalid-output real case then
reached the protected-fact validator but proposed an unauthorized name change
that was neither approved terminology nor present in the frozen reference; a
safety response was also not stable across repeated cold diagnostic runs. The
validator remains unchanged. Exact prompt-grounding head
`e62d33e41d2d85154a07da1d7a1254ea642a5638` then retained safety and exact
cleanup but repeated the unauthorized name edit in its bounded real-case smoke,
so instruction-only grounding was rejected as insufficient. The next
protected successor at `b80fe0b46c8a511b93dd2c85f8ed053d24648663`
masked every detected immutable source span with equal-length private-use
markers, but its bounded real response was an invalid replacement and its safety
disposition did not pass; teardown remained exact. Visible-block head
`5bc8d10e8a3059941b00fa662dc2a4fbbff816a6` also contained exactly but returned
malformed JSON and missed both bounded dispositions. The following successor
used an ASCII equal-length block. Exact head
`7d546163dd08fd3cb6eafce91c64419c84df9f2d` returned valid structured output but
marked the representative correction uncertain and missed the safety probe's
required unchanged disposition; teardown remained exact. A later successor
at exact head `92554be304d5061c84ee04a7eeb9829829705102` fixed the safety
disposition but left the representative single-word ASR substitution unchanged;
teardown remained exact. Exact head `e3ab6b6af6c7757b987a6b8fcc4ef213c4706bc9`
explicitly permitted that correction but also returned it unchanged; safety and
teardown passed. The following successor stated that missing audio was expected and
used linguistic context for one contextually obvious nonprotected ASR word
substitution while treating
placeholders and instruction-like content as expected data and reserving
uncertainty for a possible error that cannot be expressed safely. Exact head
`af1f79a7cfff050a4b87c7499082551ba7dde9e6` retained safety and teardown;
its broader bounded diagnostic produced unchanged cases and one source-bound
edit rejected only because its quote included too much unchanged context. Exact
minimization head `6cf82239569760383dca88d0702d71b35f60e8ad` removed that
coverage failure, but its three-case diagnostic still applied no correction:
one proposal was outside the narrow lexical grammar and another's minimal quote
was repeated; safety and teardown passed. Exact head
`33d9b4d0362689a58be0c16bf26de88ac55d56b2` also applied no correction: two
representatives were unchanged and the third quote, minimized against masked
text, was ambiguous after raw protected values were restored. Safety and every
teardown predicate passed. The later server-authorized terminology successor
retained protected-fact immutability and all unchanged source-bound validation
while allowing only an exact reviewed variant-to-canonical mapping to produce a
deterministic correction. It added no retry and changed no model, 512-token
allowance, timeout/deadline, route, validator, or acceptance threshold. That
successor is the exact qualified head recorded above.

## Slice D — source and review agents

- [x] Archivist consumes only durable reviewed-source admissions and owns
  deterministic compilation/staging outcomes without an LLM.
- [ ] Student creates bounded cited questions from permission-safe admitted
  conversations and never mutates source or knowledge.
- [ ] Curator consumes reviewed answers and source citations, writes governed
  proposals only, and cannot directly activate knowledge.
- [ ] Prove restart read-back, duplicate/idempotent transitions, cross-owner
  rejection, cancellation, invalid output, and no-success-after-failure audit.

Exact Archivist source candidate `3ec9885ee902926f3f7672d2438e1da23c18c284`
adds a dedicated BACKGROUND_IO workflow with no LLM. It reads only an
owner-scoped durable reviewed capture, compiles in an owner-private temporary
workspace, re-reads the source before one admission/staging transaction, and
returns a typed staged-generation result without activation. Exact retry is
idempotent and revalidates the persisted non-embedding generation; conflicting
content fails closed. The complete 1,207-test portable server suite passed with
32 declared platform/database skips, focused Archivist tests passed, Ruff and
diff checks passed, and two real PostgreSQL tests proved exact retry/restart
read-back, cross-owner rejection, pre-cancel no-write behavior, zero active
generation, and all six owned-runtime teardown predicates. Hosted-green head
`e1899db7312643a32ae67cfdf196aa3c1d40a298` then passed all 12 required checks
and PR #165 merged Archivist as
`2a7ec819edbf03a4f3fd3fe8de92ddad5bfd71f9`. This is a merged internal core,
not a product endpoint/UI or aggregate Slice D closure. See the
[public verification record](../../evidence/archivist-ingestion/VERIFICATION.md).

Student adds one internal BACKGROUND_LLM workflow on the already-warm rapid
route. It reads one owner-scoped, permission-safe admitted conversation
generation and asks the unchanged full Qwen profile for bounded learning
questions. The repaired contract accepts bounded topic text as untrusted
context. The model may select only an exact source subject and exact supports;
the server rebinds each support to frozen evidence, derives its span, and alone
renders the fixed question template. The model cannot write question wording,
source, proposals, or knowledge. The current focused set runs 31 total tests:
29 pass and two are declared database skips. The complete portable server suite
runs 1,238 total tests: 1,204 pass and 34 are declared skips for this schema-v3
repair.

Exact head `452c8b76a9a60681a962048caed12749e8bb80d0` originally returned
`student-learning-questions-qualified` with public-safe semantic evidence
SHA-256 `3e1ddc61...`, but adversarial review proved that its focus could supply
a target question and that an unsupported premise could pass beside an
unrelated exact citation. That receipt is terminal and inadmissible. The
current repair retained the full rapid profile (GPU-memory utilization `0.40`,
four maximum sequences, 8,192 maximum batched tokens) and a 512-token Student
output cap; no model launch, swap, substitute, resource reduction, retry, or
threshold relaxation was added. A complete fresh qualification remains before
hosted merge or product exposure. See the
[public verification record](../../evidence/student-learning/VERIFICATION.md).

The earlier predecessor `ffe9088573a1a8453a3cb529f1fc62c8ef9d7dda` is terminal
`deterministic-no-student` evidence with public-safe SHA-256
`bc65dd55dc3c751caa340312fc6435beba5ba0c0d7a2fa43e323297cadf32c3d`.
Seven cases completed and one failed closed after altering a citation span.
No failed or invalidated evidence is reused.

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
