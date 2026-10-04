# Recording notification interaction verification

Owner: Grant McNatt. Date: 2026-10-04. Status: locally verified;
renewed exact-head hosted integration pending.

[Run 557](https://github.com/ZoOtMcNoOt/yap/actions/runs/37224381593) at
`053cb592a4d92dffd50d2b1602a2333410812874` passes five jobs. The frontend job
passes 237 browser cases and fails the existing unreadable-saved-transcript case:
its normal click targets the older completion notification while the newer
preview-error notification intercepts pointer events. The old action expires
before selection. The [actual original call log](original-browser-toast.txt)
retains the failure. Its downloaded trace and screenshot also show the correct
inline read-error/retry controls already rendered; production error recovery
was available. The unchanged case passes three local Linux runs (36.7s), so the
hosted failure depends on timing rather than consistently reproducing there.

Installed Sonner's actual mouse-enter/move handlers expand its notification
stack and pause expiry while it is expanded. The existing browser case now waits
for its preview-error notification, enters the front notification to expand the
stack, then selects the older saved-transcript action through a normal click.
It retains the same dialog/error/retry/copied-text assertions, native-command
ownership and single imported recording; no forced click, artificial sleep,
larger timeout, added retry or skipped case is used. The population is unchanged.

All 11 recording-journey browser cases pass locally (1.0m), including the
previously failed case (5.1s). The full frontend unit suite passes 404 cases with
the two declared Windows-only exclusions (406 total); TypeScript/Vite production
build passes. All 72 release contracts complete with 67 passes, five declared
Windows-only exclusions and no failures (6.530s). These results verify fixture UI behavior, not physical Windows
input or inference. Renew all six required jobs on the corrected exact head
before integration; the five successful jobs at the earlier head do not complete
that new gate.
