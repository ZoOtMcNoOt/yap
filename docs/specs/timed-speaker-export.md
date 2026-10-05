# Saved timed speaker transcript export

Owner: Grant McNatt. Date: 2026-10-05.

History offers **Export timed speakers** when its persisted organization-server
speaker projection has been verified. This explicit offline file action uses the
original source-bound turns. **Export text** and **Export saved correction** retain
their separate text contracts. Free-text corrections are not aligned to source
timestamps, and this export does not infer named people or regenerate timing.

The UTF-8 JSON document has `schemaVersion: 1`, `sessionId`, the exact
`sourceResultSha256`, and the complete ordered `turns` array. Each turn contains
`turnId`, `speakerId` (a session-local anonymous identifier, or `null` for unknown),
`startMs`, `endMs`, exact Unicode `text`, and `overlapGroupId` when present.
Milliseconds remain integers; display rounding does not change exported timing.
Turn timing is distinct from word alignment. Partial speaker attribution retains
unknown speakers; exporting it does not certify speaker or model accuracy.

Native code receives only the displayed session, owned transcript output path
and source-result hash. The recording ledger and existing result/speaker bundle
validators load the projection and bind it to its original recording. Requests
cannot supply turns, text, vectors, source bundles, models, identities or credentials.
A missing, changed, damaged or foreign result is refused without private content
in the error. The serialized JSON, including escaping and its final newline, is
limited to 2 MiB; oversize output is refused before the picker without truncation.

The main-window command shares existing export admission. Its blocking worker
owns that permit through the explicit new-file picker, source revalidation and
publication, even if its caller disappears. After the picker it rechecks the
complete session/hash/turn projection. The existing destination owner adds `.json`
when absent, refuses other extensions and Yap's internal data, retains directory
handles, and creates a new file atomically without replacing an existing file.
Linked or substituted destinations cannot redirect publication into internal data.
Original recordings, source results, corrections and unrelated files are preserved.

A cancelled picker reports cancellation. A stopped worker or unconfirmed write
asks the user to inspect the destination before retrying because the file may have
been saved. A strict saved receipt echoes the exact session and source hash.
Changing selection or closing the review invalidates pending renderer feedback,
including returning to the same source later. Concurrent exports remain unavailable
until the native operation settles. No network, authentication, model or source
repair action is started by export.

[Acceptance and evidence](../evidence/timed-speaker-export/2026-10-05/verification.md)
retain software checks and current integration status. Physical Windows save-dialog
qualification, actual speaker quality, subtitle conversion and named-speaker
identity remain separate roadmap outcomes.
