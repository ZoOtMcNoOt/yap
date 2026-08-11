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

- [CI actions and cache hardening](active/2026-07-13-ci-actions-cache-hardening.md)
- [VoiceOS/Yap decision, evidence, and future-work queue](active/2026-07-17-voiceos-decision-evidence-queue.md)
- [Integrated MVP validation and delivery control](active/2026-07-23-integrated-mvp-validation-and-delivery-control.md)

Queued work (activate only in roadmap order): none.

Recently completed:

- [Governed knowledge ownership and maintainability review](completed/2026-08-10-governed-knowledge-ownership-and-maintainability-review.md)
- [Meeting transcription production qualification](completed/2026-08-03-meeting-transcription-production-qualification.md)
- [Meeting transcription ownership and maintainability review](completed/2026-08-03-meeting-transcription-ownership-and-maintainability-review.md)
- [Governed knowledge and agents](completed/2026-08-09-governed-knowledge-and-agents.md)
- [Joint speaker-attributed meeting transcription](completed/2026-07-22-joint-speaker-attributed-meeting-transcription.md)
- [Local-first server discovery and optional authentication](completed/2026-08-02-local-first-server-discovery-and-optional-auth.md)
- [Tenant-scoped identity and job authorization](completed/2026-07-25-tenant-scoped-identity-and-job-authorization.md)
- [Executable ownership and maintainability review](completed/2026-07-15-executable-ownership-and-maintainability-review.md)
- [Audio preprocessing and language routing](completed/2026-07-16-audio-preprocessing-and-language-routing.md)
- [Codebase ownership and maintainability review](completed/2026-07-18-codebase-ownership-and-maintainability-review.md)

When a plan closes, use `git mv` into `completed/` or `archived/`, repair all
references, and update [current status](../CURRENT-STATUS.md) only when
executable evidence supports the claim.
