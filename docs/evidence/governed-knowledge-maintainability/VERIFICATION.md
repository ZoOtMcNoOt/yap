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
protected route inputs. Executable repair
`4cb9123ec21fada1f0fca865909d7bfd7ada34e7` subsequently froze the exact
bounded lexical result control exposed by the first protected-head run, with
fixture SHA-256
`723032aa381e30a6060d6636667410a075441ed5e1c5ad12628f0797105c3a2f`.
Reviewed executable head
`518f78482b4f62f7e2397219e96ed27cd1d3e2fb` then bounded only final-answer
structural decoding to two attempts, without retrying or replaying tool calls,
transport failures, or well-formed semantic failures. Acceptance is schema 3;
its SHA-256 is
`3183378dbfab756dda8b25564ef1cb04a2d0bb8692f9ba00b9a2d95d72ee06a8`.
Successful candidate and fixture-child evidence are schema 2. The resulting
qualification exposed one still-implicit cited-proposal tool contract. Reviewed
executable head `4cb73aee2cb0da730337cd7f91c7d16cf6ab7e76` now freezes that one
synthetic rapid-automation request as a complete production-valid JSON argument
object without adding tool retry or changing any threshold, route cap, model, or
runtime. Its fixture SHA-256 is
`ac033eb4d0f877b7d87bc17b9027b0f5c2ef4a0a7f7beb24d21959a504c8a347`;
the resulting acceptance SHA-256 is
`461a7b6f6fcc41ca42adcc2a9add885ae61598a0c8197e38609304bf756bc8a3`.
Runtime read-back then proved that one shared vLLM image was not valid for both
frozen routes. Exact executable head
`96897d2f77f16457a9da2b87af8a9bf4c9ad2b99` binds Qwen rapid automation to
the pinned NVIDIA vLLM 26.07 ARM64 base plus XGrammar 0.2.1 overlay and strict
tool guidance, while Gemma complex orchestration remains on exact upstream
NVIDIA vLLM 26.06 ARM64. It changes no model, route, route cap, output bound,
quality/latency threshold, or tool-retry policy. Candidate-lock SHA-256 is
`3e9218c8245863c5f1bda8166a629361b51ed23cec259d7c69f11b1dee83d013`;
acceptance SHA-256 is
`19e45aec7d4cd0fafe98da0c8ece4ff023eea0fdec6844f6d7c0801fb07c6f5d`;
fixture SHA-256 remains
`ac033eb4d0f877b7d87bc17b9027b0f5c2ef4a0a7f7beb24d21959a504c8a347`.
The candidate has the following focused, non-promotional verification. Commands are
shown from their working directory; the Windows runs used the locked project
environment and Python 3.12.

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
  separately passed its focused route and admission-contract sets plus Ruff, but actual
  private admission and the aggregate gate remain blocked until replacement
  qualification. None of these focused results is a complete checkpoint-gate
  claim.
- At exact head `4cb73aee...`, the same portable command loaded the exact
  then-current 25-module/142-test membership: 138 passed, three declared
  platform/capability skips, and only the strict stale-route-lock contract
  failed. That failure is required before replacement qualification because
  the reviewed retry, cited-proposal, evidence-schema, and protected gate inputs
  intentionally differ from the historical public lock.
- At exact head `96897d2f...`, the same portable command loaded the exact
  25-module/151-test membership: 147 passed, three declared
  platform/capability skips, and only the strict stale-route-lock contract
  errored. The historical schema-2 route lock cannot admit the current schema-3
  candidate/runtime contract, so that error is the required prequalification
  state. Server-wide Ruff passed.
- From `server`, with `PYTHONPATH=src`, the current acceptance, qualification,
  vLLM-runtime, and private-route-admission contract modules ran 36 tests:
  35 passed and one Windows POSIX-permission test was declared inapplicable.
  They bind the complete per-route runtime mapping, exact platform/image/runtime
  identities, Qwen Dockerfile/build/notice/dependency inputs, enabled strict
  guidance, and stale-lock rejection.
- From `server`, with `PYTHONPATH=src`, the focused agent acceptance, fixture,
  qualification, scoring, route-artifact, pressure, vLLM metric/runtime,
  final-response-retry, reasoning-route, governed-answer, and reasoning-client
  modules ran 68 tests: 67 passed and one Windows POSIX-permission test was
  declared inapplicable.
  This verifies
  that denied-resource wording is not confused with an emitted forbidden
  tool, the route maximum output bounds remain unchanged, the one concise
  stale-generation case has a stricter frozen per-case bound, empty-result
  prompts are explicit and every empty visible result is exact-answer scored,
  cited retrieval requires its complete frozen argument map, including the
  one-result bound, with no extra generation or result controls, multi-step
  calls allow only their frozen
  controls plus the required dynamic proposal content/citations, every visible
  citation span covers its complete supplied text, proposal terminology must
  be present in governed `proposed_content` rather than only the final answer,
  and only an undecodable final answer receives one bounded retry. The retry
  retains completed tool evidence, never re-executes a tool, and records the
  exact per-case request count and full elapsed time. The cited-summary proposal
  additionally binds one exact production-valid argument and citation object;
  omission, mutation, or an extra control withholds context and fails scoring.
  The strict
  evidence/lifecycle contracts remain intact.
- From `server`, with `PYTHONPATH=src`,
  `uv run --locked python -m unittest tests.knowledge.test_okf_compiler tests.knowledge.test_cancellable_database_operation tests.knowledge.test_governed_knowledge_mcp tests.knowledge.test_governed_rag_agent tests.evaluation.test_agent_model_fixture_runner tests.evaluation.test_agent_model_scoring`
  ran 45 tests: 44 passed and one Windows directory-link capability test
  skipped. This covers canonical POSIX path/generation/profile/resource identity,
  durable-write curated authorization, strict nested MCP inputs, exact
  database-worker cancellation acknowledgement, and shared evaluator/product
  tool bounds.
- From the repository root,
  `pwsh -NoProfile -NonInteractive -ExecutionPolicy Bypass -File ./verification/list-maintainability-threshold-surfaces.ps1 -MinimumLines 250 -Json`
  enumerated 477 tracked regular surfaces: 251 at or above 350 lines and 226
  from 250 through 349. A read-back comparison of the 350-line output against
  `THRESHOLD-DISPOSITION.md` found all 251 exact paths and zero differences.
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

Five fresh private route qualifications are retained as rejected evidence and
cannot be used for admission. At exact head
`0cd9a9f88123f1f4fd1caaf42e03dce02658bfd6`, the owned lifecycles and exact
teardown completed before the decision returned `deterministic-no-model` with
public-safe evidence SHA-256
`0beaa4d04ccef663e89b215b97b14edbb7fd786c2c354179d896cb0ca65794b5`.
At exact head `4473123e24c59eb1d929e8612fb9b38817c55a14`, both owned
lifecycles and exact teardown again completed before the decision returned
`deterministic-no-model` with public-safe evidence SHA-256
`1a5f8069d193b1ba53e188f312d564167068b19e6f35580986404abfdd540a83`.

At the first protected-admission head
`cb5ae95bd1dcd0a7c1c3d12d6471ba511ecbf152`, both isolated GPU lifecycles
and exact teardown completed before the decision returned
`deterministic-no-model` with public-safe evidence SHA-256
`867289335c3383f592eb8e62d6d916a52e455e8854e5b967b5539d1d19cbf4dc`.
The complex-orchestration candidate and every frozen rapid latency bound
passed, but the rapid candidate's otherwise correct lexical call supplied the
valid product-owned `maximum_results: 1` control that the frozen expected
argument map had omitted. Exact context withholding therefore denied the
cited evidence and correctly prevented qualification. No private measurement
or model output is published by that qualitative diagnosis. The immutable run
is terminal and inadmissible.

At exact head `7f0f060e89951fd528dd229f96785cdbbe8617ea`, both owned
lifecycles and exact teardown completed before the decision again returned
`deterministic-no-model`, with public-safe evidence SHA-256
`409896c50de57efce0719c04a0bcda565be79d5b2462b0495143fe8164987c0d`.
The complex candidate remained eligible and the frozen rapid latency route
bounds passed, but the rapid candidate produced one structurally invalid final
response for the cited-summary-proposal case. The overall qualification was
therefore rejected. This immutable run is terminal and inadmissible; no raw
model output, measurement, log, or private artifact location is published.

At exact head `518f78482b4f62f7e2397219e96ed27cd1d3e2fb`, both owned
lifecycles and exact teardown completed before the decision again returned
`deterministic-no-model`, with public-safe evidence SHA-256
`92fc6573586c2b645dc34de6e0266b47cced8ccfe7cc5c42c06447c6e143a457`.
The complex candidate remained eligible. The rapid candidate produced one
structurally invalid cited-summary-proposal tool response before dispatch; its
warm and concurrency route bounds passed while the complete fixture bound did
not. The overall qualification was therefore rejected. This immutable run is
terminal and inadmissible; no raw model output, measurement, log, or private
artifact location is published.

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
only the required dynamic proposal content and citations. The protected-head
follow-up then froze `maximum_results: 1` in both the lexical instruction and
its complete expected argument map; omission, alteration, or any extra
generation control still fails closed. The current repair adds one second
attempt only when the final response cannot be structurally decoded, matching
the product's bound of two without claiming identical retry semantics. Tool
selection, arguments, transport failures, and structurally valid semantic
failures remain single-attempt evidence. No raw model output, private
measurement, log, or private artifact location is published here.
The cited-proposal repair leaves that no-tool-retry rule intact and instead makes the
one bounded cited-summary proposal request the exact complete JSON call already
required by its visible evidence and product-owned tool schema. The remaining
terminology and complex proposal cases stay open-ended.
The current runtime repair then assigns each route its compatible exact vLLM
identity: pinned 26.07 plus XGrammar 0.2.1 for Qwen and exact upstream 26.06 for
Gemma. Strict tool guidance is enabled and cannot be overridden off. The
derived Qwen image is bound by its checked Dockerfile, build script, notice,
wheel/source identities, platform, and exact observed image; this is not a
claim that independent builds have the same Docker image ID.

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
fresh qualification at reviewed executable head `96897d2f...` is required
before the aggregate gate.

## Complete checkpoint gate

Not yet consumed. The rejected `0cd9a9f8...`, `4473123e...`, `cb5ae95b...`,
`7f0f060e...`, and `518f7848...` runs and the permission-invalid publication attempt are
terminal and inadmissible. The fresh
`f7fc37e3...` private tree is semantically admitted for that exact head and its
pre-protection descendants. The new admission-protection, lexical/proposal-fixture,
bounded-final-decoding, route-specific runtime, gate-count, and evidence-schema
changes are protected route inputs,
so the current descendant rejects reuse and requires a fresh private
qualification. The aggregate checkpoint matrix remains a separate one-shot
gate after that replacement lock is frozen.

## Hosted closure

Pending exact-head PR checks and merge. Production supervision, simultaneous
model residency, sustained mixed-owner capacity/SLOs, enterprise networking,
and deployment remain Phase 10 or explicit IT/security handoffs.
