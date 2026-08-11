# Architecture Decision Records

This directory holds **Architecture Decision Records (ADRs)** for Yap — short, durable documents that capture significant technical choices, the context behind them, and their expected consequences.

## Numbering

ADRs are numbered sequentially with a four-digit prefix and a short slug:

```
NNNN-short-title-in-kebab-case.md
```

- **0001** is the first record in this repository.
- Numbers are never reused. If a decision is superseded, the original ADR stays in place; a new ADR references and replaces it.
- Gaps in numbering are acceptable if a draft was abandoned before merge.

## Format

Each ADR follows the [Nygard-style](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions) structure used across this repo:

| Section | Purpose |
|--------|---------|
| **Title / Date / Status** | What was decided and whether it is proposed, accepted, deprecated, or superseded |
| **Context** | Forces, constraints, and facts that made a decision necessary |
| **Decision** | The choice itself, stated plainly |
| **Consequences** | Expected outcomes — positive, negative, and neutral |
| **Implementation notes** | How the decision maps to code, rollout, and operational detail (when applicable) |
| **Alternatives considered** | Options that were evaluated and why they were not chosen |

Keep ADRs focused on one decision (or one tightly related cluster). Prefer updating product or design docs for UX copy; use ADRs when the choice has lasting architectural impact.

**Readable synthesis:** [Current architecture](../architecture/CURRENT-ARCHITECTURE.md)
describes the executing system; the [roadmap](../roadmap/ROADMAP.md) owns
accepted future sequencing.

**Implementation audit:** [ADR-IMPLEMENTATION-STATUS.md](../ADR-IMPLEMENTATION-STATUS.md) — current client/server ownership, executable evidence, gaps, and 0–200 scores. Decision acceptance does not imply implementation completeness.

ADRs 0001–0013 cover the original **solo / local-first profile**. ADRs 0014–0018 introduce the **team / server profile**. ADR 0019 amends the local streaming model choice. ADR 0020 reconciles meeting capture, local anonymous speaker evidence, server-authoritative diarization, and identity privacy across both profiles. Later ADRs supersede conflicting details in earlier records.
ADR 0021 makes HTTP/3 the gated long-term client-facing transport target while preserving the bounded loopback service and TCP fallback.
ADR 0022 adopts pinned Google OKF v0.1 for Phase 9, requires a Postgres/pgvector plus typed-relationship baseline, and defines permission-safe projection gates for an optional Neo4j challenger without making any database the knowledge or authorization source-of-truth.
ADR 0023 amends ADR 0014's absolute live-priority rule with bounded live preference so an always-ready interactive queue cannot starve accepted batch work.
ADR 0024 defines the Phase 6 global language/provider capability catalog, primary-language and guarded LID policy, explicit Nemotron dynamic mode, and fail-closed timing evidence.
ADR 0025 replaces the proposed common Triton ASR plane with provider-specific
serving: Cohere batch on vLLM, Nemotron's current Transformers reference and
separately gated resident NeMo streaming candidate, local Nemotron on
sherpa-onnx, and ADR 0029's vLLM runtime for the active Phase 9 Qwen/Gemma agent
workload routes.
ADR 0026 replaces the executing SpeechBrain batch-language preflight with one
verify-only AmberNet artifact and a strict five-region, user-confirmed policy.
ADR 0027 selects Tiron as the Phase 8 server baseline for joint
speaker-attributed meeting transcription while preserving Yap's local
anonymous-speaker path and model-independent result authority. The server has
one Tiron source-time epoch route; a failed promotion gate remains explicit
rather than invoking a duplicate diarization fallback.
ADR 0028 makes terminology a model-independent, owner-scoped, immutable job
authority. ADR 0029 removes SGLang from the executing path and assigns Qwen 3.6
rapid automation plus Gemma 4 complex orchestration to route-specific vLLM
runtimes rather than one universal image. Exact private head
`36350d449735a4daea6546e16759f28f6f15631a` qualified those two workload routes;
exact aggregate candidate `a4f34678ea9980379b18266d40d3347b818ac57e`
then admitted the hash-locked private tree and passed the complete Phase 9 gate
with public-safe evidence SHA-256
`4013903410e22206c5b46f4dfcbf1878badc3dc9bbdfddb0ddad2ba0e2ff3260`.
Exact hosted-green head `fa26caaf7e3ea4e20f27b390355dff80bee2464f`
merged through PR #152 as `ae81ff067c73a64528eecc14403765562726f2fe`;
production supervision and capacity remain Phase 10.
ADR 0030 makes systemd plus one Rust supervisor the production provider
lifecycle boundary. ADR 0031 defines the complete eight-agent roster as bounded
product workflows across that supervised private-server route while preserving
raw/local controls and prohibiting renderer-owned provider access or silent
cross-route fallback. Merged Slice 10.2 binds the exact Qwen/Gemma profiles and
passed sequential lifecycle, fresh private route qualification, aggregate
governed, and hosted gates through PR #157. Exact local head `9b14beff...` adds
the bounded owner-fair admission substrate for already-warm services; native/
server integration, warm simultaneous residency, roster workflows, and
promotion remain open.

## Applicability and precedence

Use ADRs in this order:

1. A `Superseded` decision is historical and never authorizes implementation.
2. A later explicit `Amends` or `Supersedes` clause wins over an earlier conflicting detail.
3. ADRs 0014–0031 define the canonical client/server architecture and phase map. Earlier ADRs remain authoritative only for the principles or deployment profile their status names.
4. [Current architecture](../architecture/CURRENT-ARCHITECTURE.md),
   [current status](../CURRENT-STATUS.md), and the
   [roadmap](../roadmap/ROADMAP.md) are readable syntheses; they cannot silently
   override an ADR.
5. Build specs describe implementation. A `Draft` spec is not permission to ship a model, dependency, protocol, data-retention rule, or external surface absent an accepted ADR.

Every implementation plan must list its applied ADRs, superseded details it intentionally ignores, deferred decisions, exact acceptance tests, and phase boundary. Exact model/runtime names in a principle-only or historical ADR are benchmark candidates rather than defaults.

## Index

| ADR | Title | Status |
|-----|-------|--------|
| [0001](0001-dual-stt-backends.md) | Dual STT backends: streaming live, server batch | Accepted principle; runtime/model amended by [0014](0014-server-tier-compute-topology.md) and [0019](0019-local-streaming-model-selection.md) |
| [0002](0002-crispasr-unified-stt-runtime.md) | CrispASR unified STT runtime (warm daemon + GGUF) | Historical runtime; active local path superseded by [0019](0019-local-streaming-model-selection.md) |
| [0003](0003-long-term-voice-architecture.md) | Long-term voice OS — recordings, SpeechBrain LID, roadmap | Accepted principles; phase map superseded by the canonical Voice OS roadmap and language details amended by [0024](0024-global-language-routing.md) |
| [0004](0004-background-diarization-okf-agents.md) | Background pipeline — diarization, micro-batches, OKF, agents | Accepted for non-diarization principles; diarization superseded by [0020](0020-meeting-capture-diarization-authority.md) |
| [0005](0005-llama-server-agents.md) | Bundled llama-server for LLM agents (CPU-first) | Accepted for solo/local; team execution amended by [0014](0014-server-tier-compute-topology.md) |
| [0006](0006-silero-agents-state-machine.md) | Silero VAD, agent profiles, runtime state machine | Accepted principles; active routing amended by [0014](0014-server-tier-compute-topology.md), [0019](0019-local-streaming-model-selection.md), and [0020](0020-meeting-capture-diarization-authority.md) |
| [0007](0007-forced-alignment-engine.md) | Forced-alignment engine for word→speaker | Accepted raw-alignment principle; engine and promotion gates amended by [0024](0024-global-language-routing.md) |
| [0008](0008-speechbrain-lid-gate.md) | SpeechBrain LID language gate | Accepted user-gate principle; executing model, runtime, delivery, probes, and threshold superseded by [0026](0026-ambernet-batch-language-preflight.md) |
| [0009](0009-knowledge-worker-protocol.md) | Knowledge worker IPC protocol | Solo/local only; team protocol superseded by [0017](0017-knowledge-base-compiler.md) |
| [0010](0010-okf-conversation-schema.md) | OKF conversation schema | Accepted Markdown/YAML and raw-preservation principles; canonical Phase 9 format superseded by [0022](0022-google-okf-permission-safe-projections.md) |
| [0011](0011-vector-rag-retrieval.md) | Vector index + RAG retrieval (L6–L7) | Accepted principles; team storage/projection amended by [0017](0017-knowledge-base-compiler.md) and [0022](0022-google-okf-permission-safe-projections.md) |
| [0012](0012-mcp-server-surface.md) | MCP server surface | Accepted surface; team hosting amended by [0017](0017-knowledge-base-compiler.md) |
| [0013](0013-global-hotkey-injection.md) | Global hotkey + safe cross-app delivery (L1) | Accepted as amended 2026-07-14 (Windows clipboard delivery active; cross-platform follow-on) |
| [0014](0014-server-tier-compute-topology.md) | Server-tier compute topology — thin client + GB-class workload router | Accepted (canonical Phases 3–5) |
| [0015](0015-two-pass-diarization-speaker-identity.md) | Two-pass diarization and speaker identity (ECAPA-TDNN + VBx) | Superseded by [0020](0020-meeting-capture-diarization-authority.md) |
| [0016](0016-auth-identity-bridge.md) | Authentication and voice identity bridge (Entra ID + MSAL) | Accepted (canonical Phase 7) |
| [0017](0017-knowledge-base-compiler.md) | Team knowledge base — source-of-truth, compiled disposable indexes, permission model | Accepted (canonical Phase 9; format and projection amended by [0022](0022-google-okf-permission-safe-projections.md)) |
| [0018](0018-three-repo-topology.md) | Three-repo topology (`yap-desktop` / `yap-server` / `yap-knowledge`) | Accepted (roadmap — canonical Phase 10) |
| [0019](0019-local-streaming-model-selection.md) | Local streaming model selection — Nemotron INT8 client fallback | Accepted (canonical Phase 2) |
| [0020](0020-meeting-capture-diarization-authority.md) | Meeting capture and diarization authority | Accepted (canonical Phase 8) |
| [0021](0021-http3-secure-edge-transport.md) | HTTP/3 transport evolution at the secure edge | Accepted (roadmap - gated after the Phase 5 remote transport and Phase 7 authentication baselines) |
| [0022](0022-google-okf-permission-safe-projections.md) | Google OKF and permission-safe knowledge projections | Accepted (canonical Phase 9 knowledge format and projection boundary) |
| [0023](0023-bounded-live-priority.md) | Bounded live priority in the server workload router | Accepted (amends ADR 0014 priority rule) |
| [0024](0024-global-language-routing.md) | Global language routing and timing evidence | Accepted decision; provider serving amended by [0025](0025-provider-specific-asr-serving.md) and batch preflight amended by [0026](0026-ambernet-batch-language-preflight.md); exact candidate `a92f338546a2f8bbaded96b04f8987f0ac475c88` passed the complete local/private matrix; hosted CI, CodeQL, and stock-NSIS passed on docs-only review head `cee13f819a85417ea43a3c63e263be85f0570838`; final exact-head read-back/merge and later promotion remain controlled in PR #67 |
| [0025](0025-provider-specific-asr-serving.md) | Provider-specific ASR serving runtimes | Accepted; Cohere vLLM, resident Nemotron NeMo, and all 18 candidate-safety children passed inside exact candidate `a92f338546a2f8bbaded96b04f8987f0ac475c88`; both services remain unpromoted and broad quality evidence stays open |
| [0026](0026-ambernet-batch-language-preflight.md) | AmberNet batch language preflight | Accepted; exact candidate `a92f338546a2f8bbaded96b04f8987f0ac475c88` passed the source-exact ARM64 lifecycle, connected route, and complete matrix; representative suggestion quality remains open |
| [0027](0027-tiron-joint-speaker-attributed-meeting-transcription.md) | Tiron joint speaker-attributed meeting transcription | Accepted Phase 8 explicit Preview baseline; PR #142 merged Preview, PR #143 merged maintainability closure, PR #144 merged the sole source-time route, and PR #150 merged the `unadvertised-baseline` qualification closure. No fallback or production claim was added. |
| [0028](0028-model-independent-terminology-authority.md) | Model-independent terminology authority and frozen projections | Accepted; merged Phase 9 has server-derived ownership, immutable job snapshots, bounded projections, revocation, governed-agent consumption, and a passed complete gate; production UI and operations remain open |
| [0029](0029-vllm-agent-reasoning-runtime.md) | vLLM agent reasoning runtime on DGX Spark | Accepted; exact-head private Qwen rapid/Gemma complex route qualification and aggregate Phase 9 admission passed and merged through PR #152; the post-Phase-9 checkpoint gate passed at `22c3f369...` and hosted head `84c22ec9...` merged through PR #153; production serving, simultaneous residency, and sustained capacity remain Phase 10 |
| [0030](0030-rust-supervised-provider-service-lifecycle.md) | Rust-supervised provider service lifecycle | Accepted Phase 10 target; Slices 10.1 and 10.2 merged the hardware-independent systemd/Rust/foreground-launcher boundary and immutable Qwen/Gemma profiles through PRs #155 and #157; admission integration and capacity remain later slices |
| [0031](0031-eight-agent-voice-os-roster.md) | Eight-agent Voice OS roster and execution boundaries | Accepted Phase 10 target; exact local head `9b14beff...` implements the bounded multi-user admission substrate for already-warm routes; product workflows, qualification, capacity, and production promotion remain pending |

**Build specs** (how, not why): [docs/specs/](../specs/) — STT sidecar, LLM sidecar, live UX, testing.

**Readable synthesis:** [Current architecture](../architecture/CURRENT-ARCHITECTURE.md)
and [executable ownership](../architecture/boundaries/EXECUTABLE-OWNERSHIP.md)
