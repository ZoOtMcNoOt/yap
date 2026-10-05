# Reviewed timed speaker export integration

Owner: Grant McNatt. Date: 2026-10-05 UTC.
Status: all seven bounded export software outcomes and all five cancelled-warmup
repair outcomes verified and integrated through
[PR #210](https://github.com/ZoOtMcNoOt/yap/pull/210). The full project goal stays active.

Reviewed tested head `12088dea5eec1bc41f9cd71fd6cff828c2c73832` passes all six
required jobs and their final exact-checkout guards in
[run 572, attempt 1](https://github.com/ZoOtMcNoOt/yap/actions/runs/37281343011/attempts/1).
Hosted Windows checks pass 1,396 native units and 27 integrations, with 12 declared
model/hardware ignores. All 419 frontend cases pass without skips; the complete
258-case browser suite passes in 6.1 minutes. Independent review reports no
unresolved findings on the corrected source.

PR #210 merged as `0c98984fc47767237e52e6e61d1a1b43ff4613a7` after PR #209.
Fetched main's tree `1d2585685e4d8ba3320e8f53aa3a0dbef231e9f3` equals the tested
head's tree. Tag `reviewed/pr-210-12088dea` preserves the tested head; the clean
completed branch and owned worktree were retired only after the comparison.

The export reads validated persisted source-bound speaker turns, retains exact
source-result/session identity, Unicode text, anonymous or unknown labels,
timestamps and overlap groups, and writes bounded UTF-8 JSON through the existing
explicit native new-file picker and atomic no-overwrite owner. Cancellation,
source/selection drift and uncertain completion preserve originals, accepted
corrections, other results and existing destinations. It does not invent speaker
identity, timestamps or alignment for accepted free-text corrections.

[Local export verification](verification.md), [Windows path renewal](windows-path-renewal.md)
and [cancelled-warmup repair](warmup-destruction-repair.md) retain the original
observations, source heads and focused checks. The earlier `d46744f7` Windows
canonical-path assertion failure and run 569's `65029dd4` real cancelled-warmup
destruction race are preserved and receive no integration credit. The repair
retains cancelled-load destruction ownership outside the state mutex until its
destructor completes, bounds cleanup and refuses conflicting load/adoption; all
30 focused lifecycle cases pass without skips. The successful reviewed run above
renews the complete corrected-head gate rather than retrying the failed source.

These checks verify software behavior and hosted Windows execution. They do not
qualify physical Windows picker/input/audio behavior, real ASR/diarization quality,
enterprise identity or production deployment. Subtitle conversion, local timestamp
generation, purpose-authorized named identity and corrected-text alignment remain
separate roadmap outcomes. Maintenance is a separate increment; its recorded checkpoint does not certify
merge. [PR #212](https://github.com/ZoOtMcNoOt/yap/pull/212) is its live integration record.
