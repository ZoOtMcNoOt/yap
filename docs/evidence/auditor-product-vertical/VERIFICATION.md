# Auditor Product Vertical Verification

## Status

Exact executable candidate
`87924d5f975ff8ceef13b32f2a9e0a0c86f046f5` over merged Coordinator
product baseline `3fd5eaed2e3d47a6e765b5467345ba26a424af23` implements and privately
qualifies the Auditor product vertical. Its owner-private ARM64 gate returned
`auditor-authenticated-product-server-boundary-qualified` with public-safe
evidence SHA-256
`b5a31c215d21ab713c51ae7d9704d8984f67c01381e5ed861ce3e7d18f994d5c`.
Exact hosted source head `6bb72953d227927b4255702fdb394b8e8a3b1ca0`
passed all six CI jobs reported for PR #183. The repository's linear-history
rule rebase-merged the tree-identical successor with main tip
`13d9e3ef7f74059f2dece6ce9ee4b62d0139b828` on 2026-08-14. Qualification
remains attributed to exact executable `87924d5f...`; it is not relabeled as a
docs or merge head.

The frozen product acceptance plan is
`server/auditor-product-acceptance.json`, SHA-256
`0c07a80df0e4ed167b97115d3d5050a21ef81324abfae43df509ed0ee98a1a46`.
The independently qualified Auditor semantic plan and corpus remain SHA-256
`0f8d01369da66b7d5d177e718ce736e950d690c08fe1d97e8c67dfdf28de1ee2`
and
`30860909f44232f3227f63e77491efc0e55b6ea91048690f4dc23e55b57dca5a`.

Exact predecessor `50417bfc4225511ee74d6002b5d3c65606f94bd1` failed closed before
publication because its qualification-only cancellation adapter exposed
`report(...)` while the production Auditor service requires `review(...)`.
It emitted no qualification receipt and established no admissible Auditor
product success evidence. The attempt is terminal and is not reused. Separate
read-back confirmed the rapid and complex containers and broker socket were
absent afterward; no broader teardown claim is attributed to that failed run.

## Executable product boundary

- `POST /v1/auditor-reports` accepts one authenticated, bounded review focus.
  Owner-scoped `GET` and `DELETE /v1/auditor-reports/{requestId}` expose status
  and cancellation only to the authenticated owner.
- The server reads current permission-safe evidence. The model may select only
  bounded evidence-index pairs. Server-owned code derives every potential-
  contradiction finding and both exact citations. Successful reports are
  noncanonical and review-required and cannot publish, activate, schedule, or
  mutate source or knowledge state.
- Native Rust owns the bearer exchange, strict request/report/finding/citation
  validation, one connection lease, cancellation, terminal retention, and quit
  containment. Credentials and internal request/evidence hashes never enter
  the renderer.
- The Knowledge workspace provides one explicit Auditor review composer and
  renders only server-derived findings and citations. Remote unavailability
  does not disable local recording, transcription, playback, History, or other
  Knowledge controls.

## Private qualification read-back

On 2026-08-14 the checked gate ran at the clean exact head above and observed:

- 8 cases across 8 authenticated owners and 10 product requests;
- 10/10 exact terminal projections: 4 complete, 5 evidence-unavailable, 0
  failed, and 1 cancelled;
- 4/4 exact server-derived, noncanonical, review-required reports with
  server-owned two-citation findings;
- authenticated `POST`/`GET`/`DELETE`, strict owner isolation, and hidden-only/
  absent public equivalence;
- fail-closed HTTP cancellation after model admission with no returned report;
- exact Auditor result and knowledge-tool audits through two owned PostgreSQL
  restart/read-backs, with no proposal, activation, source, or knowledge write;
- the unchanged full complex profile and a live eight-owner/ninth-queued broker
  probe without model launch, swap, fallback, or profile reduction; and
- exact product workers, broker, provider, container, listener, process,
  network, volume, and database teardown.

The normal-request p95 remained within the frozen 85,000 ms bound. The checked
complex profile remained Gemma 4 NVFP4 with batch invariance enabled, prefix
caching disabled, request seed `0`, 7,680 input tokens, 512 output tokens, and
eight active sequences. The live probe held eight distinct-owner leases while
the ninth remained queued, then contained every ticket without a provider or
broker identity change. This is selected-route admission evidence, not eight
simultaneous inferences, sustained throughput, or a production latency SLO.

Independent harness read-back found gate exit `0` and harness exit `0`; no
owned broker socket, rapid/complex provider container, private network,
qualification container/network/volume, PostgreSQL tree, or route listener
remained. The private evidence directory and files remain owner-only outside
Git.

## Public verification

At exact successor `87924d5f...`, the complete focused Auditor product/core
matrix passed **73 tests = 71 passed + 2 declared real-PostgreSQL skips**.
The governed fixed set passed **173 tests = 169 passed + 4 declared skips**,
whole-server Ruff and the changed-file format check passed, and `git diff
--check` was clean.

The parent implementation matrix, whose only successor delta is the corrected
qualification adapter and its test, also passed:

- desktop Vitest: **64 files / 395 tests**;
- production TypeScript/Vite build and **42/42** Playwright checks;
- Rust formatting, strict all-target/all-feature Clippy, and the complete
  locked native/orchestrator test matrices; and
- native WDIO: four spec files, **15 passed + 2 declared optional hardware
  skips**.

The full local portable-server aggregate was not admitted as green: its two
attempts reached an unrelated Windows/WSL proxy-behavior test that exceeded the
30-second Windows Bash wrapper bound. That exact isolated test and its complete
12-test module passed immediately afterward.

## Hosted review and merge

At exact source head `6bb72953...`, PR #183 reported six hosted jobs and all six
completed successfully: `frontend`, `rust`, `Native WDIO smoke (required, no
hardware)`, `server`, `Server orchestrator (Linux lifecycle)`, and `mock-oidc`.
GitHub reported the PR
mergeable and clean. A separate default-setup CodeQL suite was not instantiated
for this PR, so this record does not manufacture a 12-job claim. The linear-
history rebase produced main tip `13d9e3ef...`; independent tree comparison
confirmed it is byte-for-byte identical to hosted source head `6bb72953...`.

## Claim limits and privacy

No private tenant/subject identity, run/request ID, focus, evidence, report,
finding, citation, model output, database row, DSN, host path, individual
timing, or private receipt is committed. Git records only exact revisions,
public-safe hashes, aggregate counts, booleans, and bounded outcomes.

This result qualifies the authenticated Auditor server/database/broker
boundary and the tree-identical product vertical is merged. It does not qualify
a private native/renderer round trip, live enterprise identity-provider
exchange, production deployment, scheduled autonomous review, simultaneous
Qwen/Gemma residency, sustained capacity, or a p50/p95/p99 SLO. Gemma remains
the qualified local complex route. Muse Spark 1.2 is recorded only as a future hosted-provider
watch item because deployable open weights are not available for this
local/offline boundary.
