# Retain the selected export directory

**Owner:** Grant McNatt. **Date:** 2026-10-03. **Status:** Five of six outcomes verified locally; reviewed hosted integration pending.

An export could pass the “outside Yap data” check, then follow a replaced folder
into internal data when creating its file. Original transcripts, accepted
corrections and connection-review packages now retain one native directory owner
through staging, exclusive publication and cleanup. Source/history checks,
authenticated inspection and noncanonical proposal status keep their existing owners.

## Actual failures and correction

The Linux regression selects an external destination, renames its parent during
the source reread and puts a symlink to Yap data at the old path. The original
code reports **Saved** and creates `redirected.txt` in internal data. The
[recorded failure](original-failure.txt) retains that actual result; existing-file
protection was intact. The corrected regression refuses publication and leaves
the original transcript intact.

The [shared destination check](../../../../desktop/src-tauri/src/file_actions/export.rs)
now opens a [directory owner](../../../../desktop/src-tauri/src/atomic_text/new_file.rs)
before the source reread or second authenticated proposal read:

- Unix creation, exclusive rename, directory sync and cleanup use the owned
  directory descriptor. Ancestor identities are rechecked; replaced paths cannot
  redirect operations into their substitutes.
- Windows ancestor handles deny deletion/rename sharing, check volume/file
  identity and reject reparse points. Their actual execution still needs the
  hosted Windows gate and target qualification.
- Cleanup checks staging identity and keeps unrelated replacements. Nonblocking
  Unix inspection also preserves a substituted FIFO without waiting for a writer.

Actual-file checks cover selected-parent and ancestor substitution, a swap after
staging but before publication, failure cleanup and substituted staging entries.
The authenticated HTTP regression swaps the folder during its second read;
unchanged evidence cannot bypass the retained destination.

A late folder change can leave the export in the originally admitted directory
while returning uncertainty. The current repository writer also passes an actual
Linux directory-only `fsync`/`EIO` injection: [results](writer-results.txt) show
exact multilingual UTF-8 bytes still present, no staging, and retry refused as
`AlreadyExists`. Keep [inspection-before-retry guidance](../../transcript-export-recovery/2026-10-03/verification.md).
This is filesystem evidence, not crash-durability or native-picker qualification.
No dependency, automatic retry, deletion of a possible export or alternate export
writer is introduced.

## Local verification

| Check | Actual result |
| --- | --- |
| Complete Linux native suite | 1,383 unit + 27 integration passes; 11 declared model/hardware ignores. Includes real files and authenticated HTTP. |
| Linux Clippy, rustfmt and whitespace | Pass. Clippy retains existing Linux unused-import/unused-variable/dead-code allowances; strict Windows lint remains hosted. |
| Original, accepted and connection-review browser exports | All 36 related cases pass; native responses are fixtures. |
| Release contracts and WDIO adapter | 67 passes/five Windows-only skips (72 total); two adapter passes. |
| Documentation, licenses, provenance and browser population | All 14 checks pass; changed local file links resolve. |
| Frontend units/build and full browser regression | Unchanged renderer: earlier recovery baseline is 404 passes/two Windows-only skips and passing build; earlier selection baseline is 231 browser passes/one Windows-only skip. These were not rerun as this increment's full regression. |
| Hosted Windows and reviewed exact-head integration | Not run; GitHub authentication remains disconnected. |

```bash
source verification/cloud-env.sh
cargo test --manifest-path desktop/src-tauri/Cargo.toml --locked
pnpm --dir desktop test:e2e transcript-export.spec.ts accepted-correction-export.spec.ts connection-review-export.spec.ts
```

Historical [selection](../../accepted-correction-selection/2026-10-03/verification.md)
and [completion recovery](../../transcript-export-recovery/2026-10-03/verification.md)
receipts are preserved. Linux results do not qualify Windows sharing, reparse/ACL
behavior, picker/focus interaction or crash durability. No model or enterprise
runtime is qualified. Timed/speaker exports, history repair and the
[whole project queue](../../../plans/active/2026-10-02-yap-project-hill-climb.md)
remain open; reviewed six-job exact-head integration is still required.
