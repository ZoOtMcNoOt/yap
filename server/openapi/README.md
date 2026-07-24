# Server contracts

Server-tier contracts start here.

- `openapi.json` is the normative HTTP contract for health, verified ASR
  capabilities, the loopback batch-job boundary, and the separately enabled
  bounded LID preflight/cancellation boundary.
- `live-events.schema.json` describes the contract-only live event and
  reconnect vocabulary.
- `examples/` contains schema-checked public contract examples. The LID request
  example is the JSON manifest inside the versioned binary envelope; it is not
  raw audio.

The default profile implements health only. Batch operations require the
loopback job runtime. LID operations and the optional `languagePreflight`
catalog field appear only after the locked LID runtime verifies. Live WSS and
authentication remain unavailable. Keep generated clients out until type drift
becomes real.
