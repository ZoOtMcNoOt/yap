# Read earlier accepted corrections

**Owner:** Grant McNatt. **Status:** Six of seven software outcomes checked locally; reviewed hosted integration pending.

Choose an earlier accepted transcript revision to read, copy or export its exact
text. This works offline with a trusted saved transcript; it runs no correction
model. Reading an older revision leaves your latest acceptance and original
transcript unchanged.

## Choose a revision

1. Open a finished transcript from **History**, then **Review corrections**.
2. The latest accepted revision loads first. If more than one is saved, use
   **Accepted revision** to choose another. The newest option is marked **Latest**.
3. Compare the selected **Saved revision N** with the original. When a new
   suggestion is also visible, expand **Read the previously accepted revision**
   to read the selected saved text separately.
4. Use **Copy saved correction** or **Export saved correction** for that selected
   revision. Copying a suggestion and saving a new revision remain separate actions.

There is no history selector when only one revision is saved. If none is saved,
Yap says so. Selection reads existing history; it does not restore an older revision
as latest, accept new edits, delete revisions or repair damaged history. Saving a
new acceptance reloads the latest revision and resets an older selection, even
when its corrected text matches another revision.

## Export the selected text

Choose a new `.txt` file outside Yap's internal data folder. The default filename
is `transcript-corrected-rN.txt`. Export preserves the selected text's exact UTF-8
bytes and adds `.txt` if you omit an extension. Existing destinations are preserved.

The native worker reads the selected revision before the picker and again after
selection. A changed original, changed revision/count, or invalid history prevents
export. Selection stays disabled during export; finish or cancel the native picker
there. A saved receipt identifies the exported revision and destination.

For both **Export text** and **Export saved correction**, an unconfirmed result
means a file may already have been saved. Inspect the destination before trying
again; choose another new filename if needed. Yap retains source text and never
retries automatically or removes a file to turn an uncertain result into a failure.

## If saved history is unavailable

| What happens | Recovery |
| --- | --- |
| History cannot be read or a selected revision is missing | Use **Retry saved corrections**. Original and revision files stay intact. |
| History changes while choosing an export destination | Use **Refresh saved corrections**, review the selected text, then export again. |
| Destination already exists or is unavailable | Choose another new filename or folder. |
| Export could not be confirmed | Check the chosen destination first; a file may exist. Retry only explicitly. |
| You switch transcripts or revisions during a read | Yap hides stale text and ignores that read's late result. |

Yap refuses damaged or inconsistent history as a whole; selecting an older entry
cannot bypass a damaged later one. It does not silently fall back to another
revision or modify files to make a read succeed.

## Source and history checks

Native recovery validates the complete ordered hash chain and binds **every entry**
to the current original transcript's source revision and text hash. It rereads the
trusted source before returning the selected entry and total revision count.
Limits remain **64 revisions**, **192 KiB per artifact** and **32,768 corrected
Unicode characters**. Linked, nonregular, oversized, malformed, incomplete or
staged histories are refused without cleanup.

The renderer sends an original transcript path and optional revision number;
it cannot supply corrected text or a revision-file path as authority. Existing
native source owners and the shared new-file export owner retain those decisions.

## Verification and remaining work

[Selection evidence](../evidence/accepted-correction-selection/2026-10-03/verification.md)
records local checks and screen captures. [Export recovery](../evidence/transcript-export-recovery/2026-10-03/verification.md) records its separate verification status. Earlier
[latest-only recovery](../evidence/accepted-correction-recovery/2026-10-03/verification.md)
and [export](../evidence/accepted-correction-export/2026-10-03/verification.md)
receipts remain historical. The selection increment's complete Linux browser
regression passed; export recovery renews 38 related cases. Reviewed hosted
integration is pending. Physical Windows picker, clipboard and filesystem behavior need target
checks. No model quality is qualified; timed/speaker exports and explicit history
repair remain in the [project queue](../plans/active/2026-10-02-yap-project-hill-climb.md).
