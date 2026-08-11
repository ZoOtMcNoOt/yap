# Yap Roadmap

The roadmap is ordered. Each phase uses a separate branch and focused reviewed
PR. Repository state, executable tests, and observed runtime behavior are the
completion authority.

The [Voice OS architecture](../VOICE-OS-ARCHITECTURE.md) is the long-term
full-system frame. This roadmap is the ordered delivery authority when that
frame contains alternate or historical sequencing.

## Delivered MVP foundation

| Phase | Delivered boundary |
| --- | --- |
| 0 | Architecture reset around thin desktop, private server, explicit local fallback, and queued/offline truth. |
| 1 | Desktop capture, durability, tray/island, playback/history, and imported-job foundations. |
| 2 | Explicit local Nemotron fallback model lifecycle and live transcription. |
| 3 | Server contracts, capability health, connector state/retry, durable desktop job ledger, canonical app-data/stock NSIS closure. |
| 4 | Bounded private router/pool and isolated Cohere GPU reference worker on the pinned Python 3.12/NVIDIA stack. |
| 5 | Real durable imported-recording batch-ASR slice through the desktop/server contract with verified native result publication. |
| Checkpoint A | Phase 1–5 correctness, ownership, decomposition, provenance, documentation, and resource-bound review; merged after the one-time local/native/server/GB10 matrix and exact-head hosted closure. |
| 6 | Durable preprocessing, language-aware local routing evidence, guarded batch preflight, provider-specific ASR serving candidates, and bounded timing evidence; merged after the one-time 30-child matrix and exact-head hosted closure. |

Evidence and limits are summarized in [current status](../CURRENT-STATUS.md).

## Delivered Phase 6 boundary

Phase 6 turns the merged fixed-language canonical-WAV vertical slice into a
durable preprocessing and language-aware pipeline without pulling later
identity, diarization, knowledge, or enterprise boundaries forward:

- versioned provider/language/timing capabilities;
- one Rust-owned primary language plus a visible catalog-derived per-job
  recording-language selector that never invents an unpromoted alternate;
- deterministic normalization and advisory VAD that never deletes source audio;
- durable retryable preprocessing stages on the existing job authority;
- one bounded resident local acoustic-LID component, automatic offline language
  switching, and within-utterance source-time language spans under the existing
  Rust live-runtime owner;
- one verify-only AmberNet 1.12.0 INT8 QDQ artifact in an isolated CPU runtime,
  with five strict start-to-tail regions and explicit user confirmation for long
  fixed-language recordings;
- pinned reference Cohere/Nemotron routes plus explicit server Nemotron auto
  mode at finalized utterance boundaries, with correctness and bounded-resource
  evidence rather than a production pool claim;
- a digest-pinned Cohere vLLM 26.06 serving candidate behind the same worker
  contract, with measured GB10 lifecycle, latency, throughput, memory,
  cancellation, teardown, and concurrent-load safety evidence; representative
  output quality, rollback, and provider promotion remain separate later
  evidence rather than exact-output assumptions;
- a separate Nemotron NeMo server-streaming candidate with its own correctness,
  streaming, lifecycle, concurrency, and resource gate; and
- fail-closed word timing, initially behind an English Cohere evidence gate.

The canonical decisions are
[ADR 0024](../adr/0024-global-language-routing.md),
[ADR 0025](../adr/0025-provider-specific-asr-serving.md), and
[ADR 0026](../adr/0026-ambernet-batch-language-preflight.md). The implementation
and one-time gate contract are in the completed
[audio preprocessing and language routing plan](../plans/completed/2026-07-16-audio-preprocessing-and-language-routing.md).
The living
[decision and evidence queue](../plans/active/2026-07-17-voiceos-decision-evidence-queue.md)
preserves discussed decisions, open questions, detailed Phase 6 sub-tasks, and
later-phase owners without authorizing phase mixing.
Automatic cross-provider switching, named speaker identity, and enterprise
infrastructure are not Phase 6 claims. Within-utterance language spans are a
Phase 6 target and remain an explicit default-off Preview because the frozen
natural-switch quality target failed. Exact executable candidate
`a92f338546a2f8bbaded96b04f8987f0ac475c88` passed the frozen 30-child
local/native/server/private-runtime matrix after bounded three-agent
remediation re-review, including the target-client, 18-child resident-provider,
and connected interruption/recovery/History channels with exact teardown.
Exact runtime images were prepared before admission from digest-pinned bases
and pinned dependencies and emitted private receipts after a second clean-head
check. The admitted gate verified each frozen receipt hash, then required the
already-prepared ARM64 image ID, checked-head revision, base digest, and runtime
identity to match it. The receipt-bound ID was launched and recorded; the gate
could not build, pull, reconnect, or substitute an image. Hosted CI, CodeQL,
and stock-NSIS passed at first attempt on docs-only review head
`cee13f819a85417ea43a3c63e263be85f0570838`; a private closure receipt was
independently validated outside Git. Final reviewed head
`50f0f9e5e3cf288f41efa3745514dd08c9ee1929` passed the required exact-head
hosted policy and final adversarial read-back, and
[PR #67](https://github.com/mcnatg1/yap/pull/67) merged as
`87c8654250cba8b9eafa5007bf719c52e4749cdf`.
Authenticated owner derivation remains Phase 7. Phase 9 now has executable
vLLM Qwen/Gemma agent workload routes under ADR 0029. Persistent supervision of vLLM and NeMo
services, production multi-worker/mixed-load capacity promotion, production
observability, and external deployment remain Phase 10.

## Delivered post-Phase-6 checkpoint

The separate
[codebase ownership and maintainability review](../plans/completed/2026-07-18-codebase-ownership-and-maintainability-review.md)
reviewed the complete Phase 1–6 executable system before Phase 7 started. It used
exactly three completed antagonistic reviews, then applied the same ownership,
comprehensibility, decomposition, maintainability, resource, provenance, and
documentation standard as post-Phase-5 Checkpoint A. It added no Phase 7 product
functionality. Historical candidate
`66267af0abf38af0a6b8d3d2fac76543673c0331` and consumed hosted head
`08ab49ba8d727cb8331a40f28c7c4c70d75d4035` retain their recorded evidence
but are not merge authority. After the Cargo-output and same-process Windows
atomic replacement repairs, fresh exact executable candidate
`9dfa8a68b02cdf854d14fb046e51a166cd3da353` passed its single admitted
31-child checkpoint matrix and independent receipt validation with exact
teardown. Its private receipt SHA-256 is
`6b02bd04cb3ce3c25925c2b2be8cc2f3c20f79478513fe41519f666a498114e7`.
First-attempt hosted CI run `30206923702`, CodeQL run `30206922629`, and
stock-NSIS run `30206941391` passed on documentation-only reviewed head
`0bd11ae8dea34cd22029c6c09a9fd62a5951a363`. [PR
#68](https://github.com/mcnatg1/yap/pull/68) merged as
`15f9c8ac00211b9d2f28845d419258ae2c8de8e4`.

Phase 7 followed the same cadence: the phase merged, then its separate
post-phase adversarial/refactor checkpoint and concrete follow-ups closed.
Phase 8 Preview then merged through PR #142. Historical meeting-transcription
maintainability candidate `fb0985e7...` passed before documentation successor
`e22368fc...` exposed high-severity `GHSA-mwp4-54f8-5fhr`. Patched candidate
`393710999...` passed its exact-image lifecycle, single complete matrix,
independent receipt validation, and required CI and CodeQL jobs. PR #143 merged
the reviewed closure as `8fb511ad2fd7217a87e95ddba31d74dfa474fac2`.

## Last completed phase: meeting evidence (Phase 8)

The
[joint speaker-attributed meeting transcription plan](../plans/completed/2026-07-22-joint-speaker-attributed-meeting-transcription.md)
implemented the explicit meeting-only Tiron Preview and merged through
[PR #142](https://github.com/mcnatg1/yap/pull/142) as `4201c5e7`. The route
publishes source-bound transcript and anonymous-speaker revisions through the
existing owner-scoped result authority and projects them into native History.
It is not the default route and is not production-promoted. PR #144 merged the
replacement exact source-time epoch route and integrated request-scoped speaker
reconciliation as `b5b52bfd297edf1e95d93e120a8e59c206f7ab77`. Exact
qualification candidate `3ddb930268b544d2cae80d4389f12ef315b35ded`
then recorded `unadvertised-baseline` because the required independent private
holdout was unconfigured. No runtime/image gate was admissible, neither catalog
changed, and no second server meeting pipeline is planned. PR #150 passed all
hosted checks at exact head `2ab33ae6bd27b2002a539a6cb89dd55eb16eac6b`
and merged the closure as `599a0d0b`. Phase 8 is closed. Phase 9 passed its
complete gate and merged through hosted-green PR #152 as `ae81ff06`.

## Active checkpoint: governed-knowledge ownership and maintainability

Merged Phase 9 contains the pinned Google OKF compiler, immutable
model-independent terminology snapshots, atomic Postgres/pgvector generations,
permission-filtered cited retrieval, governed proposals/RAG/MCP, and explicit
no-fallback workload routing. Exact private GB10 head
`36350d449735a4daea6546e16759f28f6f15631a` qualified the locked Qwen rapid and
Gemma complex routes on the checked vLLM evaluation runtime. That is
route-specific evaluation evidence, not production service promotion.

Exact candidate `a4f34678ea9980379b18266d40d3347b818ac57e` passed the canonical
Python/Ruff/Postgres/pgvector/restart/private-route matrix with outcome
`governed-knowledge-gate-passed` and public-safe evidence SHA-256
`4013903410e22206c5b46f4dfcbf1878badc3dc9bbdfddb0ddad2ba0e2ff3260`.
Exact hosted-green head `fa26caaf7e3ea4e20f27b390355dff80bee2464f`
merged through PR #152 as `ae81ff067c73a64528eecc14403765562726f2fe`.
The active [post-Phase-9 checkpoint](../plans/active/2026-08-10-governed-knowledge-ownership-and-maintainability-review.md)
reviews executable ownership and maintainability before Phase 10. Reviewed
executable head `a76ed9b095ebb797064a12e9ebd90d2dd9d87bef` resolves the
accepted findings, freezes two evaluation-only final structural-decoding
attempts without retrying or replaying tools, binds one synthetic cited proposal
to a complete product-valid JSON call, assigns Qwen to pinned vLLM 26.07 plus
XGrammar 0.2.1 while Gemma remains on exact upstream vLLM 26.06, and separates
common and proposal rapid-route qualification bounds without changing either
route's maximum. Exact `96897d2f...` is terminal rejected evidence with
public-safe SHA-256
`929dd2a329387e0647db49699b0653862668f8f6b4588a4bf3ee9818ba656b75`.
Fresh exact-head qualification at `a76ed9b0...` returned
`required-workload-routes-qualified` with public-safe evidence SHA-256
`4662a2784510e63da98dcd301ea05ef107196ce46b49d68ad812abdc042d00f0`;
both locked routes were eligible and passed their semantic and route-specific
evidence contracts with exact teardown and zero owned runtime residue. The
schema-3 public lock committed at `2cf1e92c...` has raw-file SHA-256
`b8d05f9645f37c36e0be5b480cf95c5e29b31945b4e56f879c95eeb72979a1b9`
and passed hash-bound semantic admission. Exact aggregate head `22c3f369...`
then returned `governed-knowledge-gate-passed` with public-safe evidence SHA-256
`8c2bfdef6b596094fe113a12b1bbfccec94ddeb3944e1b3313f41b61d5df12b0`,
152 portable tests, Ruff, 17 zero-skip database tests, real restart/recovery,
and exact teardown with zero residue. Hosted review and merge remain open. The
split workload bounds are not production SLO/capacity or generic TPS evidence. Postgres
remains the only current knowledge projection; Redis, object storage, and
Neo4j require a measured need and a later authorized gate. Persistent
supervision, simultaneous model residency, sustained mixed-user capacity/SLOs,
external serving, observability, enterprise networking, and deployment remain
Phase 10 or IT handoffs.

## Prior merged phase: tenant-scoped identity and access (Phase 7)

The
[tenant-scoped identity and job authorization plan](../plans/completed/2026-07-25-tenant-scoped-identity-and-job-authorization.md)
implemented the Phase 7 boundary and merged as `66d314d7`. It keeps local/offline dictation independent,
derives server principals from validated Yap API tokens, enforces owner-scoped
job and LID operations, adds revocation/purpose-control/audit primitives, and
uses a synthetic signed two-principal gate where IT-owned Entra registration is
not yet available. Purpose-authorized speaker reconciliation and naming remain
unpromoted later work; Postgres/pgvector knowledge permission compilation
remains Phase 9.

Merged Phase 7 has executable evidence for a provider-neutral OIDC verifier
with Entra policy, fail-closed authentication, tenant-scoped resource
ownership, and authenticated bounded private WebSocket admission. Role-gated
purpose grants and purpose checks are implemented and unit-tested but no route
or operator entry point calls them, so they do not enforce anything yet. The native lower
WebSocket handshake is qualified against the separate internal live port. The
desktop exposes only a narrow in-process token-provider seam; no production
adapter is selected or approved. The desktop can offer only the verified fixed
numeric-loopback HTTP health origin; there is no managed LAN/enterprise or
live-endpoint discovery, live ASR, external same-origin WSS/TLS, or HTTP/3 edge.

Phase 7 is complete at the repository level. Exact application/runtime
candidate `dc635916...` passed its private 25-cell matrix and independent receipt
validation. PR #69 merged as `66d314d7`, although its final hosted head did not
have an all-green rollup and is not relabeled here. The separate adversarial
checkpoint closed at `ef6d977`, with concrete follow-ups at `1a6f06e` and
`589197e`. Real enterprise Entra policy conformance and an approved production
native provider remain IT-authorized follow-ups rather than Phase 8 work.

## Accepted later phases

| Phase | Boundary | Exit direction |
| --- | --- | --- |
| 7 | Identity and access | Provider-neutral OIDC validation with Entra policy, a native token-provider seam whose production adapter requires separate approval, replacement of the fixed development owner with tenant-scoped `(tid, oid)` ownership, purpose grants and authorization/revocation/audit records that are implemented but reachable only from tests, and authenticated bounded private live admission without a live ASR or external edge claim. |
| 8 | Meeting evidence | Local anonymous speaker evidence plus the pinned Tiron historical whole-meeting reproduction, one integrated source-time epoch route with bounded request-scoped speaker reconciliation for larger speaking rosters, timestamped result revisions, a frozen messy-meeting gate separating attendee/session/window pressure, and later purpose-authorized naming. A failed Tiron gate leaves the sole server meeting route unpromoted. |
| 9 | Knowledge and agents | Pinned Google OKF profile, deterministic compiler, permission-safe relational/vector retrieval, governed agents/RAG/MCP, and vLLM-backed compatible reasoning/tool-output models. |
| 10 | Enterprise and release | Yap-owned Rust orchestration integration, authenticated external batch and WSS/live transport, supervised provider-specific ASR runtimes plus vLLM agent/LLM services, bounded multi-owner mixed-load capacity/SLO evidence, and observability instrumentation; plus IT-managed production hosting/access/network integration, secure-edge evaluation, publication governance, audit/deploy evidence, and eventual repo split. |

Accepted ADRs remain requirements even when no premature implementation exists.
Do not treat an unchecked historical plan box as current backlog.

The merged Phase 8 Preview follows
[ADR 0027](../adr/0027-tiron-joint-speaker-attributed-meeting-transcription.md)
and the completed
[joint speaker-attributed meeting transcription plan](../plans/completed/2026-07-22-joint-speaker-attributed-meeting-transcription.md).
Selecting and explicitly enabling the Preview baseline does not place it in the
committed default catalog or production-promote it. The completed qualification
record preserves the explicit `unadvertised-baseline` outcome.
The separate
[meeting-transcription ownership and maintainability review](../plans/completed/2026-08-03-meeting-transcription-ownership-and-maintainability-review.md)
qualified patched candidate `393710999...`; PR #143 merged the reviewed closure
as `8fb511ad2fd7217a87e95ddba31d74dfa474fac2`. PR #144 merged the sole
source-time route, and the completed production-qualification record closes the
Phase 8 evidence decision without promotion.

## Enterprise handoffs

The following are controlled by IT, security, networking, or enterprise
platform owners and cannot be invented by a developer branch:

- internal DNS and certificate issuance/trust;
- synchronized server time and approved host identity;
- enterprise firewall source ranges and policy;
- ZPA application segment, policy, App Connector placement, and redundancy;
- production identity registration, token audience, conditional-access and
  revocation behavior;
- production hosting/service-manager approval, backup/deletion SLA, enterprise
  monitoring integration, SLO approval, and capacity authorization (Yap still
  owns the service implementation, bounded local capacity evidence, and
  observability instrumentation); and
- enterprise deployment, publication, and audit approval.

Until those handoffs exist, the Phase 5 SSH-forward profile remains a narrow
development boundary, not production security.

## Phase working rules

1. Do not restart or duplicate merged work.
2. Keep phases independently reviewable and mergeable.
3. Use focused verification during development; run the complete applicable
   phase matrix once when the exact head is ready.
4. Resolve correctness/security findings before merge.
5. Preserve upstream provenance and verify licenses before reuse.
6. Update completion scores/status only after executable evidence exists.
7. Keep private scan material and sensitive runtime evidence out of Git, PRs,
   hosted logs, and public docs.
8. After Phase 6 and each later phase, run the accepted separate adversarial/
   refactor checkpoint before beginning the next phase; never mix next-phase
   behavior into a checkpoint branch.
9. Name runtime modules, types, functions, tests, configuration, containers,
   and versioned contracts for the behavior they own. A phase number belongs
   only in an actual roadmap, phase gate, phase evidence artifact, or frozen
   backward-compatibility token; it is not a substitute for a domain name.
