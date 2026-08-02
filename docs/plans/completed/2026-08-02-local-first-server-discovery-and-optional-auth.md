# Local-First Server Discovery and Optional Authentication

**Status:** Completed implementation and local verification from merged
baseline `39463ffd87485f148440b65606cb6dbefa3a8153`. Hosted exact-head evidence
on [PR #140](https://github.com/mcnatg1/yap/pull/140) remains merge authority.

## Outcome

Yap must remain immediately usable for on-device live dictation without a
server, account, tunnel, or enterprise identity configuration. A supported
loopback server or SSH forward may be discovered and offered, but discovery
must never connect, persist an origin, acquire a token, or block local setup
without an explicit user action.

## In scope

1. Keep local engine/model/language setup independent from optional server
   refresh failures.
2. Retry only the fixed numeric-loopback health probe so a server or tunnel
   that starts after Yap is offered without restarting the desktop.
3. Preserve explicit origin approval before saving or contacting a discovered
   server through authenticated routes.
4. Present on-device dictation as the primary System setting and keep manual
   organization-server and sign-in configuration under progressive disclosure.
5. State the authentication truth: the provider-neutral token seam and WAM
   adapter exist, but no production provider is selected and enterprise SSO
   requires organization-provided Entra registration and approval.

## Explicitly out of scope

- LAN scanning, multicast discovery, DNS/service discovery, or automatic SSH
  tunnel ownership.
- Enabling the WAM adapter by default or inventing tenant, client, scope,
  Conditional Access, consent, certificate, ZPA, or firewall configuration.
- Live server ASR, Phase 8 meeting inference, or any Phase 9–10 capability.
- A full Codex Security scan before the planned Phase 10 gate.

## Verification and closure

- Focused browser behavior proves delayed loopback discovery, explicit connect
  consent, durable dismissal, local readiness despite server-refresh failure,
  and optional server/SSO settings.
- The one-time applicable desktop gate passed on the implementation candidate:
  dependency policy audit, 71 release/document contracts, 397 frontend unit
  tests across 59 files, production frontend build, and 40 Playwright tests.
- The native fixed-loopback probe interface is unchanged and retains its
  existing Rust contract coverage. Unrelated private-runtime and server-model
  matrices were correctly excluded from this client-only change.
- Independent race/lifecycle, local-first UX, and documentation-truth reviews
  were resolved before the focused pull request.
- Current status, architecture, ADR implementation status, ownership, roadmap,
  authentication, and server runbook claims were reconciled to checked
  behavior. Hosted checks on the exact reviewed head remain merge authority.
