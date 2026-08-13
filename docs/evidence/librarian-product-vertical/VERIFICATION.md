# Librarian product-vertical verification

**Status:** Exact executable candidate
`8565145b5279ed009f4c0da4339de1d35e478b93` implements the first
Librarian HTTP/native/renderer product vertical. Public portable checks are
green. The candidate has not run a new owner-private database/broker product
gate, hosted checks, review, or merge, so it is not a qualified or shipped
product surface.

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

## Public verification

The exact candidate completed these public checks on 2026-08-13:

- portable server suite: **1,513 total = 1,466 passed + 47 declared skips**;
- Ruff over all server `src` and `tests`: passed;
- desktop unit suite: **59 files / 372 tests passed**;
- focused successor desktop suite after the final offline-state regression:
  **27/27 passed**;
- production TypeScript/Vite build: passed;
- Rust workspace tests: **1,253 passed + 11 expected ignored**;
- strict Rust Clippy with all targets/features: passed;
- focused native Librarian tests: **8/8 passed**; and
- OpenAPI JSON parse, focused token/secret scan, and `git diff --check`: passed.

These are public development checks, not a replacement owner-private product
qualification receipt. The earlier
[Librarian core receipt](../librarian-permission-safe-evidence/VERIFICATION.md)
remains historical evidence for its exact internal-core head and is not
relabelled as endpoint/native/UI evidence.

## Deliberate limits

This candidate does **not** prove:

- a live product round trip through the real PostgreSQL store, admission broker,
  organization identity provider, native client, and renderer on one exact head;
- owner-private hidden/revoked/cross-owner data behavior through the new HTTP
  and native boundary;
- accessibility or native WDIO behavior for the Knowledge workspace;
- hosted exact-head review, merge, enterprise deployment, or production
  operation;
- sustained throughput, p95/p99, simultaneous Qwen/Gemma residency, or a
  production SLO; or
- product exposure for Archivist, Student, Curator, Analyst, Coordinator, or
  Auditor.

No private DSN, tenant or subject identity, query, evidence text, database row,
raw latency array, host path, credential, prompt, or model output belongs in
this record or hosted artifacts.
