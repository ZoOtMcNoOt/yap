# Phase 10 supervised provider services

**Status:** Active; Slice 10.1 merged through PR #155, Slice 10.2 implementation
candidate assembled with private exact-head evidence pending.

**Base:** merged post-Phase-9 maintainability closure
`fc8a16510fa27514db244eb641dea582918a940b` from
[PR #154](https://github.com/mcnatg1/yap/pull/154).

**Applied decisions:** [ADR 0014](../../adr/0014-server-tier-compute-topology.md),
[ADR 0025](../../adr/0025-provider-specific-asr-serving.md),
[ADR 0029](../../adr/0029-vllm-agent-reasoning-runtime.md), and
[ADR 0030](../../adr/0030-rust-supervised-provider-service-lifecycle.md), with
the complete product roster applied by
[ADR 0031](../../adr/0031-eight-agent-voice-os-roster.md).

**Slice 10.1 evidence:** exact hosted-green head
`1a487db840578d8e415fd2e5a51b1909af4b7041` passed the dedicated Linux
lifecycle lane and every required repository CI/CodeQL lane. PR #155 merged it
as `e2d82b89532addb26fda73f652ae4f68b2127ef7`.

## Objective

Turn the merged evaluation-only provider lifecycles into layered production
service ownership without weakening local/offline controls, duplicating
container authority, or inventing a generic TPS promise. Rust becomes the
server orchestration owner; vLLM/NeMo remain inference engines; Python keeps its
domain, authorization, retrieval, and result authority; systemd and the
existing launchers keep their explicit containment responsibilities.

## Product performance goal

The question is not "what headline TPS can the framework claim?" The product
needs the highest sustainable useful throughput that preserves all of these
route-specific requirements:

- exact governed answer/tool/citation correctness and no cross-route fallback;
- authenticated owner isolation and bounded fair admission;
- measured p50/p95/p99 queue plus inference latency by workload class;
- bounded GPU/CPU memory, tasks, queues, and response sizes;
- typed overload before resource exhaustion;
- cancellation acknowledgement, restart recovery, and zero abandoned work;
- no regression to local/offline controls when the team server is unavailable.

The qualified Qwen rapid and Gemma complex settings are frozen starting points,
not production SLOs. Phase 10 may tune batching, sequence limits, cache policy,
and residency only through exact mixed-load evidence. Generic `200+ TPS` or a
single tokens-per-second number is not Yap acceptance evidence.

## Slice 10.1 — one supervised provider lifecycle

This is the smallest hardware-independent layer that works end to end:

1. Add one functionally named Rust crate under `server/orchestrator/`.
2. Supervise exactly one fixed foreground provider launcher per process.
3. Require a numeric-loopback endpoint and exact expected model identity.
4. Own typed `starting`, `ready`, `restart-backoff`, `failed`, `stopping`, and
   `stopped` states plus bounded start/restart/readiness counters.
5. Use one fixed restart window/backoff policy; exhaustion fails closed.
6. On stop, signal the child, wait within a fixed deadline, force termination if
   necessary, and do not exit successfully until the child is reaped.
7. Atomically publish an owner-private redacted state snapshot for operations.
8. Run inside a hardened systemd-owned cgroup. The unit owns the outer process;
   the existing launcher remains the only container/proxy owner.
9. Prove startup, exact readiness, crash/restart, restart exhaustion, graceful
   stop, forced stop, unhealthy/mismatched model identity, and state-record privacy
   with a hardware-independent fixture.

This slice does **not** advertise a provider, integrate an application route,
claim simultaneous model residency, or publish a capacity/SLO result.

## Subsequent layers

### Slice 10.2 — qualified agent service profiles

- Bind the exact Qwen rapid and Gemma complex runtime/model/launch identities to
  separate supervised instances.
- Keep route-specific parser, output, batching, memory, and model settings;
  remove evaluation-only ownership from the production path.
- Prove each service's identity, cancellation, restart, and zero-residue
  lifecycle before any application route consumes it.

### Slice 10.3 — authenticated application integration

- Make Rust own route admission, bounded queues, cancellation, and typed
  readiness/backpressure for authenticated `(tenant, subject)` work.
- Keep Python ownership of authorization, governed retrieval/tools, audit, and
  publication behind versioned bounded adapters.
- Preserve explicit Qwen rapid/Gemma complex selection with no fallback.
- Deliver the bounded admission and service adapters consumed by the eight
  workflows in the
  [complete-roster plan](2026-08-11-eight-agent-voice-os-delivery.md); this
  infrastructure is not itself evidence that any persona has shipped.

### Slice 10.4 — simultaneous residency and capacity promotion

- Measure sustained mixed-owner and mixed-route workloads on the target GB
  node, including warm/cold behavior, queueing, fairness, cancellation,
  overload, recovery, GPU/CPU memory ceilings, and p50/p95/p99.
- Tune only against correctness-preserving evidence. Publish route-specific
  capacity/SLO outcomes, never raw private prompts, outputs, logs, or metrics.

### Slice 10.5 — enterprise/release handoff

- Complete observability, backup/restore, deletion, SBOM/provenance,
  deploy/rollback, disaster recovery, and private full-repository security
  evidence.
- Hand DNS, certificates, ZPA, firewall policy, conditional access, production
  hosting authorization, and monitoring integration to named IT/security
  owners. External unavailability is a blocker, not permission to simulate it.
- Split repositories only after deployable boundaries and access ownership are
  real.

## Slice 10.1 acceptance

- [x] Tests are written before implementation and fail for the missing lifecycle
  behavior.
- [x] The Rust crate has one lifecycle owner and no provider/container logic.
- [x] The systemd template and supervisor agree on one foreground process/cgroup
  ownership model.
- [x] Startup and readiness require exact service/model identity, not only an
  open port.
- [x] Unexpected exit restarts only within the fixed bound; exhaustion fails.
- [x] Stop proves the exact child is reaped and publishes terminal state.
- [x] State counters are bounded, atomic, owner-private, and secret-free.
- [x] Focused Rust, unit-contract, formatting, lint, and Linux lifecycle tests
  pass on one exact clean head.
- [x] Current architecture, ownership, runbook, status, ADR index/status, and
  threshold evidence are reconciled without claiming later Phase 10 layers.
- [x] One focused PR passes all required exact-head hosted checks and merges
  before Slice 10.2 begins.

## Explicit exclusions

- No automatic route substitution or universal model winner.
- No Redis/Neo4j/object-store addition without an executing measured need.
- No public endpoint, invented enterprise identity, certificate, DNS, firewall,
  or deployment approval.
- No production advertisement, simultaneous-residency claim, sustained
  capacity/SLO claim, or generic TPS claim in Slice 10.1.
- No migration/compatibility layer for historical gate supervisors.
