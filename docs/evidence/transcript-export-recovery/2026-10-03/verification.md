# Transcript export completion and recovery

**Owner:** Grant McNatt. **Date:** 2026-10-03. **Status:** Five of six software outcomes checked locally; reviewed hosted integration pending.

Original and accepted-correction exports share a new-file writer. A reported
write error can arrive after the complete destination exists. Recovery must
explain that uncertainty and ask the owner to inspect the chosen destination
before explicitly retrying. [User guidance](../../../specs/accepted-correction-history.md)
and the [active queue](../../../plans/active/2026-10-02-yap-project-hill-climb.md)
retain the scope and remaining work. Existing-file refusal and genuine picker
cancellation stay precise; other unconfirmed results retain inspection guidance.

## Actual failure reproduction

A scratch Rust harness imports the unchanged repository
[atomic writer](../../../../desktop/src-tauri/src/atomic_text.rs) and
[filesystem publication owner](../../../../desktop/src-tauri/src/atomic_file.rs).
A local Linux fault injector fails only directory `fsync` with `EIO`:

- The control run reports success and leaves the exact multilingual UTF-8 file.
- The injected run reports an error after publication, with that same exact
  destination present and no remaining staging file.
- Repeating the write refuses `AlreadyExists` and preserves the destination.

The observed order is file write/sync, exclusive rename, then directory sync.
The error therefore proves neither absence nor confirmed completion. This is a
real file/production-writer reproduction, not a native-picker or power-loss
qualification. The retained harness is `/tmp/yap-export-durability-reproduction`;
it adds no shipped dependency or production writer change.
[Recorded results](writer-results.txt) retain the three observed outcomes.

## Six acceptance outcomes

| Outcome | Verification status |
| --- | --- |
| Precise definite refusals and picker cancellation; generic write/join failures explain uncertainty and destination inspection | Shared native messages cover writer/join uncertainty; existing source/destination/cancellation cases pass. |
| Original receipts validate before saved/cancelled claims; malformed or misbound accepted receipts remain unconfirmed | Three original receipt cases reproduce false completion; the accepted misbound and blank-path cases reproduce missing guidance/validation. All pass after the fixes. |
| Feedback stays beside its original/accepted revision, retaining text, copy and explicit retry without automatic retry | Original/accepted text, explicit retry and keyboard focus pass. Narrow saved-export errors enter view only while its export button retains focus; choosing another control preserves focus and scroll. |
| Post-publication error retains exact destination bytes; no-replace publication and shared worker ownership remain intact | Real Linux writer reproduction and two new native file cases pass; retry refuses replacement and retains exact UTF-8 bytes. |
| Original/accepted browser recovery, malformed status/path, narrow/wide states and applicable native/frontend/build/contracts | All 38 related browser cases pass; applicable suite/build/contracts results are recorded below. |
| Recorded reviewed commit, push and six-job green exact-head integration | Local commit prepared; pushing and reviewed exact-head integration wait for GitHub access. |

Source/history checks and destination admission still refuse invalid preconditions
before publication. A genuine cancelled picker remains cancelled. Unconfirmed completion
must not claim saved or cancelled, trigger automatic retry, delete a possible
export or replace an existing destination. Retain the existing writer and export
permit through completion; no rollback or second writer is introduced.

## Current local checks

| Check | Actual result |
| --- | --- |
| Complete native suite | 1,377 unit + 27 integration passes; 11 declared model/hardware ignores. |
| Frontend units and production build | 404 passes, two Windows-only skips; TypeScript/Vite build passes. |
| Original/accepted export, selection and recovery browser regression | All 38 cases pass, including readable 360 px feedback and a late-failure focus/scroll case. |
| Release contracts and WDIO adapter | 67 passes/five Windows-only skips (72 total); two adapter passes. |
| Linux Clippy, native rustfmt and diff whitespace | Pass; Clippy retains existing platform-specific unused-import, unused-variable and dead-code allowances. Strict Windows Clippy remains hosted. |
| Documentation, licenses, provenance and browser population | All 14 cases pass; checked local file links resolve. |

The earlier selection increment's full 231-pass browser run remains its dated
baseline; this increment renews every related export/recovery/selection journey.
Native tests independently exercise actual files. Browser responses are fixtures,
so neither count establishes a native picker round trip or model quality.

[Original feedback at 720 px](original-720.png) and
[saved-correction feedback at 360 px](accepted-360.png) were inspected.
Both retain the explicit action and readable feedback without horizontal alert
overflow. The narrow view originally hid the error below the focused button;
its regression fails before the owned scroll and passes afterward. Scrolling
brings only that alert into view and never moves keyboard focus.

```bash
source verification/cloud-env.sh
cargo test --manifest-path desktop/src-tauri/Cargo.toml --locked
pnpm --dir desktop test
pnpm --dir desktop build
pnpm --dir desktop test:e2e transcript-export.spec.ts accepted-correction-export.spec.ts accepted-correction-recovery.spec.ts accepted-correction-selection.spec.ts
```

## Historical evidence and qualification

The [original export](../../transcript-export/2026-10-02-verification.md),
[accepted export](../../accepted-correction-export/2026-10-03/verification.md) and
[earlier-revision selection](../../accepted-correction-selection/2026-10-03/verification.md)
receipts remain unchanged records of their tested scopes. Their passing results
are not new completion evidence for this recovery increment.

This work changes export guidance and completion validation, not accepted text,
raw transcripts or history. No model is run or qualified. Linux fault injection
does not qualify Windows picker/focus, NTFS durability, path/ACL behavior or
enterprise deployment. Timed/speaker exports, history repair and the full project
goal remain open.
