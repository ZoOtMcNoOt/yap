# Reviewed rollback integration

Owner: Grant McNatt. Date: 2026-10-04. Status: 6/6 bounded software outcomes
verified and merged; the full project goal remains active.

[PR #206](https://github.com/ZoOtMcNoOt/yap/pull/206) merged as
`d2d3685bdb5d45e6387257113ebe4c27c197c42c`, after all six required jobs passed
on exact head `85ce2adafd3e19bdd0c58b6c4bf09f76cd0b7af3` in
[run 552](https://github.com/ZoOtMcNoOt/yap/actions/runs/37222318769).
The frontend/browser, Rust/native, portable server, mock OIDC/required SQL,
Linux lifecycle and native WDIO jobs all succeed. Automated review reports no
findings; final bounded review and thread inspection find no unresolved defect.
The merge used the expected exact head. An actual Git tree comparison after
fetching main returned no difference from that tested head.

The tested head remains under pushed annotated tag `reviewed/pr-206-85ce2ada`;
the completed remote/local branch and owned scratch worktree are retired.
[Local verification](verification.md) retains the original 404 and all 152
required real PostgreSQL cases/201 portable checks without skips, atomic restore,
concurrency, ownership, failed audit and retained original-vector recovery.

These are software checks with fixture principals and synthetic vectors. They do
not qualify real embeddings, physical Windows behavior, enterprise identity or
production deployment. Continue explicit embedding generation, full product
rebuilding and the whole roadmap; the project is not complete.
