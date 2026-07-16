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

Evidence and limits are summarized in [current status](../CURRENT-STATUS.md).

## Current gate: Phase 6 preprocessing

Phase 6 turns the merged fixed-language canonical-WAV vertical slice into a
durable preprocessing and language-aware pipeline without pulling later
identity, diarization, knowledge, or enterprise boundaries forward:

- versioned provider/language/timing capabilities;
- one Rust-owned primary language plus visible per-job override;
- deterministic normalization and advisory VAD that never deletes source audio;
- durable retryable preprocessing stages on the existing job authority;
- isolated CPU SpeechBrain suggestions for long fixed-language recordings;
- fixed Cohere/Nemotron routes plus explicit server Nemotron auto mode at
  finalized utterance boundaries; and
- fail-closed word timing, initially behind an English Cohere evidence gate.

The canonical decision is
[ADR 0024](../adr/0024-phase6-global-language-routing.md). The implementation
and one-time gate contract are in the active
[Phase 6 plan](../plans/active/2026-07-16-phase6-preprocessing-pipeline.md).
Within-utterance code switching, automatic cross-provider switching, named
speaker identity, and enterprise infrastructure are not Phase 6 claims.

## Accepted later phases

| Phase | Boundary | Exit direction |
| --- | --- | --- |
| 7 | Identity and access | Entra/MSAL client bridge, Yap API audience/token validation, tenant-scoped `(tid, oid)` ownership, purpose grants, authorization/revocation/audit behavior. |
| 8 | Meeting evidence | Anonymous speaker evidence, timestamped result revisions, benchmark gates, and purpose-authorized server reconciliation/naming. |
| 9 | Knowledge and agents | Pinned Google OKF profile, deterministic compiler, permission-safe relational/vector retrieval, governed agents/RAG/MCP. |
| 10 | Enterprise and release | IT-managed access/network hardening, secure-edge evaluation, production publication governance, audit/deploy evidence, and eventual repo split. |

Accepted ADRs remain requirements even when no premature implementation exists.
Do not treat an unchecked historical plan box as current backlog.

## Enterprise handoffs

The following are controlled by IT, security, networking, or enterprise
platform owners and cannot be invented by a developer branch:

- internal DNS and certificate issuance/trust;
- synchronized server time and approved host identity;
- enterprise firewall source ranges and policy;
- ZPA application segment, policy, App Connector placement, and redundancy;
- production identity registration, token audience, conditional-access and
  revocation behavior;
- persistent service supervision, backup/deletion SLA, monitoring, and capacity
  ownership; and
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
