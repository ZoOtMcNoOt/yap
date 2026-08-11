# Provider supervisor service

This runbook covers the Phase 10 Slice 10.1 lifecycle boundary. It does not
promote a model, create an application route, expose a network service, or
authorize a production deployment.

## Ownership

| Layer | Sole owner |
| --- | --- |
| Outer host cgroup and catastrophic supervisor restart | `systemd` through `yap-provider-supervisor@.service` |
| One launcher process, exact readiness, bounded child restart, terminal state | `server/orchestrator` Rust binary |
| Provider container, private bridge/proxy, immutable image/model checks, cleanup | Existing checked foreground launcher |
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

```bash
sudo env \
  YAP_PROVIDER_OWNER=<existing-model-owner> \
  YAP_PROVIDER_GROUP=<existing-model-owner-group> \
  YAP_SUPERVISOR_BINARY="$PWD/target/release/yap-provider-supervisor" \
  bash ../../infra/yap-server-node/install-provider-supervisor-service.sh
```

The installer copies the reviewed executable to
`/usr/local/libexec/yap-provider-supervisor`, renders the checked unit template
with that explicit owner, creates `/etc/yap/providers` as root-only mode 0700,
and reloads systemd. It deliberately leaves activation to a later reviewed
provider-profile gate.

## Per-instance configuration

The only valid unit instances are `rapid-automation` and
`complex-orchestration`; `%i` is passed directly as the Rust route identity.
Create `/etc/yap/providers/<route>.env` as a root-owned mode-0600 regular file.
The supervisor consumes exactly these lifecycle fields:

```text
YAP_PROVIDER_ENDPOINT=http://127.0.0.1:<fixed-port>
YAP_PROVIDER_MODEL=<exact-served-model-identity>
YAP_PROVIDER_LAUNCHER=<absolute-canonical-foreground-launcher-path>
```

The same file must also contain the checked launcher-specific image, model,
network, ownership-token, proxy-state, and API-key inputs. Those values are
inherited by the launcher; credentials are never placed in `ExecStart`, the
Rust command arguments, or the state snapshot. Slice 10.2 owns the exact
Qwen/Gemma production profiles, so no instance should be enabled from the
merged Slice 10.1 baseline alone.

## Readiness, restart, and state

Readiness requires both:

1. HTTP 200 from `/health` on the configured numeric-loopback endpoint; and
2. exactly one `/v1/models` entry whose `id` equals the configured model.

An open port, PID, hostname, second model, or mismatched model is not ready.
After readiness, three consecutive failed probes retire the launcher. Rust
allows at most three restarts in 60 seconds with fixed 1-, 2-, and 4-second
backoffs. Exhaustion publishes `failed` and exits with failure. A stop publishes
`stopping`, gives the launcher ten seconds, force-kills it if required, waits up
to five more seconds for reap, then publishes `stopped`.

The unit creates `/run/yap-provider-<route>` as mode 0700. Rust atomically
writes `service-state.json` as an owner-private regular file with only:

- schema version, route, and typed lifecycle state;
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
lifecycle checks, not provider quality, capacity, latency-SLO, or production
deployment evidence.

`server/orchestrator/Cargo.lock` freezes every registry checksum. The Slice
10.1 graph uses the existing permissive Rust ecosystem boundary (MIT,
Apache-2.0, Unicode-3.0, Unlicense, and LLVM-exception alternatives as declared
by the locked packages). Any distributed server artifact must add its exact
SBOM and required notice texts before the later release/deployment gate.
