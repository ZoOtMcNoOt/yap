# Current Status

**As of:** 2026-07-24

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
| Phase 6: preprocessing | Bounded final repair review passed; replacement gate pending | [ADR 0024](adr/0024-global-language-routing.md), [ADR 0025](adr/0025-provider-specific-asr-serving.md), [ADR 0026](adr/0026-ambernet-batch-language-preflight.md), and the [active plan](plans/active/2026-07-16-audio-preprocessing-and-language-routing.md) govern local language spans, guarded batch preflight, language/routing/timing, and provider-specific ASR serving. Exact executable candidate `97b63be46b05dffa21595f2fd081b8467bb95798` passed its frozen 30-child local/native/server/private-runtime attempt, but the required final adversarial review found restart/cleanup, OpenAPI, hosted-closure, evidence-bound, and persisted-vocabulary defects and explicitly invalidated that SHA as merge authority. Its receipt remains historical evidence. Admitted replacement `4b87e222c8ad7325a12a88709a52b5e9c1baf22e` failed before provider startup because its image build forced a registry lookup across the offline GB10 boundary; exact cleanup passed and that SHA cannot be retried. The current checked-runtime and containment repair passed one bounded final three-agent re-review. Runtime images are now prepared before admission and emit private receipts after a second clean-head check. Admitted gates verify the frozen receipt hashes, exact prepared ARM64 IDs, revisions, base digests, and runtime identities by inspection, launch those IDs, and bind them into evidence. One new complete gate remains before PR closure. The selector still exposes only gated Cohere `en-US`; `wordAlignment` remains false; the local automatic route remains explicit default-off Preview because its frozen natural-switch target failed; and neither resident provider is promoted. Phase 8 owns Tiron/provider promotion; Phases 7 and 10 own authentication and persistent supervised mixed-load production. |
| Phase 7: identity/access | Planned | Entra/MSAL, token-derived ownership, purpose grants, and authorization remain unimplemented. |
| Phase 8: meeting evidence | Accepted direction; not implemented | [ADR 0027](adr/0027-tiron-joint-speaker-attributed-meeting-transcription.md) selects pinned Tiron's eight-window/eight-global route as the server development baseline, queues a separately gated speaker-epoch extension for larger speaking rosters, and retains local anonymous evidence plus an ASR-plus-diarization fallback. No Tiron worker, reconciler, scorer, messy-meeting promotion result, or production speaker result path exists. |
| Phases 9–10 | Planned | Follow the accepted order in the [roadmap](roadmap/ROADMAP.md). Enterprise infrastructure remains an explicit IT/security handoff. |

Replacement admissions `7d5d1b79f0f539ca3e4c1160ed25c32442cc3fa3`
and `6b4eda32ca3853c90b40db607248fab5af23048e` are failed historical
evidence, not merge authority. The first exposed Docker 29's exact
post-removal network-absence wording after its target-client and provider
workloads; the checked fix requires an exact message match and preserves
fail-closed handling for all other daemon errors. The second was invalidated
when lid-triggered Windows Modern Standby suspended its local responsiveness
clock and reset the live SSH process. Exact remote cleanup passed after the
transport failure. The next admission must keep the controller lid open and
supervise the long GB10 lifecycle independently of the SSH transport.

The local exact-duration runner starts at the truthful prepared-audio-frame
boundary, streams ten-millisecond frames through Yap's production bounded
adapter and single live worker, and cycles finalization across one explicitly
selected, hash-bound functional profile. The Phase 6 `short-boundaries` profile
contains only the nine 250-ms-through-30-second cases. The separate
`complete-local-duration-ladders` profile retains all 15 cases through two hours
for later release qualification. Exact head, profile, plan, private suite,
manifests, raw WAV, and decoded PCM are hash-bound; evidence contains no
transcript or path. The companion Python builder atomically publishes only the
selected private suite from caller-supplied vetted sources under external
`YAP_EVAL_CACHE`.

Phase 6 does not spend several wall-clock hours qualifying a default-off Preview
or a replaceable server provider. The proportional target-client evidence is
complete: prepared audio owns speech and transcription evidence, while the
unattended 30-second UI smoke owns capture lifecycle, responsiveness,
save/delete, production quit, and teardown.
Longer manual physical-device and real-time local soaks remain available for
default-on or Phase 10 release qualification. Broad server-provider duration
and output-behavior comparison belongs to the Phase 8 Tiron decision.

Focused Phase 6 provider-duration evidence now reaches the exact four-hour
transport ceiling through both Cohere vLLM and resident NeMo with bounded result
publication and complete container/listener teardown. The inputs repeat one
licensed fixture, so this is duration/lifecycle evidence only; sentinel-rich
long-form correctness, representative quality, frozen p50/p95/p99 capacity, and
provider promotion remain open.

The checked-head resident exact-duration runner has now passed the frozen
candidate gate. It selects only the plan-owned Cohere vLLM or Nemotron NeMo
unpaced ladders, runs each exact duration once at c1, and can include the
four-hour boundary only for batch. Its evidence explicitly says
`duration-transport-and-lifecycle` and `representativeAccuracyClaim: false`;
quality, sentinel integrity, concurrency, and promotion remain separate.

Executable candidate `aa3268d73ae9a811e84534387c8399ced2cc07e1` built and
independently reloaded one private 18-track provider-duration suite from the two
license-vetted AMI prepared views. The checked locks also reverified both
already-present model directories without starting a service. This closes input
preparation only: no provider runtime cell, lifecycle wrapper, frozen gate, or
promotion claim was consumed.

The historical sequential resident-provider lifecycle wrapper published one
complete exact-head GB10 aggregate for candidate
`97b63be46b05dffa21595f2fd081b8467bb95798`: all 18 then-current
candidate-safety children and exact host teardown passed. Final review later
invalidated that SHA as merge authority, so this receipt proves only the
historical wrapper and remains outside Git with its raw logs, samples, and
snapshots.

The repaired wrapper has not yet published a replacement aggregate. It verifies
already-present models and receipt-bound, already-prepared exact-head ARM64
images; launches each provider by immutable image ID without a Docker-published
port on a temporary internal bridge; durably owns the bounded loopback-proxy
process-group identity; verifies blocked container egress; runs the plan-owned
duration/load/cancellation/capacity/resource cells; and publishes only after
complete child evidence plus clean launcher, proxy, container, network, and host
teardown. Those behaviors remain implementation awaiting the one replacement
gate, not evidence already earned by `97b63be...`. Representative quality,
provider promotion, and later production capacity also remain open.

The provider-qualification code now separates ordinary load, cancellation,
capacity, and fixed/automatic-language semantics. vLLM cancellation evidence
retains engine finish reasons and recognizes that the pinned external-disconnect
abort path frees a request without adding it to finished-request histograms;
counted abort, completion-after-cancellation, and ambiguous shapes remain
distinct. Its 17-request capacity cell now targets the truthful Yap owner:
eight running plus eight queued batch-pool reservations, not an invented vLLM
429; aggregate PCM reservation is gated at the same owner. NeMo retains its
separate authenticated eight-active plus one-429 service cell. The fixed/auto
runner requires the distinct identity-rich fixed and automatic source-span
contracts from the same locked source at c1/c8, while recording lexical and
exact punctuation/casing parity separately for later provider promotion.
Focused dirty-head GB10 controls passed all of these semantic cells,
including rejection/retry and clean teardown. The private frozen representative
quality, percentile, resource-slope, and promotion decisions remain open.

Exact head `27108e1f591920b5a62496f988ae9ee7b335f2ce` passed the complete Cohere
lifecycle and teardown, then NeMo readiness, both duration ladders, short-tail,
and 15-minute request lifecycle. Its fixed and automatic paths each completed
16 c1/c8 results with correct automatic `en-US` source-time evidence, but the
checker incorrectly required lexical equality despite automatic segmentation
changing the decode boundary. Cleanup was exact. The renamed
`nemo-finalized-fixed-auto-contract` cell now gates only the identity-rich
language contracts and records text parity for Phase 8. A new plan-bound private
suite and exact-head rerun remain open.

Exact head `2b9118ead1df1f3220da65846c2aa8949d90d83d` loaded the new
plan-bound 18-track suite and passed all Cohere children plus nine of ten NeMo
children. NeMo completed all 1,600 c8 resource requests and passed its memory,
allocation-extent, duration, sample-count, and memory-event checks, but the
resource observation failed closed at 262 cgroup tasks/entrypoint threads
against the frozen 256 ceiling. A fresh ready process measured 63 tasks and a
focused c8 wave reached 222; the complete preceding lifecycle entered its final
cell at 224 and reached 262, exposing cumulative native-library pools rather
than failed requests or active CPU saturation. Both providers, their proxies,
listeners, and the temporary network were removed, and no aggregate published.
An independent finalizer replay also found a stale mixed-window expectation:
the plan and child correctly selected both 30-second and 15-minute inputs while
the aggregate expected only 15 minutes. The finalizer now requires both members;
the runtime now bounds BLAS/OpenMP/Rayon and PyTorch pools to eight and derives
18 HTTP workers from the eight-active-request contract. Exact head
`17a727f272943e6bc57a4253247e7e824855c086` then passed a focused c8/200
request-lifecycle wave in 18.930 seconds at 316.957 audio-seconds/second and a
focused c8/1,600 resource profile with all eleven frozen checks. Fresh readiness
used 34 tasks; both workloads peaked at 97 tasks/entrypoint threads, versus 222
and 262 before the correction. Maximum current/peak cgroup memory was about
3.61/6.03 GiB, average CPU use was 1.013 cores, memory-event deltas were zero,
and teardown was exact. The frozen 256 ceiling did not change. At that point,
the complete exact-head lifecycle evidence still remained required.

Exact head `a21964c19e56648e9fddcb5200de419e59a7687c` then passed the complete
sequential resident-provider lifecycle. Its plan-bound private suite used plan
SHA `d82a770c77d879c5f9d3bd5098e5933ef91f9162971e9f660bf06552c829926f`;
the bounded public-safe aggregate has evidence SHA
`a6931acc127f2ca74e6d3a4c8c9aa6c93e33289f1d1312a4626d659dfcbeb9cb`.
All 18 Cohere/NeMo children passed, including the exact four-hour transport
control, fixed/automatic language contracts, cancellation, bounded admission,
and c8/1,600 resource cells. The NeMo resource cell completed 1,600 requests at
c8 with 105 maximum cgroup tasks and entrypoint threads against the unchanged
256 ceilings, zero memory events, 4,706,910,208 bytes maximum current memory,
and 6,475,702,272 bytes peak memory. Its mixed long-window evidence selected
both 30 seconds and 15 minutes. The final read-back found no provider container,
network, runtime process, or listener on ports 18000/18001 and unchanged
listener, firewall-observation, and service-unit snapshots. This is a
candidate-safety result only; both replaceable providers remain unpromoted and
Phase 8 retains the broad Cohere-versus-Tiron quality decision.

Focused resource controls now complete four consecutive c8/400-request repeats
per resident provider. vLLM processed the warm repeats at about 321-322 audio-
seconds/second with flat tail cgroup/allocation extent, less than 3.12 GiB
current and 5.75 GiB peak cgroup memory, and zero memory-event deltas. NeMo
processed all 1,600 requests at about 269-274 audio-seconds/second with one exact
identity, stable 1,296/4,956 MiB CUDA allocated/reserved counters, less than
3.66/6.04 GiB current/peak cgroup memory, and a 0-8-KiB tail change in its fixed
entrypoint allocation extent. Its physical RSS is a measured GB10 unified-
memory residency/reclaim sawtooth, not accumulating CUDA or Python object state.
The NeMo HTTP boundary now reuses bounded workers and reduced warm median queue
time from about 24 ms to 3-5 ms. Runtime-plan schema 5 freezes separate
c8/1,600 current/peak/allocation-extent/task/thread/memory-event ceilings for the
one-time checked-head gate. Both current-source profiles passed all eleven
focused checks and clean teardown; that does not promote either candidate or
replace the later provider-promotion evidence.

The sustained Cohere exact-track control also resolved its two reported
transcript identities: all 200 requests retained the same 92 lexical tokens,
while 11 omitted four commas. Neither in-process V1 execution nor vLLM's pinned
batch-invariant mode removed the rendering split. Provider-behavior promotion
evidence requires one lexical identity per repeated audio duration and reports
exact rendering counts separately. Phase 6 request-lifecycle evidence records
that variance while requiring identity-rich results, non-empty speech output,
planned concurrency, provider-idle read-back, and teardown. The still-open
representative-quality gate keeps punctuation scoring independent. No serving
candidate is promoted by this dirty-head result.

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
  bundle through in-process `sherpa-onnx` after explicit installation. Warmup
  requires the explicitly confirmed primary locale, validates the exact
  32-locale out-of-box allowlist, applies it to stream creation/reset, and fails
  unsupported locales visibly. A preference change retires stale idle warm
  state. On the active Phase 6 branch, automatic routing is optional and uses
  the explicitly imported AmberNet/Silero component only across user-selected
  Nemotron locales. The control is default-off and visibly labeled Preview;
  availability is not a locale-specific quality claim. Three consistent
  observations and a `0.40` margin are
  required; ambiguity, silence, unsupported labels, or runtime failure retain
  the primary locale visibly. Acoustic labels never invent a regional locale.
- Imported Phase 5 jobs admit only already-canonical mono PCM16/16 kHz WAV at
  this boundary, prepare immutable Yap-owned artifacts, and persist progress in
  native SQLite.
- On the active Phase 6 branch, imported canonical WAV jobs record deterministic
  identity normalization and optionally run the explicitly installed, exact-
  hash Silero model through the existing CPU `sherpa-onnx` runtime. Ordered
  source-time intervals or a typed bounded error are durable advisory evidence;
  neither outcome truncates or replaces the complete source.
- Desktop schema 9 owns normalization, VAD, LID-preflight, and user-confirmation
  attempts. Server schema 5 owns ASR, alignment, and result-publication attempts.
  Legacy state remains readable without manufacturing missing history.
- The development server path binds to numeric loopback. The desktop reaches a
  private node through an explicitly managed SSH forward; Yap does not create
  or silently fail over that tunnel.
- The private server validates bounded create/upload/commit requests, persists
  job/chunk/result state, and publishes an immutable result. The merged baseline
  remains the bounded raw PyTorch/Transformers Cohere reference worker. On the
  active branch, Cohere defaults to a digest-pinned vLLM candidate behind the
  same worker contract and a required loopback/API-key boundary; its composed
  candidate-safety lifecycle with resident NeMo passed at exact GB10 candidate
  `97b63be46b05dffa21595f2fd081b8467bb95798`. Locked Nemotron Transformers routes
  remain correctness references. A pinned resident NeMo candidate now executes
  behind its own authenticated numeric-loopback adapter and checked launcher,
  but is not selected and does not implement client-facing live transport. None
  is advertised as persistent supervised production capacity, and SGLang
  remains reserved for later agent workloads.
- The non-production evaluation package locks FLEURS `es-419` source identity,
  validates its private corpus boundary, runs the exact Cohere fixed-language
  route in true batches, publishes per-case evidence only to owner-restricted
  external caches, and emits a transcript-free aggregate. The full 908-case
  GB10 comparator passed; it does not alter the advertised model catalog.
- Native code verifies result identity, authority, hashes, paths, sizes, and
  transcript bytes before History can present completion.
- Native shortcut and OS-drop work use fixed workers with bounded queues;
  interactive file selection and server-settings publication each admit one
  end-to-end owner rather than accumulating blocking work.

The complete owner and trust-boundary map is
[executable ownership map](architecture/boundaries/EXECUTABLE-OWNERSHIP.md). The
focused Phase 6 ownership deltas are recorded in ADRs 0024–0026 and the active
plan. ADR 0027 records a future Phase 8 decision only; it is not executing
ownership.

## What is not claimed

- No WSS/live server transcription, general media conversion, production
  authentication, external application endpoint, persistent supervised
  multi-user service, or measured multi-worker capacity is shipped.
- No Entra/MSAL token validation, tenant-derived owner, purpose grant, internal
  DNS, enterprise certificate, ZPA policy, or production firewall rule exists.
- Phase 7 owns authenticated tenant/user derivation. Persistent warm model
  services, multi-worker and mixed live/batch capacity promotion, production
  supervision/observability, and external deployment remain Phase 10 gates;
  they are not Phase 6 completion criteria.
- Phase 6 has focused implementation slices on the current branch: a verified
  runtime may publish a bounded, fingerprinted ASR catalog through a separate
  endpoint and native projection; an origin-bound last-known snapshot explains
  offline state without becoming availability; a versioned Rust-owned primary
  language is explicitly confirmed; local warmup consumes that decision without
  implicit English/auto fallback; and each imported job freezes its primary/
  manual decision through SQLite, preprocessing manifest, and server create
  contract. Picker/drop proof is retained before a new non-runnable
  `accepted` row can commit; active playback is projected before that exact row
  becomes runnable, and restart recovery cannot recreate proof from the ledger
  path alone. Preprocessing revalidates the path-scoped authority, drain errors/
  retries retain the exact selected job identity, and a metadata-only SQLite
  write probe keeps the drain circuit-broken after a persistence failure until
  durable writes recover. React only projects native preference/catalog truth.
  The shipped catalog still honestly exposes only the gated Cohere `en-US`
  fixed-batch route. The visible per-job selector presents that exact catalog;
  it does not manufacture an alternate while provider replacement remains an
  evidence-gated Phase 8 question.
  Normalization, advisory VAD, and the optional explicitly imported AmberNet
  acoustic-LID path now execute with durable attempts/evidence. The local path
  retains one Nemotron ASR, one warm runtime owner, bounded exact-once language
  handoff, and source-time spans. Focused eight- and four-logical-CPU i7
  development-host profiles prove exact-source routing, paced zero-loss queueing,
  bounded drain, under-real-time combined execution, and teardown. The consumed
  natural-switch quality target failed and fixes the Preview boundary rather
  than remaining an unfinished pass. Exact candidate
  `97b63be46b05dffa21595f2fd081b8467bb95798` passed current-host
  resource/interference, sustained lifecycle, accessibility, and the complete
  checked-head Phase 6 matrix. The
  isolated AmberNet CPU batch preflight, durable desktop request/retry/
  cancellation path, strict five-region agreement, and explicit user
  confirmation execute under focused Python 3.12/Rust/React tests. Windows
  real-model and disposable ARM64 parity smokes exist. Exact executable commit
  `c6862262fa36a83bcd40a7bffa65ec6429ec097e` passed the focused ARM64 real-worker
  resource/teardown smoke. Exact executable head
  `a21964c19e56648e9fddcb5200de419e59a7687c` then passed the final source-exact
  ARM64 production-worker repetition with bounded CPU/memory/PIDs and complete
  teardown. The
  old SpeechBrain GB10 receipt is historical, not current-runtime evidence. The
  server Nemotron fixed/automatic routes,
  dynamic server tags, fail-closed Cohere word alignment, and the Cohere vLLM
  adapter/image/launcher contract and the resident Nemotron NeMo worker/service/
  image/launcher now execute, and their composed candidate-safety lifecycle
  passed again inside exact candidate
  `97b63be46b05dffa21595f2fd081b8467bb95798`. They remain
  unadvertised or unselected: `wordAlignment` is still false, and broad Cohere
  output-stability/quality plus representative Nemotron locale/quality evidence
  remain later provider-promotion work. The
  retired Triton experiment remains negative evidence because its cross-request
  tensor batching changed a Cohere transcript and its parity-preserving profile
  serialized model execution without a demonstrated throughput gain. Server
  live remains false.
- Phase 8 Tiron/local speaker inference, the frozen messy-meeting gate, speaker
  result publication, and reconciliation remain deferred; selecting the server
  development baseline is not implementation or production promotion. Phase 9
  knowledge/agent behavior also remains deferred.
- Private security scans, scan identifiers, host paths, and detailed private
  findings are not repository or PR material.

## Phase 5 checked-head evidence

Phase 5 PR head `4771d9be60562fa009ccecbcd3c7111b699883a5` passed the
one-time local/native/server/GB10 gate and was merged by
`b6677631b2cc8283f0f6466622f2dfa7cfdb38f6` on 2026-07-15.
Hosted frontend, Rust, server, required native WDIO, and CodeQL analyses for
Actions, JavaScript/TypeScript, Python, and Rust were green on the checked PR
head. Exact counts and environment observations remain in the completed
[remote recording transcription record](plans/completed/2026-07-14-remote-recording-transcription.md)
and [verification record](evidence/executable-ownership-review/VERIFICATION.md).

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
[executable ownership review verification](evidence/executable-ownership-review/VERIFICATION.md).

## Phase 6 historical checked-head evidence and invalidation

Exact executable candidate `97b63be46b05dffa21595f2fd081b8467bb95798`
passed the one-attempt integrated Phase 6 gate on 2026-07-24. The frozen
manifest SHA-256 is
`8c59a08174a2c1a7e72bef59fefc6a8160ca65982736e0ba7b18f853d893affd`;
the independently validated 30-child candidate receipt SHA-256 is
`798f3fcef3709f9751d1e7fc1a8c31b5bf2e429c2cf08efedad4a03b77d87f8d`.

The admitted target-client channel passed 12/12 repeated native cycles, all
nine 250-ms-through-30-second prepared-audio cases, and the release-mode
microphone/UI lifecycle. The GB10 channel passed the composed 18-child Cohere
vLLM/Nemotron NeMo suite; its public-safe aggregate SHA-256 is
`6a126aacd6fdcc1904ce2633dcebdb0b68d70a50a84cedc20301e97457fc4272`.
The connected channel proved one immutable job across a stopped and restored
SSH forward, durable preprocessing, server-authoritative result publication,
verified History review, and exact teardown. The complete command matrix passed
frontend accessibility/workflows, production build, release/provenance and
dependency contracts, Rust format/Clippy/tests/audit/Windows boundary,
server-connector integration, required native WDIO, and the portable Python
3.12 server suite.

Private audio, transcripts, raw metrics, process ledgers, host paths, and logs
remain outside Git and hosted artifacts. This candidate gate did not promote a
provider or supply hosted PR closure. Final adversarial review subsequently
identified concrete restart/cleanup, normative OpenAPI, hosted-closure,
evidence-bound, and persisted-vocabulary defects. Executable repairs therefore
invalidated `97b63be...` as the merge candidate. Its hashes above remain a
truthful historical receipt, not authority for the repaired head.

Admitted replacement
`4b87e222c8ad7325a12a88709a52b5e9c1baf22e` failed before provider startup
when its checked image build forced a registry lookup across the deliberately
offline GB10 boundary. The concurrent Windows channel was stopped and exact
cleanup passed on both hosts. That attempt remains failed private evidence and
cannot be retried, resumed, or represented by the historical passing receipt.
Runtime-image preparation now occurs before admission and emits a private
receipt only after a second clean-head check. The admitted gate verifies the
frozen receipt hashes, inspects the already-prepared exact-head images, and
fails closed on a missing or mismatched image ID, architecture, revision,
base-digest identity, or runtime identity.

## Active next steps

The living [decision and evidence queue](plans/active/2026-07-17-voiceos-decision-evidence-queue.md)
preserves the detailed discussion register, open questions, later-phase owners,
and reviewable sub-tasks. The active Phase 6 plan remains the delivery authority.
The concise
[integrated MVP validation and delivery control](plans/active/2026-07-23-integrated-mvp-validation-and-delivery-control.md)
is the ordered closeout checklist: validate the complete workflow before broad
provider optimization or non-blocking architecture work.

1. Freeze one clean replacement SHA from the focused-verified,
   three-agent-reviewed checked-runtime repair.
2. Run the complete replacement matrix once, keeping all private evidence
   outside Git and recording only bounded public-safe aggregates.
3. Open the focused Phase 6 PR and require hosted CI/CodeQL and applicable
   Windows checks on the reviewed PR head.
4. Merge only that reviewed green head, then start the separately queued
   Checkpoint B before Phase 7.

Broad Cohere-versus-Tiron comparison remains the Phase 8 model/meeting decision
point. Checkpoint B reviews broadly but changes narrowly before that integrated
decision: concrete blockers are fixed, while non-blocking optimization is
recorded rather than allowed to delay the MVP.
