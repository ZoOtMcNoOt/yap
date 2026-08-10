# yap-server staging and private reference runtime

This directory is the MVP staging area for the future `yap-server` repo.

It remains part of the MVP monorepo. Do not split the server or contracts into
another repository before the canonical Phase 10 boundary.

Keep the interfaces narrow while the private server path becomes real:

- API contracts live here first, likely `openapi/`.
- Router/service code lives here only when it has tests.
- Model worker code is isolated from the health process and must remain pinned,
  bounded, and independently gated.
- Host setup stays in `../infra/yap-server-node/`.
- Shared desktop/server contracts stay here until type drift proves a separate `yap-contracts` repo is worth it.

The server tier grows inside this shape:

```text
server/
  README.md
  openapi/
    README.md
    openapi.json            # Phase 3 health + later HTTP contracts
    live-events.schema.json # authenticated private live contract
  src/
    yap_server/
      api/
      jobs/                  # Durable loopback batch-ASR service/runtime
      pools/                 # bounded Phase 4 reference worker and pool
      schemas/
      config/
  runtime/asr/               # pinned ARM64 image recipe and notices
  model-pools.lock.json      # exact runtime/model/fixture authority
  tests/
    README.md
    contract/
    api/
    jobs/
    model_pools/
```

Name runtime modules for their actual owner and behavior. Use `schemas/` for API
and message shapes. Do not add a repo `models/` directory; runtime model files
belong on the server node, not in Git.

## Phase 3 contract boundary

`openapi/openapi.json` and `openapi/live-events.schema.json` are the normative
machine-readable wire contracts. Their presence does not mean every route is
implemented:

| Method | Path | Default Phase 3 profile | Phase 5 loopback batch profile |
|--------|------|-------------------------|--------------------------------|
| `GET` | `/v1/health` | Implemented; all processing capabilities false | Implemented; batch/status true only after runtime startup succeeds |
| `POST` | `/v1/jobs` | `501 NOT_IMPLEMENTED` | Durable create with canonical-request idempotency |
| `GET` | `/v1/jobs/{jobId}` | `501 NOT_IMPLEMENTED` | Durable status |
| `DELETE` | `/v1/jobs/{jobId}` | `501 NOT_IMPLEMENTED` | Idempotent cancellation with safe-boundary purge |
| `GET` | `/v1/jobs/{jobId}/result` | `501 NOT_IMPLEMENTED` | Immutable completed result |
| `PUT` | `/v1/jobs/{jobId}/chunks/{trackId}/{sequenceStart}-{sequenceEnd}` | `501 NOT_IMPLEMENTED` | Identity-checked resumable PCM upload |
| `POST` | `/v1/jobs/{jobId}/commit` | `501 NOT_IMPLEMENTED` | Manifest-bound dispatch through the bounded pool |
| `GET` upgrade | `/v1/live` | Event schema only | Still unimplemented; live capability remains false |

The default Phase 3 profile advertises `batchJobs`, `liveStreaming`, and
`jobStatus` as `false` and keeps every job route unavailable. The Phase 5
profile is an explicit Linux/loopback development runtime: only after its
private storage, immutable model lock, verified model directory, and pool
initialize successfully do batch/status become true. In those historical
profiles, a WebSocket runtime, authentication, token validation, diarization,
persistent supervision, and an external application listener are not present.
The merged Phase 7 baseline adds authenticated private live admission on a
separate loopback listener; it does not alter the Phase 3/5 table above or
create a production application edge.

Contract JSON fields use camelCase. Immutable manifest and server enum values
use snake_case. The React `RecordingJobView` values are an explicit projection,
not alternate wire values.

Chunk uploads use `application/octet-stream` raw `pcm_s16le` bytes. The logical
idempotency key and the SHA-256 byte identity are separate: the same key and
hash is replay success, while the same key with a different hash is a 409
`CONTENT_IDENTITY_CONFLICT`. Job and chunk requests do not accept tenant or
owner-subject fields. In `entra` mode those values are server-derived from the
validated token and identity repository; the historical development profile
uses only its isolated development principal.

## Phase 4 private batch-ASR reference slice

Phase 4 adds one executable server-internal vertical slice without turning the
Phase 3 health process into a production service:

- `model-pools.lock.json` pins the canonical Cohere model and revision, the
  public byte-distribution revision, every deployed artifact hash, the licensed
  speech fixture, the complete model license text, and the exact ARM64 runtime
  identity.
- `runtime/asr/Dockerfile` uses
  `nvcr.io/nvidia/pytorch:26.06-py3` by immutable digest, Python 3.12, the
  NVIDIA Torch/CUDA build from that image, and a hash-locked resolver-minimal
  Python overlay.
- The current loopback batch runtime delegates directly to `BatchAsrPool`, the
  executable slot, queue, cancellation, and aggregate-PCM admission owner. The
  accepted future mixed-live/batch fairness rule remains in ADR 0023 without a
  speculative non-executable router module.
- `BatchAsrPool` provides a bounded thread-backed queue. Its container adapter
  runs each job non-root with no network, a read-only root filesystem, dropped
  capabilities, `no-new-privileges`, memory/CPU/PID/output ceilings, read-only
  model/audio mounts, an explicitly non-executable `/tmp`, and only a private
  executable tmpfs for bounded PyTorch compiler output. Every run has a unique container name
  and an unconditional force-remove cleanup check.
- `gb10_asr_runtime_gate.py` connects pool -> isolated worker, verifies the
  immutable model and licensed fixture, executes the inspected raw image ID,
  requires input/result audio identity plus exact GB10/compute-capability/BF16
  runtime attestation, and enforces the fixture WER threshold. The wrapper
  publishes results atomically only after listener, firewall, Yap service-unit,
  container, and worker-process read-back passes.

The Phase 4 reference slice by itself is not an upload endpoint, automatic
desktop queue drain, authenticated session, persistent server process, external
listener, or multi-worker capacity claim. Phase 5 reuses its isolated worker
through the separate development batch runtime below; production deployment
claims remain gated.

## Loopback batch-ASR path

Set `YAP_BATCH_ASR_ENABLED=1` only on Linux with a numeric loopback bind,
private mode-0700 job storage, the immutable model lock, an already verified
model directory, and `YAP_CHECKED_HEAD` set to the full checked SHA. The merged
Phase 5 evidence used the transient custom Transformers worker. On the active
Phase 6 branch, `development-batch-server.sh` selects the Cohere vLLM adapter and
requires a separately running checked `cohere-vllm-server.sh`, numeric-loopback
endpoint, and private API key. The vLLM launcher inspects the exact ARM64 image
ID and revision label, requires a checked internal Docker bridge, runs the
container without a Docker-published port, and owns a bounded `socat` process
group that forwards only `127.0.0.1:18000` to the container-private address.
Each launcher requires a private `YAP_PROXY_PROCESS_GROUP_FILE`; the proxy
publishes its group identity there until verified teardown so the lifecycle
owner can recover it after an abnormal launcher exit.
The Yap launcher resolves Python 3.12 dependencies through the server's locked
`uv` project with network access disabled; it never falls back to ambient
system packages. Set `YAP_UV_BINARY` to an absolute executable when `uv` is not
on the noninteractive service path, and prepare the locked cache/environment
before launching the offline runtime.
The same foreground launcher can enable the verified AmberNet language
preflight by passing `YAP_LANGUAGE_DETECTION_ENABLED=1`, the private verify-only
model directory, the receipt-bound raw `server/runtime/lid` image ID, and the
private preparation-receipt path plus its frozen SHA-256.
When those inputs are absent, the server does not advertise
`languagePreflight`; clients then retain the recording for explicit language
review instead of silently bypassing the unavailable check.
The committed
capability catalog contains Cohere only; it does not advertise the unpromoted
Nemotron candidate. `nemotron-nemo-server.sh` exists for direct frozen
qualification on numeric loopback with a separate private API key. Wiring that
candidate through the development batch server additionally requires an
explicit matching candidate capability lock outside the repository. The
launcher verifies the ARM64 image/revision and the same internal-network
owner/revision contract, runs as the non-root model owner,
mounts the private job store read-only at the same absolute path, and exposes
only the bounded `127.0.0.1:18001` proxy by default. Candidate qualification is
not product-catalog
promotion. The runtime provides durable
create/upload/commit/status/result and cancellation handlers, a single running
plus two queued GPU jobs, eight bounded HTTP workers, a 512-record cap,
one-MiB chunks, and a four-hour mono PCM16/16 kHz job cap. It performs startup
and periodic maintenance, purges cancelled/failed private audio at a safe
lifecycle boundary, and retains completed results for the configured finite
period.

The reusable provider-qualification helpers build exact-duration inputs and
hash-bound jobs only beneath `YAP_EVAL_CACHE`, execute synchronized bounded
waves, and emit aggregates without paths, request IDs, transcript text, or
transcript hashes. Focused repeated-fixture controls reached the exact four-hour
boundary through both candidate adapters. They prove transport/runtime
lifecycle only. Yap sends Cohere/vLLM one offline API request; vLLM may split it
into multiple bounded engine requests and schedule those chunks concurrently.
NeMo advances 1.12-second cache-aware frames across finalized windows, while
this service currently publishes no partial transcript. Treat their wall times
as provider-specific execution-shape evidence, not a streaming-UX comparison.
The qualification output labels vLLM histograms per engine request and Yap wall
latency per API request. The frozen sentinel-rich and representative-quality
gates remain required before any catalog or performance claim.

Build the desktop's deterministic duration inputs with
`python -m yap_server.evaluation.local_stream_duration_suite`. Set
`YAP_EVAL_CACHE` to an absolute private directory and pass one or more vetted
mono PCM16/16-kHz WAVs with repeated `--source`. Select
`--profile short-boundaries` for the nine 250-ms-through-30-second Phase 6
boundary cases. Select `--profile complete-local-duration-ladders` only for the
later full 15-case release qualification. The selected functional profile is
embedded in the versioned suite manifest and uses a distinct immutable
collection ID. The command fails if a source changes during construction,
prints the private `suite.json` path and its SHA-256, and never places audio or
transcript content in the repository.
`--expect-text-case` is optional and asserts only a non-empty result for that
exact case; it is not an accuracy score.

Build the resident-provider runtime inputs with
`python -m yap_server.evaluation.provider_duration_suite` under the same private
`YAP_EVAL_CACHE` boundary. The builder derives one immutable track for every
unique duration required by the vLLM and NeMo ladders, standard/specialized load
cells, and the exact four-hour boundary. Its `suite.json` binds the public plan,
ordered requirement provenance, every track-manifest hash, and the plus-one
rejection boundary without recording source paths or transcripts. Building the
suite prepares inputs only; it does not execute or satisfy a provider gate.

Run one resident provider's plan-owned duration ladder with
`python -m yap_server.evaluation.resident_provider_duration_qualification`.
The command accepts only the Cohere vLLM batch ladder or the Nemotron NeMo
finalized-utterance/batch ladders; the exact four-hour boundary may be added only
to a batch run. It executes each selected duration once at c1, binds the clean
checked head, serving lock, plan, private suite, and selected audio, and repeats
the candidate and input read-back before atomically publishing private aggregate
evidence. The aggregate labels its scope as duration transport and lifecycle and
sets `representativeAccuracyClaim` to false. A passing run therefore proves that
the exact inputs completed and published bounded results through that resident
provider; representative WER, long-form sentinel integrity, concurrency, and
promotion remain separate gates.

Run a standard resident load cell with
`python -m yap_server.evaluation.provider_runtime_qualification`. The command
requires `--checked-head`, the absolute `--repository-root`, the plan, exact
provider-serving lock, `--duration-suite`, its out-of-band
`--duration-suite-sha256`, numeric-loopback endpoint, route languages, private
output root, and timeout. It admits only that exact clean Git head, validates the
suite against the current plan, loads only the cell's required audio durations,
hands those admitted tracks directly to the runner, then re-reads the suite and
selected audio before publishing a rehashed candidate envelope. It separately
hashes the plan and serving lock and repeats the Git/input read-back.
`YAP_EVAL_CACHE`
must name the absolute private cache containing both tracks and output; the
provider API key stays in its existing environment variable. The runner fails
closed on cancellation, fixed/automatic contracts, and capacity cells because those
require specialized semantics rather than an ordinary synchronized wave.
For the predeclared c8 resource profiles, the same command may select one
planned `--concurrency` and a bounded `--repeat-count`. Repetition is rejected
unless exactly one plan-owned concurrency is explicit; eight repeats of the
200-request short-tail cell therefore produce the required 1,600 completions
without changing the plan or synthesizing a different workload.

Those cells have separate executable entry points:
`provider_cancellation_qualification` requires a dispatched target, concurrent
provider activity, typed cancellation acknowledgement, sibling isolation,
idle read-back, and immediate recovery; for vLLM it also records the pinned
engine's `finished_reason` counters. The pinned external-disconnect path calls
the engine abort boundary but frees that request without adding it to the
finished-request histogram, so the runner distinguishes that one-stop shape
from a counted abort, a server completion after cancellation, and ambiguous
accounting. `provider_capacity_qualification`
tests Cohere at Yap's actual 8-running + 8-queued batch-pool owner, including
the aggregate four-hour PCM reservation, while testing NeMo's distinct
authenticated eight-active service boundary and typed 429. vLLM's
`--max-num-seqs 8` is a scheduler limit that can queue work, not a Yap 429
contract. `provider_fixed_auto_contract_qualification` runs the same locked
30-second source through fixed and automatic NeMo routes at c1 and c8 and
requires both deliberately different language-evidence shapes to conform to
their identity-rich contracts. It records lexical and exact rendered-text
parity without promoting either: automatic segmentation may legitimately alter
wording, casing, or punctuation, and Phase 8 owns provider-quality comparison.
Exact-track load cells report lexical and rendered identities per audio
duration. Provider-behavior promotion scope requires one non-empty lexical
identity; request/resource lifecycle scopes retain the observations without
promoting them. Representative quality scoring still evaluates punctuation
against adjudicated references.
All three commands use the same private-cache, clean checked-head/input
read-back, and aggregate-evidence rules as the standard runner. Their existence
does not consume the frozen checked-head gate.

`resident_provider_resource_sampler` resolves only a checked-head, non-root,
Yap-owned vLLM or NeMo container and writes private 250-ms cgroup-v2 and
entrypoint observations until explicit workload-start, workload-end, and stop
markers close the interval. `provider_resource_observations` then validates and
summarizes current/peak/composition, memory events, CPU/task counts, and the
container entrypoint's RSS/thread/virtual-data extent without publishing content
or paths. NeMo response aggregates also retain CUDA allocated/reserved counters.
Runtime-plan schema 5 contains
separate predeclared c8/1,600 GB10 profiles; qualification requires current and
peak ceilings, a sufficiently long sampled tail, zero memory-event increments,
bounded tasks/threads, and no more than 64 MiB absolute tail-window growth in
entrypoint virtual allocation extent. Cgroup RSS regression/range stays visible
because unified-memory residency may oscillate, but it is not mislabeled as
  growing live state. Both current-source profiles pass the executable eleven-
  check contract and clean teardown. Exact-head lifecycle results and their
  current disposition are recorded in `docs/CURRENT-STATUS.md`; profile evidence
  alone is not provider-promotion evidence. The command requires the checked
  head, repository root, and provider-serving lock and performs the same pre/post
  candidate read-back before publishing its aggregate. Raw JSONL and sampler
  control files must remain beneath the private `YAP_EVAL_CACHE`; they are never
  a repository artifact.

`resident-provider-lifecycle-gate.sh` is the checked GB10 composition for these
provider-owned cells. It requires one clean full SHA, a dedicated private cache,
the provider duration suite plus its separately supplied digest, two already
verified model directories, two already-prepared exact-head ARM64 images with
frozen private preparation-receipt hashes, and separate in-memory API keys. It
verifies those receipts and exact image IDs by inspection, binds them into
lifecycle evidence, and launches them sequentially on a temporary internal
Docker bridge, verifies no
Docker-published port and blocked container egress, owns each loopback proxy,
retries only typed transient startup unavailability, and fails immediately on
wrong auth, runtime, or model identity. The wrapper runs the exact duration, standard,
specialized, and c8/1,600 resource cells, then publishes an aggregate only when
every child is complete and no provider container, launcher, listener, or
  network remains. Focused tests establish the composition contract; exact-head
  admitted results are recorded in `docs/CURRENT-STATUS.md`. The wrapper does
  not by itself satisfy representative quality, provider promotion, or the
  complete phase matrix. See the server-node runbook for the exact private
  invocation and evidence boundary.

Container cgroup samples deliberately measure the provider container, not the
small host proxy process group. API wall latency includes the loopback proxy;
whole-host CPU/RAM capacity and persistent supervision remain Phase 10 evidence.

The Windows desktop reaches this historical Phase 5 profile only through an
explicitly started SSH local forward to `127.0.0.1:18765`. Its gate created no
TLS endpoint, firewall opening, DNS, ZPA publication, service unit, automatic
alias failover, authenticated owner, or WSS/live transport. See the
[server-node runbook](../docs/runbooks/yap-server-node-setup.md#loopback-batch-development-profile).
Use its two foreground launchers rather than reconstructing either environment
ad hoc. The merged Phase 7 identity and live-admission boundary is described
separately below.

This path passed the one-time Phase 5 local/native/server/GB10 gate on exact PR
head `4771d9be60562fa009ccecbcd3c7111b699883a5` and merged as
`b6677631b2cc8283f0f6466622f2dfa7cfdb38f6`. It remains a loopback development
profile, not an authenticated, externally published, persistent production
service.

## Phase 6 verified ASR catalog (merged baseline)

An active batch runtime now verifies `asr-capabilities.lock.json` only after its
immutable model artifacts pass their existing size and SHA-256 checks. It then
serves the joined, fingerprinted catalog at `GET /v1/asr/capabilities`. The
health-only profile returns `501`; it never advertises a catalog without a
verified runtime. `YAP_ASR_CAPABILITY_LOCK` may override the lock path for a
reviewed deployment, but the same regular-file, schema, model-pool, provenance,
evidence-revision, and 256-KiB output bounds still apply.

The current lock intentionally advertises only the already gated Cohere
`en-US` fixed-batch route. Research candidates and model-card language lists do
not become executable availability. Primary-language persistence, local and
server language-span contracts, advisory VAD, guarded LID paths, Nemotron fixed/
automatic reference routes, Cohere alignment, and the Cohere vLLM adapter/image/
launcher contract plus resident NeMo worker/service/image/launcher now have
focused implementation evidence, but none expands this catalog. NeMo remains a
separately gated server-streaming candidate and is not client-facing live.
Focused GB10 resident-service probes preserved Cohere's exact Transformers
reference hash through independent c2/c4/c8 requests and observed vLLM engine
abort after explicit client socket shutdown; NeMo separately formed one batch of
eight fixed/automatic requests. Both recovered and tore down, but neither result
consumes its frozen promotion gate or establishes production capacity.
The desktop automatic local route exists only as explicit default-off Preview
behavior and does not expand this server catalog. Additional server locales,
timing guarantees, and serving candidates remain unavailable until their exact
runtime artifacts and promotion evidence pass.

## Tiron whole-meeting candidate

The meeting candidate uses the pinned upstream `TrelisResearch/tiron` harness,
not a standalone Transformers decode. Tiron owns constrained decoding, the
default staggered second pass, and anonymous labels inside each source-bounded
30-second epoch. Yap uses the same already-loaded ECAPA encoder to reconcile
only unambiguous anonymous voices across epochs. Yap also owns verified artifact
paths, offline container execution, bounded admission and cancellation,
authenticated job ownership, source identity, result validation, and
publication. There is no second ASR-plus-diarization product route.

The foreground development launcher selects this profile only when the Tiron
settings are explicit. Set `YAP_TIRON_MODEL_DIR`, `YAP_TIRON_ECAPA_DIR`, and
`YAP_TIRON_WORKER_IMAGE` together. The runtime lock defaults to
`meeting-transcription-runtime.lock.json`, and the preview catalog defaults to
`tiron-candidate-asr-capabilities.lock.json`. Do not set `YAP_ASR_MODEL_DIR`,
`YAP_ASR_MODEL_LOCK`, or either Nemotron model setting in the same process; the
launcher and runtime reject that ambiguous composition. The committed default
catalog remains Cohere-only, so exercising this candidate does not promote or
advertise Tiron in ordinary startup.

The candidate publishes two owner-scoped immutable artifacts: the existing
transcript result and a companion anonymous-speaker result. The server writes
the speaker result first and the transcript last as the aggregate commit
marker. Restart recovery rejects incomplete aggregates. The native client
validates both against the original capture request before atomically
publishing them under the existing remote-result directory.

The product calls Tiron on exact source-time epochs so window-local labels are
available before the public aggregate discards them. Tiron's eight-slot decode
boundary is distinct from Yap's 32-speaker session target and 64-speaker safety
ceiling. An epoch exposing all eight slots produces a source-bound
`decode_window` capacity record; reaching the session ceiling produces a
meeting-scoped record. Either makes the immutable result terminal `partial`.
Ambiguous cross-epoch evidence is never forced, and no fallback pipeline runs
automatically. The retained source remains available to a later reviewed model
revision.

## Phase 7 identity and private live admission

The current server implements provider-neutral OIDC discovery and JWKS
retrieval, fixed signing-policy validation, bounded key refresh, and
Entra-specific issuer, tenant, audience, client, scope, and role policy. The
identity repository owns durable access state, purpose grant/revoke/enforcement,
tenant-specific principals, and a redacted hash-chain audit. Protected REST
routes and private live WebSocket admission use the same authenticated
principal, and the live boundary rechecks revocation.

The desktop has a narrow native access-token-provider interface with fake
providers for focused tests and an inbox WAM adapter behind explicit opt-in.
Release/default operation selects no production provider and fails closed; no
MSAL.NET, system-browser adapter, or separately managed protected production
token cache is shipped. The approved provider, tenant enrollment, and
real-provider conformance remain IT handoff inputs.

The executable private topology still uses separate loopback listeners: REST on
`127.0.0.1:18765` and the auth-only live listener on `127.0.0.1:18766`. The
desktop does not infer or discover the live origin from the REST origin. The
fixed-loopback HTTP health offer is not live discovery; no production
same-origin HTTPS/WSS edge or managed/live discovery mechanism exists, and this
admission boundary does not promote a server live-ASR provider.

The mock issuer image is digest-pinned in
[`verification/mock-oidc-provider.lock.json`](../verification/mock-oidc-provider.lock.json),
and
[`verification/test-mock-oidc-owner-flow.ps1`](../verification/test-mock-oidc-owner-flow.ps1)
owns the bounded Docker owner flow and public-safe receipt. Exact
application/runtime candidate `dc635916...` passed the private Phase 7 matrix;
PR #69 merged as `66d314d7`, and the separate adversarial checkpoint plus
concrete follow-ups are closed. Its final hosted head is not relabeled as an
all-green rollup, and none of this evidence proves real-tenant conformance.

See the
[Entra identity conformance handoff](../docs/runbooks/entra-identity-conformance-handoff.md)
for enterprise inputs and the
[integrated identity and access gate](../docs/runbooks/integrated-identity-access-gate.md)
for candidate and hosted closure.

## Governed knowledge candidate and complete gate

The active Phase 9 candidate compiles reviewed sources into deterministic Google
OKF concepts and immutable terminology snapshots, stages atomic
Postgres/pgvector generations, filters retrieval through server-derived
principal/purpose/generation authority, and exposes the same bounded cited
answer/proposal tools to the governed agent and MCP adapters. Postgres/pgvector
is the only current projection. Redis, object storage, Neo4j, production
supervision, and enterprise deployment are not implicit dependencies.

The complete gate must run once from a clean Linux/ARM64 candidate with the
already-qualified private Qwen/Gemma tree available outside Git:

```bash
umask 077
uv run --locked python -m yap_server.evaluation.governed_knowledge_gate \
  --repository-root /absolute/path/to/clean/yap \
  --checked-head <full-lowercase-git-sha> \
  --agent-route-evidence-root /absolute/private/agent-model \
  --receipt-path /absolute/private/governed-knowledge-gate.json
```

The command admits the exact hash-locked private model evidence without copying
raw outputs or measurements, runs the locked Python 3.12 Phase 9 portable suite
and server-wide Ruff, launches the immutable ARM64 Postgres/pgvector image on a fresh owned
bridge, requires that container to attach only to that bridge with an exact
loopback-only host port, requires every mandatory database test with zero skips,
restarts the actual database process, verifies cited retrieval
and stale-generation rejection after recovery, and proves container, listener,
PID, network, and volume teardown. The destination receipt must be new and
outside the repository. It contains only checked identities and public-safe
counts/booleans; never commit the private evidence tree, DSN, password, model
output, or database content.

## Local checks

```powershell
$env:PYTHONPATH = (Resolve-Path "server/src").Path
uv run --isolated --no-project --python 3.12 --with pytest pytest server/tests
```

Run only the wire-contract tests while editing the JSON documents:

```powershell
$env:PYTHONPATH = (Resolve-Path "server/src").Path
uv run --isolated --no-project --python 3.12 --with pytest pytest server/tests/contract/test_contract.py
```

The clean-head GB10 gate is run from the private node, not from normal local or
hosted CI:

```bash
umask 077
export YAP_GB10_ASR_PREPARATION_RECEIPT=/path/to/private/runtime-preparation/reference-<full-git-sha>.json
PYTHONPATH="$PWD/server/src" \
  python3.12 -m yap_server.pools.checked_runtime_image \
    prepare reference-batch-asr <full-git-sha> \
    >"$YAP_GB10_ASR_PREPARATION_RECEIPT"
export YAP_GB10_ASR_PREPARATION_RECEIPT_SHA256="$(
  sha256sum "$YAP_GB10_ASR_PREPARATION_RECEIPT" | awk '{print $1}'
)"
# Remove any temporary build proxy and restore the qualified network boundary.
YAP_CHECKED_HEAD=<full-git-sha> \
YAP_GB10_ASR_MODEL_DIR=<private-model-directory> \
YAP_GB10_ASR_EVIDENCE_DIR=<private-evidence-directory> \
bash infra/yap-server-node/gb10-asr-runtime-gate.sh
```

Preparation happens before gate admission and emits a private receipt only
after a second clean-head check. The gate verifies that receipt's frozen hash,
rejects any different image ID, and runs the receipt-bound immutable image as a
transient container only; it cannot build or pull.
It does not install a service, publish a port, or change the host firewall. Raw
host snapshots exist only in its temporary directory; final evidence stores
hashes and observed facts, not listener or firewall details. Its checked-head
evidence directory must be new and is never overwritten or silently reused.

## Run the Phase 3 health service

The service uses Python's bounded, single-request-at-a-time `HTTPServer` and has
no runtime dependencies. It binds to loopback by default:

```powershell
$env:PYTHONPATH = "server/src"
python -m yap_server
Invoke-RestMethod http://127.0.0.1:18765/v1/health
```

`YAP_SERVER_HOST` and `YAP_SERVER_PORT` override the address, but the
application service accepts only a numeric loopback host. The retired
`YAP_SERVER_ALLOW_PRIVATE_BIND` variable does not relax that rule. Use SSH
local forwarding for development or place an approved secure edge in front of
the loopback application service; the process does not change firewall rules.

In the default Phase 3 profile, only `GET /v1/health` is implemented. Job,
chunk, commit, and the REST `/v1/live` route return a stable
`501 NOT_IMPLEMENTED` JSON error; enabling the Linux-only Phase 5 profile
activates the documented batch routes but not live transport. The Phase 7
authenticated profile starts its private live WebSocket listener separately on
`YAP_SERVER_LIVE_PORT` (default `18766`); it does not make the REST route a live
upgrade endpoint. Request bodies are
capped at 1 MiB before any body read. Each accepted request has a two-second
wall-clock deadline, so slow-drip input cannot extend the single-request server
indefinitely. The service accepts HTTP/1.0 and HTTP/1.1 only.

Skipped for now: Nx/Turborepo, package workspace wiring, framework/server
dependencies, checked-in model weights, persistent worker deployment, and fake
GB300 profiles.

Python 3.12 server development uses the locked `uv` environment. Run
`uv run --locked ruff check .` from `server/` before focused tests. Ruff's
formatter is available for deliberate mechanical formatting work, but the
checkpoint does not mass-format the established server tree inside a behavioral
change.
