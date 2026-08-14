# Complete eight-agent Voice OS delivery

**Status:** Active; Slices A and B merged through PRs #157/#158. Slice C Scribe
merged through PR #164. Slice D Archivist merged through PR #165 as
`2a7ec819edbf03a4f3fd3fe8de92ddad5bfd71f9`. Student's exact `428d6e48...`
topic-copy prompt repair is privately qualified on the unchanged full Qwen
rapid profile; hosted-green head `b03c6e79...` passed all 12 checks and PR #166
merged the internal core as `2254605e...`. Exact route head `dab19fe...`,
workflow head `7cd24deb...`, and aggregate/public-lock head `7f896b34...`
privately qualified the Curator/profile-capacity successor. Hosted-green head
`593e627b...` passed all 12 checks, and PR #168 merged it as `284ab96b...`.
Student/Curator product integration and simultaneous-capacity evidence were
still open at that point. Hosted head `7505247e...` merged Librarian through PR #169 as
`d7a7e003...`. Exact executable `0665c486...` privately qualified Analyst; lock-
only `8fee7a5c...` publishes the matching batch-invariant route lock. Hosted head
`da1127f8...` merged Analyst through PR #170 as `52c45d22...`. Exact
`fed729b3...` privately qualified Coordinator; hosted head `53ee0152...` passed
all 12 checks and PR #171 merged it as `67d836da...`. Exact `08b06f6d...`
privately qualified Auditor; hosted head `937a4129...` passed all 12 checks and
PR #172 merged it as `1b255e9a...`. All eight bounded internal role cores are
merged. Exact `e2ba1864...` privately qualified Librarian's authenticated HTTP
server boundary; hosted head `67a79ce2...` passed all 12 checks and PR #174
merged its HTTP/native/Knowledge product surface as `98af78c9...`. Exact
`a2e9b551...` privately qualified Archivist's authenticated staging boundary
with 10/10 exact server-side terminals, zero activation, and exact teardown.
Hosted head `69215c43...` passed all 12 checks and PR #177 merged the vertical as
`e397af8b...`. Exact `778a7545...` privately qualified Student with 11/11 exact
server-side terminals; hosted head `53ce570b...` passed all 12 checks and PR
#178 merged it as `6546970b...`. Exact `6aa33e4d...` privately qualified the
Curator product server boundary with 10/10 exact terminals and public-safe
evidence SHA-256 `328f6640...`; hosted head `b983adb7...` passed all 12 checks
and PR #179 merged the vertical as `70303872...`. Exact `78b2c638...` privately
qualified Analyst's authenticated product server boundary with 10/10 exact
terminals and public-safe evidence SHA-256 `f26adfc0...`; hosted head
`4c8db7c2...` passed all 12 checks and PR #180 merged it as `c95fcf1a...`. Exact
`05400fb3...` privately qualifies Coordinator's product server/database/broker
boundary with public-safe evidence SHA-256 `394112ad...`; its hosted merge and
the Auditor product surface remain open.

**Current branch:** `agent/phase10-coordinator-product` follows the merged Analyst
vertical and implements and privately qualifies Coordinator's bounded product
server surface; unchanged-head hosted review/merge remains. The requested Muse
replacement decision is closed for this slice: Meta's official
[Muse Spark 1.2](https://developer.meta.com/ai/models/muse-spark/) page exposes
the model through the hosted Meta Model API with a one-million-token context,
but publishes no open-weight artifact for the organization-owned private DGX
route. The exact qualified Gemma complex profile therefore remains unchanged;
Muse Spark 1.2 is recorded as a later hosted-provider candidate rather than a
local replacement.

**Base:** Analyst product merge
`c95fcf1a043f919661b007f014a8dc6729aa02f2` from PR #180, with executable
qualification retained at exact `78b2c638...` and hosted review at exact
`4c8db7c2...`.

**Applied decisions:** [ADR 0031](../../adr/0031-eight-agent-voice-os-roster.md),
[ADR 0030](../../adr/0030-rust-supervised-provider-service-lifecycle.md),
[ADR 0029](../../adr/0029-vllm-agent-reasoning-runtime.md),
[ADR 0028](../../adr/0028-model-independent-terminology-authority.md),
[ADR 0022](../../adr/0022-google-okf-permission-safe-projections.md), and
[ADR 0016](../../adr/0016-auth-identity-bridge.md).

## Objective

Ship Scribe, Archivist, Student, Curator, Librarian, Analyst, Coordinator, and
Auditor as complete bounded product workflows through the amended
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
- [x] Student creates bounded cited questions from permission-safe admitted
  conversations and never mutates source or knowledge.
- [x] Curator consumes reviewed answers and source citations, writes governed
  proposals only, and cannot directly activate knowledge.
- [x] Prove restart read-back, duplicate/idempotent transitions, cross-owner
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

Exact product successor `a2e9b551...` adds authenticated asynchronous
Archivist HTTP jobs, native-owned durable recording/result resolution and
cancellation, and one explicit renderer **Stage for knowledge** action. Its
owner-private ARM64 gate matched 10/10 terminals, staged 9 requests, cancelled
1 queued request, produced 8 exact source admissions/staged generations,
activated 0 generations, and completed exact teardown. The private gate proves
the authenticated server/database/broker boundary; native/renderer behavior is
exact-head public-test green. See the
[product verification record](../../evidence/archivist-product-vertical/VERIFICATION.md).
Hosted head `69215c43...` passed all 12 required checks, and PR #177 merged the
vertical as `e397af8b...`.

Student adds one internal BACKGROUND_LLM workflow on the already-warm rapid
route. It reads one owner-scoped, permission-safe admitted conversation
generation and asks the unchanged full Qwen profile for bounded learning
questions. The repaired contract accepts bounded topic text as untrusted
context. The model sees ordered evidence indexes and text and returns exactly
one source subject, evidence index, and support quote. The server binds the
frozen evidence and complete citation identity, derives its span, and alone
renders the fixed question template. The model cannot write question wording,
source, proposals, or knowledge. The prompt explicitly rejects topic-derived
subjects absent from the selected quote/evidence. The current focused set runs
34 total tests: 32 pass and two are declared database skips. The protected
successor also passed 1,241 portable tests (1,207 passed and 34 declared skips).

Exact head `452c8b76a9a60681a962048caed12749e8bb80d0` originally returned
`student-learning-questions-qualified` with public-safe semantic evidence
SHA-256 `3e1ddc61...`, but adversarial review proved that its focus could supply
a target question and that an unsupported premise could pass beside an
unrelated exact citation. That receipt is terminal and inadmissible. The
current repair retained the full rapid profile (GPU-memory utilization `0.40`,
four maximum sequences, 8,192 maximum batched tokens) and a 512-token Student
output cap; no model launch, swap, substitute, resource reduction, retry, or
threshold relaxation was added. Exact head `428d6e48...` passed private
qualification before hosted review; product exposure remains open. See the
[public verification record](../../evidence/student-learning/VERIFICATION.md).

The earlier predecessor `ffe9088573a1a8453a3cb529f1fc62c8ef9d7dda` is terminal
`deterministic-no-student` evidence with public-safe SHA-256
`bc65dd55dc3c751caa340312fc6435beba5ba0c0d7a2fa43e323297cadf32c3d`.
Seven cases completed and one failed closed after altering a citation span.
No failed or invalidated evidence is reused.

Exact head `476f7a9c38287f8c6ba08cd9be4a70addabe3069` returned terminal
`deterministic-no-student` with public-safe evidence SHA-256
`9c2f68ffe411d1333c6799158fa28db30ffa0ced6359eb9f291528ded4c0d0d4`.
Six of eight cases completed and two failed closed while the unchanged warm
profile/provider, broker, synchronized eight-owner wave, PostgreSQL boundaries,
and exact teardown held. It is inadmissible for the protected evidence-index
successor and is not reused.

Exact head `0970d74c7961a63bd1b2366bc0ecef6b5fc55714` returned terminal
`deterministic-no-student` with public-safe evidence SHA-256
`316631d593e51477d855ed146e2a5bea49eec236b0753655bdd4814a20a0cb99`.
Seven of eight cases completed and one unsupported topic-derived subject failed
closed while the full warm profile, broker/wave, PostgreSQL boundaries, and
teardown held. No raw output or measurement is published, and the receipt is
not reused.

Exact head `428d6e48690621cc2242944c049e06ccfd2e45e2` returned
`student-learning-questions-qualified` with public-safe evidence SHA-256
`f597cca728d261caad66d6629332c76ffd900bc78f6be20aa7bb0c849275ebe8`.
All eight distinct owners completed with one grounded question each and zero
terminal failures. The unchanged full warm profile, provider generation,
admission broker, synchronized eight-owner queue wave, PostgreSQL
restart/cross-owner/durable audits, and exact six-part teardown held. This is
internal-core qualification, not product exposure or sustained capacity.

Hosted-green head `b03c6e79f19bad451437c3f0c495daa67bb7171f` then passed all
12 required checks and PR #166 merged the internal Student core as
`2254605ed19a592d2db1747d576762ccf11a5cc0`.

The merged baseline contains the privately qualified explicit-submission-only
Curator core and profile-capacity admission successor. Curator may append
only a governed noncanonical proposal and cannot activate knowledge or mutate
source truth. Exact route head `dab19fe...` qualified unchanged full Qwen and
Gemma profiles sequentially at rapid-four/complex-eight selected-route limits.
Exact workflow head `7cd24deb...` returned
`curator-knowledge-proposals-qualified`: eight cases/eight owners, four
proposals, four rejections, zero terminal failures, complex eight/ninth queued,
exact PostgreSQL lifecycle/read-back, and teardown. Exact aggregate/public-lock
head `7f896b34...` passed. Historical one-slot, Scribe, and Student receipts
were not reused for these protected changes. Hosted-green head `593e627b...`
passed all 12 checks, and PR #168 merged the slice as `284ab96b...`. Curator
product exposure remains open. This evidence does not prove sustained capacity,
simultaneous Qwen/Gemma residency, production SLOs, or deployment. The current
Exact `56b7f5d0...` privately qualified Librarian across the corrected actual
eight-owner broker wave. Hosted head `7505247e...` merged it through PR #169 as
`d7a7e003...`; exact predecessor `ecdcb8ee...` remains terminal/inadmissible and
is not reused.

Exact executable `0665c486...` privately qualified Analyst with three exact
synchronized repeat waves, 24 of 24 normal matches, all 29 terminal matches, 12
answers, and 15 server-owned citations. Lock-only `8fee7a5c...` publishes the
matching batch-invariant route lock. Hosted head `da1127f8...` merged Analyst
through PR #170 as `52c45d22...`. Exact `63c3d9fd...` remains terminal no-
receipt evidence from the superseded schedule-sensitive runtime and is not
reused. Same-warm-process repeatability does not prove cross-start/global
determinism, simultaneous residency, sustained capacity, or a production SLO.

Exact executable `fed729b3...` privately qualified Coordinator with three exact
synchronized eight-owner service waves, 24 of 24 normal matches, all 29
terminal matches, 15 server-derived noncanonical review-required bundles, 18
selected proposals, 18 citations, one lease per invocation, exact Curator
lineage/current authority, two PostgreSQL restart/read-backs, and teardown.
Hosted head `53ee0152...` passed all 12 checks and PR #171 merged Coordinator
as `67d836da...`.

Exact executable `08b06f6d...` privately qualified Auditor with three exact
synchronized eight-owner idle-only service waves, 24 of 24 normal matches, all
29 terminal matches, 12 server-derived noncanonical review-required reports,
15 potential-contradiction findings, 30 citations, one lease per invocation,
active/pending non-idle blocking with post-terminal resumption, two PostgreSQL
restart/read-backs, zero proposal writes, and teardown.
Hosted head `937a4129...` passed all 12 required checks and PR #172 merged
Auditor as `1b255e9a...`, completing the bounded internal roster.

## Slice E — knowledge and coordination agents

- [x] Librarian returns a permission-safe evidence pack pinned to one active
  generation for the transaction lifetime and never invokes an LLM.
- [x] Analyst produces a bounded cited answer from that frozen pack or an exact
  evidence-unavailable response.
- [x] Coordinator produces only a server-derived source-cited noncanonical
  review-required bundle from the caller's current open Curator proposals and
  never performs autonomous mutations.
- [x] Auditor's current internal core runs only by explicit authenticated manual
  request while idle, returns source-cited review findings, and never mutates
  authority. Bounded scheduled invocation remains a later product surface.
- [x] Prove Librarian revocation, hidden-before-limit/link suppression, hidden-
  only equivalence, stale generation, cancellation/deadline, Server-IO queue
  containment, exact audits, restart/read-back, and teardown behavior.
- [x] Prove Analyst role-specific failure, audit, citation, restart, and teardown
  behavior in its private qualification slice.
- [x] Prove Coordinator role-specific authority, selection, failure, audit,
  restart, admission, and teardown behavior in its private qualification slice.
- [x] Prove Auditor role-specific authority, evidence, failure, citation,
  idle-only admission, audit, restart, and teardown behavior in its private
  qualification slice.

## Slice F — product integration and promotion evidence

- [ ] Expose the roster through authenticated server endpoints and native Tauri
  commands with role-specific UI states, retry/cancel controls, and graceful
  degradation. Exact `e2ba1864...` qualified this for Librarian's authenticated
  server boundary, and PR #174 merged its hosted-green native/Knowledge surface.
  Exact `a2e9b551...` qualified the Archivist authenticated server boundary;
  hosted head `69215c43...` passed all 12 checks and PR #177 merged the vertical.
  Exact `778a7545...` privately qualified Student's authenticated product server
  boundary; hosted head `53ce570b...` passed all 12 checks and PR #178 merged
  the vertical as `6546970b...`. Exact `6aa33e4d...` privately qualified the
  Curator product server boundary; hosted head `b983adb7...` passed all 12
  checks and PR #179 merged it as `70303872...`. Exact `78b2c638...` privately
  qualified Analyst's product server boundary with 10/10 exact terminals;
  hosted head `4c8db7c2...` passed all 12 checks and PR #180 merged it as
  `c95fcf1a...`. Exact `05400fb3...` privately qualified Coordinator's product
  server/database/broker boundary with 10/10 exact terminals; its hosted merge
  plus the Auditor product surface stay open.
- [x] Immediately after the Curator product successor passed hosted review and
  merged, run a separate Muse replacement decision gate. Require an
  exact official deployable version and artifact, acceptable license/terms,
  organization identity and data-transfer approval, local/private runtime
  support, strict one-tool behavior, and full-route lifecycle/capacity plus
  affected-workflow requalification before replacing Gemma. Official Muse
  Spark 1.2 is available through the hosted Meta Model API, but its model page
  publishes no open-weight artifact for the private DGX route. Retain qualified
  Gemma and continue the Coordinator and Auditor product plan without
  blocking on the model name; treat Muse as a later hosted-provider evaluation.
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
