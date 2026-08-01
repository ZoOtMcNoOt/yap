# Fast local Rust checks without a Windows machine

The desktop crate type-checks and lints against the Windows target from any
host, including arm64 Linux, in seconds. Use this instead of pushing to CI to
find compile errors.

| | cold | incremental |
| --- | --- | --- |
| `cargo xwin check` on the arm64 Linux host | 21.5 s | **0.24 s** |
| `cargo clippy --all-targets` on the same host | 12.5 s | |
| The same work on the hosted Windows runner | 4 m 09 s | |
| Full `rust` CI job | | 17 m 53 s |

## Why this works when a plain `cargo check` does not

A plain `cargo check` on Linux targets Linux, and `tao` pulls the whole GTK
stack behind `cfg(target_os = "linux")`. That needs fourteen pkg-config system
libraries this repository never ships, because the only bundle target is
`nsis`.

Targeting Windows removes them. `cargo tree --target x86_64-pc-windows-msvc -i
gtk-sys` prints `nothing to print`: zero pkg-config crates against 14 for the
Linux target. GTK is a Linux-target dependency, not a Tauri dependency.

## Setup, once

```bash
rustup target add x86_64-pc-windows-msvc --toolchain 1.96.0
rustup component add llvm-tools --toolchain 1.96.0
cargo install --locked cargo-xwin
```

The first run downloads the MSVC CRT and Windows SDK into `~/.cache/cargo-xwin`
(about 1.1 GB, roughly seven minutes). Microsoft's SDK licence applies:
https://go.microsoft.com/fwlink/?LinkId=2086102

## Running it

```bash
export PATH=/usr/lib/llvm-18/bin:$PATH          # provides llvm-rc
cd desktop/src-tauri
cargo xwin check  --locked --target x86_64-pc-windows-msvc
cargo xwin clippy --locked --target x86_64-pc-windows-msvc --all-targets
```

For editors, point rust-analyzer at the same target so Windows code stops
showing as dead or unresolved:

```json
{ "rust-analyzer.cargo.target": "x86_64-pc-windows-msvc" }
```

## Two failures that look like something else

**`error[E0463]: can't find crate for 'core'`** — `rustup target add` without
`--toolchain 1.96.0` installs the target for `stable`, not for the toolchain
pinned in `rust-toolchain.toml`. Add the flag and rerun.

**`NotAttempted("llvm-rc")` from `tauri-winres`** — `llvm-rc` exists at
`/usr/lib/llvm-18/bin/llvm-rc` but is not on `PATH`. Export it as above.

## What this does not replace

`cargo test` still has to run on Windows. The suite drives WebView2, WASAPI
capture through `cpal`, and sherpa-onnx; running it under wine is not viable.
This gives fast compile and lint feedback, not test results.

MSI and NSIS bundles also still need Windows, and a `--release` cross-build
would need `pnpm build` to produce `../dist` first.

## It really does check Windows code

The crate has 124 `cfg(windows)` sites across 30 files. To confirm the check is
not silently skipping them, put a type error inside one and run it:

```rust
#[cfg(windows)]
fn __probe() -> u32 { let v: std::path::PathBuf = 7u32; v }
```

`cargo xwin check` reports `error[E0308]: mismatched types` at that line. Remove
the probe afterwards.

This is also why a workspace split is not a substitute: 43 of the 376
`tauri`-free files still use `windows::` or `cfg(windows)`, so a core crate
tested against the Linux host target would skip them and report success it has
not earned.
