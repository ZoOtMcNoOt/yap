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
`531132bf5f6186da2f7ce2588eb43279611581dc`. The reviewed qualification head
`f7fc37e3ecf673d5e8998cf13d8393ef1e7899b3` was its documentation-only
descendant. Public lock/CI commit `e15c152966e7144acac784e49282fed05b2730c5`
and documentation commit `e106b442bfa607b34c50efe66163a2539a703387`
extended it without changing protected route inputs. Admission-protection
commit `b8452f807ae6e2353a99f4d95c952e8103414709` then deliberately changed
protected route inputs; the current documentation descendant records the
required replacement qualification. The resulting candidate has the following
focused, non-promotional verification. Commands are shown from their working
directory; the Windows runs used the locked project environment and Python
3.12.

- From `server`,
  `uv run --locked ruff check . ../infra/yap-server-node/owned-process-supervisor.py`
  passed.
- From `server`, with `PYTHONPATH=src`,
  `uv run --locked python ../verification/run-governed-knowledge-portable-suite.py`
  initially ran the exact 24-module/134-test membership with 130 passed, three
  declared platform/capability skips, and the one required stale-route-lock
  failure. After the fresh admitted qualification was frozen in the public-safe
  lock at `e15c152966e7144acac784e49282fed05b2730c5`, that pre-protection
  candidate and documentation successor `e106b442...` ran the same exact suite
  green: 131 passed and the same three declared skips, with no failure,
  expected failure, or unexpected success. The portable suite does not consume
  private route artifacts. Current admission-protection commit `b8452f80...`
  separately passed its focused 60-test and 16-test sets plus Ruff, but actual
  private admission and the aggregate gate remain blocked until replacement
  qualification. None of these focused results is a complete checkpoint-gate
  claim.
- From `server`, with `PYTHONPATH=src`, the focused agent acceptance, fixture,
  qualification, scoring, route-artifact, pressure, vLLM metric/runtime,
  reasoning-route, governed-answer, and reasoning-client modules ran 60 tests:
  59 passed and one Windows POSIX-permission test was declared inapplicable.
  This verifies
  that denied-resource wording is not confused with an emitted forbidden
  tool, the route maximum output bounds remain unchanged, the one concise
  stale-generation case has a stricter frozen per-case bound, empty-result
  prompts are explicit and every empty visible result is exact-answer scored,
  cited retrieval requires its complete frozen argument map with no extra
  generation or result controls, multi-step calls allow only their frozen
  controls plus the required dynamic proposal content/citations, every visible
  citation span covers its complete supplied text, proposal terminology must
  be present in governed `proposed_content` rather than only the final answer,
  and the strict
  evidence/lifecycle contracts remain intact.
- From `server`, with `PYTHONPATH=src`,
  `uv run --locked python -m unittest tests.knowledge.test_okf_compiler tests.knowledge.test_cancellable_database_operation tests.knowledge.test_governed_knowledge_mcp tests.knowledge.test_governed_rag_agent tests.evaluation.test_agent_model_fixture_runner tests.evaluation.test_agent_model_scoring`
  ran 43 tests: 42 passed and one Windows directory-link capability test
  skipped. This covers canonical POSIX path/generation/profile/resource identity,
  durable-write curated authorization, strict nested MCP inputs, exact
  database-worker cancellation acknowledgement, and shared evaluator/product
  tool bounds.
- From the repository root,
  `pwsh -NoProfile -NonInteractive -ExecutionPolicy Bypass -File ./verification/list-maintainability-threshold-surfaces.ps1 -MinimumLines 250 -Json`
  enumerated 474 tracked regular surfaces: 250 at or above 350 lines and 224
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

These checks validate the repair seams while preserving the separate one-spend
rule for the final aggregate matrix.

## Rejected qualification evidence

Two fresh private route qualifications are retained as rejected evidence and
cannot be used for admission. At exact head
`0cd9a9f88123f1f4fd1caaf42e03dce02658bfd6`, the owned lifecycles and exact
teardown completed before the decision returned `deterministic-no-model` with
public-safe evidence SHA-256
`0beaa4d04ccef663e89b215b97b14edbb7fd786c2c354179d896cb0ca65794b5`.
At exact head `4473123e24c59eb1d929e8612fb9b38817c55a14`, both owned
lifecycles and exact teardown again completed before the decision returned
`deterministic-no-model` with public-safe evidence SHA-256
`1a5f8069d193b1ba53e188f312d564167068b19e6f35580986404abfdd540a83`.

The first follow-up made denied-resource, injection, and empty-result policy
answers exact without changing any acceptance threshold. The second run exposed
two remaining fixture-contract defects: one cited question did not match its
supplied evidence, and the stale-generation case did not freeze a concise
search/output contract. The current remediation aligns the cited question and
exact answer, freezes its governed purpose/query and exact citation span, pins
the stale-generation purpose, search text, and generation identity, and applies
a 128-token cap only to that case while preserving the reviewed 256-token
rapid-route maximum and every latency/correctness threshold. The complex route
now rejects unrequested generation/result controls on every step while retaining
only the required dynamic proposal content and citations. No raw model output,
private measurement, log, or private artifact location is published here.

One later publication attempt at exact head
`f7fc37e3ecf673d5e8998cf13d8393ef1e7899b3` returned a qualifying model
decision but failed the private-tree permission admission because nested
directories inherited a permissive launcher umask. That tree remains unchanged
and inadmissible; no public lock was minted from it. The external launcher was
then corrected to set owner-private creation mode inside the detached process,
without changing repository code, fixtures, models, or thresholds.

## Admitted checkpoint route qualification

The fresh create-once qualification at exact clean head
`f7fc37e3ecf673d5e8998cf13d8393ef1e7899b3` returned
`required-workload-routes-qualified`. The repository's semantic admission
validator then verified exact private modes and tree membership, every artifact
digest, both recomputed candidate summaries, checked inputs and dependencies,
runtime identity, cancellation/recovery, and teardown. The public-safe evidence
SHA-256 is
`24037bf66094bf97045e05aaa71a87880ca268dcdef5498b388dcff4b966c869`.
The committed lock contains only public-safe hashes and the outcome; raw model
output, measurements, logs, and the private artifact location remain outside
Git.

Subsequent adversarial review found that the semantic admission owner, gate
caller, and their contract tests were not themselves protected from descendant
drift. Commit `b8452f807ae6e2353a99f4d95c952e8103414709` places all four in the
protected route set and proves a diff naming any one is rejected. That stronger
self-protecting admission code intentionally makes the `f7fc37e3...` reference
historical for later descendants; no compatibility exception is carried. One
fresh qualification at the protected reviewed head is required before the
aggregate gate.

## Complete checkpoint gate

Not yet consumed. The rejected `0cd9a9f8...` and `4473123e...` runs and the
permission-invalid publication attempt are terminal and inadmissible. The fresh
`f7fc37e3...` private tree is semantically admitted for that exact head and its
pre-protection descendants. The new admission-protection change is itself a
protected route input, so the current descendant rejects reuse and requires a
fresh private qualification. The aggregate checkpoint matrix remains a
separate one-shot gate after that replacement lock is frozen.

## Hosted closure

Pending exact-head PR checks and merge. Production supervision, simultaneous
model residency, sustained mixed-owner capacity/SLOs, enterprise networking,
and deployment remain Phase 10 or explicit IT/security handoffs.
