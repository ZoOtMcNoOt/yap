# Curator Product Vertical Verification

## Status

Exact executable candidate
`2dcecef406b81b5cf8a9d72e5547f0cdc8b1de10` over merged Student baseline
`6546970ba3613fe55458b54c334a687cb7ff823e` implements and privately qualifies
the Curator product vertical. Its owner-private ARM64 gate returned
`curator-authenticated-product-server-boundary-qualified` with public-safe
evidence SHA-256
`bc24ee6baab9d0eb07f0fd9bf3e3c8c2779ddd369888a1e8b00190ff5b671b82`.
The candidate remains unmerged and still requires unchanged-head hosted review.

The frozen product acceptance plan is
`server/curator-product-acceptance.json`, SHA-256
`d1337b478926ac94e058bb6604063c014f0e4235b85624e27035e54df44ff2f6`.
The product gate reuses the independently frozen Curator semantic acceptance
and corpus, whose current SHA-256 values are
`74f53d7aa45bbc8ba3ee0339235edac792b86323719d3c42e11b26793a089696`
and
`28bfadfbabe50c89dc8cac53a440d0ce7ba30d428682b98154cef63a59dfde1b`.

## Executable product boundary

- `POST /v1/curator-proposals` accepts one authenticated explicit proposal or
  reviewed Student answer. `GET` and `DELETE
  /v1/curator-proposals/{requestId}` are owner-scoped.
- The server generates the product request identity, rebuilds the exact
  server-owned Curator request/evidence binding, and reuses the qualified
  Curator service. A successful result is only a noncanonical proposal that
  still requires review; it does not compile, stage, activate, or mutate source
  truth or active knowledge.
- Native Rust owns the bearer exchange, strict lifecycle/result validation,
  cancellation, connection-generation fencing, bounded ownership, and quit
  cleanup. Credentials never enter the renderer.
- The renderer exposes one explicit reviewed-proposal action only after a
  Student question completes, states that the result is noncanonical and still
  requires review, and does not render internal request, evidence, or proposal
  hashes.
- Remote Curator unavailability does not disable local recording,
  transcription, History, playback, copy, Librarian, or Student controls.

## Private qualification read-back

On 2026-08-14 the checked gate ran at the clean exact head above and observed:

- 8 cases across 8 authenticated owners and 10 product requests;
- 10/10 exact terminal projections: 4 proposed, 4 rejected, 1 failed, and 1
  cancelled;
- exact authenticated `POST`/`GET`/`DELETE`, owner isolation, product-to-core
  request/evidence binding, and replay/conflict behavior;
- server-derived noncanonical proposal identity with active source truth
  unchanged;
- exact Curator result/proposal/tool audit rows and two owned PostgreSQL
  restart/read-backs;
- the unchanged full complex profile and a live eight-owner/ninth-queued broker
  probe without model launch, swap, fallback, or profile reduction; and
- exact product workers, broker, provider, container, listener, process,
  network, volume, and database teardown.

The normal-request p95 remained within the frozen 60,000 ms bound. The checked
full complex profile remained Gemma 4 NVFP4 with batch invariance enabled,
prefix caching disabled, request seed 0, 7,680 input tokens, 512 output tokens,
and eight active sequences. The live capacity probe held eight distinct-owner
complex leases while the ninth remained queued, then contained all tickets
without a provider or broker identity change. This is selected-route
qualification evidence, not simultaneous Qwen/Gemma residency or a production
latency SLO.

Independent harness read-back found gate exit 0 and harness exit 0; no owned
broker socket, provider container, private network, qualification container,
qualification network, qualification volume, or rapid/complex listener
remained. The private evidence directory and files remain owner-only outside
Git.

## Public verification

Against the current implementation successor:

- the complete portable server suite passed **1,584 total = 1,537 passed + 47
  declared skips**;
- the governed fixed set passed **173 total = 169 passed + 4 declared skips**;
- focused server/API/runtime/Curator checks passed **78/78**, including the
  Curator product gate contract at **7/7**;
- whole-server Ruff passed; changed Python files pass Ruff formatting;
- desktop Vitest passed **61 files / 383 tests**, and the production
  TypeScript/Vite build completed;
- desktop Rust passed formatting, strict all-target/all-feature Clippy, and
  **1,261 unit tests = 1,250 passed + 11 expected ignored**, plus all integration
  groups; and
- `git diff --check` was clean at the public verification checkpoint.

Repository-wide Ruff formatting still contains inherited drift outside this
slice; this record does not relabel that whole-tree check as green.

## Claim limits and privacy

No private tenant/subject identity, run/request ID, source/evidence/model bytes,
database row, DSN, host path, individual timing, or private evidence artifact is
committed. Git records only the exact checked head, public-safe evidence and
acceptance hashes, aggregate counts, booleans, and bounded outcome.

This exact-head result qualifies the authenticated Curator server boundary; it
does not qualify a native/renderer round trip, live enterprise identity-provider
exchange, hosted review, merge, production deployment, simultaneous Qwen/Gemma
residency, sustained capacity, or a p95/p99 SLO. Gemma remains the qualified
private complex route. Muse Spark is a separate post-merge evaluation and cannot
replace it until an official deployable version, license/terms, organization
identity and data-transfer boundary, and exact tool-calling/runtime contract are
approved and qualified.
