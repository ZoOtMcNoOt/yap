# Timed speaker export verification

Owner: Grant McNatt. Date: 2026-10-05 UTC.

Before this increment, History displayed source-bound persisted timed speaker
turns but offered only plain original text export. Acceptance was recorded in the
[single execution queue](../../../plans/active/2026-10-02-yap-project-hill-climb.md)
before implementation at `018bc545`. The [contract](../../../specs/timed-speaker-export.md)
retains the bounded JSON format, offline/native source ownership, explicit new-file
publication, recovery and qualification limits.

The native action loads through the recording ledger and the existing result/
speaker validators, matches the displayed session/result hash, bounds serialized
JSON before the picker, and rechecks all turns after selection. It reuses shared
export admission, retained directory handles and atomic no-overwrite publication.
The browser never submits transcript content or model metadata.

All seven focused Chromium cases pass (1.5m): exact identity and preserved original
actions; cancellation; failed save/retry; mismatching hash with retained write
uncertainty; late success/failure after source changes; and narrow keyboard/reduced
motion behavior. [Narrow screenshot](narrow.png) was visually inspected: the action
wraps without horizontal overflow and source turns remain readable. Full native,
frontend/browser, build, lint and release-contract renewals are in progress.
No full-suite or integration credit is assigned before those checks complete.

The first build rejected an optional session ID; the action now requires a
verified saved session and the TypeScript/Vite build passes. The first population
contract ran before the new spec was added to its explicit inventory and refused
it; the inventory deliberately includes all four declarations/seven generated
cases and is being renewed. No assertions or existing test floors were removed.

Fixtures exercise real persisted native results/files and the renderer/native
bridge. They do not qualify actual speaker/timestamp accuracy, enterprise identity
or a physical Windows picker. Full reviewed six-job green integration after PR
#208 and PR #209 remains required; the entire roadmap remains active.
