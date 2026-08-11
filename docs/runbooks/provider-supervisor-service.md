# Provider supervisor service

This runbook covers the merged Phase 10 Slice 10.1 lifecycle boundary and the
Slice 10.2 rapid/complex profile installation contract. Installing files does
not promote a model, create an application route, expose a network service, or
authorize a production deployment. Each profile must still pass its exact-head
private lifecycle gate before an instance is enabled.

## Ownership

| Layer | Sole owner |
| --- | --- |
| Outer host cgroup and catastrophic supervisor restart | `systemd` through `yap-provider-supervisor@.service` |
| One launcher process, exact readiness, bounded child restart, terminal state | `server/orchestrator` Rust binary |
| Exact service profile and candidate-lock admission | Rust supervisor plus `agent_vllm_service_profile.py` read-back |
| Provider container, private bridge/proxy, immutable image/model checks, cleanup | `agent-vllm-server.sh` plus the existing checked foreground helper |
| Authorization, retrieval, proposals, audit, and application routing | Existing server owners; not part of Slice 10.1 |

The unit uses `KillMode=mixed`: a normal stop reaches the Rust main process
first, so Rust can terminate and reap its one launcher. The outer cgroup sends a
final kill only if that bounded stop fails. `Restart=on-abnormal` restarts a
crashed supervisor, while an ordinary fail-closed Rust error is not relabeled
as recoverable. Rust alone applies the child restart window.

## Build and install the reviewed binary

Use Rust 1.96 and the committed lock from a clean reviewed checkout:

```bash
cd server/orchestrator
cargo build --locked --release --bin yap-provider-supervisor
```

The test fixture is behind the `test-fixture` Cargo feature and is not built by
that command. The installer requires an already-existing non-root model owner;
it does not create accounts, add group membership, enable a unit, or start a
provider:

Before installation, the operations owner must provision two distinct internal
Docker bridges. Each bridge must be labeled with `io.yap.owner=private-inference`,
the exact checked revision, and the same route-specific run token supplied to
the installer. A bridge cannot be shared because its ownership token is part of
the launch admission contract.

```bash
docker network create --driver bridge --internal \
  --label io.yap.owner=private-inference \
  --label io.yap.revision=<exact-40-character-release-head> \
  --label io.yap.run-token=<rapid-route-token> \
  <checked-rapid-internal-network>
docker network create --driver bridge --internal \
  --label io.yap.owner=private-inference \
  --label io.yap.revision=<exact-40-character-release-head> \
  --label io.yap.run-token=<complex-route-token> \
  <checked-complex-internal-network>
```

```bash
sudo env \
  YAP_PROVIDER_OWNER=<existing-model-owner> \
  YAP_PROVIDER_GROUP=<existing-model-owner-group> \
  YAP_SUPERVISOR_BINARY="$PWD/target/release/yap-provider-supervisor" \
  YAP_CHECKED_HEAD=<exact-40-character-release-head> \
  YAP_RAPID_MODEL_SNAPSHOT=<absolute-qwen-snapshot> \
  YAP_COMPLEX_MODEL_SNAPSHOT=<absolute-gemma-snapshot> \
  YAP_RAPID_PRIVATE_INFERENCE_NETWORK=<checked-rapid-internal-network> \
  YAP_COMPLEX_PRIVATE_INFERENCE_NETWORK=<checked-complex-internal-network> \
  YAP_RAPID_RUNTIME_OWNER_TOKEN=<32-random-bytes-lowercase-hex> \
  YAP_COMPLEX_RUNTIME_OWNER_TOKEN=<different-32-random-bytes-lowercase-hex> \
  bash ../../infra/yap-server-node/install-provider-supervisor-service.sh
```

The installer copies the reviewed executable to
`/usr/local/libexec/yap-provider-supervisor`, the foreground agent launcher and
its existing containment helpers under `/usr/local/libexec/yap-agent-vllm/`,
the two exact profiles and candidate lock under `/usr/local/share/yap/`, and two
root-owned mode-0600 environment files under `/etc/yap/providers`. It renders
the checked unit template, reloads systemd, and deliberately neither enables
nor starts either instance.

## Per-instance configuration

The only valid unit instances are `rapid-automation` and
`complex-orchestration`; `%i` is passed directly as the Rust route identity.
The installer creates `/etc/yap/providers/<route>.env` as a root-owned
mode-0600 regular file. The supervisor consumes exactly these lifecycle fields:

```text
YAP_PROVIDER_PROFILE=/usr/local/share/yap/agent-service-profiles/<route>.json
YAP_PROVIDER_PROFILE_SHA256=<exact-profile-sha256>
YAP_PROVIDER_CANDIDATE_LOCK=/usr/local/share/yap/agent-reasoning-candidates.lock.json
YAP_PROVIDER_LAUNCHER=<absolute-canonical-foreground-launcher-path>
```

The same file contains the exact checked head, model snapshot, route-specific
internal network, instance-specific ownership token, and proxy-state path. The
installer requires its repository to be the exact clean checked head and copies
the minimal profile reader into a root-owned, non-writable runtime tree. The
service never imports mutable checkout source. The two profiles bind these
distinct public-safe service facts:

| Unit | Loopback endpoint | Container | Candidate |
| --- | --- | --- | --- |
| `rapid-automation` | `127.0.0.1:18100` | `yap-agent-qwen-rapid` | Qwen 3.6 rapid route |
| `complex-orchestration` | `127.0.0.1:18101` | `yap-agent-gemma-complex` | Gemma 4 complex route |

The profile reader revalidates the profile digest, candidate-lock digest,
route/model/runtime/parser/output settings, exact model-snapshot artifact
manifest, resource bounds, and derived vLLM arguments before Docker is called.
The launcher then revalidates the immutable ARM64 image ID, checked internal
network, non-root owner, distinct fixed container identity, and bounded
container policy. It exposes only the profile port through the existing
numeric-loopback proxy and owns exact container/proxy cleanup. It does not
accept a fallback route or provider API credential.

## Readiness, restart, and state

The profile supplies the numeric-loopback endpoint and exact served model;
supervisor control flags are single-valued. Readiness requires both:

1. HTTP 200 from `/health` on the configured numeric-loopback endpoint; and
2. exactly one `/v1/models` entry whose `id` equals the configured model.

An open port, PID, hostname, second model, or mismatched model is not ready.
After readiness, three consecutive failed probes retire the launcher. Rust
allows at most three restarts in 60 seconds with fixed 1-, 2-, and 4-second
backoffs. Exhaustion publishes `failed` and exits with failure. A stop publishes
`stopping`, gives the launcher ten seconds, force-kills it if required, waits up
to five more seconds for reap, then publishes `stopped`.

The unit creates `/run/yap-provider-<route>` as mode 0700. Rust atomically
writes schema-2 `service-state.json` as an owner-private regular file with only:

- schema version, route, exact profile ID, profile SHA-256, candidate-lock
  SHA-256, and typed lifecycle state;
- process generation and start/restart counts;
- consecutive failure and readiness-transition counts.

It contains no endpoint, model path, API key, prompt, response, token, raw
metric series, or private artifact path.

## Verification

Local cross-platform checks:

```bash
cd server/orchestrator
cargo fmt --all --check
cargo clippy --locked --all-targets --all-features -- -D warnings
cargo test --locked
cargo test --locked --features test-fixture --test supervised_service -- --test-threads=1
```

The dedicated hosted Ubuntu lane additionally proves POSIX executable and
privacy modes, normal `SIGTERM`, forced kill/reap after ignored `SIGTERM`, Bash
syntax, exact-head cleanliness, and the systemd boundary contracts. These are
lifecycle checks. Slice 10.2 additionally requires a private exact-head
sequential launch/readiness/restart/stop/zero-residue check for both profiles.
Neither lane is simultaneous-residency, provider quality, capacity,
latency-SLO, application-route, or production-deployment evidence.

Run that Slice 10.2 gate only from the exact clean ARM64 private-node checkout.
The evidence directory must be a new empty owner-private directory outside the
repository. The gate builds the locked Rust supervisor from that checkout,
stages the minimal launcher runtime privately, and runs Qwen then Gemma:

```bash
export PATH="$HOME/.cargo/bin:$HOME/.local/bin:$PATH"
export YAP_CHECKED_HEAD="$(git rev-parse HEAD)"
install -d -m 0700 <new-private-evidence-root>
cd server
PYTHONPATH=src uv run --locked python -m \
  yap_server.evaluation.agent_service_lifecycle_gate \
  --repository-root "$(git rev-parse --show-toplevel)" \
  --checked-head "$YAP_CHECKED_HEAD" \
  --rapid-model-snapshot <exact-qwen-snapshot> \
  --complex-model-snapshot <exact-gemma-snapshot> \
  --evidence-root <new-private-evidence-root>
```

Publication occurs only after each route independently reaches exact readiness,
its owned container is killed, the same route restarts as a new container and
process, the supervisor stops cleanly, and the route's container, listener,
owned processes, network, and same-label owners are absent. The public-safe
receipt includes only the exact checked head, hashes and immutable image IDs,
boolean lifecycle/teardown facts, and explicit `false` capacity and
simultaneous-residency claims. Logs, process identities, owner tokens, model
paths, and private measurements stay under the private evidence root.

`server/orchestrator/Cargo.lock` freezes every registry checksum. The Slice
10.1 graph uses the existing permissive Rust ecosystem boundary (MIT,
Apache-2.0, Unicode-3.0, Unlicense, and LLVM-exception alternatives as declared
by the locked packages). Any distributed server artifact must add its exact
SBOM and required notice texts before the later release/deployment gate.
