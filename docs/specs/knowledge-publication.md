# Publish reviewed knowledge

**Owner:** Grant McNatt. **Status:** Local software verified; hosted integration pending.

An organization-server operator can inspect and publish an already-reviewed
generation through `/v1/knowledge/publications`. This route uses the existing
source-admission, generation and audit owners. No desktop approval action is added.
The [project queue](../plans/active/2026-10-02-yap-project-hill-climb.md)
keeps canonical-source preparation, rebuilding and product integration open.

## Prepare and enable

Complete your organization's Git or deployment-approved review first. A trusted
`knowledge.curator` reviewer must admit the curated-repository source, stage its
complete compiled generation and prepare its embedding projection through the
existing owners. The HTTP route does not fetch or verify a Git commit, admit
sources, generate vectors or turn proposal references into approval.

A rebuild retry must match its admitted compiled generation and stored
concept, permission, chunk and relationship counts. Inconsistent storage refuses
without rewriting metadata. Valid staged retries need no embeddings yet; valid
active retries retain vectors/history. Staging does not prove publication
readiness or provide repair. See [rebuild verification](../evidence/knowledge-staging-descriptor/2026-10-04/verification.md).

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
explicit rollback procedure; this route does not roll it back. On unavailable or
lost confirmation, inspect before retrying: an HTTP failure alone cannot prove
whether a server transaction committed. Inspection does not repair damaged data.
Unconfigured authenticated routes return `501`; unsupported methods return `405`.

See [OpenAPI](../../server/openapi/openapi.json) and
[verification](../evidence/knowledge-publication/2026-10-04/verification.md).
