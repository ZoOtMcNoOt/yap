# Analyst Product Vertical Verification

## Status

Exact executable candidate
`78b2c638ac3ce5a96cc6b3c42bb8fb302667b517` over merged Curator product
baseline `70303872261667da17becfd06f985bc8cda960bc` implements and privately
qualifies the Analyst product vertical. Its owner-private ARM64 gate returned
`analyst-authenticated-product-server-boundary-qualified` with public-safe
evidence SHA-256
`f26adfc034cdc99d667f1a99ca54daf92dc9d885456104f17787cdf2cc96fa44`.
Hosted head `4c8db7c22f6a8ebadbc73433155f060b5b699fb6` passed all 12
required checks, and PR #180 merged the product vertical as
`c95fcf1a043f919661b007f014a8dc6729aa02f2` on 2026-08-14.

The frozen product acceptance plan is
`server/analyst-product-acceptance.json`, SHA-256
`466185d7d30928fade2c70855b85eb405978fe729503ace58caec89dd00ac6ee`.
The independently qualified Analyst semantic plan and corpus remain SHA-256
`559d9a988d6e79ef5847015fed4443fbe79449bc1d010ce7fa580d84476d4b45`
and
`275f8d889dd1d5aae6f981081c24f80cb74860bdf7f784313d8b327b2c254011`.

## Executable product boundary

- `POST /v1/analyst-answers` accepts one authenticated bounded question.
  Owner-scoped `GET` and `DELETE /v1/analyst-answers/{requestId}` expose status
  and cancellation only to the authenticated owner.
- The product job composes the qualified Analyst core. Librarian first returns
  a permission-safe evidence pack; current authority is revalidated before
  model selection and again in the successful audit transaction. The model may
  select only whole evidence-item indexes. Server-owned code derives the answer
  and complete source citations; an unavailable result contains no answer.
- Native Rust owns the bearer exchange, strict request/result/citation
  validation, one connection lease, cancellation, terminal retention, and quit
  containment. Credentials and internal request/evidence hashes never enter
  the renderer.
- The renderer places an explicit cited-answer composer beside Librarian
  evidence, presents only server-derived answers and exact citations, and keeps
  local recording/transcription controls available when the remote workflow is
  unavailable.

## Private qualification read-back

On 2026-08-14 the checked gate ran at the clean exact head above and observed:

- 8 cases across 8 authenticated owners and 10 product requests;
- 10/10 exact terminal projections: 4 complete, 5 evidence-unavailable, 0
  failed, and 1 cancelled;
- 4/4 exact server-derived answers and exact server-owned citations;
- authenticated `POST`/`GET`/`DELETE`, strict owner isolation, and hidden-only/
  absent public equivalence;
- fail-closed HTTP cancellation after model admission with no returned answer;
- exact Analyst, Librarian, and knowledge-tool audit rows through two owned
  PostgreSQL restart/read-backs, with zero proposal writes;
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

- the complete portable server suite passed **1,603 total = 1,556 passed + 47
  declared skips**;
- the governed fixed set passed **173 total = 169 passed + 4 declared skips**;
- focused Analyst server/runtime/API/gate checks passed **69 total = 67 passed
  + 2 expected real-PostgreSQL skips**, including product-gate tests at **9/9**;
- whole-server Ruff passed;
- desktop Vitest passed **62 files / 387 tests**, and the production
  TypeScript/Vite build completed;
- desktop Rust passed formatting, strict all-target/all-feature Clippy, and
  **1,269 main-unit results = 1,258 passed + 11 expected ignored**, plus **27/27
  integration tests**; and
- `git diff --check` was clean at the public verification checkpoint.

## Claim limits and privacy

No private tenant/subject identity, run/request ID, question, evidence, answer,
citation, model output, database row, DSN, host path, individual timing, or
private receipt is committed. Git records only exact revisions, public-safe
hashes, aggregate counts, booleans, and bounded outcomes.

This result qualifies the authenticated Analyst server boundary. The merged
native/renderer implementation is exact-head public- and hosted-test evidence;
the private gate did not execute a native/renderer round trip or live enterprise
identity-provider exchange. It does not qualify production deployment, simultaneous Qwen/Gemma
residency, sustained capacity, or a p50/p95/p99 SLO. The internal Analyst gate's
three synchronized repeats remain the same-warm-provider semantic-repeatability
authority; this product gate runs one synchronized eight-owner product wave and
does not broaden that claim. Gemma remains the qualified local complex route.
Muse Spark 1.2 is recorded only as a future hosted-provider watch item because
Meta has not published deployable open weights for this local/offline boundary.
