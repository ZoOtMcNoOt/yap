# Current Status

**As of:** 2026-07-16

**Current work:** Phase 6 preprocessing on
`feat/phase6-preprocessing-pipeline`.

**Merged product baseline:** Architecture Checkpoint A merge
`a80934d844a068110e7f86b30b6e29d35146db57` from
[PR #59](https://github.com/mcnatg1/yap/pull/59), preserving the gated Phase 5
product behavior.

This document is the canonical human-readable status summary. Executable code,
machine-readable contracts, focused tests, and observed runtime behavior win if
another document disagrees.

The [Voice OS architecture](VOICE-OS-ARCHITECTURE.md) remains the long-term
full-system frame of reference. Checkpoint cleanup does not retire or silently
rewrite that target; this status document distinguishes what currently executes.

## Milestone status

| Milestone | Status | Executable truth |
| --- | --- | --- |
| Phase 0: architecture reset | Merged | Thin desktop + private server direction and staged monorepo are accepted. |
| Phase 1: desktop foundation | Merged | Tray-owned app, capture/timeline/recording durability, native history/playback admission, and imported-job projection seams execute. |
| Phase 2: local fallback | Merged | Explicit Nemotron INT8 model lifecycle and in-process local live transcription execute; the runtime never silently downloads models. |
| Phase 3: server boundary | Merged and gated | Machine contracts, loopback health/capabilities, connector state/retry, durable desktop job ledger, canonical app-data migration, stock NSIS, and disposable-Windows lifecycle proof exist. |
| Phase 4: private ASR node | Merged and gated | A bounded router/pool and transient isolated Cohere worker ran on GB10 using the pinned Python 3.12 / NVIDIA PyTorch 26.06 stack. This is reference-worker proof, not a production service. |
| Phase 5: remote STT | Merged and gated | Canonical WAV admission, immutable desktop spool, durable create/upload/commit/status/result/cancel, isolated private batch inference, verified native result publication, reconnect recovery, and History projection execute through the loopback development contract. |
| Checkpoint A | Merged and gated | Implementation candidate `6d55816b0406a2365376d7b2d9a7da2afecf9118` passed the one-time local/native/server/GB10 matrix. Final PR head `2dc1c48c31928106d07cc638828f055929c33e0c` passed hosted CI, CodeQL, and disposable-Windows NSIS before merge `a80934d844a068110e7f86b30b6e29d35146db57`. |
| Phase 6: preprocessing | Active; implementation not gated | [ADR 0024](adr/0024-phase6-global-language-routing.md) and the [active plan](plans/active/2026-07-16-phase6-preprocessing-pipeline.md) record the benchmark-backed language/routing/timing decision. No Phase 6 product behavior or implementation-score increase is claimed yet. |
| Phases 7–10 | Planned | Follow the accepted order in the [roadmap](roadmap/ROADMAP.md). Enterprise infrastructure remains an explicit IT/security handoff. |

## What executes now

- One installed Tauri desktop app owns tray/window lifecycle, native recording,
  local fallback, imported-job durability, connector state, path authorization,
  transcript publication, and History truth.
- One tray-owned, hover-expanding island window projects live state. Native code
  owns its exact bounds and interactive region; no invisible sensor window owns
  clicks.
- Physical shortcut enrollment records deliberate chords. Normal typing is not
  treated as enrollment, and completed text uses the accepted safe delivery
  behavior rather than speculative field injection.
- Local live fallback uses the pinned Nemotron 3.5 ASR Streaming 0.6B INT8
  bundle through in-process `sherpa-onnx` after explicit installation.
- Imported Phase 5 jobs admit only already-canonical mono PCM16/16 kHz WAV at
  this boundary, prepare immutable Yap-owned artifacts, and persist progress in
  native SQLite.
- The development server path binds to numeric loopback. The desktop reaches a
  private node through an explicitly managed SSH forward; Yap does not create
  or silently fail over that tunnel.
- The private server validates bounded create/upload/commit requests, persists
  job/chunk/result state, routes one bounded batch workload, runs the isolated
  worker, and publishes an immutable result.
- Native code verifies result identity, authority, hashes, paths, sizes, and
  transcript bytes before History can present completion.
- Native shortcut and OS-drop work use fixed workers with bounded queues;
  interactive file selection and server-settings publication each admit one
  end-to-end owner rather than accumulating blocking work.

The complete owner and trust-boundary map is
[Phase 1–5 ownership](architecture/boundaries/PHASE-1-5-OWNERSHIP.md).

## What is not claimed

- No WSS/live server transcription, general media conversion, production
  authentication, external application endpoint, persistent supervised
  multi-user service, or measured multi-worker capacity is shipped.
- No Entra/MSAL token validation, tenant-derived owner, purpose grant, internal
  DNS, enterprise certificate, ZPA policy, or production firewall rule exists.
- Phase 6 has a focused implementation slice on the current branch: a verified
  runtime may publish a bounded, fingerprinted ASR catalog through a separate
  endpoint and native projection. The catalog honestly exposes only the gated
  Cohere `en-US` fixed-batch route. Primary-language persistence/UX,
  normalization/VAD, SpeechBrain LID, the server Nemotron pool, dynamic
  language tags, and Cohere word alignment are not yet wired product
  capabilities, and no Phase 6 gate has run.
- Phase 8 speaker inference and Phase 9 knowledge/agent behavior remain deferred.
- Private security scans, scan identifiers, host paths, and detailed private
  findings are not repository or PR material.

## Phase 5 checked-head evidence

Phase 5 PR head `4771d9be60562fa009ccecbcd3c7111b699883a5` passed the
one-time local/native/server/GB10 gate and was merged by
`b6677631b2cc8283f0f6466622f2dfa7cfdb38f6` on 2026-07-15.
Hosted frontend, Rust, server, required native WDIO, and CodeQL analyses for
Actions, JavaScript/TypeScript, Python, and Rust were green on the checked PR
head. Exact counts and environment observations remain in the completed
[Phase 5 implementation record](plans/completed/2026-07-14-phase5-remote-stt.md)
and [verification record](evidence/architecture-checkpoint-a/VERIFICATION.md).

## Checkpoint A checked-head evidence

Checkpoint implementation candidate
`6d55816b0406a2365376d7b2d9a7da2afecf9118` passed its one-time complete
local/native/server/GB10 matrix. Test-harness-only closure produced final PR
head `2dc1c48c31928106d07cc638828f055929c33e0c`; hosted CI run
[`29473149087`](https://github.com/mcnatg1/yap/actions/runs/29473149087),
CodeQL run
[`29473147668`](https://github.com/mcnatg1/yap/actions/runs/29473147668), and
stock NSIS run
[`29473161985`](https://github.com/mcnatg1/yap/actions/runs/29473161985)
all passed on that exact head. It merged through PR #59 as
`a80934d844a068110e7f86b30b6e29d35146db57`. The complete public-safe record is
[Checkpoint A verification](evidence/architecture-checkpoint-a/VERIFICATION.md).

## Active next steps

1. Finalize the Phase 6 capability/language/timing contracts and preserve the
   complete ADR precedence map in the active plan.
2. Implement the provider catalog and Rust-owned primary/per-job language
   decision flow with focused contract, persistence, migration, and UX tests.
3. Add source-authoritative VAD/durable stages, isolated LID, provider routing,
   and fail-closed timing evidence in reviewable slices.
4. Resolve focused correctness/security/license/maintainability findings, then
   freeze and run the complete Phase 6 local/native/server/GB10 matrix exactly
   once on the ready head.
5. Merge only the reviewed exact PR head after hosted checks are green.
