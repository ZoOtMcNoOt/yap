# Yap documentation

Find the guide you need without reading the whole project history.

## Start here

| I want to… | Read this |
| --- | --- |
| Understand what Yap does | [Project overview](../README.md) and [Product](../PRODUCT.md) |
| See what works today | [Current status](CURRENT-STATUS.md) |
| Set up a development environment | [Cloud development](runbooks/cloud-development.md), [desktop](../desktop/README.md) or [server](../server/README.md) |
| Pick up the next piece of work | [The project goal and execution queue](plans/active/2026-10-02-yap-project-hill-climb.md) |
| See the full feature direction | [Roadmap](roadmap/ROADMAP.md) and [Voice OS architecture](VOICE-OS-ARCHITECTURE.md) |
| Understand how the pieces fit | [Current architecture](architecture/CURRENT-ARCHITECTURE.md) |
| Review the interface and its references | [Design](../DESIGN.md), [screen review](evidence/design-refresh/2026-10-03/review.md) and [Mobbin references](evidence/ui-completion/2026-10-02-design-references.md) |
| Check the evidence behind a claim | [Verification evidence](evidence/README.md) |

There is **one active execution queue**. The roadmap keeps the feature inventory;
the goal orders the work. Earlier plans and evidence remain available through the
[plan index](plans/README.md) and [archive](archive/README.md).

## Build and verify

- [Cloud setup and checks](runbooks/cloud-development.md) — frontend, browser,
  native Rust, server and local database work without model hardware.
- [Testing strategy](specs/testing-strategy.md) — which checks belong at each layer.
- [UI acceptance](evidence/ui-completion/2026-10-02-acceptance.md) — supported
  journeys and the remaining target-platform handoff.
- [Dependency audit](runbooks/dependency-audit-policy.md) and
  [third-party provenance](provenance/THIRD-PARTY.md) — origins, notices and review.

## Understand the system

- [Executable ownership](architecture/boundaries/EXECUTABLE-OWNERSHIP.md) explains
  which component owns credentials, source files, jobs and results.
- [Architecture decisions](adr/README.md) record choices and their reasons;
  [implementation status](ADR-IMPLEMENTATION-STATUS.md) tracks what is wired up.
- [Specifications](specs/) and [OpenAPI](../server/openapi/README.md) describe
  interfaces. Each server feature still needs its explicitly configured runtime.
- [Knowledge connections](specs/knowledge-connections.md) explains source-cited
  relationships, proposals and human publication boundaries.

Code and observed behavior establish what executes. Specifications and accepted
decisions describe requirements. Current status and evidence distinguish
development checks from model, Windows and enterprise qualification.

## Operate a private server

- [Server-node setup](runbooks/yap-server-node-setup.md)
- [Provider supervision](runbooks/provider-supervisor-service.md)
- [Agent admission](runbooks/agent-admission-service.md)
- [Security posture](security/SECURITY-POSTURE.md)

## Follow the work

The [evidence index](evidence/README.md) collects verification records for imports,
exports, terminology, model lifecycle, knowledge workflows and UI changes. Use
the [changelog](../CHANGELOG.md) for the change history, the
[research index](research/README.md) for investigations, and the
[archive](archive/README.md) for earlier plans and implementation narratives.
The [server implementation history](archive/implementation-evidence/2026-10-03-server-implementation-history.md)
preserves its full earlier README, including qualification receipts and evaluation
commands; use the [server guide](../server/README.md) for current setup.
