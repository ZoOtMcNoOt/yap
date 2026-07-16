# Implementation Plans

Plans explain ordered implementation work; they are not status authority after
their execution window closes.

| Directory | Meaning | Maintenance rule |
| --- | --- | --- |
| `active/` | Work currently authorized on a named branch/gate | Name scope, owner, base, prohibited work, verification, and closure condition. |
| `completed/` | Landed implementation and gate records | Preserve evidence and historical task order; update only a stale status/link or an evidence correction. |
| `archived/` | Superseded, retired, or partially landed recipes | Keep rationale and provenance, but mark current authority and never use unchecked boxes as backlog. |

Current work:

- [Phase 6 preprocessing pipeline](active/2026-07-16-phase6-preprocessing-pipeline.md)
- [CI actions and cache hardening](active/2026-07-13-ci-actions-cache-hardening.md)

Recently completed:

- [Architecture Checkpoint A](completed/2026-07-15-architecture-checkpoint-a.md)

When a plan closes, use `git mv` into `completed/` or `archived/`, repair all
references, and update [current status](../CURRENT-STATUS.md) only when
executable evidence supports the claim.
