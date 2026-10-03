# Accepted correction recovery

**Owner:** Grant McNatt. **Date:** 2026-10-03. **Status:** Six software outcomes verified in the development working tree.

Accepted correction files already survived restart, but their renderer view disappeared after changing sources or reopening Correct. The native reader now recovers the latest accepted revision for a trusted local source. The UI labels it separately from a new suggestion and can read/copy it without an organization connection or correction model. Original files and the accepted chain remain intact. The [project goal](../../../plans/active/2026-10-02-yap-project-hill-climb.md) stays active across all workstreams.

## Ownership and recovery

- The main-window command accepts only the selected original output path. The existing live/remote source owners validate committed source provenance and derive the correction location; callers cannot select a revision file or supply source/approval claims. Original language/timing evidence must still validate under those owners.
- Recovery validates the complete ordered hash chain, then binds its latest revision to the current source revision and original-text hash. It rereads the trusted source before returning. Source changes, corrupted hashes/JSON, gaps, wrong authority, linked/nonregular files, oversized files/history and invalid staging are refused without cleanup or replacement.
- Existing limits remain: 64 revisions, 192 KiB per artifact and 32,768 corrected characters. Excess matching paths fail during enumeration. Missing remote history returns an empty result without creating a directory; existing remote history must be private and unlinked. Recovery never deletes staging or hides corruption with an older revision.
- One filesystem worker and an eight-second response deadline bound admission. A timed-out worker retains its permit until it exits; repeated calls cannot accumulate background readers. Saving and recovery share the existing publication lock.
- The source-bound renderer hides old saved/suggested text and copy actions before adopting another source. It ignores late reads, validates response path/source hashes, and retries readable failures. Same-source development mount calls share only their in-flight request; publication forces a fresh read and no settled result cache is introduced.
- Already accepted text is compared with the original and copied through an explicit saved-correction action. New model output remains a suggestion with its own copy/save controls. Saving rereads the accepted history; navigating away and reopening restores it. The correction hook now keeps pending submission/cancellation/publication flags until acknowledgement and avoids duplicate cancellation during source invalidation.

The read command uses no server connector, bearer token, model or caller-provided identity. New remote correction work retains its existing native request/source/connection owners. This increment reads the latest accepted revision; selecting older revisions and dedicated corrected/timed/speaker exports remain separate work.

## Verification

Nine added native cases cover actual immutable-file reopening, live source isolation, current-source mismatch/reread, missing/private remote history, corrupt/incomplete/excessive/staging/link refusal, external-path admission and timeout capacity retention. The focused correction suite passes 28 cases. Nine browser cases pass for offline copy at 360/1440 px, explicit-save reopening, retry, delayed/misbound reads, saved-versus-suggested text and a mounted source switch. These UI responses are fixtures; native filesystem tests supply the durability evidence.

| Check | Result |
| --- | --- |
| Frontend units | 388 passed, two existing Windows-only exclusions. |
| Native | 1,343 unit + 27 integration passed, 11 existing model/hardware ignores. |
| Full Chromium suite | 160 passed, one existing Windows-only island exclusion. |
| Final correction/layout browser regression | 12 passed after the responsive refinement: nine recovery/layout cases plus three existing correction journeys. |
| TypeScript/Vite and Linux application | Passed; Tauri debug/no-bundle build has 18 existing platform-specific warnings. |
| Documentation, dependency-license and provenance contracts | Eight passed. |
| Native formatting and diff whitespace | Passed. |

The full browser receipt precedes the final compact-preview/copy refinement;
its 12 focused cases verify that final change. No business or native source code
changed after the full native check. Server code is unchanged since the
[Curator connection checks](../../curator-connections/2026-10-03/verification.md).
Development logs are `/tmp/yap-accepted-correction-{browser,unit,native}-renewal.log`,
`/tmp/yap-accepted-correction-layout-verified.log` and
`/tmp/yap-accepted-correction-{build,native-build}-final.log`.

Reproduce focused checks from the repository root:

```bash
source verification/cloud-env.sh
cargo test --manifest-path desktop/src-tauri/Cargo.toml --locked transcript_correction
cd desktop
pnpm test:e2e accepted-correction-recovery.spec.ts correction-journey.spec.ts transcript-correction.spec.ts
```

## Screen review

Actual Chromium captures were inspected with reduced motion enabled at
[1440 px](01-saved-desktop.png) and [360 px](02-saved-mobile.png). The saved
revision and its explicit copy action stay distinct from unavailable model
controls. Short narrow comparisons fit their content; long corrections retain
bounded keyboard-scrollable viewports. The narrow page has no horizontal
overflow. These interaction fixtures do not qualify model quality or Windows
clipboard behavior.

## Qualification

No actual correction model was run. Windows path/ACL/reparse behavior, physical window/clipboard interaction and enterprise identity remain target qualification work. The Unix link/privacy cases and Linux build cannot qualify Windows. Corrupt or conflicting histories stay available for a future explicit repair/recovery process; this reader preserves them and reports the problem.
