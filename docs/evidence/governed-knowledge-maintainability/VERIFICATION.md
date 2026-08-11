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

The source-admission and lifecycle remediation was completed at
`8e3ece5a3580ec29116c05f31b045a5748c143b8`. The route-qualification
remediation is frozen at
`a62a18916a57d914ee74d3f876ee18418e226ffb`; its current documentation-only
descendant has the following focused, non-promotional verification. Commands
are shown from their working directory; the Windows runs used the locked
project environment and Python 3.12.

- From `server`,
  `uv run --locked ruff check . ../infra/yap-server-node/owned-process-supervisor.py`
  passed.
- From `server`, with `PYTHONPATH=src`,
  `uv run --locked python ../verification/run-governed-knowledge-portable-suite.py`
  ran the exact 24-module/132-test membership: 128 passed, three declared
  platform/capability skips, and one strict stale-route-lock failure. No other
  failure or unexpected/expected-failure classification occurred. The lock
  failure is the required fail-closed blocker until a fresh private
  qualification replaces the Phase 9 predecessor; this is not a green
  checkpoint claim.
- From `server`, with `PYTHONPATH=src`, the focused agent acceptance, fixture,
  qualification, scoring, route-artifact, pressure, vLLM metric/runtime,
  governed-answer, and reasoning-client modules ran 56 tests: 55 passed and
  one Windows POSIX-permission test was declared inapplicable. This verifies
  that denied-resource wording is not confused with an emitted forbidden
  tool, the route-specific output bounds remain frozen, empty-result prompts
  are explicit, and the strict evidence/lifecycle contracts remain intact.
- From `server`, with `PYTHONPATH=src`,
  `uv run --locked python -m unittest tests.knowledge.test_okf_compiler tests.knowledge.test_cancellable_database_operation tests.knowledge.test_governed_knowledge_mcp tests.knowledge.test_governed_rag_agent tests.evaluation.test_agent_model_fixture_runner tests.evaluation.test_agent_model_scoring`
  ran 42 tests: 41 passed and one Windows directory-link capability test
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

## Rejected qualification evidence

The one fresh private route qualification at exact head
`0cd9a9f88123f1f4fd1caaf42e03dce02658bfd6` completed both owned model
lifecycles and exact teardown, then correctly returned `deterministic-no-model`
with public-safe evidence SHA-256
`0beaa4d04ccef663e89b215b97b14edbb7fd786c2c354179d896cb0ca65794b5`.
It is retained as rejected private evidence and cannot be used for admission.
The follow-up remediation keeps every latency and correctness threshold intact;
it narrows forbidden-tool scoring to actual emitted tool identities, makes
empty-result instructions explicit, and assigns smaller output bounds to the
rapid route and larger structured-answer bounds to the complex route. No raw
model output, private measurement, log, or private artifact location is
published here.

## Complete checkpoint gate

Not yet consumed. The rejected `0cd9a9f8...` run is terminal for that exact
candidate. Protected tool/runtime inputs changed at `a62a1891...`, so the old
Phase 9 evidence and the rejected run are both intentionally inadmissible. One
new qualification is required only after the three reviewers approve this
exact remediation head; the aggregate checkpoint matrix remains a separate
one-shot gate after the new public-safe route lock is frozen.

## Hosted closure

Pending exact-head PR checks and merge. Production supervision, simultaneous
model residency, sustained mixed-owner capacity/SLOs, enterprise networking,
and deployment remain Phase 10 or explicit IT/security handoffs.
