# Archivist Product Vertical Verification

## Status

Exact executable candidate
`a2e9b55157799749ffc4eca32a92feabe63fba8e` privately qualified the Archivist
product vertical. Its owner-private ARM64 gate returned
`archivist-authenticated-product-vertical-qualified` with public-safe evidence
SHA-256 `9ec9e37353c2c89198f374efe0f474b8284e077455b4168eb345d6a1e7a76a4f`.
The frozen acceptance plan SHA-256 is
`ebac7e6ecf35d73ab9d6f6c554e3f6dfb0aad00858fe89d1ac5d614a65f64b0a`.

Predecessor `163a409c0e186e3d239826088d5fa63f806568c8` first qualified the
vertical with public-safe evidence SHA-256
`d25ccd61d6c2ba732440f9fd84c03f8cddd21b7608af37f2674f30c2b6309005`.
The hosted release contract then found that its protected E2E population
inventory did not enumerate the new Archivist spec. Successor `e78746b5...`
added that explicit test floor and was freshly qualified with evidence
`3de55ce4...`. Final review then found that native cancellation and quit cleanup
could stop after a `cancellation-requested` response and retain the owned
connection lease indefinitely. `4ac421e2...` added bounded terminal
reconciliation and exact request/source checks; `a2e9b551...` also refreshed
the complete native capability assertion exposed by the hosted WDIO smoke.
Those protected changes required the current fresh qualification. Earlier
receipts remain exact-head history and are not used for this successor.

This record qualifies the authenticated HTTP/server, durable recording-source,
Server-IO admission, reviewed-capture, and deterministic staging boundary. It
does not qualify a private native-to-renderer round trip or a live enterprise
identity-provider exchange. Those client contracts are exact-head public-test
evidence. Hosted head `69215c43437c75d7ca2498154a80c4ae5bb749ed`
passed all 12 required checks, and PR #177 merged the vertical as
`e397af8b29737fa21197c7058c659eab2ad0a00b` on 2026-08-14.

## Executable product boundary

- `POST /v1/archivist-ingestions` accepts only `schemaVersion`, `jobId`, and an
  expected durable-result SHA-256 under an authenticated principal.
- `GET` and `DELETE /v1/archivist-ingestions/{requestId}` are owner-scoped and
  expose typed status/cancellation without returning raw reviewed-source bytes.
- The server derives the reviewed capture from the completed durable recording
  job, submits exactly the bound Archivist Server-IO work, compiles the source,
  and stages a non-embedding generation without activating knowledge.
- Native Rust owns bearer transport, job/result identity resolution, one
  ingestion lease, restart recovery, and bounded cancellation/quit
  reconciliation through an exact terminal request/source identity before it
  releases the owned connection lease.
- The renderer sends only the local recording identity to native code and shows
  one explicit **Stage for knowledge** action for a completed server-batch
  transcript. Remote failure leaves local playback, transcript, and controls
  available.

## Exact private qualification

The fresh owner-private gate proved:

- 9 source cases across 8 authenticated owners and 10 product requests;
- one synchronized wave of 8 authenticated client calls;
- 10/10 exact terminal results: 9 staged and 1 cancelled;
- 9 exact reviewed captures, 8 source admissions, and 8 staged generations;
- exact replay reused the existing staged result without a second source
  admission or generation;
- the ninth source remained queued behind an independently held Server-IO slot
  and cancelled without staging;
- strict bearer enforcement, owner-scoped status/cancellation, foreign-source
  denial, missing-result `404`, and source-drift `409` behavior;
- exact server-derived review/capture/source/generation identities and two owned
  PostgreSQL restart/read-backs;
- one source-bound Archivist lease per product request and no product model-route
  lease request;
- live Server-IO capacity one with an overflow owner queued, contained, and the
  broker identity unchanged;
- recording-job restart read-back, zero active generations, and no knowledge
  activation; and
- exact worker, broker socket, provider, container, listener, network, process,
  and database teardown.

The normal-request p95 remained within the frozen 60,000 ms qualification
bound. This bounded synthetic result is not a sustained-capacity, p95/p99 SLO,
fairness, production-load, or deployment claim.

## Public verification

At production implementation head `163a409c...`:

- the portable server suite passed **1,548 total = 1,501 passed + 47 declared
  skips**;
- the governed fixed set passed **173 total = 169 passed + 4 declared skips**;
- server Ruff passed across `src` and `tests`;
- desktop Vitest passed **59 files / 374 tests**;
- desktop Playwright passed **42/42** Chromium scenarios, including the
  renderer-to-native Archivist boundary;
- TypeScript and the production Vite build passed;
- desktop Rust passed formatting, strict all-target/all-feature Clippy, and
  **1,244 unit tests = 1,233 passed + 11 expected ignored**, plus all integration
  groups; and
- server-orchestrator Rust passed formatting, strict Clippy, and all tests.

At protected successor `e78746b5...`, the corrected E2E population contract
passed 3/3 and the supported Chromium suite again passed 42/42, including the
Archivist scenario.

At exact executable successor `a2e9b551...`:

- the portable server suite passed **1,548 total = 1,501 passed + 47 declared
  skips**, the governed fixed set passed **173 = 169 + 4**, and whole-server
  Ruff was clean;
- desktop Vitest passed **59 files / 374 tests**, Playwright passed **42/42**
  including the Archivist scenario, and the production TypeScript/Vite build
  completed;
- focused native Archivist ownership tests passed 5/5, including an
  authenticated cancellation-requested-to-cancelled exchange, concurrent
  terminal reconciliation, mismatched identity rejection, and terminal lease
  reclamation;
- desktop Rust passed formatting, strict all-target/all-feature Clippy, and
  **1,247 unit tests = 1,236 passed + 11 expected ignored**, plus all integration
  groups;
- the required native WDIO matrix passed **3/3 spec files and 15/15 tests**
  across smoke, overlay, and tray with an empty isolated recording root;
- the Archivist product-gate unit suite passed 8/8; and
- the owner-private gate reran from a clean immutable checkout and returned the
  current evidence hash above with exact provider/broker/database teardown.

Hosted head `69215c43437c75d7ca2498154a80c4ae5bb749ed` passed all 12 required
checks before PR #177 merged the vertical as
`e397af8b29737fa21197c7058c659eab2ad0a00b`.

## Claim limits and privacy

The create-once private receipt is a mode-`0600`, single-link file outside Git.
Tenant/subject identities, run and request IDs, source/review bytes, database
rows, DSN, host paths, and individual timings remain owner-private. Git contains
only the checked head, plan/evidence hashes, aggregate counts, booleans, and the
bounded conclusions above.

Archivist stages reviewed knowledge; it does not embed or activate it. This
merged vertical does not establish simultaneous Qwen/Gemma residency, sustained
capacity, an enterprise identity exchange, production operations, or deployment
approval. Product deployment and promotion remain separate gates.
