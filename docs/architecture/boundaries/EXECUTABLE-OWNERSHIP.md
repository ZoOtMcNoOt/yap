# Executable Ownership and Trust Boundaries

This map records the executable ownership baseline through merged Phase 9.
Phase 8's meeting route and maintainability repair merged through PRs #142 and
#143. Phase 9's reviewed knowledge and agent baseline passed its exact-head
private and aggregate gates, then merged through PR #152 as
`ae81ff067c73a64528eecc14403765562726f2fe`. The current post-phase
maintainability checkpoint maps the executable owners that merge introduced;
it does not promote the evaluation runtimes into supervised production
services. Paths are relative to the repository root. Later implementation must
update this map only after its behavior is executable and verified.

## Dependency direction

```text
desktop/src components
  -> desktop/src hooks and typed adapters
  -> desktop/src-tauri commands
  -> desktop native domain/lifecycle owners
  -> SQLite and atomic app-data artifacts

desktop jobs/drain
  -> desktop server_connector/batch
  -> desktop server_connector/authorization
  -> loopback HTTP
  -> server auth request adapter
  -> server api request adapters
  -> server jobs service
  -> job store/artifacts + bounded router/pool

desktop settings/identity commands
  -> desktop native token manager/provider interface
  -> [no approved production provider adapter]

desktop live authorization
  -> bounded native WebSocket actor + session lease
  -> separate private loopback WebSocket endpoint
  -> server token/principal admission
  -> bounded live protocol registry [no ASR consumer]
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
- **Persisted state:** one current Yap-owned SQLite baseline, job status, retry/cancellation,
  remote origin/identity/progress, retention, immutable per-job language
  decision and catalog binding, stage-attempt history,
  `client_preflight_artifacts`, owned artifact references, the singleton write
  probe, and version-2 development or hashed native-provider account authority.
  SQLite application ID `YAPJ` plus schema version 1 identify the database.
  Installation claims only an empty unowned database; historical schemas and
  obsolete language dispositions fail closed without migration or rewriting.
- **Transient state:** transaction-local rows and snapshots.
- **Trust boundary:** database ownership/schema identity, row decoding, monotonic status
  transitions, origin generation, and bounded retention.
- **Dependencies/events:** model records/status -> ledger mapping -> command and
  drain projections.
- **Failure/recovery:** current-schema installation is transactional; restart
  rehydrates remote work without duplicating jobs or accepted bytes.
- **Cancellation:** cancellation is persisted before transport work.
- **Duplicate owner:** none; renderer queue state is not durable authority.

### 9. Client/server connector

- **Entry point:** settings commands and background polling in
  `server_connector/desktop.rs`.
- **Authoritative owner:** `server_connector/state.rs` for connection state and
  generations; `config/*` for validated persisted configuration; and
  `server_connector/capability_snapshot.rs` for the bounded last-known catalog
  projection. `native_access_token_provider.rs` owns the in-process provider
  interface, native sign-in state, and zeroizing token projection;
  `authorization.rs` owns bearer injection, session invalidation, and durable
  account pinning.
- **Persisted state:** server configuration and approved origin, plus
  `asr-capabilities-snapshot.json`. Each is admitted through bounded no-follow
  regular-file I/O before schema validation. The capability file is an offline
  last-known projection, never current readiness or live server authority.
- **Transient state:** in-flight health request, retry schedule, generation,
  latest capability snapshot, one frontend-owned fixed-loopback discovery
  timer/probe, zeroizing access token, and hashed selected-account binding.
- **Trust boundary:** untrusted origin/configuration, bounded HTTP response, and
  the narrow native provider return contract. No production provider
  implementation is selected. Raw tokens and raw provider account IDs never
  enter React or ordinary app-data persistence.
- **Dependencies/events:** core policy -> health/batch clients -> connector
  state -> typed frontend events. While no origin is configured, the frontend
  may ask the native command to probe only `http://127.0.0.1:18765`; a verified
  Yap health response becomes an offer, never an automatic connection. Saving
  still crosses the ordinary origin-confirmation interface.
- **Failure/recovery:** stale generation responses are discarded; typed offline
  reasons schedule bounded retry. Oversized, linked/reparse, or future-schema
  configuration fails without replacing the existing entry. Missing/expired
  identity, sign-out, reconfiguration, and account switching fail before
  authenticated remote dispatch; optional server refresh/probe failures cannot
  fail on-device setup, and local/offline behavior remains available.
- **Publication serialization:** one settings-save lease spans normalization,
  origin confirmation, durable settings/approval publication, generation
  invalidation, and applied-state projection.
- **Cancellation:** reconfiguration cancels the old in-flight generation;
  shutdown joins polling.
- **Duplicate owner:** none; frontend hook projects snapshots.

### 9a. Private authenticated live admission

- **Entry point:** desktop
  `server_connector/authorization/live_websocket.rs`; server
  `server/live/websocket_server.py` and `server/live/protocol.py`.
- **Authoritative owner:** the Rust WebSocket actor owns one authorized client
  connection and its bounded command/event queues; the Python live server owns
  loopback listener lifecycle, authenticated admission, connection limits,
  replay state, and protocol sequencing.
- **Persisted state:** none. The service uses the existing durable identity
  repository for principal-access and revocation decisions.
- **Transient state:** zeroizing bearer access, one `SessionLease`, bounded
  message/queue state, up to eight admitted server connections, and the live
  protocol registry.
- **Trust boundary:** explicit approved origin, exact `yap.live.v1`
  subprotocol, sensitive bearer injection, handshake status, message/frame
  sizes, sequence/replay windows, token expiry, and access revocation.
- **Dependencies/events:** the current server starts the authenticated live
  listener at `127.0.0.1:18766` by default, separate from HTTP port `18765`.
  Focused parity evidence qualifies the native lower handshake against the
  two-port topology. The fixed-loopback offer discovers only the HTTP health
  origin; managed/live endpoint discovery and wiring to the separate live port
  do not exist.
- **Failure/recovery:** bad origin, missing/invalid authorization, wrong
  subprotocol, overflow, replay, expiry, revocation, or account-generation
  change fails closed and closes or rejects the connection without leaking
  bearer/header content.
- **Cancellation:** sign-out or configuration/account change invalidates the
  shared session lease and cancels handshake plus actor I/O.
- **Duplicate owner:** none. This is admission/transport only; no live ASR,
  transcript publication, external same-origin WSS/TLS edge, or HTTP/3 carrier
  exists.

### 10. Server create/upload/commit/status/result lifecycle

- **Entry point:** `server/api/app.py` and `api/job_requests.py`.
- **Authoritative owner:** `jobs/service.py` coordinates the transaction;
  `job_store.py`, `chunk_upload.py`, `completion.py`, and `artifacts.py` own
  durable mechanisms. `jobs/result_bundle.py` owns generic result aggregate
  publication policy; functional adapters decode provider-specific companions.
  Adapter registration is independent from the worker profile that admits new
  work, so a restart can reopen already-durable results after profile changes.
  The request-authentication adapter supplies the immutable principal; handlers
  never accept a client-supplied owner as authority.
- **Persisted state:** current-schema principal-scoped private job JSON/state, chunk
  receipts/files, assembled WAV, immutable result, idempotency key,
  cancellation, and retention metadata.
- **Transient state:** admitted HTTP request, router/pool work, and processing
  cancellation set.
- **Trust boundary:** bearer authentication, HTTP body/headers,
  manifest/chunk/result contracts, filesystem identity, worker output, and
  retained private content. Absent and cross-owner resources share the same
  non-disclosing projection.
- **Dependencies/events:** request adapter -> service -> store/artifacts ->
  router/pool -> completion; status/result responses are bounded projections.
- **Failure/recovery:** startup converts interrupted processing into an explicit
  retryable terminal state, reconciles atomic results, and never invents
  success; create/upload/commit are idempotent. Result-companion policy is
  validated before publication and the same registered adapter reopens it after
  restart. Chunk assembly reopens each
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
  identity, worker output bounds, and cleanup proof. Each real container launch
  writes Docker's immutable 64-character ID to a private per-request
  `--cidfile`; cleanup verifies that ID's owner, storage, runtime-instance, job,
  and checked-revision labels before removing only that ID.
- **Dependencies/events:** HTTP adapter -> transport parser -> service ->
  materialization -> preflight engine -> isolated worker. The response is an
  assistive suggestion only; the client language-decision owner remains
  authoritative.
- **Failure/recovery:** a cleanup failure fences the LID service and retains the
  request root plus immutable container identity. On restart, owned containers
  are reconciled first; only then may startup validate and retire that bounded
  identity file with the stale owned probe directory. Runtime startup failure
  retires an already-created job service before worker cleanup and retains the
  storage lease whenever containment cannot be proved.
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
  `pools/model_lock.py`, `model_assets.py`, neutral `pools/pcm_audio.py`,
  provider-specific engines/adapters, `batch_asr_worker.py` for the executable
  worker protocol, and `batch_pool.py` for admission and lifecycle. The Tiron
  harness owns its third-party whole-meeting decode; Yap's meeting adapter owns
  source/result validation, while generic durable-result decoding remains
  independent from whether the Tiron worker profile is currently enabled.
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
  worker failures become typed job failure/retry state. Batch and LID workers
  have mandatory close boundaries; a later provider startup failure closes
  every worker already created before ownership transfers.
- **Cancellation:** operation generation cancels downloads/loads; server runtime
  force-cleans the isolated worker.
- **Duplicate owner:** none. The NGC image is a build base, not a second runtime
  owner. Provider engines do not import the executable worker entry point, and
  the loopback runtime does not wrap `BatchAsrPool` in a second immediate
  enqueue/dequeue scheduler.

### 13. Process supervision and containment

- **Entry point:** app background startup and server pool/runtime invocation.
- **Authoritative owner:** desktop lifecycle resources for native tasks;
  fixed shortcut/native-import dispatchers for process-lifetime event work; and
  `server/pools/container_runtime.py` plus `batch_asr_worker.py` for the
  transient reference worker. The two provider-specific foreground launchers
  own normal resident-container teardown. The integrated identity/access gate's
  `owned-process-supervisor.py` owns initial launcher, sampler, and proxy child
  identity, release, signalling, and exact reap; the lifecycle gate owns their
  sequential qualification run, temporary internal bridge, and abnormal-exit
  recovery.
- **Persisted state:** each active supervised target publishes private
  versioned PID/start-time/supervisor state and an authoritative cleanup result.
  Each active proxy also publishes its immutable token-owned process-group
  identity until verified teardown. Before Docker create, the launcher publishes
  a private container recovery record; Docker writes its exclusive container-ID
  file. Neither survives successful cleanup, while an unresolved create retains
  the record and fails the gate. Durable job/cancellation state drives
  application restart behavior.
- **Transient state:** retained pidfd, release/control/exec-status descriptors,
  task handles, child/container identity, proxy process group and fixed child
  ceiling, deadlines, and cleanup guards. Shortcut/import
  worker counts and queue capacities are fixed; they end with the desktop
  process rather than being dynamically multiplied.
- **Trust boundary:** subprocess environment, image/revision identity, resource
  ceilings, filesystem mounts, and termination.
- **Dependencies/events:** job pool invokes runtime; lifecycle errors become
  safe status/failure projections.
- **Failure/recovery:** isolated/no-site system Python starts behind a release
  barrier and keeps the exact child pidfd from fork through
  `waitid(P_PIDFD)`, including the interval before exec-time token visibility.
  Control writes contain `SIGPIPE`; setup and pidfd-acquisition failures are
  bounded. After a missing or failed supervisor result, recovery first proves
  and reaps the direct supervisor, then validates the per-run token on every
  live process-group member before bounded TERM/KILL cleanup. Cleanup proof
  remains latched after reap; an `EACCES` environment race is treated as exit
  only after the same identity is causally gone or zombie. Proxy teardown
  bounds every Docker probe/operation below the supervisor TERM deadline and
  separates Docker create from start. It resolves fixed name, immutable
  container ID, and token before stopping and force-removing that exact external
  container. If an interrupted create cannot be resolved, timed absence is not
  proof: cleanup fails and its private recovery identity remains. Recovery
  retires only after direct immutable-ID absence; renamed, relabeled, or foreign
  state is retained and refused. A failed recovery-artifact deletion remains an
  unclean launcher result, and the outer lifecycle gate independently requires
  the recovery record, partial publication, and container-ID file absent before
  clearing their path. Provider containers omit Docker auto-removal so bounded
  log capture precedes explicit immutable-ID removal. It has no stale numeric-PID
  log follower. Restart relies on durable job state rather than pretending a
  child survived.
- **Cancellation:** explicit control-channel stop, retained-pidfd pending-child
  kill, verified process-group TERM/KILL, and bounded exact reap.
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
  `commands/history/*`; remote result verification lives in
  `jobs/remote/result.rs`. The catalog validates bounded directory/result/text
  identity plus speaker-file metadata. Selection of an exact result triggers
  the bounded full speaker hash, parse, canonical-content, and source-binding
  verification.
- **Persisted state:** immutable transcript/revision files, commit/result
  metadata, hash-chained language-label correction revisions, and native
  hidden/deletion state where applicable.
- **Transient state:** frontend preview, selection, search, and manual correction
  comparison;
  one serialized latest-wins native speaker-detail read and a bounded page of
  canonical turn IDs.
- **Trust boundary:** text/result size, revision identity/hash, catalog path,
  source replacement, and renderer file actions.
- **Dependencies/events:** publication -> native catalog -> frontend history
  reconciliation.
- **Failure/recovery:** corrupt highest revision does not silently fall back to a
  different truth; catalog maintenance warns and preserves recoverable data. A
  crash after immutable result publication leaves durable `Saving` state;
  restart validates and finalizes the complete locally published bundle before
  acquiring any server lease, while cancellation removes the unattached owned
  spool and prevents a later terminal commit.
- **Cancellation:** aborts preview/correction projection. Result publication and
  cancellation share the native mutation gate, so cancellation either wins
  before publication or observes the completed terminal record afterward.
- **Duplicate owner:** `localStorage` owns browser-created presentation entries
  only; native catalog identity and result authority never originate there.

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

### 18. Authentication, authorization, and enterprise networking handoffs

- **Entry point:** desktop identity commands and request authorization;
  `server/auth/*` token, repository, and purpose authorization; the current
  development profile still uses explicit loopback and a user-managed SSH
  forward.
- **Authoritative owner:** the Rust native provider interface owns the token
  acquisition contract but has no production implementation; Rust owns token
  projection, account binding, session invalidation, and request injection. The
  common server OIDC layer owns JWT/discovery verification, the Entra policy
  owns tenant/audience/scope/client/role requirements, and the identity and
  purpose-authorization services own principal access, grant enforcement, and
  redacted audit records. IT/security owns provider approval, tenant policy, and
  enterprise infrastructure.
- **Persisted state:** approved origin, versioned hashed remote account plus
  normalized tenant/client/API-scope configuration binding, and the SQLite
  development identity repository. No token, raw provider account ID, tenant
  ID, client ID, or API scope is stored in the renderer or job ledger.
- **Transient state:** zeroizing access tokens and SSH tunnel state; the tunnel
  remains outside Yap process ownership.
- **Trust boundary:** provider-neutral fixed-algorithm OIDC validation, bounded
  discovery/JWKS retrieval/cache, Entra tenant/audience/scope/client/role policy,
  owner- and purpose-scoped authorization, numeric loopback, and the narrow
  native provider contract. Default authentication fails closed; the fixed
  development principal requires explicit development-only configuration. Real
  provider registration/adapter approval, Conditional Access, MFA, consent,
  external WSS/TLS, DNS, certificates, ZPA, firewall, production database/audit,
  and deployment policy remain external.
- **Dependencies/events:** validated identity -> immutable request principal ->
  repository authorization -> owner-scoped job/LID/live admission. The
  `Yap.IdentityAdministrator` role gates same-tenant grant/revoke and access
  mutations; active grant combinations gate and audit enrollment, matching, and
  adaptation seams. The connector observes availability; it does not create or
  silently fail over tunnels.
- **Failure/recovery:** invalid/expired/revoked access fails closed; account
  switching cannot reuse another account's durable work; absent and cross-owner
  lookup are non-disclosing. Tunnel loss projects retrying and resumes against
  the unchanged origin when connectivity returns.
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
  validate the exact PR head. Request-time ASR, NeMo, LID, and Tiron images
  exclude the `yap_server.evaluation` package before application source enters
  the final image; private qualification adds evaluation code or source material
  only through the explicit evaluation image/mount boundary.
- **Identity-provider evidence:** a version-and-digest-pinned mock OIDC provider
  and owner-flow harness exercise real discovery, JWKS, signed-token, ownership,
  and revocation behavior. The applicable hosted execution evidence is recorded
  with the merged phase that consumed it.
- **Checked-runtime boundary:** pre-admission preparation owns digest-pinned
  Dockerfile execution and emits a private receipt only after a second
  clean-head check. The frozen private plan owns each receipt hash. Admitted
  gates are inspection-only: they require the receipt-bound ARM64 image ID,
  pass that ID to the launcher, and bind the ID plus receipt hash into final
  evidence. Provider launchers and the shared loopback helper use a per-run
  token and immutable container/network IDs so cleanup cannot claim a later
  fixed-name replacement.
- **Failure/recovery:** runners fail closed on stale/partial evidence, avoid
  inherited fixed-port assumptions, and clean up only their owned
  processes/listeners/networks. Resident-provider final evidence additionally
  requires the exact child set and clean host-boundary read-back.
- **Cancellation:** harnesses terminate owned children and reject inherited
  evidence after a code change.
- **Duplicate owner:** none after release-contract decomposition; the facade,
  CLI, policy, process, cache, Git-fixture, and contract modules have one-way
  dependencies.

### 20. Reviewed knowledge-source admission and OKF compilation

- **Entry point:** `knowledge/reviewed_capture_ledger.py` for reviewed meeting
  results, `knowledge/knowledge_source_admission.py` for admitted Lane 1/Lane 2
  sources, and `knowledge/okf_compiler.py` for deterministic compilation.
- **Authoritative owner:** the recording job/result ledger owns the exact
  immutable meeting result; the reviewed-capture ledger owns its reviewed
  normalized source; the source-admission ledger owns the exact source-to-build
  authority. The compiler owns only the deterministic projection.
- **Persisted state:** reviewed capture identities and source-admission records
  bind tenant, owner or reviewer, source kind/path, source revision, content or
  derived manifest hash, review-authority hash, and the compiled generation
  hash.
- **Trust boundary:** a caller cannot supply a raw job owner/result descriptor or
  relabel arbitrary OKF provenance as reviewed. Meeting admission is derived
  from the owner-scoped authoritative job/result, exact-compares the stored
  normalized source/path/resource/provenance, and enforces the current
  owner-only permission. Curated admission is one durable operation that
  requires the fixed role on a server-authenticated principal and derives its
  review identity and canonical compiled-source manifest from the repository
  revision/path and complete generation; callers cannot mint a reusable review
  token. Production Git hosting/review remains a later repository/operations
  owner.
- **Dependencies/events:** exact reviewed capture or curated repository source
  -> typed source admission -> deterministic OKF generation -> staged Postgres
  generation. Staging requires the durable admission identity in the same
  database transaction.
- **Failure/recovery:** inserts return and read back the durable row. Only an
  exact retry is idempotent; review replay, changed title/content/provenance,
  cross-owner use, or an unobserved conflict fails closed.
- **Cancellation:** database cancellation rolls back admission/staging; no
  compiled projection becomes authority without the committed admission row.
- **Duplicate owner:** none. Provenance text is descriptive; the admission row
  is the sole authority to stage a generation.

### 21. Terminology records, snapshots, and job bindings

- **Entry point:** `knowledge/terminology_ledger.py` and
  `knowledge/terminology_snapshot.py`.
- **Authoritative owner:** the terminology ledger owns tenant-scoped immutable
  records, frozen snapshots, and owner-scoped job bindings. Projection helpers
  derive decoder hints, normalization constraints, glossary concepts, and exact
  forms without becoming writers.
- **Persisted state:** terminology records, canonical snapshot payloads/hashes,
  and `(tenant, subject, job)` bindings.
- **Trust boundary:** server-derived principal/team/organization authorization
  selects visible records; request data cannot grant itself membership or
  management authority. Reads and bindings enforce tenant, subject, and job
  ownership.
- **Dependencies/events:** authorized terminology mutation -> deterministic
  tenant snapshot -> immutable job binding -> compiler and governed-agent
  projections consume the same snapshot identity.
- **Failure/recovery:** invalid scope, forged membership, cross-owner lookup,
  stale or malformed snapshot material, and conflicting job binding fail closed.
  Exact persisted identities survive reconnect.
- **Cancellation:** transactions either publish one complete record/binding or
  roll back.
- **Duplicate owner:** none; model-specific hint formats are projections of the
  model-independent ledger.

### 22. Knowledge generations and permission-safe retrieval

- **Entry point:** `knowledge/generation_ledger.py`,
  `knowledge/postgres_permission_view.py`,
  `knowledge/postgres_knowledge_retrieval.py`, and
  `knowledge/postgres_relationship_retrieval.py`.
- **Authoritative owner:** the generation ledger owns staged builds, embeddings,
  validation, the active pointer, activation history, rollback, and retention.
  The Postgres permission view owns query authorization; the retrieval modules
  own lexical/vector/hybrid/tree/relationship reads against that exact view.
- **Persisted state:** admitted builds, concepts, chunks, relationships,
  permissions, audiences/denials/purposes, embeddings, active build, and
  activation history.
- **Trust boundary:** principal, purpose, capability, tenant, generation, and
  permission-hash checks run before any text/relationship is returned. A shared
  tenant transaction lock pins the active generation through authorization,
  retrieval, proposal/audit publication, and commit; activation and pruning use
  the exclusive counterpart.
- **Dependencies/events:** source admission -> staged complete generation ->
  atomic activation -> authorized query -> exact cited results. The next query
  sees a successor only after the prior pinned query releases its transaction.
- **Failure/recovery:** incomplete/unadmitted generations cannot activate. The
  activation transaction revalidates the durable source-admission identity and
  the complete persisted non-embedding projection before moving the pointer;
  stale-generation requests, hidden concepts/links, permission changes, and
  cross-tenant/owner reads fail non-disclosingly. Rollback and bounded prune
  operate under the same tenant lock.
- **Cancellation:** connection cancellation/rollback releases the shared lock;
  no partial response or audit success is committed.
- **Duplicate owner:** none. The former in-memory permission/search
  implementations are removed; behavioral authority is Postgres-only.

### 23. Governed tools, proposals, RAG, MCP, and route selection

- **Entry point:** `knowledge/knowledge_tool_contract.py`,
  `knowledge/governed_knowledge_tools.py`,
  `knowledge/governed_rag_agent.py`,
  `knowledge/governed_knowledge_mcp.py`, and
  `knowledge/agent_reasoning_routes.py`.
- **Authoritative owner:** the tool contract owns names, bounds, request
  validation, and model-facing schemas. Governed tools own permission-safe
  execution; the RAG agent owns the cited answer workflow; MCP is a thin async
  adapter over the same authority. The route selector maps one explicit workload
  class to one configured model and never substitutes another route.
- **Persisted state:** immutable proposal/citation records and content-free tool
  audit identities. Proposed items are noncanonical; authorized discard is the
  sole current disposition and atomically releases generation retention.
- **Trust boundary:** token-derived principal, agent capability, purpose,
  permission view, visible citations, job terminology snapshot, and exact tool
  bounds are revalidated at every transition. Neither MCP nor model output gains
  raw repository, SQL, vector-index, credential, or private-evidence authority.
- **Dependencies/events:** explicit route -> bounded tool calls -> authorized
  Postgres results -> cited answer or immutable proposal -> audit. Unresolved
  proposals keep their cited generation reviewable; discarded proposals do not.
- **Failure/recovery:** invalid tools/arguments/citations, route failure,
  authorization change, cancellation failure, and model transport errors fail
  closed without cross-route fallback or late proposal/audit success.
- **Cancellation:** the async MCP adapter signals cancellation and waits through
  shielded cleanup for the database operation, cancellation watcher, and
  connection context to finish.
- **Duplicate owner:** none. MCP and qualification consume the shared production
  tool contract rather than maintaining independent schemas.

### 24. Agent qualification and aggregate governed-knowledge gate

- **Entry point:** `evaluation/agent_model_qualification.py` and
  `evaluation/governed_knowledge_gate.py`.
- **Authoritative owner:** `evaluation/agent_vllm_runtime.py` owns each immutable
  evaluation container/model lifecycle; `agent-reasoning-candidates.lock.json`
  owns the exact route-to-runtime mapping; the model qualifier owns the frozen
  route decision; `evaluation/agent_model_acceptance.py` owns the exact runtime
  recipe/input hashes, two-attempt final-response bound, and route-specific
  common/proposal latency and output policy; the fixture runner owns
  conversation/tool sequencing, per-case output bounds, and final structural decoding;
  `evaluation/owned_postgres_knowledge_runtime.py`
  owns the disposable database lifecycle; the aggregate gate composes those
  admitted results with the exact portable, Ruff, Postgres, restart, and
  teardown checks.
- **Persisted state:** create-once owner-private evidence outside Git. Public
  repository state contains only frozen contracts, immutable runtime/model
  identities, and public-safe hashes/outcomes. Exact qualification head
  `a76ed9b0...` returned `required-workload-routes-qualified`; schema-3 lock
  commit `2cf1e92c...` binds its exact artifact/input/dependency hashes and has
  passed semantic admission. Separate aggregate head `22c3f369...` owns the
  create-once `governed-knowledge-gate-passed` receipt with evidence SHA-256
  `8c2bfdef6b596094fe113a12b1bbfccec94ddeb3944e1b3313f41b61d5df12b0`;
  route admission alone does not imply that result.
- **Trust boundary:** clean exact HEAD, protected input hashes, route-specific
  Dockerfile/build/notice/dependency identities, exact observed immutable
  Docker image/container/model identity, bounded loopback endpoints, private
  artifact admission, child hashes, and exact teardown. Qwen and Gemma never
  inherit one shared runtime assumption or silently fall back. Raw prompts, outputs,
  measurements, credentials, DSNs, rows, and private paths never enter public
  receipts.
- **Dependencies/events:** one owned Qwen 26.07+XGrammar 0.2.1 run and one owned
  Gemma 26.06 run -> private
  route decision -> semantic private-tree admission -> owned Postgres gate ->
  exact-head hosted checks. Each case completes every tool step once before its
  final response; only a structurally undecodable final answer may receive one
  additional request against the unchanged conversation/tool result. One
  synthetic rapid cited-proposal case freezes the complete product-valid call;
  terminology and complex proposal cases retain open-ended grounding evidence.
  The rapid route keeps its 256-token maximum, caps its three frozen proposal
  fixtures at 160, and evaluates common and proposal latency separately; Gemma
  remains at 512. Those are evaluation-route bounds rather than a production
  service SLO or capacity claim.
- **Failure/recovery:** pre-admission and started identities remain observable
  until exact container/listener/PID/cgroup cleanup; partial evidence is never
  published. Protected producer/runtime/tool changes invalidate predecessor
  evidence and require one fresh private qualification. Tool/argument/transport
  errors and well-formed semantic failures do not enter the final decoder retry;
  request count and elapsed time span the complete case.
- **Cancellation:** candidate and database runtimes prove cancellation,
  recovery, containment, and teardown before a decision or receipt is admitted.
- **Duplicate owner:** none. `private_json_evidence.py` owns the narrow
  create-once JSON publication primitive used by both gates.

### 25. Rust-supervised provider lifecycle

- **Entry point:** `server/orchestrator/src/main.rs`, with lifecycle composition
  in `supervisor.rs`; the outer host entry point is
  `infra/yap-server-node/yap-provider-supervisor@.service.in`.
- **Authoritative owner:** systemd owns the outer cgroup and abnormal
  supervisor restart. One Rust supervisor owns exactly one configured
  foreground launcher process, numeric-loopback readiness, exact served-model
  identity, bounded child restart/backoff, stop/reap, and the typed lifecycle
  snapshot. The existing launcher remains the sole container, private proxy,
  immutable image/model, and teardown owner. Rust never calls Docker.
- **State:** one boot-scoped, atomically replaced, owner-private JSON snapshot
  containing only route identity, lifecycle state, process generation, and
  bounded start/restart/failure/readiness counters. It is an operational
  projection, not durable application state or performance evidence.
- **Trust boundary:** the command line requires one supported service identity,
  canonical numeric-loopback HTTP authority, one exact model identity, one
  absolute canonical regular launcher, one absolute private state destination,
  and an explicit `--` launcher-argument boundary. Readiness requires HTTP 200
  from `/health` plus exactly one matching `/v1/models` entry; PID/listener
  presence, hostnames, extra models, and fallback routes are insufficient.
- **Dependencies/events:** systemd -> Rust supervisor -> one exact profile -> one
  foreground launcher -> launcher-owned container/proxy -> exact health/model
  read-back. Merged Slice 10.2 supplies immutable Qwen rapid and Gemma complex
  profiles to separate instances; the separate admission owner below consumes
  their state without changing lifecycle authority.
- **Failure/recovery:** startup has a fixed deadline; three consecutive ready
  probe failures retire the child; the supervisor permits at most three
  restarts in 60 seconds with fixed 1/2/4-second backoff. Exhaustion publishes
  `failed`. Normal stop publishes `stopping`, signals the launcher, force-kills
  only after the fixed grace period, proves reap, and then publishes `stopped`.
  systemd uses `Restart=on-abnormal`, so it does not relabel an ordinary
  fail-closed supervisor exit or duplicate Rust's child restart policy.
- **Cancellation:** Unix `SIGINT`/`SIGTERM` and Windows console termination
  signals converge on the same bounded stop/reap path. A shutdown received
  during restart backoff terminates cleanly without launching another child.
- **Duplicate owner:** none. Rust does not reconstruct launcher/container
  policy, and systemd does not own child restart. Authenticated queues and
  capacity evidence must consume these exact-profile lifecycle owners rather
  than introduce another health/restart state machine.

Exact Slice 10.2 lifecycle head `4b103c1b...` passed sequential Qwen/Gemma
start/readiness/restart/stop and zero-residue teardown; qualification head
`4d623212...` qualified both routes; and aggregate head `0471b158...` passed the
governed gate. Hosted-green head `6d1400cc...` merged through PR #157 as
`cac8989b...`. Production process
supervision, simultaneous warm model residency, sustained
mixed-owner capacity/SLOs, external transport, enterprise identity/networking,
backup/restore, and deployment remain Phase 10 or explicit IT handoffs; the
sequential lifecycle evidence above is not production-service or capacity
evidence.

### 26. Multi-user agent admission

- **Entry point:** `server/orchestrator/src/bin/yap-agent-admission-broker.rs`,
  with the state machine in `agent_admission.rs`; Python enters only through
  `yap_server/agents/admission_client.py` and its strict protocol owner.
- **Authoritative owner:** one Rust scheduler owns role/purpose/route/class
  binding, provider readiness generations, global/per-owner queue limits,
  owner round robin, weighted priority, idle-only exclusion, queue-inclusive
  deadlines, terminal retention, and token-bound completion/cancellation.
  Python supplies an already-authenticated tenant/subject and later owns the
  authorized workflow; it does not own scheduling or provider readiness.
- **State:** bounded in-memory pending, active, and terminal lease state. The
  broker deliberately does not auto-restart after losing that state. Its
  systemd unit creates a 0700 runtime directory and 0600 Unix socket, never
  starts provider units, and is installed without enable/start.
- **Trust boundary:** strict one-line JSON up to 16 KiB; exact schema and role
  binding; source SHA, request ID, cancellation token, deadline and provider
  generation validation; same-UID owner-private socket read-back; no bearer,
  client ID, scope, provider credential, prompt, or output crosses the internal
  protocol.
- **Dependencies/events:** exact provider lifecycle snapshots -> generation-
  bound admission -> role-owned Python work -> token-bound completion or
  acknowledged cancellation. A route is unavailable unless its exact already-
  warm snapshot is ready; admission never launches or swaps a model.
- **Failure/recovery:** queue/owner overload, unavailable providers, deadlines,
  cancellation, and non-disclosing token failures are typed. Provider unready
  or generation change fails queued work and requests cancellation of active
  work without releasing capacity before acknowledgement. Broker failure keeps
  new admission closed for operator containment rather than reconstructing
  leases it cannot prove.
- **Duplicate owner:** none. Provider supervisors remain lifecycle owners;
  role workflows remain domain owners; the broker only owns admission.

Exact protected head `7bd93dc6...` passes Windows and Linux Rust format,
all-target lint/tests, the Linux private-socket lifecycle, the exact 169-test
portable matrix across 28 modules, and Ruff. Its replacement private
qualification admitted both routes; public-lock/aggregate head `135cc2ba...`
passed semantic admission, the portable and 17-test Postgres matrices, real
restart/retrieval/stale/successor proof, unchanged desktop dependency scope,
and exact teardown. Hosted-green head `cf1e69a4...` merged the substrate through
PR #158 as `84d95842...`. The merged Scribe workflow below is its first product
consumer. Simultaneous residency, sustained capacity, and production promotion
remain open.

The current protected successor changes admission inputs so active capacity is
derived from the immutable service profiles: four for rapid automation and
eight for complex orchestration, while Server IO remains one and one active
request per owner remains global. Exact route head `dab19fe...` qualified Qwen
and Gemma sequentially on those unchanged full profiles with public-safe
evidence SHA-256 `96228914...`; exact workflow head `7cd24deb...` then qualified
Scribe, Student, and Curator, and aggregate/public-lock head `7f896b34...`
passed with evidence SHA-256 `fd197b98...`. The exact one-slot evidence above
remains historical and authoritative for its merged head; it is no longer the
current merged boundary. Hosted-green head `593e627b...` passed all 12 checks,
and PR #168 merged the successor as `284ab96b...`. Selected-route capacity is
not sustained-throughput, simultaneous-residency, or production-SLO evidence.

Exact executable successor `0665c486...` changed the complex runtime/profile to
batch-invariant request execution with seed `0` and prefix caching disabled. It
passed sequential lifecycle evidence `7cc016f4...` and route evidence
`06277bd9...`; lock-only `8fee7a5c...` publishes the matching lock. At that
lock-only successor, the affected Curator, Scribe, Student, and Librarian gates
and the aggregate gate passed. The complex probe held eight owners and queued
the ninth without changing provider/broker identity. This is selected-route and
same-warm-process evidence, not cross-start/global determinism, simultaneous
residency, sustained capacity, or a production SLO.

### 27. Scribe transcript correction

- **Entry point:** native commands in `desktop/src-tauri/src/transcript_correction/`
  and the authenticated connector in
  `desktop/src-tauri/src/server_connector/transcript_correction.rs`; server HTTP
  composition enters through
  `yap_server/api/transcript_correction_requests.py` and
  `yap_server/agents/transcript_correction_service.py`.
- **Authoritative owner:** native source readers own which finalized live/remote
  transcript may be corrected and native revision code owns user-accepted
  publication. The Python correction contract owns bounded structured edits and
  semantic preservation. The Rust admission broker remains the sole queue/
  readiness/deadline/cancellation owner; the renderer owns presentation only.
- **Persisted state:** raw transcript and its timing/language revision remain
  immutable. A user acceptance publishes a separate hash-chained correction
  revision beside the live source or inside the owned remote job spool. Server
  request/terminal state is bounded in memory; terminology snapshots remain in
  their existing Postgres ledger. Model output is never source truth.
- **Trust boundary:** native revalidates the trusted source before submission
  and again before publication; the server requires exact ordered segment
  hashes, source/revision identity, timestamps, language, owner/purpose, one
  immutable terminology snapshot, and a validated rapid-route response. The
  renderer receives neither bearer material nor arbitrary filesystem authority.
- **Dependencies/events:** finalized transcript -> native authenticated lease ->
  asynchronous POST/status/cancel -> Scribe HOT admission on the already-warm
  rapid route -> validated raw/corrected preview -> explicit native publication.
  Meeting notes/summaries are different workflows and do not enter this owner.
- **Failure/recovery:** overload, unavailable provider, queue-inclusive deadline,
  cancellation, source change, invalid/uncertain output, and unsupported old
  timingless transcripts return a typed non-publication outcome. Raw ASR,
  playback, export, deletion, capture, and other local controls remain usable.
- **Cancellation:** UI cleanup or source change requests server cancellation;
  the server keeps capacity owned until Rust acknowledges the terminal token.
  No cancelled, failed, or stale request can publish a correction revision.
- **Duplicate owner:** none. The deleted renderer/Ollama Polish implementation is
  not retained as a fallback or compatibility path.

Exact Scribe source-lock head `e5858424...` passed its private gate; hosted-green
head `bc9a88bc...` passed all 12 required checks and PR #164 merged the workflow
as `ec3af506...`.

### 28. Archivist reviewed-source ingestion

- **Entry point:** `yap_server/agents/archivist_service.py` owns one synchronous
  BACKGROUND_IO broker workflow; `yap_server/agents/archivist.py` owns the
  reviewed-capture-to-compiled-generation boundary.
- **Authoritative owner:** the reviewed-capture ledger owns durable source
  identity and bytes; the existing compiler, source-admission ledger, and
  generation ledger remain the only compilation/admission/staging writers.
  Archivist composes them and does not become a second database authority.
- **Persisted state:** one source admission plus one immutable staged generation.
  Archivist never stores raw caller content, embeddings, an active-generation
  pointer, or a separate success ledger.
- **Trust boundary:** the request contains only schema version and capture SHA.
  Tenant/owner comes from the authenticated principal. The capture is read,
  compiled in an owner-private temporary workspace, and re-read before one
  admission/staging transaction.
- **Dependencies/events:** durable reviewed capture -> SERVER_IO lease ->
  deterministic OKF compile -> source admission -> exact idempotent generation
  stage -> typed result. No LLM/GPU route is selected.
- **Failure/recovery:** queued/active cancellation, deadline, invalid/cross-owner
  source, storage failure, and wrong-route lease fail without activation or a
  success result. Exact retry succeeds only when the complete persisted
  non-embedding generation is identical.
- **Duplicate owner:** none. `ArchivistService` owns broker state/cancellation;
  `archivist.py` owns private compilation; existing ledgers retain durable
  authority.

Exact source candidate `3ec9885e...` passed focused unit checks, the complete
1,207-test portable server suite, and two real PostgreSQL retry/restart/
cross-owner/cancellation tests with exact six-part teardown. Hosted-green head
`e1899db7...` passed all 12 checks and PR #165 merged the core as
`2a7ec819...`. HTTP/native/UI exposure remains later work.

### 29. Student learning-question workflow

- **Entry point:** `yap_server/agents/student_service.py` owns one synchronous
  BACKGROUND_LLM broker workflow; `yap_server/agents/student_runtime.py` binds
  it only to the authenticated already-warm rapid profile.
- **Authoritative owner:** the Postgres permission/retrieval owners supply one
  active owner-scoped conversation generation and its exact citations;
  `student_model.py` owns strict bounded response decoding. Student creates no
  second source, permission, proposal, or knowledge authority.
- **Persisted state:** `student_result_audit.py` writes one immutable redacted
  terminal outcome identity. Question text is returned to the caller but is not
  stored in that audit ledger.
- **Trust boundary:** tenant/subject comes from the authenticated principal;
  request identity binds the expected generation and conversation concept. The
  server constructs the evidence pack and retains complete citation objects.
  The model sees only ordered evidence indexes and text and supplies exactly
  one source subject, one non-Boolean in-range evidence index, and one support
  quote. The server selects the frozen evidence object, binds the complete
  citation, resolves the unique quote, derives its span, and alone renders the
  question text.
- **Dependencies/events:** permission-safe generation read -> rapid-route lease
  -> bounded exact-subject selection -> canonical citation/support validation
  -> server-rendered question -> one terminal audit. The route is already warm;
  Student never launches, swaps, or reduces it.
- **Failure/recovery:** cancellation, deadline, provider loss, invalid/stale
  evidence, cross-owner access, invalid output, and audit/storage failure yield
  no successful questions. Capacity remains owned until cancellation is
  acknowledged.
- **Duplicate owner:** none. Retrieval owns evidence, the Rust broker owns the
  lease, the Qwen client owns one bounded inference, and the audit ledger owns
  only the redacted terminal record.

Exact candidate `452c8b76...` produced a nominally green private receipt, but
adversarial review demonstrated unsupported-premise admission and invalidated
that evidence. Exact `476f7a9c...` then returned terminal
`deterministic-no-student`. Exact evidence-index successor `0970d74c...`
also returned terminal `deterministic-no-student` after a model-selected
subject was absent from its exact quote/evidence; the server rejected it. The
current prompt/test repair changes protected inputs and is complete-portable-
test green and privately qualified at exact head `428d6e48...` on the unchanged
full Qwen rapid profile, with public-safe evidence SHA-256 `f597cca7...`.
Hosted-green head `b03c6e79...` passed all 12 required checks and PR #166 merged
the internal core as `2254605e...`. An HTTP/native/UI surface remains open.

### 30. Curator knowledge-proposal core

- **Status:** privately qualified internal core at exact head `7cd24deb...` with
  public-safe evidence SHA-256 `b60df1e2...`; hosted-green head `593e627b...`
  passed all 12 checks, and PR #168 merged it as `284ab96b...`. No HTTP, native,
  renderer/UI surface, active-knowledge promotion, or production promotion exists.
- **Entry point:** `yap_server/agents/curator_service.py` owns an internal
  complex-route workflow for only `explicit-proposal` and
  `reviewed-student-answer` submissions.
- **Authoritative owner:** the server re-reads each submitted citation from the
  authenticated permission-safe generation. The model may return only a
  bounded propose/reject decision; it cannot supply citation authority or
  activate knowledge.
- **Persisted state:** `curator_publisher.py` may atomically append one
  noncanonical `KnowledgeProposal` plus its audit identity. Proposal state is
  proposed or discarded and is not an active generation, compiled source, or
  mutation of reviewed source truth.
- **Failure/recovery:** invalid/stale evidence, cross-owner access, model
  rejection, cancellation, deadline, provider loss, capacity, and audit/write
  failure publish no successful proposal. Exact retries must replay the same
  durable terminal outcome.
- **Duplicate owner:** none. Permission-safe retrieval owns evidence;
  `CuratorService` owns the workflow; the existing proposal ledger owns
  noncanonical proposal state; activation remains outside Curator.

The exact gate completed eight cases/eight owners with four proposals, four
rejections, zero terminal failures, complex capacity eight plus a queued ninth
owner, unchanged warm/broker identities, PostgreSQL restart/read-back and exact
teardown. Candidate `7ba4e45c...` failed closed on the empty forced-tool content-
envelope contract, wrote no Curator qualification receipt, established no
admissible Curator success evidence, and remains terminal; no teardown result is
attributed to it. See the
[Curator verification record](../../evidence/curator-knowledge-proposals/VERIFICATION.md).

### 31. Librarian permission-safe evidence core

- **Status:** privately qualified at exact head `56b7f5d0...`; hosted head
  `7505247e...` merged through PR #169 as `d7a7e003...`. All product surfaces
  remain pending.
- **Entry point:** `yap_server/agents/librarian_service.py` owns one bounded
  authenticated Server-IO read. It acquires no model-route lease.
- **Authoritative owner:** the Postgres permission-safe retrieval owner pins the
  active generation and derives citations; Librarian cannot accept caller-owned
  evidence authority or expose hidden nodes or links.
- **Persisted state:** the immutable Librarian result-audit ledger records only
  bounded identities and terminal outcomes. Librarian writes no knowledge
  proposal and activates no generation.
- **Failure/recovery:** stale generation, revocation, unavailable evidence,
  deadline, cancellation, audit failure, and admission failure return typed
  fail-closed outcomes. Exact predecessor `ecdcb8ee...` is terminal and not
  reused because its nominal eight-owner wave produced seven broker submissions.
- **Duplicate owner:** none. The broker owns the Server-IO lease; permission-safe
  retrieval owns evidence; `LibrarianService` owns workflow termination; the
  result-audit ledger owns durable outcome identity.

See the [Librarian verification record](../../evidence/librarian-permission-safe-evidence/VERIFICATION.md).

### 32. Analyst grounded cited-answer core

- **Status:** privately qualified merged internal core. Exact executable head
  `0665c486...` supplied qualification; lock-only `8fee7a5c...` publishes the
  matching route lock; hosted head `da1127f8...` merged through PR #170 as
  `52c45d22...`. All product surfaces remain pending.
- **Entry point:** `yap_server/agents/analyst_service.py` owns one bounded
  authenticated interactive complex-route request composed through
  `analyst_runtime.py`.
- **Authoritative owner:** `LibrarianService` owns permission-safe retrieval;
  the PostgreSQL Analyst evidence verifier reauthorizes the exact succeeded
  Librarian pack and current generation in transaction. The model selects only
  whole evidence-item indexes. Server-owned Analyst code derives answer and
  citation identities from the frozen pack.
- **Persisted state:** the immutable Analyst result-audit ledger records bounded
  identities and terminal outcomes. It does not persist answer or evidence bytes,
  publish a knowledge proposal, or activate a generation.
- **Failure/recovery:** empty or unavailable evidence, stale generation, invalid
  output, cross-owner access, replay conflict, provider loss, cancellation, and
  deadline return typed fail-closed outcomes with no answer.
- **Duplicate owner:** none. Librarian owns retrieval; the verifier owns current
  authorization; `AnalystService` owns workflow termination; the Analyst result-
  audit ledger owns durable outcome identity; the broker owns admission.

Three synchronized repeat waves matched 24 of 24 normal invocations, all 29
terminals matched, and 12 answers contained 15 server-owned citations. Exact
`63c3d9fd...` remains terminal no-receipt evidence from the superseded schedule-
sensitive runtime and is not reused. See the
[Analyst verification record](../../evidence/analyst-grounded-cited-answers/VERIFICATION.md).

### 33. Coordinator source-cited proposal-bundle core

- **Status:** privately qualified merged internal core at exact executable head
  `fed729b3...`. Hosted head `53ee0152...` passed all 12 checks, and PR #171
  merged it as `67d836da...`. All product surfaces remain pending.
- **Entry point:** `yap_server/agents/coordinator_service.py` owns one bounded
  authenticated background complex-route request composed through
  `coordinator_runtime.py`. It submits no nested role-service request.
- **Authoritative owner:** the owner-scoped proposal reader in
  `knowledge_proposals.py` pins the active generation, takes the tenant/owner
  advisory locks, requires exact succeeded Curator lineage, reauthorizes every
  current citation, and returns only current eligible proposals. The model may
  select ordered indexes only; server-owned Coordinator code derives all bundle
  text, proposal identities, and citations.
- **Persisted state:** the immutable Coordinator result-audit ledger records
  bounded content-free request, evidence, bundle, citation, authority, model,
  provider, and terminal identities. Coordinator does not publish a proposal,
  plan, task, source mutation, or knowledge activation.
- **Failure/recovery:** empty/hidden/foreign/stale evidence, invalid model
  output, cross-owner access, replay conflict, provider loss, cancellation,
  deadline, and audit failure return typed fail-closed outcomes with no bundle.
  Success re-reads and exact-compares current evidence in the terminal audit
  transaction before returning.
- **Duplicate owner:** none. The proposal ledger owns Curator artifacts; the
  proposal reader owns current authorization; `CoordinatorService` owns one
  workflow lease and termination; the Coordinator result-audit ledger owns
  durable terminal identity; the broker owns admission.

Three synchronized repeat waves matched 24 of 24 normal service calls, all 29
terminals matched, and 15 server-derived noncanonical review-required bundles
contained 18 selected items and 18 citations. Exact `11f325bb...` remains
terminal no-receipt evidence from the superseded deadline-lifecycle verifier
and is not reused. See the
[Coordinator verification record](../../evidence/coordinator-proposal-bundles/VERIFICATION.md).

### 34. Auditor source-cited review-findings core

- **Status:** privately qualified merged internal core at exact executable head
  `08b06f6d...`. Hosted head `937a4129...` passed all 12 checks and PR #172
  merged it as `1b255e9a...`; all product surfaces remain pending.
- **Entry point:** `yap_server/agents/auditor_service.py` owns one bounded
  authenticated idle-only complex-route request composed through
  `auditor_runtime.py`. It submits no nested role-service request.
- **Authoritative owner:** `PostgresAuditorEvidenceReader` pins the active
  generation, derives the fixed `knowledge.read` authority from the principal,
  and returns only bounded current owner-visible source evidence. The model may
  select evidence-index pairs only; server-owned Auditor code canonicalizes
  those pairs and derives all finding text, source identities, and citations.
- **Persisted state:** the immutable Auditor result-audit ledger records bounded
  content-free request, evidence, report, citation, authority, model, provider,
  and terminal identities. Auditor does not publish a proposal, source, task,
  action, finding body, or knowledge activation.
- **Failure/recovery:** insufficient/hidden/stale evidence, invalid model output,
  cross-owner access, replay conflict, provider loss, cancellation, deadline,
  and audit failure return typed fail-closed outcomes with no report. Success
  re-reads and exact-compares current evidence in the terminal audit transaction
  before returning.
- **Admission owner:** the broker alone owns idle-only dispatch. Active or
  queued non-idle work blocks Auditor admission; Auditor does not cancel,
  preempt, throttle, or replace accepted non-idle work.
- **Duplicate owner:** none. The knowledge ledger owns source truth; the Auditor
  reader owns current authorization; `AuditorService` owns one workflow lease
  and termination; the Auditor result-audit ledger owns durable terminal
  identity; the broker owns admission.

Three synchronized repeat waves matched 24 of 24 normal service calls, all 29
terminals matched, and 12 server-derived noncanonical review-required reports
contained 15 findings and 30 citations. The active/pending non-idle block and
post-terminal resumption contract was observed without changing provider or
broker identity. See the
[Auditor verification record](../../evidence/auditor-source-cited-review-findings/VERIFICATION.md).

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
| Server principal/access/purpose revisions | server identity repository | HTTP and private-live admission; purpose authorization |
| Reviewed meeting captures | reviewed-capture ledger | source admission and deterministic compilation |
| Reviewed Lane 1/Lane 2 source admissions | knowledge-source admission ledger | generation staging |
| Terminology records/snapshots/job bindings | terminology ledger | compiler, ASR projections, governed agents |
| Knowledge builds, active pointer, permissions, embeddings, and activation history | Postgres generation ledger | permission view and retrieval |
| Permission-safe cited retrieval | Postgres permission/retrieval owners | governed tools, RAG, MCP |
| Governed proposals and tool audit identities | proposal and audit ledgers | review workflow and generation retention |
| Librarian, Analyst, Coordinator, and Auditor terminal identities | immutable role result-audit ledgers | permission-safe evidence, grounded cited-answer, proposal-bundle, and review-findings replay; no evidence/answer/bundle/report bytes |
| Agent workload route selection | explicit server route selector | governed RAG invocation |
| Private route and aggregate gate evidence | evaluation lifecycle and gate owners | public-safe hashes/outcomes only |
| Boot-scoped provider lifecycle snapshot | one Rust provider supervisor | systemd/operators; not durable application truth |
| Boot-scoped agent admission leases | Rust agent admission broker | authenticated Python role workflows; not durable application truth |
| Accepted transcript-correction revisions | native Scribe revision owner | React diff/history projection; raw transcript remains authoritative |
| Archivist ingestion outcomes | reviewed-capture, source-admission, and generation ledgers | typed staged-generation result; no activation |
| Student workflow outcomes | immutable Student result-audit ledger | typed source-supported question result; question text is not durable audit state |
| Librarian workflow outcomes | immutable Librarian result-audit ledger | typed permission-safe evidence result; evidence text is not durable audit state |
| Analyst workflow outcomes | immutable Analyst result-audit ledger | typed grounded cited-answer result; answer/evidence text is not durable audit state |
| Coordinator workflow outcomes | immutable Coordinator result-audit ledger | typed proposal-bundle result; objective/proposal/citation bytes are not durable audit state |
| Auditor workflow outcomes | immutable Auditor result-audit ledger | typed source-cited review result; focus/evidence/finding/citation bytes are not durable audit state |
| Presentation preferences/drafts | feature-specific frontend storage/state | React only |

## No-multiple-owner invariant

A second representation is acceptable only when it is a read-only projection,
an atomic compatibility import, or an adapter around the authoritative owner.
If a future change introduces two writers for any row above, it requires a new
ADR or a checkpoint finding before merge.
