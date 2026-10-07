# Dependency remediation — October 7, 2026

## Source and scope

The starting main revision was `53c4c23ff03825f4238774aefec395457ff56ec6`.
Dependabot PRs 213–217 cover GitHub Actions, Vitest, Cargo minor/patch updates,
windows-future and dirs. The GitHub Actions update was independently reviewed
at `ca19010126cecabe55ecfbc4b0562d6b0246c371`; all six CI jobs and unchanged
checkout guards passed in run 579 (`37561041606`). PR 213 merged as
`6b72e9b44c536a0f51e374341bcf28d6e4efbc1c`; fetched main's tree matched its
tested head. The annotated tag is `reviewed/pr-213-ca190101`.

The combined repair includes the Vitest/Cargo/dirs updates and the frontend
advisory fix. It migrates ORT's removed array-extraction call to checked dynamic
tensor extraction, preserving the required f32 type, exact `[1, 107]` shape
and existing error behavior. Exact Windows-target shipped dependency inventory,
source notices and pinned-driver local integrity hashes are regenerated.
The matching Linux Sherpa 1.13.8 native archive is downloaded from the upstream
release; its observed SHA-256 is
`e1fdc5b67530e15741ef897fa5ffff297056f3bf0c6d829a27af9225a4c4b5a6`.
The cloud setup checks those exact bytes before using that archive. The first
native check stopped because the old cloud cache contained only Sherpa 1.13.4;
that setup failure is not credited as a passed compile.

## Frontend advisory

The baseline full pnpm audit reports `GHSA-73rr-hh4g-fpgx` for diff 7.0.0
through `@wdio/mocha-framework > mocha`. The affected parsePatch/applyPatch
entry points can hang on a carriage-return-bearing patch header. A separate
child running the baseline parser with `--- a\rb` was killed after two seconds
without returning. Mocha itself uses createPatch/diffWordsWithSpace for
assertion reporting, rather than the affected parsing entry points.

The exact consumer override `mocha@11.8.0>diff: 8.0.4` removes the affected
package while retaining Mocha 11.8.0 and WDIO 9.32.0. Patched parser checks
exercise three hostile header representations through parsePatch and applyPatch
in a bounded child, plus an ordinary create/apply roundtrip. Consumer-resolved
Mocha checks exercise both unified and inline assertion diffs and reject its
swallowed-error report. Existing actual-adapter checks retain async hooks,
retries, skips, and success/failure event reporting.

Verified locally:

- Frozen pnpm installation passes; full JSON audit reports zero vulnerabilities
  at every severity, with no ignores.
- `pnpm --dir desktop test:wdio-framework`: four checks pass, zero skips.
- `pnpm --dir desktop build`: TypeScript and Vite pass.
- A separate TypeScript check of `desktop/vite.config.ts` passes, including the
  Vitest 5 public `TestUserConfig` import from `vitest/config`.
- `pnpm --dir desktop test`: 417 pass, two declared Windows-only exclusions.
- Third-party provenance integrity check passes.

The hosted exact-head six-job CI and required clean-all checks must pass before
integration; their final result is retained on the repair PR and tested tag.

## Windows binding compatibility

PR 216's standalone windows-future 0.100 update fails hosted Windows compilation:
its windows-core types cannot implement the interfaces/runtime types expected
by windows 0.62.2's WAM bindings. The repair pins the matching 0.3.2 exactly and
defers >=0.100 version updates until coordinated Windows binding migration.
No authentication path, fallback or security boundary is weakened.

PR 215's ORT API compile failure and PRs 215–217's stale inventory/provenance
failures are retained in their original CI runs 581–583. Those failures are
resolved by consumer migration and regenerated evidence, not bypassed checks.

## Boundaries and unresolved intake

Both GitHub security endpoints returned Forbidden:
`/repos/ZoOtMcNoOt/yap/code-scanning/alerts` and
`/repos/ZoOtMcNoOt/yap/dependabot/alerts`. This is an intake blocker, not an
empty alert result. The GitHub security pages were opened for the user, but the
session has no tool to inspect their authenticated browser content.

The known GLib 0.18 Linux GTK advisory and upstream warning classifications
remain governed by the dependency audit policy. Windows graph exclusion does
not resolve a Linux advisory. Real-model, physical Windows, enterprise and
Linux-release qualification are not established by these software checks.
