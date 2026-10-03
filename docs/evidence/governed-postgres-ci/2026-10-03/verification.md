# Complete model-free PostgreSQL gate

**Owner:** Grant McNatt. **Date:** 2026-10-03. **Status:** Locally verified; hosted integration pending.

Hosted server checks exclude real database cases. The original dedicated gate ran four modules/19 cases. The complete gate now requires **23 modules/117 cases**, covering knowledge generations, permission-safe retrieval, all eight agent roles, terminology and authenticated Connections APIs. Empty or failed modules, skips, expected failures and incomplete execution cannot produce a passing receipt.

The Linux hosted job runs this gate against its own disposable database. The launcher first checks the locked Python 3.12 runtime, then starts a digest-pinned PostgreSQL/pgvector container on a random loopback port. It owns generated test credentials, bounded connection/SQL/readiness/test deadlines and a 2-CPU/512-MiB budget. Data lives in container tmpfs; cleanup removes only the uniquely named container. No developer or production database/volume is mounted. Inherited Docker/database routes cannot redirect the gate.

## Acceptance and evidence

| Outcome | Local verification | Hosted boundary |
| --- | --- | --- |
| Complete required suite | All 117 cases pass without skips on fresh disposable runs, including the final main-checkout implementation. The runner requires every named module and complete success. | Actual hosted execution pending. |
| Isolated runtime and cleanup | Pinned PostgreSQL 17.11 and pgvector 0.8.7 report their identities; the owned container is removed after successful and failed test execution. A run with invalid inherited Docker/database routes still passes all 117 against its own runtime. | Hosted Docker start/teardown pending. |
| Self-contained fixtures | Unchanged main reproduces the Auditor fixture's one-source/two-source expectation mismatch. The corrected synthetic query reads both authorized statements. A fresh database also exposes a missing reviewed-capture schema in shared Curator cleanup; the fixture now installs every schema it uses. | No production authorization or model behavior changes. |
| Required hosted closure | Existing Linux lifecycle/identity job adds an unconditional PostgreSQL step and installs locked evaluation/test dependencies. A release contract refuses a missing, conditional or continue-on-error gate. All 72 local release contracts run: 67 pass, five Windows-only skips. Ruff passes. | All exact-head checks must pass before merge. |

## Review and hosted rehearsal

[Run 546](https://github.com/ZoOtMcNoOt/yap/actions/runs/37136218110) executes all **117 PostgreSQL cases without skips** on initial head `b6307e90ea9012089d732037fd5ecf32a4a9cdd5`, with successful teardown. This qualifies that rehearsal; final exact-head integration is still pending.

Review reproduced the aggregate qualification validator rejecting the new receipt because it retained a duplicated 19-case contract. The runner now imports the existing aggregate gate's complete membership/count constants, matching the portable runner's pattern. Contract checks reject skips, old/incomplete counts and missing modules; the actual complete receipt passes with matching development runtime identity. Historical model artifacts and the separate ARM64 production database lock remain unchanged.

The portable server job also exposed an existing OIDC clock-boundary fixture race: a two-second verification delay makes its future tokens fall inside the allowed skew. The test now fixes both validation clocks, uses numeric timestamps and checks accepted/rejected expiry, not-before and issued-at boundaries. Authentication policy is unchanged. All 23 focused aggregate/authentication cases and the renewed disposable 117-case gate pass. The isolated portable server executes all 1,754 cases: 1,640 pass with 114 declared platform/fixture/database exclusions. Final exact-head hosted integration remains pending.

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
