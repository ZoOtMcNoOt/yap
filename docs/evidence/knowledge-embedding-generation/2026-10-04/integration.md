# Reviewed embedding integration

Owner: Grant McNatt. Date: 2026-10-04. Status: 7/7 bounded software outcomes
verified and merged; the full project goal remains active.

[PR #207](https://github.com/ZoOtMcNoOt/yap/pull/207) merged as
`0d137282805e288d82884c143c79ca39f3614994`, after all six required jobs passed
on exact head `f64bd355357039a5a8da96233b01556802477e59` in
[run 558](https://github.com/ZoOtMcNoOt/yap/actions/runs/37226621903).
The merge supplied the expected exact head. Final head inspection confirmed
that head; all three review threads were resolved. An actual Git tree comparison
after fetching main returned no difference from the tested head, and main was
fast-forwarded to the merge. Its tree is `2e849d805bde5a71b621bbb472cf7822123c9a44`.

| Required job | Actual renewed result |
| --- | --- |
| frontend | Success; 406 units, all 238 browser cases and all 72 release contracts pass. Browser suite takes 14.7 minutes. |
| rust | Success; 1,380 Windows native units and 27 integrations pass, with 11 declared model/hardware ignores; strict Clippy and authenticated connector runtime checks pass. |
| server | Success; 1,633 Windows server cases pass, with 197 declared platform/fixture/database exclusions (1,830 total). Required real SQL runs separately below. |
| mock-oidc | Success; 52 identity cases and all 161 required real SQL cases across 26 modules pass without skips. Actual PostgreSQL 17.11 and pgvector 0.8.7 use the pinned image. |
| Server orchestrator (Linux lifecycle) | Success. |
| Native WDIO smoke (required, no hardware) | Success. |

[Local verification](verification.md) retains the missing route, real SQL/HTTP
source-to-publication/read/restore journey, strict synthetic provider checks and
209 skip-free portable cases. [Review verification](review-verification.md)
retains the actual numeric-overflow failures and contained refusal correction.
Run 557 failed one existing browser case because stacked notifications obscured
the older action; [browser evidence](browser-verification.md) retains the original
failure and artifact. The existing case now waits for the newer error and hovers
the front notification to expose its actions, exercising Sonner's real behavior.
All original dialog/error/retry assertions remain. Renewed run 558 passes all
238 browser cases on the corrected head; no forced click, skip or retry bypass.

The tested head remains under pushed annotated tag `reviewed/pr-207-f64bd355`.
The completed remote/local feature branch and owned scratch worktree are retired,
after confirming the tag and fetched-main tree equality. Unique older work and
the dedicated next-increment worktree remain preserved.

Separately, the restored cloud runtime passes the full Linux native suite at
main `d2d3685b`: 1,383 units and 27 integrations, with 11 declared model/hardware
ignores and no failures. Native source is identical to the tested embedding head;
this renews Linux software verification without inventing physical qualification.

Fixture identity and synthetic vectors do not qualify real embedding provenance,
quality, enterprise deployment, physical Windows/RDP/session-lock or installers.
The authenticated desktop rebuild caller is not yet implemented (0/7 outcomes);
continue its recorded contract, larger rebuilds and the entire roadmap.
