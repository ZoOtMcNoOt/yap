# Coordinator Product Vertical Verification

## Status

Exact executable candidate
`05400fb33a6a2ed63f49db622b8789a330def3e7` over merged Analyst product
baseline `c95fcf1a043f919661b007f014a8dc6729aa02f2` implements and privately
qualifies the Coordinator product vertical. Its owner-private ARM64 gate
returned `coordinator-authenticated-product-server-boundary-qualified` with
public-safe evidence SHA-256
`394112ade3727f4e40fbec0b5083e23d7889a0318553026227f0c4a0e6c4bd89`.
The candidate remains unmerged and requires unchanged-head hosted review.

The frozen product acceptance plan is
`server/coordinator-product-acceptance.json`, SHA-256
`5e52d54547fed0ae7ab6fcaa5d2ea79ce4f1c71bf6f4c5143549db6399b99e91`.
The independently qualified Coordinator semantic plan and corpus remain
SHA-256
`34f7152da6eeeb7c21018bcfb4581cfea89d794414ffe15e7a690e43d64d5b04`
and
`e427bb41a7cd351e0b092333a6ce800a4abd931fa7593e3b9d6f127f9b95895f`.

## Executable product boundary

- `POST /v1/coordinator-bundles` accepts one authenticated bounded objective.
  Owner-scoped `GET` and `DELETE /v1/coordinator-bundles/{requestId}` expose
  status and cancellation only to the authenticated owner.
- The server reads only current, owner-visible, lineage-bound Curator proposals.
  The model may select proposal indexes only. Server-owned code derives the
  proposal bundle and complete citations; every successful bundle is
  noncanonical and review-required and performs no autonomous action or
  knowledge mutation.
- Native Rust owns the bearer exchange, strict request/result/citation
  validation, one connection lease, cancellation, terminal retention, and quit
  containment. Credentials and internal request/evidence hashes never enter
  the renderer.
- The renderer provides one explicit Coordinator composer and displays only
  the server-derived bundle and citations. Remote unavailability does not
  disable local recording, transcription, or Knowledge controls.

## Private qualification read-back

On 2026-08-14 the checked gate ran at the clean exact head above and observed:

- 8 cases across 8 authenticated owners and 10 product requests;
- 10/10 exact terminal projections: 5 complete, 4 evidence-unavailable, 0
  failed, and 1 cancelled;
- 5/5 exact server-derived bundles with server-owned citations;
- authenticated `POST`/`GET`/`DELETE`, strict owner isolation, and hidden-only/
  absent public equivalence;
- fail-closed HTTP cancellation after model admission with no returned bundle;
- exact Curator proposal lineage, Coordinator result audits, knowledge-tool
  audits, and activation history through two owned PostgreSQL restart/read-backs;
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
owned broker socket, provider container, private network, qualification
container/network/volume, PostgreSQL tree, or rapid/complex listener remained.
The private evidence directory and files remain owner-only outside Git.

## Public verification

Against this exact implementation candidate:

- the complete portable server suite passed **1,622 total = 1,575 passed + 47
  declared skips**;
- the governed fixed set passed **173 total = 169 passed + 4 declared skips**;
- focused Coordinator product/core checks passed **41 tests**;
- whole-server Ruff passed;
- desktop Vitest passed **63 files / 391 tests**, and the production
  TypeScript/Vite build completed;
- desktop Rust passed formatting, strict all-target/all-feature Clippy, and its
  complete locked test matrix.

On the public documentation successor, documentation truth and relative links
passed 4/4, the 373-entry maintainability appendix matched the tracked tree
exactly, and `git diff --check` was clean.

## Claim limits and privacy

No private tenant/subject identity, run/request ID, objective, proposal,
evidence, bundle, citation, model output, database row, DSN, host path,
individual timing, or private receipt is committed. Git records only exact
revisions, public-safe hashes, aggregate counts, booleans, and bounded outcomes.

This result qualifies the authenticated Coordinator server/database/broker
boundary. It does not qualify a private native/renderer round trip, live
enterprise identity-provider exchange, hosted review, merge, production
deployment, simultaneous Qwen/Gemma residency, sustained capacity, or a
p50/p95/p99 SLO. Gemma remains the qualified local complex route. Muse Spark
1.2 is recorded only as a future hosted-provider watch item because deployable
open weights are not available for this local/offline boundary.
