# Restore reviewer-owned retained knowledge over HTTP

Owner: Grant McNatt. Date: 2026-10-04. Status: 5/6 outcomes locally verified;
reviewed six-job exact-head integration remains pending.

Publication returned an explicit-rollback instruction for retained data, but the
HTTP operator had no rollback route. The real retained-generation regression
returned 404 before implementation; [original observation](original-route.txt)
retains the failure. `POST /v1/knowledge/rollbacks` now restores a previously
published complete generation using the existing publication service, authenticated
principal, tenant lock, complete-generation validation and atomic success audit.
Existing publication inspection supplies the target/current metadata.

The active queue defines six acceptance outcomes. Authority/isolation, retained
source/vector truth, atomic recovery and explicit replay are checked with real
HTTP and digest-pinned PostgreSQL 17.11/pgvector 0.8.7. Fixture principals and
768-dimensional synthetic vectors exercise orchestration only. No model output,
production identity, IT policy, Windows behavior or real embedding quality is
qualified. No vectors, source or proposals are rewritten by rollback.

Eight added SQL/HTTP cases cover persistence/restart/replay, other-reviewer and
cross-tenant refusal, unpublished/pruned targets, stale active references, source/
admission/vector/count mutations, audit failure/lock timeout, concurrent rollback
versus publication and strict/disabled/runtime/log boundaries. All 152 cases in
25 required database modules pass without skips (60.141s). All 201 governed portable cases pass without skips (10.945s); 15 OpenAPI,
HTTP identity and configuration cases pass. Full isolated Ubuntu discovery passes
1,664 cases with 149 declared platform/fixture/database exclusions (1,813 total,
97.766s); all real SQL cases execute separately above. Server Ruff, seven-file
format checks and all 30 documentation/license/provenance/population/workflow
cases pass (7.252s). No changed renderer or native checks are claimed for this
server-only increment. Final review finds no remaining actionable defect in
the bounded rollback change.

Use [operator instructions](../../../specs/knowledge-publication.md#restore-a-retained-generation)
to inspect, restore and recover uncertain confirmation. Actual embedding-provider
selection/generation, full source-to-product rebuilding, desktop integration,
pruned-source restore and the rest of the active roadmap remain open.
