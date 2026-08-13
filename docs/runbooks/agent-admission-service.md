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

The merged profile-capacity successor derives active route limits from the immutable
service profiles (four rapid, eight complex) while retaining Server IO at one
and one active request per owner globally. Exact route head `dab19fe...`
qualified both unchanged full profiles sequentially; exact workflow head
`7cd24deb...` qualified Scribe, Student, and Curator; and replacement public-
lock/aggregate head `7f896b34...` passed. Hosted-green head `593e627b...` passed
all 12 checks, and PR #168 merged the successor as `284ab96b...`. Production
enablement remains open. The earlier one-slot
contract below is retained as historical exact-head evidence. Do not use the
selected-route limits as sustained-capacity, simultaneous-residency, or
production-SLO evidence.

The current batch-invariant successor has separate evidence. Exact executable
`0665c486...` passed sequential lifecycle evidence `7cc016f4...` and route
evidence `06277bd9...`; lock-only `8fee7a5c...` publishes the matching lock. The
full complex profile uses seed `0`, disables prefix caching, and retains its c8/
8,192-token/`0.70` boundary. Its live probe held eight and queued the ninth
without changing provider/broker identity. At the lock-only successor, affected
workflow and aggregate gates freshly passed. This remains internal selected-
route and same-warm-process evidence, not cross-start/global determinism,
sustained capacity, or production enablement.

## Ownership and safety boundary

| Layer | Sole owner |
| --- | --- |
| Exact Qwen/Gemma process lifecycle and readiness generation | Separate `yap-provider-supervisor@<route>` instances |
| Multi-user queue, fairness, leases, deadlines, and terminal outcomes | `yap-agent-admission-broker` Rust process |
| Authenticated tenant/subject and role workflow | Python server application |
| Provider credentials and organization bearer acquisition | Native connector and IT-controlled identity boundary; never the broker payload |

The broker admits only work whose exact provider snapshot is already ready. It
does not enable or start provider units, call Docker, swap a model, or substitute
one route for another. The current candidate capacity is the selected ready
profile's exact maximum-sequence limit: four rapid, eight complex, or one Server
IO request, with one active request per owner globally. These limits were
qualification-probed on each selected route; they are not permission to claim
simultaneous model residency or sustained throughput. Because one Spark cannot
hold the unchanged `0.40` and `0.70` profiles together, warm two-route promotion
still requires a second owned service node and private route.

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

For model-backed routes, active lease counts are additionally bounded by the
selected immutable profile: four for rapid and eight for complex. One owner may
still hold only one active request. Overflow owners remain queued within the
global/per-owner bounds and queue-inclusive deadline; capacity is never borrowed
from another route.

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

That paragraph is historical evidence for the merged one-slot head. The merged
profile-capacity successor's exact route head `dab19fe...` returned
`required-workload-routes-qualified` with public-safe evidence SHA-256
`96228914...`; it admitted Qwen and Gemma sequentially on unchanged full
profiles and completed exact teardown. Exact `7cd24deb...` workflow gates held
four rapid owners plus a queued fifth and eight complex owners plus a queued
ninth, contained every lease, and required unchanged provider/broker identity.
Exact aggregate/public-lock head `7f896b34...` returned
`governed-knowledge-gate-passed` with public-safe evidence SHA-256
`fd197b98...`. See the
[profile-capacity evidence](../evidence/agent-admission-profile-capacity/VERIFICATION.md).
PR #168 merged as `284ab96b...`; none of these facts is a sustained-load or
production-availability claim.

Exact `56b7f5d0...` separately qualified the no-LLM Librarian core on the
Server-IO route: one owner was active, the second queued, cancellation and
acknowledgement completed, every probe lease was contained, and broker identity
remained unchanged. The actual synchronized normal-owner wave submitted all
eight owners. Librarian acquired no model-route lease. This is workflow
qualification, not sustained-capacity or production evidence. Hosted head
`7505247e...` merged it through PR #169 as `d7a7e003...`. See the
[Librarian evidence](../evidence/librarian-permission-safe-evidence/VERIFICATION.md).

Exact executable `0665c486...` privately qualified Analyst on the complex route;
lock-only `8fee7a5c...` publishes the matching route lock. Three synchronized
repeat waves matched 24 of 24 normal invocations and all 29 terminal outcomes.
Hosted head `da1127f8...` merged the internal core through PR #170 as
`52c45d22...`. This qualifies a merged internal workflow, not a product endpoint
or production service. See the
[Analyst evidence](../evidence/analyst-grounded-cited-answers/VERIFICATION.md).

Exact executable `fed729b3...` privately qualified Coordinator on the complex
route. Three synchronized repeat waves matched 24 of 24 normal service calls
and all 29 terminal outcomes. The gate independently proved exactly one ticket
per invocation, 28 submitted leases, 26 completions, one client cancellation,
one deadline expiry, and one pre-cancelled unsubmitted ticket. Hosted head
`53ee0152...` passed all 12 checks, and PR #171 merged Coordinator as
`67d836da...`. This qualifies a merged internal workflow, not a product
endpoint, autonomous action, or production service. See the
[Coordinator evidence](../evidence/coordinator-proposal-bundles/VERIFICATION.md).

Exact executable `08b06f6d...` privately qualified Auditor on the idle-only
complex route. Three synchronized repeat waves matched 24 of 24 normal service
calls and all 29 terminal outcomes. The gate independently proved exactly one
ticket per invocation, 28 submitted leases, 26 completions, one client
cancellation, one deadline expiry, and one pre-cancelled unsubmitted ticket.
Active and queued non-idle work each blocked Auditor admission; admission
resumed only after non-idle work became terminal. Hosted head `937a4129...`
passed all 12 checks and PR #172 merged Auditor as `1b255e9a...`. This qualifies
a merged internal workflow, not a product endpoint, scheduled autonomous review,
or production service. See the
[Auditor evidence](../evidence/auditor-source-cited-review-findings/VERIFICATION.md).

## Later enablement and recovery

Do not enable or start the admission unit until all of these are true:

1. PRs #158, #168, #169, #170, #171, and #172 have passed hosted exact-head
   review and merged (complete); role merge does not authorize service
   enablement;
2. the selected provider topology has passed simultaneous-residency evidence;
3. the authenticated Python workflow owns cancellation through final worker
   termination and can prove no work survives a released lease; and
4. operations has a tested failure procedure that contains old workers before
   a manual broker restart.

Application endpoints, product UI, production observability, capacity tuning,
backup/restore, certificates, enterprise networking, and deployment approval
remain later product or IT/security work.
