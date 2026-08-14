# Student Product Vertical Verification

## Status

Exact executable candidate
`778a7545d711bd6e3cd34e900d7d85013bdb1404` privately qualified the
authenticated Student product server boundary. Its owner-private ARM64 gate
returned `student-authenticated-product-server-boundary-qualified` with
public-safe evidence SHA-256
`c46cf7df12e1038c613a53547a729866d19f10ab69d88d7f2aa75791b2d7b005`.
The frozen product acceptance plan SHA-256 is
`71de1b4f58bf896a1e16a61525311c0669cb1606176b0d45fa75f7e7a47f69ca`.
The semantic acceptance plan SHA-256 is
`99471659c91618028a3c2e5d58739b8f2635aee1a7d3800c445ac7c855aa6e67`.
The independently compiled synthetic corpus is
`student-source-subjects-v2`, SHA-256
`da9af6614908f8677fece1166ee0fcc12ac94f52c2f2953c26c51a2b2380505c`,
and the semantic evidence SHA-256 is
`5399a1ae51eab360f635315e89cf3e2f45df65defd7cc8940551fc1e8b6825e9`.

This is a privately qualified, merged product vertical. It qualifies the
authenticated HTTP/server, current-generation authority, rapid-route admission,
result-audit, cancellation, and database boundary. It does not qualify a live
native-to-renderer round trip or a live enterprise identity-provider exchange.
Those client contracts are exact-head public-test evidence. Hosted head
`53ce570bf2aedafa1d2d2aebdbcc19349e904ce4` passed all 12 required checks,
and PR #178 merged the vertical as
`6546970ba3613fe55458b54c334a687cb7ff823e` on 2026-08-14.

Two protected predecessors are terminal and inadmissible. Exact
`b8671d4601548d53af6c2a1d7c2daa1a01222000` reached the active polling path but
incorrectly required a terminal evidence hash while the job was still running.
Exact `79160de0b9d53741f72fcf1dc7b75ccd07083d35` completed the semantic workload
but compared teardown against obsolete database key names. Both attempts failed
closed and emitted no qualification receipt. Neither is reused.

## Executable product boundary

- `POST /v1/student-questions` accepts one authenticated source-bound request;
  `GET` and `DELETE /v1/student-questions/{requestId}` are owner-scoped.
- The server generates the product request identity, reuses the qualified
  Student core, and returns only typed status plus bounded server-derived
  questions and complete citation/support spans on success.
- Native Rust owns bearer transport, exact response/citation/span validation,
  one request lease, cancellation, connector fencing, and quit cleanup. Bearer
  material is not exposed to React.
- The renderer offers the learning-question action only beside a permission-
  safe Librarian evidence item for a meeting concept. It passes the exact active
  generation identity supplied by the server and renders the returned source-
  cited question without creating citation identity.
- Remote Student unavailability does not disable local recording,
  transcription, History, playback, or copy controls.
- Student creates no proposal, source, generation, activation, or other
  knowledge mutation.

## Exact private qualification

The fresh owner-private gate proved:

- 8 cases across 8 authenticated owners and 11 product requests;
- 11/11 exact terminal results: 8 complete, 2 unavailable, 1 cancelled, and 0
  failed;
- 11 unique product request IDs and exact product-to-internal request binding;
- strict health-capability and bearer enforcement on `POST`, `GET`, and
  `DELETE`, plus exact owner isolation;
- server-derived questions, exactly one source-cited question per successful
  result, and hidden-only/absent indistinguishability;
- exact current-generation, permission, authorization, evidence, result-audit,
  and governed knowledge-tool identities;
- two owned PostgreSQL restart/read-backs, an unchanged active generation, and
  zero proposal writes;
- the unchanged full Qwen rapid profile at 512 output tokens, four active
  sequences, and 8,192 maximum batched tokens;
- a live rapid-route probe with four distinct owners admitted and the fifth
  queued, contained, and acknowledged while provider and broker identities
  remained unchanged;
- no request-time model launch, swap, fallback, or profile reduction; and
- exact worker, broker, provider, container, listener, network, process, and
  database teardown.

The normal-request p95 remained within the frozen 31,000 ms qualification
bound. This bounded synthetic result is not a sustained-capacity, p95/p99 SLO,
fairness, production-load, or deployment claim.

## Public verification

At exact executable `778a7545...`:

- the focused Student matrix passed **77 total = 76 passed + 1 expected skip**;
- the portable server suite passed **1,569 total = 1,522 passed + 47 declared
  skips**;
- the governed fixed set passed **173 total = 169 passed + 4 declared skips**;
- whole-server Ruff passed across `src` and `tests`, changed-file Ruff format
  checks passed, and `git diff --check` was clean;
- desktop Vitest passed **60 files / 379 tests** and the production TypeScript/
  Vite build completed;
- desktop Rust passed formatting, strict all-target/all-feature Clippy, and
  **1,243 unit tests = 1,232 passed + 11 expected ignored**; and
- the owner-private gate reran from a clean immutable checkout and returned the
  current evidence hash above with exact provider, broker, and database
  teardown.

The whole-tree Ruff format inventory still contains inherited formatting drift
outside this product slice; this record does not relabel that repository-wide
check as green.

Hosted head `53ce570bf2aedafa1d2d2aebdbcc19349e904ce4` passed all 12 required
checks before PR #178 merged the vertical as
`6546970ba3613fe55458b54c334a687cb7ff823e`.

## Claim limits and privacy

The create-once private receipt is a mode-`0600`, single-link file outside Git.
Tenant/subject identities, run and request IDs, source/evidence/question bytes,
database rows, DSN, host paths, and individual timings remain owner-private.
Git contains only checked heads, plan/evidence hashes, aggregate counts,
booleans, and the bounded conclusions above.

This merged vertical does not establish simultaneous Qwen/Gemma residency, sustained
capacity, enterprise identity exchange, production operations, deployment
approval, or a Muse Spark model transition. Muse Spark 1.2 remains a separate
evaluation because no approved deployable artifact is currently bound to this
repository and an external hosted route would require explicit organization
cloud/data-transfer approval and an organization-owned credential.
