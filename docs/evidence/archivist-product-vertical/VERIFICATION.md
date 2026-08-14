# Archivist Product Vertical Verification

## Status

Exact executable candidate
`e78746b583bf5f9aa3179ec1c166890a4c4cf11e` is privately qualified as an
unmerged Archivist product candidate. Its owner-private ARM64 gate returned
`archivist-authenticated-product-vertical-qualified` with public-safe evidence
SHA-256 `3de55ce4c091d70114491a002c32b0262042869f54b84c22404aaed115dab31e`.
The frozen acceptance plan SHA-256 is
`ebac7e6ecf35d73ab9d6f6c554e3f6dfb0aad00858fe89d1ac5d614a65f64b0a`.

Predecessor `163a409c0e186e3d239826088d5fa63f806568c8` first qualified the
vertical with public-safe evidence SHA-256
`d25ccd61d6c2ba732440f9fd84c03f8cddd21b7608af37f2674f30c2b6309005`.
The hosted release contract then found that its protected E2E population
inventory did not enumerate the new Archivist spec. Successor `e78746b5...`
adds only that explicit test floor and was freshly qualified; the predecessor
receipt is retained as exact-head history and is not used for this successor.

This record qualifies the authenticated HTTP/server, durable recording-source,
Server-IO admission, reviewed-capture, and deterministic staging boundary. It
does not qualify a private native-to-renderer round trip or a live enterprise
identity-provider exchange. Those client contracts are exact-head public-test
evidence and still require hosted review on the final candidate.

## Executable product boundary

- `POST /v1/archivist-ingestions` accepts only `schemaVersion`, `jobId`, and an
  expected durable-result SHA-256 under an authenticated principal.
- `GET` and `DELETE /v1/archivist-ingestions/{requestId}` are owner-scoped and
  expose typed status/cancellation without returning raw reviewed-source bytes.
- The server derives the reviewed capture from the completed durable recording
  job, submits exactly the bound Archivist Server-IO work, compiles the source,
  and stages a non-embedding generation without activating knowledge.
- Native Rust owns bearer transport, job/result identity resolution, one
  ingestion lease, cancellation, restart recovery, and quit containment.
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
Archivist scenario. The owner-private gate was rerun from a clean immutable
checkout and returned the current evidence hash above. Hosted checks still must
pass the final documentation successor before merge.

## Claim limits and privacy

The create-once private receipt is a mode-`0600`, single-link file outside Git.
Tenant/subject identities, run and request IDs, source/review bytes, database
rows, DSN, host paths, and individual timings remain owner-private. Git contains
only the checked head, plan/evidence hashes, aggregate counts, booleans, and the
bounded conclusions above.

Archivist stages reviewed knowledge; it does not embed or activate it. This
candidate does not establish simultaneous Qwen/Gemma residency, sustained
capacity, an enterprise identity exchange, production operations, or deployment
approval. Hosted exact-head checks, review, and merge remain required before the
product surface is described as merged.
