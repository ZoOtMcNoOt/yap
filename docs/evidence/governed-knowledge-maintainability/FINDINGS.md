# Governed Knowledge Maintainability Findings

**Discovery anchor:** `e2fff1f5b087cc05a549588ea41aae71a6806024`

This is the public-safe consolidated register for exactly three independent
read-only reviews. Reviewers do not edit. The primary controller deduplicates,
adjudicates, and implements accepted findings after discovery.

## Severity and disposition

- **P0:** immediate data-loss, cross-owner/security, or uncontrolled-resource
  failure that prevents continued development.
- **P1:** correctness, authorization, privacy, provenance, lifecycle, or
  false-green evidence defect that blocks the checkpoint.
- **P2:** concrete maintainability, naming, cohesion, documentation-truth, or
  bounded failure-path defect that blocks the checkpoint.
- **P3:** optional optimization or later-phase improvement; record it without
  turning the checkpoint into open-ended research.

Every accepted finding needs an exact code/document anchor, owner/workflow,
executable failure or maintenance scenario, smallest sound fix, focused check,
and final disposition: verified correct, fixed here, retained with concrete
justification, deferred to a named phase, or blocked by an external owner.

## Discovery register

| ID | Severity | Lens | Owner/workflow | Evidence and failure scenario | Disposition | Verification |
| --- | --- | --- | --- | --- | --- | --- |
| KAP-01 | P1 | Knowledge authority/persistence | Active generation and permission-safe queries | `postgres_permission_view.py` read the active generation before later retrieval statements without holding the tenant advisory lock shared against activation/pruning. Under READ COMMITTED, a writer could activate and prune between authorization and retrieval. | Implemented; final Postgres gate and independent re-review pending | Authorization now acquires the shared tenant transaction lock before reading the active generation and holds it through retrieval/proposal/audit commit. A two-connection barrier regression proves activation/pruning waits and the next query sees G2. |
| KAP-02 | P1 | Knowledge authority/persistence | Authoritative result -> reviewed capture | The review omitted job/title identity, and append accepted those values again while returning an unobserved descriptor after `ON CONFLICT DO NOTHING`. | Implemented; final Postgres gate and independent re-review pending | Review identity now binds job/title/result; append derives the owner-scoped authoritative job/result, uses `RETURNING`, and admits only exact stored retry. Cross-owner/replayed/changed normalization and restart read-back regressions are in the required database lane. |
| AR-01 | P1 | Agent runtime/evidence | Owned vLLM qualification lifecycle | The runtime accepted Docker's returned ID but inspected/stopped/removed by fixed name and lost partial-start identity. | Implemented; fresh private qualification and independent re-review pending | A typed pending immutable ID is retained immediately; all inspection/containment operates on that ID and verifies exact name/image/command/nonroot/network/IPC/GPU/mount/ulimit/cgroup policy. Focused vLLM/qualification lifecycle tests pass. |
| AR-02 | P1 | Agent runtime/evidence | Governed MCP database cancellation | MCP abandoned its thread on cancellation, while a daemon watcher lost `cancel_safe` failure and did not require completion. | Implemented; final re-review pending | A non-daemon watcher reports cancel failure, closes an unacknowledged connection, joins under fixed bounds, and rejects late success. MCP signals cancellation and shield-waits under a five-second acknowledgement bound. Eight focused cancellation/MCP tests pass. |
| KAP-03 | P2 | Knowledge authority/persistence | Reviewed source admission -> compilation -> staging | Reviewed captures and compiled builds lacked an executable admission link. | Implemented; final Postgres gate and independent re-review pending | One durable source-admission ledger binds exact reviewed capture or curated repository revision/path/manifest/content to the compiled generation. Staging requires that identity; unreviewed, mutated, fabricated, and cross-owner cases fail. |
| KAP-04 | P2 | Knowledge authority/persistence | Proposal retention and generation pruning | Every proposal created an orphanable generic generation hold and had no disposition. | Implemented; final Postgres gate and independent re-review pending | The duplicate hold layer is deleted. Prune consults unresolved proposals directly; authorized owner-only discard and prune serialize under the tenant lock. Retention/release/concurrency regressions are in the required database lane. |
| KAP-05 | P2 | Knowledge authority/persistence | Permission-safe retrieval | Two test-only in-memory permission/search implementations shipped beside canonical Postgres retrieval. | Fixed by deletion; final re-review pending | Both production modules and their duplicate behavioral test are removed. The neutral tree DTO moved to the Postgres owner; compiler-only assertions remain portable and permission/retrieval behavior stays in the zero-skip Postgres lane. |
| KAP-06 | P2 | Knowledge authority/persistence | Development identity schema | The development repository preserved an obsolete v1-to-v2 compatibility mutation. | Fixed by deletion; focused verification green | Only empty/current schemas are accepted. The migration and its preservation test are removed; obsolete/unknown/malformed nonempty stores fail without byte mutation. |
| AR-03 | P2 | Agent runtime/evidence + architecture | Governed tool protocol | Qualification, MCP, RAG, and storage duplicated divergent tool schemas and limits. | Implemented; fresh private qualification and re-review pending | `knowledge_tool_contract.py` now owns functional Pydantic types, schemas, bounds, and argument validation. RAG/MCP/storage/evaluation consume it; exact boundary and schema-parity tests pass. |
| AR-04 | P2 | Agent runtime/evidence | vLLM prompt/output endpoint | The client accepted mutable `localhost` instead of numeric loopback proof. | Implemented; focused verification green | The existing numeric-loopback parser is reused. Tests reject hostname/userinfo/path/query/fragment/nonloopback/port zero and accept canonical numeric IPv4/IPv6 loopback. |
| AR-05 | P2 | Agent runtime/evidence | Create-once private JSON publication | The governed gate used a misleading model-specific evidence writer. | Fixed by rename/deletion; focused verification green | The obsolete module is deleted. `private_json_evidence.py` owns canonical newline bytes, create-once `O_EXCL`, owner-private mode, fsync, and destination/link rejection for both callers. |
| ARCH-01 | P2 | Architecture/human maintainability | Canonical executable ownership map | The canonical map stopped at Phase 8 and omitted Phase 9 durable writers/consumers. | Documentation reconciled; navigation assessment and re-review pending | The map now identifies reviewed-source admission, terminology, generation/active-pointer/retrieval, proposal/audit, MCP/RAG, explicit routes, vLLM qualification, and aggregate-gate owners plus persistent-state consumers and Phase 10/IT handoffs. |
| ARCH-02 | P2 | Architecture/human maintainability | Normative/current documentation | Voice OS and ADR status prose called merged Phase 9 active/candidate or pending merge. | Documentation reconciled; re-review pending | Current/normative descriptions now say merged Phase 9 baseline, preserve asynchronous/local controls, and distinguish it from production supervision/capacity in Phase 10. |
| ARCH-03 | P2 | Architecture/human maintainability | Reasoning transport dependency | The vLLM transport imported its retry error from the high-level RAG workflow. | Implemented; focused verification green | `ReasoningRetryableError` moved into the neutral explicit-route contract. Client and RAG import downward; focused tests and Ruff pass. |
| ARCH-04 | P2 | Architecture/human maintainability | Test ownership/cohesion | One 700+ line module mixed aggregate-gate contracts with owned Postgres/Docker lifecycle tests and fakes. | Implemented; exact current membership frozen | Gate contracts and owned Postgres runtime tests now live in separate functional modules. The Phase 9 portable contract lists 24 modules/125 tests; the database contract lists 4 modules/14 tests. |

## Bounded P3 observations

- The governed gate captures child stdout/stderr without a byte bound. Consider
  a local bounded capture/spool policy when the gate next changes; do not build
  a generic runner framework.
- `jobs/service.py` is large, but its single locked aggregate root is a credible
  cohesion boundary. Retain it with that explicit justification unless a pure
  transition policy can be extracted without creating a second state owner.
- Retain cohesive large SQL/lifecycle owners where decomposition would split a
  transaction or state machine. Remove duplicated protocol and test ownership
  instead of applying a mechanical line quota.

Private scan identifiers, host paths, model outputs, measurements, prompts,
retrieved content, transcripts, credentials, and database rows never belong in
this register.
