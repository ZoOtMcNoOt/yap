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

Executable remediation commit
`8e3ece5a3580ec29116c05f31b045a5748c143b8` and its current
documentation-only descendant have the following focused, non-promotional
verification. Commands are shown from their working directory; the Windows
runs used the locked project environment and Python 3.12.

- From `server`,
  `uv run --locked ruff check . ../infra/yap-server-node/owned-process-supervisor.py`
  passed.
- From `server`, with `PYTHONPATH=src`,
  `uv run --locked python ../verification/run-governed-knowledge-portable-suite.py`
  ran the exact 24-module/130-test membership: 126 passed, three declared
  platform/capability skips, and one strict stale-route-lock failure. No other
  failure or unexpected/expected-failure classification occurred. The lock
  failure is the required fail-closed blocker until a fresh private
  qualification replaces the Phase 9 predecessor; this is not a green
  checkpoint claim.
- From `server`, with `PYTHONPATH=src`,
  `uv run --locked python -m unittest tests.knowledge.test_okf_compiler tests.knowledge.test_cancellable_database_operation tests.knowledge.test_governed_knowledge_mcp tests.knowledge.test_governed_rag_agent tests.evaluation.test_agent_model_fixture_runner tests.evaluation.test_agent_model_scoring`
  ran 40 tests: 39 passed and one Windows directory-link capability test
  skipped. This covers canonical POSIX path/generation/profile/resource identity,
  durable-write curated authorization, strict nested MCP inputs, exact
  database-worker cancellation acknowledgement, and shared evaluator/product
  tool bounds.
- From the repository root,
  `pwsh -NoProfile -NonInteractive -ExecutionPolicy Bypass -File ./verification/list-maintainability-threshold-surfaces.ps1 -MinimumLines 250 -Json`
  enumerated 473 tracked regular surfaces: 250 at or above 350 lines and 223
  from 250 through 349. A read-back comparison of the 350-line output against
  `THRESHOLD-DISPOSITION.md` found all 250 exact paths and zero differences.
- On the ARM64 qualification host at exact code commit
  `8e3ece5a3580ec29116c05f31b045a5748c143b8`, the gate-owned locked PostgreSQL
  17 / pgvector 0.8.6 runtime invoked, from `server` with `PYTHONPATH=src`,
  `uv run --locked python ../verification/run-governed-knowledge-postgres-suite.py`.
  All 17 mandatory tests across four modules passed with zero skips, expected
  failures, or unexpected successes. The set includes autocommit generation
  pinning, reviewed/curated source authority, durable-row rehashing,
  stage/activation tamper rejection, permission-safe retrieval,
  proposals/retention, and terminology ownership.
- At the same exact head, a focused owned-runtime diagnostic performed a real
  database process restart, retained the same container identity, observed a
  new process and re-read loopback binding, recovered cited retrieval, rejected
  the stale generation, retrieved the successor, and proved container,
  listener, process, same-label owner, network, and volume teardown. It did not
  publish or consume the complete checkpoint gate.

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
