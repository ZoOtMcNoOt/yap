# Implementation Plans

Plans explain ordered implementation work; they are not status authority after
their execution window closes.

| Directory | Meaning | Maintenance rule |
| --- | --- | --- |
| `active/` | Work currently authorized on a named branch/gate | Name scope, owner, base, prohibited work, verification, and closure condition. |
| `queued/` | Accepted next work that is not authorized in the current branch | State the activation condition and keep its unchecked work out of current status claims. |
| `completed/` | Landed implementation and gate records | Preserve evidence and historical task order; update only a stale status/link or an evidence correction. |
| `archived/` | Superseded, retired, or partially landed recipes | Keep rationale and provenance, but mark current authority and never use unchecked boxes as backlog. |

Current work:

- [Audio preprocessing and language routing](active/2026-07-16-audio-preprocessing-and-language-routing.md)
- [CI actions and cache hardening](active/2026-07-13-ci-actions-cache-hardening.md)

Queued work (activate only in roadmap order):

- [Codebase ownership and maintainability review](queued/2026-07-18-codebase-ownership-and-maintainability-review.md)
- [Joint speaker-attributed meeting transcription](queued/2026-07-22-joint-speaker-attributed-meeting-transcription.md)

Recently completed:

- [Executable ownership and maintainability review](completed/2026-07-15-executable-ownership-and-maintainability-review.md)

When a plan closes, use `git mv` into `completed/` or `archived/`, repair all
references, and update [current status](../CURRENT-STATUS.md) only when
executable evidence supports the claim.
