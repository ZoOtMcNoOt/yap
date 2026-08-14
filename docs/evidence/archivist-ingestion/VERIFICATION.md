# Archivist ingestion verification

**Status:** Focused exact-head implementation, real PostgreSQL verification,
hosted review, and merge passed. The separate Archivist product vertical later
merged through PR #177. Student's separately qualified product vertical later
merged through PR #178. Exact `2dcecef4...` privately qualifies the Curator
product server boundary; its vertical remains unmerged pending hosted review.

## Exact candidate

- Executable head: `3ec9885ee902926f3f7672d2438e1da23c18c284`
- Base: merged Scribe head
  `ec3af506da68bbb7a0ce855369dd09c8a791742d`
- Hosted-green head: `e1899db7312643a32ae67cfdf196aa3c1d40a298`
- Merge: [PR #165](https://github.com/mcnatg1/yap/pull/165) as
  `2a7ec819edbf03a4f3fd3fe8de92ddad5bfd71f9`
- Work class and route: `BACKGROUND_IO` / `SERVER_IO`; no LLM or GPU route

## What the focused evidence proved

- Archivist accepts only an authenticated owner-scoped durable reviewed-capture
  identity. It does not accept caller-supplied transcript, title, owner, or raw
  source content.
- Compilation runs in an owner-private temporary workspace and reuses the
  existing deterministic OKF compiler, reviewed-source admission, generation
  ledger, cancellation, and broker owners.
- The workflow re-reads the exact durable capture before committing admission
  and staging in one transaction. It never embeds or activates a generation.
- Exact retries are idempotent only when the source admission and complete
  persisted non-embedding generation match; conflicting content fails closed.
- Queueing, queue-inclusive deadline, active and queued cancellation,
  cancellation acknowledgement, invalid source handling, wrong-route
  containment, and no success after failure are covered by focused tests.
- Two real PostgreSQL tests proved exact retry and restart read-back with one
  admission, one staged build, and no active generation; cross-owner and
  pre-cancel paths wrote no generation.
- The owned pinned PostgreSQL 17 / pgvector 0.8.6 ARM64 lifecycle ended with
  container, loopback listener, network, owned process, same-label owners, and
  volume all absent.

## Public verification

- The complete portable server suite ran 1,207 tests with 32 declared
  platform/database skips and no failures.
- The focused Archivist modules ran nine tests locally: seven passed and two
  database-only cases were declared skipped without a test DSN.
- The same two database cases passed against the owned real PostgreSQL runtime.
- Relevant unit and knowledge-owner tests ran 28 tests with only the expected
  local database skips and no failures.
- Server-wide Ruff, Python compilation, and `git diff --check` passed.
- A disposable private-server worktree matched the exact candidate tree and was
  removed after successful zero-residue teardown.
- The exact hosted successor passed all 12 required checks before merge.

## Deliberate limits

This evidence closes and merges only the Archivist core workflow. It does not expose an
HTTP/native/UI product surface, activate knowledge, integrate Student or Curator,
prove the complete Slice D audit matrix, run an LLM, prove simultaneous Qwen and
Gemma residency, establish sustained capacity/SLOs, or promote a production
service. No DSN, credential, database content, private path, or raw reviewed
source belongs in this record.
