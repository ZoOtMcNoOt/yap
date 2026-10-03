# Saved connection inspection

**Owner:** Grant McNatt. **Date:** 2026-10-03. **Status:** Six software outcomes verified in the development working tree.

A Curator connection previously ended with a copyable reference and no way to
reopen its sources. Knowledge → Review proposals now opens that reference or an
explicit **Inspect saved connection** handoff. It shows direction, type, rationale
and both exact excerpts, labeled as a proposal requiring human review. Reading
needs the organization knowledge service, but no reasoning model.

## Authority and preservation

The existing authenticated knowledge-read service selects only the principal's
proposed Curator relationship record. It checks central typed content, normalized
citations, proposal identity and inherited-policy checksum, then reauthorizes both
endpoints against the current reviewed generation. Unknown, foreign, hidden,
discarded and wrong-type references share 404. Owned stale generations return 409;
corrupt evidence, failed auditing and excess response size refuse partial output.
The transaction writes only content-free read audits; proposals and graph data
remain unchanged. Existing unstructured records are preserved without migration.

Each response contains exactly two source identities, revision/content hashes,
citation ranges and exact excerpts of at most 1,024 Unicode characters. Shared
limits remain two service reads, five-second SQL statements, one-second locks and
64 KiB ASCII-encoded JSON. Startup probes the proposal table alongside the five
existing ledger/audit tables, without provisioning or activation.

The main-window native reader shares existing bearer dispatch, current connection
leases, one read permit, cancellation and the 20-second deadline. It accepts only
a lowercase 64-character reference; strict decoding checks proposed status,
central candidate bounds, exact endpoint identities, source proof and quote
lengths. No renderer identity, human approval or canonical authority is accepted.
Native submission and inspection share the candidate validator. HTTP/native
projections use camelCase; the persisted typed proposal remains unchanged.

UI ownership hides old evidence immediately on account changes or a changed input.
Same-owner offline drafts remain editable, with reading disabled. Task changes
retain drafts and pending work. Cancellation retains busy state until the read
settles; late results cannot restore evidence or attach cancellation failures to a new
owner. The late-cancellation case reproduced without the epoch guard and passes
with it restored. A new explicit handoff cancels an
older inspection and waits before starting its replacement. Coordinator retains
its existing qualified summary-bundle workflow.

## Acceptance and checks

- [x] Read only the authenticated principal's proposed typed Curator record, validate its content/citation/inherited-policy checksum and current generation, and preserve all stored data.
- [x] Reauthorize both endpoints before returning exact bounded excerpts; unknown, hidden, discarded, wrong-type and foreign-owner references share an unavailable result. Changed knowledge refuses stale inspection.
- [x] Reuse bounded database/HTTP/native admission, redacted audits, strict response validation and current native connection leases without invoking models or accepting caller identity/authority.
- [x] Review proposals opens a pasted reference or the newly created connection, shows direction/type/rationale and exact citations, and clearly distinguishes a proposal from published knowledge.
- [x] Responsive keyboard controls, cancellation/retry, task changes and server/account changes preserve useful same-owner drafts while hiding stale/private results and containing delayed reads.
- [x] Real persisted/API tests, native boundary cases, browser journeys, builds and documentation verify inspection; canonical publication/rebuilding and reasoning/Windows qualification remain open.

## Checks

| Check | Result |
| --- | --- |
| New real Postgres/storage and authenticated HTTP | Nine passed, no skips. Includes actual persisted Curator output, owner/hidden/stale/corrupt refusal, exact quotes, unchanged graph/journal, busy slots, query restrictions and success-audit rollback on budget failure. |
| Focused native | Seven passed: three new proposal identity/source/transport cases and four existing graph/transport cases. |
| Focused Knowledge Chromium regression | 54 earlier Knowledge cases passed; the final inspection renewal passes ten cases, including card bounds and the reproduced late-cancellation regression. |
| Full frontend | 388 passed; two existing Windows-only exclusions. |
| Full native | 1,353 unit + 27 integration passed; 11 existing model/hardware ignores. |
| TypeScript/Vite and Linux Tauri debug/no-bundle | Passed on the final UI, with 18 existing platform-specific native warnings. |
| Documentation, license and provenance contracts; rustfmt and diff whitespace | Eight contracts passed; formatting and whitespace passed. |
| Isolated portable server | 1,639 passed; 96 declared platform/fixture/database skips (1,735 total). |
| Expanded real Postgres/service/API regression | 102 passed, no skips; renews the prior 93 cases and nine new inspection cases. |
| Full Chromium | 179 passed; one existing Windows-only island exclusion. All ten inspection cases renewed after the final retry-label accessibility change. |

Reproduce the new checks from the repository root:

```bash
source verification/cloud-env.sh
source .tools/postgres/env
PYTHONPATH=server/src:server server/.venv/bin/python -m unittest \
  tests.knowledge.test_connection_proposal_inspection \
  tests.api.test_connection_proposal_inspection_api -v
.tools/native/usr/bin/tini -s -- cargo test \
  --manifest-path desktop/src-tauri/Cargo.toml --locked server_connector::knowledge_connections
cd desktop
pnpm test:e2e connection-proposal-inspection.spec.ts
```

Full commands are in the [cloud runbook](../../../runbooks/cloud-development.md).
Development logs use `/tmp/yap-proposal-inspection-*-renewal.log`, with focused
checks in the corresponding `*-focused.log` / `*-second.log` files.

## Screen review

Actual system-Chromium captures were inspected at 1440 and 360 px with reduced
motion. Sources sit beside each other on desktop and stack on narrow screens;
long IDs/paths wrap. A reproduced intrinsic grid/button overflow is fixed with
constrained tracks and wrapping actions; tests now check card bounds as well as
page bounds. The review badge wraps inside its card, details are keyboard
operable, and stale proposals explain how to return to current sources. The
existing [design and Mobbin references](../../design-refresh/2026-10-03/review.md)
inform document reading and recovery; no additional animation/dependency is added.

- [Desktop proposal and expanded source details](01-saved-proposal-desktop.png)
- [Mobile exact sources and review status](02-exact-sources-mobile.png)
- [Mobile changed-knowledge recovery](03-stale-proposal-recovery.png)

## Remaining work

Inspection does not approve, publish or rebuild knowledge. Connections remains
six of seven overall outcomes; authorized human publication requires reviewed
repository provenance and complete projection before activation. Rebuild recovery,
actual connection reasoning and Windows/enterprise qualification remain open.
Database tests use deterministic Curator transport and synthetic fixture vectors;
browser tests use native-boundary projections. These are development checks,
not production inference, Entra or reviewed release-head evidence. The project-wide
goal stays active, with format expansion and every other workstream preserved.
