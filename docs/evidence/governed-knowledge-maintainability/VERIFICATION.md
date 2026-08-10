# Governed Knowledge Maintainability Verification

This record separates inherited merged evidence, focused repair checks, and the
one complete checkpoint gate. It remains incomplete until the reviewed
checkpoint candidate merges.

## Inherited Phase 9 evidence

- Merged base: `ae81ff067c73a64528eecc14403765562726f2fe`.
- Phase 9 gate candidate: `a4f34678ea9980379b18266d40d3347b818ac57e`.
- Public-safe gate outcome: `governed-knowledge-gate-passed`.
- Public-safe gate evidence SHA-256:
  `4013903410e22206c5b46f4dfcbf1878badc3dc9bbdfddb0ddad2ba0e2ff3260`.
- Hosted-green PR head: `fa26caaf7e3ea4e20f27b390355dff80bee2464f`.
- Merge: PR #152 as `ae81ff067c73a64528eecc14403765562726f2fe`.

The exact Phase 9 gate ran 109 portable tests across 22 modules, Ruff, nine
zero-skip Postgres tests across four modules, and a real Postgres process
restart/recovery/stale-generation/successor/teardown path. It semantically
admitted the separately hash-locked private Qwen/Gemma route evidence without
publishing private output. This is inherited evidence, not a checkpoint gate.

## Focused checkpoint verification

Core remediation commit `c332700597eac1cc6af3f68afb3e75fce0b6ec77`
and its current documentation/test-contract descendant have the following
focused, non-promotional verification:

- Locked Ruff across the server and owned-process supervisor: pass.
- Current portable membership: 24 exact modules and 129 tests. The 128 tests
  independent of the intentionally stale private-route lock passed, with three
  platform/capability skips. The complete runner fails only the strict frozen
  route-lock assertion until the newly required private qualification replaces
  the Phase 9 predecessor; this is an expected fail-closed blocker, not a green
  checkpoint claim.
- Compiler/tool/cancellation/RAG/evaluator focus: 39 tests passed with one
  platform-only directory-link skip. This includes canonical generation
  identity, authenticated curated review, strict nested MCP inputs, exact
  database-worker cancellation acknowledgement, and shared evaluator/product
  tool bounds.
- On the ARM64 qualification host, the locked PostgreSQL 17 / pgvector 0.8.6
  runtime ran all 17 mandatory tests across four modules with zero skips. The
  set includes autocommit generation pinning, reviewed/curated source
  authority, durable-row rehashing, stage/activation tamper rejection,
  permission-safe retrieval, proposals/retention, and terminology ownership.
- A separate focused owned-runtime diagnostic performed a real database process
  restart, recovered cited retrieval, rejected the stale generation, retrieved
  the successor, and proved complete teardown. It did not publish or consume
  the complete checkpoint gate.

These checks validate the repair seams while preserving the one-spend rule for
fresh private model qualification and the final aggregate matrix.

## Complete checkpoint gate

Not yet consumed. Freeze exactly one candidate only after the three reviews,
accepted P0-P2 repairs, documentation reconciliation, provenance checks, and
comprehension assessment are complete. Protected tool/runtime/dependency inputs
changed, so the old Phase 9 private route evidence is intentionally inadmissible
and one fresh qualification is required at the final reviewed code head.

## Hosted closure

Pending exact-head PR checks and merge. Production supervision, simultaneous
model residency, sustained mixed-owner capacity/SLOs, enterprise networking,
and deployment remain Phase 10 or explicit IT/security handoffs.
