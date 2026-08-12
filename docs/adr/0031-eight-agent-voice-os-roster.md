# ADR 0031: Eight-agent Voice OS roster and execution boundaries

**Status:** Accepted target; service profiles and bounded admission merged, Scribe candidate implemented, remaining workflows and promotion pending
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

The current Scribe candidate is the first application workflow to consume the
merged owner. It removes the development renderer-to-Ollama Polish prototype
and replaces unrestricted rewriting with authenticated source-hashed finalized
segments, structured edits, server-bound terminology, native-owned immutable
publication, visible diff, and raw-ASR fallback. Its public matrix is green;
private bilingual/multi-owner qualification and aggregate admission remain
pending. The other seven named roles remain documented targets rather than
executing product workflows.

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

- **HOT:** Scribe only. One admitted request. Its product deadline includes
  queueing and inference; deadline failure yields raw ASR.
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
return structured edit operations tied to those hashes and spans. The product
validates full source coverage; unchanged ordering and timing; preservation of
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
#158 as `84d95842...`. The current Scribe candidate now supplies one
authenticated rapid-route product endpoint and native/UI workflow without
enabling a service or changing the model lifecycle. Its 24-case planned private
qualification uses English and Spanish real-ASR source evidence, eight distinct
owners, safety fallbacks, exact no-invention preservation, correction benefit,
and queue-inclusive latency. That qualification has not yet been consumed.
Warm simultaneous residency, the other seven product workflows, sustained
multi-owner capacity, and production promotion remain open.

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
