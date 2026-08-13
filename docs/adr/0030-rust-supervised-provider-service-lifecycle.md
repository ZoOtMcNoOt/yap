# ADR 0030: Rust-supervised provider service lifecycle

**Status:** Accepted; Slices 10.1–10.3 and Scribe merged; later workflows and production layers pending
**Date:** 2026-08-11
**Deciders:** Yap product and engineering owner
**Amends:** [ADR 0014](0014-server-tier-compute-topology.md),
[ADR 0025](0025-provider-specific-asr-serving.md), and
[ADR 0029](0029-vllm-agent-reasoning-runtime.md)

## Context

The merged server has bounded foreground launchers and exact evaluation
lifecycle evidence for provider containers, but those launchers are not
persistent production services. The Python and Bash qualification owners prove
candidate identity, behavior, containment, and teardown; they are not a
production control plane. Phase 10 must add persistent supervision without
moving model inference into Rust, duplicating launcher/container ownership, or
turning headline token throughput into a product SLO.

The organization-owned private server remains the canonical team route.
Supported local/offline operation remains available when that server is absent,
and a remote failure may not disable local controls. Enterprise identity,
network, certificate, deployment, and monitoring integration remain explicit
IT/security handoffs.

## Decision

Yap will grow the production service boundary in two layers:

1. **systemd owns the outer host service and cgroup.** It starts one Rust
   supervisor instance, applies host-level resource and restart policy, and
   guarantees that an orchestrator crash cannot leave an unowned process tree.
2. **The Rust supervisor owns one provider launcher lifecycle.** It starts one
   fixed foreground launcher, verifies the configured numeric-loopback health
   and exact served-model identity, records typed lifecycle state and bounded
   counters, performs a fixed bounded child-restart policy, and stops/reaps the
   child before exit.

The existing provider launcher remains the sole owner of its container,
loopback proxy, immutable image/model checks, and exact teardown. The Rust
supervisor does not call Docker directly and does not reconstruct launcher
policy. One supervisor instance never substitutes another workload route: a
rapid-route failure remains a rapid-route failure, and a complex-route failure
remains a complex-route failure.

The first Phase 10 slice implements this lifecycle with a hardware-independent
fixture. Slice 10.2 binds immutable Qwen rapid and Gemma complex profiles to
separate supervised instances and proves their sequential lifecycles plus fresh
route qualification. Slice 10.3 now has a merged, gated Rust admission core with strict
private Python transport; hosted-green head `cf1e69a4...` merged it through PR
#158 as `84d95842...`. Qualified Scribe is its first authenticated application
consumer and merged through PR #164 as `ec3af506...`. Simultaneous warm residency, sustained multi-owner capacity,
p95/p99 SLOs, and deployment promotion remain later evidence layers.

## Options considered

### systemd directly supervises each provider launcher

This is operationally simple, but it cannot own Yap's model-identity readiness,
typed lifecycle projection, later route admission, or workload-aware recovery.
Those behaviors would be scattered across unit files and application callers.

### Promote the Python qualification supervisor

The existing supervisor is strong evidence tooling, but it is intentionally
Linux-gate-specific and owns one bounded qualification command. Promoting it
would make evaluation code the production authority and contradict the accepted
Rust orchestration target.

### Rust child lifecycle inside a systemd-owned cgroup

This keeps the host service manager responsible for outer containment while
giving Yap one functional Rust owner for provider identity, health, restart,
state, and later admission. It reuses the existing foreground launchers rather
than adding a second container owner. This option is selected.

## Consequences

- A provider process is never considered ready from PID/listener presence
  alone; the exact configured service and model identity must be observed.
- Restart count, consecutive failures, readiness transitions, and terminal
  state are operational facts, not performance or capacity claims.
- The supervisor state record is owner-private and contains no API key, prompt,
  output, model response, raw metric series, credential, or private path.
- Later admission and fairness must consume this owner rather than create a
  second health/restart state machine in Python or shell.
- Production token throughput will be measured per workload route alongside
  correctness, p95/p99 latency, memory ceilings, fairness, overload behavior,
  and recovery. No generic TPS target is promoted from framework marketing.
- Exact hosted-green head `1a487db840578d8e415fd2e5a51b1909af4b7041`
  passed the dedicated Linux lifecycle lane and every required repository check;
  PR #155 merged Slice 10.1 as
  `e2d82b89532addb26fda73f652ae4f68b2127ef7`. This is lifecycle evidence,
  not provider promotion or capacity evidence.
- Exact Slice 10.2 lifecycle head
  `4b103c1bd8b393b7cabf6d219071fa8ba37bda09` passed sequential Qwen and
  Gemma start/readiness/restart/stop plus zero-residue teardown with public-safe
  evidence SHA-256
  `9b6a34f6d4f099123894212bbabda79463b73c1a954bbd04a71a7dfb1d88f27d`.
  Exact qualification head `4d6232123520dd85202f7095c156c766c7dd2ee0`
  returned `required-workload-routes-qualified`; public-lock successor
  `0471b158ac34f97c0f2be7323433470fe5de7fa4` passed the aggregate gate.
  Hosted-green head `6d1400cc...` merged through PR #157 as `cac8989b...`.
  This is not simultaneous-residency or capacity evidence.
- Exact protected admission-core head `7bd93dc6...` implements bounded role/owner queues,
  queue-inclusive deadlines, token-bound cancellation acknowledgement,
  provider-generation disruption, typed overload, and an owner-private Unix
  broker. It is gated and intentionally does not auto-start either
  provider or auto-restart after losing lease state. Replacement qualification
  admitted both routes; public-lock/aggregate head `135cc2ba...` passed the
  complete admission-slice gate, and PR #158 merged it. Scribe is the first
  product consumer; exact head `e5858424...` passed its private gate with
  public-safe semantic evidence SHA-256 `5e187ed4...`, and hosted-green head
  `bc9a88bc...` merged through PR #164 as `ec3af506...`.
- Exact batch-invariant executable candidate `0665c486...` reran the two full
  service lifecycles sequentially with public-safe evidence SHA-256
  `7cc016f4...`, then returned `required-workload-routes-qualified` with
  public-safe evidence SHA-256 `06277bd9...`. Lock-only successor `8fee7a5c...`
  publishes the matching route lock. The Gemma profile now owns batch-invariant
  request execution with prefix caching disabled; its exact warm identity held
  through the affected workflow gates. This remains sequential lifecycle and
  same-warm-process evidence, not simultaneous residency, cross-start/global
  determinism, sustained capacity, or a production SLO.

## Action items

- [x] Implement and focused-test the single-service Rust lifecycle owner.
- [x] Add a hardened systemd unit template and exact configuration validation.
- [x] Bind the qualified Qwen rapid and Gemma complex launch profiles without
  cross-route fallback.
- [ ] Integrate typed readiness/backpressure with the authenticated server
  application boundary.
- [ ] Keep both exact services warm behind bounded owner-fair admission; never
  launch or swap a model in request handling.
- [ ] Run simultaneous-residency and sustained mixed-owner capacity/SLO gates
  before production advertisement.
