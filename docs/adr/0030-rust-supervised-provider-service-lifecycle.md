# ADR 0030: Rust-supervised provider service lifecycle

**Status:** Accepted target; Slice 10.1 local candidate implemented, hosted review pending
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
fixture. Provider-specific production launch profiles, simultaneous residency,
multi-owner admission/fairness, application-route integration, sustained
capacity, p95/p99 SLOs, and deployment promotion remain later evidence layers.

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

## Action items

- [x] Implement and focused-test the single-service Rust lifecycle owner.
- [x] Add a hardened systemd unit template and exact configuration validation.
- [ ] Bind the qualified Qwen rapid and Gemma complex launch profiles without
  cross-route fallback.
- [ ] Integrate typed readiness/backpressure with the authenticated server
  application boundary.
- [ ] Run simultaneous-residency and sustained mixed-owner capacity/SLO gates
  before production advertisement.
