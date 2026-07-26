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
  output quality, rollback, and provider promotion remain separate Phase 8
  decisions rather than exact-output assumptions;
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
Authenticated owner derivation remains Phase 7. Phase 9 introduces actual
SGLang agent/LLM workloads. Persistent supervision of the selected vLLM, NeMo,
and SGLang services, production multi-worker/mixed-load capacity promotion, production
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

Phase 7 follows the same cadence: independently merge the phase, run a separate
post-phase adversarial/refactor checkpoint, and begin Phase 8 only after that
checkpoint merges.

## Current phase: tenant-scoped identity and access

The
[tenant-scoped identity and job authorization plan](../plans/active/2026-07-25-tenant-scoped-identity-and-job-authorization.md)
implements the Phase 7 boundary. It keeps local/offline dictation independent,
derives server principals from validated Yap API tokens, enforces owner-scoped
job and LID operations, adds revocation/purpose-control/audit primitives, and
uses a synthetic signed two-principal gate where IT-owned Entra registration is
not yet available. Biometric profiles remain Phase 8; Postgres/pgvector
knowledge permission compilation remains Phase 9.

The active branch now has focused executable evidence for a provider-neutral
OIDC verifier with Entra policy, fail-closed authentication, tenant-scoped
resource ownership, role-gated and audited purpose grants, enforced purpose
checks, and authenticated bounded private WebSocket admission. The native lower
WebSocket handshake is qualified against the separate internal live port. The
desktop exposes only a narrow in-process token-provider seam; no production
adapter is selected or approved. There is no live ASR, product endpoint
discovery, external same-origin WSS/TLS, or HTTP/3 edge.

This is implementation progress, not phase completion. The pinned mock OIDC
flow is focused-green, while hosted Docker execution, final review, the one
admitted complete matrix, hosted PR closure, and merge remain required. Real
enterprise Entra policy conformance and an approved native adapter remain
IT-authorized follow-ups.

## Accepted later phases

| Phase | Boundary | Exit direction |
| --- | --- | --- |
| 7 | Identity and access | Provider-neutral OIDC validation with Entra policy, a native token-provider seam whose production adapter requires separate approval, replacement of the fixed development owner with tenant-scoped `(tid, oid)` ownership, enforced purpose grants, authorization/revocation/audit behavior, and authenticated bounded private live admission without a live ASR or external edge claim. |
| 8 | Meeting evidence | Local anonymous speaker evidence plus the pinned Tiron eight-window/eight-global server baseline, a separately gated speaker-epoch extension for larger speaking rosters, timestamped result revisions, a frozen messy-meeting gate separating attendee/global/window pressure, ASR-plus-diarization fallback, and purpose-authorized server reconciliation/naming. |
| 9 | Knowledge and agents | Pinned Google OKF profile, deterministic compiler, permission-safe relational/vector retrieval, governed agents/RAG/MCP, and SGLang-backed compatible reasoning/tool-output models. |
| 10 | Enterprise and release | Yap-owned Rust orchestration integration, authenticated external batch and WSS/live transport, supervised provider-specific ASR runtimes plus SGLang agent/LLM services, bounded multi-owner mixed-load capacity/SLO evidence, and observability instrumentation; plus IT-managed production hosting/access/network integration, secure-edge evaluation, publication governance, audit/deploy evidence, and eventual repo split. |

Accepted ADRs remain requirements even when no premature implementation exists.
Do not treat an unchecked historical plan box as current backlog.

Phase 8 follows
[ADR 0027](../adr/0027-tiron-joint-speaker-attributed-meeting-transcription.md)
and the queued
[joint speaker-attributed meeting transcription plan](../plans/queued/2026-07-22-joint-speaker-attributed-meeting-transcription.md).
Selecting the development baseline does not advertise or production-promote
the route before its independent accuracy, capacity, lifecycle, and privacy
evidence exists.

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
