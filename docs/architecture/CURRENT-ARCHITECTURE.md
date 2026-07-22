# Current Architecture

This document describes the merged executable Phase 1–5 system plus the focused
Phase 6 catalog, fixed-language decision, local primary-language conditioning,
durable-stage, normalization, and imported-file advisory-VAD slices that execute
on the active branch. The
[Voice OS architecture](../VOICE-OS-ARCHITECTURE.md) remains the first-class
long-term frame; accepted future work is sequenced by the
[roadmap](../roadmap/ROADMAP.md) and ADRs, not promoted into current-state
claims before it executes.

## System context

```mermaid
flowchart LR
  User["User"] --> UI["React desktop views"]
  UI --> Native["Tauri Rust owners"]
  Native --> Local["Local Nemotron fallback"]
  Native --> DB["SQLite and app-data artifacts"]
  Native --> Loopback["Numeric loopback HTTP"]
  Loopback -. "explicit SSH forward" .-> Server["Private Yap server"]
  Server --> Store["Private job store and artifacts"]
  Server --> Router["Bounded workload router and pool"]
  Router --> Reference["Transformers reference workers"]
  Router --> Cohere["Cohere vLLM candidate"]
  Router --> NeMo["Nemotron NeMo candidate"]
```

The SSH forward is a development access boundary managed outside Yap. It is
not an application TLS endpoint or enterprise deployment.

## Desktop

### React projection layer

`desktop/src/` renders the installed desktop experience. `App.tsx` composes
feature hooks and views; it does not own native job, recording, connector,
path, or result transitions. Feature hooks hold navigation, selected-item,
preview, draft, and loading state. Native snapshots/events are re-read after
missed or stale events instead of being promoted into a second durable owner.

The live surface is one renderer hosted in the native `live-overlay` window.
View variants, waveform, reduced-motion behavior, and presentation timing live
under `components/live/`; native code owns window identity, bounds, placement,
visible region, and lifecycle. The renderer reads the OS reduced-motion
preference synchronously for its initial state before subscribing to changes.

### Tauri/native boundary

`desktop/src-tauri/src/app.rs` composes startup/shutdown, the tray, windows, and
owned background tasks. `commands/*` and `jobs/commands/*` authorize and adapt
WebView requests; domain owners below them perform transitions. Blocking
interactive workflows acquire their owner lease before opening a native picker
or awaiting server-origin confirmation.

Major native owners are:

| Area | Authority |
| --- | --- |
| Capture/frame/timeline/recording | `audio/*` |
| Live state, actions, shortcut runtime, and local stream resources | `live/*` |
| Imported job state, scheduling, spool, retry, cancel, and result verification | `jobs/*` |
| Connector configuration, health, generations, retry, and batch contract | `server_connector/*` |
| Source/path admission and playback leases | `media_protocol/*` and `recording_access/*` |
| Transcript/catalog/file actions | `live/recordings/*`, `commands/history/*`, and `file_actions/*` |
| Local model download/integrity/Nemotron lifecycle | `stt/*` |
| Canonical and legacy app-data paths | `paths/*` |

Desktop durable truth is native SQLite plus hash-bound, atomically published
files under Tauri's canonical app-data directory. On Windows this is
`%APPDATA%\com.mcnatg1.yap`. Recognized legacy entries from
`%LOCALAPPDATA%\Yap` migrate through a serialized, non-following,
conflict-aware, hash-verified process. An unsafe conflict stops startup and
leaves source data recoverable. Persisted file consumers use bounded,
no-follow regular-file reads with opened-handle identity/extent checks; the
install namespace and connector configuration fail closed on unsafe state.

### Local live fallback

The user explicitly installs the pinned local model bundle. Native code
re-verifies artifacts at load, preflights the input device, creates bounded
capture/worker paths, records exact loss evidence, streams to one in-process
Nemotron recognizer, and atomically finalizes recoverable audio/transcript
artifacts. A failed worker cannot manufacture a complete capture.

Shortcut enrollment is a deliberate native interaction. One runtime owner
normalizes physical input, dispatches through 16-event and 4-action queues on
two fixed process-lifetime workers, and records registration/startup failures.
Window and UI callers request transitions; they do not implement a second
shortcut state machine or create per-event threads.

### Imported Phase 5 job

```text
native source admission
  -> bounded canonical-WAV validation/extraction
  -> immutable Yap spool + manifest/chunks
  -> SQLite transition
  -> create/upload/commit/status/result through bound origin
  -> native result verification and atomic publication
  -> native history catalog
  -> React projection
```

The external source is immutable from Yap's perspective and is never deleted
by cancel, retry, or retention. Cancellation is a durable outbox action. A
retry creates a new server binding while preserving the source. Configuration
generation and origin bind all in-flight work so stale responses cannot become
current truth. OS drops enter one fixed worker with a one-batch backlog and a
200-path admission bound; one lease spans each blocking native picker.

## Private server

`server/src/yap_server/api/*` owns bounded HTTP parsing and response projection.
`jobs/service.py` coordinates the job transaction through separate contract,
store, upload, completion, artifact, and runtime owners. The service supports
idempotent create, exact chunk replay, manifest-bound commit, status, immutable
result, cancellation, restart recovery, bounded retention, and safe private
artifact cleanup. Uploaded chunks are reopened as bounded regular files and
must still match their declared exact extent and SHA before exclusive atomic
WAV publication.

`workload_router/*` and `pools/*` own bounded admission and one isolated GPU
worker. The executable pool admits one running job plus two queued jobs. The
current adapter uses one fixed `development-loopback` owner and dispatches each
batch request immediately to that pool; the actual waiting bound is the pool,
not a durable authenticated multi-tenant router queue.

The checked reference worker image uses the digest-pinned NVIDIA PyTorch 26.06
base, Python 3.12, the locked NVIDIA Torch/CUDA runtime, Transformers 5.13.1,
and immutable model/runtime contracts. Each transient reference container loads
one Cohere or Nemotron model in BF16, processes bounded work, emits one result,
and exits. Its generic `/torch-compile-cache` mount is only a bounded PyTorch
compiler cache. The worker runs non-root with no network, read-only/bounded
resources, and explicit fail-closed cleanup.

`server/src/yap_server/evaluation/*` is a separate non-production evidence
boundary, not a second serving owner. Its FLEURS source lock and comparator plan
bind the exact public release, Cohere model revision, `es-419` evaluation locale,
provider route `es`, batch shape, scorer, and transcript-free aggregate. Corpus
bytes, references, hypotheses, and run receipts live only under an explicitly
private external `YAP_EVAL_CACHE`; repository and hosted-CI fallbacks do not
exist. The evaluator streams validated WAV members without extracting them,
publishes case and aggregate JSON atomically with private permissions, and uses
the same locked Python 3.12/NVIDIA Torch/CUDA/BF16 model contract as the
reference worker. Its successful 908-case GB10 run is descriptive regression
evidence and does not own runtime routing, model promotion, capacity, or product
result publication.

Independent-promotion loading additionally uses a private, out-of-band-digest-
pinned registry. It binds the complete frozen candidate/exposure set and one
case-level human-reference receipt, authorizes the required listener,
adjudicator, locale, and rights roles, and verifies separate blind-assignment,
review, adjudication, locale, rights, attribution, and preprocessing artifacts.
The source-identity receipt separately binds the corpus item and source URI,
snapshot, original recording/retrieval times, upstream URIs, and
original/reference/legal hashes. The receipt also fixes suite/condition labels,
speaker/timing metadata, and canonical audio shape. Bounded same-open reads
verify the opened handle remains inside the private cache; portable paths reject
Windows alternate streams, while duplicate JSON keys, replacement, excessive
aggregate I/O, and oversize fail closed. The receipt must match exact rights,
defects, locale, and timestamp. No real
reviewed registry or second-locale gold case exists yet, so this executing trust
boundary is not promotion evidence and leaves the representative Phase 6 gate
open.

ADR 0025 replaces the attempted universal ASR plane with provider-specific
runtimes behind Yap's existing worker-neutral contracts. Cohere batch now has a
digest-pinned NVIDIA vLLM 26.06 candidate: vLLM owns model residency and
continuous GPU scheduling while Yap retains bounded admission, durable jobs,
cancellation, validation, and publication. Nemotron keeps the pinned
Transformers/BF16 correctness route and uses a NeMo toolkit cache-aware service
as its separate server streaming promotion candidate. Local Nemotron remains
sherpa-onnx. The Cohere
vLLM adapter and a resident Nemotron NeMo adapter each now have bounded
loopback/API-key transport, exact readiness identity, provider-neutral worker
integration, checked image contracts, and launchers under focused tests. The
NeMo candidate retains one cache-aware scheduler owner and bounded independent
job cancellation. Its transport uses a bounded reusable HTTP worker pool, while
the distinct model admission boundary remains eight active requests so control-
plane cancellation can still be serviced. It is not client-facing live
transport. Focused GB10 service
probes preserved Cohere's Transformers reference hash across c2/c4/c8 and
exercised vLLM's disconnect-to-engine-abort boundary, while NeMo formed one
batch of eight isolated fixed/auto requests; both recovered and tore down. A
later source-backed metrics control confirmed that the pinned external abort is
not added to vLLM's finished-request histogram. Checked-head representative
parity/locale/duration, percentile, admission, and memory-slope gates remain open
for selection. Neither candidate has been promoted. The earlier Triton
Python-backend experiment remains historical negative evidence because parity-
preserving execution serialized model calls without a demonstrated throughput
gain. SGLang remains a later agent/LLM choice, and persistent supervised
production deployment remains Phase 10 work.

Source-exact focused GB10 smokes at executable commit
`fcccf21e785b116b92cd8e46150a36b9b5ee91db` additionally ran each full locked
model through its real Yap adapter and left no owned container or listener. They
close basic image/model/adapter integration only; the frozen comparisons and
promotion gates above remain open.

Provider admission has two explicit owners. Cohere's resident vLLM process
uses `--max-num-seqs 8` for active scheduling and may queue internally; it is
not treated as a reliable HTTP 429 source. Yap's batch pool therefore owns the
executable 8-running + 8-queued and aggregate-PCM rejection boundary. NeMo's
authenticated adapter independently owns eight active requests and a typed
ninth-request 429. The private qualification layer now has distinct standard,
cancellation, capacity, and fixed/automatic-language runners so completion
counts cannot stand in for the named semantics. The frozen GB10 evidence is
still open.

Exact-track load evidence separates recognized-word stability from rendered
formatting. Repeated immutable input is grouped by audio duration and must retain
one non-empty lexical identity; exact casing/punctuation identities are reported
separately and punctuation remains part of representative reference scoring.
This boundary reflects observed sustained Cohere/vLLM behavior and does not
weaken the still-open quality gate.

Provider resource ownership is also explicit. The cgroup supplies current,
peak, task, and memory-event truth; the container entrypoint supplies RSS,
anonymous/file/shared composition, thread count, and virtual allocation extent;
NeMo responses additionally supply CUDA allocated/reserved and peak counters.
Runtime-plan schema 5 binds each candidate to a c8/1,600 GB10 profile with
current/peak and task/thread ceilings, zero memory-event increments, and a
64-MiB tail bound on virtual allocation-extent growth. Physical RSS regression
and range remain visible because unified-memory residency can oscillate, but
they are not substituted for allocation growth. Focused results selected these
thresholds, and both current-source profiles pass their eleven focused checks
plus clean teardown. Only the frozen checked-head run can satisfy the Phase 6
gate.

The server's dynamic health response advertises batch/status only when the
Phase 5 runtime actually initializes. Live streaming remains false and
`/v1/live` remains unimplemented.

## Active Phase 6 slices

The current branch adds a separately bounded ASR capability-catalog endpoint,
native fingerprint/bounds validation, and an origin-bound last-known snapshot
that explains offline state without authorizing a route. Rust owns the
versioned primary-language preference and freezes each imported job's
primary/manual disposition through SQLite, preprocessing evidence, and the
server create contract. Local warmup serially reads that confirmed locale,
validates the exact 32-locale out-of-box Nemotron allowlist, and applies it to
every native stream and reset. Unsupported locales fail visibly; a preference
change invalidates idle warm state and cannot race an active capture. A picker/
drop batch retains bounded native-selection
proof before its non-runnable `accepted` rows can commit. Active playback is
projected before an unlocked row becomes `preflighting`; restart snapshot
recovery may consume the retained proof but never recreate it from a ledger path,
while a concurrent cancellation cannot restore authority. An already-locked
Phase 5 row retains the compatibility transition to `queued_server`. Background
preflight rechecks the selection registry, creates one immutable Yap-owned
normalization/VAD capture, and freezes a short configured decision or a confirmed
long-recording suggestion before promoting those exact bytes to remote upload.
Catalog validation, upload, result polling, retry, and failure paths retain one
exact job ID instead of rescanning a neighbor. React projects those native/server
owners.

Schema 9 adds desktop-authoritative bounded attempts for normalization, VAD,
LID preflight, and user confirmation; schema 10 binds the immutable client
preflight artifact and any in-flight LID request identity to the same job.
Imported canonical PCM WAV preprocessing
records identity normalization, then optionally runs the explicitly installed,
hash-verified Silero artifact through the existing `sherpa-onnx` CPU runtime.
It emits ordered source-sample/source-millisecond advisory intervals or a typed
bounded error and always retains the complete source. Server schema 5 records
ASR, alignment, and result-publication attempts with restart/retry admission and
bounded evidence; legacy rows remain readable without invented stage history.

Native selection is intentionally scoped to the canonical path, matching the
existing replace-in-place behavior. Each access reopens no-follow and takes a
fresh fingerprint; byte identity becomes immutable when preprocessing publishes
the verified Yap-owned spool. The path registry does not claim that an external
file can never change after selection.

The catalog still promotes only the locked Cohere `en-US` fixed-batch route.
The optional, explicitly imported AmberNet 1.12.0 QDQ INT8 plus Silero local
language path now loads once beside the single Nemotron ASR under `LiveRuntime`.
The exact native frontend, one-thread static-ORT session, immutable 107-label
map, three-observation/`0.40`-margin policy, and user-selected regional locale
catalog are bound into the component revision. The runtime partitions bounded
held audio exactly once at accepted switches, returns visibly to the primary
locale on ambiguity or failure, and stores revisioned source-time
span/decision evidence inside the hash-bound recording sidecar. Overlapping
detector windows and ASR commits use independent bounded cursors over the same
shared source frames, so detector history cannot cause ASR replay and ASR
commits cannot discard future detector input. The artifact is local-import only:
it is neither bundled nor network-downloaded while NGC redistribution review is
open. Focused runtime, exact-frontend, label-map, lifecycle, and private
holdout checks execute. A controlled release-mode i7-13850HX proxy restricted
the process to eight logical CPUs and routed 38.4 seconds exactly once through
resident Nemotron plus AmberNet/Silero. Four configured Nemotron threads were
oversubscribed: two threads improved the combined path to `0.431` RTF while
using 61.844 CPU-seconds, or about 1.61 logical-core equivalents when spread
over continuous real-time source arrival. A one-thread diagnostic remained
below real time at `0.484` RTF with lower CPU use but materially slower model
load. The executable default is therefore two threads pending the actual target
gate. A follow-on source-paced proxy delivered all 3,840 ten-millisecond frames
without loss through the production-sized 64-frame local-ASR queue, reached a
42-frame high-water mark, completed 864 ms after the 38.4-second source ended,
and averaged 1.765 logical cores (22.066% of the eight-CPU affinity budget).
Concurrent ten-millisecond scheduler probes observed 0.752 ms p95 and 6.966 ms
maximum wake delay. The language path added about 58.64 MB of private memory and
left about 7.92 MB after teardown. A harsher four-logical-CPU repeat still lost
no frames, reached 45/64 queued frames, drained in 911 ms, averaged 1.773 logical
cores during paced input, and measured 8.023 ms p95/45.864 ms maximum scheduler
wake delay. Its unpaced combined pass consumed 3.71 of four logical cores, which
is saturation evidence rather than an interactive workload claim. These are
accelerated and paced runtime proxies, not rendered-UI, battery, thermal, or
i5-1135G7 evidence. The route is therefore available only as an explicit,
default-off Preview; target-i5 resource and interference, sustained-session,
restart, cancellation, and the complete checked-head gate still gate Phase 6
release. A deterministic duration runner now streams the machine plan's exact
short and 30-second-to-two-hour ladders from the prepared-audio-frame boundary
through the production bounded adapter, the same single live worker, and
finalization. It locks the checked head, plan, private suite, manifests, raw WAV,
and decoded PCM without retaining transcript text or paths. The multi-hour run
has not been consumed and does not replace physical-microphone, rendered-UI,
target-i5, or natural-accuracy evidence. A separately frozen clean German-English
representative set then retained
exact source coverage and the required primary-language fallback but detected
zero of four required natural alternate-language spans and matched neither the
entry nor exit boundaries. A post-failure diagnostic of the exact implemented INT8
detector found 68 speech-qualified windows inside those alternate regions but
only five alternate top labels and one observation above the `0.40` margin;
none appeared outside the alternate regions. The earlier FP32 diagnostic also
misclassified three of the four spans, while whole-clip FP32 and INT8 scores
were 322/340 and 323/340 respectively. The failed route is therefore recorded
as a short-window/domain limitation rather than an INT8 regression; it is not
retuned, and it blocks removing the Preview label or making a natural-switch
quality claim. The isolated SpeechBrain CPU preflight now executes behind the
server capability catalog: at most two speech-rich windows are copied into a
transient non-root, offline Python 3.12 worker, and its uncalibrated suggestion
remains inert until the user confirms it. Request origin/identity, cleanup,
restart cancellation, and evidence are durable and bounded. At exact executable
source SHA `04266c4bbffd0fd31eaf2afd0bcce42e0248344f`, the platform-manifest-pinned
image exercised the real `ContainerLidWorker` on both bounded probes and removed
its owned container/listener; the private receipt stays outside Git. Peak RSS,
sustained CPU, target-i5 behavior, and the complete resource gate remain open. A
server Nemotron
worker, explicit automatic-job language tags, fail-closed Cohere attention
alignment, the Cohere vLLM adapter, and the resident NeMo worker/service/image/
launcher now execute as locked focused slices. Separate focused GB10 service
proofs exercised independent Cohere c2/c4/c8 requests with vLLM engine abort and
one NeMo batch of eight; both cancelled without publication, recovered, and
removed their owned container/listener. A privacy-safe aggregate duration
control subsequently ran each candidate at 30-second c2 and c1 2-minute,
15-minute, two-hour, and exact four-hour inputs. Both published bounded results
and tore down; the four-hour controls used 4.272 GiB for vLLM and 2.356 GiB for
NeMo. Yap submitted each vLLM file as one offline API request; vLLM internally
scheduled long audio as multiple bounded engine chunks. NeMo advanced the
cache-aware streaming model in 1.12-second frames across finalized windows, but
this service returns only a final result, not partial text. The resulting
wall-time gap currently favors vLLM for offline long-form throughput and is not
client-facing streaming evidence. Engine-chunk histograms and API-request wall
latency remain explicitly different units. Repeated-fixture controls do not
prove sentinel integrity, natural long-form quality, frozen percentiles, or
promotion.
These paths remain unadvertised/unselected:
the catalog still exposes only Cohere `en-US` with `wordAlignment: false`, and
the frozen vLLM comparison, frozen representative Nemotron NeMo gate, and
complete Phase 6 gate have not run. Both candidate launchers publish only
numeric loopback and require separate private API keys; this does not implement
the still-false live capability. Phase 6 does not claim authenticated ownership
or a persistent supervised mixed-load production service. Phase 7 owns
authenticated tenant/user identity. Phase 10 owns production supervision,
capacity promotion, observability, and enterprise deployment.

Local and server language evidence now share the narrow version-1 16 kHz
`LanguageSpan` wire contract without sharing a state owner. Local acoustic
decisions carry `clientDecision`; server automatic results carry
`serverUtterance`, complete canonical-source coverage, immutable model and
utterance-plan identities, and lossless text links through `sourceSpanIndex`.
Mixed or incomplete server text evidence makes the finalized utterance `und`.
The worker, durable server result, OpenAPI, and native admission validators all
reject missing, discontinuous, unbound, or provenance-mismatched evidence. This
does not promote server terminal tags to within-utterance diarization.

Dynamic server labels are correctable without weakening result authority.
History resolves the current native remote identity, revalidates the immutable
result, and lazily projects its bounded segments. A correction is a separate
append-only, strict-schema revision under the owned job root, hash-bound to the
exact `result.json`, its preceding correction, session, segment, source span,
and original label. One native mutex serializes writes and an expected revision
rejects stale UI actions. The server result, transcript, and retained audio are
never rewritten; restoring the server label appends another correction. History
shows effective correction and remaining-review counts only after the complete
chain verifies, and React renders the list in bounded pages rather than creating
one DOM row per possible segment.

## Persistence and recovery

| Durable boundary | Recovery invariant |
| --- | --- |
| Desktop SQLite job ledger | Transactional migration and replay preserve one job identity and accepted remote progress. Schema 8 adds a singleton metadata write probe; schema 9 adds bounded client-stage attempts without fabricating history for legacy rows; schema 10 binds the immutable preflight artifact and persisted LID dispatch identity. After a mutation failure, an in-memory circuit blocks preprocessing and remote dispatch until the probe commits. |
| Recording commit/sidecar/transcript | Only hash-valid, atomically published lineage becomes complete History truth. |
| Remote result review | Native History derives fixed/dynamic/unknown-language and available/unavailable/legacy-timing summaries only from a verified immutable result, then projects them into the one existing transcript review surface. |
| Prepared spool/chunks | Only verified Yap-owned paths are cleaned; external sources are preserved. |
| Install identity | Bounded no-follow regular-file admission rejects linked, oversized, or invalid namespace state. |
| Connector configuration | Bounded no-follow regular-file admission precedes schema validation; one save lease spans confirmation, publication, approval, generation change, and applied-state projection. |
| Server job/chunk/result state | Schema 5 retains bounded ASR/alignment/result-publication attempts. Idempotency survives restart; interrupted processing and retry admission remain explicit without rewriting completed result authority. |
| Deletion intent/quarantine | Destructive work revalidates identity and resumes without following replacement paths. |

## Trust boundaries and limits

- WebView commands require the intended window/command authorization and typed
  validation.
- Imported files, native paths, server requests/responses, worker output, and
  persisted JSON/SQLite rows are untrusted at their admission boundary.
- Reads, files, chunks, responses, queues, retries, request workers, retention,
  model output, and process resources are bounded.
- Links, Windows reparse points, path replacement, physical file extent, and
  time-of-check/time-of-use races are handled by admission plus identity
  revalidation/leases where mutation requires it.
- Logs and public errors describe stable codes/state without private audio or
  transcript content.
- The application boundary is numeric loopback during development. External
  networking, authentication, certificates, DNS, firewall policy, ZPA, and
  enterprise deployment are not implied.

See the complete [ownership map](boundaries/EXECUTABLE-OWNERSHIP.md) and public
[security posture](../security/SECURITY-POSTURE.md).

## Build and verification boundaries

The frontend uses Node 24 and pnpm 11.7.0. Native code uses Rust 1.96. The
portable server supports Python 3.12 only. Windows automation requires
PowerShell Core 7.4 or newer. Installer lifecycle tests run only in a
disposable Windows environment.

Focused suites protect each extraction. Browser automation allocates an
OS-selected loopback port, and native restart automation terminates only its
exact isolated app process before bounded session cleanup. The full
local/native/server/GB10 matrix runs once only after an exact phase/checkpoint
implementation head is ready. Hosted CI and disposable installer automation
then verify the final PR head before merge.
