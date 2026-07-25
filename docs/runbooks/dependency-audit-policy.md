# Dependency Audit Policy

Yap treats `cargo audit` vulnerabilities as release blockers unless the risk is
explicitly accepted in CI with a removal condition. Warnings are reviewed, but
they do not fail CI by themselves.

## Frontend Registry Audit

The desktop release gate and hosted CI run:

```powershell
pnpm audit:dependencies
```

That command executes the real `pnpm audit --audit-level high` check. It retries
only explicit transient registry or network failures on a bounded
10-second, 30-second, 60-second, and 120-second schedule. It disables pnpm's
internal fetch retries so the enclosing schedule remains bounded. A reported
vulnerability, certificate or configuration error, unrecognized failure, or
exhausted registry retry still fails the audit. Do not use
`--ignore-registry-errors` in a release gate.

The workspace policy contains exactly one accepted frontend advisory exception:
`GHSA-mh99-v99m-4gvg`. A unit test fails if that list expands or changes
silently, and the hosted workflow names the documented policy boundary. Before
the registry audit runs, the same command queries the installed production
dependency graph with `pnpm why --prod` and fails closed if `brace-expansion`
is reachable there. This guard is independent of pnpm's advisory ignore and
prevents the exception from silently masking a future production path.

### Frontend development-tool exception

On July 24, 2026, the registry began reporting
`GHSA-mh99-v99m-4gvg` for every `brace-expansion` release through 5.0.7.
The fix is available in 5.0.8, whose API and packaging are a breaking change
for the older `minimatch` consumers in WebdriverIO's development-only CLI,
glob, archive, and scaffolding graph. The locked product dependency graph
reports no known vulnerability under `pnpm audit --prod`.

Yap temporarily accepts this one development-tool advisory because:

- every reachable path is under the desktop test/build toolchain;
- no shipped application code imports `brace-expansion`;
- the checked commands use repository-owned glob patterns rather than
  attacker-controlled patterns; and
- forcing 5.0.8 underneath older `minimatch` majors would replace a known
  development-tool risk with an unreviewed compatibility break in the release
  gate.

The exception must be removed as soon as the WebdriverIO/glob/minimatch graph
offers compatible patched releases, or when the old scaffolding dependency can
be removed without weakening desktop verification. Any new use of
attacker-controlled glob patterns, any production-reachable path, or any second
ignored frontend advisory invalidates this acceptance immediately.

The same July 24 audit also reported
`GHSA-r28c-9q8g-f849` in PostCSS 8.5.16. That finding has a compatible upstream
fix and is resolved by the workspace's exact PostCSS 8.5.18 override; it is not
ignored.

## Current Rust Policy

CI runs `cargo audit` for the Windows desktop target:

```powershell
cargo audit --target-os windows --target-arch x86_64
```

Warnings from Tauri's transitive target-all desktop stack are allowed while the
desktop app targets Windows first. The current warning set includes GTK3
bindings, `glib`, `proc-macro-error`, and `unic-*` crates pulled through that
graph. Do not add `cargo audit -D warnings` until the upstream Tauri dependency
graph no longer reports those warnings for crates we do not ship directly.

As of July 13, 2026, the CI command reports 17 allowed warning-class findings
and no vulnerability-class failure. Those warnings include the `glib`
unsoundness advisory described below.

## Open Target-Specific Alerts

GitHub Dependabot alert `GHSA-wrw7-89jp-8q8g` remains open for `glib` 0.18.5.
The advisory is medium severity, affects versions from 0.15.0 through 0.19.x,
and is patched in 0.20.0. The vulnerable crate is present in `Cargo.lock`
through Tauri's Linux GTK dependency path when Cargo resolves all targets.
CI enumerates the full locked Windows graph with `cargo tree --locked --offline
--target x86_64-pc-windows-msvc --prefix none --format "{p}"` and fails if any
package line starts with `glib v`. This broader boundary prevents a second
advisory-affected `glib` version from becoming Windows-reachable while 0.18.5
remains present only in the Linux graph. CI also fails if Cargo cannot complete
the graph inspection.

The Windows-scoped `cargo-audit` command still emits this lockfile advisory as
an allowed `unsound` warning. CI passes because warning-class findings are not
denied; the target distinction limits shipped exposure but is not what makes
the command exit successfully. This does not dismiss or close the alert. Keep
the GitHub alert open until the affected path is removed or upgraded. Enabling
Linux support, or changing the Tauri/GTK dependency graph, requires
reevaluating this alert before release and either removing the GTK path or
upgrading it to a graph that uses `glib` 0.20.0 or later.

### July 20, 2026 target classification

Focused inspection of the current Phase 6 worktree produced the following
public-safe evidence:

- the exact locked `x86_64-pc-windows-msvc` graph contained 994 package lines
  and no package line beginning with `glib v`;
- the default host reverse-dependency query also found no reachable `glib`;
- the target-all reverse graph reaches `glib` 0.18.5 only through the GTK 0.18,
  WebKitGTK 2.0.2, Wry 0.55.1, and Tauri 2.11.5 desktop path; and
- a normal locked Windows `cargo check` completed without a GLib or native
  compiler warning, while the release-contract test continued to prove that CI
  fails closed if any `glib` version becomes Windows-reachable.

This evidence classifies the current alert as follows:

- **Supported Windows product defect:** no. The affected crate is not in the
  resolved Windows feature/target graph.
- **Upstream target-all warning:** yes. `glib` 0.18.5 remains in the locked
  Linux GTK/Tauri path and remains covered by `RUSTSEC-2024-0429`.
- **Missing platform gate:** Linux release support remains gated. Yap must not
  advertise or enable Linux release support until the GTK path is removed or
  upgraded and the Linux build/runtime matrix passes.
- **Pin or patch action:** none on this evidence. Yap has no direct `glib`
  dependency, and editing or pruning lockfile entries would not change the
  active Tauri dependency graph. A package entry in `Cargo.lock` is not proof
  that the package is reachable for a supported target and active feature set.

The classification must be repeated if Tauri/Wry features change, Linux becomes
a supported target, or the exact Windows graph guard reports a reachable
`glib` package.

## Ignored Rust Advisories

The CI ignore list is empty. `RUSTSEC-2026-0194` and `RUSTSEC-2026-0195` were
removed after `plist` 1.10.0 moved the transitive parser to `quick-xml` 0.41.0.

## Change Rules

- New unignored vulnerabilities must fail CI.
- The Windows graph guard must reject every reachable `glib` version until the
  alert is removed or this policy is deliberately revised with new executable
  evidence.
- New ignores require a short justification and a removal condition in this
  runbook and `.github/workflows/ci.yml`.
- Dependency updates should prefer removing ignores over expanding the list.
- Linux support and Tauri/GTK dependency changes require a target-all audit and
  explicit reevaluation of every open target-specific alert.
