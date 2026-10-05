# Publish reviewed knowledge

**Owner:** Grant McNatt. **Status:** Bounded operator software verified and integrated through PR #205, #206 and #207; desktop controls are locally verified with hosted integration pending.

An organization-server operator can prepare a deployment-selected reviewed
source through `/v1/knowledge/source-preparations`, then inspect and explicitly
publish a complete generation through `/v1/knowledge/publications`. Both use
the existing source-admission, staging, generation and audit owners. The
[desktop Rebuild task](knowledge-rebuild.md) uses these authenticated routes
for explicit preparation, publication and retained restore. Organization Git
and deployment approval remain prerequisites. The [project queue](../plans/active/2026-10-02-yap-project-hill-climb.md)
records implemented bounded embedding preparation and records desktop integration pending and keeps larger rebuild orchestration
and provider qualification open.

## Prepare and enable

Complete your organization's Git or deployment-approved review first. Configure
the reviewed source as described below, then have its trusted
`knowledge.curator` reviewer explicitly admit and stage it. Generate the complete embedding projection through the explicit operator action
below before publication.
These routes do not fetch or verify Git review. Publication itself does not
admit sources or generate vectors; proposal references cannot supply approval.

A rebuild retry must match its admitted compiled generation and stored
concept, permission, chunk and relationship counts. Inconsistent storage refuses
without rewriting metadata. Valid staged retries need no embeddings yet; valid
active retries retain vectors/history. Staging does not prove publication
readiness or provide repair. See [rebuild verification](../evidence/knowledge-staging-descriptor/2026-10-04/verification.md).

Embedding preparation also rechecks stored compiled source, admission and all
four counts under the tenant lock before updating vectors. Prepared vector keys
must cover exactly those validated chunks. Invalid source or admission refuses
without repairs or partial vector/model writes. Only never-published generations
can be prepared; published vectors remain immutable. This guards source integrity,
not model output provenance or quality. The explicit embedding action below now supplies bounded generation through a
deployment-selected loopback provider; actual model quality and deployment
qualification remain separate work. See [embedding verification](../evidence/knowledge-embedding-source-integrity/2026-10-04/verification.md).

Configure organization authentication and provision the existing knowledge and
tool-audit schemas before startup. Then explicitly enable publication:

```bash
export YAP_KNOWLEDGE_PUBLICATION_RUNTIME=postgres
export YAP_KNOWLEDGE_PUBLICATION_DSN_FILE=/private/yap/knowledge.dsn
```

Use an absolute private regular-file path outside source control. The DSN file
contains one valid UTF-8 connection string, at most 4,096 bytes. On Unix it must
belong to the server owner with mode `0600`; native Windows ACL qualification
remains separate. Credentials load once; restart after changing them. Missing,
conflicting, nonprivate or unavailable configuration fails startup with redacted
errors. Unset or explicit `disabled` mode without a DSN opens no database.

## Configure and prepare the reviewed source

Source preparation uses the publication runtime, organization authentication,
private DSN and `knowledge.curator` role above. Deploy one reviewed OKF bundle on
the server. Describe it with the read-only command; redirect stdout to a new
manifest file outside the bundle:

```bash
PYTHONPATH=server/src server/.venv/bin/python -m yap_server.knowledge.reviewed_source_snapshot \
  --bundle-root /private/yap/reviewed-okf \
  --tenant-id '<organization tenant>' \
  --repository-revision '<reviewed revision>' \
  --source-path knowledge/reviewed-okf > /private/yap/reviewed-source.json
```

The CLI emits exact JSON bytes on stdout and their SHA-256 plus a no-Git-approval
disclaimer on stderr. It opens no database or credentials and leaves sources
unchanged. A source refusal exits `2` with no JSON and redacted guidance. The
repository revision and relative POSIX `sourcePath` are provenance supplied by
the authorized operator; the command does not resolve them against Git.

```bash
export YAP_KNOWLEDGE_REVIEWED_SOURCE_FILE=/private/yap/reviewed-source.json
export YAP_KNOWLEDGE_REVIEWED_SOURCE_SHA256='<manifest SHA-256 from trusted deployment>'
```

Supply both settings and pin the exact manifest bytes through the trusted
deployment configuration, independently of the manifest file. The strict
4,096-byte maximum JSON manifest has exactly `schemaVersion: 1`, `tenantId`,
absolute real `bundleRoot`, `repositoryRevision`, relative `sourcePath` and
`generationSha256`. It must be a real regular file; linked/nonregular files,
duplicate/extra fields and digest mismatches refuse startup. The manifest has no
code-enforced `0600` requirement; the private DSN still does. Restrict deployment
metadata access according to your organization. Manifest configuration loads
once: restart after changing its file or pin. Each request recompiles the bundle
and must match the pinned generation. No manifest leaves publication available
but source preparation unconfigured (`501`); incomplete pairs fail startup.

1. As the configured tenant's reviewer, send
   `GET /v1/knowledge/source-preparations` with no query or body. It returns source
   revision/path, compiled counts, generation and current active generation, with
   status `unadmitted`, `staged`, `active` or `retained`. This metadata does not
   certify database integrity or readiness to publish.
2. Explicitly prepare the inspected generation with
   `POST /v1/knowledge/source-preparations`, JSON content type and exactly:

   ```json
   {"schemaVersion": 1, "expectedGenerationSha256": "<inspected generation SHA-256>"}
   ```

   No query, source uploads, paths, identity, policy, approval or vectors are
   accepted. Tenant and reviewer come from organization authentication. The
   reviewer who first admits this generation owns its admission; another
   reviewer cannot reopen or prepare it through these routes.
3. Successful first preparation returns `status: staged` and `changed: true`.
   Admission, staging and content-free success audit commit together under the
   existing tenant lock. Preparation creates no embeddings and changes neither
   the active generation nor activation history. Generate embeddings using the action below, then follow publication inspection
   and activation.

Same-reviewer replay rechecks source/admission/staging integrity and returns
`changed: false`; existing active/retained status, vectors and history remain.
Pruned published identities require explicit restore, not preparation. On a
changed/invalid source (`409`), inspect the configured deployment before another
explicit attempt. On `503` or lost confirmation, inspect and retry
the same generation after resolving the failure; no automatic retry or silent
repair occurs. Source preparation and publication share two request slots; busy
work returns `429` while health remains available. No health capability or native
UI source action is added. See [preparation evidence](../evidence/knowledge-source-preparation/2026-10-04/verification.md).

## Inspect, then publish

Use your existing organization authentication. Both requests require
`knowledge.curator`; tenant and reviewer come from the authenticated principal.
Only that reviewer's curated-repository admissions are available.

1. Send `GET /v1/knowledge/publications?generationSha256=<target>` with no body.
   Read its source revision, counts, status (`staged`, `active` or `retained`) and
   `activeGenerationSha256`. Inspection is metadata, not a readiness certificate.
2. For a staged target, explicitly send `POST /v1/knowledge/publications` with
   `Content-Type: application/json` and exactly:

   ```json
   {
     "schemaVersion": 1,
     "generationSha256": "<target SHA-256>",
     "expectedActiveGenerationSha256": "<active SHA-256 from inspection>"
   }
   ```

   Use JSON `null` for the expected active value only when inspection shows none.
   Hashes must be 64 lowercase hexadecimal characters. Caller-supplied tenant,
   identity, source, approval or vector fields are rejected.
3. A valid receipt has `status: active` and `changed: true` for a new activation.
   Repeating an already-active target revalidates the complete generation and
   returns `changed: false`, without another activation or vector rewrite. Replay
   accepts the prior expected-active value after complete revalidation.

New activation checks expected active state under the existing tenant lock. It
reconstructs and validates persisted relational content, source admission and
complete vector/model projection before activation. Activation/history and the
content-free success audit commit together; failed checks or audit preserve the
prior active state. Existing sources, proposals and vectors are retained.

On `409 KNOWLEDGE_PUBLICATION_CHANGED`, inspect again and review the new active
state before another explicit request. A retained target needs the existing
explicit rollback action below. The publication action does not roll it back. On unavailable or
lost confirmation, inspect before retrying: an HTTP failure alone cannot prove
whether a server transaction committed. Inspection does not repair damaged data.
Unconfigured authenticated routes return `501`; unsupported methods return `405`.

See [OpenAPI](../../server/openapi/openapi.json) and
[verification](../evidence/knowledge-publication/2026-10-04/verification.md).


## Generate reviewed embeddings

Deploy and independently verify one already-running local vLLM-compatible
embedding service. It must return 768-dimensional float embeddings through
`POST /v1/embeddings`, with its response `model` matching the configured served
model identifier. The [official vLLM embedding protocol](https://github.com/vllm-project/vllm/blob/main/vllm/entrypoints/pooling/embed/protocol.py)
defines the request and indexed response. This action does not start services,
download models, authenticate to a remote provider or promote a runtime. The
organization owns the prepared image, model artifacts, revision and qualification.

Configure all three values before server startup:

```bash
export YAP_KNOWLEDGE_EMBEDDING_ENDPOINT=http://127.0.0.1:9001
export YAP_KNOWLEDGE_EMBEDDING_MODEL_ID='<prepared served model identifier>'
export YAP_KNOWLEDGE_EMBEDDING_MODEL_REVISION='<prepared artifact revision SHA-256>'
```

The endpoint must be numeric-loopback HTTP with an explicit port and no path,
credentials, query or fragment. The model identifier is at most 128 printable
ASCII characters with no whitespace; the revision is 64 lowercase hex digits.
The revision is trusted deployment metadata, not an artifact attestation obtained
from the response. Missing/inconsistent values fail startup without database or
provider requests. With all three absent, the action is disabled (`501`). Enabling
it also requires the authenticated publication runtime above. Configuration loads
once; restart after changing it. No public/remote provider or fallback is selected.

After explicit source preparation, its admitting curator sends
`POST /v1/knowledge/embedding-preparations` with JSON content type, no query, and
exactly:

```json
{"schemaVersion": 1, "generationSha256": "<prepared generation SHA-256>"}
```

The service validates the entire stored compiled source, admission and counts
under the same tenant lock before dispatching exact stored chunk text. The request
cannot provide source text, vectors, endpoint, model, approval, tenant or subject.
One generation is bounded to 64 nonempty chunks and 262,144 UTF-8 input bytes;
the provider exchange has a 10-second deadline and 2,000,000-byte response limit.
The service refuses oversized inputs, incomplete/duplicate indexed responses,
model mismatches, invalid dimensions and nonfinite values. It does not truncate
source or retry another provider automatically. Larger rebuild orchestration
remains open. A zero-chunk generation needs no provider call.

A `200` receipt reports `status: prepared`, the generation/chunk count, configured
model/revision and `changed`. Complete vectors, model metadata and the content-free
success audit commit together; source, proposals, active state and activation
history stay intact. This action never publishes. Inspect publication and
explicitly activate separately. Previously published generations refuse; they
retain their original vectors for rollback. Conflicting model identities and
inconsistent partial projections refuse without repair.

Same-model staged replay validates completeness and returns `changed: false`
without provider dispatch or vector overwrite. After a lost reply or `503`, repeat
this explicit preparation before publishing; an audit failure rolls back every
vector and model write. Correct an unavailable or malformed provider through the
trusted deployment, then explicitly retry. A published generation needs rollback,
not regeneration. Changing models requires a separately reviewed generation; do
not edit ledger rows to bypass immutable identity.

The complete source-preparation → embedding → publication → permission-filtered
read → rollback journey is checked using deterministic local HTTP output and real
PostgreSQL. That verifies orchestration, not real embedding provenance/quality,
production identity, model capacity or enterprise deployment. Qualify the selected
prepared provider and representative corpus before promotion. Desktop rebuild
controls and broader source/product integration remain open.

## Restore a retained generation

After inspecting the target through `GET /v1/knowledge/publications`, explicitly
send `POST /v1/knowledge/rollbacks` with the same versioned target and
expected-active references used for publication:

```json
{
  "schemaVersion": 1,
  "generationSha256": "<retained generation SHA-256>",
  "expectedActiveGenerationSha256": "<currently active generation SHA-256>"
}
```

Use the existing organization bearer authority and publication configuration.
Only `knowledge.curator` reviewers can restore their own curated-repository
admissions. The target must have durable publication history and retained,
complete source/admission/count/vector truth; an unpublished staged generation
cannot become published through rollback. A pruned generation needs a separate
explicit source/projection restore procedure. Rollback never repairs stored data,
regenerates embeddings or changes source files/proposals.

The existing tenant lock compares expected-active state before changing the
pointer. Activation history records `rollback`; its content-free success audit
commits in the same transaction. The receipt uses `KnowledgePublicationReceipt`:
`status` is `active`, `changed` identifies whether the pointer changed, and
`previousActiveGenerationSha256` identifies the state observed under the lock.
Replay of the current target revalidates complete truth without another activation.

If a reply is lost or unavailable, inspect target/current state again. If the target
is active and valid, explicit retry returns `changed: false`; otherwise inspect
and decide whether to retry against the new active reference. Do not automatically
replace a newer generation. Stale intent, invalid retained truth, audit failure
and lock timeout retain the prior active state and every existing projection.
The internal ledger remains the single activation owner; no new provider,
model-quality, enterprise-identity or full product rebuilding qualification is
claimed. [Rollback evidence](../evidence/knowledge-rollback-api/2026-10-04/verification.md)
records actual HTTP/Postgres checks and their synthetic-vector boundary.
