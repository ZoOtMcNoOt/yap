# ADR implementation status

**Status:** Living, non-normative implementation audit
**As of:** 2026-07-22; Phases 3–5 and Architecture Checkpoint A are merged and their checked-head evidence remains recorded below. Phase 5 PR head `4771d9be60562fa009ccecbcd3c7111b699883a5` passed the one-time complete local/native/server/GB10 gate and hosted checks, then merged as `b6677631b2cc8283f0f6466622f2dfa7cfdb38f6`. Checkpoint implementation candidate `6d55816b0406a2365376d7b2d9a7da2afecf9118` passed its one-time complete matrix; final PR head `2dc1c48c31928106d07cc638828f055929c33e0c` passed hosted CI, CodeQL, and disposable-Windows NSIS, then merged as `a80934d844a068110e7f86b30b6e29d35146db57`. Phase 6 is active; ADR 0024 now has focused executable catalog, fixed-language decision, local primary-language conditioning, durable-stage, normalization, advisory-VAD, local language-span, isolated SpeechBrain preflight, and released-candidate slices. ADR 0025 replaces the retired Triton experiment with focused Cohere vLLM and resident Nemotron NeMo adapter/image/launcher contracts. The automatic local route is implemented only as an explicit, default-off Preview after its representative natural-switch quality target failed; Phase 6 has not passed its complete gate or promoted a second fixed locale, Cohere vLLM service, or Nemotron NeMo service.
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
| [0001](adr/0001-dual-stt-backends.md) | Live fallback vs official batch principle retained; model details amended by 0014/0019 | Shared | **150** | In-process pinned Nemotron live fallback plus the gated Phase 5 durable loopback batch path through the isolated Cohere worker with verified native result publication | No WSS/live, authentication, persistent production service, external edge, general media conversion, or measured production capacity | Retain the two-route policy while later phases harden transport, identity, media preparation, and deployment |
| [0002](adr/0002-crispasr-unified-stt-runtime.md) | Historical; replaced by 0019 | Client | **0** | No tracked or wired CrispASR runtime | Entire retired runtime path absent by design | Do not revive; use 0019 |
| [0003](adr/0003-long-term-voice-architecture.md) | Long-term principles retained; runtime, meeting, and language details amended by 0013/0014/0019/0020/0024 | Shared | **65** | Capture, local ASR, overlay, history, hotkeys, safe Windows clipboard delivery, the gated Phase 5 loopback server-batch path, local language spans, and guarded batch LID cover early layers | No promoted multilingual server routes, production server deployment, enrichment, OKF, agents, or KB | Follow the canonical remaining phases and ADR 0024, not its historical phase map |
| [0004](adr/0004-background-diarization-okf-agents.md) | Non-blocking background principles retained; diarization details superseded by 0020 | Shared | **45** | Independent bounded sinks, track/gap/chunk contracts, crash-safe recording, evidence/result types | No production speaker sink, worker, diarizer, alignment, OKF, or agents | Phase 8 uses 0020 authority; Phase 9 owns OKF/agents |
| [0005](adr/0005-llama-server-agents.md) | Accepted target; team placement amended by 0014 | Shared | **20** | Development-only Polish flow exists | Polish still calls Ollama; no bundled llama-server, manager, model pin, health gate, or profiles | Implement only when local/server LLM product work is activated |
| [0006](adr/0006-silero-agents-state-machine.md) | Accepted principles; routing and preprocessing amended by 0014/0019/0020/0024 | Shared | **100** | Connector state/capability projection, single warm Nemotron lifecycle, durable client/server stage attempts, and an explicitly installed/hash-verified Silero ONNX path now produce bounded advisory source-time intervals for imported canonical WAV while retaining complete source audio; the speculative unused umbrella orchestrator was removed during Checkpoint A | No live-microphone Silero/chunker, agent registry, LLM mutex/queue, authenticated live-server transition, or complete Phase 6 gate | Finish ADR 0024 preprocessing/routing; live endpointing and later LLM gates retain domain-owned orchestration |
| [0007](adr/0007-forced-alignment-engine.md) | Raw-transcript alignment principle retained; exact engine and promotion gates amended by 0024 | Shared | **10** | Aligned-word and revision contract placeholders plus aggregate English candidate research exist | No wired aligner, capability gate, source-bound word validator, fixture suite, worker, or published timing evidence | Implement ADR 0024's fail-closed Phase 6 path |
| [0008](adr/0008-speechbrain-lid-gate.md) | User-gated LID principle retained; runtime, probes, and threshold amended by 0024 | Shared | **100** | The Phase 6 branch has an ARM64 non-root/offline Python 3.12 CPU component, hash-locked SpeechBrain/Torch/model artifacts, bounded two-window materialization, uncalibrated suggestion policy, redacted API, durable desktop evidence/dispatch identity, restart cancellation, explicit React user confirmation, focused Python 3.12/Rust coverage, and a source-exact GB10 image/real-worker/two-probe/teardown smoke at `04266c4bbffd0fd31eaf2afd0bcce42e0248344f` | No checked-head peak RSS or sustained CPU result, representative locale promotion suite, second promoted fixed route, target-i5 evidence, or complete Phase 6 gate | Preserve the executing path and close its resource, representative, target-i5, and complete Phase 6 matrix evidence without treating the focused image smoke as promotion |
| [0009](adr/0009-knowledge-worker-protocol.md) | Solo protocol retained historically; team transport superseded by 0017 | Shared | **10** | Capture/chunk prerequisites exist | No worker, socket protocol, lifecycle, backpressure events, quarantine, or stitcher | Team work follows 0017; solo worker remains deferred |
| [0010](adr/0010-okf-conversation-schema.md) | Accepted Markdown/raw-preservation principles; historical schema superseded by 0022 | Shared | **20** | Durable TXT transcripts and immutable JSON revisions exist | No Google OKF validator/writer, Yap profile, glossary/actions, migration, or compiler output | Implement the ADR 0022 profile in the Phase 9 compiler |
| [0011](adr/0011-vector-rag-retrieval.md) | Accepted retrieval principles; team projection amended by 0017/0022 | Server | **0** | None | No FTS/vector store, embeddings, chunker, RRF, calibration, citations, permission filtering, or graph projection | Phase 9 after authoritative OKF and access boundaries |
| [0012](adr/0012-mcp-server-surface.md) | Accepted Phase 9 target; team hosting amended by 0017 | Server | **0** | None | No MCP runtime, tools/resources, transport, opt-in, authorization, or tests | Phase 9 after permission-filtered KB APIs |
| [0013](adr/0013-global-hotkey-injection.md) | Accepted as amended 2026-07-14; Windows hotkey and safe-delivery implementation active | Client | **180** | Dual safe defaults, native-confirmed 15-second physical-chord enrollment with neutral/chord/release and modifier floors, normalization and reserved/conflict rejection, Cancel/per-action Reset, transactional registration rollback, fixed-capacity two-worker shortcut dispatch, one exact-bounds non-focusable island, synchronous first-render reduced-motion projection, clipboard-only delivery with Yap HWND ownership and visible paste guidance, focused native WDIO, stock installer contract, and a passing hosted disposable-Windows lifecycle | No macOS/Linux hotkey/clipboard adapters, broad real-app clipboard matrix, exact-field authority for safe direct insertion, or verified local real-model/hardware lifecycle on this machine | Expand native compatibility and hardware evidence without reintroducing synthesized input without exact-field authority |
| [0014](adr/0014-server-tier-compute-topology.md) | Canonical server topology, amended/constrained by 0016/0019/0020/0021/0023/0024/0025 | Shared | **150** | Versioned contracts, bounded loopback capability API, validated connector with serialized settings publication, durable desktop/server job state, canonical-WAV preparation, descriptor-bound exact artifact reads, reconnect drain, verified result publication, hardened bootstrap, fixed-development-owner router seam, immutable Cohere/NGC/Python 3.12 locks, verified ASR catalog projection, the gated one-running/two-queued raw Transformers GB10 slice, pinned Nemotron reference adapters, a focused resident Cohere vLLM c2/c4/c8/parity/engine-abort/recovery/teardown proof, a resident NeMo worker/service/image/launcher with focused c8/cancellation/recovery/teardown evidence, and privacy-safe repeated-fixture duration controls through the exact four-hour boundary for both candidates; retired Triton results remain negative evidence | No promoted Cohere vLLM or Nemotron NeMo frozen lifecycle/capacity result, selected persistent warm production pool, general media conversion, authenticated owner/router, WSS/live pool, TLS/QUIC edge, representative long-recording benchmark, sentinel-rich long-form quality result, or measured multi-worker/mixed-load capacity | Preserve the gated transient references; close each provider's separate frozen gate; derive the authenticated owner/admission seam in Phase 7; implement external batch/WSS transport, persistent warm pools, observability, and measured multi-owner mixed-load capacity in Phase 10 |
| [0015](adr/0015-two-pass-diarization-speaker-identity.md) | Superseded by 0020 | Server | **0** | No implementation of the retired ECAPA/VBx design | Entire retired design absent by intent | Do not implement; use 0020 |
| [0016](adr/0016-auth-identity-bridge.md) | Canonical Phase 7 decision | Shared | **15** | Evidence/result contracts require provenance for named server assertions; Phase 5 uses an explicit SSH development boundary without treating it as application identity | No MSAL, credential storage, Yap-token validation, identity DB, grants, enrollment, deletion, or audit | Phase 7 after the private batch boundary passes its gate |
| [0017](adr/0017-knowledge-base-compiler.md) | Canonical team KB/compiler decision; format/projection amended by 0022 | Server | **0** | None beyond repository documentation | No Lane 1 store, `yap-knowledge`, compiler, databases, permission inheritance, APIs, or IaC | Phase 9 after identity and result authority |
| [0018](adr/0018-three-repo-topology.md) | Accepted eventual topology; staged monorepo retained through MVP | Shared | **45** | `desktop/`, `server/`, `infra/`, and `docs/` staging layout now contains an executable client/server batch boundary without premature repo extraction | No three-repo split, independent CI/CD/access controls, link migration, or cross-repo version policy | Split only at Phase 10 after deployable server/knowledge boundaries |
| [0019](adr/0019-local-streaming-model-selection.md) | Canonical single-ASR client fallback decision; narrowly amended by 0024 for one auxiliary acoustic-LID component | Client | **180** | Pinned model revision/SHA artifacts, in-process sherpa Nemotron, warm lifecycle, setup controls, profiler, native tests, local release/packaging contracts, a passing hosted stock-NSIS lifecycle, verified sherpa/native-runtime plus Silero provenance, and one `LiveRuntime`-owned optional resident LID/span/handoff implementation under focused tests | No completed Nemotron model-artifact license review, local-Nemotron use of the licensed speech/WER fixture, real-model CI accuracy smoke, cross-platform evidence, or promoted resident LID artifact/resource/switch-point gate | Close the Nemotron and 0024 promotion gates without adding an ASR router or second lifecycle owner |
| [0020](adr/0020-meeting-capture-diarization-authority.md) | Canonical meeting/capture/identity authority | Shared | **100** | Source-aware sessions/tracks, exact gaps, bounded sinks, crash-safe recording/recovery, one-worker bounded native-drop admission with an exclusive picker lease, gated canonical-WAV upload/reconnect, verified server-authoritative result revisions, finite retention, and naming restrictions | No general media conversion, system loopback, meeting UX, speaker model, speaker reconciliation, contacts, or identity service | Phase 6 preserves the capture/result contracts; Phase 8 adds speaker inference/reconciliation |
| [0021](adr/0021-http3-secure-edge-transport.md) | Accepted gated HTTP/3 edge target; the application remains loopback HTTP/1.1 | Shared | **0** | Transport-neutral job semantics execute over the gated Phase 5 SSH-forwarded loopback batch path; live-carrier and TCP-fallback direction remain documented | No TLS/QUIC edge, UDP exposure, client HTTP/3 path, negotiated capability, authenticated live baseline, fallback drill, or transport benchmark | Complete the Phase 7 authenticated baseline, then benchmark and security-gate the HTTP/3 edge |
| [0022](adr/0022-google-okf-permission-safe-projections.md) | Canonical Phase 9 Google OKF and permission-safe projection boundary | Server | **0** | Decision, pinned upstream revision, enterprise profile, permission algebra, baseline/challenger boundary, generation protocol, and verification gates are documented | No Google OKF fixtures/validator, Yap profile compiler, `yap-knowledge`, Postgres relationship/permission ledger, pgvector baseline, virtual view, or Neo4j challenger benchmark | Implement after Phase 7 identity and Phase 8 result authority are available |
| [0023](adr/0023-bounded-live-priority.md) | Accepted amendment to ADR 0014's priority rule | Server | **100** | The owner-fair reference router has focused regression coverage, and Phase 5 batch commits enqueue and immediately dispatch through one fixed development owner into the bounded pool | No live target in the executing runtime, authenticated owner, durable multi-tenant router queue, persistent production service, or measured mixed-load tuning/capacity | Phase 7 replaces the fixed owner with the authenticated admission seam; Phase 10 integrates the durable live/batch router and proves multi-owner fairness, bounded overload, cancellation isolation, restart recovery, fixed resource ceilings, and sustained mixed-load SLOs |
| [0024](adr/0024-global-language-routing.md) | Accepted canonical Phase 6 language, local language-diarization, provider, LID, and timing decision; serving details amended by 0025 | Shared | **145** | Public aggregate candidate benchmarks; bounded catalog/primary/job decisions; durable stages; deterministic normalization; pinned Silero lifecycle; exact AmberNet 1.12.0 QDQ INT8 frontend, one-thread static-ORT runtime, 107-label boundary, hash-verified local-import lifecycle, and frozen three-observation/`0.40`-margin policy; one warm `LiveRuntime` inference bundle; independent bounded detector/ASR cursors; exact-once stream transitions; visible primary fallback; a once-consumed 58-clip private holdout with 54 correct alternates, one abstention, three wrong alternates, and zero false alternates when the primary was correct; focused eight- and four-logical-CPU i7-13850HX profiles with exact-source routing, paced zero-loss queueing, bounded drain, scheduler-wake evidence, measured incremental memory, and teardown; a source-exact SpeechBrain GB10 image/real-worker/two-probe/teardown smoke at `04266c4bbffd0fd31eaf2afd0bcce42e0248344f`; an implemented checked-head/hash-bound streaming local duration runner at the prepared-audio-frame-to-final boundary whose multi-hour evidence remains unconsumed; historical Whisper, CrispASR, SpeechBrain, AmberNet natural/noisy, and Triton failures retained as negative evidence; revisioned decision-bearing local language spans; a shared boundary-explicit local/server span schema; model/utterance-plan-bound server spans linked to lossless text; source preservation; pinned server Nemotron Transformers fixed/auto references; fail-closed Cohere timing; immutable hash-chained detected-label corrections with concurrent/stale/tamper/restart coverage; backward-readable and future-failing contract migration tests; a private FLEURS `es-419` comparator that is not misrepresented as locale promotion; and focused Rust/TypeScript/Python 3.12/release-contract tests exist | No second promoted fixed locale/selectable override, target-i5 AmberNet/Nemotron interference and sustained-session resource evidence, checked-head SpeechBrain peak RSS/sustained CPU result, promoted aligned-word production, representative locale gate, complete accessibility audit, or complete Phase 6 matrix. The consumed natural-switch target failed and confines local automatic routing to explicit default-off Preview status. | Finish the accepted AmberNet target-i5/sustained safety gate without reopening model research or relabeling the failed quality result; follow ADR 0025 for provider runtimes; then finish timing, SpeechBrain resources, accessibility, and frozen performance gates on `feat/phase6-preprocessing-pipeline`. Removing Preview requires new independent natural/noisy evidence; authenticated ownership and persistent supervised mixed-load production service remain Phases 7 and 10 respectively. |
| [0025](adr/0025-provider-specific-asr-serving.md) | Accepted amendment replacing the universal Triton ASR plane with provider-specific runtimes | Server | **150** | Digest-pinned NVIDIA vLLM 26.06/Python 3.12 Cohere image contract; attributed TorchAudio Mel-filter shim; strict loopback/API-key/version/model readiness boundaries; bounded request/response validation; explicit socket interruption with observed vLLM engine abort; a focused GB10 resident Cohere exact-reference/c2/c4/c8/cancellation/recovery/teardown proof; provider-neutral Cohere and Nemotron workers; a pinned native NeMo cache-aware scheduler with checked prompt projection, c8 identity/admission tests, and a focused GB10 resident c8/cancellation/recovery/teardown proof; source-exact full-model image/adapter/teardown smokes for both providers at `fcccf21e785b116b92cd8e46150a36b9b5ee91db`; checked launchers; and retired Triton implementation removal | No frozen checked-head full Cohere lifecycle/parity/duration/capacity gate; no frozen representative Nemotron locale/duration/cache-state/memory/capacity/lifecycle gate; neither service is promoted; no persistent supervised mixed-user production boundary | Complete both independent frozen GB10 provider gates without changing provider-neutral job/result authority; keep authenticated ownership and persistent production supervision in Phases 7 and 10 |

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
head. These checks do not activate later product gates: there is still no
meeting RTTM/diarization fixture suite, live server pool, authenticated
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
