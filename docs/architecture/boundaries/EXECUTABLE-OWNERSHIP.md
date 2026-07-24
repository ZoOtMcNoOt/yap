# Executable Ownership and Trust Boundaries

This map records the executable ownership baseline established by architecture
checkpoint A and the executing Phase 6 branch. Paths are relative to the
repository root; later implementation must update this map only after its
behavior is executable and verified.

## Dependency direction

```text
desktop/src components
  -> desktop/src hooks and typed adapters
  -> desktop/src-tauri commands
  -> desktop native domain/lifecycle owners
  -> SQLite and atomic app-data artifacts

desktop jobs/drain
  -> desktop server_connector/batch
  -> loopback HTTP
  -> server api request adapters
  -> server jobs service
  -> job store/artifacts + bounded router/pool
```

Imports may point down this diagram. Durable owners must not import React,
Tauri command adapters, or HTTP request handlers. Adapters may project an
owner's state but may not recreate its transition logic.

## Workflow ownership

### 1. Application startup and shutdown

- **Entry point:** `desktop/src-tauri/src/main.rs` -> `lib.rs` -> `app.rs`.
- **Authoritative owner:** `app.rs`, with native resources provided by
  `runtime/desktop_lifecycle.rs` and domain resource modules.
- **Persisted state:** none owned by startup; it opens validated app-data state.
- **Transient state:** tray, windows, connector poller, job drain, live runtime,
  playback registry, fixed shortcut/import dispatchers, and shutdown
  authorization.
- **Trust boundary:** Tauri navigation and window creation; legacy app-data
  migration before normal startup.
- **Dependencies/events:** command registry, tray, migration, connector, job,
  live, and model resources; emits typed native events through those owners.
- **Failure/recovery:** unsafe migration stops startup with a private diagnostic
  path and user-safe error; owned background-task shutdown errors are logged.
- **Cancellation:** app exit cancels/joins `DesktopLifecycle` periodic/async and
  session-owned work before process termination. The two shortcut workers and
  one native-import worker are fixed process-lifetime dispatchers whose bounded
  channels close with the process; they are not spawned per event.
- **Duplicate owner:** none. Feature resources own their state; `app.rs` owns
  only composition and process lifecycle.

### 2. Tauri command registration and authorization

- **Entry point:** `commands/mod.rs` and the handler list in `lib.rs`.
- **Authoritative owner:** individual domain modules below thin command
  adapters (`commands/*`, `jobs/commands/*`, `live/actions/*`).
- **Persisted/transient state:** commands own neither; they validate caller
  context and delegate to a resource owner.
- **Trust boundary:** untrusted WebView invoke arguments and window identity.
- **Dependencies/events:** authorization, path admission, job/live/settings
  resources; results are typed views or stable errors.
- **Failure/recovery:** validation fails before mutation; owner errors are
  projected without leaking private content. Commands acquire a semaphore or
  owner lease before blocking file selection, settings confirmation, model
  operation, transcript action, or hotkey enrollment.
- **Cancellation:** delegated to the job/live/model owner; command futures are
  not treated as authority after an owner rejects them.
- **Duplicate owner:** none.

### 3. Tray and live-island window

- **Entry point:** `tray.rs`, `live/overlay_window.rs`, and
  `components/live/live-overlay-host.tsx`.
- **Authoritative owner:** native `overlay_window.rs` for window identity,
  geometry, monitor placement, visibility, and visible hit region;
  `live/state/owner.rs` for live state.
- **Persisted state:** selected hotkeys/settings only; window geometry is
  transient.
- **Transient state:** one tray-owned island window and its projected mode.
- **Trust boundary:** native OS window APIs and WebView pointer/focus behavior.
- **Dependencies/events:** native live-state events ->
  `native-surface-sync.ts` -> view modules.
- **Failure/recovery:** native surface updates fail visibly/log safely; the
  renderer cannot expand an invisible click-catching region independently. The
  OS reduced-motion preference is read for initial render before its change
  subscription is installed.
- **Cancellation:** stop/quit actions flow through `live/actions`, not component
  teardown.
- **Duplicate owner:** none. React owns presentation only.

### 4. Frontend application state and event projection

- **Entry point:** `desktop/src/main.tsx` and `App.tsx`.
- **Authoritative owner:** feature hooks for presentation state; native owners
  for recording, live, server, path, and result state.
- **Persisted state:** `localStorage` is limited to presentation preferences,
  setup acknowledgement, and compatible history projection; native catalog and
  ledger remain authoritative.
- **Transient state:** navigation, selected item, open sheets/dialogs, previews,
  drafts, and loading/error projections.
- **Trust boundary:** native event payloads and invoke results are treated as
  typed projections, not filesystem authority.
- **Dependencies/events:** hooks subscribe to `recording-jobs-changed`, native
  history, connector, live, and setup events.
- **Failure/recovery:** hooks re-read native snapshots after missed/stale events;
  warnings do not manufacture completion.
- **Cancellation:** feature hooks abort presentation work; native mutations use
  explicit owner commands.
- **Duplicate owner:** none known after app-state/history decomposition.

### 5. Imported-recording lifecycle

- **Entry point:** native picker/drop admission through
  `jobs/commands/imports.rs`, `jobs/commands/native_import_dispatcher.rs`, and
  `media_protocol/*`.
- **Authoritative owner:** `jobs/ledger/*` for job state and `jobs/drain/*` for
  remote lifecycle scheduling.
- **Persisted state:** SQLite job rows plus immutable Yap-owned preparation,
  manifest, chunk, and result artifacts under app data.
- **Transient state:** one fixed native-import worker with a one-batch backlog,
  one active picker lease, active preparation/upload/poll attempt, and scheduler
  wakeups. A batch is rejected above 200 paths before it enters the worker.
- **Trust boundary:** untrusted external file, OS drop/picker, path identity,
  WAV/container bounds, and server responses.
- **Dependencies/events:** media admission -> remote preparation -> ledger ->
  drain -> connector; emits recording-job snapshot changes.
- **Failure/recovery:** restart reconstructs work from ledger; source is never
  deleted; partial owned artifacts are validated or safely cleaned. Queue or
  picker overload returns stable `IMPORT_BUSY` instead of accumulating threads
  or native dialogs.
- **Cancellation:** durable cancellation intent drains before new upload work;
  retry clears the old remote binding while preserving the source.
- **Duplicate owner:** none. React queue is a projection.

### 6. Live-recording lifecycle

- **Entry point:** tray/shortcut/UI start and stop through `live/actions/*`.
- **Authoritative owner:** `live/state/owner.rs` for lifecycle state and
  `live/runtime/*` for runtime resources.
- **Persisted state:** committed audio/sidecar/transcript revisions through the
  recording owners; selected device/hotkey settings separately.
- **Transient state:** capture adapter, packet worker, one warm local Nemotron
  ASR stream, the optional resident AmberNet/Silero language pipeline, levels,
  bounded detector history, active session token, and finalization state.
- **Trust boundary:** microphone/CPAL callback, global shortcut input, native
  injection, model artifacts, and OS device/window APIs.
- **Dependencies/events:** actions -> lifecycle gate -> local
  start/capture/language evidence/ASR -> finalization; typed live-state, level,
  and source-time language evidence project outward.
- **Failure/recovery:** callback loss is explicit timeline evidence; worker
  failure cannot publish a fabricated complete capture. Persisted language
  evidence must end at the exact committed PCM source extent; queue timeout,
  disconnect, or mismatched evidence makes capture partial rather than claiming
  complete evidence. Startup scans durable partials for recovery.
- **Cancellation:** stop has one finisher path with bounded drain; quit uses the
  same lifecycle owner.
- **Duplicate owner:** none. Shortcut/UI callers request transitions. Shortcut
  input/action execution uses two fixed process-lifetime workers with capacities
  16 and 4; it does not create one thread per invocation.

### 7. Audio preprocessing and immutable spool

- **Entry point:** imported job preparation in `jobs/remote/preparation.rs`;
  live frames enter `audio/*`.
- **Authoritative owner:** `jobs/remote/preparation.rs` owns canonical
  normalization, advisory Silero VAD, immutable preparation artifacts, and
  durable stage attempts for imported work; shared frame/session/manifest
  contracts belong to `audio/*`.
- **Persisted state:** immutable PCM spool, chunk set, manifest/evidence, and
  hashes under job-owned app-data directories.
- **Transient state:** bounded buffers and preparation work.
- **Trust boundary:** RIFF/WAVE structure, physical file extent, source identity,
  hashes, size/duration limits, and atomic destination publication.
- **Dependencies/events:** artifact admission -> bounded normalization ->
  advisory VAD/preflight -> spool publication -> ledger transition.
- **Failure/recovery:** validation or publication failure leaves no authoritative
  prepared transition; owned remnants are reconciled on restart.
- **Cancellation:** cancels owned preparation and removes only verified Yap
  artifacts, never source media.
- **Duplicate owner:** none. The client remains source/preprocessing authority;
  server recomputation validates or produces official inference evidence without
  rewriting the client history.

### 8. Durable desktop job ledger

- **Entry point:** `jobs/commands/*` and `jobs/drain/*`.
- **Authoritative owner:** `jobs/ledger.rs` plus `jobs/ledger/*` submodules.
- **Persisted state:** SQLite schema/migrations, job status, retry/cancellation,
  remote origin/identity/progress, retention, immutable per-job language
  decision and catalog binding, stage-attempt history,
  `client_preflight_artifacts`, and owned artifact references. Schema 11 rewrites
  the former phase-derived implicit-English disposition to the functional
  `legacy_implicit_english_default` token while preserving child rows and
  foreign-key integrity.
- **Transient state:** transaction-local rows and snapshots.
- **Trust boundary:** database migrations, row decoding, monotonic status
  transitions, origin generation, and bounded retention.
- **Dependencies/events:** model records/status -> ledger mapping -> command and
  drain projections.
- **Failure/recovery:** migrations are transactional; restart rehydrates remote
  work without duplicating jobs or accepted bytes.
- **Cancellation:** cancellation is persisted before transport work.
- **Duplicate owner:** none; renderer queue state is not durable authority.

### 9. Client/server connector

- **Entry point:** settings commands and background polling in
  `server_connector/desktop.rs`.
- **Authoritative owner:** `server_connector/state.rs` for connection state and
  generations; `config/*` for validated persisted configuration; and
  `server_connector/capability_snapshot.rs` for the bounded last-known catalog
  projection.
- **Persisted state:** server configuration and approved origin, plus
  `asr-capabilities-snapshot.json`. Each is admitted through bounded no-follow
  regular-file I/O before schema validation. The capability file is an offline
  last-known projection, never current readiness or live server authority.
- **Transient state:** in-flight health request, retry schedule, generation, and
  latest capability snapshot.
- **Trust boundary:** untrusted origin/configuration and bounded HTTP response.
- **Dependencies/events:** core policy -> health/batch clients -> connector
  state -> typed frontend events.
- **Failure/recovery:** stale generation responses are discarded; typed offline
  reasons schedule bounded retry. Oversized, linked/reparse, or future-schema
  configuration fails without replacing the existing entry.
- **Publication serialization:** one settings-save lease spans normalization,
  origin confirmation, durable settings/approval publication, generation
  invalidation, and applied-state projection.
- **Cancellation:** reconfiguration cancels the old in-flight generation;
  shutdown joins polling.
- **Duplicate owner:** none; frontend hook projects snapshots.

### 10. Server create/upload/commit/status/result lifecycle

- **Entry point:** `server/api/app.py` and `api/job_requests.py`.
- **Authoritative owner:** `jobs/service.py` coordinates the transaction;
  `job_store.py`, `chunk_upload.py`, `completion.py`, and `artifacts.py` own
  durable mechanisms.
- **Persisted state:** private job JSON/state, chunk receipts/files, assembled
  WAV, immutable result, idempotency key, cancellation, and retention metadata.
- **Transient state:** admitted HTTP request, router/pool work, and processing
  cancellation set.
- **Trust boundary:** HTTP body/headers, manifest/chunk/result contracts,
  filesystem identity, worker output, and retained private content.
- **Dependencies/events:** request adapter -> service -> store/artifacts ->
  router/pool -> completion; status/result responses are bounded projections.
- **Failure/recovery:** startup converts interrupted processing into an explicit
  retryable terminal state, reconciles atomic results, and never invents
  success; create/upload/commit are idempotent. Chunk assembly reopens each
  regular file through a bounded descriptor and verifies its declared exact
  length and SHA before exclusive atomic WAV publication. Every mutating
  service entry point linearizes against runtime shutdown, the pool rejects and
  releases unstarted reservations after shutdown, and an unverified worker
  cleanup retains the exclusive storage lease until fail-stop process exit.
- **Cancellation:** idempotent cancellation wins tested commit/result races and
  purges private audio at the safe boundary.
- **Duplicate owner:** none. HTTP handlers and workers do not write job state
  independently of the service/store contract.

### 11. Server language-preflight lifecycle

- **Entry point:** `server/api/lid_requests.py` for
  `POST /v1/lid/preflight` and
  `DELETE /v1/lid/preflights/{requestId}`; `jobs/runtime.py` composes the
  optional runtime.
- **Authoritative owner:** `lid/service.py` owns active-request identity,
  cancellation, transient probe lifetime, cleanup, and shutdown;
  `lid/preflight.py` owns evaluation policy; `lid/runtime.py` owns component
  construction and startup reconciliation.
- **Persisted state:** no preflight result or probe audio is durable. The
  repository-pinned component/model/policy locks and the verified ASR
  capability catalog define the executable contract.
- **Transient state:** one bounded active-request map, cancellation events,
  materialized PCM probe files under the private server storage namespace, and
  the isolated AmberNet worker/container.
- **Trust boundary:** versioned binary envelope, exact manifest/body lengths and
  hashes, source-sample intervals, catalog/policy/model identity, private path
  identity, worker output bounds, and cleanup proof.
- **Dependencies/events:** HTTP adapter -> transport parser -> service ->
  materialization -> preflight engine -> isolated worker. The response is an
  assistive suggestion only; the client language-decision owner remains
  authoritative.
- **Failure/recovery:** stale owned probe directories are reconciled at startup;
  a cleanup failure fences the LID service. Runtime startup failure retires an
  already-created job service before worker cleanup and retains the storage
  lease whenever containment cannot be proved.
- **Cancellation:** an accepted DELETE sets the request cancellation while the
  request is active. Finalization checks that signal under the same lock that
  removes active identity, so an accepted cancellation cannot race into a
  successful POST response.
- **Duplicate owner:** none. The HTTP adapter does not own request lifetime, and
  the server suggestion does not replace the desktop decision owner.

### 12. Model and runtime selection

- **Entry point:** local setup/settings commands and server runtime creation.
- **Authoritative owner:** desktop `stt/fallback_model/*`, `stt/nemotron/*`,
  `stt/ambernet_language_detector*`, and `stt/silero_vad.rs`; server
  `pools/model_lock.py`, `model_assets.py`, provider-specific worker adapters,
  and `batch_asr*.py`.
- **Persisted state:** verified local model artifacts/settings and immutable
  server runtime/model lock.
- **Transient state:** explicit import/download operation, load guard, warm
  recognizer/detector, isolated worker process/container, and pool reservation.
- **Trust boundary:** pinned revisions/hashes, local artifact replacement,
  container identity, checked internal-network identity, worker protocol, and
  model output bounds.
- **Dependencies/events:** setup/model progress events; live runtime adapter;
  server pool and completion contract.
- **Failure/recovery:** approved downloads and import-only artifacts publish
  atomically after exact hash/size verification; load re-verifies artifacts;
  worker failures become typed job failure/retry state. A later provider startup
  failure closes every worker already created before ownership transfers.
- **Cancellation:** operation generation cancels downloads/loads; server runtime
  force-cleans the isolated worker.
- **Duplicate owner:** none. The NGC image is a build base, not a second runtime
  owner.

### 13. Process supervision and containment

- **Entry point:** app background startup and server pool/runtime invocation.
- **Authoritative owner:** desktop lifecycle resources for native tasks;
  fixed shortcut/native-import dispatchers for process-lifetime event work; and
  `server/pools/container_runtime.py` plus `batch_asr_worker.py` for the
  transient reference worker. The two provider-specific foreground launchers
  own their resident containers and bounded loopback-proxy process groups; the
  lifecycle gate owns only their sequential qualification run and temporary
  internal bridge.
- **Persisted state:** no process handle is durable; durable job/cancellation
  state drives restart behavior.
- **Transient state:** task handles, child/container identity, proxy process
  group and fixed child ceiling, timeouts, and cleanup guards. Shortcut/import
  worker counts and queue capacities are fixed; they end with the desktop
  process rather than being dynamically multiplied.
- **Trust boundary:** subprocess environment, image/revision identity, resource
  ceilings, filesystem mounts, and termination.
- **Dependencies/events:** job pool invokes runtime; lifecycle errors become
  safe status/failure projections.
- **Failure/recovery:** handles and complete proxy process groups are
  reaped/force-cleaned; restart relies on durable state rather than pretending a
  child survived.
- **Cancellation:** explicit terminate/kill fallback with bounded wait.
- **Duplicate owner:** installer-only containment was retired; real runtime
  process safety remains.

### 14. Filesystem admission and path authorization

- **Entry point:** `media_protocol/*`, `recording_access/*`, `file_actions/*`,
  `audio/recording/*`, `jobs/remote/*`, shared native `bounded_file.rs`, shared
  server `bounded_file.py`, and server `jobs/artifacts.py`.
- **Authoritative owner:** the module that mints/adopts each artifact identity;
  `recording_access/registry/*` owns renderer playback admission.
- **Persisted state:** admitted source identities where restart requires them;
  atomic private artifacts and deletion intents.
- **Transient state:** open handles/leases and pre/post-operation identity
  snapshots.
- **Trust boundary:** traversal, links/reparse points, replacement races,
  physical extent, private permissions, and allowed app-data roots.
- **Dependencies/events:** path policy and admission precede I/O; catalog/history
  expose only validated paths.
- **Failure/recovery:** mismatched identity fails closed; quarantine/recovery
  retains evidence without following attacker-controlled paths. General
  persisted-file readers cap bytes at `maximum + 1`, require regular no-follow
  opens, and compare opened/path identity where the platform exposes it;
  artifact-specific owners add exact length/hash checks.
- **Cancellation:** removes only verified owned artifacts.
- **Duplicate owner:** none; generic string paths are not authority.

### 15. Transcript publication and history

- **Entry point:** live finalization or verified remote result publication.
- **Authoritative owner:** native transcript revision/catalog modules and
  `commands/history/*`; remote result verification lives in `jobs/remote/result.rs`.
- **Persisted state:** immutable transcript/revision files, commit/result
  metadata, hash-chained language-label correction revisions, and native
  hidden/deletion state where applicable.
- **Transient state:** frontend preview, selection, search, and polish draft.
- **Trust boundary:** text/result size, revision identity/hash, catalog path,
  source replacement, and renderer file actions.
- **Dependencies/events:** publication -> native catalog -> frontend history
  reconciliation.
- **Failure/recovery:** corrupt highest revision does not silently fall back to a
  different truth; catalog maintenance warns and preserves recoverable data.
- **Cancellation:** aborts preview/polish projection; published native mutation
  uses explicit action owners.
- **Duplicate owner:** `localStorage` is compatibility/presentation only.

### 16. Configuration and environment variables

- **Entry point:** native settings commands and server `config/settings.py`.
- **Authoritative owner:** desktop `server_connector/config/*`,
  `language_preferences/*`, live settings, and STT settings for their domains;
  server `ServerSettings` for process config.
- **Persisted state:** atomic app-data configuration with a generation/origin;
  `primary-language.json` for the confirmed primary locale;
  `live-language-routing.json` for the explicit default-off Preview policy and
  its catalog revision; persisted JSON is limited to 64 KiB and server URL input
  to 2,048 bytes; server environment is process input.
- **Transient state:** renderer draft and validation errors.
- **Trust boundary:** malformed persisted data, confirmation of new origins,
  allowed loopback bind, and secret/private-value logging.
- **Dependencies/events:** validated configuration feeds connector/runtime
  creation; UI receives redacted projections.
- **Failure/recovery:** invalid, oversized, linked/reparse, or incompatible
  config fails visibly without applying a partial generation or overwriting the
  prior entry.
- **Cancellation:** a new generation retires old in-flight connector work.
- **Duplicate owner:** renderer draft is not applied state. One native save lease
  serializes the complete confirmation/publication/application sequence.

### 17. Health, capability, and readiness projection

- **Entry point:** server `/v1/health`; desktop health client/poller.
- **Authoritative owner:** server capability calculation and desktop connector
  state machine for the local projection.
- **Persisted state:** `asr-capabilities-snapshot.json` is a bounded last-known
  offline display projection only; current capability/readiness remains observed
  runtime truth.
- **Transient state:** bounded live health response and retry/readiness snapshot.
- **Trust boundary:** untrusted response schema/version/size and stale origin.
- **Dependencies/events:** server router/pool readiness -> health -> bounded
  client validation -> frontend server hook.
- **Failure/recovery:** malformed/oversized/stale health becomes typed offline or
  retrying state, never ready.
- **Cancellation:** reconfiguration/shutdown cancels polling.
- **Duplicate owner:** none; UI labels do not infer readiness.

### 18. Security, authentication, and enterprise networking handoffs

- **Entry point:** current development profile uses explicit loopback and a
  user-managed SSH forward.
- **Authoritative owner:** current application only enforces loopback/origin and
  contract controls. IT/security owns future enterprise infrastructure.
- **Persisted state:** approved development origin; no production identity or
  enterprise credential store exists.
- **Transient state:** SSH tunnel is outside Yap process ownership.
- **Trust boundary:** numeric loopback application endpoint; future TLS, DNS,
  certificate, ZPA, firewall, tenant identity, and policy boundaries are absent.
- **Dependencies/events:** connector observes availability; it does not create or
  silently fail over tunnels.
- **Failure/recovery:** tunnel loss projects retrying and resumes against the
  unchanged origin when connectivity returns.
- **Cancellation:** user/IT controls the tunnel; job cancellation remains a
  durable application action.
- **Duplicate owner:** none; developer infrastructure is not a substitute for
  enterprise ownership.

### 19. Test harnesses and release gates

- **Entry point:** `desktop/package.json`, `server` test commands,
  `.github/workflows/*`, and `desktop/tests/scripts/*`.
- **Authoritative owner:** each focused runner owns one test family; release
  contracts describe the composition and immutable evidence policy.
- **Persisted state:** tracked fixtures/contracts only; generated results, scan
  material, private media, and machine-local evidence are ignored.
- **Transient state:** OS-assigned loopback test servers, exact isolated WDIO app
  processes, browser contexts, disposable installer environments, GB10
  containers, and the checked temporary resident-provider network.
- **Trust boundary:** toolchain versions, cache keys, process cleanup, artifact
  hashes, checked-head identity, and the private evaluation registry's separately
  supplied digest. Independent ASR cases require registry-authorized human roles
  and separately pinned assignment/review/adjudication/locale/rights artifacts;
  neither the public manifest nor an individual model exposure can self-authorize
  promotion.
- **Dependencies/events:** focused suites feed the final matrix; hosted workflows
  validate the exact PR head. Production ASR, NeMo, and LID images exclude the
  `yap_server.evaluation` package; private qualification adds evaluation code or
  source material only through the explicit evaluation image/mount boundary.
- **Failure/recovery:** runners fail closed on stale/partial evidence, avoid
  inherited fixed-port assumptions, and clean up only their owned
  processes/listeners/networks. Resident-provider final evidence additionally
  requires the exact child set and clean host-boundary read-back.
- **Cancellation:** harnesses terminate owned children and reject inherited
  evidence after a code change.
- **Duplicate owner:** none after release-contract decomposition; the facade,
  CLI, policy, process, cache, Git-fixture, and contract modules have one-way
  dependencies.

## Persistent-state owners

| State | Owner | Projection/consumer |
| --- | --- | --- |
| Desktop recording jobs and remote progress | native SQLite ledger | React queue/history, job drain |
| Live capture audio/sidecar/commit | native audio recording owner | native catalog/history |
| Transcript revisions and remote results | native publication/catalog owners | React preview/history |
| Recording playback admission | native recording-access registry | media protocol/WebView player |
| Server connector configuration | native connector config owner | connector state and settings UI |
| Local model artifacts/settings | native STT model/settings owners | live runtime and setup UI |
| Server job/chunk/result lifecycle | server store/service/artifact owners | HTTP status/result projections |
| Presentation preferences/drafts | feature-specific frontend storage/state | React only |

## No-multiple-owner invariant

A second representation is acceptable only when it is a read-only projection,
an atomic compatibility import, or an adapter around the authoritative owner.
If a future change introduces two writers for any row above, it requires a new
ADR or a checkpoint finding before merge.
