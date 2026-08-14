# ADR 0031: Eight-agent Voice OS roster and execution boundaries

**Status:** Accepted target; all eight bounded role cores and five product surfaces are merged; Analyst has a privately qualified unmerged product successor; Coordinator/Auditor product surfaces and promotion remain open
**Date:** 2026-08-11
**Deciders:** Yap product and engineering owner
**Amends:** [ADR 0006](0006-silero-agents-state-machine.md),
[ADR 0014](0014-server-tier-compute-topology.md),
[ADR 0017](0017-knowledge-base-compiler.md),
[ADR 0028](0028-model-independent-terminology-authority.md),
[ADR 0029](0029-vllm-agent-reasoning-runtime.md), and
[ADR 0030](0030-rust-supervised-provider-service-lifecycle.md)

## Context

The product architecture names eight agents, and the merged system now delivers
all eight as bounded internal role cores. Scribe, Librarian, Archivist, Student, and Curator have current
product surfaces in the merged product. Exact `e2ba1864...` privately qualified
Librarian's authenticated HTTP server boundary; hosted head `67a79ce2...` passed
all 12 checks, and PR #174 merged the HTTP/native/Knowledge vertical as
`98af78c9...`. Exact `a2e9b551...` privately qualified Archivist's
HTTP/native/renderer boundary with 10/10 exact server-side terminals, zero
activation, and exact teardown; hosted head `69215c43...` passed all 12 checks
and PR #177 merged the vertical as `e397af8b...`. Exact `778a7545...` privately
qualified Student with authenticated question
jobs, native-owned transport/validation, and a source-bound renderer action;
its private gate covers the authenticated server boundary rather than a live
native/renderer run. Hosted head `53ce570b...` passed all 12 checks, and PR #178
merged the vertical as `6546970b...`. Exact `6aa33e4d...` privately qualified
Curator's authenticated server boundary with 10/10 exact terminals and public-
safe evidence SHA-256 `328f6640...`; hosted head `b983adb7...` passed all 12
checks and PR #179 merged the vertical as `70303872...`. Exact `78b2c638...`
now privately qualifies Analyst's authenticated cited-answer server boundary
with 10/10 exact product terminals and public-safe evidence SHA-256
`f26adfc0...`; its HTTP/native/renderer successor remains unmerged pending
hosted review. Phase 9 merged the
governed knowledge, tool, retrieval, terminology,
and two qualified reasoning-route foundations. Phase 10
Slices 10.1 and 10.2 merged the Rust-supervised lifecycle and exact Qwen rapid/
Gemma complex profiles. Exact protected head `7bd93dc6...` implements the
bounded admission substrate, exact public-lock head `135cc2ba...` passed its
replacement route qualification and aggregate gate, and PR #158 merged that
substrate as `84d95842...` after all 12 hosted checks passed.

The merged Scribe workflow is the first application workflow to consume the
merged owner. It removes the development renderer-to-Ollama Polish prototype
and replaces unrestricted rewriting with authenticated source-hashed finalized
segments, structured edits, server-bound terminology, native-owned immutable
publication, visible diff, and raw-ASR fallback. Exact source-lock head
`e5858424...` passed its complete 24-case bilingual/eight-owner private gate
with public-safe semantic evidence SHA-256 `5e187ed4...`, correction benefit,
one stable warm rapid generation, bounded raw fallback, and exact teardown.
Hosted-green head `bc9a88bc...` passed all 12 checks and PR #164 merged it as
`ec3af506...`. Hosted-green head `e1899db7...` then passed all 12 checks and PR
#165 merged the no-LLM Archivist reviewed-source compilation/staging core as
`2a7ec819...`. Student's bounded learning-question workflow now has a
complete-portable-test-green topic-copy prompt repair on the already-warm full Qwen
rapid route. Exact `428d6e48...` returned
`student-learning-questions-qualified` with public-safe evidence SHA-256
`f597cca7...`; exact predecessor `0970d74c...` remains terminal
`deterministic-no-student`. Hosted-green head `b03c6e79...` passed all 12 checks
and PR #166 merged the internal core as `2254605e...`; product exposure was
still open at that merge. Exact workflow head `7cd24deb...` then privately requalified Scribe and
Student and qualified the explicit-submission-only Curator core. Curator
returned `curator-knowledge-proposals-qualified` with public-safe evidence
SHA-256 `b60df1e2...`: eight cases/eight owners, four proposals, four
rejections, zero terminal failures, complex capacity eight with a ninth owner
queued, exact PostgreSQL lifecycle/read-back, and teardown. Curator may append
only a noncanonical proposal; it cannot activate or mutate source truth.
Hosted-green head `593e627b...` passed all 12 checks, and PR #168 merged the
Curator/profile-capacity slice as `284ab96b...` on 2026-08-13. Curator product
qualification later passed at `6aa33e4d...`, and PR #179 merged that vertical.
Exact head `56b7f5d0...` privately qualified the no-LLM
Librarian permission-safe evidence core across an actual eight-owner broker
wave, ten exact invocations, Server-IO one-active/second-queued containment,
  PostgreSQL restart/read-back, and exact teardown. Hosted head `7505247e...`
  merged the internal core through PR #169 as `d7a7e003...`; PR #174 later
  merged its authenticated product surface. Exact predecessor `ecdcb8ee...` is
terminal/inadmissible because only seven owners entered broker submission.
Exact executable `0665c486...` then privately qualified Analyst as an internal
candidate with public-safe evidence SHA-256 `940fd7c6...`: three synchronized
eight-owner waves matched 24 of 24 normal results, all 29 terminals matched,
and the 12 answers contained 15 server-owned citations. Hosted head
`da1127f8...` passed all 12 checks, and PR #170 merged Analyst as
`52c45d22...`. Exact executable `fed729b3...` then privately qualified
Coordinator's selection-only proposal-bundle core with public-safe evidence
SHA-256 `1bce03b6...`: three synchronized eight-owner waves matched all 24
normal calls, all 29 terminals matched, and 15 noncanonical review-required
bundles contained 18 selected proposals and 18 server-owned citations. Hosted
head `53ee0152...` passed all 12 checks, and PR #171 merged Coordinator as
`67d836da...`. Exact executable `08b06f6d...` then privately qualified
Auditor's idle-only review-findings core with public-safe evidence SHA-256
`2c1dbc05...`: three synchronized eight-owner waves matched all 24 normal
calls, all 29 terminals matched, and 12 noncanonical review-required reports
contained 15 potential-contradiction findings and 30 server-owned citations.
Active and queued non-idle work blocked admission; Auditor resumed only after
the non-idle work became terminal. Hosted head `937a4129...` passed all 12
required checks, and PR #172 merged Auditor as `1b255e9a...`.

The current protected successor still derives four rapid and eight complex
active limits from the immutable full profiles while retaining one active
request per owner. Exact executable `0665c486...` passed the sequential
lifecycle and `required-workload-routes-qualified`; lock-only `8fee7a5c...`
publishes the matching route lock. The complex profile now owns batch-invariant
execution with seed `0` and prefix caching disabled. Its live probe held eight
and queued the ninth without changing provider/broker identity. The three exact
Analyst repeats prove same-warm-process repeatability, not cross-start/global
determinism. Older route/admission receipts remain historical authority for
their exact heads. None proves simultaneous Qwen/Gemma residency, sustained
capacity/fairness, production SLOs, or deployment.

Calling the foundations "the agent team" would be incorrect. Conversely,
implementing eight unrelated prompts would duplicate authority, bypass
permission-safe retrieval, obscure cancellation, and turn one provider failure
into a product-wide failure. The complete product needs one roster with explicit
triggers, inputs, outputs, route ownership, deadlines, and safe failure behavior.

The organization-owned private server is the canonical team route. The Windows
desktop remains the owner of local controls and supported local/offline
operation. A private-server, provider, agent, or network failure must never
disable capture, raw transcription access, local playback, export, or deletion.

## Decision

Yap will ship the complete eight-agent roster below. Each name denotes a bounded
product workflow, not an autonomous identity and not a generic chat agent.

| Agent | Trigger | Authoritative input | Route | Product output | Failure behavior |
| --- | --- | --- | --- | --- | --- |
| **Scribe** | User requests correction for finalized ASR segments | Immutable raw segment hashes, timestamps, language, and approved terminology snapshot | Rapid automation | Separate source-bound correction revision and visible diff | Return raw ASR unchanged; never overwrite it |
| **Archivist** | Reviewed capture or import becomes eligible for knowledge ingestion | Durable reviewed source admission | No LLM | Deterministic OKF compilation, staging, and provenance | Preserve source and report typed ingestion failure |
| **Student** | User requests learning prompts for an admitted conversation | Permission-safe conversation evidence | Rapid automation when reasoning is needed | Bounded source-cited questions | No questions; retain conversation unchanged |
| **Curator** | User submits a reviewed answer to a Student prompt or explicitly proposes knowledge | Reviewed answer plus source citations and authority | Complex orchestration | Governed proposal only; no direct knowledge mutation | Reject proposal and publish no success audit |
| **Auditor** | Authorized manual run or bounded scheduled review | Immutable audit/review records and current authority | Complex orchestration, idle-only | Source-cited review findings | Defer while hot work is active; never mutate source truth |
| **Librarian** | Authenticated knowledge query | Tenant/subject authorization and active-generation snapshot | No LLM | Permission-safe evidence pack | Typed unavailable/unauthorized result; no hidden-node leakage |
| **Analyst** | Authenticated user requests a grounded answer; the server obtains the current Librarian evidence pack | Server-owned evidence pack and question | Complex orchestration for complex work; rapid route only for its accepted class | Governed cited answer | Evidence-unavailable response; no uncited answer |
| **Coordinator** | Authenticated user explicitly requests a coordination bundle | Caller-owned current open Curator proposals, exact Curator lineage, current source citations, and fixed purpose | Complex orchestration | Server-derived source-cited noncanonical review-required proposal bundle; no autonomous mutation | Evidence unavailable or no bundle; local product remains usable |

### Shared execution rules

1. Rust owns authenticated admission, priority, bounded queues, cancellation,
   provider readiness, overload, and the exact rapid-versus-complex selection.
2. Python owns authorization, source admission, knowledge compilation,
   permission-safe retrieval, governed tools, proposals, audits, and result
   validation behind bounded adapters.
3. Qwen rapid automation and Gemma complex orchestration run as distinct
   supervised services. A route failure is returned as that route's typed
   failure; there is no cross-route model fallback.
4. Both route services remain warm for multi-user work. Request handling never
   launches or swaps a model. Bounded owner-fair admission is required before
   use, and separate owned service nodes are required if one node cannot satisfy
   simultaneous-residency evidence.
5. Every LLM-backed workflow uses structured, bounded, source-referenced input
   and output. A prompt alone is never the correctness boundary.
6. Raw audio, raw ASR, reviewed source records, and active knowledge authority
   are immutable inputs. Agent output is a new revision, proposal, question,
   answer, or finding; it never silently rewrites source truth.
7. Authentication and organization identity terminate in the native/server
   boundary. The renderer never receives a bearer token or calls a provider
   directly.
8. Agent timeouts, cancellation, invalid output, provider unavailability, and
   overload degrade only the requested enrichment. Local capture and controls
   remain available.
9. Every result binds tenant, subject, purpose, source identities, model route,
   model/runtime revision, request identity, and audit outcome without storing
   secrets or exposing private prompts and outputs in public evidence.

### Scheduling classes

- **HOT:** Scribe only. Its product deadline includes queueing and inference;
  deadline failure yields raw ASR. Admission is bounded by the exact ready
  rapid profile and one-active-per-owner rule. The privately qualified current
  candidate admits four distinct rapid-route owners and queues a fifth. This is
  selected-route admission evidence, not simultaneous-model or sustained-
  throughput evidence.
- **INTERACTIVE:** Librarian reads and user-requested Analyst work. Interactive
  work may pause new background admission but does not cancel accepted durable
  work without an acknowledged transition.
- **BACKGROUND_IO:** Archivist compilation and durable projection work; bounded
  independently from LLM queues.
- **BACKGROUND_LLM:** Student, Curator, and Coordinator. One bounded fair queue
  per authenticated ownership policy.
- **IDLE_ONLY:** Auditor. It is never admitted while live or interactive work is
  active.

Priority is not authorization. Every operation must pass its own identity,
purpose, source, generation, and permission checks after scheduling.

### Scribe correction contract

Scribe is transcript correction, not summarization. The server receives only a
bounded ordered set of finalized segments with immutable source hashes. It may
return structured edit operations tied to those hashes and exact source quotes.
The model does not own character offsets: the server derives a Unicode span only
when the quoted text occurs exactly once in the bound segment. Before inference,
the product replaces protected source spans with equal-length ASCII redaction
blocks. The model contract restricts each edit string to 256 characters and asks
for the shortest unique quote. Projection restores the original values only when
every included block run retains its exact length and order. A strictly identical
source/replacement edit normalizes to unchanged; it cannot satisfy correction-
quality thresholds. Model edit strings must first satisfy the exact 256-character
and content bounds. After exact protected-block restoration, identical prefix/
suffix context is reduced to the shortest whole-token quote that remains unique
in the raw segment, so a broad quote cannot inflate the changed-source budget or
bypass the same unique-source and preservation checks.
Approved terminology is immutable context rather than permission to rename a
term. Placeholder presence and instruction-like transcript content do not by
themselves make a response uncertain. A source needing no correction is a
confident unchanged result; uncertainty is reserved for a possible ASR error
that cannot be expressed safely. One contextually obvious nonprotected ASR word
substitution is permitted as a narrow source-bound edit; broad rewriting is not.
The workload intentionally has no audio input; that absence is expected rather
than an uncertainty condition. The raw-source validator then checks full source
coverage; unchanged
ordering and timing; preservation of
names, numbers, dates, units, medication-like terms, and negation unless a
source-bound edit explicitly proves the change; approved terminology use; and
the absence of inserted unsupported content. A valid result is saved as a
separate correction revision with a visible diff. Raw ASR remains authoritative
and exportable. Meeting notes and summaries use separate workflows.

### Delivery and promotion

Implementation proceeds as working vertical slices: exact provider profiles,
authenticated admission, Scribe, source/knowledge agents, knowledge-answering
agents, then complete integration and capacity evidence. A role is delivered
only when its trigger, authorization, persistence, cancellation, invalid-output,
unavailable-provider, restart, teardown, and user-visible behavior are tested.

Private qualification must use representative source-bound workloads. Scribe
promotion requires measured correction benefit plus entity/number/negation,
deletion, hallucination, source-coverage, and p95 latency evidence. Other
LLM-backed agents retain their route-specific tool/citation/correctness gates.
No generic TPS, simultaneous-residency, production-service, enterprise-network,
or deployment claim is authorized without its later exact-head evidence.

Slice 10.2 exact lifecycle head `4b103c1b...` passed both sequential route
lifecycles, exact qualification head `4d623212...` qualified both routes, and
public-lock successor `0471b158...` passed the aggregate governed gate, and
hosted-green head `6d1400cc...` merged through PR #157. Bounded admission head
`7bd93dc6...` qualified both exact routes with public-safe evidence SHA-256
`a75500c344eaa7546695ab1e7415466c031ccf394620ed442ca618ea1ede8c06`;
public-lock successor `135cc2ba...` passed the aggregate gate with public-safe
evidence SHA-256
`350c13a5569cfc7237174d1f7e2132857ffb3aaf28b6afd2eca03aa1999aea79`.
Hosted-green head `cf1e69a4...` merged the bounded admission slice through PR
#158 as `84d95842...`. The Scribe workflow now supplies one
authenticated rapid-route product endpoint and native/UI workflow without
enabling a service or changing the model lifecycle. Its 24-case private
qualification uses English and Spanish real-ASR source evidence, eight distinct
owners, safety fallbacks, exact no-invention preservation, correction benefit,
and queue-inclusive latency. Exact source-lock head `e5858424...` then returned
`scribe-transcript-correction-qualified` with public-safe semantic evidence
SHA-256 `5e187ed4...`; all correction-benefit, preservation, raw-fallback,
latency, warm-generation, broker, database, and teardown checks passed. The
exact rejected attempts remain terminal evidence and were not reused.
Hosted-green head `bc9a88bc...` then merged Scribe through PR #164 as
`ec3af506...`. Exact Archivist source candidate `3ec9885e...` consumes only a
durable owner-scoped reviewed capture, compiles/stages deterministically without
an LLM or activation, and passed focused portable plus real PostgreSQL
restart/idempotency/cross-owner/cancellation/teardown evidence. Hosted-green
head `e1899db7...` merged it through PR #165 as `2a7ec819...`.
Exact product successor `a2e9b551...` composes that core behind authenticated
HTTP jobs, native-owned durable recording/result resolution, and an explicit
renderer **Stage for knowledge** action. Its owner-private ARM64 gate returned
`archivist-authenticated-product-vertical-qualified` with public-safe evidence
SHA-256 `9ec9e373...`: 10/10 exact terminals, 9 staged requests, 1 queued
cancellation, 8 source admissions/staged generations, 0 active generations,
exact replay, and complete teardown. The private gate qualifies the server/
database/broker boundary; native/renderer behavior is exact-head public-test
evidence. Hosted head `69215c43...` passed all 12 required checks, and PR #177
merged the vertical as `e397af8b...`.

The protected profile-capacity successor was then qualified without reducing
either immutable service profile. Exact route head `dab19fe...` returned
`required-workload-routes-qualified` with public-safe evidence SHA-256
`96228914...`; Qwen and Gemma were admitted sequentially and exact teardown
held. Terminal attempts `9551532d...` and `98fb89f9...` exposed respectively a
prompt-refusal/tool-selection phase ambiguity and answer/citation field-
ownership ambiguity; both returned `deterministic-no-model`, remain
inadmissible, and were not reused. Exact workflow head `7cd24deb...` requalified
Scribe with public-safe evidence SHA-256 `9c3c44c5...`, requalified Student with
public-safe evidence SHA-256 `d3561e1a...`, and qualified Curator with public-
safe evidence SHA-256 `b60df1e2...`. Exact public-lock/aggregate head
`7f896b34...` then returned `governed-knowledge-gate-passed` with public-safe
evidence SHA-256 `fd197b98...`.

The batch-invariant successor has a separate exact evidence chain. Executable
candidate `0665c486...` passed the sequential lifecycle with public-safe
evidence SHA-256 `7cc016f4...` and route qualification with public-safe evidence
SHA-256 `06277bd9...`; lock-only `8fee7a5c...` publishes the matching route lock.
At that lock-only successor, Curator, Scribe, Student, and Librarian freshly
qualified with public-safe evidence SHA-256 values `330ddab8...`, `7ef51c6d...`,
`5c2525b3...`, and `ca7ead2a...`; the aggregate gate passed with `5d4b6e10...`.
Analyst qualified at the executable candidate with `940fd7c6...`, three exact
synchronized repeat waves, 24 of 24 normal matches, 29 exact terminals, 12
answers, and 15 server-owned citations. Exact `63c3d9fd...` remains terminal
no-receipt evidence from the prior schedule-sensitive runtime and is not reused.
Hosted head `da1127f8...` passed all 12 checks and PR #170 merged Analyst as
`52c45d22...`. Exact `fed729b3...` privately qualified Coordinator with
public-safe evidence SHA-256 `1bce03b6...`: three exact synchronized repeat
waves, 24 of 24 normal matches, 29 exact terminals, 15 server-derived bundles,
18 selected proposals, 18 citations, exact Curator/current-authority lineage,
one lease per invocation, two PostgreSQL restart/read-backs, and teardown. Exact
`11f325bb...` failed closed before receipt publication on the superseded
deadline-lifecycle verifier and is not reused.

Hosted head `53ee0152...` passed all 12 checks and PR #171 merged Coordinator
as `67d836da...`. Exact `08b06f6d...` privately qualified Auditor with public-
safe evidence SHA-256 `2c1dbc05...`: three exact synchronized repeat waves, 24
of 24 normal matches, 29 exact terminals, 12 server-derived reports, 15
potential-contradiction findings, 30 citations, one lease per invocation,
active/pending non-idle blocking with post-terminal resumption, two PostgreSQL
restart/read-backs, zero proposal writes, and exact teardown.
Hosted head `937a4129...` passed all 12 checks and PR #172 merged Auditor as
`1b255e9a...`, completing the bounded internal roster.

Exact Student candidate `452c8b76...` originally returned
`student-learning-questions-qualified` with public-safe semantic evidence
SHA-256 `3e1ddc61...`. It recorded one synchronized eight-owner wave, unchanged
warm-provider generation and broker identity, real PostgreSQL restart/cross-
owner/audit proof, exact teardown, and the unchanged full Qwen rapid profile.
Post-gate adversarial review then proved that caller-controlled focus text could
provide the target question and that an unsupported premise could pass beside
an unrelated exact citation. That receipt is terminal and inadmissible.

The repaired contract accepts bounded topic text as untrusted context. The
model sees ordered evidence indexes and text and returns exactly one source
subject, evidence index, and support quote; the server selects the frozen
evidence object, binds its complete citation, derives the span, and alone
renders the fixed question template. The prompt now requires an exact
contiguous subject-inside-quote-inside-evidence chain and forbids promoting
topic text that does not occur there. The repair is complete-portable-test green and retains
`0.40` GPU-memory utilization,
four maximum sequences, 8,192 maximum batched tokens, and a 512-token Student
output cap. It adds no request-time launch, model swap, source mutation,
proposal write, knowledge activation, retry, or threshold relaxation. Exact
predecessor `0970d74c...` ran 1,241 portable tests (1,207 passed and 34
declared skips) but then returned terminal `deterministic-no-student` with
public-safe evidence SHA-256 `316631d5...`: seven of eight cases completed,
and one unsupported subject failed closed. Its evidence is not reused. The
earlier `ffe90885...` failure is also terminal and not reused. Exact
`428d6e48...` then passed private qualification with public-safe evidence
SHA-256 `f597cca7...`: all eight owners completed with one grounded question
each and zero terminal failures; the unchanged full warm profile and broker,
PostgreSQL restart/cross-owner/durable audits, and six-part teardown held. This
does not prove product exposure or sustained capacity. Exact
`476f7a9c...` returned terminal `deterministic-no-student` with public-safe
evidence SHA-256 `9c2f68ff...`; six of eight cases completed while the warm
provider/broker, queue wave, database boundaries, and teardown held. Hosted
head `b03c6e79...` passed all 12 checks and PR #166 merged the internal core as
`2254605e...`. The Curator/profile-capacity successor retained exact
qualification at `7cd24deb...`/`7f896b34...`; hosted-green head `593e627b...`
passed all 12 checks, and PR #168 merged it as `284ab96b...`. Hosted head
`7505247e...` then merged Librarian through PR #169 as `d7a7e003...`; hosted
head `da1127f8...` merged Analyst through PR #170 as `52c45d22...`; hosted head
`53ee0152...` merged Coordinator through PR #171 as `67d836da...`; hosted head
`937a4129...` merged Auditor through PR #172 as `1b255e9a...`. Librarian's
product vertical later merged through PR #174; Archivist's product vertical
merged through PR #177. Exact `778a7545...` privately qualified Student, and
hosted head `53ce570b...` merged the product vertical through PR #178 as
`6546970b...`. Exact `6aa33e4d...` privately qualified Curator's product
successor with public-safe evidence SHA-256 `328f6640...`; hosted head
`b983adb7...` passed all 12 checks and PR #179 merged it as `70303872...`.
Exact `78b2c638...` privately qualifies Analyst's product server boundary with
public-safe evidence SHA-256 `f26adfc0...`; Analyst hosted merge plus Coordinator
and Auditor product exposure, warm
simultaneous two-route residency, sustained multi-owner capacity, and production
promotion remain open.
One Spark cannot retain the
unchanged `0.40` Qwen and `0.70` Gemma
profiles simultaneously; a second owned GPU node/private route remains
required for the intended two-route topology.

## Consequences

- The complete roster has one navigable contract and no role can be declared
  shipped from a prompt or persona name alone.
- Existing Phase 9 knowledge owners are reused rather than reimplemented for
  each agent.
- The development renderer-to-Ollama Polish path is removed by the Scribe
  candidate. It is not retained as a fallback or compatibility path.
- Scribe remains useful during remote failure because raw ASR is preserved and
  returned unchanged, not because another unqualified model is selected.
- Full delivery requires multiple reviewed exact-head slices and private
  evidence. This ADR does not itself promote a model, service, capacity, or
  enterprise deployment.

## Rejected alternatives

### Eight independent prompt files over one chat endpoint

Rejected. It has no shared authorization, scheduling, source identity,
cancellation, persistence, or output-validation boundary.

### Treat the Phase 9 Qwen/Gemma routes as the delivered roster

Rejected. Those routes prove bounded reasoning classes and governed tools; they
do not implement the eight product triggers and outputs.

### Keep direct renderer-to-Ollama transcript polishing as local fallback

Rejected. It exposes provider ownership to the renderer and cannot prove
source-bound semantic preservation. Raw ASR is the safe Scribe fallback.

### One model fallback between rapid and complex routes

Rejected. It changes the qualified workload contract and can hide capacity or
correctness failure. Each route fails explicitly.
