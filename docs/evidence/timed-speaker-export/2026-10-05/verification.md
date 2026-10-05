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
motion behavior. [Narrow](narrow.png) and [wide](wide.png) screenshots were visually inspected: the action
wraps without horizontal overflow and source turns remain readable. Native renewal
passes 1,399 units and all 27 integrations, with 12 declared model/fixture ignores
(104.78s units). All 417 frontend units pass with two Windows-only exclusions;
TypeScript/Vite and strict all-target Clippy pass. Release contracts pass 67/72
with five Windows-only exclusions; local process contracts pass 71/86 with 15
platform exclusions. All 27 documentation/license/provenance/population/workflow
cases pass without skips. The initial complete 258-case browser run ended with 254 passes, three failures
and one declared Windows-only exclusion (30.3m). The first-run and History controls
appeared after their readiness assertions expired; the collapse-grace trace
showed browser-command scheduling delays exceeding the actual grace period.
The run overlapped native builds and another browser suite, and both worktrees
shared a writable Vite cache. Failure traces/screenshots are retained outside Git
under `/tmp/yap-timed-export-browser-original`; this run receives no full-suite
pass credit. A full serial renewal with a private Vite cache is required; cases,
assertions, one worker and timeouts remain unchanged.

The first build rejected an optional session ID; the action now requires a
verified saved session and the TypeScript/Vite build passes. The first population
contract ran before the new spec was added to its explicit inventory and refused
it; the inventory deliberately includes all four declarations/seven generated
cases and passes on renewal. No assertions or existing test floors were removed.

Fixtures exercise real persisted native results/files and the renderer/native
bridge. They do not qualify actual speaker/timestamp accuracy, enterprise identity
or a physical Windows picker. Independent read-only review of `8e1804dcf2ff22897d7cb6465846472d39f771fa`
found no unresolved actionable findings. Final read-only metadata review of
`60d4d25916af6bcdda0d1fad41d89c271d59e94e` also found no unresolved issues.
Both complete contract sets renewed on that clean head: 67/72 release cases and
71/86 local cases pass with their five/15 declared platform exclusions; no failures.
Full reviewed six-job green integration after PR
#208 and PR #209 remains required; the entire roadmap remains active.
