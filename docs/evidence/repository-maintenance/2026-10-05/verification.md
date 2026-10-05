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

PR #210 then exposed a cancelled-warmup destruction ownership race in its hosted
native suite. Its [separate acceptance and repair](../../timed-speaker-export/2026-10-05/warmup-destruction-repair.md)
requires inclusion and fresh native verification before this final maintenance
candidate can integrate. The renderer source exercised by the full browser run
is unchanged by that native repair.

Both committed clean-checkout contract sets, final corrected native renewal,
independent final-head review and all six hosted gates remain pending. Preserve
every original failure; final integration must name actual results and exact heads.
