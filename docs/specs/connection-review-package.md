# Connection review package

**Owner:** Grant McNatt. **Status:** Implemented; integration verification pending.

Export a saved connection proposal and its two cited excerpts for Git review.
The suggestion stays **proposed**: export does not approve or discard it, publish
a graph edge or activate a generation. The [active queue](../plans/active/2026-10-02-yap-project-hill-climb.md#current-increment-export-a-connection-review-package)
tracks verification and the remaining publication work.

## Export a proposal

1. Open **Knowledge → Review proposals**, load your saved proposals and open one.
   You need a ready organization-server connection with knowledge browsing enabled.
2. Read the rationale and both source excerpts. Choose **Export review package…**.
3. In the native file picker, choose a **new `.json` file** outside Yap's internal
   data folder. Yap adds `.json` if you omit an extension. It preserves existing
   files, including a destination you accidentally select.
4. After Yap confirms the export, expand **Saved file location** to read its path.
   Take the package into your organization's
   authorized Git review workflow. The file contains readable source excerpts;
   choose a location whose readers may access them.

Yap authenticates and inspects the proposal before the picker and after selection.
The candidate, evidence and generation must still match. Lost access, discard or
a changed account/server prevents a new export. A package is not a permission
grant or proof of a reviewer's current access.

## If export does not finish

| What you see | What to do |
| --- | --- |
| Picker cancelled | The proposal and sources stay saved. Export again when ready. |
| File already exists or destination rejected | Choose another new `.json` file outside Yap's internal data folder. |
| Another read or export is active | Finish it before starting another export. |
| Evidence changed or proposal unavailable | Check the connection and reopen the proposal before exporting. |
| Export could not be confirmed | A file may already exist. Check the chosen destination before trying again. |

Finish or cancel an open picker there. Yap cannot claim cancellation while its
native worker can still save a file. Connection loss leaves an uncertainty
message; an account/server change hides old evidence and late results, but cannot
undo a saved file. Local controls remain usable.

## What is in the file

The package is UTF-8 JSON with a trailing newline, limited to **64 KiB** including
serialization. It has these top-level fields:

| Field | Meaning |
| --- | --- |
| `schemaVersion`, `kind`, `status` | `1`, `connection-review`, `proposed` |
| `proposalId`, `generationSha256` | The inspected proposal and generation, each a 64-character lowercase SHA-256 identifier |
| `candidate` | `schemaVersion: 1`, `sourceConceptId`, `targetConceptId`, `relationshipType`, `rationale` |
| `sources` | Exactly two distinct endpoint entries, each with `node`, `citation` and quoted `text` |

Nodes retain their concept ID, type, title, repository path, source revision and
content hash. Citations retain the matching ID, revision, hash and character span.
Each excerpt is at most 1,024 Unicode characters. Rationale remains proposed text,
separate from the quotations. Connection credentials, session fingerprints (`permissionHash` and
`authorizationHash`) and approval claims are excluded.

**Check hashes and spans correctly.** `contentSha256` covers the complete original
source-file bytes, including frontmatter. `charStart` and `charEnd` are zero-based
Unicode-character offsets into the parsed Markdown body, with an exclusive end.
They are not file-byte offsets or JavaScript UTF-16 indexes.

## Review and later publication

Review both `sourcePath` files at the cited `sourceRevision`: check their hashes,
parse the Markdown bodies and compare the spans with `text`. Assess the proposed
direction, relationship and rationale alongside those quotes. Changed revisions
or hashes require fresh evidence.

Publication requires a separately reviewed Git/OKF source change. The authorized
`knowledge.curator` admission owner, compiler, complete embedding projection and
generation ledger govern activation. JSON supplies neither reviewer authority nor
production vectors. Publication and rebuilding remain open; see
[ADR 0022](../adr/0022-google-okf-permission-safe-projections.md).

## Implementation and verification

The [native export owner](../../desktop/src-tauri/src/knowledge_connections/review_export.rs)
reuses [authenticated proposal inspection](knowledge-connections.md#saved-connection-inspection)
and the [shared new-file writer](../../desktop/src-tauri/src/atomic_text.rs).
The renderer supplies only proposal/generation references and connection revision;
the native worker owns the picker, both authenticated reads and file publication.

The [verification record](../evidence/connection-review-export/2026-10-03/verification.md)
retains actual transport/file checks and simulated browser results. Linux-native and hosted Windows checks do not
replace physical Windows picker/focus/filesystem testing. Export needs no model
execution and does not qualify reasoning, real embeddings, enterprise policy or
production promotion. Exact-head integration remains pending.
