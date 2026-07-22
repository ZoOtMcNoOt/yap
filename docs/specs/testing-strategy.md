# Spec: Testing strategy

**Status:** Living verification contract (updated 2026-07-22); future phase gates activate only when their fixtures exist
**Scope:** Cross-cutting tests for the desktop runtime, track-aware audio contracts, local fallback, source-aware diarization, server contracts, and native UI.

This is the shared reference the phase specs point to for their acceptance tests.

**Current activation:** deterministic generated-tone and contract fixtures exist.
Phase 4 also has one committed, licensed LibriSpeech WAV with a locked golden
transcript and a standard-library WER gate for the private Cohere worker. The
Phase 5 added frontend, Rust, Python 3.12, API, contract, restart, reconnect,
cancellation, retention, result-publication, native, and GB10 coverage; its
one-time complete gate passed on exact PR head
`4771d9be60562fa009ccecbcd3c7111b699883a5`. The
desktop speech suite, meeting RTTM manifest, diarization benchmark harness,
bundled llama-server, and per-OS real-model matrix described below do not exist
yet. Phase 6 catalog, deterministic preprocessing/VAD, guarded server LID,
Preview local LID/span routing, provider-specific server candidates, alignment,
private-corpus trust, scoring, and runtime-qualification components now execute
under focused tests. The representative private promotion corpus, target-i5
hardware evidence, frozen checked-head GB10 comparisons, and complete Phase 6
gate remain open. ADR 0027 selects Tiron as the future Phase 8 server meeting
baseline, but no Tiron worker or meeting scorer executes yet. The tables below
distinguish executable focused coverage from future phase-gate requirements;
neither is a claim about ordinary hosted CI.

---

## 1. Test layers

| Layer | What | Tooling |
|-------|------|---------|
| **Unit** | Pure logic — error mapping, language code map, manifest serde, path naming | `vitest` (TS), `cargo test` (Rust) |
| **Integration** | Rust ↔ sidecar over real IPC; one fixture in → expected shape out | `cargo test` w/ sidecar launched; tagged `#[ignore]` unless binaries present |
| **E2E (smoke)** | App boots, overlay responds, desktop shell opens | Playwright for browser/Tauri shell surfaces; WebdriverIO for true desktop smoke |
| **Accuracy** | WER spot-check vs golden transcripts | Phase 4 standard-library WER gate now; backend-specific licensed suites later |
| **Diarization** | DER/JER, speaker count, short-turn recall, overlap, and identity false-name gates | License-clear RTTM fixtures + benchmark harness |
| **Reliability/privacy** | Gap recovery, batch reconnect/cancellation/restart/retention, consent, deletion, tenant isolation | Rust integration plus Python service/API/contract tests |
| **Performance** | Capture drops, ASR regression, CPU, RSS, and RTF | Deterministic profiler jobs; hardware results recorded separately from CI pass/fail when hosts differ |

Keep unit/integration fast and offline. Accuracy + E2E run on the per-OS matrix.

### Phase 5 checked-head boundary

Focused development suites ran while the candidate changed. The complete
Phase 5 local/native/server/GB10 matrix then ran once on frozen PR head
`4771d9be60562fa009ccecbcd3c7111b699883a5`. It exercised a licensed,
non-sensitive desktop import through preparation, SSH-forwarded loopback upload,
the actual GB10 worker, verified History publication, reconnect, cancellation,
retry, retention, and clean process/listener/container teardown. Private audio,
transcripts, host snapshots, and security-scan material are never repository,
CI-artifact, or PR content.

The native vertical-slice gate owns one explicitly configured SSH alias and
interrupts/restores that forward around the same durable client job; it never
accepts an already reachable local port. Cancellation races, user retry,
restart replay, malformed input, worker failure, saturation, storage limits,
and retention are covered by the complete Rust/Python matrix on the same frozen
SHA, while the GB10 portion supplies the real image/model/runtime/WER and clean
host-boundary evidence.

### Phase 6 target boundary

Focused suites cover each Phase 6 slice while the branch changes. The complete
local/native/server/GB10 matrix runs exactly once only after the provider
catalog, primary/per-job language flow, advisory VAD, durable stages, isolated
LID, fixed/dynamic routing, timing evidence, migrations, docs, and focused
reviews are ready on one frozen candidate.

The gate must use license-clear public fixtures to prove contract shape,
language decisions, representative advertised tiers, source preservation,
restart/cancel/retry behavior, alignment failure semantics, resource ceilings,
and clean teardown. Aggregate candidate research cannot promote a locale or
alignment capability by itself. Private recordings, raw benchmark output, host
paths, and scan evidence remain outside Git and hosted artifacts.

The local-language resource harness has two distinct development-host modes.
Its accelerated mode measures throughput, model load, incremental memory, and
ASR interference; its source-paced mode feeds the production-sized bounded
local-ASR queue at ten-millisecond source cadence while concurrently sampling
scheduler wake delay, frame loss, queue high-water, CPU use, and bounded drain.
A developer-host affinity limit is useful evidence but cannot replace the
actual i5-class Windows, rendered-UI/audio interference, energy, thermal, and
sustained-session qualification.

The deterministic local-duration runner starts at Yap's prepared-audio-frame
boundary, not at the physical microphone. It binds the exact checked Git SHA,
public runtime-plan hash, an out-of-band-hash-pinned private suite, every track
manifest, and both raw-WAV and decoded-PCM identity. It streams ten-millisecond
frames through the production-sized local-ASR queue, reuses the single live
worker across start/finalize cycles, and records exact accepted/dropped/decoded
sample counts, drain/finalization timing, and text-present booleans without
recording transcript text. It deliberately does not replace the native
microphone/rendered-UI target-device test or natural quick-correction accuracy
scoring. The machine plan therefore names this boundary
`desktop-prepared-audio-frame-to-final`; stronger microphone-to-final claims
require the separate hardware gate.

Build that suite with
`python -m yap_server.evaluation.local_stream_duration_suite`, one or more
repeated `--source` arguments naming vetted mono PCM16/16-kHz WAVs, and the
external `YAP_EVAL_CACHE`. The builder reads the two local ladders from the
validated plan, decodes and hashes each source once, rechecks raw identity
before publishing all 15 immutable tracks as one atomic private collection, and
prints the `suite.json` path and SHA-256 needed by the native gate.
`--expect-text-case` is opt-in per planned case; it
asserts only that text appears and must not be used to turn looped runtime
controls into accuracy evidence. Source license/provenance records and natural
references remain separately vetted private-corpus inputs.

The [ASR evaluation corpus and runtime qualification](../research/2026-07-17-asr-evaluation-corpus-and-runtime-matrix.md)
owns the Phase 6 corpus tiers, provenance manifest, per-slice metrics, live and
batch duration ladder, and risk-weighted concurrency matrix. Natural quality
evidence and deterministic duration/load evidence are separate requirements.
`server/asr-evaluation-plan.json` is the machine-validated runtime matrix. Every
quality case also carries a model-revision exposure decision; public benchmark
membership does not prove the model did not train on it. Only contractually
excluded or post-model-freeze sealed cases support independent promotion.

Resident-provider qualification aggregates additionally bind the full checked
Git head, clean worktree state, runtime-plan hash, and exact provider-serving
lock hash. The runner reads those identities before work and again before
publishing the evidence envelope. This prevents an otherwise valid private
result from being relabeled as evidence for a later candidate; the enclosing
GB10 lifecycle gate must still attest the launched image and teardown boundary.
Every provider workload also consumes one out-of-band-hash-pinned duration suite
derived from that plan; ad hoc track-manifest lists are not a gate interface.
Only the selected cell's audio is admitted, the loaded tracks are reused by the
runner, and the suite plus selected audio are re-read before evidence is
published.

That decision covers base-model and adapter/fine-tune lineage, and transformed
copies inherit their source exposure. Missing lineage evidence stays `unknown`.
The manifest is not its own trust root: independent cases use the dedicated
promotion loader, a private registry, an out-of-band registry SHA-256, and
hash-verified candidate-lock/freeze/exposure artifacts binding the complete
candidate set and exact case hashes. Every independent case also requires one
case-level human-reference receipt. The registry authorizes two distinct
listeners and an independent adjudicator, plus locale-reviewer and rights-owner
roles, and separately pins the blind assignment, reviews, adjudication, locale
basis, rights decision, source identity, attribution, and preprocessing
artifacts. Reviewed rights, known defects, locale, fractional recording time,
source URI/retrieval time, suite/condition labels, audio shape, speaker/timing
metadata, and candidate exposure set must match the manifest exactly. Artifact
reads recheck opened-handle cache containment, reject nonportable/alternate-stream
paths, and enforce per-file plus aggregate bounds. Schema v2 admits only natural
source audio
to that gate and rejects duplicate raw or decoded audio; derived and generated
inputs stay nonpromotion. Controlled suite/condition labels make required
acoustic slices auditable, while typed derivation recipes bind source-audio and
recipe hashes and cannot silently masquerade as natural coverage.
The private registry also binds an exact scorer lock and canonical per-case
evaluation-policy digest. Promotion scoring must use `score_manifest_case`,
which verifies the private reference, scorer lock, manifest identity, model,
hash-pinned inference-result/runtime lock, and manifest-frozen language/metric
policies before invoking the scorer. The inference-result lock binds the case,
hypothesis hash, raw and decoded audio, candidate lock, exact model revision,
and runtime identity. The adapter streams the verified PCM WAV and derives its
duration; a self-attested manifest duration cannot dilute silence metrics.
Private case evidence remains under `YAP_EVAL_CACHE`; public evidence is
aggregate and omits transcript and critical-policy hashes.
No production review registry, trust anchor, or human-reviewed second-locale
case is tracked in Git; implementing the fail-closed loader does not satisfy
that Phase 6 evidence requirement.
The locked public ASR fixture is therefore an exposure-unknown regression
comparator, not a promotion holdout. Exact-duration controls are generated and
validated outside Git under `YAP_EVAL_CACHE`; their benchmark evidence must
report null WER, zero accuracy-sample increment, and independent-promotion
ineligibility even when the worker returns transcript text internally.
The Cohere vLLM gate uses independent multipart transcription requests rather
than Yap-owned tensor batching. It measures the exact duration ladder and
c1/c2/c4/c8 waves, verifies every response against an identity-rich request and
reference transcript, and records server-observed concurrency, latency,
throughput, memory, and queue behavior. Continuous batching is an internal vLLM
optimization; Yap must never concatenate, pad, or mix audio across owners to
manufacture a batch. Cancellation is accepted only when the client connection
closes, bounded acknowledgement completes, siblings remain isolated, an
immediate request recovers, and teardown leaves no listener, container, or GPU
work attributable to the checked run. A server-side success after client
cancellation is recorded explicitly rather than misreported as preemption.

Nemotron NeMo streaming uses a separate gate because it has different state,
cache, and streaming-boundary semantics. It cannot inherit Cohere vLLM parity or
capacity evidence. The retired Triton batching probes remain historical negative
evidence and are not part of the current Phase 6 matrix.

### Windows installer safety boundary

Yap uses Tauri's stock NSIS template without installer hooks. The application and Tauri agree on the
same canonical data namespace: Tauri `app_data_dir()` for `com.mcnatg1.yap`, which is
`%APPDATA%\com.mcnatg1.yap` on Windows. Local development may build the bundle and run static
release contracts, but must not execute the production installer lifecycle on an everyday profile.

The lifecycle smoke runs only on a fresh GitHub-hosted Windows runner or in an explicitly disposable
Windows VM (`YAP_DISPOSABLE_WINDOWS=1`). It fails if production install, registry, or app-data state
already exists; verifies the installer hash when supplied; uses bounded process handles for install,
app launch, and uninstall; proves the app writes its log under the canonical Tauri directory; and
uses stock silent uninstall. It also hashes the installed notice and provenance resources against
the reviewed repository inputs. Stock silent uninstall preserves app data and the product
install-location registry record; disposal of the Windows environment clears that residual state.
The workflow makes no automated delete-data claim and performs no script-owned recursive cleanup.

The application performs the one-time storage transition before opening any runtime state. A
cross-process file lock serializes starts; a second launch times out after ten seconds and uses the
native startup-error path rather than waiting forever. Yap recursively validates only recognized runtime entries
from the former `%LOCALAPPDATA%\Yap` tree, rejects links/reparse points and dangling destinations,
copies into staging on the canonical volume, flushes and hash-verifies the full trees, publishes and
re-verifies every destination, and only then retires legacy sources. On restart, transaction-owned
staging and retirement residue is reconciled under the lock; a duplicate is removed only after a
byte-identical source or canonical copy is verified, an only copy is preserved, and cleanup failures
are surfaced. Installer files stay in place,
and redirected profiles with Local and Roaming AppData on different volumes are supported. A conflict
or failure stops startup with a native error and a uniquely created temporary diagnostic rather than
overwriting or silently abandoning either copy.

The supported release workflow stages a verified GitHub draft from an immutable commit on `main`.
The live `production-release` environment currently has branch-policy protection but no required-
reviewer rule. The workflow therefore never publishes the draft itself. Final publication is an
explicit GitHub UI action after reviewing the draft assets and `release-metadata.json`.

### Overlay and motion contract

The live overlay has two test owners:

| Owner | Covers | Must catch |
|-------|--------|------------|
| Playwright preview mode | DOM layout, visible island dimensions, hover/recording/processing/success states, reduced-motion behavior | One-frame layout jumps, hit-area shrink, overlap, text overflow |
| WebdriverIO desktop smoke | Real Tauri overlay window properties and tray/app-window behavior | Taskbar/Alt-Tab exposure, focusability, native frame size drift |

For overlay changes, settled screenshots are not enough. Add a short `requestAnimationFrame` sampler around hover/state churn and fail on unexpected rect drift. During native resize, the top hover target must remain reachable through the collapse grace period while window bounds continue to match the visible island.

---

## 2. Fixtures

Current generated fixtures:

| Path | Purpose | Expectation |
|------|---------|-------------|
| `desktop/tests/fixtures/audio-fixture.ts` | Deterministic 16 kHz mono WAV generator for UI/contract tests | Stable bytes; not treated as speech quality evidence |

The active server fixture is
`server/tests/fixtures/asr/2086-149220-0033.wav`; its source, CC BY 4.0 license,
SHA-256, and golden transcript are locked in `server/model-pools.lock.json`.

Tiny hosted-CI desktop and meeting smoke fixtures may be stored under
`desktop/tests/fixtures/` when their license and provenance permit
redistribution:

| File | Purpose | Expectation |
|------|---------|-------------|
| `en-60s.wav` | English batch + live | WER ≤ target vs `en-60s.golden.txt` |
| `multi-fr-30s.wav` | `-l fr` batch | Non-empty French; LID detects `fr` |
| `silence-5s.wav` | VAD/no-speech | No phrases finalized |
| `corrupt.m4a` | decode failure | `AUDIO_DECODE` error |
| `meeting-one-speaker.wav` + RTTM | Baseline attribution | One stable anonymous cluster; no false name |
| `meeting-two-speaker.wav` + RTTM | Turn-taking diarization | DER/JER and speaker-count gates |
| `meeting-short-turns.wav` + RTTM | Sub-1.6 s evidence | Short turns preserved; weak evidence may remain unknown |
| `meeting-overlap.wav` + RTTM | Concurrent speakers | Overlap scored explicitly; challenger promotion gate |
| `meeting-echo-two-track/` | Future mic/system leakage | No duplicate speaker inflation; track drift and gaps represented |

Only tiny redistributable public golden transcripts live beside fixtures. The
comprehensive corpus, Yap-adjudicated references, hypotheses, and raw
per-utterance results live in the private external evaluation cache and are
addressed by hashes in the committed manifest. Comparison is **WER-tolerant**,
never byte-equal (quantized models drift), but sentinel order, job identity,
language tags, and fail-closed result structure remain exact.

Real sidecar parity tests stay opt-in: set `YAP_PARITY_CLIP` and run the ignored
Cargo parity tests when a licensed audio clip is available. Normal CI uses
`desktop/src-tauri/tests/fixtures/parity-contract.verbose.json` to keep
timestamp-shape coverage without shipping private or unclear audio.

---

## 3. Accuracy scoring and spot-checks

- The GB10 gate's `yap_server.evaluation.word_error_rate.word_error_rate` and desktop Rust
  parity helper remain dependency-free, single-fixture smoke diagnostics. They
  cannot produce multilingual promotion claims.
- Phase 6 promotion uses the separately pinned `evaluation` extra and
  `yap_server.evaluation.transcript_scoring`. It reports raw and normalized word
  plus extended-grapheme edit counts, boundary-position punctuation metrics,
  and optional hash-pinned critical-token retention, order, and exact-surface
  metrics without transcript or policy text. It selects grapheme error for the
  admitted whitespace-free/CJK
  profiles, records exact Unicode/package/scorer/profile revisions, and fails
  closed on empty primary references, policy/hash mismatch, silence-policy
  misuse, mixed or partial critical-policy aggregation, or bounded-input/
  alignment limits. Long recordings are scored in immutable
  source-time segments and aggregate edit counts, not one unbounded alignment.
- Normalized critical-token occurrence and ordered-sequence metrics catch
  missing, excess, substituted, and reordered policy phrases. A separate
  case/punctuation-sensitive surface metric catches acronym, number, and unit
  form drift that normalized WER intentionally ignores. Neither establishes
  general clinical number/unit semantic equivalence; that remains a separate
  executable fixture and review gate.
- Early single-fixture gates (not broad quality certification):

| Path | WER gate |
|------|----------|
| Server Cohere batch (en) | ≤ 0.12 |
| Nemotron INT8 live (en, finals) | ≤ 0.18 |

- A regression beyond the threshold fails that backend's applicable gate. The
  private GB10 check is a phase gate, not a portable hosted-CI inference job.
  Phase 6 promotion additionally requires frozen per-locale, per-domain,
  meeting, acoustic, duration, and critical-token thresholds. A better macro
  WER cannot offset a failed required slice, hallucination-on-silence,
  cross-request leak, or long-form integrity failure.

### Diarization and identity gates

Starting targets from the source-aware design:

| Metric | Gate |
|--------|------|
| No-collar DER with overlap scored | ≤ 0.20 |
| Speaker-count mean absolute error | ≤ 0.5 |
| Named identity precision | ≥ 0.995 |
| Open-set false-name rate | ≤ 0.001 |
| Local anonymous diarization RSS increase | < 150 MB |
| Client p95 CPU increase on reference hardware | < 5 percentage points |
| Local-ASR latency regression while evidence is active | < 10% |
| Supported-load audio callback drops | 0 |

Named-identity gates remain inactive until the purpose-authorized server identity phase exists. Anonymous clustering must never manufacture a name to improve a metric.

The future approved diarization suite is rooted at
`desktop/tests/fixtures/diarization/manifest.json` and binds
license/provenance records, SHA-256 hashes, redistributable smoke audio,
transcripts, and RTTM annotations for the meeting cases above. It does not
exist yet. Comprehensive or private meeting media and references remain in the
external private cache and are addressed only by public-safe hashes. No
baseline can be accepted while any required fixture, private registry, or
license record is missing. The initial client reference profile is Windows 11
x64, CPU-only, 4 physical cores/8 threads in the Intel Core i5-1135G7
performance class, 16 GB RAM, normal process priority, and the OS balanced
power plan. Every benchmark result records exact CPU, RAM, OS build,
runtime/model revisions, and power mode.

The Phase 8 server meeting gate adds a frozen **messy-meeting acceptance
suite**. AMI, ICSI, and open NOTSOFAR-1 subsets are exposure-known public
comparators for Tiron; they cannot independently promote it. A separate sealed,
license-clear, Yap-adjudicated holdout supplies independent evidence. Before
model output is revealed, its manifest freezes sources, hashes, defects,
reviewer/adjudication receipts, transformations, scorer versions, slice
thresholds, and normalization/collar/permutation policies.

Required server metrics include cpWER, time-constrained or speaker-attributed
WER, overlap-region word deletion/recall, DER/JER where compatible,
speaker-count error, timestamp error, and speaker merge/split/fragmentation.
Required runtime metrics include cold/warm latency, RTF, VRAM/RAM,
c1/c2/c4/c8 admission and p50/p95/p99, cancellation and cross-request
isolation, restart/teardown, and duration-dependent memory plus speaker-linking
stability. The suite covers more-than-15-person sessions separately from
Tiron's one-to-eight window-local slots and includes an explicit more-than-eight
talker pressure case.

The supported-load callback test runs 48 kHz stereo capture converted to the required prepared format while local ASR, recording, and anonymous speaker evidence are active. It includes deterministic queue saturation and a four-hour accelerated timeline. Hardware-specific performance gates run on the pinned reference host; portable CI still runs deterministic contract, fixture-shape, and loss-accounting tests.

---

## 4. CI matrix (pinned native runtimes)

The risk is **native runtimes**, not app logic. CI must run the pinned Nemotron/sherpa path and `llama-server` per OS.

| OS | Nemotron live smoke | llama-server smoke | E2E |
|----|----------------|--------------------|-----|
| Windows x64 | ✅ profiler + fixture | ✅ 1 completion | ✅ |
| macOS arm64 | ✅ | ✅ | ✅ |
| macOS x64 | if retained | if retained | — |
| Linux x64 | best-effort | best-effort | — |

- Versions pinned in `desktop/src-tauri/src/stt/nemotron.rs` and `desktop/llama-model.txt` (+ llama.cpp build hash).
- Smoke = run `nemotron_profile` against one fixture, assert non-empty output + real-time factor under gate. Catches breaking changes on upgrade ([ADR 0019](../adr/0019-local-streaming-model-selection.md)).

---

## 5. Per-phase test focus

| Phase | Critical tests |
|-------|----------------|
| 1–2 Desktop/fallback | Nemotron profiler, live state transitions, local fallback disabled, queue blocks larger files without server |
| 3 Contract | OpenAPI/schema validation, loopback health bounds, connector failure/retry, durable client ledger restart |
| 4 Server node | Router fairness/backpressure, immutable runtime/model/fixture locks, isolated non-root container, ARM64/CUDA attestation, WER, atomic evidence, no persistent listener |
| 5 Remote STT | Resumable upload identity, queue drain, job state/cancel/retry, capability truth, result ingestion, tunnel-loss recovery |
| 6 Preprocessing | versioned provider/language/timing catalog; primary/per-job choice; mixed-session rejection; track-aware content IDs; exact gaps; bounded windows; advisory VAD/source preservation; verify-only AmberNet five-region strict-agreement/manual gate including exact long-tail selection; fixed/dynamic routing; durable stage restart/cancel/retry; fail-closed aligned words; model/license locks; AMD64/ARM64 frontend parity plus checked-head GB10 resource/accuracy/teardown evidence |
| 7 Identity/access | Yap API token audience, `(tid, oid)` isolation, consent and withdrawal, profile-version compatibility |
| 8 Meeting evidence | local one/two/overlap/short/noisy anonymous evidence; pinned Tiron joint speaker-attributed server baseline; messy-meeting public comparators plus independent holdout; 1–8 and over-capacity window pressure; >15-person session linking; stable result revisions; bounded clusters; no local names or persistent embeddings |
| 9 Knowledge/agents | Google OKF conformance, permission-safe projection, citation-required Analyst, three-strike Student, RAG confidence floor |
| 10 Enterprise/release | authenticated multi-owner fairness/no-starvation; bounded overload/backpressure; cancellation and timeout isolation; restart recovery; fixed worker/memory ceilings; sustained mixed live/batch p50/p95 latency, throughput, and queue-age evidence on GB10; approved network/policy evidence; deployment rollback; publication governance; repo-boundary checks |

---

## 6. Client state machine tests

- Rust transition-table tests cover runtime invariants: live vs batch exclusion, large-recording block when server is offline, fallback setup races, and finish/error transitions.
- Frontend projection tests cover setup/server labels, blocked jobs, retry rows, and history-to-job conversion.
- Future contract tests cover server health/auth, batch upload/job status, live WSS tokens, and fallback events.
- Event-order tests must use job IDs before server upload work ships.

## 7. Source-aware meeting tests

- `SessionMode`, trigger gesture, physical `CaptureSource`, local speaker slot, session speaker, and durable identity are independently serialized and validated.
- Recording remains correct when ASR, speaker evidence, or transport is absent, backpressured, or crashed.
- Long meeting recording uses bounded memory; an interrupted write is recoverable and cannot appear complete.
- Cross-session and cross-track frames fail closed instead of being relabeled.
- Lost callback intervals produce explicit gaps and a partial/degraded result.
- A saturated callback handoff reports the exact loss through the reserved accumulator.
- A callback update racing an accumulator drain appears in the next loss generation.
- `Unknown` may pass through a hidden candidate state and become `Speaker N` in a new revision; neither state may become a local name.
- Repeated weak evidence may establish an anonymous cluster but cannot update a profile.
- Speaker-turn and aligned-word intervals are end-exclusive, monotonic, bounded by the capture timeline, and preserve overlap.
- Alignment failure leaves timestamped speaker turns intact and omits or marks word timing unavailable.
- The local baseline passes the absolute DER, speaker-count, CPU, RSS, latency, and callback-drop gates before release.
- The server Tiron route consumes the same source timeline as the fallback,
  preserves concurrent segments, and cannot publish malformed speaker tokens,
  out-of-bounds timestamps, or a result whose runtime/capture identity differs
  from the admitted job.
- The eight-speaker decode-window cap is tested independently from the 32-target/
  64-ceiling session roster. Reaching or plausibly exceeding the local cap
  yields an explicit partial/degraded region and retained source for fallback.
- Public Tiron benchmark corpora remain comparator-only; promotion uses the
  separately frozen independent messy-meeting holdout and fails on any required
  overlap, locale, capacity, isolation, or lifecycle slice.
- Server reconciliation appends a revision and cannot silently overwrite a user correction.
- Contact import and transcript renaming create no biometric enrollment.
- Unenrolled, withdrawn, expired, cross-tenant, and incompatible-model profiles cannot match; enrollment, matching, and adaptation grants are checked separately, and matching-grant withdrawal denies naming without requiring profile deletion.
- Same replay key/same hash is idempotent; same key/different hash conflicts; different keys/same hash remain distinct.
- Fault injection around every recording commit step cannot produce a false-complete session.
- Withdrawal during in-flight matching prevents publication, and backup restore honors deletion tombstones.
- Replayed server results apply an authorized profile adaptation at most once; conflicting evidence fails closed.
- Transient embeddings are absent from logs, sidecars, temporary artifacts, and SQLite after normal and crashed runs.
- Four-hour and 64-speaker synthetic tests prove bounded memory and assignment state.

---

## 8. Non-goals

- No cloud test infra (local-first; fixtures are committed/small).
- No unbounded generic enterprise load laboratory in v1. Phase 10 still requires a bounded, reproducible multi-owner mixed-load test that proves the promoted service limits and SLO evidence above.
- No telemetry — debugging uses Tauri app-data logs (`%APPDATA%/com.mcnatg1.yap/logs/` on Windows).
