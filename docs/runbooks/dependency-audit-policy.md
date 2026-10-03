# Dependency audit policy

Audit findings are release inputs, not something to hide to obtain a green build.
Yap currently has **no frontend advisory exceptions and no Rust advisory ignores**.
High/critical frontend findings and Rust vulnerability-class findings block
release. Warning-class findings require review at the actual shipping target.

## Run the gates

From the repository root:

```powershell
pnpm --dir desktop audit:dependencies
```

This runs the real `pnpm audit --audit-level high`. Only recognized transient
registry/network failures receive retries, after 10, 30, 60 and 120 seconds.
Internal fetch retries are disabled. High/critical vulnerability findings,
certificate/configuration errors, unknown failures and exhausted retries fail
the gate. Never use
`--ignore-registry-errors`. A unit test requires `auditConfig` to remain absent.

For the desktop Rust lockfile, run from `desktop/src-tauri/`:

```powershell
cargo audit --target-os windows --target-arch x86_64
```

CI also checks the complete locked Windows dependency graph through the
[Windows boundary guard](../../verification/test-windows-rust-dependency-boundary.ps1).
Failure to inspect that graph is a failure, not evidence of absence.

Audit the core Python server from the repository root with Python 3.12 and uv:

```bash
python verification/audit-server-dependencies.py
```

This exports the locked core to PEP 751 with all extras and development groups,
checks that every PyPI package version in `server/uv.lock` is represented, and
runs isolated `pip-audit==2.10.1` with `--strict`. The pinned auditor checks every
exported version without filtering platform markers. Findings, skipped/unknown
packages, unreviewed sources, incomplete exports and unavailable advisory data
fail the gate. There are no advisory ignores. Audit tools are not installed in
the server environment, and the command downloads no models.

This gate covers the core lock, not model overlays or container base images.
The [core server evidence](../evidence/server-dependencies/2026-10-03/verification.md)
records fixed versions, behavioral checks and separate unresolved NeMo findings.

## Current dependency refresh

The locked refresh passes the frontend high/critical gate with **one low finding**
and the Rust vulnerability gate with **zero vulnerability-class findings** and
two reviewed warning-class findings. There are no advisory ignores.
[Verification](../evidence/dependency-refresh/2026-10-03/verification.md) records
consumer checks and target limits; [PR #199](https://github.com/ZoOtMcNoOt/yap/pull/199)
records the merged integration; all six exact-head jobs passed in run 532.

| Dependency path | Selected update | Reason or remaining check |
| --- | --- | --- |
| Older glob dependencies | `brace-expansion@1` → `1.1.21`; `@2` → `2.1.7` | Keep fixes within the existing major lines. |
| WebdriverIO HTTP dependencies | `undici@6` → `6.28.1`; `@7` → `7.29.1` | Compatible patched releases for both transitive lines. |
| YAML parser | `js-yaml@4` → `4.3.2` | Apply the available patched release. |
| Desktop automation | WebdriverIO `9.32`, Tauri service/plugin `1.4` | Real adapter and hosted Windows native WDIO checks pass; the optional test driver retains the immutable compatibility fix described in the evidence. |
| Mocha through WebdriverIO | Scoped `mocha@10` → `11.8.0` override | Removes the affected `braces` path through Chokidar 4; actual async hooks, retry, skip and success/failure reporting checks pass. |
| Desktop runtime | Tauri/API/CLI `2.12.1`, Tao `0.37.1` | Upstream removes the global mutex path implicated in [issue #92](https://github.com/ZoOtMcNoOt/yap/issues/92); actual RDP/session-lock checks remain open. |
| Rust TLS | `rustls` `0.23.45` | Patched release for `RUSTSEC-2026-0285`. |
| Rust event listeners | `event-listener` `5.4.2` | Patched release for warning-class `RUSTSEC-2026-0221`. |

The registry does not publish the proposed `braces` `3.0.4` fix. Mocha 12 was
rejected after an actual WebdriverIO adapter import failed; removing the advisory
path without a working adapter is not a solution. The scoped Mocha 11 change is
verified against the actual locked adapter, not just its dependency graph.

The authoritative frontend selections are in
[`pnpm-workspace.yaml`](../../desktop/pnpm-workspace.yaml) and its lockfile;
Rust selections are in [`Cargo.lock`](../../desktop/src-tauri/Cargo.lock).
Issue #92 stays open until Windows RDP/session-lock reproduction and recovery
checks establish the behavior on the intended client.

The remaining frontend finding is low-severity `diff` through Mocha
(`GHSA-73rr-hh4g-fpgx`), affecting `parsePatch`/`applyPatch`. The installed Mocha
reporter uses diff creation/word comparison, not those patch-parsing functions.
The published fix begins at `diff` 8, a major change for this consumer; retain
the visible finding until a verified consumer update removes it. It is not an
audit exception, and this does not qualify native desktop execution.

## GLib and the Windows boundary

`GHSA-wrw7-89jp-8q8g` / `RUSTSEC-2024-0429` remains open for `glib` `0.18.5` in the
Linux GTK dependency graph. Affected versions are `0.15.0` through `0.19.x`;
the fix begins at `0.20.0`.

The Windows guard enumerates the complete locked feature/target graph and
rejects **every** reachable `glib` version. This prevents another affected
version from becoming Windows-reachable. A lockfile entry alone does not show
that a package ships for a particular target.

`cargo audit` still reports this as an allowed `unsound` warning. Its warning
classification explains the successful exit; target exclusion explains the
Windows exposure boundary. Neither closes the advisory. Linux development
builds do not qualify Linux releases: release support requires removing or
upgrading the affected GTK path and passing the Linux build/runtime matrix.
Repeat the classification whenever Tauri/Wry features change, Linux becomes a
release target or the Windows guard finds GLib.

The other current warning is unmaintained `proc-macro-error` `1.0.4`
(`RUSTSEC-2024-0370`). The refreshed graph removes the old `unic-*` paths. Do not add `cargo audit -D warnings` until that
upstream graph no longer reports the unshipped transitive warnings. Report the
current audit output; old warning counts are not current evidence.

The optional native WDIO driver temporarily pins the reviewed upstream fix
`fb4a544bcc49605f6c6fb34f04b292abf428a72a` from
[PR #687](https://github.com/webdriverio/desktop-mobile/pull/687), because published
1.4.0 fails against Tauri 2.12's WebView2 bindings. Direct Windows bindings align
at 0.62.2 / Windows-future 0.3.2. The Git pin is test-only, is outside the normal
production graph, and has exact source/license evidence in the provenance
manifest. Remove the pin when a compatible published release passes native WDIO
checks. It is not an advisory ignore.

## Provenance and notice review

The [shipped dependency inventory](../../SHIPPED_DEPENDENCY_INVENTORY.json),
[notice bundle](../../SHIPPED_DEPENDENCY_NOTICES.json) and
[third-party provenance](../provenance/THIRD-PARTY.md) must match exact installed
sources. Preserve attribution when updating packages.

[Notice metadata exemptions](../../SHIPPED_DEPENDENCY_NOTICE_EXEMPTIONS.json)
identify exact packages whose archives omit a standalone license file and bind
reviewed source/metadata bytes instead. They **do not suppress vulnerabilities**,
waive licenses or alter audit results. Stale or unnecessary notice exemptions
must fail the inventory check.

## Change rules

- Repair high/critical findings; review lower-severity findings and apply
  compatible fixes when available. Prefer removing an affected dependency path
  over inventing an unpublished package or forcing an untested major upgrade.
- Keep audit ignores empty. Any future Rust risk acceptance needs explicit CI
  configuration, a short justification here and a concrete removal condition.
- Keep the Windows GLib guard until the alert is removed or new executable
  evidence supports a deliberate policy change.
- Tauri/GTK feature changes and Linux release support require a target-all audit
  and renewed review of every open target-specific alert.
- Verify the actual consumer, renew provenance/notices and record the exact
  checked revision before treating a dependency update as release-ready.

## Earlier decisions

The August 3, 2026 compatible `brace-expansion` backports (`1.1.18` / `2.1.4`)
removed the old development-tool exception and its production-only reachability
guard. They addressed `GHSA-mh99-v99m-4gvg` and `GHSA-rgw5-rvv9-x895`.
PostCSS `8.5.23` addressed `GHSA-r28c-9q8g-f849` and `GHSA-fxqj-rqcc-2cmp`;
Undici `6.28.0` / `7.29.0` addressed `GHSA-8xcm-r25x-g524` and
`GHSA-4cwx-7wf7-3272`. The development-only Puppeteer proxy chain was patched
with `ip-address` `10.3.1` for `GHSA-mwp4-54f8-5fhr`. None used an audit ignore.

The July 20 Windows classification inspected 994 package lines with no GLib,
passed a locked Windows check and found the affected target-all path through
GTK `0.18`, WebKitGTK `2.0.2`, Wry `0.55.1` and Tauri `2.11.5`. The July 13 audit
reported 17 warning-class findings. Those observations describe their dated
heads; they are not receipts for the current refresh.

Rust ignores `RUSTSEC-2026-0194` and `RUSTSEC-2026-0195` were removed after
`plist` `1.10.0` adopted `quick-xml` `0.41.0`.
