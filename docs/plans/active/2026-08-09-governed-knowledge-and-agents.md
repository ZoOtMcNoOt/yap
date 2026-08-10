# Governed knowledge and agents

**Status:** Active on `feat/governed-knowledge-retrieval` from reviewed Phase 8
closure `10618e9d292e6810d6fee7defd7adc4902ecb2ed`.

## Authority

- [ADR 0017](../../adr/0017-knowledge-base-compiler.md)
- [ADR 0022](../../adr/0022-google-okf-permission-safe-projections.md)
- [ADR 0016](../../adr/0016-auth-identity-bridge.md)
- [ADR 0029](../../adr/0029-vllm-agent-reasoning-runtime.md)
- [Voice OS architecture](../../VOICE-OS-ARCHITECTURE.md)
- [Roadmap](../../roadmap/ROADMAP.md)
- Pinned Google OKF v0.1 revision
  `d44368c15e38e7c92481c5992e4f9b5b421a801d`

Executable behavior and persisted contracts remain authoritative when prose is
stale. This plan does not authorize a change to the long-term Voice OS frame.

## Required outcome

Deliver one governed path from an immutable, owner-scoped meeting result or
reviewed curated document through deterministic Google OKF compilation,
generation-bound permission filtering, cited retrieval, and a governed agent
tool interface. Probabilistic models may rank, summarize, or propose; they may
never compile permissions, grant access, or promote their own output.

## Ordered implementation

### 1. Canonical source and compiler

- [ ] Add pinned OKF v0.1 conformance fixtures without copying upstream code.
- [ ] Validate UTF-8 Markdown concepts, root and directory reserved files,
  required non-empty `type`, supported links, broken-link diagnostics, unknown
  types, and lossless unknown frontmatter fields.
- [ ] Validate the Yap profile: title, stable tenant-scoped `yap://` resource,
  timestamp, schema version, provenance, relationships, and redirect history.
- [ ] Compile deterministic concepts, chunks, relationships, permissions,
  provenance, diagnostics, and content hashes from a bounded source tree.
- [ ] Reject duplicate resources, path escapes, symlink/junction escapes,
  cross-tenant resources, malformed principals, unsupported schema versions,
  and conflicting permission policies.

### 2. Canonical terminology

- [ ] Amend the accepted architecture with one model-independent terminology
  domain covering personal, team, and organization scope; locale; owner;
  sensitivity; precedence; versioning; deletion; audit; and conflicts.
- [ ] Freeze one immutable terminology snapshot per job/session.
- [ ] Compile bounded provider hints, deterministic exact-form normalization,
  grammar-model preservation constraints, and permission-safe OKF glossary
  concepts from the same snapshot.
- [ ] Keep raw transcript evidence immutable and every correction reversible.

### 3. Durable compiled ledger and atomic generations

- [ ] Add Postgres migrations for tenants, builds, active generation,
  concepts/resources, permissions, lineage, audit, chunks, typed relationships,
  terminology, Lane 1 immutable captures, and pgvector embeddings.
- [ ] Compile a non-active generation, validate it completely, then atomically
  promote only the Postgres active-generation pointer.
- [ ] Prove failure injection leaves the prior generation active; implement
  rollback, revocation, bounded retention, orphan cleanup, and deterministic
  full rebuild.
- [ ] Make Redis optional and disposable; a miss falls back to Postgres, never
  raw policy files. Keep object storage behind the immutable blob interface and
  leave enterprise lifecycle configuration as an explicit handoff.

### 4. Permission-safe retrieval

- [ ] Expose Yap-owned parameterized tree, lexical/metadata, pgvector, hybrid,
  and bounded multi-hop query interfaces.
- [ ] Bind every query to token-derived tenant/subject, purpose, agent
  capability, active generation, and permission hash for its lifetime.
- [ ] Filter before retrieval where supported and recheck every result against
  the compiled ledger before return.
- [ ] Prevent hidden names, paths, resources, types, counts, degrees, backlinks,
  snippets, scores, edges, and inferred relationships from leaking.
- [ ] Return exact source revision and span citations with every result.

### 5. Governed agents, RAG, and MCP

- [ ] Give agents only the governed retrieval and proposal interfaces—never
  repository, SQL, vector-index, permission-file, or private-evidence access.
- [ ] Validate bounded structured tool inputs/outputs, prompt/context/output
  budgets, cancellation, retries, audit events, and redacted observability.
- [ ] Keep generated summaries and relationships immutable proposals with exact
  provenance and strictest-source permission inheritance until accepted.
- [ ] Expose the same governed tool contract through MCP without broadening
  authority or logging sensitive content.

### 6. Model and projection evidence

- [ ] Freeze licensed representative terminology, question-answering,
  structured-tool, and multi-user isolation fixtures before model output.
- [ ] Qualify the required vLLM workload routes: Qwen 3.6 35B-A3B NVFP4 for
  rapid automation and Gemma 4 31B IT NVFP4 for complex orchestration. Bind
  task quality, citation fidelity, structured-output validity, terminology
  preservation, prefix-cache isolation, latency, concurrency, memory, license,
  cancellation, and teardown to each exact route.
- [ ] Prove Rust/Yap selects an explicit workload class and never silently
  reroutes a failed request between models. Keep simultaneous residency and
  sustained mixed-route capacity as Phase 10 evidence.
- [ ] Treat the assignment as a frozen product hypothesis until a Qwen rapid
  latency/throughput track and a Gemma multi-step orchestration track pass.
  Common admission evidence alone must not be reported as specialization proof.
- [ ] Promote no model without workload-specific evidence; keep a deterministic
  no-model path for compiler, authorization, retrieval, and citations.
- [ ] Benchmark the Postgres/pgvector baseline first. Implement Neo4j only if it
  clears the predefined multi-hop quality, isolation, operations, licensing,
  resource, rebuild, and cost gates.

### 7. Integrated product route

- [ ] Prove `authoritative meeting result -> reviewed OKF document -> compiled
  generation -> permission-filtered retrieval -> cited answer/proposal`.
- [ ] Prove personal/team/organization terminology ownership and revocation.
- [ ] Prove cross-tenant, cross-owner, stale-generation, purpose, cancellation,
  restart, partial-publication, and cache-invalidation failure paths.
- [ ] Preserve local/offline controls when the knowledge or agent server is
  unavailable; do not silently route content or acquire credentials.

## Evidence and closure

- Use focused tests while each vertical slice changes.
- Keep source corpora, prompts, retrieved content, transcripts, credentials,
  tokens, and private evaluation output outside Git and hosted artifacts.
- Complete one bounded adversarial review of permission, compiler, retrieval,
  tool, concurrency, provenance, privacy, and maintainability boundaries.
- Freeze one exact candidate only after implementation, tests, documentation,
  provenance, and accepted findings are complete.
- Run the complete applicable local/native/server/Postgres/pgvector/vLLM/GB10
  Phase 9 matrix exactly once against that candidate.
- Reconcile ADR scores and all architecture/status claims only from evidence.
- Open one focused PR and merge only a reviewed hosted-green exact head.
- Complete the separate post-Phase-9 architecture checkpoint before Phase 10.

## Explicit exclusions and handoffs

- No raw knowledge source is queried as a substitute for the compiled ledger.
- No model output grants permission or becomes canonical without review.
- No unproved Neo4j, vLLM model, capacity, or production-readiness claim.
- No full Codex Security scan before the Phase 10 final gate.
- Entra configuration, enterprise repository hosting, DNS, certificates, ZPA,
  firewall policy, production Postgres/Redis/object storage, backup policy,
  monitoring integration, and deployment approval remain explicit IT/security
  handoffs. Developer-owned contracts and local integration evidence continue.
