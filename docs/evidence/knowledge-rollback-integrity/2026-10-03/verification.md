# Preserve published vectors through rollback

**Owner:** Grant McNatt. **Date:** 2026-10-03. **Status:** Four local software outcomes verified; integration pending.

After a successor activates, a retained generation was no longer protected by
the embedding writer's active-pointer check. A same-model write changed its
vectors, and rollback restored the changed projection. Actual PostgreSQL tests
reproduced both a direct overwrite and a writer waiting across publication and
replacement; both fail under the original writer.

The [embedding writer](../../../../server/src/yap_server/knowledge/generation_ledger.py)
now checks durable activation history as well as the active pointer while holding
the existing tenant transaction lock. Every previously published projection stays
immutable. Refusal preserves chunk vectors/model identity, build model identity,
active state and activation history. Rollback restores the original projection.
Initial complete staged preparation can still retry before its first publication.

## Verification

- **Eight real generation-ledger cases pass**, including the two new regressions.
  A separate connection demonstrably waits on the PostgreSQL advisory lock, then
  refuses after its target is published and replaced within that transaction.
- **All 119 required database cases pass without skips** on a fresh owned,
  digest-pinned PostgreSQL 17.11 / pgvector 0.8.7 runtime. The shared gate now
  requires 119 rather than 117 cases; prior receipts keep their historical counts.
- **All 185 governed portable cases pass**, with no skips or expected/unexpected
  failures. Server-wide Ruff lint, changed-file formatting and diff whitespace pass.
  All 14 documentation/license/provenance/browser-population contracts pass.

From the prepared cloud environment at the repository root:

```bash
source verification/cloud-env.sh
server/.venv/bin/python verification/run-disposable-governed-postgres-suite.py
(cd server && PYTHONPATH=src .venv/bin/python ../verification/run-governed-knowledge-portable-suite.py)
```

The disposable gate owns and removes its runtime; it never inherits an operator's
DSN. Tests use explicit synthetic 768-dimensional vectors, not model output.

## Operator boundary

Prepare vectors only on a generation that has never been published. A retained
build is a rollback target, not a mutable work area. Different embeddings require
a new compiled generation and the normal reviewed-source/projection/activation
checks. A pruned published identity still has activation history and cannot be
re-embedded through this writer. Restoring actual backups remains a separate
operations procedure; direct database edits are not authenticated repair.

GitHub remains disconnected, so pushing, review and all six exact-head hosted
checks are pending. Canonical publication, production backup/restore, real model
quality, enterprise policy and Windows qualification remain open. No schema,
dependency, source-admission authority or production promotion is added.
