# Repository consolidation

**Owner:** Grant McNatt. **Date:** 2026-10-03.

Grant requested readable documentation, consolidation onto `main`, retirement
of old branches/PRs and a commit/push after each verified iteration.

## Preserved history

Before deleting any branch, all 27 original tips were retained as parents of
archive commit `18f590fc831a1c26bc744443cb475e81d9cf4241`. Its tree is the previous
`main` tree; it archives history without installing old code or dependency
proposals. The annotated tag
[`archive/branch-consolidation-2026-10-03`](https://github.com/ZoOtMcNoOt/yap/releases/tag/archive/branch-consolidation-2026-10-03)
was pushed and its remote object/peeled commit verified before cleanup.

Several old branches were integrated through squash/reworked successors rather
than retaining their original SHA as ancestors. Patch comparison, current files,
completed plans and main history were inspected. Phase 7's completed plan records
PR #69 and later ownership repairs; local-first discovery and decoder owners
have current implementations. The pre-lean process archive intentionally retains
retired work. The single archive tag preserves all original history, including
proposals not installed into the current tree.

| Retired branch (except retained `main`) | Preserved tip |
| --- | --- |
| `archive/phase3-contained-process-pre-lean-20260713` | `98e487a72f36ab6aafcaa5e7d23ada67676a1741` |
| `chore/local-heavy-tests` | `3d7535c47bf29dfda0ca84eaba2c6d1c46ef4052` |
| `chore/reduce-gate-friction` | `392200e4d643cd5f859ce80e5430d75700ccc8d9` |
| `dependabot/cargo/desktop/src-tauri/cargo-minor-and-patch-5c07c818b1` | `270339ac7e8d0126a5104aed167b3ac3ce576462` |
| `dependabot/cargo/desktop/src-tauri/symphonia-0.6.0` | `c0c47480e5deb9f719279acbdfd8f3fdb2941f9e` |
| `dependabot/cargo/desktop/src-tauri/windows-future-0.3.2` | `8565336beab477d0a4dce994c269e0bec684d471` |
| `dependabot/github_actions/github-actions-b880dd3b79` | `056b8dda47df1f44ffd9f461cb819887ea937e94` |
| `dependabot/npm_and_yarn/desktop/npm-minor-and-patch-534f735139` | `65ef9b50809b31fdb3166b4188d01f46496d7e4e` |
| `dependabot/npm_and_yarn/desktop/vitest-5.0.0` | `c27049b77db92967d5557f0321406fde6f4efbe1` |
| `dependabot/npm_and_yarn/desktop/wdio-core-2f703c94f1` | `c2c4b9bf4dc62020797c1c81c23f4e47eac996f5` |
| `dependabot/npm_and_yarn/desktop/wdio-tauri-f1600f7b4e` | `cc29fb3bec3fe3c45b8c7357ec658ad8c4f299da` |
| `dependabot/uv/server/uv-9199f210d9` | `13b797bd0d141658192ab64051c94c27024a7570` |
| `feat/decode-imported-audio` | `8eb4fac1dd6f6ba23e6b3d6a929ded86be2d2d44` |
| `feat/local-first-server-discovery` | `081e1ec0ae7d801916aa2918bb7a5ab173b6a288` |
| `feat/phase7-identity-access` | `5b6555c2b3caaf2be474fe4412e9f34480c7ee1f` |
| `feature/wispr-flow-live-moonshine` | `0eb62d9645dac465ddafdf85651eabe13da11708` |
| `fix/harness-opacity` | `2d769ecc8b1facaaef26e12dfa3e6c446c78956c` |
| `fix/live-audio-antialias` | `1f595a14acceb9a38027d0c3171f49a1fc4a7861` |
| `fix/provenance-hash-after-antialias` | `d51771d0354e5b9f1bf9ce26a8a786e68d78502c` |
| `fix/ssh-profile-hook-timeout` | `393571f9d966c64c03f1a51990a8fe9e2d7ae5bc` |
| `fix/ssh-profile-local` | `a56b28af795f7a32a543db47b8cb7f5473271eaf` |
| `main` | `c76118200003f8b1a555d9125795cbd2fb501ad3` |
| `phase7-admission-c1d81fc` | `c1d81fc085218cf91a4e370087bcc5927e5b1f70` |
| `phase7-admission-c95cfe0` | `c95cfe02a4a1df81dfc4aaed58ac15f61247c4f4` |
| `phase7-admission-cafbe307` | `cafbe307e7203e09050fdbe2eb080d5d84b65026` |
| `phase7-admission-dc635916` | `dc6359162fb16909d38f410cdb75c2729d83972f` |
| `refactor/meeting-transcription-maintainability` | `b1f227ef69562887be80bf09777df0e91b4e9615` |

## Cleanup

Nine stale Dependabot PRs were closed: #198, #197, #192, #189, #187, #185, #161,
#147 and #146. Closing removed their nine branches automatically. The remaining
17 historical branches were deleted with expected-SHA leases in one atomic
push; concurrent/changed heads were not discarded. The first atomic attempt
refused because the nine automatically deleted heads no longer matched; no
branches were deleted by that attempt. Refreshed heads matched the preserved
snapshot before the successful deletion. Remote inspection then showed only
`main`.

Symphonia 0.6.0's proposal is superseded by the verified pinned 0.6.1 decoder.
The other dependency updates are retained as archived proposals, not silently
installed or declared unnecessary. GitHub reported default-branch dependency
alerts during cleanup; current locked dependency audits and subsequent fixes
remain part of release/operations work.

## Documentation and development integration

README/docs entry points are organized by product and reader tasks. Historical
feature inventories, goals, plans, operational requirements and qualification
evidence remain reachable. The active project goal and AGENTS.md now require
committing/pushing each verified iteration, using required checks before merge
and deleting finished temporary branches.

Development integration into current `main` is pending final local and hosted
checks. The archive does not establish production/model/Windows qualification.
