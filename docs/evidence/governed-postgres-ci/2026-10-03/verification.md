# Complete model-free PostgreSQL gate

**Owner:** Grant McNatt. **Date:** 2026-10-03. **Status:** All five software outcomes verified; reviewed integration complete.

Hosted server checks exclude real database cases. The original dedicated gate ran four modules/19 cases. The complete gate now requires **23 modules/117 cases**, covering knowledge generations, permission-safe retrieval, all eight agent roles, terminology and authenticated Connections APIs. Empty or failed modules, skips, expected failures and incomplete execution cannot produce a passing receipt.

The Linux hosted job runs this gate against its own disposable database. The launcher first checks the locked Python 3.12 runtime, then starts a digest-pinned PostgreSQL/pgvector container on a random loopback port. It owns generated test credentials, bounded connection/SQL/readiness/test deadlines and a 2-CPU/512-MiB budget. Data lives in container tmpfs; cleanup removes only the uniquely named container. No developer or production database/volume is mounted. Inherited Docker/database routes cannot redirect the gate.

## Acceptance and evidence

| Outcome | Local verification | Hosted boundary |
| --- | --- | --- |
| Complete required suite | All 117 cases pass without skips on fresh disposable runs, including the final main-checkout implementation. The runner requires every named module and complete success. | All 117 cases pass without skips in final hosted run 547. |
| Isolated runtime and cleanup | Pinned PostgreSQL 17.11 and pgvector 0.8.7 report their identities; the owned container is removed after successful and failed test execution. A run with invalid inherited Docker/database routes still passes all 117 against its own runtime. | Hosted startup and teardown pass on the final reviewed head. |
| Self-contained fixtures | Unchanged main reproduces the Auditor fixture's one-source/two-source expectation mismatch. The corrected synthetic query reads both authorized statements. A fresh database also exposes a missing reviewed-capture schema in shared Curator cleanup; the fixture now installs every schema it uses. | No production authorization or model behavior changes. |
| Required hosted closure | Existing Linux lifecycle/identity job adds an unconditional PostgreSQL step and installs locked evaluation/test dependencies. A release contract refuses a missing, conditional or continue-on-error gate. All 72 local release contracts run: 67 pass, five Windows-only skips. Ruff passes. | All six exact-head jobs pass; integration below. |

## Review and hosted rehearsal

[Run 546](https://github.com/ZoOtMcNoOt/yap/actions/runs/37136218110) executes all **117 PostgreSQL cases without skips** on initial head `b6307e90ea9012089d732037fd5ecf32a4a9cdd5`, with successful teardown. This qualifies that rehearsal; final integration is recorded below.

Review reproduced the aggregate qualification validator rejecting the new receipt because it retained a duplicated 19-case contract. The runner now imports the existing aggregate gate's complete membership/count constants, matching the portable runner's pattern. Contract checks reject skips, old/incomplete counts and missing modules; the actual complete receipt passes with matching development runtime identity. Historical model artifacts and the separate ARM64 production database lock remain unchanged.

The portable server job also exposed an existing OIDC clock-boundary fixture race: a two-second verification delay makes its future tokens fall inside the allowed skew. The test now fixes both validation clocks, uses numeric timestamps and checks accepted/rejected expiry, not-before and issued-at boundaries. Authentication policy is unchanged. All 23 focused aggregate/authentication cases and the renewed disposable 117-case gate pass. The isolated portable server executes all 1,754 cases: 1,640 pass with 114 declared platform/fixture/database exclusions. Final exact-head hosted integration is recorded below.

## Reviewed integration

[PR #204](https://github.com/ZoOtMcNoOt/yap/pull/204) merges as `b19b8e7199396ba52e2388ecf7949b00ad9a86ca` after [run 547](https://github.com/ZoOtMcNoOt/yap/actions/runs/37137161514) passes all six jobs on `8816301942d1a4a10e832f8bf2a6a9d8cc08cf83`. PostgreSQL executes **117 cases, no skips**. Windows passes **398 frontend units**, **205 browser cases**, **72 release contracts**, **two adapter cases**, strict Clippy and **1,370 native units + 27 integrations** (11 declared model/hardware ignores), plus native WDIO. Server executes 1,754 cases: **1,601 pass/153 declared exclusions**; identity and service lifecycle pass. Main's tree `557be6ad72164ac7952b6266133d5f9592334245` exactly matches the reviewed head, retained in `refs/archive/pull-204-head`; the iteration branch is retired.

### Completed acceptance

- [x] Require every database-backed knowledge, agent and authenticated API module: all 23 modules/117 cases must execute successfully with no skips, expected failures or incomplete receipts.
- [x] Own a digest-pinned disposable PostgreSQL/pgvector runtime with fresh credentials, loopback-only routing, bounded startup/tests and cleanup. Ignore inherited database/Docker routes and remove only this run's container.
- [x] Make fixtures self-contained on a fresh database. Reproduce existing failures independently; correct synthetic evidence/schema setup without weakening production authority or model behavior.
- [x] Add the same unconditional gate to existing Linux CI, using locked Python dependencies. Verify local execution, runtime provenance, documentation and the release contract that keeps it required.
- [x] Review/push and integrate only after all exact-head jobs pass; preserve the reviewed head and retire the temporary branch. Continue publication/rebuilding and every available workstream.

## Runtime provenance

- Image: `pgvector/pgvector@sha256:ac08538c6f8b9904c33c8224c5e5706dbe760aca29db1d096972b4052c22a75d`.
- Observed PostgreSQL: `17.11 (Debian 17.11-1.pgdg12+2)`; pgvector: `0.8.7`.
- Publisher: [pgvector](https://github.com/pgvector/pgvector); [inspected v0.8.7 license](https://github.com/pgvector/pgvector/blob/v0.8.7/LICENSE). Upstream notices remain in the image; this adds a test runtime rather than a shipped dependency.

The retained development database still uses PostgreSQL 17.11/pgvector 0.8.0. Existing evidence retains its original versions. The new gate uses synthetic vectors and deterministic providers to verify persistence, authority, transport and recovery. It does not qualify real embeddings, reasoning accuracy, production capacity, private identity or enterprise deployment.

## Run it

On Linux with Docker and the locked server environment:

```bash
source verification/cloud-env.sh
server/.venv/bin/python verification/run-disposable-governed-postgres-suite.py
```

For an explicitly configured local test database, load its private `YAP_TEST_POSTGRES_DSN`, change to `server`, and run `PYTHONPATH=src .venv/bin/python ../verification/run-governed-knowledge-postgres-suite.py`. Do not print or commit the database environment.
