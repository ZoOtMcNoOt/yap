# Reviewed bounded embedding integration

Owner: Grant McNatt. Date: 2026-10-05 UTC.
Status: all seven bounded software outcomes verified and integrated through
[PR #209](https://github.com/ZoOtMcNoOt/yap/pull/209). The whole project goal stays
active; this is software integration, not model or enterprise qualification.

The reviewed tested head is
`996109b946423a6c8e85fbd7288cd483f3cdb4d4`. [Run 568, attempt 1](https://github.com/ZoOtMcNoOt/yap/actions/runs/37278373605/attempts/1)
passes all six required jobs and their final exact-checkout guards. The complete
hosted frontend browser suite passes all 251 cases in 6.2 minutes. The fixed
browser runner prebundles the specific test/fixture entries while preserving the
development overlay and application assertions; this does not replace the browser
journeys with a production-only smoke or weaken their acceptance conditions.

PR #209 merged as `fefbfc114fbf4967b6615f1aa49b3f99a05dc778` after PR #208.
Fetched main's tree `ca83bad3dbb7285797516d0449d513fe1ca1ce84` equals the tested
head's tree. Tag `reviewed/pr-209-996109b9` preserves the tested head; the clean
completed branch and owned worktree were retired only after that comparison.

The delivered provider preflights at most 1,024 unique nonempty reviewed chunks
and 4 MiB of exact UTF-8 source, packs requests with at most 64 chunks and 256 KiB
each, shares one configured total deadline, validates every indexed finite
768-dimensional response and commits only the complete generation through the
existing atomic owner. Replay remains provider-free and published vectors remain
immutable. [Local verification](verification.md) and [independent review corrections](review-verification.md)
retain the real HTTP/PostgreSQL source-to-prepare/publish/read/restore journey,
165 skip-free SQL cases, 215 skip-free portable cases and 1,678 isolated server
passes with 162 declared exclusions.

The earlier `af3a65c8f31fde29556d7bc126fb4e1bdf759af6` head's
[run 37272605309](https://github.com/ZoOtMcNoOt/yap/actions/runs/37272605309)
recorded 249 browser passes and two initial-navigation loopback resource failures.
That failed result is retained as an observation, receives no complete-suite or
integration credit and is superseded by the complete reviewed run above. The
original local failures and admission/late-dispatch review corrections remain in
their dated evidence; they were not erased by the successful integration.

Synthetic vectors and deterministic identities verify orchestration, persistence,
permission isolation and recovery against actual HTTP/PostgreSQL. They do not
qualify embedding quality/provenance, representative provider capacity, production
identity, physical Windows operation or enterprise deployment. Timed speaker
export and Ogg FLAC remain separate unmerged PRs, and the full roadmap remains
active.
