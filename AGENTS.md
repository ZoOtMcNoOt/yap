# VoiceOS/Yap Agent Instructions

## Engineering principles

- Do not preserve backwards compatibility. Remove obsolete paths instead of adding compatibility layers, fallbacks, or migrations.
- Choose the simplest implementation that fully meets the current requirements. Avoid speculative abstractions, configurations, and indirection.
- Grow the system in layers. Start from the smallest version that works end to end, and add each new capability on top of a product that already works. Never trade a working product for unfinished complexity.
- Keep components modular and concerns clearly separated.
- Prefer established, well-maintained libraries when they reduce overall complexity or improve reliability. Do not reimplement common functionality without a clear reason.
- Lean on the dependencies already in the project before writing your own implementation or adding packages. Do not assume that a library lacks a needed capability without checking its documentation and types.
- Make architectural decisions for the long term. Do not accept a stopgap that only works for now and is meant to be replaced later.

## Product hierarchy

- The team/private-server profile is the canonical VoiceOS/Yap product journey and roadmap architecture.
- Local Nemotron is the explicit solo, offline, and degraded-mode fallback. Local-first means resilience and privacy; it does not make the local path the primary team-product hierarchy.
- Managed onboarding is organization-first: connect to the provisioned organization server, sign in through organization SSO, verify server access, then prepare and demonstrate the on-device fallback.
- For an unprovisioned installation, make **Connect to your organization** the primary action and **Use offline** the secondary action.
- Treat the server and identity state as first-class product concepts. Do not hide them under an advanced-settings hierarchy in the team profile.
- Auth or server-refresh failures must never block local controls or the offline fallback.
- Do not silently connect to a server, route audio, or acquire credentials. Require explicit user action and show the active route clearly.

## Identity and enterprise boundary

- Do not create Yap-native user credentials for the team profile. Use provider-neutral organization sign-in through the approved native token-provider seam and server-side OIDC verification.
- Do not claim production SSO, enterprise networking, or managed deployment without observed conformance evidence.
- IT owns tenant and app registration, Entra and Conditional Access policy, certificates, DNS, ZPA, firewall policy, and enterprise deployment. Record these as explicit handoffs or blockers rather than inventing developer-owned substitutes.

## Delivery discipline

- Treat the repository, current branch, executable tests, and observed runtime behavior as truth. Accepted ADRs describe decisions; they do not prove implementation.
- Name branches, files, modules, functions, and tests for their behavior or responsibility, not for a roadmap phase.
- Keep roadmap phases independently reviewable and mergeable. Do not combine multiple phases in one long-lived worktree.
- Use focused verification while developing. Run the full applicable local/native/server/GB10 matrix once when a phase candidate is ready, and do not rerun unaffected gates for runner-only changes.
- Merge only after the reviewed exact head is green. If hosted checks are unavailable, record equivalent local evidence and disclose the unavailable checks.
- Reconcile ADR completion claims, implementation plans, architecture documents, and status only after executable evidence exists.
- Use external design references for interaction patterns and principles only; do not copy proprietary implementation or visual assets. Preserve license and provenance records for reused external code.
