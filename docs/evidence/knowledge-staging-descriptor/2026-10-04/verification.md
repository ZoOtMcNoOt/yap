# Refuse inconsistent rebuild staging receipts

**Owner:** Grant McNatt. **Date:** 2026-10-04. **Status:** Five local software outcomes verified; hosted integration pending.

An actual PostgreSQL retry accepted a damaged stored descriptor: its compiled
generation contained two concepts and two permissions, but the receipt reported
five of each. Source-content validation passed while stored counts escaped the
retry check. The [original observation](original-result.txt) retains that result.

The existing [staging owner](../../../../server/src/yap_server/knowledge/generation_ledger.py)
now compares the complete stored descriptor and concept, permission, chunk and
relationship counts against the admitted compiled generation before returning a
retry receipt. A mismatch refuses without repair. Valid staged retries still
work before embeddings exist; valid active retries preserve vectors and history.
Staging supplies no publication approval or activation readiness certificate.

## Observed checks

- **Nine real PostgreSQL ledger cases pass.** The one new case independently
  damages each of four counts on both a staged and an active generation. It
  resets only its synthetic fixture between checks. Refusal preserves snapshots
  of twelve tenant tables and the original source bytes; valid retries likewise
  preserve vectors, admissions, active state and activation history.
- **All 130 required database cases pass across 24 modules, without skips**, on
  the owned digest-pinned PostgreSQL 17.11 / pgvector 0.8.7 runtime.
- **All 192 governed portable cases pass across 30 modules**, with no skips,
  expected failures or unexpected successes. Server-wide Ruff lint passes.

From the prepared checkout:

```bash
source verification/cloud-env.sh
server/.venv/bin/python verification/run-disposable-governed-postgres-suite.py
(cd server && PYTHONPATH=src .venv/bin/python ../verification/run-governed-knowledge-portable-suite.py)
```

Full isolated Ubuntu server discovery passes: **1,655 passed and 127 declared
platform/fixture/database skips (1,782 total)**. The required database gate
separately executes the new ledger case without skips. All three changed Python
files pass formatting; all 30 documentation/license/provenance/population and
workflow contracts pass without skips. [Recorded results](check-results.txt) retain populations
and pinned runtime identities.

No renderer/native checks are renewed by this server-only change. Tests use
reviewed fixture admissions and synthetic vectors; no model, Windows behavior,
production identity provider or enterprise repair procedure is qualified.
Source admission and the complete product rebuild journey remain open in the
[project queue](../../../plans/active/2026-10-02-yap-project-hill-climb.md).
GitHub access still blocks reviewed hosted integration; software work continues.
