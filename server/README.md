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

## Governed knowledge runtime and complete gate

The merged Phase 9 runtime compiles reviewed sources into deterministic Google
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
uv run --locked --all-extras python -m yap_server.evaluation.governed_knowledge_gate \
  --repository-root /absolute/path/to/clean/yap \
  --checked-head <full-lowercase-git-sha> \
  --agent-route-evidence-root /absolute/private/agent-model \
  --receipt-path /absolute/private/governed-knowledge-gate.json
```

`--all-extras` materializes the locked evaluation and test packages before the
gate-owned runtime-identity check; omitting it on a clean host fails closed.

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

Exact candidate `a4f34678ea9980379b18266d40d3347b818ac57e` consumed this gate and
returned `governed-knowledge-gate-passed` with public-safe evidence SHA-256
`4013903410e22206c5b46f4dfcbf1878badc3dc9bbdfddb0ddad2ba0e2ff3260`.
It ran 109 portable tests across 22 modules, Ruff, nine mandatory Postgres tests
across four modules with zero skips on locked PostgreSQL 17 / pgvector 0.8.6,
and the real restart/recovery/stale-
generation/successor path, then proved exact teardown and zero owned residue.
Exact hosted-green head `fa26caaf7e3ea4e20f27b390355dff80bee2464f`
merged through PR #152 as `ae81ff067c73a64528eecc14403765562726f2fe`.
These facts do not promote a production agent service, simultaneous model
residency, or sustained mixed-route capacity.

The completed maintainability checkpoint did not reuse that historical route
tree. Reviewed executable head
`a76ed9b095ebb797064a12e9ebd90d2dd9d87bef` freezes acceptance schema 4,
exactly two evaluation-only final structural-decoding attempts, one exact
product-valid cited-proposal tool call, and candidate-specific runtime
identities. Qwen uses a pinned NVIDIA vLLM 26.07 ARM64 base plus XGrammar 0.2.1
overlay with strict tool guidance; Gemma uses exact upstream NVIDIA vLLM 26.06
ARM64. Qwen keeps its 256-token route maximum, caps only the three frozen
proposal fixtures at 160, and applies separate three-second common and
ten-second proposal qualification bounds; Gemma remains 512. Correctness,
warm/C8, model, route, runtime, and no-tool-retry contracts are unchanged.
Candidate lock SHA-256 is
`3e9218c8245863c5f1bda8166a629361b51ed23cec259d7c69f11b1dee83d013`;
acceptance SHA-256 is
`d2b422afa2da8c36da1920b0c32da9c5425f4b73718b55b0bf8cb136d3d7a773`.
The Qwen Dockerfile, build script, third-party notice, dependency identities,
platform, and exact observed image are protected qualification inputs; this is
a pinned evaluation build contract, not a byte-identical rebuild claim.
Prepare that exact local evaluation image from `server` with:

```bash
bash runtime/agent-vllm/build-qwen-vllm-runtime.sh
```

The build is source- and input-pinned, performs no registry pull, and must be
read back against the candidate lock before use. A qualification receipt binds
the observed image ID; rebuilding does not authorize substituting a new ID.
The exact `96897d2f...` private qualification is terminal and rejected with
public-safe evidence SHA-256
`929dd2a329387e0647db49699b0653862668f8f6b4588a4bf3ee9818ba656b75`.
Gemma remained eligible and Qwen passed its semantic, common, warm, and C8
checks, but the obsolete aggregate fixture bound rejected the proposal
workflow. Raw output, measurements, logs, and private locations remain outside
Git. The new split bounds are frozen route-evaluation controls, not production
p95/p99 SLO, capacity, or generic TPS evidence.
Fresh exact-head qualification at `a76ed9b0...` returned
`required-workload-routes-qualified` with public-safe evidence SHA-256
`4662a2784510e63da98dcd301ea05ef107196ce46b49d68ad812abdc042d00f0`.
Both locked candidates were eligible and passed their semantic and
route-specific evidence contracts; both lifecycles reported exact teardown and
zero owned runtime residue. Schema-3 public lock commit `2cf1e92c...` has
raw-file SHA-256
`b8d05f9645f37c36e0be5b480cf95c5e29b31945b4e56f879c95eeb72979a1b9`
and passed hash-bound semantic admission against the owner-private tree. Raw
outputs, measurements, logs, private locations, and runtime credentials remain
outside Git. Exact aggregate candidate
`22c3f3698a6b5c5ff592e74f3a0f0e144778c9c5` returned
`governed-knowledge-gate-passed` with public-safe evidence SHA-256
`8c2bfdef6b596094fe113a12b1bbfccec94ddeb3944e1b3313f41b61d5df12b0`.
It ran 152 portable tests across 25 modules, Ruff, 17 zero-skip Postgres tests
across four modules on locked PostgreSQL 17 / pgvector 0.8.6 ARM64, and the
real restart/recovered-retrieval/stale-generation/successor path. The receipt
records the unchanged desktop dependency boundary and all six teardown
predicates; independent name/owner read-back found zero container, network, or
volume residue. This remains checkpoint evidence, not a production p95/p99
SLO, capacity, or generic TPS claim. Final hosted head
`84c22ec9935af824ca1b47d046e18003ec2c7883` passed every required CI and
CodeQL lane and merged through PR #153 as
`ca151b1b45be3b98e4c56c6ea2b89446eeaa8814`.

## Phase 10 supervised-provider lifecycle baseline

`orchestrator/` now owns the hardware-independent first production-lifecycle
layer defined by ADR 0030. One `yap-provider-supervisor` process accepts one
explicit workload route, one numeric-loopback endpoint, one exact served-model
identity, one private state destination, and one absolute canonical foreground
launcher. It never selects a fallback route or calls Docker. The existing
launcher remains the sole container/private-proxy/image/teardown owner.

The supervisor publishes typed lifecycle state, requires `/health` plus an
exact single-model `/v1/models` response, bounds child restarts to the fixed
three-in-60-second policy, and does not report a clean stop until the complete
owned launcher process group is absent. The test-only provider fixture is
feature-gated out of default builds. A rendered hardened systemd template owns
the outer cgroup and only
restarts abnormal supervisor crashes; it does not duplicate Rust's child
restart policy.

Exact hosted-green head `1a487db840578d8e415fd2e5a51b1909af4b7041`
passed the dedicated Linux lifecycle lane, every required repository CI and
CodeQL lane, and the native WDIO smoke. PR #155 merged Slice 10.1 as
`e2d82b89532addb26fda73f652ae4f68b2127ef7`.

Merged Slice 10.2 binds the exact Qwen rapid and Gemma complex profiles to separate
supervised instances. Exact lifecycle head
`4b103c1bd8b393b7cabf6d219071fa8ba37bda09` passed sequential
start/readiness/restart/stop and exact teardown for both routes with public-safe
evidence SHA-256
`9b6a34f6d4f099123894212bbabda79463b73c1a954bbd04a71a7dfb1d88f27d`.
Exact private qualification head
`4d6232123520dd85202f7095c156c766c7dd2ee0` returned
`required-workload-routes-qualified` with public-safe evidence SHA-256
`4a856f3e4fcdb3ed8bb79310646cbd8df5c12533ce91f5049190daa7379ca8d8`;
public-lock successor `0471b158ac34f97c0f2be7323433470fe5de7fa4`
then returned `governed-knowledge-gate-passed` with public-safe evidence SHA-256
`008d748bfe88b5eb68b2c8abbecd682e0a4aceb6634872ead077e0993a2455b2`.
The aggregate ran 157 portable tests across 26 modules, Ruff, and 17 zero-skip
Postgres tests across four modules, then proved restart/retrieval and exact
teardown. Hosted-green head `6d1400ccdf481333840700b51f516c813960272b`
merged through PR #157 as `cac8989b762ada02d6196aad6bbcbc37f2d1a339`.

The intended multi-user topology keeps both exact route services warm behind
bounded fair admission; requests never cold-start or swap models. Exact
protected head `7bd93dc624e6d8651dffc710026ca144909b2399` adds the
Rust admission broker and strict Python adapter for the complete eight-role
map. It conservatively permits one active request per route, bounds pending and
per-owner work, schedules owners fairly across typed priorities, includes queue
time in deadlines, requires cancellation acknowledgement before releasing
capacity, and fails work on provider-generation changes without substituting a
route. Its owner-private Unix socket carries no bearer or provider credential.

The broker is installed without enable/start, never starts provider units, and
deliberately uses `Restart=no`: after losing in-memory lease state, an operator
must first contain any external workers before starting a new scheduler. No
service is enabled by installation. Hosted-green head `cf1e69a4...` passed all
12 required checks and PR #158 merged the bounded admission slice as
`84d95842...`.
Replacement private qualification admitted both routes with public-safe
evidence SHA-256
`a75500c344eaa7546695ab1e7415466c031ccf394620ed442ca618ea1ede8c06`.
Public-lock/aggregate head `135cc2ba...` then passed semantic admission, 169
portable tests across 28 modules, Ruff, 17 zero-skip Postgres tests across four
modules, real restart/retrieval/stale/successor checks, unchanged desktop
dependency scope, and exact teardown with public-safe evidence SHA-256
`350c13a5569cfc7237174d1f7e2132857ffb3aaf28b6afd2eca03aa1999aea79`.
This evidence does not prove simultaneous residency, sustained
capacity/fairness, production p95/p99, or deployment. Build, installation,
configuration, state, and verification details are in the
[provider supervisor runbook](../docs/runbooks/provider-supervisor-service.md)
and [agent admission runbook](../docs/runbooks/agent-admission-service.md).

The current protected profile-capacity successor derives active route limits
from the immutable service profiles: four rapid and eight complex, with Server
IO remaining one and one active request per owner remaining global. Exact route
head `dab19fe...` returned `required-workload-routes-qualified` with public-safe
evidence SHA-256 `96228914...`; Qwen and Gemma were admitted sequentially on
their unchanged full profiles and completed exact teardown. Exact workflow head
`7cd24deb...` qualified Scribe, Student, and Curator, including rapid-four/
fifth-queued and complex-eight/ninth-queued live broker probes. Replacement
public-lock/aggregate head `7f896b34...` returned
`governed-knowledge-gate-passed` with public-safe evidence SHA-256
`fd197b98...`. The exact one-slot evidence above remains historical authority
for its merged head, not the current boundary. Hosted-green head `593e627b...`
passed all 12 checks, and PR #168 merged the successor as `284ab96b...`.
Selected-route limits do not prove simultaneous Qwen/Gemma residency, sustained
capacity/fairness, production p95/p99, or deployment. See the
[profile-capacity record](../docs/evidence/agent-admission-profile-capacity/VERIFICATION.md).

The next protected successor changes the complex runtime/profile rather than
reusing that receipt. Exact executable `0665c486...` passed sequential lifecycle
evidence SHA-256 `7cc016f4...` and `required-workload-routes-qualified` evidence
SHA-256 `06277bd9...`; lock-only `8fee7a5c...` publishes the matching route lock.
The full complex profile is batch invariant with seed `0` and prefix caching
disabled. It retains c8, 8,192 maximum batched tokens, and `0.70` GPU-memory
utilization. The live probe held eight owners and queued the ninth without
changing the provider/broker identity. Affected workflow and aggregate gates
received fresh exact-head evidence; older merged receipts are not relabeled.

## Scribe transcript correction

The first merged product consumer of the broker is the authenticated
asynchronous Scribe route:

- `POST /v1/transcript-corrections` admits one bounded correction and returns
  `202` with its typed queued/running/terminal projection.
- `GET /v1/transcript-corrections/{requestId}` reads only the authenticated
  owner-scoped projection.
- `DELETE /v1/transcript-corrections/{requestId}` requests token-bound
  cancellation and does not release scheduler capacity before acknowledgement.

The request contains only finalized ordered segments with immutable source,
revision, segment, timing, and language identity. Python binds one authorized
terminology snapshot and submits Scribe HOT work to the already-warm rapid route;
it never starts, swaps, or falls back to another model. Structured edits are
rejected unless they preserve coverage, order, timing, names, numbers, dates,
units, medication-like terms, negation, and unsupported-content boundaries. A
valid no-op, uncertainty, invalid output, overload, unavailable provider,
deadline, and cancellation are distinct outcomes.

Native code owns trusted source reads and user-accepted publication. It re-reads
the source before publication and writes a separate hash-chained correction
revision only after the user reviews the raw/corrected diff. Raw ASR remains
authoritative and exportable. The renderer receives no bearer and cannot call a
provider directly. The removed Ollama Polish implementation is not a fallback.

The exact candidate passes 1,198 portable server tests with 30 declared
platform skips, Ruff, 367 desktop unit tests, production build, 41 browser
scenarios, and both Rust workspaces with strict lint. Its private qualification
is deliberately separate: 24 bilingual/safety cases, eight distinct owners,
real-ASR source evidence, one warm rapid-provider generation, correction
benefit, zero protected-fact regression/invention/deletion, bounded fallback,
queue-inclusive latency, and exact teardown. No private corpus, output,
measurement, credential, or filesystem path belongs in Git or hosted logs.

Exact candidate `a53333a577534148b11a49f6f8625ce4ac9b2d00` returned terminal
`deterministic-no-scribe` evidence SHA-256
`80718c6c8ad2fedd6bec5300c99a2a0af8ae71473c2457313a79b9138f5d8415`.
The warm, broker, eight-owner, terminal, and teardown boundaries passed, but
every model response was rejected because the response contract required a
request digest that was not supplied as an exact trusted binding. The repaired
candidate places the server-computed request and source hashes into the strict
JSON schema as constants; validation still rechecks them and no failed evidence
is reused.

Exact binding-repair head `b89fd9f118b881d107cc2025b9b8a41e51b9db37`
returned a second terminal `deterministic-no-scribe` decision with public-safe
evidence SHA-256
`0c37120a03d3bcd7434c908ca24a086ccf785678b7c5e9ec49ec6fc051f81c74`.
Valid unchanged responses began passing, while edited responses reached the
Scribe workload's 256-token ceiling before completing their structured JSON.
Exact successor `21559371db2a869e2c8b7ae3cd589f80c189d0cd` raised only the
Scribe response allowance to 512 tokens and returned terminal
`deterministic-no-scribe`, with public-safe evidence SHA-256
`a103144c66940ff55d8390c227bc73e6379cbfa6f73a199a9818839adaf48e2b`.
The 24 cases, eight owners, 16 unique real-audio inputs, warm generation, broker,
latency, preservation/no-regression, and exact database/runtime teardown checks
held. Completed edited JSON showed that model-authored character offsets did not
consistently bind the quoted source. Response schema 2 therefore removes those
offsets from model authority: the model quotes an exact source substring, and
the server derives its Unicode span only when that quote occurs exactly once in
the bound segment. Missing or repeated text fails closed. Model residency,
broker fairness, the 512-token allowance, no-tool-retry behavior,
timeout/deadline, validation, and quality thresholds were unchanged. A complete
fresh qualification was required at that point.

Exact schema-v2 head `cbd7335a26bd7700106b331827756af19c34e38a`
subsequently passed public verification. A bounded private smoke proved that
response decoding, exact request/segment/source binding, server-derived spans,
and bounded-edit checks now pass, and every run proved exact provider, broker,
database, listener, process, and network cleanup. A real case selected from the
prior invalid-output set then attempted an unauthorized name change that was
neither approved terminology nor present in the frozen reference; a safety
response also varied across repeated cold diagnostics. The protected-fact guard
correctly rejected the name change. Exact prompt-grounding head
`e62d33e41d2d85154a07da1d7a1254ea642a5638` retained safety and exact teardown
but repeated that unsafe edit, proving prompt compliance alone insufficient.
Exact private-use masking head
`b80fe0b46c8a511b93dd2c85f8ed053d24648663` retained exact teardown but returned
an invalid real replacement and missed the safety disposition. Visible-block
head `5bc8d10e8a3059941b00fa662dc2a4fbbff816a6` also contained exactly but returned
malformed JSON and missed both bounded dispositions. The next protected
successor used an ASCII equal-length redaction block. Exact head
`7d546163dd08fd3cb6eafce91c64419c84df9f2d` returned valid structured output but
marked the representative correction uncertain and missed the safety probe's
required unchanged disposition; teardown remained exact. A later successor
at exact head `92554be304d5061c84ee04a7eeb9829829705102` fixed the safety
disposition but left the representative single-word ASR substitution unchanged;
teardown remained exact. Exact head `e3ab6b6af6c7757b987a6b8fcc4ef213c4706bc9`
explicitly permitted that correction but also returned it unchanged; safety and
teardown passed. The following successor stated that missing audio was expected and
used linguistic context for one contextually obvious nonprotected ASR word
substitution while treating
placeholders and instruction-like content as expected data and reserving
uncertainty for a possible error that cannot be expressed safely. Exact head
`af1f79a7cfff050a4b87c7499082551ba7dde9e6` retained safety and teardown;
its broader bounded diagnostic produced unchanged cases and one source-bound
edit rejected only because its quote included too much unchanged context. Exact
minimization head `6cf82239569760383dca88d0702d71b35f60e8ad` removed that
coverage failure, but its three-case diagnostic still applied no correction:
one proposal was outside the narrow lexical grammar and another's minimal quote
was repeated; safety and teardown passed. Historical exact head
`33d9b4d0362689a58be0c16bf26de88ac55d56b2` also applied no correction: two
representatives were unchanged and the third quote, minimized against masked
text, was ambiguous after raw protected values were restored. Safety and every
teardown predicate passed.

Exact source-lock head `e585842485a7cd38b2935cc8f79314b19b37f7fd`
then passed the complete private qualification gate with outcome
`scribe-transcript-correction-qualified` and public-safe semantic evidence
SHA-256
`5e187ed4f33e7a84c53824afb5a2af4b5ad0afcb3b7b7b36cb0b01692c74b3cb`.
Hosted-green head `bc9a88bc3d3ee3fd767dbfee1497b6bc61733ce6`
passed all 12 required checks and PR #164 merged the slice as
`ec3af506da68bbb7a0ce855369dd09c8a791742d`.
The untouched final corpus contained 24 terminal cases, 16 unique real-audio
inputs, eight owners, eight English and eight Spanish real-ASR cases, eight
safety cases, eight corrected references, eight source-preserved references,
six unchanged outcomes, and two uncertainty outcomes. All frozen benefit,
preservation, no-invention, insertion/deletion, critical-fact, fallback,
queue-inclusive p95, warm-generation, broker-identity, database, and teardown
checks passed. The executing correction authority is now exact
server-authorized terminology replacement plus separately validated bounded
model edits; protected facts remain immutable and uncertainty returns raw ASR.
The [public verification record](../docs/evidence/scribe-transcript-correction/VERIFICATION.md)
contains the exact hashes, counts, and limits. Hosted review and merge closed
through PR #164. This result does not prove simultaneous Qwen/Gemma residency, sustained
mixed-route capacity, production SLOs, or completion of the remaining role workflows.

## Student learning questions

The Student core is an internal `BACKGROUND_LLM` consumer of the already-warm
rapid route. Its runtime builder is enabled only in authenticated team mode;
each invocation receives one server-derived principal. The workflow reads one
owner-scoped, permission-safe admitted conversation generation, freezes its
exact evidence/citation tuples, and returns bounded source-supported learning
questions. Caller-authored source text, another owner's evidence, direct
knowledge mutation, proposal writes, and generation activation are rejected.

Student submits a bounded request through the same owner-fair broker. Its
queue-inclusive deadline is 60 seconds and its model output cap is 512 tokens.
It neither starts nor swaps a model. Student does not reduce the pinned full
Qwen rapid profile: GPU-memory utilization remains `0.40`, with four maximum
sequences and 8,192 maximum batched tokens. Invalid output, cancellation,
deadline, provider loss, cross-owner access, stale source identity, and audit
failure are terminal and publish no successful result.

The current repair replaces caller-controlled target-question text with a
bounded topic. The model sees only ordered evidence indexes and text and must
return exactly one source subject, one evidence index, and one exact support
quote. The server validates the index, binds the frozen evidence and complete
citation identity, derives the support span, and alone renders the fixed
learning-question template. The model cannot create citation identity, rewrite
the selected subject, or write question wording. The focused set is green at
34 total tests: 32 passed and two were declared database skips. The current
successor also passed the complete portable server suite at 1,241 total tests:
1,207 passed and 34 were declared skips. Exact head
`428d6e48690621cc2242944c049e06ccfd2e45e2` then returned
`student-learning-questions-qualified` with public-safe evidence SHA-256
`f597cca728d261caad66d6629332c76ffd900bc78f6be20aa7bb0c849275ebe8`.
All eight distinct owners completed with one grounded question each and zero
terminal failures. The full warm profile, provider generation, broker,
PostgreSQL restart/cross-owner/audit boundaries, and six-part teardown remained
exact. Hosted-green head `b03c6e79f19bad451437c3f0c495daa67bb7171f`
then passed all 12 required checks and PR #166 merged the internal core as
`2254605ed19a592d2db1747d576762ccf11a5cc0`. This proves the bounded
internal core, not product exposure or sustained capacity.

Exact head `0970d74c7961a63bd1b2366bc0ecef6b5fc55714` returned terminal
`deterministic-no-student` evidence with public-safe SHA-256
`316631d593e51477d855ed146e2a5bea49eec236b0753655bdd4814a20a0cb99`.
Seven of eight cases completed and one failed closed. The warm full profile,
broker/wave, PostgreSQL boundaries, and teardown held. A bounded diagnostic
showed a topic-derived subject absent from the selected exact quote/evidence;
the server rejected it. The prompt now explicitly forbids that promotion and
requires an exact contiguous subject-inside-quote-inside-evidence chain. No raw
response or measurement is published, and the receipt is not reused.

Exact head `476f7a9c38287f8c6ba08cd9be4a70addabe3069` returned terminal
`deterministic-no-student` evidence with public-safe SHA-256
`9c2f68ffe411d1333c6799158fa28db30ffa0ced6359eb9f291528ded4c0d0d4`.
Six of eight cases completed and two failed closed. The unchanged full warm
profile, provider generation, broker, synchronized eight-owner queue wave,
PostgreSQL restart, cross-owner and audit boundaries, and exact teardown held.
The receipt is inadmissible for the evidence-index successor and is not reused.

Exact head `452c8b76a9a60681a962048caed12749e8bb80d0` originally returned
`student-learning-questions-qualified` with public-safe SHA-256
`3e1ddc61bf0c8d009a25b06ef261f0b6f7dcd8d7c1f58eeb666ba31e98420c41`,
but post-gate adversarial review proved that it could publish an unsupported
question premise beside an unrelated exact citation. Its corpus also embedded
each target question in the caller-controlled focus. That receipt is terminal
and inadmissible even though its warm-provider, broker, PostgreSQL restart,
cross-owner, audit, and teardown observations remain historical facts.

Exact predecessor `ffe9088573a1a8453a3cb529f1fc62c8ef9d7dda` remains terminal
`deterministic-no-student` evidence with public-safe SHA-256
`bc65dd55dc3c751caa340312fc6435beba5ba0c0d7a2fa43e323297cadf32c3d`.
One case failed closed after altering a citation span. Neither historical run
is reused. The current repair changes no model, full profile, output cap, retry
behavior, queue bound, timeout, or acceptance threshold.

The [public verification record](../docs/evidence/student-learning/VERIFICATION.md)
contains the exact public-safe identities and limits. Student still has no HTTP
endpoint, native adapter, renderer/UI workflow, or production promotion. A
second owned GPU node/private route remains required before both
unchanged full Qwen and Gemma services can be kept warm together. Student does
not reduce the pinned full profile, and request-time model swapping remains
prohibited.

## Curator knowledge-proposal core

The merged server contains a privately qualified internal Curator core. It
accepts only an explicit proposal or reviewed Student answer, re-reads every
citation through the server's permission-safe generation owner, and asks the
already-warm complex route for one bounded propose/reject decision. A proposed
result may append only a noncanonical `KnowledgeProposal`; Curator cannot
compile, stage, activate, or otherwise mutate source truth or active knowledge.

Exact head `7cd24deb...` returned `curator-knowledge-proposals-qualified` with
public-safe evidence SHA-256 `b60df1e2...`: eight cases/eight owners, four
proposals, four rejections, zero terminal failures, complex capacity eight with
the ninth owner queued, unchanged warm/broker identities, exact PostgreSQL
lifecycle/read-back, and teardown. Candidate `7ba4e45c...` failed closed on the
empty forced-tool content envelope, wrote no Curator qualification receipt, and
established no admissible Curator success evidence; it remains terminal and no
teardown result is claimed for it. Invalid/stale evidence, model rejection,
cancellation, timeout, provider loss, capacity, or audit/write failure publishes
no successful proposal.

The [Curator verification record](../docs/evidence/curator-knowledge-proposals/VERIFICATION.md)
contains the public-safe exact-head result. Hosted-green head `593e627b...`
passed all 12 checks, and PR #168 merged the core as `284ab96b...`. HTTP,
native, renderer/UI, active-knowledge promotion, and production operation remain
open.

## Librarian permission-safe evidence core

The server contains a privately qualified, merged no-LLM Librarian internal
core. `LibrarianService` admits one authenticated interactive Server-IO
read, pins the permission-safe active generation, filters hidden nodes and links
before limiting, and returns a bounded evidence pack or typed terminal result.
It writes no proposal, activates no generation, and acquires no model lease.

Exact head `56b7f5d0...` returned
`librarian-permission-safe-evidence-qualified` with public-safe evidence
SHA-256 `def8e648...`. The actual eight-normal-owner broker wave, ten exact
invocations, Server-IO one-active/second-queued cancellation containment, two
PostgreSQL restart/read-backs, exact tool/result audits, zero proposals, and
six-part teardown passed. Exact predecessor `ecdcb8ee...` is terminal and
inadmissible because adversarial review found only seven broker submissions.
See the [Librarian verification record](../docs/evidence/librarian-permission-safe-evidence/VERIFICATION.md).
Hosted head `7505247e...` merged through PR #169 as `d7a7e003...`. HTTP/native/
renderer exposure, sustained capacity, and production operation remain pending.

## Analyst grounded cited-answer core

The server contains a privately qualified, merged internal Analyst core.
`AnalystService` asks Librarian for one permission-safe evidence pack,
reauthorizes the exact succeeded pack and current generation in PostgreSQL, and
uses the already-warm complex route only to select whole evidence-item indexes.
Server-owned code derives the bounded answer and citation identities. Empty or
unavailable evidence, stale generation, invalid output, cross-owner access,
replay conflict, cancellation, and deadline publish no answer.

Exact executable `0665c486...` returned
`analyst-grounded-cited-answers-qualified` with public-safe evidence SHA-256
`940fd7c6...`. Three synchronized repeat waves matched all 24 normal
invocations; all 29 terminals matched, and 12 answers contained 15 server-owned
citations. Exact database/audit read-back, zero proposals, warm provider/broker
identity, complex c8/ninth-queued containment, and teardown held. Lock-only
`8fee7a5c...` publishes the matching route lock.

Exact `63c3d9fd...` failed the official gate and emitted no receipt. Its later
same-head diagnostic replay was deliberately inadmissible; conflicting outcomes
under the earlier concurrent online runtime made both attempts terminal and
nonreusable. The replacement's three repeats prove only same-warm-process
repeatability, not cross-start/global determinism. See the
[Analyst verification record](../docs/evidence/analyst-grounded-cited-answers/VERIFICATION.md).
Hosted head `da1127f8...` passed all 12 checks, and PR #170 merged the core as
`52c45d22...`. HTTP/native/renderer/UI exposure, simultaneous residency,
sustained capacity, a production SLO, and deployment remain pending.

## Coordinator source-cited proposal-bundle core

The server also contains a privately qualified, merged internal Coordinator
core. `CoordinatorService` submits exactly one background complex-route
lease for an explicit authenticated request, reads only the caller's current
open Curator proposals, reauthorizes exact Curator lineage/current citations,
and lets Gemma select ordered proposal indexes only. Server-owned code derives
all selected content and citations into a noncanonical, review-required bundle.
Coordinator writes no proposal, plan, task, source, or active knowledge and
performs no autonomous action.

Exact executable `fed729b3...` returned
`coordinator-proposal-bundle-selection-qualified` with public-safe evidence
SHA-256 `1bce03b6...`. Three synchronized repeat waves matched all 24 normal
service calls; all 29 terminals matched, and 15 bundles contained 18 selected
items with 18 server-owned citations. One ticket per invocation, 28 submitted
leases, exact client/deadline cancellation identities, current Curator
lineage, database/audit read-back, two PostgreSQL restarts, complex c8/ninth-
queued containment, unchanged warm provider/broker identity, and teardown held.

Exact `11f325bb...` completed the workload but failed closed before receipt
publication because its verifier conflated the deadline-expired lease with an
ordinary client cancellation. It emitted no receipt, is terminal, and is not
reused; its owner-private harness teardown passed. See the
[Coordinator verification record](../docs/evidence/coordinator-proposal-bundles/VERIFICATION.md).
Hosted head `53ee0152...` passed all 12 checks, and PR #171 merged the core as
`67d836da...`. HTTP/native/renderer/UI exposure, autonomous action,
simultaneous residency, sustained capacity, a production SLO, and deployment
remain pending.

## Auditor source-cited review-findings core

The server also contains a privately qualified, unmerged internal Auditor
candidate. `AuditorService` submits exactly one idle-only complex-route lease
for an explicit authenticated request, reads only current owner-visible source
evidence, and lets Gemma select bounded evidence-index pairs only. Server-owned
code canonicalizes those pairs and derives potential-contradiction finding text
and exact citations into a noncanonical, review-required report. Auditor writes
no proposal, source, task, action, or active knowledge and performs no
autonomous mutation.

Exact executable `08b06f6d...` returned
`auditor-source-cited-review-findings-qualified` with public-safe evidence
SHA-256 `2c1dbc05...`. Three synchronized repeat waves matched all 24 normal
service calls; all 29 terminals matched, and 12 reports contained 15 findings
with 30 server-owned citations. One ticket per invocation, 28 submitted leases,
exact client/deadline cancellation identities, current source authority,
database/audit read-back, two PostgreSQL restarts, zero proposal writes,
complex c8/ninth-queued containment, unchanged warm provider/broker identity,
and teardown held.

The live idle-only probe observed both active and queued non-idle work blocking
Auditor admission, then observed admission resume after that work became
terminal. It did not cancel or preempt accepted non-idle work. See the
[Auditor verification record](../docs/evidence/auditor-source-cited-review-findings/VERIFICATION.md).
Hosted review/merge, scheduled autonomous execution, HTTP/native/renderer/UI
exposure, simultaneous residency, sustained capacity, a production SLO, and
deployment remain pending.

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
