# Bind embedding preparation to stored reviewed source

**Owner:** Grant McNatt. **Date:** 2026-10-04. **Status:** Local software verified; hosted integration pending.

After reviewed staging, actual PostgreSQL chunk bodies were changed while the
original files remained intact. The original embedding writer still returned
success and added vectors: zero vector rows became one. The
[original observation](original-result.txt) records synthetic vectors only.

The existing [embedding and publication owner](../../../../server/src/yap_server/knowledge/generation_ledger.py)
now shares one stored-source validator. Under the existing tenant lock, embedding
preparation reconstructs the current compiled source, validates its admission and
four descriptor counts, then compares the complete prepared-vector keys against
the validated chunks before writing. Invalid state refuses without repairing
source, metadata or vectors. Valid first preparation and staged retries remain
usable; previously published projections retain their existing immutability.

## Observed checks

- **Eleven real PostgreSQL ledger cases pass.** Two new regressions cover thirteen
  independently prepared storage mutations and an actual advisory-lock wait.
  Mutations include chunk text/span, concept text/metadata, relationship type,
  permission policy/audience, reviewer, revision and all four counts. Refusal
  preserves snapshots of twelve tenant tables and original source bytes.
- A separate writer is observed waiting in PostgreSQL's `Lock` / `advisory`
  state. Another transaction changes stored chunk text before releasing the lock;
  the resumed writer rechecks and refuses without vector/model writes. The two
  regressions fail against the original writer; fourteen failed assertions are
  mutation/wait outcomes, not fourteen new test cases.
- **All 144 required database cases pass across 25 modules without skips**, on
  owned digest-pinned PostgreSQL 17.11 / pgvector 0.8.7.
- **All 201 governed portable cases pass across 31 modules**, with no skips,
  expected failures or unexpected successes. Server-wide Ruff and three changed
  Python-file formatting checks pass.

**Full isolated Ubuntu server discovery passes:** 1,664 passed and 141 declared
platform/fixture/database exclusions (1,805 total). The required database gate
separately executes both new SQL regressions without skips. All 30 relevant
documentation/license/provenance/population/workflow checks pass without skips.
[Results](check-results.txt) retain commands and populations. No native/renderer
changes or renewed desktop qualification are claimed.

The tests supply explicit synthetic vectors. This guard checks the stored source
being prepared; it does not prove that supplied vectors came from a particular
provider or describe that source accurately. Provider selection, real embedding
generation, the operator interface and complete product rebuilding remain open.
It adds no Git review/approval verification, Entra deployment, enterprise policy
or Windows qualification. See the [operator guide](../../../specs/knowledge-publication.md)
and [whole project queue](../../../plans/active/2026-10-02-yap-project-hill-climb.md).
GitHub account access still gates pushing and reviewed hosted integration;
independent software work continues.
