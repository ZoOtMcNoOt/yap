# Curator connection proposals

**Owner:** Grant McNatt. **Date:** 2026-10-03. **Status:** Six software outcomes verified in the development working tree.

Curator previously reviewed statements and Student answers; the typed connection journal had no desktop review journey. The existing workflow now accepts one directed relationship and two cited search excerpts. It records a proposal for human review without changing the canonical graph. The [project goal](../../../plans/active/2026-10-02-yap-project-hill-climb.md) remains active; canonical publication and rebuilding are still open.

## Boundaries

- `reviewed-connection` reuses the central strict candidate contract: two distinct endpoint IDs, a bounded type and rationale, exactly two citations and the current generation. Content is normalized before replay hashing. Extra fields, duplicate JSON keys, authority claims and mismatched endpoints fail before review.
- Connection review supplies the frozen direction/type/rationale and both identified excerpts to Curator's existing binary decision tool. Summary and Student input contracts retain their scope. Similarity alone is insufficient; the decision cannot rewrite the suggestion or choose evidence. The existing admission and runtime owners remain in use.
- Source resolution checks current visibility, revision, hash and exact compiled excerpt spans. Publication rereads the evidence inside the transaction, then records a typed relationship proposal and audits atomically. Failure, cancellation, hidden sources and generation changes cannot publish it. Replay is owner scoped; changed intent with the same submission ID conflicts. Graph generations and canonical edges remain unchanged.
- Native code derives the two citations and generation from a completed Librarian query it owns. The renderer sends its query ID, two result indexes, type, rationale and connection revision. Both captured leases must be current; Curator submissions also bind the revision. Foreign queries, incomplete results, identical concepts and excerpts over 1,024 characters are refused without cropping.
- The form offers source selection, direction reversal, type suggestions, inspected excerpts and a rationale. Pending review/cancellation locks editing; task changes preserve the draft. New source results or account changes remove the old form and contain late jobs. Rejection explains insufficient support; failures and cancellation allow retry. A created proposal provides a reference for the organization's review process.

The same Curator hook handles Student answers and connections. It now keeps pending submission/cancellation state until acknowledgement, hides prior-source results immediately and prevents duplicate cancellation during invalidation. No new role, graph database, animation library or dependency is added.

## Checks

| Check | Result |
| --- | --- |
| New server cases | 11 passed: four portable contract/model-input, five real-Postgres and two authenticated HTTP/worker cases. Includes an actual Librarian-to-Curator source-proof round trip. |
| Desktop frontend | 388 passed, two existing Windows-only exclusions; TypeScript/Vite production build passed. |
| Native suite | 1,334 unit and 27 integration passed, 11 existing model/hardware ignores. Four new cases cover owned source pairs and typed request bounds; the existing stale-revision case also covers Curator. |
| Full Chromium suite | 152 passed, one existing Windows-only island exclusion. Nine added cases cover direction/layout, bounded distinct sources, retry/rejection, task preservation, source changes and delayed account/cancellation cleanup. |
| Isolated portable server | 1,639 passed, 87 declared platform/fixture/database skips (1,726 total). |
| Expanded local database/service regression | 93 passed, no skips; renews the prior 82-case agent/compiler/storage/API set and all 11 new cases. |
| Linux application | Tauri debug/no-bundle build passed; 18 existing platform-specific warnings. No Windows or installer qualification. |
| Ruff, native formatting and diff whitespace | Passed. |
| Documentation, dependency-license and provenance contracts | Eight passed on the final documentation update. |

The actual resolver, publisher, journal, audit and result persistence run against
private local Postgres with a deterministic decision transport. Synthetic vectors
are test fixtures, not inference or corpus evidence. The isolated suite skips
the seven new database/HTTP cases; all seven pass
in the explicit local database run. Prior terminology, Connections and typed
candidate database exclusions also retain their real-Postgres receipts. No
production model runtime was started.

Reproduce the new checks from the repository root:

```bash
source verification/cloud-env.sh
source .tools/postgres/env
PYTHONPATH=server/src:server server/.venv/bin/python -m unittest \
  tests.agents.test_curator_connections \
  tests.agents.test_curator_connections_postgres \
  tests.api.test_curator_connections_api -v
cd desktop
pnpm test:e2e connection-proposals.spec.ts
```

The broader commands are in the [cloud runbook](../../../runbooks/cloud-development.md).
Development logs are `/tmp/yap-curator-{browser,unit,native,server,postgres,build,native-build}-renewal.log`;
Ruff uses the documented server working directory. These development results
do not constitute a reviewed release head.

## Screen review

Actual Chromium captures were inspected with reduced motion enabled. Desktop
keeps source selection on one row; narrow windows stack the selectors, direction
control and cited excerpts. The mobile flow scrolls to its rationale and action;
its page has no horizontal overflow. Selection text can truncate in native
controls, with complete IDs and exact text available in source details. The
proposal result keeps human review and its copyable reference visible. This
extends the [shared design](../../design-refresh/2026-10-03/review.md) and existing
citation component; no additional glass layer, force simulation or motion is used.

- [Desktop review, 1440 px viewport](01-review-desktop.png)
- [Mobile source selection, 360 px viewport](02-review-mobile.png)
- [Mobile excerpts, rationale and action](04-review-mobile-actions.png)
- [Proposal result, 720 px viewport](03-proposed-tablet.png)

## Qualification and next work

Existing Curator model receipts qualify their recorded statement/Student inputs. They do not qualify this new identified-source-pair prompt. Before production promotion, collect actual connection reasoning evidence for support, direction, relationship type, unrelated/shared-word sources and injected instructions; renew the relevant model/capacity and release gates. Browser bridge fixtures do not qualify native identity or Windows behavior.

The current product creates a noncanonical proposal only. Human canonical publication needs an authorized review process, reviewed source revision, complete projection and generation activation. Rebuild recovery must preserve those owners and refuse partial activation. Neither this form nor a deterministic model response supplies human approval, Git provenance or real embedding vectors.
