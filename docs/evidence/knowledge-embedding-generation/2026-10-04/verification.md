# Generate reviewed embeddings through the operator service

Owner: Grant McNatt. Date: 2026-10-04. Status: 6/7 outcomes locally software
verified; reviewed all-six-job exact-head hosted integration remains pending.

The actual source-preparation journey stopped at staging: no authenticated action
could generate its missing vectors. The regression returned `404`; [original
observation](original-route.txt) preserves that result. Explicit
`POST /v1/knowledge/embedding-preparations` now connects the existing publication
owner, stored compiled-source validator, immutable vector writer and bounded
loopback JSON transport. No new dependency or separate authority is introduced.

Deployment selects one already-running numeric-loopback embedding service and
prepared model/revision. The admitting curator supplies only the exact stored
generation reference. Source/admission/count validation precedes dispatch; only
exact compiled chunk text is sent. Complete indexed 768-dimensional finite vectors
and content-free success audit commit under the existing tenant lock. Refusals
preserve source/proposals/active/history. Published/conflicting/partial projections
refuse; complete same-model staged replay revalidates without another provider
call or vector overwrite. The operator guidance records bounds and uncertain
confirmation recovery; these actions do not start or download a model.

Nine real HTTP/PostgreSQL cases verify the full pinned source → explicit staging →
embedding generation → publication → permission-filtered vector and HTTP reads →
rollback journey, plus authority, source/admission/count damage, partial vectors,
provider failure, failed audit, concurrent replay and lock timeout. Alice retrieves
the exact newly embedded chunk through pgvector; Bob receives no result. The
final nine-case journey run passes in 7.537s. Eight real local HTTP provider cases
cover exact Unicode input, out-of-order/duplicate/missing indexes, wrong model,
invalid vectors, input/response bounds, empty chunks, configured-disabled/no-I/O,
HTTP failure and a contained socket timeout followed by recovery.

All 161 required PostgreSQL cases in 26 modules pass without skips (48.064s),
using owned digest-pinned PostgreSQL 17.11/pgvector 0.8.7. All 209 governed portable
checks in 32 modules pass without skips (18.843s). Full isolated Ubuntu server
discovery passes 1,672 with 158 declared platform/fixture/database exclusions
(1,830 discovered, 93.511s); required real SQL runs separately above. All 15
OpenAPI/HTTP-identity/publication-configuration checks pass (0.047s). Server Ruff,
changed-file formatting and documentation/license/provenance/population/workflow
contracts pass. Final bounded diff review finds no remaining actionable defect.
Shared source API fixtures now have a separate test-case base so new integration
coverage does not duplicate existing source-preparation tests.

Fixture organization principals and deterministic synthetic vectors verify
orchestration only. No real model inference, embedding quality/provenance,
production identity, physical Windows or enterprise network policy is qualified.
The configured revision is trusted deployment metadata, not a provider artifact
attestation. [Operator instructions](../../../specs/knowledge-publication.md#generate-reviewed-embeddings)
retain the prepared-provider qualification requirement, 64-chunk/256-KiB input
boundary, disabled route, strict requests and immutable published-data recovery.
Desktop rebuild controls, larger rebuild orchestration, actual provider/corpus
qualification and the entire remaining roadmap stay open.

[Review corrections](review-verification.md) retain actual oversized-numeric
provider/HTTP failures and the shared-serializer fix, renewed complete suites,
and consistent integration-status descriptions. The test population is unchanged.
