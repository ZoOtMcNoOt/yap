# Repository maintenance verification

Owner: Grant McNatt. Date: 2026-10-05 UTC.

The [single execution queue](../../../plans/active/2026-10-02-yap-project-hill-climb.md)
records five bounded acceptance outcomes before implementation at `97e665ff`.
The whole-repository audit found focused duplication and four verified unused or
generated files.

Two private helpers in the existing native connector owner consolidate twelve
typed lease constructors and twelve commit guards. Feature capability predicates,
client types, error messages, configured origin/generation binding and Ready
checks remain explicit; the connector lock remains held through typed lease
construction and commit. A regression checks lock ownership during publication
and loss of either required batch capability without a generation change.

Analyst and Coordinator now share request presentation lifecycle through
`use-request-lifecycle.ts`; their drafts, validation, native arguments, response
types and guidance remain feature-owned. Review found that an already pending
status read could overwrite terminal cancellation: the shared owner now checks
both request identity and epoch after every awaited poll. Two browser regressions
exercise that ordering and preserve Retry's submitted draft after a later edit.
Existing owner-change, delayed submission/cancellation and offline journeys remain.

Static import/re-export/require checks found no consumers of `field.tsx`,
`progress.tsx` or `use-elapsed-seconds.ts`; these files and generated
`tsconfig.tsbuildinfo` are removed. Regenerated TypeScript metadata is ignored.
Packaging assets, original recordings, licenses, provenance, lockfiles and dated
historical evidence remain. The Tao reproduction harness is explicitly historical
and retained; the ECAPA/Tiron research is indexed with its qualification limits.

Current status, roadmap, architecture and ADR implementation notes now preserve
all 31 decision-register dispositions and credit actual delivered publication,
rebuilding, role cores and terminology projections. Pending PRs and target
qualification retain their separate boundaries. This is maintenance progress,
not complete product or model/physical Windows/enterprise qualification.

## Actual local verification at `243f0dfe13252294ce08a5684f280c004242e829`

| Check | Observed result |
| --- | --- |
| Full Linux native suite | 1,407 units and 27 integrations pass; 12 declared fixture/model ignores. New capability/lock regression passes. |
| Actual built-native rebuilding journey | Exactly one authenticated HTTP/PostgreSQL source/stage/embedding/publication/replay/retained restore journey passes, zero skips, using a fresh owned pinned disposable PostgreSQL 17.11/pgvector 0.8.7 container; owned cleanup succeeds. Synthetic identities/vectors only. |
| All-target Clippy | Passes `-D clippy::all`; existing Linux platform warnings remain separate from Windows strict lint. |
| Full frontend units | 417 pass across 70 files, two declared Windows-only exclusions. The first sandbox run's denied loopback listener remains a failed observation; renewal with test binding available passes. |
| TypeScript and production Vite build | Pass. |
| Full serial Chromium browser suite | 260 pass, one Windows-only exclusion, 10.6m. Includes both new stale-poll/Retry regressions. Own Vite cache and bundled artifact; no competing heavy checks. |

Full logs and failure artifacts remain outside Git under
`/tmp/yap-maintenance-{native-full,native-postgres,clippy,frontend-renewed,build,browser-full}.log`
and `/tmp/yap-maintenance-browser-full-results`. Counts describe observed runs,
not model/provider or physical Windows qualification. The default native suite
ignores the real PostgreSQL fixture; it was explicitly executed separately with
its actual built binary and no skip.

## Corrected combined native and clean-checkout renewal

The reviewed source at `d3d5a3123fb58ca696a1f3528913693b3132bf55` includes
PR #210's [cancelled-load destruction repair](../../timed-speaker-export/2026-10-05/warmup-destruction-repair.md).
Full native renewal passes 1,409 units and all 27 integrations, with 12 declared
fixture/model ignores (2m12s compilation, 30.51s units). All-target Clippy passes
`-D clippy::all` (25.58s), retaining the previously reported Linux platform warnings.
The exact final built-native PostgreSQL/HTTP journey is explicitly renewed:
one pass, zero skips, 0.41s, with owned disposable-container cleanup successful.
An initial extra renewal selected system Python and failed before running tests
because psycopg was unavailable; `uv run --project server --no-sync` selects the
locked runtime and succeeds. Logs retain both observations.

Both complete clean-checkout contract sets pass on this committed candidate:
67/72 release cases with five declared Windows/platform exclusions and 71/86
local cases with 15 exclusions; no failures. All 30 documentation, dependency,
provenance, model-provenance, population and workflow contracts pass with no skips.
The earlier full frontend/build/browser source is unchanged by the native repair.
Independent read-only review of both original maintenance source and the combined
`d3d5a312` candidate reports no unresolved actionable findings.

Corrected logs: `/tmp/yap-maintenance-native-final.log`,
`/tmp/yap-maintenance-clippy-final.log`,
`/tmp/yap-maintenance-native-postgres-final{,-renewed}.log`,
`/tmp/yap-maintenance-clean-all.log`, and
`/tmp/yap-maintenance-documentation-contracts.log`. Final metadata changes require
clean-contract renewal and independent exact-head review. All six hosted jobs
must pass on the unchanged reviewed final head before ordered integration after
PRs #210 and #211; preserve tested tags, fetched-main tree equality and unique
successors before completed branch/worktree retirement. The full roadmap remains active.

## Hosted source verification and ancestry renewal

[Run 574](https://github.com/ZoOtMcNoOt/yap/actions/runs/37281864081) passes all
six required jobs and every final unchanged-checkout guard on independently
reviewed `5438a899c8303746d3f8948af671264a92519644`, attempt 1. Windows
verification passes 1,404 native units and all 27 integrations/12 declared
fixture ignores, strict Clippy `-D warnings`, both exact connector runtime
checks, dependency boundary/audit, 419 frontend units, 72 release contracts,
two WDIO framework contracts, TypeScript/Vite and all 261 browser cases (5.2m).
The actual built Windows app smoke, skip-free owned-process/PostgreSQL checks,
core server suite and orchestrator checks also pass. Linux and Windows native
populations differ by their compiled platform-specific cases; no model or
physical Windows qualification is inferred. Annotated tag
`reviewed/pr-212-5438a899` preserves this tested source head.

After PRs #210 and #211 integrated, GitHub refused PR #212's merge with HTTP405
and stated merge conflicts. Local Git's ort strategy computed the exact tested
tree without conflicts, with two merge bases (`12088dea` and `8e774f73`).
An explicit merge of fetched main `55109ef46c9cc8ca90e97b563fd4b90eb732dcb1`
produces `babdc2ff43e1982298a8aaf521ef9c6ebe90a958` with the identical entire
tree `bbf044c1658d67daec1f0f25a4a26328b3d0398b`, and one unambiguous main
ancestor. This is an ancestry repair; executable source has not changed.

The following metadata renewal records actual parent integrations and preserves
this original failed merge observation. Its final reviewed head requires both
clean-contract sets and all six hosted gates to pass again. [PR #212](https://github.com/ZoOtMcNoOt/yap/pull/212)
is the live integration record; preserve the final tested tag and compare the
fetched main tree before retiring the completed temporary branch/worktree.
