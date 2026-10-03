# Server contracts

Server-tier contracts start here.

- `openapi.json` is the normative HTTP contract for health, verified ASR
  capabilities, the loopback batch-job boundary, and the separately enabled
  bounded LID preflight/cancellation boundary, authenticated agent operations,
  and model-independent personal and shared terminology.
- `live-events.schema.json` describes the contract-only live event and
  reconnect vocabulary.
- `examples/` contains schema-checked public contract examples. The LID request
  example is the JSON manifest inside the versioned binary envelope; it is not
  raw audio.

The default profile implements health only. Batch operations require the job
runtime. LID operations and the optional `languagePreflight` catalog field appear
only after the locked LID runtime verifies. Agent operations require their
explicit authenticated runtimes; contracts do not imply enabled models.
Terminology requires explicit organization authentication and private
Postgres configuration, independently of inference. Shared scopes require explicit trusted policy; viewing and management grants are separate. See the
[API contract](../../docs/specs/terminology-api.md) and
[configuration](../../docs/runbooks/cloud-development.md#enable-terminology-on-a-private-server).
Authenticated private live transport exists; live ASR remains incomplete and
the health capability stays false. External WSS/TLS requires the secure edge
and target qualification.
