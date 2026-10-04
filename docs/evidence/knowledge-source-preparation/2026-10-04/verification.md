# Prepare the configured reviewed source

**Owner:** Grant McNatt. **Date:** 2026-10-04. **Status:** Local software verified; hosted integration pending.

Authenticated HTTP previously returned `404` for source preparation; source
admission/staging required internal calls. The [original response](original-route.txt)
retains the actual observation. The existing
[publication service](../../../../server/src/yap_server/knowledge/knowledge_publication_service.py)
now exposes explicit inspection/preparation of one deployment-selected snapshot.
The [operator guide](../../../specs/knowledge-publication.md) gives setup and recovery.

An out-of-band SHA-256 binds the strict bounded manifest; the configured compiled
generation binds each source read. Organization authentication, the configured
tenant and existing `knowledge.curator` role supply reviewer authority. Client
requests select only an expected generation, never source, identity, approval,
policy or vectors. Admission, staging and success audit share a transaction and
tenant lock; failed audit rolls back actual writes. Preparation adds no embeddings
and changes no active pointer/history. Replay preserves existing state; damaged
or foreign-owned admissions refuse, and pruned published identities need restore.

## Observed checks

- **31 earlier focused actual HTTP/PostgreSQL cases pass:** twelve new source-preparation,
  ten publication and nine ledger cases. They exercise first preparation,
  replay/restart, owner/role/tenant isolation, source drift/stale intent, invalid
  storage, injected audit failure, active/retained replay, pruned-target refusal,
  concurrent first preparation, lock timeout, shared-slot saturation and request
  boundaries. Source bytes and stored state remain intact where required.
- **21 focused portable/configuration/contract cases pass**, including actual
  read-only CLI bytes/digest/refusal, source drift, strict manifest fields/paths,
  malformed/duplicate/linked/nonregular files, cached configuration and startup.
- **All 142 required database cases pass across 25 modules with zero skips**, on
  owned digest-pinned PostgreSQL 17.11 / pgvector 0.8.7.
- **All 201 governed portable cases pass across 31 modules**, with no skips,
  expected failures or unexpected successes.
- **Full isolated Ubuntu server discovery passes:** 1,664 passes and 139 declared
  platform/fixture/database exclusions (1,803 total). Server-wide Ruff and twelve
  changed-file formatting checks pass. All 30 documentation/license/provenance/
  population/workflow checks pass; release checks pass 67 cases with five
  declared Windows-only skips. [Results](check-results.txt) retain the counts.

The CLI emits exact manifest bytes and their digest without creating approval or
changing source files. The loader enforces manifest integrity, not Unix owner
privacy; the existing DSN reader retains its `0600`/owner check on Unix. Loaded
manifest configuration stays fixed until restart; bundle compilation runs for
each request. Concurrent preparation returns one changed and one replay receipt;
no claim is made that both were observed waiting on the lock. Shared slots refuse
excess source/publication work without blocking health or later retry.

Tests use deterministic organization principals, reviewed fixture admissions and
synthetic vectors. They qualify neither Git provenance/review, real model output,
Entra deployment, enterprise policy nor Windows behavior. No health capability
or native UI source action is added. Embedding preparation and complete product
rebuild/publication integration remain open in the
[project queue](../../../plans/active/2026-10-02-yap-project-hill-climb.md).
GitHub app authentication is disconnected and cloud push authentication was
rejected. Neither diagnostic establishes the cause. Hosted integration waits for
restored access; independent software work continues. Earlier receipts keep their
original populations and qualification limits.

## Source-read recovery

The [original Linux observation](original-fifo-read.txt) records a real regular
file replaced by a FIFO between the path check and actual open. The original
reader remained blocked after two seconds; its owned subprocess was terminated.
The shared bounded reader now opens nonblocking where the platform supports it,
then rejects nonregular or changed opened handles. The regression performs the
actual substitution in a bounded subprocess and passes, alongside normal CLI
and source reads. This checks the Linux race, not every filesystem failure or
Windows FIFO behavior. The replacement remains intact; the reader does not
repair or remove it.
