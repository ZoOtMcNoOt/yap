# GLib borrowed iterator security repair — October 7, 2026

`GHSA-wrw7-89jp-8q8g` / `RUSTSEC-2024-0429` identifies an immutable
pointer passed to `g_variant_get_child` as a mutable C out-pointer. Every
borrowed string iterator direction reaches that helper. The compiler may
retain the original null pointer, causing undefined behavior even for an
ordinary valid string array. No direct application call was found; the
unsafe implementation remains present in the Linux GTK3 dependency graph.

The original `glib` 0.18.5 release was reproduced with a separate optimized
Rust test: the borrowed iterator test terminated with SIGSEGV. The ordinary
allocating iterator control passed. The identical two tests pass with the
backport, without skips. They cover next/nth/last/next_back/nth_back,
collection in both directions, mixed directions, Unicode, empty strings,
empty arrays, exhaustion and wrong-type rejection. The repository regression
is run with `cargo test --release --locked` in the required Linux CI job.

The complete 121-file published archive is retained in
`desktop/src-tauri/vendor/glib`, preserving LICENSE and COPYRIGHT. Archive
SHA-256 is `233daaf6e83ae6a12a52055f568f9d7cf4671dabb78ff9560ab6da230ce00ee5`.
Only `src/variant_iter.rs` differs, by the two lines from upstream
[PR #1343](https://github.com/gtk-rs/gtk-rs-core/pull/1343), commit
`b5a4071e439bef2b5eea76c3aa25e5ae84839e34`. Its repaired SHA-256 is
`a0f5ee8acb8faa089bcdfbc9a57372609fce7654026ccef7d9a224d05a654ccc`.
The version remains 0.18.5; no unpublished fixed version is invented.

The published fix starts at 0.20.0, incompatible with the current GTK3
bindings. Upstream's 0.18 branch still points to the original release;
[backport PR #2009](https://github.com/gtk-rs/gtk-rs-core/pull/2009) closed
unmerged and the branch is EOL. This backport therefore creates an explicit
local maintenance obligation. Remove it when a compatible maintained
binding graph passes the same behavioral and platform checks.

`cargo-audit` 0.22.2 excludes path packages from advisory matching. Audit
success or a missing GLib warning alone proves nothing about this repair.
The source-integrity gate independently verifies every archive file and the
exact selected Linux package before both shipped inventory checks and the
Windows audit. Negative tests reject a reverted repair, modified license,
missing/extra file, registry fallback, alternate local source and absent
Linux selection. The optimized executable regression is an additional gate.
Modern GLib 0.21 remains unchanged. The full Windows graph still excludes
GLib, enforced by the existing Windows boundary check.

These checks do not qualify Linux production builds. GitHub security alert
lists returned Forbidden; authenticated browser inspection is unavailable
in this session. CodeQL analysis success does not establish that its alert
list is empty. Actual GitHub alert closure remains unverified.
