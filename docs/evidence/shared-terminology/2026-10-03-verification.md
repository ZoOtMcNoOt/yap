# Shared terminology

**Owner:** Grant McNatt. **Date:** 2026-10-03. **Scope:** Development working tree; real local Postgres, deterministic authenticated HTTP, Linux native transport and Chromium fixture journeys.

Settings → Personalization now discovers and manages personal, team and organization terms. Previously, the service and desktop exposed only personal CRUD and production correction snapshots had no trusted team memberships. One explicit operator policy now supplies tenant-scoped visibility, team managers, organization administrator roles and readable labels to both CRUD and correction snapshots. Unconfigured shared scopes remain unavailable.

## Acceptance

**Coverage: 9/9 defined software outcomes.** These results do not qualify actual directory synchronization, Windows/WAM or inference.

| Outcome | Verified behavior |
| --- | --- |
| Explicit trusted configuration | Owner-private, bounded regular JSON policy; authentication required; duplicate/unknown fields, excessive grants, links/FIFOs and managers outside membership fail closed. No policy exposes only Personal, even with an administrator role. |
| Bounded authorized discovery/listing | At most 34 trusted scopes and ten records per page. SQL filters tenant, scope and owner before pagination; explicit locale includes language-independent terms. Read-only labels and controls remain clear. |
| Append-only scope-bound mutations | Authenticated principal and policy derive ownership. Create/edit/tombstone append to the existing canonical ledger; request fields cannot mint tenant, owner, role or membership. |
| Visibility separate from management | Team readers can list/read but cannot create, edit, delete or replay creation. Cross-scope/tenant reads fail; only configured authenticated organization roles manage organization terms. Revoked creation replay is refused. |
| Replay, conflicts and frozen history | Existing personal creation IDs and data remain unchanged. Shared creation additionally binds scope/owner. Replay preserves the first receipt; stale edits conflict; tombstones preserve history. Old jobs remain frozen and new correction snapshots observe authorized edits. |
| Native route/session/scope binding | Existing authenticated dispatch and connector leases remain authoritative. Native requests and receipts bind exact scope. Discovery supplies a native connection revision; subsequent commands must match it before HTTP dispatch, and stale completion is refused. An old creation draft cannot be submitted under a new connection. |
| Usable Personalization | Explicit trusted scope and language selectors, contextual management actions, read-only states, preferred spelling/variants/sensitivity, retained drafts and deliberate conflict comparison. Scope changes are blocked while a draft/deletion is active. |
| Recovery and local independence | Discovery/list/write failures have retry paths. Settings navigation retains pending work without duplicate submission. Sign-out clears private loaded data and discards delayed results. Revoked visibility keeps a cancellable draft but requires explicit selection of another scope; changed native authority clears the old draft on rediscovery. |
| Verification and documentation | Real database/HTTP, full native/server/frontend/browser checks and build pass. API, configuration, product/roadmap and design references describe executable behavior and qualification limits. |

The browser suite reproduced a deletion-cancel focus regression introduced during this increment; keeping the triggering row control focusable fixed it. Review also found that a preserved draft could be submitted after a connection change. The native revision check now refuses that dispatch. The full frontend suite found an outdated local provenance hash from the earlier resampling change; the current local-file hash was renewed without changing its third-party upstream origin or attribution.

## Checks

| Check | Result |
| --- | --- |
| Focused terminology database/HTTP/configuration | 28 passed, no skips, using Postgres 17.11 and pgvector 0.8.0 |
| Focused terminology, correction, OpenAPI and startup wiring | 53 passed, no skips; includes the 28 cases above |
| Governed-knowledge Postgres suite | 19 passed, no skips |
| Full isolated portable server suite | 1,621 passed; 54 expected skips, including 18 terminology database/HTTP cases exercised separately |
| Full native Rust suite | 1,320 unit + 27 integration passed; 11 existing hardware/model exclusions |
| Frontend unit suite | 388 passed; two existing Windows exclusions |
| Focused Personalization browser suite | 16 passed |
| Full Chromium browser suite | 109 passed; one existing Windows-specific exclusion |
| Production frontend build | Passed |
| Native Linux debug application build | Passed (`pnpm tauri build --debug --no-bundle`); no installer or new physical launch qualification |
| Dependency license, documentation truth and provenance contracts | Eight passed |
| Focused Ruff, rustfmt and diff whitespace | Passed |

Commands use the [cloud environment](../../runbooks/cloud-development.md) and locked dependencies. The portable server wrapper has no external network or database credentials; the real database suites load the private local test environment without printing it. Browser fixtures exercise the UI/native contract, not a live identity or inference service.

Six local captures were inspected: team management, narrow draft and action views, revoked visibility with a retained cancellable draft, a team reader, and organization read-only empty state. At 1122×740 and 720×520, controls/text fit without horizontal clipping; narrow forms use normal vertical scrolling. Captures remain development artifacts under ignored `.tools/ui-audit/28-shared-team.png` through `33-shared-organization.png`. [Mobbin references](../ui-completion/2026-10-02-design-references.md) record inspected screens and flow steps; no third-party visuals are shipped.

## Sources and limits

The [policy](../../../server/src/yap_server/knowledge/terminology_policy.py), [runtime](../../../server/src/yap_server/knowledge/terminology_runtime.py), [service](../../../server/src/yap_server/knowledge/terminology_service.py) and [ledger](../../../server/src/yap_server/knowledge/terminology_ledger.py) retain canonical ownership. The [correction resolver](../../../server/src/yap_server/agents/transcript_correction_terminology.py) uses the same policy. [Native dispatch](../../../desktop/src-tauri/src/terminology.rs), [transport](../../../desktop/src-tauri/src/server_connector/terminology.rs), [UI control](../../../desktop/src/hooks/use-terminology.ts) and [Personalization](../../../desktop/src/components/settings/personalization-settings-section.tsx) bind the journey. The [API contract](../../specs/terminology-api.md) and [configuration](../../runbooks/cloud-development.md#enable-terminology-on-a-private-server) define the operator handoff.

Policy is immutable for a running server; grant changes require restart and client Refresh terms. This is explicit trusted configuration, not automatic directory integration or an in-product membership editor. CRUD and correction must use the same canonical database. Saving terms does not enable models or prove provider-specific effectiveness. Additional terminology projections, directory administration, Windows/WAM, enterprise deployment and inference qualification remain open in the [project goal](../../plans/active/2026-10-02-yap-project-hill-climb.md).
