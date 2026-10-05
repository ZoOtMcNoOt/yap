# Authenticated desktop rebuilding integration

Owner: Grant McNatt. Date: 2026-10-05 UTC.

[PR #208](https://github.com/ZoOtMcNoOt/yap/pull/208) merges as `181085afa1b7d026f90c1532b484157b64211d79`,
with the exact tested tree of `5f6e62a2d1845c4b197d63537d6eb70c37db0296`.
All six required jobs in [run 563](https://github.com/ZoOtMcNoOt/yap/actions/runs/37272490398)
pass on that head. Annotated tag `reviewed/pr-208-5f6e62a2` retains the reviewed
head; the fetched main tree equals it (`69eac6112b4c3e99ae6b7f2596b08620c548b61a`).
Only after that comparison are the completed branch/worktrees retired.

Independent read-only review reproduced native authorization failures retaining
private inspection, staging overwriting immutable descriptors and lost-reply
activation replay losing descriptor binding. All three are corrected, and
independent re-review of `20fa6779` reports no unresolved actionable findings.
[Review evidence](review-verification.md) retains the original failures and local
renewals. The original run560 WDIO shape failure and pre-correction green run561
remain historical observations, not credit for this final tested head.

| Required hosted check | Actual result |
| --- | --- |
| frontend | Success: 411 frontend units, 72 release contracts, WDIO framework contracts, TypeScript/Vite and all 251 browser cases (17.2m). |
| rust | Success: 1,390 native units + 27 integrations, 12 declared fixture ignores, strict Clippy and authenticated connector checks. |
| server | Success: 1,830 total/1,633 passes/197 declared exclusions; exact locked dependency audit passes. |
| mock-oidc | Success: 52 owned-process lifecycle cases and all 161 required real SQL cases without skips; pinned mock identity owner flow passes. |
| Server orchestrator (Linux lifecycle) | Success: every target, strict lint, lifecycle and installer/systemd boundary checks pass. |
| Native WDIO smoke (required, no hardware) | Success: actual built Windows app smoke and all 72 release contracts pass. |

Local corrected verification separately passes 1,393 Linux native units + 27
integrations (12 declared ignores), exactly one actual built-native HTTP/SQL
rebuilding journey with zero skips, all 13 rebuilding browser cases, 409 frontend
units/two Windows-only exclusions, TypeScript/Vite, strict Clippy and 30 repository
contracts. Committed clean20fa release contracts pass 67/5 Windows-only skips
(72 total); local contracts pass 71/15 platform exclusions (86 total).

Synthetic identities/vectors verify orchestration. No real provider quality,
enterprise deployment or physical Windows/RDP qualification is claimed. The
organization retains source/Git/deployment review responsibility. The existing
service accepts an owned saved retained reference rather than discovering an
activation-history list. Broader source/product integration and the entire
roadmap remain active.

The next bounded increment prepares larger reviewed generations in deterministic
requests with one total deadline and complete atomic persistence. Its independent
review and own six-job exact-head gate remain separate.

Run 562 is historical failed gate evidence: the 25-minute job ceiling cancelled
the serial 251-case browser suite after 199 passing markers. Run 563 retains
every case/assertion/test timeout with only the whole-job ceiling raised to 40
minutes. Independent final-head review found no unresolved actionable findings.
Run 563 attempt 1 retained a 250-pass/one initial-navigation timeout failure;
attempt 2 reran the entire frontend job unchanged and passed all 251 cases.
All six required jobs and their final unchanged-checkout guards succeeded.
This is ordinary reviewed-head integration evidence, not first-attempt admitted
candidate closure evidence.
