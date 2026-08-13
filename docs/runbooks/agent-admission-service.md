# Agent admission service

This runbook covers the bounded multi-user admission substrate implemented at
exact protected head `7bd93dc624e6d8651dffc710026ca144909b2399` and
admitted by exact public-lock/aggregate head
`135cc2ba8534f41d91ff52cd6b6d366460c7b60f`. It is not yet an enabled
production service: hosted-green head `cf1e69a4...` merged it through PR #158 as
`84d95842...`, and qualified Scribe now consumes it in an authenticated
native/server workflow merged through PR #164 as `ec3af506...`. Simultaneous
full-profile residency, sustained capacity, later workflows, and production
operations evidence remain open.

The current development branch contains an unqualified successor that derives
active route limits from the immutable service profiles (four rapid, eight
complex) while retaining Server IO at one and one active request per owner
globally. Because that work changes protected broker/profile inputs, it requires
fresh exact-head route and affected-workflow qualification, a replacement
public lock, hosted review, and merge. Until those close, the one-slot exact-head
contract documented below remains the qualified merged runbook boundary. Do not
use the candidate limits as sustained-capacity, simultaneous-residency, or
production-SLO evidence.

## Ownership and safety boundary

| Layer | Sole owner |
| --- | --- |
| Exact Qwen/Gemma process lifecycle and readiness generation | Separate `yap-provider-supervisor@<route>` instances |
| Multi-user queue, fairness, leases, deadlines, and terminal outcomes | `yap-agent-admission-broker` Rust process |
| Authenticated tenant/subject and role workflow | Python server application |
| Provider credentials and organization bearer acquisition | Native connector and IT-controlled identity boundary; never the broker payload |

The broker admits only work whose exact provider snapshot is already ready. It
does not enable or start provider units, call Docker, swap a model, or substitute
one route for another. The initial capacity is deliberately one active request
per route. Increase it only from route-specific simultaneous-residency and
sustained multi-owner evidence; if one node cannot pass, use separate owned
service nodes.

Admission state is boot-scoped and in memory. The service uses `Restart=no`.
After a broker failure, new work remains closed until the operator has contained
or accounted for every external model worker that may still hold an old lease.
Do not auto-restart the broker and reconstruct capacity from guesses.

## Build and install

Use Rust 1.96 and the committed lock from a clean reviewed checkout:

```bash
cd server/orchestrator
cargo build --locked --release --bin yap-agent-admission-broker
```

The installer requires the same existing non-root owner and group that can read
the owner-private provider snapshots. It validates an exact clean Git head,
requires the already-installed profiles and candidate lock to match that
checkout byte-for-byte, and copies only the reviewed broker binary and rendered
unit. It deliberately does not enable or start the unit:

```bash
sudo env \
  YAP_PROVIDER_OWNER=<existing-model-owner> \
  YAP_PROVIDER_GROUP=<existing-model-owner-group> \
  YAP_ADMISSION_BROKER_BINARY="$PWD/target/release/yap-agent-admission-broker" \
  YAP_CHECKED_HEAD=<exact-40-character-reviewed-head> \
  bash ../../infra/yap-server-node/install-agent-admission-service.sh
```

Before any later enablement, read back that both route profile files and the
candidate lock exactly match the reviewed checkout and that operations has
selected either a proved shared-node topology or two separately owned nodes.

## Runtime contract

The unit creates an owner-only runtime directory and a mode-0600 Unix socket.
The protocol is one strict newline-delimited JSON object, at most 16 KiB, with
typed responses at most 4 KiB. Unknown fields, links, wrong owners, non-sockets,
wrong modes, malformed identities, and oversized payloads fail closed.

Each request binds:

- authenticated tenant and subject identifiers;
- exact role, purpose, workload route, and work class;
- request and source SHA-256 identities;
- a monotonic queue-inclusive deadline; and
- a 256-bit cancellation/completion token.

The broker permits at most 64 pending requests globally and four active plus
pending requests per owner. It schedules owners round-robin, uses the frozen
route-specific work-class weights, and admits idle-only work only when no
non-idle work remains. A provider unready transition or generation change
rejects queued work and requests cancellation of active work. Capacity is not
released until cancellation is acknowledged. Terminal results are bounded and
token-protected; a duplicate request ID discloses nothing without the original
token.

No bearer, client ID, scope, provider credential, prompt, response, transcript,
or model output belongs in this socket protocol, unit environment, service
state, logs, or public evidence.

## Verification

Run the hardware-independent checks before hosted review:

```bash
cd server/orchestrator
cargo fmt --all --check
cargo clippy --locked --all-targets --all-features -- -D warnings
cargo test --locked
```

From the repository root, run the exact portable server suite and Ruff:

```bash
cd server
PYTHONPATH=src uv run --locked --all-extras python \
  ../verification/run-governed-knowledge-portable-suite.py
uv run --locked --all-extras ruff check src tests
```

At protected head `7bd93dc6...`, Windows and Linux Rust checks, the Linux
owner-private socket lifecycle, 169 portable tests across 28 modules, and Ruff
passed. Replacement qualification admitted both routes; aggregate head
`135cc2ba...` passed semantic admission, the portable and 17-test Postgres
matrices, real restart/retrieval/stale/successor proof, unchanged desktop scope,
and exact teardown. These are admission-contract checks. They are not
simultaneous-model, capacity, production-availability, endpoint, or deployment
evidence.

## Later enablement and recovery

Do not enable or start the admission unit until all of these are true:

1. PR #158 has passed hosted exact-head review and merged (complete);
2. the selected provider topology has passed simultaneous-residency evidence;
3. the authenticated Python workflow owns cancellation through final worker
   termination and can prove no work survives a released lease; and
4. operations has a tested failure procedure that contains old workers before
   a manual broker restart.

Application endpoints, product UI, production observability, capacity tuning,
backup/restore, certificates, enterprise networking, and deployment approval
remain later product or IT/security work.
