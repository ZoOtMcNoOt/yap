# Connection review package

**Owner:** Grant McNatt. **Status:** Implemented; integration verification pending.

Export a saved connection proposal and its two cited excerpts for Git review.
The suggestion stays **proposed**: export does not approve or discard it, publish
a graph edge or activate a generation. The [active queue](../plans/active/2026-10-02-yap-project-hill-climb.md#awaiting-integration-export-a-connection-review-package)
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

The shared native owner retains the destination directory before reinspection
and throughout publication; a replaced path cannot redirect operations into its
substitute. [Directory evidence](../evidence/export-directory-ownership/2026-10-03/verification.md)
records actual checks and the remaining Windows qualification.

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

## Check the sources locally

Use the prepared [server environment](../runbooks/cloud-development.md) to check
an exported package against an explicitly selected **complete OKF bundle**,
including its root document, concepts and permission files. Run from the Yap
repository root, replacing these example paths and identifiers:

```bash
PYTHONPATH=server/src server/.venv/bin/python -m yap_server.knowledge.connection_review \
  /review/connection-review.json \
  --bundle-root /review/okf-bundle \
  --tenant-id organization-tenant \
  --source-revision reviewed-revision
```

Choose the tenant and source-revision label used to compile the exported
proposal's generation. Supplying only the two cited files is insufficient: the
checker recompiles the complete bundle and requires its generation hash to match.
It also checks both endpoint identities, source metadata, complete-file hashes
and exact Unicode-character spans against the quoted text.

Success exits with `0` and prints a JSON receipt with `status: source-matched`,
`sourceCount: 2`, the proposal/generation references and `packageSha256`. That hash
binds the receipt to the exact package bytes you checked; editing the JSON,
including its whitespace, changes it. The receipt contains no excerpts or
rationale. Keep it alongside the package in your review.

Malformed packages, mismatched sources or unsafe files produce a short refusal
on stderr and exit `2`, without a success receipt or source text. Check the chosen
bundle, tenant and revision; obtain fresh evidence for changed sources. The
command reads local files and changes neither the package nor the source bundle.

**Source matching is one review check.** The command does not fetch or verify a
Git commit, authenticate the original proposal ID or rationale, or check current
server permissions. The revision is an explicit input label. Review provenance,
access, the rationale and approval through your organization's separate process.

## Review and later publication

Use the source checker alongside a trusted checkout at the cited revision.
Assess the proposed direction, relationship and rationale alongside both quotes.
Changed revisions or hashes require fresh evidence; a source-match receipt supplies
no reviewer authority or approval.

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
