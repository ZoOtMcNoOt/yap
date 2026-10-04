# Export a connection proposal for human review

**Owner:** Grant McNatt. **Date:** 2026-10-03. **Status:** Five local software outcomes verified; exact-head integration pending.

Owners can now export an inspected connection proposal and its two source excerpts
into their organization's Git review workflow. The package preserves proposed
status. Export neither discards the suggestion nor publishes a canonical edge.
[User steps and file contract](../../../specs/connection-review-package.md) explain
review, recovery and the remaining publication boundary.

## Acceptance

| Outcome | Evidence |
| --- | --- |
| Bounded exact evidence | Strict authenticated proposal decoding feeds readable version-1 JSON, capped at 65,536 bytes including its final newline. Native checks retain the exact candidate, two endpoint identities/revisions/hashes/Unicode spans and quotes, excluding session fingerprints and inferred approval. |
| Current native authority | The main-window command accepts only proposal/generation references and connection revision. Both inspections use the existing authenticated service route; current-generation and native lease checks bind publication to its owner. Renderer quotations and destinations cannot supply authority. |
| Explicit new-file publication | Actual temporary files verify UTF-8 bytes, implicit/case-insensitive JSON extensions, private Unix permissions, existing-file/staging preservation, invalid destinations and internal-directory aliases. Actual TCP reinspection refuses revoked, discarded, expired, stale or changed evidence before any file is created. Existing original/accepted exports share the same worker permit and destination owner. |
| Accessible recovery | Seventeen export browser cases cover keyboard/focus, 360/720/1440 px, picker cancellation, destination/refusal/uncertainty, owner changes, offline late results, duplicate activation and queued Curator handoffs. Long paths stay behind a keyboard-accessible, height-bounded location disclosure. |
| Appropriate checks and provenance | Full native/frontend unit checks, production frontend build, existing release/documentation/license/provenance gates and simulated browser checks exercise the software without adding dependencies or changing source/graph data. |
| Reviewed integration | Pending: restore GitHub access, push the reviewed iteration, pass all six exact-head jobs, merge, retain the tested head and retire its branch. |

## Verification

- Linux native: **1,372 unit + 27 integration passes**, with 11 declared model/hardware ignores. The six new cases include one Unix-only filesystem case. After correcting Windows path-prefix and case-insensitive fixture assumptions, **all 19 focused connection cases pass** again. Original and accepted export regressions are included in the full suite.
- Native TCP/files: two authenticated GETs exercise current inspection across the picker interval, followed by real atomic file publication. Scenarios cover success, 403 revocation, 404 discard/unavailability, 401 expiry, generation change and changed candidate evidence. This simulates the picker interval; it does not automate a physical picker or a production identity provider.
- Frontend: **400 unit passes and two declared Windows-only skips** (402 total), including four new receipt cases. TypeScript/Vite production build passes. **All 17 export browser cases pass** on the corrected UI; 31 related inspection/discovery cases also pass. **Full Linux browser regression passes: 221 cases, one declared Windows-only island skip** (222 total, 10.5 minutes).
- Existing release contracts: **67 passes, five Windows-only skips** (72 total). WDIO framework adapter: **two passes**. Documentation, licenses, provenance and population: **11 passes**. Frontend audit passes its existing policy with one low finding.
- Linux Clippy passes with the existing platform-specific unused-import/variable/dead-code categories allowed. Hosted Windows strict Clippy and native runtime checks remain pending. Rustfmt and diff whitespace pass.

The screen review found excessive narrow-screen height from long saved paths.
The final UI keeps the confirmation compact and exposes the complete location on
demand: [360 px](saved-360.png), [720 px](saved-720.png), [1440 px](saved-1440.png).
Expanded locations remain bounded and wrap: [360 px](location-360.png),
[720 px](location-720.png), [1440 px](location-1440.png).

A native worker owns both read/export permits through picker, reinspection and
publication. UI disappearance cannot release that ownership or promise a cancelled
write. An I/O error can occur after publication, so unconfirmed export always tells
the user to check the destination. Account changes hide private paths and evidence;
they cannot undo an already saved file. New-file semantics preserve existing work.

## Repeatable checks

```bash
source verification/cloud-env.sh
(cd desktop/src-tauri && CARGO_INCREMENTAL=0 cargo test --locked --no-default-features)
pnpm --dir desktop test
pnpm --dir desktop build
YAP_PLAYWRIGHT_REUSE_SERVER=0 pnpm --dir desktop test:e2e
pnpm --dir desktop test:release-contract
pnpm --dir desktop test:wdio-framework
```

Human canonical publication, source admission and complete embedding/rebuild
activation remain separate open work. These checks do not qualify model reasoning,
production vectors, private enterprise policy, physical Windows picker/focus/filesystem
behavior or RDP/session-lock responsiveness. Issue [#92](https://github.com/ZoOtMcNoOt/yap/issues/92)
and the entire project goal remain open.

## Integration handoff

Implementation commit `9cb8d310df6e3069eab2d78a977406cb45983a94` is retained
locally on `feat/connection-review-package`. Its push was rejected by GitHub;
the connector independently reports `USER_NOT_LOGGED_IN`. Hosted checks, a PR
and merging are therefore pending restored access. No remote integration is claimed.
The project goal continues through available local software work.
