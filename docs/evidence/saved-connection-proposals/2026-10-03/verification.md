# Discover saved connection proposals

**Owner:** Grant McNatt. **Date:** 2026-10-03. **Status:** Five software outcomes verified locally; hosted integration pending.

Previously, Review opened a copied reference or an explicit Curator handoff. It could not discover the current owner's saved proposals. Review now offers an explicit Load/Refresh action, a dated list and keyboard selection. Exact source details remain behind current permission checks. The manual reference field stays available in a disclosure.

## Acceptance

| Outcome | Evidence and boundary |
| --- | --- |
| Authenticated owner metadata only | Actual PostgreSQL and HTTP cases separate tenant/subject owners and exclude discarded/other-type entries. The response contains only proposal references and UTC creation times; it exposes no source text, candidate, foreign counts or caller identity selectors. |
| Complete, bounded, read-only discovery | The existing 64-proposal cap bounds the complete list. Invalid references, timestamps or a 65th row refuse the entire response. Existing admission, SQL timeouts and 65,536-byte response budget apply. Content-free audits share the read transaction; journal and published graph remain unchanged. |
| Strict native ownership | Existing main-window/current-lease command sends authenticated GET `/v1/knowledge/connection-proposals` without selectors. Native decoding rejects extra fields, wrong schema, duplicates, malformed references, invalid calendar/non-UTC timestamps and excessive rows. No new command, credentials or dependencies. |
| Explicit accessible discovery | Load/Refresh and selection work at 360/720/1440 px with keyboard access. Empty, failed, corrupt and offline states keep source navigation and manual recovery. Selecting a stale/hidden owned reference does not grant source access. |
| Confirmed cleanup and recovery | Only confirmed discard removes its row locally. Uncertain delivery retains the exact retry reference and disables list selection, refresh and manual editing. Offline/account changes hide metadata; late receipts cannot populate another owner's view. Reads expose Cancel even with the manual disclosure closed and retain the native slot until completion. |
| Reviewed integration | Local and hosted receipts will be recorded below. Production/model/enterprise qualification remains separate; the project goal stays active. |

[Inspected Mobbin references](../../ui-completion/2026-10-02-design-references.md#saved-proposal-discovery) informed dated rows and deliberate detail selection. Metadata has no safe source title, so rows show a shortened reference and creation time. Full references remain accessible to assistive technology and in the manual field.

## Verification

- Real PostgreSQL/API: **20 passed, no skips**, covering eight discovery storage cases, existing discard invariants and six authenticated HTTP cases. OpenAPI: **18 passed**.
- Linux native: **1,366 unit + 27 integration passed**, 11 declared model/hardware ignores. Two new cases cover actual authenticated HTTP and strict list decoding, including 64 valid entries and malformed/oversized receipts.
- Frontend: **396 units passed, two declared Windows-only skips**; TypeScript/Vite build passed. **50 related browser cases passed**, then **31 inspection/discovery cases passed** after adding visible-detail focus and a regression for completion in another task. Screens retain [360 px list](screens/saved-list-360.png), [360 px selected details](screens/saved-selected-360.png), [720 px](screens/saved-list-720.png) and [1440 px](screens/saved-list-1440.png).
- Portable server: **1,640 passed, 114 declared exclusions** (1,754 total); the ten added PostgreSQL/API cases are exercised separately above. Linux native debug build passed with existing platform-specific unused-code warnings. Release contracts: **66 passed, five Windows-only skips** (71 total). Ruff and all seven documentation/population contracts passed.
- Review found hidden inspection cancellation and editable uncertain-discard references. Both are corrected, with browser regression coverage. PR review also caught a helper overriding `unittest.TestCase.fail`; renaming it restores standard assertion reporting. A deliberate `assertIsNone` failure enters the pending helper on the old code and raises the correct `AssertionError` after the fix. All 20 PostgreSQL/API and seven documentation/population cases pass again.

Hosted checks and exact integration head are pending. Browser fixtures verify interaction; actual SQL and native TCP tests verify persistence/transport without models. This does not qualify inference, physical Windows input, private identity or enterprise deployment. Issue [#92](https://github.com/ZoOtMcNoOt/yap/issues/92) remains open until an actual Windows RDP/session-lock responsiveness check passes.

## Repeatable checks

```bash
source verification/cloud-env.sh
source .tools/postgres/env
(cd server && PYTHONPATH=src .venv/bin/python -m unittest tests.knowledge.test_pending_connection_proposals tests.knowledge.test_connection_proposal_discard tests.api.test_connection_proposal_inspection_api -v)
(cd desktop/src-tauri && CARGO_INCREMENTAL=0 cargo test --locked)
pnpm --dir desktop test
pnpm --dir desktop build
YAP_PLAYWRIGHT_REUSE_SERVER=0 YAP_PLAYWRIGHT_VIDEO=off pnpm --dir desktop test:e2e saved-connection-proposals.spec.ts connection-proposal-inspection.spec.ts connection-proposals.spec.ts connections.spec.ts
bash verification/test-cloud-server.sh
```

Do not print or commit the local database environment. Hosted server checks currently exclude real PostgreSQL cases; adding that repeatable gate remains in the execution queue.
