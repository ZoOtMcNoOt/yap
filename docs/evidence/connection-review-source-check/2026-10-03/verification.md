# Check a connection review package against its sources

**Owner:** Grant McNatt. **Date:** 2026-10-03. **Status:** Four local software outcomes verified; integration pending.

The [operator command](../../../specs/connection-review-package.md#check-the-sources-locally)
checks an exported proposal against an explicitly selected complete OKF bundle.
It reuses the bounded artifact reader, typed candidate/citation contracts and OKF
compiler. No dependency, service route, database, credential or model is added.

## Verified behavior

- Version-1 proposed packages are bounded to 65,536 bytes. Duplicate/extra fields,
  unsupported status, malformed references and inconsistent endpoints are refused.
- An explicit tenant and revision compile the complete bundle. Its generation
  must match; both endpoint identities, metadata, original file-byte hashes and
  parsed-body Unicode spans must reproduce the quotes exactly.
- Success returns a content-free `source-matched` receipt with the exact checked
  package-byte digest. CLI refusal exits `2` with a static message and no source
  text, including when a typed validation exception would contain the input.
- Actual before/after file snapshots prove the checker preserves package and
  source bytes. Fixtures exercise Unicode, frontmatter versus body hashing,
  changed content/policy/revisions, forged metadata, malformed/oversized/deep JSON,
  missing sources and linked trees. Subprocess checks exercise the actual CLI.

## Software checks

**29 focused tests pass:** eight source-check cases, nine existing compiler cases
and 12 governed-gate contracts. **All 185 governed portable cases pass**, with no
skips, expected failures or unexpected successes. The shared required population
now includes the eight source-check cases; the 117-case database gate is unchanged.
Historical qualification receipts retain their original populations and hashes.

The complete server regression passes in the pinned isolated Ubuntu/Python 3.12
runtime: **1,648 passes and 114 declared platform/database exclusions** (1,762
total). The initial attempt stopped at cloud disk capacity; removing only
reproducible first-party Rust build outputs allowed the unchanged suite to finish.
No test or refusal was weakened.

Ruff lint passes across server source/tests and both PostgreSQL verification
scripts. **14 documentation/license/provenance/browser-population contracts pass**, with
no skips. Formatting passes for the three changed Python files; the repository-wide
format check still reports 206 existing files, which this increment does not rewrite.

From the repository root, after preparing the documented cloud environment:

```bash
source verification/cloud-env.sh
(cd server && PYTHONPATH=src .venv/bin/python -m unittest \
  tests.knowledge.test_connection_review tests.knowledge.test_okf_compiler \
  tests.evaluation.test_governed_knowledge_gate)
(cd server && PYTHONPATH=src .venv/bin/python ../verification/run-governed-knowledge-portable-suite.py)
bash verification/test-cloud-server.sh
```

## Review and integration limits

The revision is an explicit compiler input label. The checker does not fetch or
verify a Git commit, authenticate the original proposal/rationale, or establish
current server permissions. Compilation matches the compiled generation; it does
not authenticate every byte of a Git tree. Review provenance, access, rationale
and approval separately. Canonical admission still requires an authorized
`knowledge.curator`, reviewed sources and complete projection before activation.

GitHub reports `USER_NOT_LOGGED_IN`; pushing, a PR and all six exact-head hosted
jobs remain pending. These model-free Linux checks do not qualify Windows,
enterprise policy, production embeddings or reasoning. The project goal remains
active, and issue #92 remains open for actual Windows RDP/session-lock verification.
