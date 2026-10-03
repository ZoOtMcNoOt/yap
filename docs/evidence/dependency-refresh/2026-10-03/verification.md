# Dependency refresh and Windows session-lock handoff

**Owner:** Grant McNatt. **Date:** 2026-10-03.

The refresh replaces stale dependency proposals with supported locked releases.
It removes the current frontend high/critical findings and Rust vulnerability
finding without an advisory ignore. Integration is tracked in [PR #199](https://github.com/ZoOtMcNoOt/yap/pull/199);
the PR records required hosted checks. Actual Windows RDP/session-lock
qualification remains open.

## Audit and consumer results

- Before: npm reported 11 high, 10 moderate and 4 low findings. After the final
  locked refresh: zero high/critical, zero moderate and one low finding.
  `pnpm --dir desktop audit:dependencies` passes on its first attempt.
- Remaining low finding: `diff` through Mocha, `GHSA-73rr-hh4g-fpgx`, affecting
  `parsePatch`/`applyPatch`. Mocha's installed reporter uses `createPatch` and
  `diffWordsWithSpace`; it does not call the affected parsing functions.
  The published fix starts at diff 8 and needs a verified consumer update.
  The finding remains visible; there is no advisory exception.
- Rust: `rustls` 0.23.45 fixes `RUSTSEC-2026-0285`; `event-listener` 5.4.2 fixes
  warning-class `RUSTSEC-2026-0221`. `cargo audit --file desktop/src-tauri/Cargo.lock
  --target-os windows --target-arch x86_64 --json` reports zero vulnerability-class
  findings and two warnings: unmaintained `proc-macro-error` 1.0.4 and Linux GLib
  0.18.5 unsoundness. Ignore list is empty.
- The actual locked Windows boundary script passes: no GLib is reachable in the
  Windows graph. Linux GTK remains affected and does not qualify Linux release.
- Published brace-expansion 1.1.21 / 2.1.7, Undici 6.28.1 / 7.29.1 and js-yaml
  4.3.2 replace older exact security pins within their major lines.
- Braces 3.0.4 is not published. Mocha 11.8.0 instead removes the affected
  Chokidar 3 path. Mocha 12 was rejected when the actual WDIO adapter could not
  import its removed `mocha/lib/cli/run-helpers.js`.
- `pnpm test:wdio-framework` runs two checks through the actual locked WDIO
  Mocha adapter: async hooks/tests, retries, skipped tests, success reporting and
  propagation of deliberate assertion failure all pass. These checks launch no
  desktop driver and do not claim native interaction coverage.
- WDIO 9.32 / Tauri service/plugin 1.4 use a scoped globals 9.31.3 override to
  replace the service's stale 9.29.1 peer path. `pnpm peers check` reports no
  peer dependency issues. Node 24 / pnpm 11.7 remain enforced.

## Hosted Windows binding repair

Hosted run [526](https://github.com/ZoOtMcNoOt/yap/actions/runs/37114232230)
found a Windows-only mismatch: Tauri's HWND uses Windows 0.62 while the app
still declared 0.61. The direct Windows and Windows-future dependencies now
align at 0.62.2 / 0.3.2; clipboard, island regions/styles and WAM keep their
existing native owners. Windows-future 0.3 renames blocking completion
from `get()` to `join()`; all four WAM broker call sites use the current method.
Installed source review confirms the same status/completion wait and result path.

The optional embedded WDIO driver also failed because even published 1.4.0
still uses WebView2 0.38 / Windows 0.61. The exact upstream fix in
[WebdriverIO PR #687](https://github.com/webdriverio/desktop-mobile/pull/687)
is pinned at `fb4a544bcc49605f6c6fb34f04b292abf428a72a`. It declares
StructuredStorage, aligns WebView2 0.39 / Windows 0.62, and rebinds the owned COM
controller at five Tauri boundaries. The current matching types make that
transfer a no-op; source review confirms the AddRef'd reference is moved once,
not duplicated. The MIT license and exact reviewed Git/source hashes are retained.
No driver code is copied into Yap; the optional driver is outside the production
graph. This is an unreleased, immutable test dependency. Replace it with a
compatible published version only after that version passes native WDIO checks.
The actual hosted Windows compile/runtime renewal remains a required merge gate.

Run 526 also passed 182 Windows browser cases and failed two recording-journey
clipboard assertions solely on OS CRLF transport versus the fixture's LF.
Those assertions now normalize only CRLF; they retain all other content and the
existing byte-exact export checks. The affected eleven browser cases are renewed
locally, and full Windows browser renewal remains a hosted gate.

## Issue #92

Official Tauri 2.12.1 selects Tao 0.37.1 without vendoring or a git patch.
In Tao 0.35.3, Windows `event_loop.rs:977` holds `KEY_EVENT_BUILDERS.lock()`
across keyboard message processing. In 0.37.1, `WindowData` owns
`key_event_builder` (`event_loop.rs:109`); lines 943–948 call that per-window
builder. No `KEY_EVENT_BUILDERS` global remains in the installed Windows source.
This establishes removal of the reported source path, not recovery on hardware.

[Issue #92](https://github.com/ZoOtMcNoOt/yap/issues/92) remains open. On Windows,
start recording, exercise keys/global shortcut, lock/unlock the session and
disconnect/reconnect RDP. Confirm both the main window and floating island
remain responsive and recording recovers correctly; a green backend health
response alone is insufficient. Repeat with idle and in-flight recording.

## Provenance and check renewal

Exact shipped inventory/notices are regenerated from installed sources.
Updated alloc-stdlib 0.3.0 and selectors 0.38.0 retain reviewed metadata-bound
license notices where archives omit standalone license files. WebView2 COM/sys
0.39.1 use exact normalized Cargo metadata declaring MIT, checked against original
workspace metadata and source attribution. Stale unic and old WebView2 notice
exemptions are removed. These are notice-source declarations, not audit exceptions.

The browser test population contract now includes all 26 current spec files and
raises the existing offer floor from three to eight declarations. Removing a
spec, shrinking its protected population or adding a file-scope skip still fails.
Strict Windows Clippy exposed a decoded pathname field unused in production:
it is now retained only for Unix cleanup and tests. Windows deletion remains
owned by the created file handle with DELETE_ON_CLOSE.

The final locked development checks pass in the configured cloud environment:

| Check | Result |
| --- | --- |
| Desktop Rust tests | 1,363 unit + 27 integration passed; 11 declared ignores |
| Desktop Clippy / rustfmt | Passed; existing Linux-specific 18 lib / 14 test unused warnings; not a strict Windows result |
| Frontend units | 388 passed; 2 declared Windows-only skips |
| TypeScript / Vite production build | Passed |
| Linux native debug app, no installer bundle | Passed |
| System Chromium workflows | 183 passed; 1 declared Windows-only skip; 8.3 minutes |
| Actual locked WDIO Mocha adapter | 2 passed |
| Portable hosted release contracts | 66 passed; 5 declared Windows runtime skips |
| Documentation / exact dependency notices / provenance | 8 passed, no skips |
| Frozen pnpm install / peers | Passed; no peer dependency issues |
| Windows dependency boundary | Passed; no reachable GLib |

Commands: `cargo test --locked`, `cargo clippy --locked --all-targets`,
`cargo fmt --check` in `desktop/src-tauri`; `pnpm --dir desktop test`, `build`,
`tauri build --debug --no-bundle`, `test:e2e`, `test:wdio-framework`,
`test:release-contract`; `node --test` for documentation-truth,
dependency-license and provenance contracts; and PowerShell
`verification/test-windows-rust-dependency-boundary.ps1`.
The full browser run includes island hover p95 within 220 ms and reduced motion;
it does not establish GPU/frame-rate or native RDP behavior.

The unchanged server,
real Postgres and orchestrator checks retain their dated receipts; model quality,
Windows RDP, enterprise integration and distribution clearance remain separate.

## Windows file ownership renewal

[Hosted run 529](https://github.com/ZoOtMcNoOt/yap/actions/runs/37116069254)
at `ac6bb417` passed strict Windows Clippy, 392 frontend units, 184 browser
workflows, all 71 hosted release contracts, and the native WDIO application build.
Server, mock identity and orchestrator jobs passed. Native tests and one WDIO
assertion failed; this run does not qualify integration.

Native model installation exposed a real sharing violation: the no-follow
verifier reopened staging while its writer was still open. Both download and
offline import now verify the retained read/write staging handle after sync,
seeking its clone to the start and preserving exact size/hash/cancellation checks.
Admitted external artifacts keep their stricter sharing and no-follow boundary.
The staging handle closes before same-directory atomic publication.

The other native failures were test ownership assumptions. Export receipts use
canonical paths, including Windows long-path/short-name resolution. Decoded
plaintext disappears after every cloned DELETE_ON_CLOSE handle closes. Mid-decode
cancellation tests now observe file length on the retained handle, because Windows
directory-entry lengths may remain stale while writing; the 128 KiB cancellation
bound, original bytes and owned-file cleanup remain asserted. The native Knowledge
smoke assertion follows the refreshed offline copy and still checks disabled
search, accessible labeling and available local navigation.

The follow-up renews all 1,363 Linux native unit tests (11 declared ignores),
Clippy, formatting and eight documentation/license/provenance checks.
[Hosted run 530](https://github.com/ZoOtMcNoOt/yap/actions/runs/37117347492)
at `8c00b0f3` passes 1,367 Windows native units plus 27 integration cases,
strict Clippy, both actual server-connector runtimes, the Windows dependency
boundary/audit and required native WDIO. Server, identity and orchestrator jobs
also pass. No RDP/session-lock or model quality result is inferred.

The frontend job reported 152 passing browser cases before its 15-minute job
deadline cancelled the still-running 184-case suite. It reported no assertion
failure. The job budget is now 25 minutes to accommodate dependency/browser
setup and the expanded single-worker suite on hosted Windows. Per-test 20-second
and assertion five-second timeouts, test population and final exact-head guard
remain unchanged. The updated integration commit must pass every required job;
the cancelled run is not a green frontend receipt.

Run 531 exposed a parallel orchestrator fixture collision at exclusive directory
creation. Broker and lifecycle test directories now include the atomic sequence
already used by supervised-service fixtures, so repeated clock timestamps cannot
choose the same path within a process. Exclusive creation and private permissions
remain enforced. Production code is unchanged; all 46 default orchestrator
contracts and strict all-target/all-feature Clippy pass locally. The corrected
integration commit renews every hosted job before merge.

[Audit policy](../../../runbooks/dependency-audit-policy.md) records the remaining
findings and removal conditions. The [single goal](../../../plans/active/2026-10-02-yap-project-hill-climb.md)
remains active after this increment.
