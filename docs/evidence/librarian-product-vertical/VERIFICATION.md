# Librarian product-vertical verification

**Status:** Exact executable candidate
`e2ba1864ec989a2bb693e000d0b4c30910d2720f` privately qualified the
authenticated Librarian HTTP server boundary. Its native, renderer, and
Knowledge-workspace code was exact-head public-test green, but that client path
was not part of the private gate. Hosted head
`67a79ce2a888e626ab562515b665c8ed33c8d51e` passed all 12 required checks,
and PR #174 merged the vertical as
`98af78c940ea801a37103f615002658f90626fb3`.

## What the candidate implements

- The authenticated server owns bounded asynchronous Librarian queries through
  `POST /v1/librarian-queries` and owner-scoped `GET`/`DELETE` operations on
  `/v1/librarian-queries/{requestId}`.
- `YAP_LIBRARIAN_RUNTIME=permission_safe_postgres` requires organization
  authentication, an absolute admission-socket path, and an absolute private
  PostgreSQL DSN-file path. Disabled or incomplete configuration fails closed.
- Tauri Rust owns the bearer-bearing HTTP exchange, validates the complete
  evidence wire and recomputes its canonical evidence hash before React can
  observe it, and cancels accepted work on ownership or shutdown failure.
- The desktop adds a dedicated **Knowledge** workspace with one active query,
  explicit cancel/retry controls, and at most three permission-safe excerpts
  with source-revision/span citations. It is not a generic chat surface.
- Server or capability loss clears remote knowledge results without disabling
  local capture, playback, transcript history, correction, or other offline
  controls. Hidden-only and absent searches use the same public unavailable
  presentation.

The vertical reuses the previously qualified Librarian core. It adds no model,
proposal, source mutation, knowledge activation, bearer storage in React,
renderer-owned server call, fallback route, or compatibility path.

## Private authenticated-server qualification

The exact candidate returned
`librarian-authenticated-product-server-boundary-qualified` with public-safe
evidence SHA-256
`45eac22913c807c0390ae2410e5a486d4bd03fd849e00c8a39e927f973635a92`.
The frozen acceptance-plan and corpus SHA-256 values are
`eda3e4d6c674ad5d737d95309f689b3421ce8b93e14aea883095426d403125fc`
and `928c4053d2237e1ca64e990402520e296b27ef1d8378747083fb622f6d031ffe`.

The owner-private gate proved:

- eight synchronized authenticated owner calls through a real threaded HTTP
  server and **10/10** exact terminal views: four complete, three unavailable,
  one failed, and two cancelled;
- missing and invalid bearer rejection for `POST`, `GET`, and `DELETE`, plus
  uniform `404` denial for a foreign owner's read and cancellation request;
- live Server-IO capacity **1**, a second owner remaining queued, explicit
  queued cancellation, and a queue-inclusive deadline with exact containment;
- independently revalidated evidence wires, content hashes, spans, ordering,
  request identities, and durable result/tool-audit cardinality;
- two owned PostgreSQL restarts with exact read-back, unchanged active
  generation, no proposal mutation, no model-route lease, worker containment,
  and six-part database teardown; and
- a public-safe receipt containing only bounded hashes, counts, booleans, and
  outcome identities. Raw tenants, subjects, queries, evidence, measurements,
  paths, credentials, and database rows remain owner-private outside Git.

Exact predecessor `1d5862669bf53b0b551090c5edb6945d36ee17a2` failed before
workload or database execution because candidate admission rejected a tracked
zero-byte package marker. It emitted no receipt and is terminal/inadmissible.
The successor makes that nonempty bounded-input invariant executable in its
focused gate test.

## Exact-head public verification

The exact candidate completed these public checks on 2026-08-13:

- portable server suite: **1,521 total = 1,474 passed + 47 declared skips**;
- governed fixed membership: **173 total = 169 passed + 4 declared skips**;
- Ruff over all server `src` and `tests`: passed;
- desktop unit suite: **59 files / 373 tests passed**;
- production TypeScript/Vite build: passed;
- Rust workspace tests: **1,253 passed + 11 expected ignored**;
- strict Rust Clippy with all targets/features: passed;
- focused product-gate suite: **8/8 passed**;
- combined native WDIO: **4/4 spec files**, **15 passed + 2 declared
  hardware-dependent skips**, including the Knowledge offline workspace,
  genuine process restart, live-overlay focus, and tray flows; and
- `git diff --check` plus the exact maintainability inventory: passed.

The 250-line inventory is **598 = 344 at or above 350 lines + 254 from 250
through 349**. The exact 344 high-band path/line/disposition tuples are recorded
in the governed-maintainability evidence.

The earlier
[Librarian core receipt](../librarian-permission-safe-evidence/VERIFICATION.md)
remains historical evidence for its exact internal-core head and is not
relabelled as endpoint/native/UI evidence.

## Deliberate limits

This candidate does **not** prove:

- a private native-to-server-to-renderer round trip or a live enterprise
  identity-provider exchange; the private gate qualifies the authenticated HTTP
  server boundary, while native and renderer behavior are public-tested;
- enterprise deployment or production operation;
- sustained throughput, p95/p99, simultaneous Qwen/Gemma residency, or a
  production SLO; or
- any other role's product exposure. Archivist, Student, and Curator have
  separate qualified and merged product evidence. Exact `78b2c638...` privately
  qualifies Analyst's product server boundary, but its successor remains
  unmerged; Coordinator and Auditor remain unexposed.

No private DSN, tenant or subject identity, query, evidence text, database row,
raw latency array, host path, credential, prompt, or model output belongs in
this record or hosted artifacts.
