# Explicit publication of reviewed knowledge

**Owner:** Grant McNatt. **Date:** 2026-10-04. **Status:** Five local software outcomes verified; hosted integration pending.

The authenticated operator journey previously had no publication route and
returned `404` ([observed response](original-route.txt)). Existing admission/staging/activation functions could not be
reached through an explicit HTTP publication request. The new
[service](../../../../server/src/yap_server/knowledge/knowledge_publication_service.py)
and [request owner](../../../../server/src/yap_server/api/knowledge_publication_requests.py)
offer reviewer-owned inspection and publication; the
[operator guide](../../../specs/knowledge-publication.md) records setup and recovery.

Organization authentication and the existing `knowledge.curator` role determine
tenant and reviewer. Requests cannot supply source or approval authority. The
existing tenant lock serializes expected-active comparison and complete
relational/vector validation. Replay revalidates current stored truth without
another activation; retained generations require explicit rollback. Activation
and its success audit share a transaction. Failed preparation, tampering, stale
intent and audit failure retain the previous state.

## Observed checks

- **18 focused real-database cases pass:** ten new authenticated HTTP cases plus
  eight existing generation-ledger cases. They cover publication/replay/restart,
  first activation with explicit `null`, reviewer/role/tenant isolation, stale
  intent, retained targets, incomplete/tampered state, audit rollback, lock
  timeout, concurrent requests, invalid replay and strict request/logging bounds.
- **Seven portable configuration cases pass**, including explicit mode/auth,
  private credential and unavailable-startup refusal, and authenticated disabled
  routes (`501`) versus unauthenticated requests (`401`).
- **All 129 required database cases pass across 24 modules, without skips**, on
  the owned digest-pinned PostgreSQL 17.11 / pgvector 0.8.7 disposable runtime.
- **All 192 governed portable cases pass across 30 modules**, with zero skips,
  expected failures or unexpected successes.
- **Full isolated Ubuntu server discovery passes:** 1,655 passed and 126
  declared platform/fixture/database skips (1,781 total). The required database
  gate above separately runs the publication database cases without skips.
- **Twelve startup and route-contract cases pass** after broad verification
  caught missing publication inventory and a stale startup assertion; the
  final full suite includes both corrections.
- **Release contracts pass:** 67 passed and five Windows-only skips (72 total).
  Server-wide Ruff, eleven changed owner/test formatting checks and all 14
  documentation/license/provenance/population contracts pass.

[Recorded results](check-results.txt) retain observed populations and pinned
runtime identities. From the prepared checkout:

```bash
source verification/cloud-env.sh
server/.venv/bin/python verification/run-disposable-governed-postgres-suite.py
(cd server && PYTHONPATH=src .venv/bin/python ../verification/run-governed-knowledge-portable-suite.py)
bash verification/test-cloud-server.sh
pnpm --dir desktop test:release-contract
```

No renderer/native code changes are part of this increment; prior desktop
receipts remain dated baselines. Audit-failure recovery injects a database
exception at the success-audit call after actual SQL activation, verifying full
transaction rollback. Concurrent actual HTTP requests share one expected build:
one succeeds and one refuses; no claim is made that both were observed blocking.

Tests use explicit synthetic vectors and an authenticated test principal on an
actual HTTP server/database. They do not qualify inference, an organization
identity-provider deployment, production governance or Windows behavior. The
route neither fetches/verifies Git nor creates source admission, review approval
or vectors. Source preparation, canonical rebuilding and full product integration
remain open. GitHub is disconnected, so pushing and reviewed exact-head hosted
integration remain pending. Historical receipts retain their original counts.
