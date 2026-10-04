# Earlier accepted correction selection

**Owner:** Grant McNatt. **Date:** 2026-10-03. **Status:** Six of seven software outcomes checked locally; reviewed hosted integration pending.

Correct can select an earlier accepted revision, read it alongside the original,
and copy or export its exact text offline. Latest remains the initial selection.
These operations neither accept edits nor change the original, latest acceptance
or saved history. [User guidance](../../../specs/accepted-correction-history.md)
and the [project queue](../../../plans/active/2026-10-02-yap-project-hill-climb.md)
retain the flow and remaining work.

## Verified boundaries

- Native reads validate the entire ordered chain, including entries after the
  selected one. Every entry must match the current original source revision and
  text hash; even a consistent chain cannot substitute a foreign source hash.
- Actual files verify earlier-revision reopening, exact multilingual UTF-8 export,
  retained original/revision bytes and an unchanged latest revision. Invalid,
  missing or damaged selection refuses without deletion or repair.
- Recovery retains 64-entry, 192-KiB artifact and 32,768-character bounds. Existing
  source admission, bounded read ownership, private history and link/staging
  refusal remain in force.
- Export rereads the same selected revision before and after the native picker.
  Changed source, selected entry/count or invalid history refuses publication.
  The shared new-file writer preserves existing/internal destinations and retained
  history; the worker owns admission through completion.
- The source/selection-bound renderer checks returned path, source hashes,
  selected revision and total count. Late, misbound and source-switched reads
  cannot expose substituted saved text or enable its export. Read failures retain
  original access and an explicit retry for the selected revision.
- A keyboard-accessible selector appears for multiple revisions. Offline copy and
  export use the selected entry; selection is disabled while export is active.
- A new acceptance reloads the latest history and resets an earlier selection.
  Refresh follows the native immutable revision path, so equal corrected-text
  hashes cannot confuse two distinct acceptances.

## Current checks

| Check | Actual local result |
| --- | --- |
| Complete native suite | 1,375 unit + 27 integration passes; 11 declared model/hardware ignores. |
| Frontend units | 404 passes; two declared Windows-only skips. |
| TypeScript/Vite production build | Passed. |
| Final focused browser regression | All 27 cases pass, including nine selection cases, same-text acceptance refresh and actual keyboard selection at three widths. |
| Complete browser regression | 231 passes; one declared Windows-only island skip (232 total), 10.8 minutes. |
| Release contracts | 67 passes; five declared Windows-only skips (72 total). |
| WDIO framework adapter | Two passes; native Windows WDIO remains a hosted check. |
| Documentation, licenses, provenance and browser population | All 14 cases pass. |
| Native Clippy/rustfmt and diff whitespace | Passed; Linux Clippy retains existing platform-specific unused-import, unused-variable and dead-code allowances. Strict Windows Clippy remains a hosted check. |
| Reviewed hosted integration | Pending while GitHub authentication is disconnected. |

Reproduce the focused checks from the repository root:

```bash
source verification/cloud-env.sh
CARGO_INCREMENTAL=0 cargo test --manifest-path desktop/src-tauri/Cargo.toml --locked transcript_correction
pnpm --dir desktop test:e2e accepted-correction-selection.spec.ts accepted-correction-recovery.spec.ts accepted-correction-export.spec.ts
```

The focused browser cases cover offline selection/copy/export at three widths,
late reads, switching transcripts, damaged-history retry, misbound receipts,
retained selection during export and repeated pending selection. Browser responses
are fixtures; native file checks independently establish source/history
preservation and export bytes.

The final refresh case first accepts revision 2, selects revision 1, then accepts
identical corrected text as revision 3. Text-hash-only publication ownership left
the stale selection visible; immutable `revisionPath` ownership reloads revision 3.
A second regression reproduced a pending read stuck after selecting its revision
again. Selection now leaves the existing read epoch intact when its effective
revision is unchanged. Both cases and all 27 focused browser checks pass on the
final behavior. Frontend units/build and the complete browser regression pass.
All checked local file links in changed documentation resolve; the documentation
review retains original feature goals and unchanged historical receipts.

## Screens and provenance

Actual Chromium captures were inspected at [360 px](revision-360.png),
[720 px](revision-720.png) and [1440 px](revision-1440.png). Actions wrap on narrow
screens, the selector and selected revision stay readable, and the original/saved
comparison stacks before using desktop columns. Focus remains on the explicit
export action. Browser assertions check no horizontal page overflow.

This increment reuses the existing design, native history/source owners and export
writer; it adds no dependency or external asset. Historical
[latest-only recovery](../../accepted-correction-recovery/2026-10-03/verification.md)
and [latest-only export](../../accepted-correction-export/2026-10-03/verification.md)
receipts are preserved rather than rewritten as evidence for this selection work.

## Qualification

These are Linux development checks, not an exact-head reviewed release. Hosted
Windows checks and physical picker/focus/clipboard, path, ACL and no-replace
behavior remain separate. No correction model was run or qualified. Reading
saved accepted text establishes neither suggestion quality nor production
enterprise operation. Timed/speaker export and explicit history repair remain
open; the project goal continues across the full queue.
