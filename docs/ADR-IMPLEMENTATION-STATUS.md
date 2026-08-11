# ADR implementation status

**Status:** Living, non-normative implementation audit
**As of:** 2026-08-10; Phases 3–9 and Architecture Checkpoints A/B are closed and
their checked-head evidence remains recorded below. Patched post-Phase-8
meeting-transcription maintainability candidate
`393710999b53a4bd1b00639e30c0fec88b152530` passed its exact-head lifecycle,
single complete 18-child matrix, independent receipt validation, and required
CI and CodeQL jobs. PR #143 merged the reviewed closure as
`8fb511ad2fd7217a87e95ddba31d74dfa474fac2`. Exact Phase 6
executable candidate `a92f338546a2f8bbaded96b04f8987f0ac475c88` passed its frozen
30-child local/native/server/private-runtime gate. Its target-client evidence
passed 12/12 paced cycles, all nine short-boundary cases, the unattended
release-mode microphone/UI lifecycle, and complete teardown. Its GB10 evidence
passed ADR 0025's composed 18-child Cohere vLLM/Nemotron NeMo lifecycle; its
connected evidence proved durable preprocessing, five-window AmberNet
preflight, tunnel interruption/recovery, server-authoritative publication,
verified History review, and complete local/remote teardown. The candidate
receipt was independently validated for the exact head and all 30 children and
has SHA-256
`74f183041082c77d05a0633202fa1052222d6a77bd9bef5ce2706546bf3e9647`.
The automatic local route remains explicit default-off Preview behavior because
its frozen natural-switch quality target failed. The catalog intentionally
exposes only gated Cohere `en-US` with `wordAlignment: false`; neither resident
provider is promoted. The repaired implementation passed the required bounded
three-agent adversarial re-review. Hosted CI, CodeQL, and stock-NSIS passed at
first attempt on final reviewed head
`50f0f9e5e3cf288f41efa3745514dd08c9ee1929`; PR #67 merged as
`87c8654250cba8b9eafa5007bf719c52e4749cdf`.
Exact Phase 9 candidate `a4f34678ea9980379b18266d40d3347b818ac57e`
passed its complete governed-knowledge gate. Exact hosted-green head
`fa26caaf7e3ea4e20f27b390355dff80bee2464f` then merged through PR #152 as
`ae81ff067c73a64528eecc14403765562726f2fe`. The separate post-Phase-9
maintainability checkpoint is active and does not inflate the evidence scores
below.
Post-Phase-6 Checkpoint B changes no ADR score. Historical candidate
`66267af0abf38af0a6b8d3d2fac76543673c0331` and consumed hosted head
`08ab49ba8d727cb8331a40f28c7c4c70d75d4035` retain their recorded evidence
but are not merge authority. After repairing the hosted Cargo color
contamination and same-process Windows atomic replacement race, fresh exact
executable candidate `9dfa8a68b02cdf854d14fb046e51a166cd3da353`
passed its single admitted 31-child checkpoint matrix and independent receipt
validation with exact teardown. The frozen manifest SHA-256 remains
`2641f613a2a8dfbf0d2e1c7989b37c3af7e85aab732c3ae20381b52c1d144ac2`;
the private receipt SHA-256 is
`6b02bd04cb3ce3c25925c2b2be8cc2f3c20f79478513fe41519f666a498114e7`.
First-attempt hosted CI, CodeQL, and stock-NSIS passed on documentation-only
reviewed head `0bd11ae8dea34cd22029c6c09a9fd62a5951a363`; PR #68 merged as
`15f9c8ac00211b9d2f28845d419258ae2c8de8e4`. Checkpoint B changed no ADR
score.
Phase 7 merged as `66d314d7`; its adversarial checkpoint closed at `ef6d977`,
and concrete follow-ups closed at `1a6f06e` and `589197e`. Executable evidence
covers the provider-neutral OIDC verifier with Entra policy, fail-closed
authentication defaults, tenant-scoped ownership, authenticated bounded private
WebSocket admission, and the qualified native lower handshake. Exact
application/runtime candidate `dc635916...` passed its complete private 25-cell
matrix and independent receipt validation. PR #69's final hosted head did not
have an all-green rollup, so this audit does not retroactively label it green.
Purpose grants and revocation remain reachable only from tests. A Windows WAM
adapter is compiled behind explicit opt-in but is neither approved nor selected
by default; real tenant policy and provider conformance remain IT handoffs.
Phase 8 adds an explicitly configured Tiron meeting candidate through the
existing authenticated job and native publication boundaries.
Exact application/runtime candidate
`1c69b61cf2902c9cfda50c6158168890974f969f` passed the supported-launcher
client/HTTP/Tiron/native/History roundtrip and the one admitted
local/native/server/GB10 Preview matrix. Protected aggregate receipt SHA-256
`9f647b3a968ae31ab4b7f869bda160177b665747a3be5deecdde11399919e154`
binds the exact immutable image, subordinate receipt hashes, lane counts, and
reviewed test/gate-only descendant `9ff06d7d...`. It does not claim model
promotion, managed discovery, live ASR, production SSO, or an enterprise edge.
Reviewed head `ec4e4ab46234c35555136a75da530c6d73a042d8` passed hosted CI and
CodeQL before PR #142 merged as
`4201c5e7f1674dc0b15e76241bc308c49a5719bb`. Historical ownership and
maintainability candidate `fb0985e7c08cf0a0e69752afbe61e372cbfe76db`
passed its checkpoint, but documentation-only successor `e22368fc...` exposed
`GHSA-mwp4-54f8-5fhr` and did not close. Patched development-only `ip-address`
10.3.1 changed the lockfile, so replacement candidate
`393710999b53a4bd1b00639e30c0fec88b152530` received a fresh admission. It
passed the canonical native build, receipt-bound image preflight, real History
and cancellation lifecycle with independent teardown, its single complete
18-child matrix, independent receipt validation, and all required CI and
CodeQL jobs. PR #143 merged the reviewed closure as
`8fb511ad2fd7217a87e95ddba31d74dfa474fac2`; this changed no ADR score or
model/runtime qualification claim.
PR #144 subsequently merged the sole source-time route as
`b5b52bfd297edf1e95d93e120a8e59c206f7ab77`. Exact qualification candidate
`3ddb930268b544d2cae80d4389f12ef315b35ded` recorded
`unadvertised-baseline` because the independently reviewed private holdout was
unconfigured. No image preparation, GPU inference, catalog promotion, or ADR
score increase was justified. PR #150 passed every hosted CI and CodeQL check
at exact head `2ab33ae6bd27b2002a539a6cb89dd55eb16eac6b` and merged as
`599a0d0b`.

**Authority:** ADRs define decisions; current code and executable tests define implementation truth.

An ADR can be accepted while its implementation score is zero. Superseded ADRs remain in the table for historical completeness, but a low score on a superseded decision is not backlog authorization.

## Score scale

| Score | Meaning |
|------:|---------|
| **0** | Plan only, or intentionally unimplemented because a later ADR superseded it |
| **50** | Useful skeleton, contracts, or isolated prerequisites |
| **100** | Partial working path with major end-to-end gaps |
| **150** | Usable baseline with hardening, platform, fixture, or release gaps |
| **200** | Production/release ready across the ADR's stated scope |

Scores are evidence-based estimates, not percentages. The owner column uses **Client**, **Server**, or **Shared** for the canonical boundary; historical solo/team differences are called out in the row.

## Complete ADR audit

| ADR | Decision status / precedence | Owner | Score / 200 | Implemented evidence | Missing or blocking evidence | Next canonical gate or replacement |
|-----|------------------------------|-------|------------:|----------------------|------------------------------|------------------------------------|
| [0001](adr/0001-dual-stt-backends.md) | Live fallback vs official batch principle retained; model details amended by 0014/0019 | Shared | **150** | In-process pinned Nemotron live fallback plus the gated Phase 5 durable loopback batch path through the isolated Cohere worker with verified native result publication; Phase 7 added authenticated private WebSocket admission without an ASR route | No server live ASR, approved production identity adapter, persistent production service, external secure edge, general media conversion, or measured production capacity | Retain the two-route policy while later phases harden transport, identity, media preparation, and deployment |
| [0002](adr/0002-crispasr-unified-stt-runtime.md) | Historical; replaced by 0019 | Client | **0** | No tracked or wired CrispASR runtime | Entire retired runtime path absent by design | Do not revive; use 0019 |
| [0003](adr/0003-long-term-voice-architecture.md) | Long-term principles retained; runtime, meeting, language, knowledge, and agent details amended by 0013/0014/0017/0019/0020/0022/0024/0028/0029 | Shared | **100** | Capture, local ASR, overlay, history, hotkeys, safe Windows delivery, gated loopback server batch, language evidence, meeting-result authority, deterministic OKF/terminology compilation, permission-safe Postgres/pgvector retrieval, governed tools, and privately qualified vLLM workload routes cover the merged product through Phase 9. | No promoted multilingual/live server routes, persistent supervised production deployment, simultaneous agent-model residency, sustained mixed-user capacity, external secure edge, enterprise operations, or final release evidence. | Complete the post-Phase-9 checkpoint, then follow the canonical Phase 10 plan rather than the historical phase map. |
| [0004](adr/0004-background-diarization-okf-agents.md) | Non-blocking background principles retained; diarization details superseded by 0020 | Shared | **100** | Independent bounded sinks, track/gap/chunk contracts, crash-safe recording, source-bound meeting evidence, deterministic reviewed-result-to-OKF compilation, immutable terminology, permission-safe retrieval, governed proposal/RAG/MCP tools, and explicit vLLM workload routes now execute in merged Phase 9. | No promoted local speaker model, purpose-authorized speaker naming entry point, production agent service, sustained capacity, or enterprise operations. | Preserve 0020/0027 authority for speaker work and 0017/0022/0028/0029 for knowledge/agents; do not revive superseded details during the maintainability checkpoint. |
| [0005](adr/0005-llama-server-agents.md) | Accepted target; team placement amended by 0014 | Shared | **20** | Development-only Polish flow exists | Polish still calls Ollama; no bundled llama-server, manager, model pin, health gate, or profiles | Implement only when local/server LLM product work is activated |
| [0006](adr/0006-silero-agents-state-machine.md) | Accepted principles; routing and preprocessing amended by 0014/0019/0020/0024 | Shared | **100** | Connector state/capability projection, single warm Nemotron lifecycle, durable client/server stage attempts, and an explicitly installed/hash-verified Silero ONNX path now produce bounded advisory source-time intervals for imported canonical WAV while retaining complete source audio; the speculative unused umbrella orchestrator was removed during Checkpoint A | No live-microphone Silero/chunker, agent registry, LLM mutex/queue, or authenticated live-ASR transition | Preserve advisory source retention; later live endpointing and LLM gates retain domain-owned orchestration |
| [0007](adr/0007-forced-alignment-engine.md) | Raw-transcript alignment principle retained; exact engine and promotion gates amended by 0024 | Shared | **100** | A bounded English Cohere decoder-attention candidate executes behind the provider capability gate with FP32 Q/K reconstruction, finite filtering, monotonic DTW, raw-transcript reconciliation, source-bounded aligned-word validation, and typed fail-closed unavailable results. Focused contract tests and a contained Python 3.12/GB10 proof produced WER 0.0, 23 deterministic source-bounded words, a 159 ms warm path, and measured peak GPU allocation. | `wordAlignment` remains false; no frozen checked-head latency/memory, representative boundary-error/accuracy, multilingual, or production-promotion evidence exists | Keep unsupported or failed routes explicitly unavailable; run the full promotion workload only if a later selected provider proposes alignment, and evaluate any multilingual challenger separately |
| [0008](adr/0008-speechbrain-lid-gate.md) | User-gated LID principle retained; executing model/runtime/delivery/probes/scores superseded by 0026 | Shared | **100** | Explicit suggestion-only semantics, manual fallback, durable evidence, restart cancellation, and mandatory user confirmation execute through the current provider-neutral preflight boundary. The old SpeechBrain two-probe GB10 receipt at `04266c4bbffd0fd31eaf2afd0bcce42e0248344f` remains historical containment evidence. | SpeechBrain is no longer the executing component; representative advertised-locale suggestion evidence remains open under ADR 0026. | Preserve the user-gate principle; do not revive the superseded SpeechBrain runtime or two-probe policy. |
| [0009](adr/0009-knowledge-worker-protocol.md) | Solo protocol retained historically; team transport superseded by 0017 | Shared | **10** | Capture/chunk prerequisites exist | No worker, socket protocol, lifecycle, backpressure events, quarantine, or stitcher | Team work follows 0017; solo worker remains deferred |
| [0010](adr/0010-okf-conversation-schema.md) | Accepted Markdown/raw-preservation principles; historical schema superseded by 0022 | Shared | **100** | Durable transcripts and immutable result revisions now feed a pinned Google OKF v0.1 validator/compiler with the Yap profile, deterministic concepts/relationships/provenance, lossless unknown frontmatter, and permission-safe terminology glossary projection. Exact candidate `a4f34678...` passed the complete Phase 9 gate and PR #152 merged it. | The historical schema itself is not revived; production source-ingestion operations remain open under ADR 0022. | Use the executing ADR 0022 profile without reviving the historical schema. |
| [0011](adr/0011-vector-rag-retrieval.md) | Accepted retrieval principles; team projection amended by 0017/0022 | Server | **150** | Merged Phase 9 compiles deterministic chunks, stores complete model/revision-bound embedding maps, stages atomic Postgres/pgvector generations, exposes lexical/vector/hybrid and bounded relationship retrieval, filters by server-derived principal/purpose/generation before return, rechecks every result, emits exact citations, and feeds only governed results to RAG. Exact candidate `a4f34678...` passed the complete gate, including nine zero-skip Postgres tests and post-restart cited retrieval; PR #152 merged it. | Production supervision, calibrated production ranking/SLOs, sustained multi-owner capacity, observability, and external deployment remain open. Neo4j was deliberately not admitted because no measured baseline gap justified it. | Keep production service/capacity and any measured challenger in Phase 10. |
| [0012](adr/0012-mcp-server-surface.md) | Accepted Phase 9 target; team hosting amended by 0017 | Server | **100** | A typed MCP adapter exposes the same governed search, traversal, answer, and proposal contracts as the in-process agent route. Server-derived principal/agent authority, purpose, bounded inputs/outputs, cancellation, citations, audit identities, and tests prevent MCP from broadening repository, SQL, vector-index, or private-evidence access. Exact candidate `a4f34678...` passed the complete Phase 9 contract gate and PR #152 merged it. | No production MCP transport/service, enterprise client enrollment, external auth/network surface, operational supervision, sustained capacity, or deployment approval exists. | Production transport and enterprise enablement remain Phase 10/IT work. |
| [0013](adr/0013-global-hotkey-injection.md) | Accepted as amended 2026-07-14 and 2026-07-25; Windows hotkey and safe-delivery implementation active | Client | **180** | Dual safe defaults, native-confirmed 15-second physical-chord enrollment with neutral/chord/release and modifier floors, normalization and reserved/conflict rejection, Cancel/per-action Reset, transactional registration rollback, fixed-capacity two-worker shortcut dispatch, one exact-bounds island that remains unfocused on show/hover but accepts explicit keyboard focus, primitive-wide reduced-motion suppression, clipboard-only delivery with Yap HWND ownership and visible paste guidance, focused native WDIO, stock installer contract, and a passing hosted disposable-Windows lifecycle | No macOS/Linux hotkey/clipboard adapters, broad real-app clipboard matrix, exact-field authority for safe direct insertion, or verified local real-model/hardware lifecycle on this machine | Expand native compatibility and hardware evidence without reintroducing synthesized input without exact-field authority |
| [0014](adr/0014-server-tier-compute-topology.md) | Canonical server topology, amended/constrained by 0016/0019/0020/0021/0023/0024/0025/0027 | Shared | **150** | Versioned contracts, bounded loopback capability API, validated connector with serialized settings publication, consent-gated fixed-loopback discovery that never scans or connects automatically, durable desktop/server job state, canonical-WAV preparation, descriptor-bound exact artifact reads, reconnect drain, verified result publication, hardened bootstrap, immutable Cohere/NGC/Python 3.12 locks, verified ASR catalog projection, the gated one-running/two-queued raw Transformers GB10 slice, pinned Nemotron reference adapters, resident Cohere vLLM and NeMo workers/services/images/launchers, privacy-safe repeated-fixture duration controls through the exact four-hour boundary, and an exact-source production-preprocessed AMI close/far long-meeting comparison. Exact candidate `a92f338546a2f8bbaded96b04f8987f0ac475c88` passed the composed 18-child provider lifecycle and complete 30-child Phase 6 matrix; retired Triton and non-executable reference-router results remain historical evidence. Phase 7, merged at `66d314d7`, replaces fixed development ownership with validated `(tid, oid)` principals in Entra mode, owner-scopes the job/LID boundary, and adds authenticated bounded private WebSocket admission on a separate loopback port plus a qualified native lower handshake. Its reviewed lifecycle launches resident providers, the sampler, and the loopback proxy behind a release barrier with a retained pidfd and exact child reap instead of treating exec-time environment visibility as initial ownership; it also canonicalizes the GB10 `socat` package link before container mutation. Exact application/runtime head `dc635916...` passed the complete private matrix; its reviewed descendants are confined to hosted/gate tooling, contracts, and documentation. Phase 8 merged the explicit ADR 0027 Tiron meeting Preview through PR #142 without replacing either provider-specific dictation candidate. | No provider has been promoted; no selected persistent warm production pool, general media conversion, live ASR pool, managed LAN/enterprise or live-endpoint discovery, external same-origin WSS/TLS/QUIC edge, independently reviewed representative long-recording promotion benchmark, sentinel-rich long-form quality result, rollback result, or measured multi-worker/mixed-load capacity exists. Enterprise networking and identity conformance remain IT handoffs. | Preserve the gated provider-neutral boundary and merged meeting Preview; require new independent evidence for model promotion or replacement, then implement external batch/WSS transport, persistent warm pools, observability, and measured multi-owner mixed-load capacity in Phase 10 |
| [0015](adr/0015-two-pass-diarization-speaker-identity.md) | Superseded by 0020 | Server | **0** | No implementation of the retired ECAPA/VBx design | Entire retired design absent by intent | Do not implement; use 0020 |
| [0016](adr/0016-auth-identity-bridge.md) | Canonical Phase 7 decision; speaker-purpose use remains gated and KB persistence is sequenced to Phase 9 | Shared | **150** | The merged implementation has a provider-neutral OIDC JWT verifier and discovery/JWKS boundary with an Entra-specific tenant/audience/scope/client/role policy; fail-closed default authentication with an explicit development-only loopback mode; token-derived `(tid, oid)` principals; a provider-neutral identity repository with SQLite development storage; durable access disable/restore; role-gated purpose grant/revoke operations and enrollment/matching/adaptation purpose checks that are implemented and unit-tested but called by nothing outside tests; owner-scoped job/LID/idempotency/artifact access; non-disclosing lookup behavior; authenticated bounded private WebSocket admission with expiry/revocation enforcement; a narrow in-process native token-provider seam that keeps bearer material out of React and ordinary persistence; and local-first desktop setup that does not depend on server or auth availability. A WAM adapter exists behind explicit opt-in but is not selected. Exact application/runtime head `dc635916...` passed the complete private 25-cell matrix and independent receipt validation; its adversarial checkpoint closed at `ef6d977`. | No approved production native token adapter, real tenant registration, Conditional Access/MFA/consent conformance, production identity database/audit sink, live ASR route, managed LAN/enterprise or live-endpoint discovery, external same-origin WSS/TLS/HTTP/3 edge, or IT-owned deployment evidence. Purpose enforcement and access revocation have no HTTP or operator entry point, so `access_disabled` and grants can be changed only by editing `identity.sqlite` directly | Keep the unreachable purpose layer out of product claims. A future purpose-authorized speaker reconciliation/naming workflow must either supply a reviewed entry point or delete unused machinery; real-provider conformance remains a Phase 10/IT handoff |
| [0017](adr/0017-knowledge-base-compiler.md) | Canonical team KB/compiler decision; format/projection amended by 0022 | Server | **150** | Merged Phase 9 consumes reviewed immutable captures/documents, compiles deterministic OKF concepts/chunks/relationships/permissions/provenance, stages and validates non-active Postgres generations, atomically advances the active pointer, preserves rollback/history/retention, and exposes permission-safe retrieval and immutable proposals. Exact candidate `a4f34678...` passed the complete gate, including a real owned Postgres process restart, recovered cited retrieval, stale-generation rejection, successor retrieval, and exact teardown; PR #152 merged it. | Production database topology, backup/restore, encryption, monitoring, repository split, external transport, and IT-managed lifecycle do not exist. | Defer production operations and repository extraction to Phase 10. |
| [0018](adr/0018-three-repo-topology.md) | Accepted eventual topology; staged monorepo retained through MVP | Shared | **45** | `desktop/`, `server/`, `infra/`, and `docs/` staging layout now contains an executable client/server batch boundary without premature repo extraction | No three-repo split, independent CI/CD/access controls, link migration, or cross-repo version policy | Split only at Phase 10 after deployable server/knowledge boundaries |
| [0019](adr/0019-local-streaming-model-selection.md) | Canonical single-ASR client fallback decision; narrowly amended by 0024 for one auxiliary acoustic-LID component | Client | **180** | Pinned model revision/SHA artifacts, in-process sherpa Nemotron, warm lifecycle, setup controls, profiler, native tests, local release/packaging contracts, a passing hosted stock-NSIS lifecycle, verified sherpa/native-runtime plus Silero provenance, and one `LiveRuntime`-owned optional resident LID/span/handoff implementation. Exact candidate `a92f338546a2f8bbaded96b04f8987f0ac475c88` passed the target-client and complete Phase 6 matrices. | No completed Nemotron model-artifact license review, local-Nemotron use of the licensed speech/WER fixture, real-model CI accuracy smoke, cross-platform evidence, distributable AmberNet artifact, default-on automatic switching, or low-end physical battery/thermal certification | Preserve one local ASR lifecycle owner and the explicit default-off Preview; require new independent quality and release evidence before broader promotion. |
| [0020](adr/0020-meeting-capture-diarization-authority.md) | Canonical meeting/capture/identity authority; server baseline selected by 0027 | Shared | **100** | Source-aware sessions/tracks, exact gaps, bounded sinks, crash-safe recording/recovery, one-worker bounded native-drop admission with an exclusive picker lease, gated canonical-WAV upload/reconnect, verified server-authoritative transcript and anonymous-speaker revisions, finite retention, naming restrictions, and one executable Tiron-based source-time meeting path through native History with a 32-target/64-ceiling roster | No general media conversion, system loopback, promoted local meeting UX/anonymous model, contacts, purpose-authorized identity entry point, or production-promoted meeting model; Phase 8 closed as `unadvertised-baseline` | Preserve the capture/result authority; later identity or model-promotion work requires a separately authorized scope and evidence |
| [0021](adr/0021-http3-secure-edge-transport.md) | Accepted gated HTTP/3 edge target; the application remains loopback HTTP/1.1 | Shared | **50** | Transport-neutral job semantics execute over the gated Phase 5 SSH-forwarded loopback batch path. The desktop can offer a verified fixed-loopback health endpoint without connecting. Phase 7 added token-authenticated, revocation-aware, bounded private `ws://127.0.0.1` admission on a separate internal port and qualifies the native lower WebSocket handshake with exact `yap.live.v1` negotiation. | No live ASR, managed LAN/enterprise or live-endpoint discovery, external same-origin WSS/TLS edge, QUIC/HTTP/3 or UDP exposure, negotiated edge capability, fallback drill, or transport benchmark | Keep private admission from being treated as an external edge, then benchmark and security-gate the future HTTP/3 edge |
| [0022](adr/0022-google-okf-permission-safe-projections.md) | Canonical Phase 9 Google OKF and permission-safe projection boundary | Server | **150** | Pinned OKF v0.1 conformance fixtures, bounded source admission, the Yap profile, lossless unknown frontmatter, deterministic projection hashes, Postgres/pgvector and typed-relationship generations, server-derived permission views, prefilter/recheck, non-disclosure, exact citations, atomic activation, rollback, rebuild, and real process-restart recovery passed the complete gate at `a4f34678...`; PR #152 merged it. Postgres is deliberately the sole Phase 9 projection. | Production database operations remain open. No Neo4j benchmark was run because no predefined baseline gap activated a challenger; no Redis/object-storage lifecycle is claimed. | Add another projection only after a measured need and separately authorized evidence. |
| [0023](adr/0023-bounded-live-priority.md) | Accepted amendment to ADR 0014's priority rule; historical reference implementation retired | Server | **20** | The bounded live-priority/fairness decision and historical Phase 4 exact-candidate evidence remain documented; current loopback batch commits dispatch directly to the bounded pool, while Phase 7 supplied authenticated private live admission only | No executing live ASR target, owner-fair router, durable multi-tenant queue, persistent production service, or measured mixed-load tuning/capacity | Phase 10 implements and proves the durable live/batch fairness rule against real owners, bounded overload, cancellation isolation, restart recovery, fixed resource ceilings, and sustained mixed-load SLOs |
| [0024](adr/0024-global-language-routing.md) | Accepted canonical Phase 6 language, local language-diarization, provider, LID, and timing decision; serving amended by 0025 and batch preflight amended by 0026 | Shared | **180** | Bounded catalog/primary/job decisions and a catalog-derived selector exposing only gated Cohere `en-US`; durable preprocessing and source preservation; pinned advisory Silero; one `LiveRuntime`-owned exact AmberNet INT8 local detector with source-time spans, exact-once handoff, visible fallback, and explicit default-off Preview; verify-only five-region AmberNet batch preflight with independent client/server decisions and user confirmation; pinned Nemotron fixed/auto references; fail-closed Cohere timing; and immutable correction history. Exact candidate `a92f338546a2f8bbaded96b04f8987f0ac475c88` passed the 12-cycle/nine-duration/release-UI target-client channel, 18-child provider lifecycle, connected interruption/recovery/History channel, accessibility, and the complete 30-child matrix after focused three-agent remediation re-review. Hosted CI, CodeQL, and stock-NSIS passed at first attempt on docs-only head `cee13f819a85417ea43a3c63e263be85f0570838`. | `wordAlignment` intentionally remains false. A second Cohere locale is not manufactured to populate the selector. The frozen natural-switch target failed and confines local automatic routing to explicit default-off Preview status. Representative low-end battery/thermal certification, broad provider quality/replacement, and meeting/overlap promotion remain later evidence. | Preserve the explicit default-off Preview and require new independent natural/noisy evidence before changing it. Authenticated ownership, provider replacement, meeting/speaker promotion, persistent mixed-load production, and physical release certification remain later gates. |
| [0025](adr/0025-provider-specific-asr-serving.md) | Accepted amendment replacing the universal Triton ASR plane with provider-specific runtimes | Server | **150** | Digest-pinned NVIDIA vLLM 26.06/Python 3.12 Cohere and NVIDIA PyTorch 26.06/NeMo contracts; attributed compatibility fixes and pinned licenses; strict loopback/API-key/runtime/model readiness; bounded requests, cancellation, admission, and resource controls; provider-neutral workers; cache-aware NeMo scheduling; source-exact images; and launcher-owned proxies with no Docker-published provider port. Exact candidate `a92f338546a2f8bbaded96b04f8987f0ac475c88` passed the composed 18-child duration/request/language/resource/lifecycle suite with exact teardown and public-safe aggregate file SHA-256 `98cdc087b574f35a0e12b386a5d8c4c576a9ada548afe88101d1442868e96deb`, then completed the checked Cohere route from real desktop import through server-authoritative History result and cleanup. The retired Triton implementation remains removed. Phase 8's separate Tiron meeting Preview is governed by ADR 0027 and does not replace these provider-specific dictation candidates. | Host-proxy CPU/RSS is outside the provider cgroup profile; neither service is promoted; independently reviewed representative quality, frozen percentiles, output behavior, rollback, whole-host capacity, and persistent supervised mixed-user production evidence do not exist. | Preserve provider-neutral job/result authority and the distinct merged meeting Preview; require independent evidence for any provider replacement or promotion, and leave persistent production supervision/capacity to Phase 10. |
| [0026](adr/0026-ambernet-batch-language-preflight.md) | Accepted replacement for the superseded SpeechBrain batch preflight | Shared | **150** | Verify-only exact AmberNet 1.12.0 INT8 QDQ artifact contract; pinned Python 3.12/NumPy/CPU ONNX Runtime image; independent NeMo-compatible frontend golden and AMD64/ARM64 logit parity; one-thread graph contract; deterministic five-region start-to-tail selection through the four-hour selector bound; strict all-five agreement/manual fallback; bounded private materialization/transport/admission/cancellation/cleanup; independent Rust recomputation; source-exact ARM64 resource/teardown evidence; and canonical batch-launcher integration. Exact candidate `a92f338546a2f8bbaded96b04f8987f0ac475c88` passed the portable Python, Rust, contract, connected-route, and complete Phase 6 matrix while preserving short-input fixed decisions without unnecessary LID dispatch. | Representative advertised-locale/long-tail suggestion quality remains unpromoted. Redistribution is not approved, so model delivery remains explicit verify-only import. | Preserve the bounded user-confirmed seam without adding download/bundle behavior or claiming four-hour end-to-end ASR; revisit broad suggestion quality only with a later advertised route. |
| [0027](adr/0027-tiron-joint-speaker-attributed-meeting-transcription.md) | Accepted canonical Phase 8 server baseline; qualification closed as `unadvertised-baseline` | Server | **150** | Exact Tiron identities are locked. PR #144 merged exact 30-second public-API epochs, request-scoped ECAPA reconciliation, canonical 32-target/64-ceiling session IDs, typed capacity records, strict `Unknown`, one-speaker History projection, and no fallback. Exact candidate `3ddb930...` consumed the single production gate and emitted a hash-bound transcript-free decision. | The independent private holdout was unconfigured, so production quality/runtime admission did not occur; Tiron remains explicit Preview and absent from the default catalog. | Keep the score at 150. Phase 9 is merged separately; any later Tiron promotion requires new authorization and complete independent evidence. |
| [0028](adr/0028-model-independent-terminology-authority.md) | Accepted canonical Phase 9 terminology boundary | Server | **150** | Merged Phase 9 implements server-derived authorization for personal/team/organization records, immutable job-bound snapshots, locale/sensitivity/precedence/conflict/deletion/audit identities, bounded provider hints, deterministic exact-form normalization, grammar preservation constraints, and permission-safe OKF glossary projection. Cross-owner/tenant forgery, revocation, stale/wrong snapshots, governed RAG consumption, and the complete gate passed at `a4f34678...`; PR #152 merged it. | Product UI, production retention/backup/administration, and provider-specific production effectiveness remain open. | Keep UI/operations or broader provider optimization separately scoped. |
| [0029](adr/0029-vllm-agent-reasoning-runtime.md) | Accepted canonical Phase 9 vLLM agent-runtime amendment | Server | **150** | Exact private head `36350d449735a4daea6546e16759f28f6f15631a` returned `required-workload-routes-qualified` with public-safe evidence SHA-256 `ca5a3f712ff737b92cc0d17979e5cd5b00e3034c880729e290a6f6ba255ca951` for locked Qwen 3.6 rapid automation and Gemma 4 complex orchestration. Evidence binds immutable model manifests, the digest-pinned ARM64 vLLM image, exact parser/template/final-response protocols, semantic tool workloads, citation/terminology/isolation checks, Qwen route latency/concurrency bounds, Gemma multi-step semantics, cancellation/recovery, cgroup observations, and exact teardown. Exact aggregate candidate `a4f34678...` semantically admitted that hash-locked private tree and passed the complete knowledge gate with evidence SHA-256 `4013903410e22206c5b46f4dfcbf1878badc3dc9bbdfddb0ddad2ba0e2ff3260`; PR #152 merged it. Yap's Python server selector chooses an explicit route and never silently substitutes the other model. Reviewed checkpoint head `4cb73aee...` freezes exactly two evaluation-only final structural-decoding attempts without tool replay and one complete product-valid cited-proposal call; its focused public checks and three-lens review passed. | Exact `518f7848...` is terminal rejected evidence, and the public route lock is deliberately stale until a replacement qualification binds the protected retry/proposal/evidence inputs. Rust-owned production orchestration, persistent supervised serving, simultaneous model residency, sustained mixed-route and multi-owner capacity, production p95/p99 SLOs, observability, rollback, external serving, and enterprise deployment remain open. Generic 200+ TPS is not Yap evidence. | Keep the score at 150. Run one replacement private qualification and the separate checkpoint gate; production service and capacity evidence remain Phase 10. |

### Phase 6 historical candidate verification snapshot

Exact executable candidate `97b63be46b05dffa21595f2fd081b8467bb95798`
passed the one-attempt integrated gate on 2026-07-24:

- frozen manifest SHA-256
  `8c59a08174a2c1a7e72bef59fefc6a8160ca65982736e0ba7b18f853d893affd`;
- independently validated exact-head 30-child receipt;
- 12/12 repeated local runtime cycles, nine short-duration cases, and the
  release-mode microphone/UI lifecycle with no retained recording, model,
  process, or listener;
- all 18 GB10 Cohere vLLM/Nemotron NeMo candidate-safety children with
  public-safe aggregate SHA-256
  `6a126aacd6fdcc1904ce2633dcebdb0b68d70a50a84cedc20301e97457fc4272`;
- one real desktop/private-server job surviving an SSH-forward interruption,
  publishing a server-authoritative result, opening through History, and
  leaving no owned local or remote runtime; and
- the complete frontend/accessibility, native Rust, required WDIO, connector,
  dependency/provenance, and portable Python 3.12 command inventory.

Private audio, transcript text, raw metrics, paths, host observations, process
ledgers, and logs remain outside the repository. This receipt remains valid for
what that exact source executed, but final adversarial findings superseded it as
merge authority. It cannot be reused for the repaired replacement. Hosted PR
closure and merge are not yet claimed.

## Verification snapshot

The one-time Phase 3 local/native/server/GB10 implementation gate ran against
exact candidate `c3999b7b685dd668165d54b64d1af61e41adad05`. After the hosted lifecycle
exposed an early uninstall-cleanup assertion, implementation head
`a721121315c7a4bf5510212196141f17e9b237bd` added bounded convergence waiting
and passed hosted CI run `29293287930` plus stock NSIS lifecycle run
`29293291582`. This evidence-only documentation commit does not change
executable behavior and remains subject to the final checked-head PR gate.

- Server contract, health service, and infra: **50/50 passed** locally and **50/50 passed** from the immutable GB10 release.
- Frontend unit tests: **257/257 passed**; the production TypeScript/Vite build passed with 295 modules.
- Rust: **660/660 library tests** plus **27/27 integration tests** passed; format and all-target Clippy passed with warnings denied.
- Local live server boundary: **10/10 connector integration tests** passed against the bounded Python health process, followed by clean teardown.
- Playwright: **19/19 passed**.
- Required native WDIO passed all four spec files and 10 required assertions; the optional real-microphone/model probe remained explicitly skipped because no verified Nemotron model is installed.
- Release contract: **32/32 passed**. The exact pinned upstream revisions, license evidence, and selected source hashes verified, and the pnpm high-severity audit found no known vulnerabilities.
- Stock NSIS bundle: `Yap_0.1.0_x64-setup.exe`, 10,072,228 bytes, SHA-256 `c854a5b7b8e824fe305a9b78c7f0effc0b05c128125dddfb2163e0d730efb4b7`. It was built but not installed on the everyday Windows profile.
- Hosted closure: CI run `29293287930` passed frontend, server, native WDIO, Rust format/Clippy/tests/connector integration, the Windows advisory boundary, and the checksum-pinned RustSec audit on exact head `a721121315c7a4bf5510212196141f17e9b237bd`; CodeQL run `29293286157` passed for Actions, JavaScript/TypeScript, Python, and Rust.
- Installer closure: stock NSIS run `29293291582` passed on a disposable `windows-2025` runner. Its installer SHA-256 was `eeefad9860a5ca13c3ce240453d1877ba0f793391a9072f99d8ed16503d82655`; install/launch used `%APPDATA%\com.mcnatg1.yap`, silent uninstall converged, app data and the stock product registry record remained, and the install directory plus uninstall registry entry were removed.
- GB10 evidence: exact immutable release `c3999b7b685dd668165d54b64d1af61e41adad05`, archive SHA-256 `be7f43d757821c3e74d0ae2809599f5a84b369115d24afce42fe6687b1bf12e1`; ARM64/Python 3.12 checks passed **50/50**, tunneled production connector projected `Ready`, a separate refusal invocation projected `Retrying`, and teardown left no Yap process or local/remote port-18765 listener.

The GB10 run did not prove a persistent service or same-process native UI transition, and it introduced no upload, WSS, authentication, ASR, external listener, or firewall change. The local machine did not have `cargo-audit`; the checksum-pinned hosted RustSec lane supplied that evidence and passed on the implementation head.

### Phase 4 checked-head evidence

Exact executable candidate `309a2d427707e3483b2649f13940bd48dfaee836`
passed the one-time complete matrix. Frozen frontend install, the high-severity
pnpm audit, 32/32 release-contract tests, 261/261 Vitest tests, the 295-module
production build, and 23/23 Playwright tests passed. Python 3.12.13 passed
109/109 portable server tests. Rust format, warnings-denied all-target Clippy,
687/687 library tests, 27/27 integration tests, the no-`glib` Windows boundary,
and the checksum-pinned RustSec audit passed; the audit reported zero
vulnerabilities and 17 documented target-all warnings. The live connector
passed 10/10 with clean process/listener teardown. Native WDIO passed all four
spec files and 13 required assertions; its one optional real-microphone/model
probe remained explicitly skipped because no verified Nemotron model is
installed locally.

The disposable exact-head GB10 gate built ARM64 image
`sha256:8b98372d980b3d3ae3cb8bb5cc1498141d161d15157cbd6114339e7a31b8ddff`
and ran the locked Cohere revision on NVIDIA GB10 compute capability 12.1 in
CUDA/BF16. The returned runtime was Python 3.12.3, NVIDIA Torch
`2.13.0a0+8145d630e8.nv26.06`, and Torch CUDA 13.3; WER was `0.0` against the
`0.12` ceiling. Result SHA-256
`1a2850ad767489e00f6a496a46f95384d0d14b4a609d537a27a1304b80cfbbf0`
is bound by evidence SHA-256
`3157efc6845d3c03e05e22a5ad5d0a2e216de5ae26ae990501586a2dfa45312b`.
Before/after listener, firewall-policy, and service-unit observations matched;
the run opened no port or persistent service and left no Phase 4 container or
worker. Post-gate repository changes are evidence/status documentation only.

At the Phase 4 boundary ADR 0014 remained at **100/200** because that checked
reference worker was not connected to a durable desktop/server job path. The
later gated Phase 5 vertical slice supplies that connection and raises the
current audit score to **150/200**; authentication, persistent production
service, external edge, and measured capacity remain absent.

Hosted closure ran on evidence-only PR head
`7c7970ffb959209ba283918a4a200cc16c35fb1f`. CI run `29363957581` passed
frontend, portable server, Rust format/Clippy/tests/connector integration,
the Windows advisory boundary, the checksum-pinned RustSec audit, and required
native WDIO. CodeQL run `29363955498` passed for Actions,
JavaScript/TypeScript, Python, and Rust. Stock NSIS run `29364138311` passed
once on a disposable `windows-2025` runner; installer SHA-256
`8908b394f9fe9e9fe5a6b393c9b7ed7d44f360103b3e9624323d8b6b3e613627`
used `%APPDATA%\com.mcnatg1.yap`, and silent uninstall preserved app data plus
the stock product registry record. These hosted runs add no persistent service,
external listener, firewall mutation, or production deployment claim.

### Phase 5 checked-head evidence

Exact PR head `4771d9be60562fa009ccecbcd3c7111b699883a5` passed the
one-time local/native/server/GB10 matrix and merged as
`b6677631b2cc8283f0f6466622f2dfa7cfdb38f6`. The recorded matrix includes the
frozen frontend build/audit, 32/32 release contracts, 271 frontend unit tests,
23 Playwright tests, 165 portable Python 3.12 tests, 719 Rust library tests plus
integration suites, connector integration, required native WDIO, zero Rust
audit vulnerabilities, the Windows no-`glib` boundary, SSH-forward interruption
and recovery, cancellation/restart/resource checks, GB10 Python 3.12.3 with
NVIDIA Torch `2.13.0a0+8145d630e8.nv26.06`/CUDA 13.3/BF16, WER `0.0` against
the `0.12` ceiling, and clean container/process/listener teardown.

Hosted frontend, Rust, server, required native WDIO, and CodeQL analyses for
Actions, JavaScript/TypeScript, Python, and Rust were green on that exact PR
head. Those historical checks did not activate later product gates or establish
a meeting RTTM/diarization fixture suite, live server pool, authenticated
end-to-end service, persistent production service, external edge, or measured
multi-worker capacity.

### Architecture Checkpoint A evidence

Exact implementation candidate
`6d55816b0406a2365376d7b2d9a7da2afecf9118` passed the one-time complete
local/native/server/GB10 checkpoint matrix. The public-safe result includes
33/33 release/provenance contracts, 277/277 frontend tests, 23/23 Playwright
tests, 182 portable Python 3.12 tests with one platform skip, 797 Rust tests,
warnings-denied all-target Clippy, 10/10 live connector checks, required native
WDIO 13/13, zero dependency-audit vulnerabilities with 17 existing allowed
target-all advisory warnings, the Windows no-`glib` boundary, WER `0.0` against
the `0.12` ceiling on GB10, tunnel interruption/recovery, and clean owned
container/process/listener teardown.

Final PR head `2dc1c48c31928106d07cc638828f055929c33e0c` passed CI run
[`29473149087`](https://github.com/mcnatg1/yap/actions/runs/29473149087),
CodeQL run
[`29473147668`](https://github.com/mcnatg1/yap/actions/runs/29473147668), and
disposable-Windows stock NSIS run
[`29473161985`](https://github.com/mcnatg1/yap/actions/runs/29473161985), then
merged through PR #59 as `a80934d844a068110e7f86b30b6e29d35146db57`.
Checkpoint A reorganizes and hardens the verified foundation but supplies none
of the still-missing platform, deployment, or later-product evidence, so every
pre-existing ADR score remains unchanged.
