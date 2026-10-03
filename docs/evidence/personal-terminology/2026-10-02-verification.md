# Personal terminology

**Owner:** Grant McNatt. **Date:** 2026-10-02. **Scope:** Development working tree; real local Postgres, deterministic HTTP authentication, Linux native transport and Chromium fixture journeys.

Source links follow the current generalized terminology owners after the 2026-10-03 shared-scope increment. The results below remain the historical personal-scope receipt.

Settings → Personalization now lists, creates, edits and deletes the signed-in
user's personal terminology. The server derives tenant/subject from the token;
the renderer supplies only vocabulary and version fields. Native dispatch owns
credentials, binds the approved server/session and rejects stale completion.
The service uses the existing append-only ledger, independent of inference.

## Acceptance

**Coverage: 9/9 defined software acceptance outcomes.** This verifies the
registered path at its database, HTTP, native and browser boundaries. Browser
tests simulate native receipts; they are not a live Windows/WAM round trip.

| Outcome | Evidence |
| --- | --- |
| Explicit authenticated model-independent service | Private credential/runtime tests reject disabled/implicit/development configuration. HTTP tests build the production service against real Postgres and advertise terminology while correction remains false. |
| Owner/tenant authority and safe denial | Database tests isolate users/tenants and reject forged payload grants; HTTP uses authenticated owner binding and indistinguishable foreign/missing 404s. Native leases require capability and reject stale commits. |
| Optimistic versions, append-only history and tombstones | Database create/edit/delete/reconnect and concurrent-edit tests preserve all versions with one winner. Native receipts must match the requested record, content and version. |
| Idempotent creation after lost response | Owner-bound mutation replay returns the original receipt without duplication or rollback. Browser simulates a committed response loss, retains the draft and retries with the same mutation ID. |
| Frozen existing snapshots and new-snapshot visibility | Real database tests preserve an old job snapshot after editing while a newly created snapshot observes accepted terminology. No provider-effectiveness claim follows. |
| Failure and conflict recovery | Browser retains drafts, compares latest content before explicit conflict resolution, and distinguishes acknowledged writes from failed list refreshes. Deletion requires confirmation and supports cancellation. |
| Settings lifecycle and identity clearing | Browser preserves drafts across section changes/offline recovery and one pending save across closing/reopening Settings. Sign-out clears personal drafts/data; late responses are guarded by the native session/route and renderer epoch. |
| Bounded readable keyboard flow | Ten-record pages, validated cursors, bounded content and four-MiB native response limit. Browser verifies paging, keyboard creation and focus restoration; list/conflict inspected at 1122×740 and narrow form at 720×520. |
| Explicit language selection | Browser checks that the asynchronously loaded primary preference initializes terminology language, controls remain explicit, and editing cannot change the immutable locale. |

Sources: [service](../../../server/src/yap_server/knowledge/terminology_service.py),
[configuration](../../../server/src/yap_server/knowledge/terminology_runtime.py),
[HTTP](../../../server/src/yap_server/api/terminology_requests.py),
[native client](../../../desktop/src-tauri/src/server_connector/terminology.rs),
[registered command](../../../desktop/src-tauri/src/terminology.rs),
[renderer owner](../../../desktop/src/hooks/use-terminology.ts), and
[settings](../../../desktop/src/components/settings/personalization-settings-section.tsx).

## Verification

- Focused database/HTTP/configuration: **16 passed, no skips** (seven persistence, four HTTP, five configuration). Tests use Postgres 17.11/pgvector 0.8.0 development storage and synthetic authentication, with no models.
- Full portable Python: **1,616 passed, 47 skipped** (1,663 total). Eleven additional skips are the database/HTTP cases verified separately above; 36 preexisting platform/fixture skips remain. Ruff passes.
- Native connector: **224 passed**, including five new transport/shape checks and one capability/stale-lease case. Full desktop Rust: **1,269 unit + 27 integration passed**, 11 existing model/hardware ignores. Locked dependencies and rustfmt pass; existing Linux warnings remain.
- Frontend: **388 passed, two existing Windows skips**; production build passes. Browser: **100 passed, one existing Windows skip**, including all nine Personalization cases.

Reproduce through [cloud development](../../runbooks/cloud-development.md):
load the private database environment and run the focused modules; use the
isolated portable server wrapper for process-containment tests. Desktop commands
are `cargo test --manifest-path src-tauri/Cargo.toml --locked`, `pnpm test`,
`pnpm build`, and `pnpm test:e2e`. Focused browser selection uses
`pnpm exec node tests/scripts/run-playwright-e2e.mjs tests/e2e/personalization.spec.ts`.
Test sources are the [database](../../../server/tests/knowledge/test_terminology_service.py),
[HTTP](../../../server/tests/api/test_terminology_api.py),
[configuration](../../../server/tests/knowledge/test_terminology_runtime.py),
[native](../../../desktop/src-tauri/src/server_connector/terminology/tests.rs), and
[browser](../../../desktop/tests/e2e/personalization.spec.ts) cases.
Canonical [Mobbin references](../ui-completion/2026-10-02-design-references.md)
record the inspected screens and flow previews; their assets are not shipped.

## Remaining boundary

Actual Windows/WAM identity, target interaction and enterprise deployment remain
unqualified here. Deploy the updated desktop/server capability contract together;
incompatible health shapes remain rejected. The service must share the canonical
terminology ledger with enabled correction workflows. Production database
versions, backup/retention and policy remain their own gates.

Personal CRUD does not complete terminology's team/organization management,
provider-native ASR hints, deterministic normalization or knowledge projections.
Those remain in the [project goal](../../plans/active/2026-10-02-yap-project-hill-climb.md).
Real effectiveness and inference quality require actual models; none is claimed.
