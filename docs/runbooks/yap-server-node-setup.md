# Yap Server Node Setup Runbook

Yap's team profile treats an NVIDIA GB-class server node as a private server tier, not a public service. The desktop stays thin: local Nemotron INT8 is the live/offline fallback. Phase 3 provides health reachability and durable queued-job ownership. Phase 4 adds one transient, server-internal Cohere batch reference worker. The gated Phase 5 path sends imported recordings through the durable loopback batch contract. Phase 6 adds bounded Cohere vLLM and Nemotron NeMo resident candidates behind the same job/result authority; exact executable candidate `0ed2037dbbb8c3df9350dbc37aeddc633f567a40` passed their lifecycle boundary inside the complete Phase 6 matrix. Neither candidate is promoted. This remains a development profile, not a public or persistent production service.

The first supported node profile is DGX Spark GB10. A later GB300-class node should keep the same server contract and change only host-specific config: NIC names, CIDRs, GPU/runtime sizing, and deployment capacity.

## Security Shape

Keep three planes separate:

| Plane | Purpose | Exposure |
| --- | --- | --- |
| Management | SSH, recovery, tunnels | Private Ethernet for demos; corporate LAN/VPN later |
| App entrypoint | Current loopback HTTP batch; future `yap-server` WSS + HTTPS | SSH-forwarded loopback during Phase 5 development; one managed TLS endpoint later |
| Model/runtime internals | Ollama, VNC, dashboard, model pools, databases | Loopback, container network, or SSH tunnel only |

Default rule: a Yap application service is never exposed to the public internet.
Do not infer host isolation from the private cable: the current GB10 also has
Wi-Fi and overlay routes. Corporate access should mean approved LAN/VPN
reachability plus TLS plus auth, not open model ports.

## Current GB10 And Phase 3 Demo Mode

The 2026-07-12 read-only audit found:

- Windows laptop private IP: `192.168.50.63/24`
- Spark private IP: `192.168.50.1/24`
- Spark wired interface: `enP7s7`
- Spark default route: active Wi-Fi, with additional overlay interfaces
- SSH alias: `dgx-spark-eth`
- UFW: active, but effective rules require root to inspect
- External TCP: SSH only; dashboard, Ollama, and Twingate local services are
  loopback-only
- Tailscale: removed after the audit; Twingate/`sdwan0` remains active
- Time: not NTP-synchronized and about 18.6 seconds ahead of the Windows client

Do **not** rerun the baseline setup script on this prepared, multi-purpose host.
Its landing zone and SSH hardening already exist, and a rerun would perform
unnecessary package, firewall, logging, and service operations.

The current validated 2026-07-13 smoke used exact immutable release
`c3999b7b685dd668165d54b64d1af61e41adad05` transiently. Its deployment archive
SHA-256 is `be7f43d757821c3e74d0ae2809599f5a84b369115d24afce42fe6687b1bf12e1`.
It was stopped after validation; no persistent service remains. Any newer
executable SHA requires promotion and fresh GB10 evidence and must not inherit
this result.

Phase 3 uses a loopback-only health process on the GB10:

```bash
YAP_SERVER_HOST=127.0.0.1 \
YAP_SERVER_PORT=18765 \
PYTHONPATH=/srv/yap-server/releases/<git-sha>/server/src \
python3 -m yap_server
```

Forward that loopback port over the private SSH alias from Windows:

```powershell
ssh -o BatchMode=yes `
  -o ExitOnForwardFailure=yes `
  -o ServerAliveInterval=15 `
  -o ServerAliveCountMax=3 `
  -N -T `
  -L 127.0.0.1:18765:127.0.0.1:18765 `
  dgx-spark-eth
```

Point the desktop connector to `http://127.0.0.1:18765`. This opens no GB10
application port, needs no UFW change, and satisfies the connector's
loopback-only HTTP policy. The client must fail closed when the tunnel dies and
must never retry against the Wi-Fi address.

For an explicitly manual Wi-Fi rehearsal, substitute `dgx-spark-lan` only as
the SSH transport alias in the forwarding command. Keep both sides of the
forward and the desktop connector URL at `127.0.0.1:18765`. Do not put the
Wi-Fi/node address in app configuration, and do not add automatic alias or
network failover.

See the [GB10 readiness audit](../research/2026-07-12-gb10-readiness-audit.md)
for the evidence and remaining gates.

## Phase 4 Transient Batch-ASR Gate

Phase 4 does not open an application port or install a worker service. Before
admission, its runtime-image preparation creates one immutable ARM64 image from
the digest-pinned `nvcr.io/nvidia/pytorch:26.06-py3` base with Python 3.12. The
gate itself only verifies that already-prepared image, runs one licensed fixture
through the bounded router and batch pool, writes result/evidence JSON, and
removes the job container. The model remains the locked canonical Cohere
Transcribe revision even though its public byte distribution avoids putting
model credentials on the node.

Run the final gate only from a clean checkout at the exact candidate SHA:

```bash
cd /path/to/clean/yap-candidate
export YAP_CHECKED_HEAD="$(git rev-parse HEAD)"
export YAP_GB10_ASR_MODEL_DIR=/path/to/private/cohere-transcribe-03-2026
export YAP_GB10_ASR_EVIDENCE_DIR=/path/to/private/gb10-asr-runtime-evidence/$YAP_CHECKED_HEAD
umask 077
export YAP_GB10_ASR_PREPARATION_RECEIPT=/path/to/private/runtime-preparation/reference-$YAP_CHECKED_HEAD.json
PYTHONPATH="$PWD/server/src" \
  python3.12 -m yap_server.pools.checked_runtime_image \
    prepare reference-batch-asr "$YAP_CHECKED_HEAD" \
    >"$YAP_GB10_ASR_PREPARATION_RECEIPT"
export YAP_GB10_ASR_PREPARATION_RECEIPT_SHA256="$(
  sha256sum "$YAP_GB10_ASR_PREPARATION_RECEIPT" | awk '{print $1}'
)"
# Remove any temporary build proxy and restore the qualified network boundary.
bash infra/yap-server-node/gb10-asr-runtime-gate.sh
```

`YAP_GB10_ASR_EVIDENCE_DIR` is a one-shot checked-head destination and must not
exist before the run. The finalizer creates it only after host-boundary
verification and refuses to replace an existing directory or evidence file.
Keep failed or completed directories for audit; remove one only through an
explicitly reviewed rerun decision.

The invoking POSIX identity must be non-root and must be able to read every
locked model file. The host adapter passes that exact UID/GID into the worker.
The gate prefers non-interactive read-only `sudo` access to the active host
firewall status command (`ufw`, `nft`, or `iptables-save`). On the current UFW
node, if that narrow access is unavailable, it compares non-root-readable UFW
configuration metadata and the UFW unit state instead. That fallback proves
the gate did not persist a UFW policy change; it does not replace the explicit
root-level effective-rule review required before any persistent or exposed
deployment.
The worker has no network, a read-only root filesystem, dropped capabilities,
`no-new-privileges`, read-only model/audio mounts, a non-executable general
`/tmp`, and a private mode-0700 executable tmpfs used only for bounded PyTorch
compiler artifacts. Do not loosen the entire root filesystem or expose a model
port to work around compiler-cache requirements.

The gate verifies:

- the full model and fixture SHA-256 set;
- the image's ARM64 architecture and exact checked-head revision label, then
  execution by the inspected raw image ID rather than the mutable build tag;
- router-to-pool dispatch and bounded one-worker execution;
- the 96 GiB memory/no-swap, 16-CPU, PID, temporary-storage, and one-MiB
  per-output-stream ceilings;
- Python, Torch, CUDA, overlay-package, model, language, and punctuation
  identities returned by the isolated process;
- the worker result's exact input SHA-256, 16 kHz sample rate, and positive
  duration before host publication;
- exact `NVIDIA GB10`, compute capability 12.1, CUDA/BF16 execution, and fixture
  WER no greater than `0.12`;
- a unique named worker container is force-removed even when the Docker client
  times out or exceeds its output bound;
- before/after listener, firewall, and Yap service-unit snapshots match and no
  Phase 4 container or worker process remains before atomic result/evidence
  publication. Raw host snapshots are deleted with the temporary gate
  directory; final evidence contains only their hashes, observation method,
  and observed facts. Missing firewall observation tooling fails closed.

This short fixture is a correctness gate, not a throughput or concurrency
benchmark. Keep the image/model caches after the run unless a separate cleanup
change is authorized.

## Loopback Batch Development Profile

The merged Phase 5 batch baseline connects Yap's
create/upload/commit/status/result contract to the isolated Cohere worker. It
is a development profile, not an enterprise deployment:

- the application service still binds only to server loopback;
- Windows reaches it only through an explicitly started SSH local forward;
- the desktop remains configured with `http://127.0.0.1:18765`;
- SSH access is the temporary transport authorization boundary; the service
  does not yet derive a tenant or owner from an Entra token;
- no GB10 application firewall rule, TLS listener, DNS record, ZPA segment, or
  persistent service is created; and
- the merged Phase 5 reference worker remains a transient, non-root, networkless
  comparison path; on the active Phase 6 branch, Cohere uses a separately
  checked vLLM container with no Docker-published port or external egress. A
  bounded launcher-owned proxy exposes only server loopback and the private API
  key remains mandatory. Optional Nemotron jobs use the same shape on a
  different loopback port and API key. None is a persistent supervised
  production service.

On the Linux node, use Python 3.12 and private mode-0700 job storage. Replace
the angle-bracket paths only with a clean staged candidate and the already
verified private model directory; do not place model files, API keys, or job
storage in Git.

Prepare checked runtime images before admitting a gate. The preparation owner
resolves every external `FROM`, rejects any base that is not digest-pinned,
requires that exact digest in the local Docker image store, and uses
`--pull=false`. That prevents base-tag drift, but Dockerfile `RUN` steps may
still use the network to materialize hash- or revision-pinned dependencies.
Complete that work before the candidate is admitted, remove any temporary proxy
or route, and restore the qualified network boundary. Checked-head revision
metadata is applied after network-dependent dependency materialization so
changing only the candidate SHA does not invalidate the pinned dependency
layer.

The preparation owner emits a private receipt only after a second clean-head
check. The receipt binds the Dockerfile SHA-256, runtime, base digest, and
immutable image ID. Freeze its SHA-256 in the admission plan.

The admitted gate never prepares or builds an image. It calls the same owner in
`verify-prepared` mode, which checks the private receipt hash, inspects the
exact-head tag, requires ARM64 architecture plus the exact revision, base, and
runtime labels, and rejects any image ID other than the prepared ID. That
receipt-bound immutable ID is the image passed to the launcher and recorded in
the lifecycle evidence. A missing or mismatched receipt or image is a preflight
failure, never permission to substitute a tag, reconnect, or build.

```bash
release_root='/srv/yap-server/releases/<checked-head>'
model_dir='/path/to/private/cohere-transcribe-03-2026'
storage_dir='/srv/yap-server/private/batch-jobs-<checked-head>'
checked_head="$(git -C "$release_root" rev-parse HEAD)"
vllm_image="yap-cohere-vllm:checked-head-$checked_head"
preparation_root='/path/to/private/runtime-preparation'

install -d -m 0700 "$storage_dir" "$preparation_root"
umask 077
export YAP_COHERE_VLLM_PREPARATION_RECEIPT="$preparation_root/cohere-$checked_head.json"
PYTHONPATH="$release_root/server/src" \
  python3.12 -m yap_server.pools.checked_runtime_image \
    prepare cohere-vllm "$checked_head" \
    >"$YAP_COHERE_VLLM_PREPARATION_RECEIPT"
export YAP_COHERE_VLLM_PREPARATION_RECEIPT_SHA256="$(
  sha256sum "$YAP_COHERE_VLLM_PREPARATION_RECEIPT" | awk '{print $1}'
)"
vllm_image="$(
  PYTHONPATH="$release_root/server/src" \
    python3.12 -m yap_server.pools.checked_runtime_image \
      verify-prepared cohere-vllm "$checked_head" \
      "$YAP_COHERE_VLLM_PREPARATION_RECEIPT" \
      "$YAP_COHERE_VLLM_PREPARATION_RECEIPT_SHA256"
)"
```

To exercise the optional resident Nemotron candidate, point a second model
directory at the exact `.nemo` artifact in `nemotron-nemo-serving.lock.json` and
build the thin checked image. Do not copy the checkpoint into the build context:

```bash
nemotron_model_dir='/path/to/private/nemotron-3.5-asr-streaming-0.6b'
nemo_image="yap-nemotron-nemo:checked-head-$checked_head"
export YAP_NEMOTRON_NEMO_PREPARATION_RECEIPT="$preparation_root/nemotron-$checked_head.json"

PYTHONPATH="$release_root/server/src" \
  python3.12 -m yap_server.pools.checked_runtime_image \
    prepare nemotron-nemo "$checked_head" \
    >"$YAP_NEMOTRON_NEMO_PREPARATION_RECEIPT"
export YAP_NEMOTRON_NEMO_PREPARATION_RECEIPT_SHA256="$(
  sha256sum "$YAP_NEMOTRON_NEMO_PREPARATION_RECEIPT" | awk '{print $1}'
)"
nemo_image="$(
  PYTHONPATH="$release_root/server/src" \
    python3.12 -m yap_server.pools.checked_runtime_image \
      verify-prepared nemotron-nemo "$checked_head" \
      "$YAP_NEMOTRON_NEMO_PREPARATION_RECEIPT" \
      "$YAP_NEMOTRON_NEMO_PREPARATION_RECEIPT_SHA256"
)"
```

To exercise the accepted Phase 6 server language-preflight path, build the
small checked AmberNet worker separately and point it at the already verified
private model directory. The model is mounted at request time and must not be
copied into the image or repository:

```bash
lid_model_dir='/path/to/private/ambernet-1.12.0-int8-qdq'
lid_image="yap-lid:checked-head-$checked_head"
export YAP_LANGUAGE_DETECTION_PREPARATION_RECEIPT="$preparation_root/lid-$checked_head.json"

PYTHONPATH="$release_root/server/src" \
  python3.12 -m yap_server.pools.checked_runtime_image \
    prepare language-detection "$checked_head" \
    >"$YAP_LANGUAGE_DETECTION_PREPARATION_RECEIPT"
export YAP_LANGUAGE_DETECTION_PREPARATION_RECEIPT_SHA256="$(
  sha256sum "$YAP_LANGUAGE_DETECTION_PREPARATION_RECEIPT" | awk '{print $1}'
)"
lid_image="$(
  PYTHONPATH="$release_root/server/src" \
    python3.12 -m yap_server.pools.checked_runtime_image \
      verify-prepared language-detection "$checked_head" \
      "$YAP_LANGUAGE_DETECTION_PREPARATION_RECEIPT" \
      "$YAP_LANGUAGE_DETECTION_PREPARATION_RECEIPT_SHA256"
)"
```

Create one checked, temporary internal bridge for the foreground model
containers. The launchers reject the default Docker bridge, a non-internal
network, or a network whose owner/revision labels do not match the candidate.
The containers therefore have no registry or Internet egress. Docker 29 on the
qualified GB10 did not make an `--internal` bridge's requested published port
reachable, so the checked launchers intentionally publish no Docker ports.
They require `socat` 1.8+, `setsid`, `ss`, and `ps`; each launcher starts one
bounded process group that forwards only numeric IPv4 loopback to the fixed
container-private address. The proxy process starts with a cleared environment
and does not inherit the provider API key:

```bash
inference_network="yap-private-inference-${checked_head:0:12}"
runtime_owner_token="$(python3.12 -c 'import secrets; print(secrets.token_hex(32))')"
runtime_identity_dir="$HOME/.local/share/yap-private/runtime-${checked_head:0:12}"
install -d -m 0700 "$runtime_identity_dir"
inference_network_id="$(
  docker network create \
  --driver bridge \
  --internal \
  --label io.yap.owner=private-inference \
  --label "io.yap.revision=$checked_head" \
  --label "io.yap.run-token=$runtime_owner_token" \
  "$inference_network"
)"
if [[ ! "$inference_network_id" =~ ^[0-9a-f]{64}$ ]] || [ "$(
  docker network inspect \
    --format '{{.Name}}|{{index .Labels "io.yap.run-token"}}' \
    "$inference_network_id"
)" != "$inference_network|$runtime_owner_token" ]; then
  echo "the checked inference network identity is invalid" >&2
  exit 1
fi
```

Re-establish `release_root`, `checked_head`, `inference_network`, and the same
mode-0700 real `runtime_identity_dir` from the clean release in each foreground
terminal. Securely copy the **same**
`runtime_owner_token` into every terminal; never regenerate it after the
network is created because the launchers compare it to the network label.
Re-establish each preparation-receipt path and frozen hash in the terminal that
needs it, then rerun the corresponding `verify-prepared` command above to
recover `vllm_image`, `nemo_image`, or `lid_image`. Those immutable IDs must
come from the same receipt bytes in every shell. Do not persist either API key
in a shell file. Set one private printable-ASCII Cohere API key in both the
Cohere and Yap foreground shells without writing it to a file or command
argument. Start the model server first:

```bash
cd "$release_root"
YAP_CHECKED_HEAD="$checked_head" \
YAP_COHERE_VLLM_IMAGE="$vllm_image" \
YAP_COHERE_MODEL_DIR="$model_dir" \
YAP_COHERE_VLLM_API_KEY="$YAP_COHERE_VLLM_API_KEY" \
YAP_PRIVATE_INFERENCE_NETWORK="$inference_network" \
YAP_RUNTIME_OWNER_TOKEN="$runtime_owner_token" \
YAP_PROXY_PROCESS_GROUP_FILE="$runtime_identity_dir/cohere-vllm-proxy.pgid" \
bash infra/yap-server-node/cohere-vllm-server.sh
```

For direct Nemotron qualification, generate a different in-memory
printable-ASCII key and start its checked foreground service in another shell.
This does not add Nemotron to the committed product capability catalog. The
launcher mounts the same
private job-storage directory read-only at its absolute host path so the Yap
worker can pass only already-owned hash-bound files:

```bash
cd "$release_root"
YAP_CHECKED_HEAD="$checked_head" \
YAP_NEMOTRON_NEMO_IMAGE="$nemo_image" \
YAP_NEMOTRON_MODEL_DIR="$nemotron_model_dir" \
YAP_BATCH_JOB_STORAGE_DIR="$storage_dir" \
YAP_NEMOTRON_NEMO_API_KEY="$YAP_NEMOTRON_NEMO_API_KEY" \
YAP_PRIVATE_INFERENCE_NETWORK="$inference_network" \
YAP_RUNTIME_OWNER_TOKEN="$runtime_owner_token" \
YAP_PROXY_PROCESS_GROUP_FILE="$runtime_identity_dir/nemotron-nemo-proxy.pgid" \
bash infra/yap-server-node/nemotron-nemo-server.sh
```

After the model server reports startup completion, start Yap in a second
foreground shell with the same in-memory key; Yap performs the authenticated
version and exact-model readiness checks before advertising batch capability:

```bash
cd "$release_root"
YAP_CHECKED_HEAD="$checked_head" \
YAP_ASR_MODEL_DIR="$model_dir" \
YAP_BATCH_JOB_STORAGE_DIR="$storage_dir" \
YAP_COHERE_VLLM_ENDPOINT="http://127.0.0.1:18000" \
YAP_COHERE_VLLM_API_KEY="$YAP_COHERE_VLLM_API_KEY" \
YAP_LANGUAGE_DETECTION_ENABLED=1 \
YAP_LANGUAGE_DETECTION_MODEL_DIR="$lid_model_dir" \
YAP_LANGUAGE_DETECTION_WORKER_IMAGE="$lid_image" \
YAP_LANGUAGE_DETECTION_PREPARATION_RECEIPT="$YAP_LANGUAGE_DETECTION_PREPARATION_RECEIPT" \
YAP_LANGUAGE_DETECTION_PREPARATION_RECEIPT_SHA256="$YAP_LANGUAGE_DETECTION_PREPARATION_RECEIPT_SHA256" \
bash infra/yap-server-node/development-batch-server.sh
```

Omit the five language-detection variables only when intentionally testing
the explicit manual-review fallback. In that mode the server does not
advertise `languagePreflight`, and the client must not advance as though a
language preflight had succeeded.

Only a frozen qualification that intentionally exercises the provider-neutral
Yap job boundary should use the complete invocation below. Create a matching
candidate capability lock in the restricted evaluation workspace outside Git,
set `candidate_capability_lock` to that absolute path, and keep the file out of
hosted logs and PRs. Omit the Nemotron lines for the ordinary committed-catalog
development path:

```bash
cd "$release_root"
YAP_CHECKED_HEAD="$checked_head" \
YAP_ASR_MODEL_DIR="$model_dir" \
YAP_BATCH_JOB_STORAGE_DIR="$storage_dir" \
YAP_COHERE_VLLM_ENDPOINT="http://127.0.0.1:18000" \
YAP_COHERE_VLLM_API_KEY="$YAP_COHERE_VLLM_API_KEY" \
YAP_LANGUAGE_DETECTION_ENABLED=1 \
YAP_LANGUAGE_DETECTION_MODEL_DIR="$lid_model_dir" \
YAP_LANGUAGE_DETECTION_WORKER_IMAGE="$lid_image" \
YAP_LANGUAGE_DETECTION_PREPARATION_RECEIPT="$YAP_LANGUAGE_DETECTION_PREPARATION_RECEIPT" \
YAP_LANGUAGE_DETECTION_PREPARATION_RECEIPT_SHA256="$YAP_LANGUAGE_DETECTION_PREPARATION_RECEIPT_SHA256" \
YAP_ASR_CAPABILITY_LOCK="$candidate_capability_lock" \
YAP_NEMOTRON_MODEL_DIR="$nemotron_model_dir" \
YAP_NEMOTRON_MODEL_LOCK="$release_root/server/nemotron-nemo-serving.lock.json" \
YAP_NEMOTRON_NEMO_ENDPOINT="http://127.0.0.1:18001" \
YAP_NEMOTRON_NEMO_API_KEY="$YAP_NEMOTRON_NEMO_API_KEY" \
bash infra/yap-server-node/development-batch-server.sh
```

The lifecycle wrapper refuses a dirty or different Git head. The foreground
launchers refuse a non-ARM64 or revision-mismatched image, a root invoking
identity, an invalid key, missing/invalid inputs, an unchecked network, a busy
loopback port, or a missing/unbounded proxy prerequisite. They verify that the
container joined only the named internal bridge and that the proxy listener is
exactly numeric IPv4 loopback. The model containers use the invoking non-root
UID/GID so mode-0700 private model directories remain readable without widening
host permissions. Run every
configured service and Yap in the foreground so `Ctrl+C`, SSH loss, and
`SIGTERM` stop the container, its log follower, and the complete proxy process
and must not be installed as persistent units before their separate frozen
lifecycle/capacity gates and later production-supervision work. An external
candidate capability lock is qualification input, not evidence that Nemotron is
selected or advertised. After both foreground model containers are stopped,
verify that neither private `*.pgid` identity remains. If a launcher was
abnormally killed, first recover its container by the expected name, require
the same run token, checked revision, and internal network, then stop only the
returned immutable ID:

```bash
for provider_name in yap-cohere-vllm yap-nemotron-nemo; do
  provider_identity="$(
    docker container inspect \
      --format '{{.Id}}|{{index .Config.Labels "io.yap.run-token"}}|{{index .Config.Labels "io.yap.revision"}}|{{.HostConfig.NetworkMode}}' \
      "$provider_name" 2>/dev/null || true
  )"
  [ -z "$provider_identity" ] && continue
  IFS='|' read -r provider_id provider_token provider_revision provider_network \
    <<<"$provider_identity"
  if [[ ! "$provider_id" =~ ^[0-9a-f]{64}$ ]] \
    || [ "$provider_token" != "$runtime_owner_token" ] \
    || [ "$provider_revision" != "$checked_head" ] \
    || [ "$provider_network" != "$inference_network" ]; then
    echo "refusing to stop an unowned replacement provider" >&2
    exit 1
  fi
  docker stop --time 10 "$provider_id"
done
```

Then source `infra/yap-server-node/owned-process-group.sh` and call
`stop_recorded_token_owned_process_group` with that provider's identity file,
the same `runtime_owner_token`, and a descriptive label; it refuses to signal a
group unless every surviving member still carries that token. Then
remove the exact temporary network explicitly with
its immutable ID after checking its name and run-token label:

```bash
if [ "$(
  docker network inspect \
    --format '{{.Name}}|{{index .Labels "io.yap.run-token"}}' \
    "$inference_network_id" 2>/dev/null || true
)" != "$inference_network|$runtime_owner_token" ]; then
  echo "refusing to remove an unowned replacement network" >&2
  exit 1
fi
docker network rm "$inference_network_id"
```

A successful exact-ID removal is part of the manual teardown read-back.

The checked resident-provider lifecycle wrapper composes the provider-owned
cells without turning them into one universal serving runtime. Run it only from
the frozen clean candidate on the GB10 after building the plan-derived provider
duration suite inside a dedicated, mode-0700 `YAP_EVAL_CACHE`. Keep the suite,
raw samples, service logs, host snapshots, and final evidence outside Git and
hosted artifacts:

```bash
cd "$release_root"
YAP_CHECKED_HEAD="$checked_head" \
YAP_EVAL_CACHE="$private_provider_gate_cache" \
YAP_PROVIDER_DURATION_SUITE="$provider_duration_suite" \
YAP_PROVIDER_DURATION_SUITE_SHA256="$provider_duration_suite_sha256" \
YAP_COHERE_MODEL_DIR="$model_dir" \
YAP_NEMOTRON_MODEL_DIR="$nemotron_model_dir" \
YAP_COHERE_VLLM_API_KEY="$YAP_COHERE_VLLM_API_KEY" \
YAP_NEMOTRON_NEMO_API_KEY="$YAP_NEMOTRON_NEMO_API_KEY" \
YAP_COHERE_VLLM_PREPARATION_RECEIPT="$YAP_COHERE_VLLM_PREPARATION_RECEIPT" \
YAP_COHERE_VLLM_PREPARATION_RECEIPT_SHA256="$YAP_COHERE_VLLM_PREPARATION_RECEIPT_SHA256" \
YAP_NEMOTRON_NEMO_PREPARATION_RECEIPT="$YAP_NEMOTRON_NEMO_PREPARATION_RECEIPT" \
YAP_NEMOTRON_NEMO_PREPARATION_RECEIPT_SHA256="$YAP_NEMOTRON_NEMO_PREPARATION_RECEIPT_SHA256" \
bash infra/yap-server-node/resident-provider-lifecycle-gate.sh
```

That wrapper verifies already-present model artifacts without downloading,
verifies both already-prepared checked ARM64 images against their frozen private
preparation receipts without building or pulling, launches those exact immutable
image IDs, creates and later removes its own internal bridge, verifies that
Docker published no provider port and that a fixed external-address probe is
blocked from each container, and runs Cohere then NeMo so the two models do not
overlap in memory.
For each provider it records the image ID and preparation-receipt hash,
exact-model readiness, plan-owned duration/load,
cancellation, capacity, and c8/1,600 resource evidence. Final publication
requires the exact child set, unchanged checked head, unchanged listener,
firewall, and Yap-service snapshots, and no remaining provider container,
proxy, launcher, or network. Readiness timing starts at the first exact-model probe
after Docker reports the container running; it is not image-build,
launcher-to-ready, or production cold-start evidence. The wrapper is only the
resident-provider lifecycle component of the one-time Phase 6 matrix.

For the replaceable Cohere candidate, this lifecycle component requires the c1
duration ladder, short-tail request/result isolation at c1/c2/c4, the c8/1,600
resource cell, cancellation/recovery, slot and PCM admission, and exact
teardown. These `request-lifecycle` cells record lexical variance without
turning repeated-output determinism into a Phase 6 promotion requirement. It
does not run the plan's `vllm-long-waves` or `vllm-mixed-eight` cells. Those cells remain
available for a provider-promotion comparison, including the Phase 8 Cohere-
versus-Tiron decision, but they are not candidate-safety prerequisites.

The first checked-head attempt at
`e7d322fc07c6e1a39e69c2eec4d45e2c94d79e3a` stopped before NeMo after the
accuracy-ineligible 15-minute `vllm-long-waves` control returned all four c2
results but failed transcript-identity stability. Pairwise normalized edit
ratios were 6.9% through 21.6%, and each c2 result differed from the c1 result by
22.4% through 23.4%. The short-tail c1/c2/c4 cell and the duration ladder passed,
and teardown removed the provider container, proxy, listener, launcher, and
temporary network. Retain that private failed receipt as negative provider-
promotion evidence. It points to long-form provider/model stability; it does not
by itself prove or disprove cross-request ownership mixing. A new exact-head
lifecycle run is required after this scope correction.

The next exact-head attempt at
`5b56929889925c933c63374a8d7ab282b6b82a3f` passed Cohere readiness, duration,
short-tail c1/c2/c4, cancellation/recovery, slot admission, and PCM admission.
Its c8 resource load completed all 1,600 requests and passed every current,
peak, allocation, task, thread, and memory-event ceiling. It still failed closed
before NeMo for two test-contract reasons: one repeat reported three lexical
identities, and the faster 116.317-second observation left only 57.798 seconds
in a last-half tail whose minimum is 60 seconds. Cleanup was exact. The corrected
wrapper now labels that load `resource-lifecycle`, records lexical variance
without treating it as provider promotion, and keeps the resource observation
open for at least 125 seconds. No ceiling, request count, concurrency, or teardown
requirement was lowered. A new exact-head run remains required.

At exact head `63318e51d569a1851f1a6daf8d1b707c353f2fa8`, the complete corrected
Cohere lifecycle passed and was torn down before NeMo started. NeMo readiness
passed, but its finalized-duration cell was mislabeled failed: the worker wrote
all nine result files, while seven short/silent cases carried canonical empty
transcripts and the generic observation harness counted only the two non-empty
results as completed. Cleanup was exact. The harness now counts canonical empty
text as a completed result only for `duration-transport-and-lifecycle`;
provider-behavior, request-lifecycle, and resource-lifecycle scopes still
require non-empty output.
The private failed receipt remains regression evidence and a new exact-head run
is required.

At exact head `4ffec120f212d20a26e314108940989c1b6e93a5`, Cohere passed its complete
lifecycle and exact teardown. NeMo passed readiness and both duration ladders,
then completed and published all 600 non-empty short-tail results. Its c1/c2
outputs were lexically stable; two of 200 c4 outputs differed by one word while
remaining correctly bound to their jobs, audio identity, model lock, and output
paths. Cleanup was exact. Because repeated copies of one audio input measure
model determinism rather than cross-request ownership, the wrapper now applies
`request-lifecycle` to the Phase 6 short/long standard cells and records lexical
variance. `provider-behavior` remains a later provider-promotion scope. A new
exact-head run is required.

At exact head `27108e1f591920b5a62496f988ae9ee7b335f2ce`, the full Cohere lifecycle
passed and tore down. NeMo then passed readiness, both duration ladders,
short-tail, and its 15-minute request-lifecycle cell. The fixed/automatic cell
completed 16 results per mode across c1/c8 with correct detected `en-US`
source-time evidence, but automatic segmentation changed wording and produced
zero lexical matches with fixed decoding. The old checker conflated text parity
with language-contract conformance, so the gate stopped closed and cleaned up
exactly. The corrected `nemo-finalized-fixed-auto-contract` cell requires the
distinct fixed/automatic contracts and records text parity for Phase 8 rather
than promoting it. Because this changes the runtime-plan identity, rebuild or
rebind the private suite under a new out-of-band SHA before the next exact-head
run.

Exact head `2b9118ead1df1f3220da65846c2aa8949d90d83d` consumed that rebound
suite and passed all Cohere children plus nine of ten NeMo children. The NeMo
resource workload completed 1,600/1,600, but its separate resource observation
recorded 262 tasks and entrypoint threads against the frozen 256 ceiling. Every
memory, allocation, timing, sampling, and memory-event check passed. Exact
teardown completed and no aggregate published. An independent finalizer replay
also rejected the otherwise-correct mixed long-window evidence because its
stale expectation named only the 15-minute member while the plan selects both
30-second and 15-minute inputs. The finalizer now requires both durations; the
runtime now caps native/PyTorch pools at eight and derives 18 HTTP workers from
the eight-active-request contract. Use a new exact-head evidence directory for
the corrected rerun rather than relabeling the failed receipt. Focused exact-head
`17a727f272943e6bc57a4253247e7e824855c086` evidence has already passed c8/200
and the full c8/1,600 resource profile with a 97-task/thread maximum, all eleven
frozen checks, unchanged 256 ceiling, and exact teardown. This validates the
resource correction only; it does not replace the complete sequential lifecycle
gate.

The complete sequential lifecycle subsequently passed at exact head
`a21964c19e56648e9fddcb5200de419e59a7687c`. Its plan-bound 18-track suite used
plan SHA `d82a770c77d879c5f9d3bd5098e5933ef91f9162971e9f660bf06552c829926f`,
and the bounded aggregate published with evidence SHA
`a6931acc127f2ca74e6d3a4c8c9aa6c93e33289f1d1312a4626d659dfcbeb9cb`.
All 18 children passed. The final NeMo c8/1,600 cell reached 105 tasks and
entrypoint threads against unchanged 256 ceilings, recorded zero memory events,
and stayed within its frozen memory and allocation limits. The mixed long-window
cell selected both 30 seconds and 15 minutes. Finalization and a separate read-
back found no provider container, temporary network, runtime process, or listener
on 18000/18001. Keep the raw suite, child evidence, logs, and samples private;
only these bounded facts belong in repository status. This result closed the
Phase 6 resident-provider candidate-safety component but did not install either
service persistently or promote Cohere/NeMo over a later Tiron comparison.
Exact executable candidate `0ed2037dbbb8c3df9350dbc37aeddc633f567a40`
later repeated all 18 provider children inside the complete 30-child Phase 6
matrix; its public-safe provider aggregate has SHA-256
`b8daa673febc3fb7777ea099c84878bb929ea2ce49d2f3a70c17b0baf594bc78`.

Representative provider quality and low-end physical client hardware
certification remain later gates. Provider cgroup evidence excludes the small host
proxy process group, while API wall latency includes it; whole-host CPU/RAM and
persistent supervision remain Phase 10 evidence.

The service and launcher refuse a non-numeric-loopback bind while batch ASR
mode is enabled; `localhost` is intentionally not accepted for private audio.
It admits at most one running and two queued GPU jobs, eight concurrent HTTP
request workers, 512 retained job records, one-MiB PCM chunks, and four hours
of mono PCM16/16 kHz audio per job. Meeting intake requires a finite retention
expiry after capture start. Expiry maintenance runs at startup and every 60
seconds. An expired active job is cancelled, and destructive removal waits for
commit/worker activity to reach a safe boundary. Cancelled and failed private
audio is purged at that boundary; completed results retain the configured
30-day default unless a shorter policy applies.

From Windows, choose exactly one SSH transport for a rehearsal:

```powershell
# Direct private-Ethernet development
$YapSshAlias = 'dgx-spark-eth'

# Or an explicitly authorized Wi-Fi transport rehearsal
# $YapSshAlias = 'dgx-spark-lan'

ssh -o BatchMode=yes `
  -o ExitOnForwardFailure=yes `
  -o ServerAliveInterval=15 `
  -o ServerAliveCountMax=3 `
  -N -T `
  -L 127.0.0.1:18765:127.0.0.1:18765 `
  $YapSshAlias
```

Keep the forward in its own terminal so its lifecycle is visible. Never put
the Wi-Fi/node address in Yap settings, never add alias failover, and never run
both forwards against the same local port. In another PowerShell terminal:

```powershell
$health = Invoke-RestMethod http://127.0.0.1:18765/v1/health
$health.service
$health.apiVersion
$health.capabilities
```

The batch rehearsal is valid only when `batchJobs` and `jobStatus` are `true`
and `liveStreaming` is `false`. Use a licensed, non-sensitive recording. During
the lifecycle check, interrupt the SSH forward once, verify the desktop keeps
the immutable job queued/retrying without changing its configured origin, then
restore the same forward and verify the same job reaches one server-authoritative
result. Cancellation must remain cancelled across reconnect, and a user retry
must create a new server job without changing the original source.

For the one-time checked-head native gate, do not start the forward manually.
The gate owns one explicit SSH alias, proves port 18765 is initially
unreachable, starts the forward, imports the locked CC-BY-4.0 fixture, drops
the forward around that same durable client job, observes `Retrying`, restores
the same alias/origin, and waits for the verified History result. Its evidence
directory is a new private path outside the repository and contains only
non-content metadata and hashes:

```powershell
$CheckedHead = (git rev-parse HEAD).Trim()
$EvidenceParent = Join-Path $env:LOCALAPPDATA 'Yap-private-gate-evidence'
New-Item -ItemType Directory -Force -Path $EvidenceParent | Out-Null

$env:YAP_CHECKED_HEAD = $CheckedHead
$env:YAP_PRIVATE_SERVER_ASR_GATE_BASE_URL = 'http://127.0.0.1:18765'
$env:YAP_PRIVATE_SERVER_ASR_GATE_SSH_ALIAS = 'dgx-spark-eth'
$env:YAP_PRIVATE_SERVER_ASR_GATE_EVIDENCE_DIR = Join-Path $EvidenceParent $CheckedHead
$env:YAP_PRIVATE_SERVER_ASR_GATE_TIMEOUT_MS = '2700000'

Set-Location desktop
pnpm test:private-server-asr-gate
```

Use `dgx-spark-lan` only for the separately authorized Wi-Fi rehearsal. The
gate never resolves or substitutes aliases and refuses an alias containing
shell syntax. It also refuses to run from a dirty/different head, with a
pre-existing local listener/forward, or with an evidence destination that
already exists.

After the rehearsal, stop the desktop, forward, and server process. Confirm no
Yap listener or worker remains before treating cleanup as complete:

```powershell
Get-NetTCPConnection -LocalPort 18765 -ErrorAction SilentlyContinue
ssh $YapSshAlias "ss -ltnp '( sport = :18765 )' || true; docker ps --format '{{.Names}}' | grep '^yap-batch-asr-' || true"
```

Do not record private audio, transcripts, job storage, tokens, host snapshots,
or security-scan output in Git, CI artifacts, PR comments, or public logs.

## Fresh Dedicated Node Bootstrap

On a genuinely fresh, dedicated demo node, validate the values first without
root or host mutation:

```bash
env \
  YAP_CONFIGURE_PRIVATE_ETHERNET=1 \
  YAP_PRIVATE_IFACE=enP7s7 \
  YAP_PRIVATE_ADDR=192.168.50.1/24 \
  YAP_PRIVATE_SSH_FROM=192.168.50.63 \
  YAP_SSH_POLICY_TEST_ADDR=192.168.50.63 \
  YAP_LAN_SSH_CIDR= \
  YAP_VALIDATE_ONLY=1 \
  bash infra/yap-server-node/setup-server.sh
```

Then run the bootstrap with conservative firewall handling and explicit
desktop/peripheral cleanup:

```bash
sudo env \
  YAP_CONFIGURE_PRIVATE_ETHERNET=1 \
  YAP_PRIVATE_IFACE=enP7s7 \
  YAP_PRIVATE_ADDR=192.168.50.1/24 \
  YAP_PRIVATE_SSH_FROM=192.168.50.63 \
  YAP_SSH_POLICY_TEST_ADDR=192.168.50.63 \
  YAP_LAN_SSH_CIDR= \
  YAP_HARDWARE_PROFILE=dgx-spark-gb10 \
  YAP_FIREWALL_RESET=0 \
  YAP_DISABLE_NOISE_SERVICES=1 \
  bash infra/yap-server-node/setup-server.sh
```

This adds only the direct-management-link SSH rule and does not open an app
port. Because reset is disabled, existing UFW rules remain and must be
inspected separately. Before running it remotely, prove that a second terminal
can connect with `ssh dgx-spark-eth`. Missing `nmcli`, failed profile
activation, or a missing private address now stops setup before UFW changes.
Before SSH is reloaded, the script also evaluates `sshd -T -C` for the
representative `YAP_SSH_POLICY_TEST_ADDR` and refuses the reload unless the
effective owner, authentication, root-login, X11, agent, tunnel, environment,
and forwarding policy exactly matches the documented baseline. The supplied
address must be one client IP inside a configured management source, not a
CIDR; setup also derives and evaluates a representative address from every
configured management source.

`YAP_DISABLE_NOISE_SERVICES=1` stops desktop/peripheral services. Use it only on
a dedicated node. If incompatible existing UFW rules truly require a reset,
run only from the local console with a tested recovery path and set both
`YAP_FIREWALL_RESET=1` and `YAP_FIREWALL_RESET_CONFIRM=local-console`. The
script validates all app-port inputs before mutation, installs management rules
before re-enabling UFW, and attempts to restore those rules if a later reset
step fails. Treat any reported recovery failure as a console repair condition.

## Product And IT Ownership Boundary

| Owner | Responsibilities |
| --- | --- |
| Product | Configurable HTTPS origin (with loopback HTTP limited to the Phase 3 tunnel), capability and auth-required state gating, no embedded node IP, and fail-closed retry without automatic network failover |
| IT | Internal DNS, ZPA app segment and policy, App Connector placement and redundancy, connector-to-server routing, TLS termination and certificates, firewall source ranges, and Entra policy |

Product configuration cannot substitute for approved network topology, and IT
network reachability does not imply that upload, authentication, or inference
has shipped.

## Corporate LAN/VPN Mode

For corporate use, get these from IT before opening the app endpoint:

- Stable DNS name, for example `yap-server.<corp-domain>`
- DHCP reservation or static IP for the server node, including wireless if the node is intended to live on Wi-Fi
- Client CIDR or VPN CIDR allowed to reach the service
- TLS certificate source, preferably corporate CA or approved internal ACME
- Auth plan from ADR 0016, likely Entra/MSAL bearer tokens

Then run with corporate CIDRs:

All angle-bracket names and CIDRs below are documentation placeholders. Do not
execute firewall/bootstrap changes with placeholders or guessed values; wait
for approved IT topology and change authorization.

```bash
sudo env \
  YAP_CONFIGURE_PRIVATE_ETHERNET=0 \
  YAP_PRIVATE_SSH_FROM= \
  YAP_LAN_SSH_CIDR='<corp-admin-cidr>' \
  YAP_SSH_POLICY_TEST_ADDR='<approved-admin-host-ip>' \
  YAP_FIREWALL_RESET=0 \
  YAP_DISABLE_NOISE_SERVICES=0 \
  bash infra/yap-server-node/setup-server.sh
```

Only set `YAP_APP_PORT` after `yap-server` exists and has TLS/auth in front of it:

```bash
sudo env \
  YAP_LAN_SSH_CIDR='<corp-admin-cidr>' \
  YAP_SSH_POLICY_TEST_ADDR='<approved-admin-host-ip>' \
  YAP_APP_PORT=443 \
  YAP_APP_CIDR='<corp-client-or-vpn-cidr>' \
  YAP_FIREWALL_RESET=0 \
  YAP_DISABLE_NOISE_SERVICES=0 \
  bash infra/yap-server-node/setup-server.sh
```

## Zscaler / Wireless Mode

Longer term, prefer Zscaler Private Access or the approved corporate zero-trust path over exposing the server node to a broad wireless subnet.

Target shape:

- Server node joins corporate Wi-Fi or wired LAN with a stable reservation.
- `yap-server` has an internal DNS name approved by IT.
- Zscaler publishes an app segment for that name and port.
- The server node firewall allows the Zscaler connector/client CIDR to the `yap-server` port.
- SSH stays limited to admin CIDRs or Zscaler admin access, not all wireless clients.
- TLS is required at the app entrypoint; auth is enforced above `/health`.

Example once IT gives the Zscaler CIDRs:

The values in this example remain placeholders until IT supplies the actual
DNS, ZPA, routing, certificate, and source-range design. Do not apply the
example as a firewall change by substituting laptop Wi-Fi addresses.

```bash
sudo env \
  YAP_LAN_SSH_CIDR='<admin-cidr-or-empty>' \
  YAP_ZSCALER_SSH_CIDR='<zpa-admin-cidr>' \
  YAP_SSH_POLICY_TEST_ADDR='<approved-zpa-admin-host-ip>' \
  YAP_APP_PORT=443 \
  YAP_APP_CIDR= \
  YAP_ZSCALER_APP_CIDR='<zpa-app-cidr>' \
  bash infra/yap-server-node/setup-server.sh
```

If IT routes Zscaler traffic through connector hosts, use the connector subnet for `YAP_ZSCALER_APP_CIDR`. If clients source NAT directly from a Zscaler client range, use that range instead. Do not guess this value from the laptop's current Wi-Fi IP.

## Baseline Script

`infra/yap-server-node/setup-server.sh` is intentionally small, but it is a
host-mutating bootstrap tool rather than a normal deploy command. It configures:

- `/srv/yap-server/{releases,shared,logs,data,models}`
- SSH key-only access for the configured admin user
- UFW default-deny inbound firewall
- unattended security updates, no automatic reboot
- journald retention
- Docker log rotation when Docker has no existing daemon config
- optional private Ethernet NetworkManager profile
- optional app entrypoint allow rule
- disabled desktop/peripheral noise that does not belong on a server

Copy `infra/yap-server-node/server.env.example` to a local, untracked env file
for repeatable setup. Its defaults do not reset UFW, disable services, open LAN
SSH, or open an application port. Set `YAP_VALIDATE_ONLY=1` for a non-mutating
configuration and host-prerequisite check before every bootstrap run.

For non-fresh or corporate-managed nodes, keep the conservative settings
explicit even though they are the defaults:

```bash
sudo env \
  YAP_FIREWALL_RESET=0 \
  YAP_DISABLE_NOISE_SERVICES=0 \
  bash infra/yap-server-node/setup-server.sh
```

On a fresh dedicated node, opt in to reset/disable behavior only as shown in the
fresh-node section. Never assume that a second run is harmless merely because
the directory and allow-rule operations are repeatable.

## What Not To Do Yet

- Do not open `11000`, `11434`, `5909`, database ports, or model worker ports directly.
- Do not bind the Phase 3 health service to `0.0.0.0`, `[::]`, the Wi-Fi address, or an
  overlay address.
- Do not expose the Phase 4 container worker or model directory as a network
  service.
- Do not make the server node public-internet reachable.
- Do not reuse cached model weights, Handy model files, or `latest` container
  tags without pinned provenance, licenses, and hashes.
- Do not enable time-sensitive auth, leases, replay windows, or authoritative
  server timestamps until the host clock is synchronized.
- Do not delete Docker images or model caches just because they are large; disk is cheap and redownloading model/runtime layers is slow.
- Do not force headless mode until VNC/DGX Dashboard recovery is no longer useful.

## Verification

After setup:

```bash
ssh dgx-spark-eth 'hostname; uname -r; systemctl --failed --no-pager'
ssh dgx-spark-eth 'nvidia-smi --query-gpu=name,driver_version --format=csv,noheader'
ssh dgx-spark-eth 'timedatectl show -p NTPSynchronized --value'
ssh dgx-spark-eth 'docker run --rm --pull=never --device=nvidia.com/gpu=all nvcr.io/nvidia/cuda:13.0.1-devel-ubuntu24.04 nvidia-smi --query-gpu=name --format=csv,noheader'
ssh dgx-spark-eth 'sudo ufw status verbose'
```

The Docker command creates an ephemeral container; run it only when that runtime
validation is authorized. The firewall command requires an interactive sudo
session and must never receive a password through a script or command line.

The completed Phase 3 proof established private-link SSH, loopback-only health,
a loopback-only Windows forward, command-line production connector `Ready`
while reachable, and `Retrying` in a separate tunnel-refusal invocation. It did
not establish a same-process native UI transition. Cleanup left no Yap process
or local/remote port-18765 listener. No application firewall rule or external bind was
added. Host clock synchronization and root UFW read-back remain separate later
gates; do not infer them from service status alone.
