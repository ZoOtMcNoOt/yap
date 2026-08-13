# ADR 0031: Eight-agent Voice OS roster and execution boundaries

**Status:** Accepted target; four role cores merged through PR #168; Librarian, Analyst, Coordinator, and Auditor plus product exposure and promotion remain open
**Date:** 2026-08-11
**Deciders:** Yap product and engineering owner
**Amends:** [ADR 0006](0006-silero-agents-state-machine.md),
[ADR 0014](0014-server-tier-compute-topology.md),
[ADR 0017](0017-knowledge-base-compiler.md),
[ADR 0028](0028-model-independent-terminology-authority.md),
[ADR 0029](0029-vllm-agent-reasoning-runtime.md), and
[ADR 0030](0030-rust-supervised-provider-service-lifecycle.md)

## Context

The product architecture names eight agents, but the merged system does not yet
deliver that complete roster. Phase 9 merged the governed knowledge, tool,
retrieval, terminology, and two qualified reasoning-route foundations. Phase 10
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
and PR #166 merged the internal core as `2254605e...`; product exposure remains
open. Exact workflow head `7cd24deb...` then privately requalified Scribe and
Student and qualified the explicit-submission-only Curator core. Curator
returned `curator-knowledge-proposals-qualified` with public-safe evidence
SHA-256 `b60df1e2...`: eight cases/eight owners, four proposals, four
rejections, zero terminal failures, complex capacity eight with a ninth owner
queued, exact PostgreSQL lifecycle/read-back, and teardown. Curator may append
only a noncanonical proposal; it cannot activate or mutate source truth.
Hosted-green head `593e627b...` passed all 12 checks, and PR #168 merged the
Curator/profile-capacity slice as `284ab96b...` on 2026-08-13. Curator product
exposure remains open. Librarian, Analyst, Coordinator, and Auditor remain
pending; no Librarian implementation is claimed.

The current protected profile-capacity successor derives four rapid and eight
complex active limits from the immutable full profiles while retaining one
active request per owner. Exact route head `dab19fe...` returned
`required-workload-routes-qualified` with public-safe evidence SHA-256
`96228914...`; Qwen and Gemma were admitted sequentially on unchanged full
profiles and completed exact teardown. Exact public-lock/aggregate head
`7f896b34...` returned `governed-knowledge-gate-passed` with public-safe
evidence SHA-256 `fd197b98...`. The merged one-slot evidence remains historical
authority for its exact head, not the current candidate boundary. These
selected-route limits are not proof of simultaneous Qwen/Gemma residency,
sustained capacity/fairness, production SLOs, or deployment.

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
| **Analyst** | User requests an explanation from a Librarian evidence pack | Frozen evidence pack and question | Complex orchestration for complex work; rapid route only for its accepted class | Governed cited answer | Evidence-unavailable response; no uncited answer |
| **Coordinator** | User requests cross-conversation planning or an admitted conversation event enables it | Permission-safe conversation summaries, open proposals, and explicit purpose | Complex orchestration | Source-cited plan/proposal, never an autonomous mutation | No plan/proposal; local product remains usable |

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
passed all 12 checks, and PR #168 merged it as `284ab96b...`. Student and Curator
product exposure, warm simultaneous two-route residency, the four remaining
workflows (Librarian, Analyst, Coordinator, and Auditor), sustained multi-owner
capacity, and production promotion remain open. One Spark cannot retain the
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
