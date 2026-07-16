# Phase 6 Preprocessing Pipeline Implementation Plan

**Status:** Active on `feat/phase6-preprocessing-pipeline`. Decision research
and public aggregate benchmark evidence are complete. The bounded verified ASR
catalog slice executes with focused Python 3.12, OpenAPI, Rust, and TypeScript
coverage; the remaining implementation and the Phase 6 gate are not complete.

**Base:** Checkpoint A merge
`a80934d844a068110e7f86b30b6e29d35146db57` from
[PR #59](https://github.com/mcnatg1/yap/pull/59).

**Canonical owners:** Rust owns user language preferences, imported-job
decisions, source preparation, and native result admission. The server owns the
versioned provider capability catalog, heavy preprocessing/inference stages,
and server-authoritative result production. React renders native/server state;
it does not become a third settings, routing, or pipeline authority.

**Scope:** Complete canonical Phase 6: deterministic normalization and advisory
VAD, source-bounded chunk/decision manifests, primary-language and per-job UX,
guarded long-recording LID, fixed and explicit dynamic ASR routing, truthful
word-timing evidence, and durable retryable pipeline stages. Preserve the
merged Phase 5 path and keep later identity, diarization, knowledge, secure-edge,
and enterprise work in their accepted phases.

## Architecture authority

### Applied decisions

- [ADR 0003](../../adr/0003-long-term-voice-architecture.md): user confirmation,
  multiple probes, and no silent LID routing remain required.
- [ADR 0004](../../adr/0004-background-diarization-okf-agents.md): critical-path
  isolation, bounded background work, recoverable failures, and aligning raw
  transcripts remain required. Its diarization algorithm details do not apply.
- [ADR 0006](../../adr/0006-silero-agents-state-machine.md): Silero VAD is an
  advisory boundary signal; VAD failure or false negatives never delete source
  audio.
- [ADR 0007](../../adr/0007-forced-alignment-engine.md): align raw ASR output,
  not polished text. The historical exact engine choice is amended by ADR 0024.
- [ADR 0008](../../adr/0008-speechbrain-lid-gate.md): LID is an assistive,
  user-gated batch decision. ADR 0024 replaces its fixed threshold, raw
  start-window shortcut, and desktop-runtime assumption.
- [ADR 0014](../../adr/0014-server-tier-compute-topology.md): the client stays
  thin and the private server owns heavy model pools and official inference.
- [ADR 0018](../../adr/0018-three-repo-topology.md): Phase 6 remains in the
  staged monorepo; repository extraction waits for Phase 10.
- [ADR 0019](../../adr/0019-local-streaming-model-selection.md): the desktop
  retains one pinned local Nemotron fallback and no client model router.
- [ADR 0020](../../adr/0020-meeting-capture-diarization-authority.md): retained
  source audio is authoritative, client VAD is advisory, and result revisions
  may truthfully omit alignment.
- [ADR 0023](../../adr/0023-bounded-live-priority.md): new server work uses the
  existing bounded live-preference and owner-fair backpressure rules.
- [ADR 0024](../../adr/0024-phase6-global-language-routing.md): the provider
  catalog, primary-language policy, SpeechBrain preflight, Nemotron auto mode,
  alignment gates, and benchmark-backed exclusions are canonical for Phase 6.

### Superseded or intentionally ignored details

- Do not revive ADR 0002's CrispASR runtime.
- Do not implement ADR 0004's diarizer/vault, ADR 0006's historical umbrella
  orchestrator, ADR 0007's unbenchmarked Canary/Wav2Vec2 choice, ADR 0008's
  `0.70` shortcut, ADR 0009's solo TCP knowledge worker, or superseded ADR 0015.
- Do not infer support from a tokenizer, prompt dictionary, or adaptation-ready
  locale. No Phase 6 model fine-tuning pipeline is authorized.

### Deferred decisions

- Phase 7: Entra/MSAL, token-derived ownership, authorization, revocation, and
  audit identity.
- Phase 8: speaker inference, speaker reconciliation, contact/profile identity,
  and named attribution.
- Phase 9: Google OKF, permission-safe retrieval, agents, and MCP.
- Phase 10: production DNS/certificates/ZPA/firewall policy, secure-edge
  promotion, enterprise deployment, publication governance, and repo split.
- Within-utterance language diarization, client-local dynamic detection, and
  automatic cross-provider switching remain outside Phase 6 unless a separate
  accepted decision and representative benchmark prove them.

## Executable baseline to preserve

- Phase 5 accepts only canonical mono PCM16/16 kHz WAV, creates an immutable
  Yap-owned spool, persists one native job ledger, and drains create/upload/
  commit/status/result/cancel over the numeric-loopback development contract.
- The Phase 5 isolated Cohere worker and its immutable NVIDIA 26.06/Python 3.12
  lock remain the accuracy-first supported path.
- Local live fallback remains the in-process pinned `sherpa-onnx` Nemotron
  bundle. Its current export has no verified language-prompt/tag interface.
- Result publication remains server-authoritative and native-verified before
  History can present completion.
- Private audio, transcripts, scan output, host paths, and raw benchmark output
  remain outside Git, PRs, hosted logs, and public artifacts.

## Decision evidence

The aggregate public-fixture spike is recorded in ADR 0024. It is design
evidence, not per-language certification:

The [dynamic language detection evaluation](../../research/2026-07-16-dynamic-language-detection-evaluation.md)
also separates clip-level LID, finalized-segment tags, and true language
diarization. Qwen3-ASR and VibeVoice remain benchmark challengers; neither
changes the accepted Nemotron segment-level implementation before executable
comparative evidence exists.

- Nemotron automatic LID: 78/84 correct over 28 out-of-box language families,
  mean 134 ms/probe, and 1.293 GiB peak GPU allocation in the measured shape.
- SpeechBrain VoxLingua107: 77/84 over the same 28 families plus 3/3 Greek;
  selected CPU path mean 179 ms, p95 234 ms, and about 760 MiB peak RSS.
- SpeechBrain probe-length evidence supports at least eight voiced seconds per
  bounded probe; silence/noise and related-language confusions require VAD,
  multiple windows, and manual confirmation.
- Cohere attention alignment is currently English-only evidence: held-out start
  MAE 92.2 ms, end MAE 80.3 ms, and minimum coverage 91.8%.
- Nemotron auto mode proved useful per-utterance language tags but did not prove
  within-utterance code switching.

## Ordered implementation slices

### 1. Version the language, provider, and timing capability contract

- [x] Define one bounded catalog schema shared by OpenAPI, Python, Rust, and
      TypeScript projections.
- [x] Record provider/model revision, BCP 47 locale, execution mode, quality
      tier, language suggestion/tag support, alignment support, provenance/
      license identity, and promotion-evidence revision.
- [x] Advertise a catalog only when its locked runtime and required artifacts
      are verified. Health remains small; catalog retrieval is separately
      bounded and versioned.
- [ ] Keep a last-known verified native snapshot for offline explanation
      without treating it as current server availability.
- [ ] Reject duplicate locales/modes, unknown tiers, invalid BCP 47 tags,
      adaptation-ready Nemotron entries, mutable revisions, and unbounded text.

### 2. Add one Rust-owned primary-language and per-job decision flow

- [x] Persist a versioned, bounded primary BCP 47 locale under canonical app
      data with atomic/no-follow behavior and safe recovery.
- [x] Setup must require confirmation; the OS locale may suggest but may not
      silently save the decision.
- [ ] Settings may edit the primary language and imported jobs now freeze and
      display the exact primary/manual disposition. Promotion remains open
      until a second verified fixed-batch locale makes the catalog-derived
      override selectable in the shipped catalog.
- [x] Fixed short recordings skip SpeechBrain and use the primary/manual
      language. A job override never rewrites the saved primary language.
- [x] React remains a projection of native preferences and catalog state; no
      localStorage language authority or hard-coded permanent provider matrix.

### 3. Produce deterministic source-authoritative preprocessing evidence

- [ ] Define normalization and advisory VAD output as source-time intervals and
      immutable stage evidence; never create a speech-only authoritative source.
- [ ] Pin and verify the selected Silero artifact/license before enabling it.
- [ ] Bound input duration, window size, padding, memory, CPU concurrency,
      output count, and serialized manifest size.
- [ ] Preserve exact gaps and source offsets. VAD error continues with the
      retained source and an explicit unavailable/error result.
- [ ] Keep current one-MiB transport bounds independent from VAD so uninterrupted
      speech or detector failure cannot create an unbounded chunk.

### 4. Make preprocessing stages durable and retryable

- [ ] Add explicit normalization, VAD, LID decision, ASR, alignment, and result
      publication stage records to the existing job authority rather than
      creating a second queue.
- [ ] Record input fingerprints, immutable component revisions, attempts,
      terminal outcome, retryability, and source-bounded evidence.
- [ ] Make restart/resume idempotent. Retry one failed stage without rewriting
      capture identity, a confirmed language choice, or a prior result revision.
- [ ] Bound retention and delete only Yap-owned derived artifacts; never delete
      an admitted external source because a stage failed or was cancelled.

### 5. Add the isolated SpeechBrain batch preflight

- [ ] Build a separate CPU-only Python 3.12 component pinned to SpeechBrain
      1.1.0, `torch==2.11.0+cpu`, `torchaudio==2.11.0+cpu`, and model revision
      `0253049ae131d6a4be1c4f0d8b0ff483a0f8c8e9`.
- [ ] Pin hashes/licenses and stage artifacts before a networkless production
      invocation. Do not modify the NVIDIA ASR image or desktop installer.
- [ ] Probe at most two speech-rich windows, each at most 15 seconds and with at
      least eight voiced seconds. Preserve exact source offsets.
- [ ] Treat scores as uncalibrated evidence. Silence, disagreement, unsupported
      or ambiguous locale mapping, and unusable probes require manual choice.
- [ ] A supported agreement pre-fills the picker only; user confirmation remains
      required before fixed-language commit.

### 6. Route fixed and explicit dynamic ASR without hidden provider changes

- [ ] Keep Cohere accuracy-first for its enabled fixed-language catalog and add
      a pinned server Nemotron pool for enabled fixed broad/fast routes.
- [ ] Add explicit Nemotron `target_lang=auto` dynamic mode. Preserve a valid
      emitted locale tag for every finalized segment.
- [ ] Permit language changes only across finalized VAD/endpoint utterances.
      Partial text never changes language/provider underneath the user.
- [ ] Mark missing, invalid, disabled, or adaptation-ready tags `Unknown` and
      require visible review; never silently relabel them as the primary locale.
- [ ] Keep one provider for the entire automatic job. Do not silently dispatch
      individual utterances between Cohere and Nemotron.

### 7. Publish truthful timing evidence

- [ ] Implement the measured Cohere decoder-attention candidate behind an
      English-only capability gate first: ordinary BF16 generation, FP32 Q/K
      reconstruction, finite checks, filtering, monotonic DTW, and exact raw-
      transcript reconciliation.
- [ ] Bound alignment latency, memory, word count, token count, and artifact
      size. Reject NaN/Inf, non-monotonic, overlapping, out-of-source, missing,
      or transcript-divergent intervals.
- [ ] Publish `alignedWords: []` plus a typed unavailable reason when the
      provider/language or evidence fails its gate. Never invent even spacing,
      confidence, or speaker attribution.
- [ ] Retain Qwen3 ForcedAligner only as a separately licensed/measured
      challenger for supported languages.

### 8. Complete the review UX and contract migration

- [ ] Present primary, per-job fixed, suggested, dynamic, unknown, unsupported,
      and timing-unavailable states in plain language.
- [ ] Keep detected labels correctable without mutating retained source or a
      previous immutable server result.
- [ ] Migrate persisted/job/result contracts with backward-readable Phase 5
      records and fail-closed handling for future/unknown schemas.
- [ ] Preserve History ownership and one canonical transcript/review surface.
- [ ] Add accessibility coverage for picker keyboard use, labels, focus,
      reduced motion, errors, and non-color-only quality/status communication.

### 9. Reconcile evidence and close the exact head

- [ ] Resolve focused correctness, security, privacy, license/provenance,
      maintainability, accessibility, and resource-bound findings.
- [ ] Update ADR implementation scores only for behavior proved by executable
      tests and observed runtime evidence.
- [ ] Reconcile current architecture, Voice OS synthesis, roadmap, status,
      OpenAPI, runbooks, and this plan with what actually executes.
- [ ] Freeze one Phase 6 candidate and run the complete applicable local/native/
      server/GB10 matrix exactly once.
- [ ] Open a focused PR, require hosted exact-head CI/CodeQL and any applicable
      disposable-Windows lifecycle evidence, review the checked SHA, and merge
      only that green reviewed head.

## Focused development verification

Run only the checks that cover each edited surface while developing:

- OpenAPI/examples and Python/Rust/TypeScript contract fixtures;
- Rust language-preference, migration, VAD/manifest, ledger-stage, result-
  admission, restart, cancellation, retention, and path-safety tests;
- React setup/settings/queue/history accessibility and state-projection tests;
- portable Python capability-catalog, component-lock, LID-probe, provider-route,
  result, alignment, containment, and restart tests;
- isolated public-fixture smoke/accuracy/resource checks on the relevant server
  component; and
- formatting, static analysis, dependency/provenance contracts, and diff checks
  for the changed languages only.

Do not run unrelated suites for a scoped change. Do not use a full Codex
Security plugin scan as a Phase 6 gate; normal security-aware design, focused
tests, dependency/provenance checks, and code review remain required. The next
full plugin scan is reserved for the accepted Phase 10 enterprise checkpoint,
and private scan material never enters this repository.

## One-time Phase 6 gate

The complete gate runs once only after code, contracts, docs, provenance,
focused reviews, and public-safe evidence are ready on one immutable candidate.
It must prove at least:

1. frontend install/build/unit/Playwright and required native WDIO pass;
2. Rust format, warnings-denied Clippy, library/integration/connector tests,
   dependency audit, and Windows dependency boundary pass;
3. portable Python 3.12 server/contract/component/runtime/infra tests pass;
4. backward-readable Phase 5 state plus Phase 6 migration/restart/cancel/retry/
   retention and result-admission behavior pass on the exact head;
5. the capability catalog exactly matches verified model locks and excludes
   Nemotron adaptation-ready locales;
6. primary/fixed/suggested/dynamic/unknown flows preserve explicit user choice
   and never manufacture a language confidence;
7. VAD failure preserves source audio and bounded transport; alignment failure
   publishes an explicit unavailable result rather than fabricated timing;
8. public representative fixtures exercise advertised locales/tiers without
   promoting unmeasured broad-coverage quality claims;
9. GB10 uses the exact locked Python 3.12/NVIDIA runtime, records WER/CER/LID/
   alignment/resource ceilings appropriate to the promoted capabilities, and
   leaves no owned container, process, model port, or listener; and
10. the LAN/SSH-forward development path still reconnects without claiming
    production authentication, persistent service, external networking, or an
    IT-owned enterprise deployment.

Any executable change after the complete run invalidates the candidate and
requires an explicit gate decision. Documentation-only evidence correction
must still be reviewed and must identify the unchanged checked SHA.

## Phase boundary and prohibited scope

- No Entra/MSAL, user/profile database, named speaker identity, OKF/agents/MCP,
  HTTP/3/UDP edge, external listener, certificate, DNS, ZPA, firewall policy,
  persistent production service, or repo split.
- No adaptation-locale fine-tuning, unsupported language claim, automatic
  cross-provider voting, or word-level code-switching claim.
- No new desktop model router, bundled desktop Python runtime, or alteration of
  the pinned local Nemotron fallback contract.
- No private recordings, transcripts, scan findings, host paths, raw benchmark
  output, tokens, credentials, or enterprise configuration in Git or PRs.
- No ADR score/status inflation before implementation evidence exists.
