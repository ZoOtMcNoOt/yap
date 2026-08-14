# Governed Knowledge Maintainability Coverage

**Merged implementation base:**
`ae81ff067c73a64528eecc14403765562726f2fe`

**Inventory and review anchor:** `e2fff1f5b087cc05a549588ea41aae71a6806024`

**Inventory date:** 2026-08-10

This checkpoint reviews the whole active first-party repository through merged
Phase 9. Earlier phase and checkpoint acceptance is evidence, not an exemption.
The Phase 9 delta receives deeper inspection, but it is not the coverage limit.

The current read-back below extends the navigation and cohesion inventory
through all eight merged product boundaries. Auditor qualified at exact
executable `87924d5f...`; hosted source head `6bb72953...` passed all six CI jobs
reported for PR #183 and rebase-merged tree-identically with main tip
`13d9e3ef...`. The threshold inventory is recomputed against that merged tree
with this public documentation reconciliation applied. The tracked-path and
physical-line tables below remain the labeled merged Phase 9 inventory anchor; they are not
silently relabeled as current. This document does not claim a privately
qualified native/renderer round trip, knowledge activation, sustained capacity,
simultaneous full-profile residency, production SLOs, deployment, or production
promotion.

## Method and exclusions

The path partition comes from `git ls-files`. Physical line counts come from the
checked-out regular files. Generated build output, ignored `target*`,
`node_modules`, package caches, native `bin`/`obj`, binaries, model weights, and
private evidence are excluded. Tracked lockfiles, generated OpenAPI/schema
documents, and dependency inventory/notice JSON remain in the reproducibility
and provenance review but do not trigger hand-written decomposition by size.

Every active first-party area receives a breadth review. Deep review is required
for ambiguous or high-risk ownership, critical workflows and trust boundaries,
broad fan-in/fan-out, suspicious wrappers/generic helpers, high churn, and every
hand-written file at or above 250 lines. At 350 lines, retain only with a
concrete cohesion justification or decompose around a real owner.

## Tracked path partition

| Area | Tracked files | Coverage owner |
| --- | ---: | --- |
| Desktop frontend production | 144 | Architecture/comprehensibility reviewer; runtime reviewer for projected state boundaries |
| Desktop native source and inline tests | 463 | Runtime/ownership reviewer with architecture and assurance cross-review |
| Desktop dedicated tests | 156 | Architecture/comprehensibility and assurance reviewers |
| Desktop packaging, configuration, and assets | 40 | Assurance reviewer |
| Server production | 214 | All three reviewers by assigned lens |
| Server tests and fixtures | 207 | All three reviewers by assigned lens |
| Server contracts, runtime locks, and configuration | 73 | Runtime and assurance reviewers |
| Infrastructure | 12 | Runtime and assurance reviewers |
| Verification | 50 | Runtime/evidence and architecture reviewers |
| Hosted workflows and policy | 4 | Assurance reviewer |
| Documentation | 104 | Architecture/comprehensibility reviewer |
| Root product, dependency, provenance, and repository files | 21 | Assurance and architecture reviewers |
| **Total** | **1,488** | One consolidated controller |

The merged Phase 9 change from `10618e9d292e6810d6fee7defd7adc4902ecb2ed`
through `ae81ff067c73a64528eecc14403765562726f2fe` contains 106 paths: 30
knowledge-production modules, 13 agent/evaluation runtime modules, 15 knowledge
tests, 12 evaluation tests, 13 server contracts/configuration paths, four gate
scripts, 18 documents, and one hosted-workflow change.

## Physical-line baseline

These counts are navigation and change-cost measurements, not quality scores.
They include inline tests where the source file owns them and include tracked
text contracts/configuration; generated or machine-maintained inputs are called
out above rather than treated as refactor candidates.

| Domain | Files counted | Physical lines |
| --- | ---: | ---: |
| Desktop frontend | 143 | 16,370 |
| Desktop native source and inline tests | 477 | 109,240 |
| Desktop test harness | 146 | 26,801 |
| Server production | 214 | 64,840 |
| Server tests | 205 | 51,328 |
| Server contracts/runtime configuration | 29 | 6,729 |
| Verification tooling | 47 | 12,312 |
| Infrastructure | 2 | 1,131 |
| Hosted workflows | 4 | 1,372 |
| Documentation | 104 | 33,563 |
| Root/configuration/provenance text | 49 | 19,801 |

At the merged Phase 9 inventory anchor, the reproducible threshold screen found
494 tracked regular source, text, and policy surfaces at or above 250 lines: 259
at or above 350 and 235 from 250 through 349. The exact extension set, five
excluded generated/dependency
artifacts, disposition rules, and current output are owned by
`verification/list-maintainability-threshold-surfaces.ps1`. Review
disposition—not line count alone—decides whether each surface is cohesive,
historical, or needs repair.

## Executable ownership and dependency map

The detailed workflow map is
[Executable Ownership and Trust Boundaries](../../architecture/boundaries/EXECUTABLE-OWNERSHIP.md).
This checkpoint reconciles it through the merged Phase 9 owners below.

| Workflow or durable truth | Current owner | Required dependency direction |
| --- | --- | --- |
| Tray/island geometry and lifecycle | Native live window/runtime owners | React projects native state; it does not own a second window |
| Capture, immutable recording, gaps, and local fallback | Native audio coordinator/recording and `LiveRuntime` owners | UI commands adapt; model adapters do not own capture or durable truth |
| Language preference, local LID spans, and correction history | Native language preference/live-routing and job-ledger owners | Detectors emit evidence; ledger/session owners decide and persist |
| Imported source, preprocessing, remote job, retry, and result publication | Native job ledger/drain/remote owners plus server job service/store | Transport and models remain below durable job/result authority |
| Provider/model lifecycle | Native fallback runtime and server pool/provider runtime owners | Capability/route decisions select adapters; models do not own jobs |
| Authentication and owner identity | Server token validator, authorization context, and identity repository | Tenant/subject/purpose derive server-side; callers cannot choose them |
| Meeting evidence and result revisions | Server meeting-transcription result/reconciliation owners | Acoustic evidence remains separate from identity and History projection |
| Reviewed knowledge source admission | Reviewed capture/meeting knowledge owners | Only reviewed immutable inputs reach deterministic compilation |
| Terminology records and frozen job snapshots | Terminology authorization, ledger, and snapshot owners | Provider/grammar/OKF projections consume one identity-bound snapshot |
| OKF compilation and active generation | OKF compiler plus Postgres generation ledger | Compiler is deterministic; atomic ledger pointer is durable authority |
| Permission-safe retrieval and citations | Server-derived permission view plus Postgres retrieval owners | Filter/recheck precede return; model output never grants access |
| Knowledge proposals and tool audit | Proposal ledger and governed tool/audit owners | Answers/relationships remain cited noncanonical proposals until accepted |
| MCP/RAG agent access | Governed MCP/RAG adapters | Same bounded tool contracts; no raw repository/SQL/private evidence access |
| Agent workload selection | `agent_reasoning_routes.py` | Explicit class selects one route; no silent cross-route fallback |
| Agent model lifecycle and qualification evidence | Owned vLLM runtime/candidate runner and qualification owners | Immutable runtime observations flow into one fail-closed decision |
| Aggregate knowledge gate | Governed gate plus owned Postgres runtime | Gate owns disposable DB lifecycle and admits, but never republishes, private model evidence |
| Release/hosted evidence | Functional verification scripts and hosted workflow owners | Exact checked head and public-safe receipts precede merge claims |

## Critical end-to-end traces

The three reviews must collectively trace these paths rather than sampling files
in isolation:

1. microphone -> bounded capture -> immutable recording -> local ASR -> History;
2. imported source -> immutable spool -> preprocessing/LID -> upload/commit ->
   server inference -> verified result -> History;
3. token/discovery -> validated principal -> owner/purpose authorization ->
   REST/WSS/job access -> revocation/expiry/reconnect;
4. source-time meeting audio -> Tiron result -> immutable speaker/result revision
   -> one-speaker or speaker-attributed History projection;
5. reviewed result/document -> OKF compile -> staged generation -> permission
   view -> cited retrieval -> answer/proposal/MCP;
6. explicit workload class -> Qwen/Gemma route -> governed tools -> bounded
   final response -> cancellation/recovery/teardown evidence; and
7. frozen candidate -> local/private gate -> hosted exact-head checks -> merge
   -> documentation/status reconciliation.

## Review completion state

| Area | Breadth review | Deep review | Disposition |
| --- | --- | --- | --- |
| Desktop UI/native/local lifecycle | Complete across three lenses | Critical workflows and every threshold-triggered owner dispositioned; no Phase 9 desktop delta | No P0-P2; retain inherited local/offline boundary evidence |
| Durable client/server batch and preprocessing | Complete across three lenses | Job scheduling/result/cancel/restart owners | No P0-P2; retain `jobs/service.py` with aggregate-root cohesion justification |
| Identity/authorization/WSS | Complete across three lenses | Identity durable owner and adjacent trust seams | KAP-06 removes the obsolete development-schema migration; no tenant/subject/revocation defect found |
| Meeting evidence | Complete across three lenses | Result revision -> reviewed capture -> source admission -> compilation | KAP-02/KAP-03 remediations implemented; 17-test real-Postgres focus, independent re-review, and exact aggregate gate passed |
| Knowledge/terminology/retrieval | Complete across three lenses | Generation, permissions, retrieval, terminology, proposal, SQL lifecycle | KAP-01 through KAP-07 remediations implemented; 17-test real-Postgres focus, restart diagnostic, independent re-review, and exact aggregate gate passed |
| Agent runtime/evidence | Complete across three lenses | Tool/RAG/MCP, route selection, vLLM lifecycle, qualification, private admission | AR-01 through AR-11 and ARCH-03 remediations implemented; the self-protecting admission owner admitted the fresh exact-head Qwen/Gemma tree, and aggregate head `22c3f369...` passed; no fallback defect found |
| Packaging/CI/gates/provenance | Complete across three lenses | Locks, licenses, receipt boundaries, exact-head hosted workflow | No P0-P2; private/public evidence separation remains sound |
| Docs/ADRs/plans/runbooks/status | Complete across three lenses | Current/normative taxonomy and ownership navigation | Ownership/current docs reconciled, mixed test owner split, independent re-review, gate reconciliation passed, and hosted head `84c22ec9...` merged through PR #153 |

## Deletion and consolidation result

The checkpoint removed 546 lines of known duplicated or obsolete authority
before counting replacements: 286 lines of in-memory permission/retrieval code
and its duplicate behavioral test, 244 lines of evaluator-owned tool schemas and
validators, and 16 lines of obsolete identity-schema migration. The generic
proposal-hold table and mutation path were also deleted; unresolved proposals
now carry their own retention meaning and an authorized discard is the one
current disposition. The model-specific evidence publisher was removed and its
bounded behavior moved to a functional shared owner. New source-admission,
containment, cancellation, and adversarial tests make the overall checkpoint
net additive; no LOC-reduction claim is made for those correctness repairs.

## Retained cohesion decisions

### Complete threshold disposition

The previously recorded Phase 10 Student candidate snapshot remains historical:
527 in-scope surfaces at or above 250 physical lines, comprising 287 at or above
350 and 240 from 250 through 349. It is not recomputed against this successor.

Against merged main tip `13d9e3ef...`, with the current public documentation
reconciliation applied, the inventory contains 631 in-
scope tracked source, text, policy, and provenance surfaces at or above 250
physical lines: 377 at or above 350 and 254 from 250 through 349. The completed
checkpoint reviews remain the authority for their historical exact heads. This
freeze-time read-back retains the Auditor authenticated HTTP runner, native
request/connector owners, report composer, product gate, and affected
shared server/desktop owners. The mutually exclusive rows below classify every
one of the 377 decomposition-triggering surfaces. The exact path/line/disposition read-back is
recorded in [THRESHOLD-DISPOSITION.md](THRESHOLD-DISPOSITION.md); generated
OpenAPI, the package lock, dependency-inventory JSON, media, model artifacts,
caches, and build output remain excluded rather than disguised as cohesion
decisions.

| Exact path group | >=350 files | Disposition and concrete cohesion reason |
| --- | ---: | --- |
| `.github/workflows/*` | 2 | Retain the CI and release dependency DAGs as the two hosted policy owners. Jobs are already named by functional gate; extracting YAML fragments would hide exact-head ordering without removing authority. |
| `desktop/src-tauri/migrations/*` | 1 | Retain the single current job-ledger schema as one atomic durable-state definition; obsolete migration branches are forbidden and were removed where found. |
| `desktop/src-tauri/src/**` | 98 | Retain along existing functional module boundaries: app activation, audio session/coordinator, commands, job drain/ledger/remote state, language/live runtime, connector/auth, model adapters, trusted-source/correction revision, Librarian query/HTTP, Archivist ingestion/HTTP, Student request/HTTP, Curator proposal/HTTP, Analyst answer/HTTP, Coordinator bundle/HTTP, and Auditor report/HTTP owners each own one state machine or transaction family. Inline tests remain beside their private Rust owners. The product verticals add no second credential or knowledge authority. |
| `desktop/src-tauri/tests/*` | 2 | Retain the two integration owners for audio foundation and model-download lifecycle; each crosses native components deliberately and owns no production state. |
| `desktop/src/*` | 5 | Retain the application composer, live-overlay views, shared sidebar primitive, settings-control hook, and bounded Archivist action owner as separate UI owners; native projected state remains authoritative. |
| `desktop/tests/**` | 16 | Retain each functional E2E, WDIO, release-contract, inventory, or runner configuration owner, including the hand-written dependency-inventory script rather than its generated JSON products. These are scenario/gate compositions, not production authority; the mixed gate contracts already use named child boundaries. |
| Current/normative `docs/**` excluding completed/archived plans and research | 20 | Retain each ADR, current architecture/status, active decision queue, active production-promotion plan, runbook, spec, evidence/coverage record, and Voice OS document by taxonomy/decision owner. Stale current-state claims are repaired; these files are not executable modules. |
| `docs/plans/{archived,completed}/**` and `docs/research/**` | 12 | Retain as immutable historical delivery/evidence records, including the completed eight-agent roster plan. Rewriting or splitting them would damage provenance; current truth lives in current/normative documents. |
| `infra/**` | 5 | Retain each process-group, supervisor, loopback proxy, resident lifecycle, and setup owner because containment must remain end to end within its script/process boundary. |
| `server/librarian-workload-fixtures.json` | 1 | Retain the one frozen synthetic Librarian qualification corpus as a hand-maintained executable contract; it contains no private qualification output. |
| `server/README.md` | 1 | Retain the server runbook as the single operator navigation surface; executable gates and source modules remain authoritative. |
| `server/orchestrator/**` | 3 | Retain the supervisor as the provider-lifecycle owner, the admission scheduler as the bounded multi-user lease/fairness/capacity owner, and the hardware-independent integration suite as the end-to-end lifecycle contract. The frozen candidate derives rapid/complex active limits from immutable service profiles while preserving one active request per owner; configuration, protocol, dispatch, queue, terminal, and readiness concerns remain split across functional Rust modules. This is an ownership disposition, not capacity qualification. |
| `server/src/yap_server/auth/**` | 3 | Retain identity repository, token validation, and OIDC metadata as separate trust-boundary owners. The obsolete identity migration was deleted; no caller-chosen tenant/subject path remains. |
| `server/src/yap_server/evaluation/**` | 58 | Retain each named acceptance, corpus/review, scorer, runtime observation, lifecycle, qualification, and aggregate-decision owner. Librarian, Analyst, Coordinator, and Auditor keep their deterministic evaluation and exact-head gate owners separate; the Librarian, Archivist, Student, Curator, Analyst, Coordinator, and Auditor product gates separately own their authenticated HTTP composition proofs. Public decisions, database lifecycle, broker probes, and publication boundaries do not become request-time owners. |
| `server/src/yap_server/jobs/**` | 5 | Retain completion/store/runtime plus the single locked service aggregate. The 1,401-line service owns one `RLock`; pure policies may move only when they do not create a second job-state authority. |
| `server/src/yap_server/knowledge/**` | 6 | Retain generation ledger, source admission, tool contract, compiler, proposal, and Postgres retrieval by transaction/protocol boundary. The proposal owner enforces unresolved capacity, transaction-owned Curator publication, and Coordinator's owner-scoped current-lineage projection while remaining noncanonical; activation stays outside it. Individual high-change surfaces are itemized below. |
| `server/src/yap_server/lid/**` | 5 | Retain component lock, runtime/materialization, policy, and worker contract as the bounded acoustic-LID artifact/runtime decision family; selection and durable job state remain outside it. |
| `server/src/yap_server/live/**` | 2 | Retain protocol and WebSocket server as separate contract/admission owners; neither owns ASR jobs, identity, or external production transport. |
| `server/src/yap_server/meeting_transcription/**` | 3 | Retain container worker, immutable result-revision authority, and runtime provenance as distinct meeting execution/evidence owners; speaker naming remains outside scope. |
| `server/src/yap_server/pools/**` | 13 | Retain provider-neutral pool contracts, the exact agent-service profile reader, and provider-specific engine/client/service/scheduler boundaries. Each large file owns one runtime or request protocol; no universal fallback/router was reintroduced. |
| Other `server/src/yap_server/**` | 27 | Retain the HTTP application plus product-job owners and the eight role semantic/lifecycle/audit owners as separate routing, validation, transport, persistence, and workflow boundaries. Librarian query, Archivist ingestion, Student question, Curator proposal, Analyst answer, Coordinator bundle, and Auditor report jobs compose existing cores without moving identity, evidence, recording-result, question, answer, bundle, report, citation, proposal, or knowledge authority into HTTP. |
| `server/tests/{auth,capabilities,contract}/**` | 6 | Retain by trust/contract owner; these suites intentionally enumerate adversarial token, metadata, catalog, public-contract, and OpenAPI cases. |
| `server/tests/evaluation/**` | 30 | Retain one suite per corpus/runtime/qualification/evidence owner. Librarian, Analyst, Coordinator, Auditor, Archivist, Student, and Curator product decision tests remain separate from their exact gates because only each gate owns subprocess, database, broker, HTTP composition, publication, and teardown orchestration. |
| `server/tests/infra/**` | 4 | Retain end-to-end process/proxy/lifecycle harnesses because their failure cases span subprocess boundaries while production owners stay in `infra/`. |
| `server/tests/jobs/**` | 8 | Retain suites by runtime, commit admission, contract, meeting result, processing, restart, recovery, and retention workflow. They share fixtures, not production state. |
| `server/tests/knowledge/**` | 5 | Retain the compiler, proposal-authority contract, and three real-Postgres integration owners. Each is itemized below and the database lane requires every test with zero skips. |
| `server/tests/{lid,live,model_pools,pools}/**` | 9 | Retain by component/runtime owner; these are bounded lifecycle, protocol, scheduler, client, and server-composition integration suites inherited from reviewed earlier phases or extended by the Curator product boundary. |
| Other `server/tests/**` | 18 | Retain Scribe, Archivist, Student, Curator, Librarian, Analyst, Coordinator, and Auditor semantic/lifecycle/PostgreSQL suites beside their production owners. Archivist separates reviewed-source semantics, product job composition, and real-Postgres authority behavior. |
| `verification/**` | 9 | Retain each functional aggregate runner, hosted-closure, private-evidence, product-checkpoint, meeting-evidence, OIDC-owner/flow, and checkout verifier. They compose existing children and publish no product state. |

This grouped inventory is exhaustive for the threshold at this tree, while the
following individual decisions make the most coupled or changed owners directly
navigable.

| Surface | Lines after remediation | Concrete owner justification |
| --- | ---: | --- |
| `desktop/src-tauri/src/archivist_ingestion.rs` | 403 | One native Archivist product aggregate binds a local recording identity to the durable remote job/result, owns one connector lease, monotonic staging state, cancellation, terminal retention, restart read-back, and quit containment; React never gains bearer or source-path authority. |
| `desktop/src-tauri/src/server_connector/archivist.rs` | 430 | One strict authenticated HTTP client owns the bounded Archivist create/status/cancel wire, response-size and identity validation, and typed error projection; token acquisition, durable recording truth, and UI state remain separate owners. |
| `desktop/src-tauri/src/jobs/commands/catalog.rs` | 389 | One native recording-catalog command owner projects durable jobs/results and local source identity to the UI and Archivist owner. It does not stage knowledge or acquire credentials. |
| `desktop/src/components/panels/transcript-panel.tsx` | 365 | One transcript presentation owner renders playback/copy/reveal plus the bounded knowledge-staging state supplied by the Archivist hook; native projections remain authoritative and the panel performs no transport. |
| `server/src/yap_server/agents/archivist_service.py` | 424 | One internal BACKGROUND_IO workflow owns the source-bound Server-IO lease, deterministic compile/stage lifecycle, typed failures, cancellation, and containment without accepting raw caller bytes or activating knowledge. |
| `server/src/yap_server/agents/archivist_ingestion_service.py` | 464 | One bounded asynchronous product-job owner resolves authenticated durable recording results into reviewed captures, owns create/status/cancel and terminal retention, and delegates compilation to the existing Archivist core without creating a second source or knowledge authority. |
| `server/src/yap_server/evaluation/archivist_product_qualification_gate.py` | 2,128 | One exact-head private product gate owns clean candidate admission, authenticated threaded HTTP composition, source-bound Server-IO lease evidence, owned PostgreSQL restart/read-back, replay/isolation/drift/cancellation proofs, public-safe create-once evidence, and exact teardown. |
| `server/tests/agents/test_archivist.py` | 380 | One internal semantic/lifecycle suite protects reviewed-capture identity, deterministic compilation/staging, idempotent replay, cancellation, and no-activation behavior without duplicating product HTTP orchestration. |
| `server/tests/evaluation/test_archivist_product_qualification_gate.py` | 567 | One gate suite protects acceptance/candidate closure, HTTP auth/isolation, exact canonical source derivation, source-bound lease/cardinality evidence, private/public receipt shape, restart read-back, and teardown. |
| `server/tests/contract/contract_http_values.py` | 653 | One public HTTP contract registry enumerates operation IDs, capability fields, examples, runtime modes, schema names, and route paths for generated/spec drift detection; it owns no request execution. |
| `server/tests/contract/test_examples_contract.py` | 380 | One OpenAPI/example contract suite proves capabilities, errors, examples, and schemas stay mutually consistent, including the product feature flags and strict request/result shapes. |
| `server/tests/jobs/test_runtime.py` | 1,056 | One runtime-composition suite spans the existing server modes and their fail-closed configuration matrices; service semantics remain in their dedicated owners and the suite creates no runtime fallback. |
| `verification/mock-oidc-owner-flow.py` | 378 | One standalone synthetic OIDC owner-flow verifier exercises the existing mock-provider token lifecycle without becoming a production identity adapter or storing credentials. |
| `desktop/src-tauri/src/librarian_query.rs` | 393 | One native Librarian request owner binds authenticated connector leases, monotonic query state, cancellation, terminal retention, capability/generation fencing, and shutdown containment without moving bearer or evidence authority into React. |
| `desktop/src-tauri/src/server_connector/librarian.rs` | 516 | One strict native HTTP client owns the bounded Librarian request/result wire, response-size limit, span/content validation, and independent evidence-hash recomputation; credential acquisition and UI state remain separate owners. |
| `server/src/yap_server/api/app.py` | 543 | One HTTP application composition root installs authenticated job, correction, capability, Librarian query, Archivist ingestion, Student question, Curator proposal, Analyst answer, Coordinator bundle, and Auditor report routes and owns startup/shutdown ordering; each protocol handler and runtime remains in its functional module. |
| `server/src/yap_server/jobs/service.py` | 1,401 | One `RLock` protects the server job aggregate: scheduling, cancellation, result publication, and recovery must not acquire a second state owner. Extract only pure policies if a future change establishes a real seam. |
| `desktop/src-tauri/src/server_connector/transcript_correction.rs` | 498 | One strict authenticated HTTP client owns the bounded correction wire request/status/error projection. Credential acquisition remains in the connector dispatcher and source/publication authority remains in native Scribe owners. |
| `desktop/src-tauri/src/transcript_correction/mod.rs` | 446 | One native request aggregate owns trusted-source admission, connector lease lifetime, monotonic server-state projection, cancellation, bounded terminal retention, and explicit publication dispatch. Source and revision mechanics are already separate modules. |
| `desktop/src-tauri/src/transcript_correction/revision.rs` | 828 | One hash-chained correction-revision owner validates source identity before/after publication, serializes user acceptance, and couples deletion to the existing live/remote source lifecycle. Splitting the write/read/delete invariants would create competing derivative authority. |
| `server/src/yap_server/agents/transcript_correction.py` | 1,136 | One Scribe semantic contract owns segment/request/edit/response schema, source hashes, bounded edit application, protected-fact preservation, exact authorized terminology replacement, and raw/corrected projection. Scheduling, model transport, persistence, and HTTP remain separate owners. |
| `server/src/yap_server/agents/transcript_correction_model.py` | 440 | One bounded model adapter owns protected-source masking, exact request binding, forced one-candidate (`n=1`) structured generation, response parsing, no-op removal, protected-value restoration, and shortest raw whole-token edit-context normalization before the independent semantic validator. It does not own scheduling, persistence, or publication. |
| `server/src/yap_server/agents/transcript_correction_service.py` | 754 | One bounded asynchronous lifecycle owns submit/status/cancel, broker lease, worker containment, queue-inclusive deadline, 64 in-flight and 256 terminal limits, and typed terminal disposition. The semantic validator and model client remain separate. |
| `server/src/yap_server/evaluation/transcript_correction_corpus.py` | 448 | One private corpus admission owner validates exact source-evidence membership, immutable reviewed dispositions, authorized terminology mappings, owner/language/case diversity, and source/reference integrity without executing a model or publishing private content. |
| `server/src/yap_server/evaluation/transcript_correction_qualification.py` | 775 | One qualification decision synchronizes distinct owners through one warm generation, records every case/wave, recomputes correction/safety/latency/disposition metrics, and fails closed on containment or lifecycle drift. Corpus/source admission and aggregate orchestration remain separate. |
| `server/src/yap_server/evaluation/transcript_correction_qualification_gate.py` | 425 | One exact-head aggregate composes source-evidence admission, public contracts, protected shared admission/profile owners, Rust/desktop/server children, warm-route qualification, teardown, and create-once public-safe publication. It does not own model/service mutation or claim successor qualification. |
| `server/src/yap_server/evaluation/transcript_correction_source_evidence.py` | 447 | One private source-evidence admission boundary binds exact public plan/release/model hashes, private file identity, membership, language, candidate route, and privacy-safe result shape without disclosing source paths or transcript content. |
| `server/tests/agents/test_transcript_correction.py` | 605 | One semantic-contract suite covers source/request identity, protected facts, exact authorized terminology application, model-edit composition, raw fallback, ordering, coverage, and correction projection without owning scheduling or persistence. |
| `server/tests/agents/test_transcript_correction_model.py` | 563 | One adapter suite covers strict response shape/bounds, exact one-candidate generation, request binding, protected masking/restoration, no-op removal, shortest unique context, and failure behavior without duplicating the semantic validator. |
| `server/tests/agents/test_transcript_correction_service.py` | 778 | One lifecycle suite covers multi-owner admission, overload, deadline, cancellation acknowledgement, model/terminology failures, no-op/uncertain/invalid distinctions, containment fencing, and bounded retention against the service owner. |
| `server/tests/evaluation/test_transcript_correction_qualification.py` | 1,137 | One acceptance suite covers eight-owner synchronized waves, duplicate-owner rejection, warm-generation identity, real-ASR source membership, authorized correction/safety bounds, invalid fallback false-pass prevention, latency, and teardown. |
| `server/src/yap_server/agents/librarian.py` | 428 | One no-LLM semantic owner validates the bounded request and permission-safe generation-pinned evidence pack. Admission, lifecycle, and durable audit remain separate. |
| `server/src/yap_server/agents/librarian_service.py` | 760 | One Server-IO workflow owner covers admission, queue-inclusive deadlines, cancellation acknowledgement, containment, typed terminal results, and audit handoff without acquiring a model lease. |
| `server/src/yap_server/agents/librarian_result_audit.py` | 446 | One immutable content-free terminal ledger owns Librarian outcome identity without storing evidence text or writing proposals. |
| `server/src/yap_server/evaluation/librarian_qualification.py` | 1,860 | One deterministic public qualification owner binds the frozen synthetic corpus, exact evidence expectations, hidden/revocation/stale/cancel outcomes, synchronized owner wave, and bounded p95 decision. |
| `server/src/yap_server/evaluation/librarian_qualification_gate.py` | 1,139 | One exact-head private gate owns checked input admission, Server-IO broker probing, owned PostgreSQL restart/read-back, exact audits, create-once owner-private publication, and teardown. |
| `server/tests/evaluation/test_librarian_qualification.py` | 762 | One public decision suite protects exact corpus binding, all-eight normal-owner broker entry, hidden-data equivalence, terminal counts, and false-pass prevention. |
| `server/tests/evaluation/test_librarian_qualification_gate.py` | 485 | One gate suite protects clean-head/private-destination admission, broker containment, database read-back, exact audit/publication semantics, and fail-closed evidence creation. |
| `server/src/yap_server/evaluation/librarian_product_qualification_gate.py` | 1,669 | One product-boundary gate composes strict bearer authentication, real threaded HTTP requests, Server-IO admission, owned PostgreSQL restart/read-back, exact evidence and audit validation, owner isolation, cancellation/deadline controls, public-safe receipt creation, and teardown without claiming native/renderer execution. |
| `server/tests/evaluation/test_librarian_product_qualification_gate.py` | 439 | One focused gate suite protects acceptance/candidate closure, strict response parsing, HTTP auth and isolation probes, cancellation/deadline containment, public evidence shape, and the bounded nonempty candidate-input invariant. |
| `server/src/yap_server/agents/analyst.py` | 398 | One Analyst semantic owner validates bounded questions, Librarian lineage, current-generation authorization, whole-item evidence selection, server-derived answers/citations, request/work/evidence identities, and fail-closed unavailable results. Admission, model transport, workflow lifecycle, and durable audit remain separate. |
| `server/src/yap_server/agents/analyst_result_audit.py` | 754 | One immutable content-free terminal ledger binds Analyst request, Librarian lineage, evidence, answer/citation, provider, authorization, and runtime identities without storing answer or evidence bytes or writing proposals. |
| `server/src/yap_server/agents/analyst_service.py` | 905 | One interactive workflow owner composes Librarian retrieval, in-transaction current-generation reauthorization, complex-route admission, bounded model selection, queue-inclusive deadline, cancellation acknowledgement, containment, exact replay, and terminal auditing. Semantic validation, model transport, and persistence owners remain distinct. |
| `server/src/yap_server/evaluation/analyst_qualification.py` | 1,397 | One deterministic qualification owner binds the frozen corpus-v4 and acceptance plan, runs three synchronized repeat waves plus controlled failures, independently derives server-owned answers/citations, and emits only bounded public counts and booleans. It does not own private runtime orchestration. |
| `server/src/yap_server/evaluation/analyst_qualification_gate.py` | 1,522 | One exact-head private gate owns protected candidate/profile admission, independent render/compile/bind, live complex c8/ninth-owner-queued probing, two PostgreSQL restart/read-backs, exact Analyst/Librarian/tool audits, provider/broker invariance, create-once owner-private publication, and teardown. |
| `server/tests/agents/test_analyst_result_audit.py` | 686 | One durable-audit suite protects immutable identity, content-free storage, replay/conflict, cross-owner, and terminal-row invariants without duplicating service or qualification orchestration. |
| `server/tests/agents/test_analyst_service.py` | 521 | One lifecycle suite covers Librarian composition, current-generation reauthorization, complete/unavailable outcomes, exact replay, cross-owner isolation, model and admission failures, cancellation/deadline containment, and content-free auditing. |
| `server/tests/evaluation/test_analyst_qualification.py` | 422 | One decision suite protects the three exact synchronized repeat waves, frozen answer/citation oracle, terminal counts, controlled failures, and false-pass prevention without owning private infrastructure. |
| `server/tests/evaluation/test_analyst_qualification_gate.py` | 486 | One gate suite protects candidate-input closure, batch-invariant profile arguments, live c8/ninth-queued admission, database/audit lineage, provider/broker identity, create-once private evidence, and teardown. |
| `server/src/yap_server/agents/analyst_answer_service.py` | 308 | One bounded asynchronous Analyst product-job owner generates public request IDs, retains active and terminal jobs, projects exact qualified-core answers, and contains cancellation/shutdown without creating a second evidence, answer, citation, or audit authority. |
| `server/src/yap_server/evaluation/analyst_product_qualification_gate.py` | 1,797 | One exact-head private product gate owns clean candidate admission, authenticated threaded HTTP composition, independent compiler-bound Analyst expectations, complex-c8/ninth-owner-queued probing, two PostgreSQL restart/read-backs, exact Analyst/Librarian/tool audit identities, owner isolation, HTTP cancellation, public-safe create-once evidence, and teardown without claiming native/renderer execution. |
| `server/tests/evaluation/test_analyst_product_qualification_gate.py` | 512 | One gate suite protects product acceptance/candidate closure, strict authenticated wire parsing, owner isolation, exact answer/citation binding, controlled cancellation, database/audit arithmetic, privacy-safe receipt shape, and fail-closed create-once publication. |
| `desktop/src-tauri/src/analyst_answer.rs` | 399 | One native Analyst product aggregate owns a single authenticated connector lease, monotonic answer-request state, cancellation, terminal retention, connector fencing, exact cited-answer validation, and quit containment without exposing bearer material or granting React citation authority. |
| `desktop/src-tauri/src/server_connector/analyst.rs` | 524 | One strict native HTTP client owns Analyst create/status/cancel transport, exact answer/citation/span/content validation, response bounds, and typed error projection; token acquisition, evidence authority, and UI state remain separate owners. |
| `desktop/src-tauri/src/coordinator_bundle.rs` | 416 | One native Coordinator product aggregate owns a single authenticated connector lease, monotonic bundle-request state, cancellation, terminal retention, connector fencing, exact bundle/citation validation, and quit containment without exposing bearer material or granting React proposal authority. |
| `desktop/src-tauri/src/server_connector/coordinator.rs` | 596 | One strict native HTTP client owns Coordinator create/status/cancel transport, exact bundle/item/citation validation, response bounds, and typed error projection; token acquisition, proposal authority, and UI state remain separate owners. |
| `server/src/yap_server/agents/coordinator.py` | 753 | One Coordinator semantic owner validates bounded explicit requests, owner-scoped Curator candidates, exact current citation and lineage bindings, selection-only noncanonical review-required bundles, canonical hashes, and bundle wire shape. Admission, model transport, proposal reading, and persistence remain separate. |
| `server/src/yap_server/agents/coordinator_result_audit.py` | 688 | One immutable content-free terminal ledger reauthorizes the complete current evidence pack and binds Coordinator request, work, evidence, bundle/citation, provider, authorization, Curator lineage, and runtime identities without storing objective, proposal, citation, or model-output bytes. |
| `server/src/yap_server/agents/coordinator_service.py` | 885 | One background complex-route workflow owns a single broker lease, current-evidence read and revalidation, bounded selection, queue-inclusive deadlines, exact cancellation acknowledgement, containment, typed terminal results, and audit handoff without invoking another role service or publishing a proposal. |
| `server/src/yap_server/evaluation/coordinator_qualification.py` | 1,726 | One deterministic qualification owner binds the frozen synthetic corpus-v2 and acceptance plan, runs three synchronized repeat waves plus controlled failures, independently derives exact server-owned bundles and citations, and emits only bounded public counts and booleans. Private infrastructure remains in the gate. |
| `server/src/yap_server/evaluation/coordinator_qualification_gate.py` | 1,926 | One exact-head private gate owns protected candidate admission, independent render/compile/bind, production Curator-lineage seeding, live complex c8/ninth-owner-queued probing, two PostgreSQL restart/read-backs, exact admission and audit cardinality, unchanged provider/broker identity, create-once owner-private publication, and teardown. |
| `server/tests/agents/test_coordinator.py` | 424 | One semantic-contract suite protects strict request/evidence/candidate/bundle fields, canonical hashes, server-owned selection order and citations, noncanonical review-required output, and forged or stale binding rejection without duplicating lifecycle or persistence. |
| `server/tests/agents/test_coordinator_result_audit.py` | 442 | One durable-audit suite protects content-free exact identity, current-evidence reauthorization, Curator lineage, replay/conflict, commit recovery, cancellation/deadline bounds, and fail-closed bundle validation. |
| `server/tests/agents/test_coordinator_service.py` | 553 | One lifecycle suite covers the single-lease invariant, complete/unavailable outcomes, invalid selection, stale authority, provider/runtime failures, deadline and cancellation acknowledgement, exact terminal auditing, and worker containment. |
| `server/tests/agents/test_coordinator_postgres.py` | 438 | One real-PostgreSQL authority owner covers owner-scoped current proposal reads, hidden/foreign/stale suppression, exact Curator lineage and citation rebinding, shared/exclusive advisory-lock ordering, and terminal audit interleavings. |
| `server/tests/evaluation/test_coordinator_qualification.py` | 476 | One decision suite protects the three exact synchronized repeat waves, frozen bundle/citation oracle, terminal arithmetic, hidden/absent equivalence, controlled failures, actual service-call cardinality, and false-pass prevention. |
| `server/tests/evaluation/test_coordinator_qualification_gate.py` | 872 | One gate suite protects complete candidate-source closure, full complex profile, live c8/ninth-queued admission, production Curator lineage, exact 29-ticket lifecycle and database/audit cardinality, private/public receipt separation, restart read-back, and teardown. |
| `server/src/yap_server/evaluation/coordinator_product_qualification_gate.py` | 1,937 | One exact-head private product gate owns checked candidate admission, authenticated threaded HTTP composition, independent Coordinator bundle expectations, Curator lineage, complex-c8/ninth-owner-queued probing, two PostgreSQL restart/read-backs, exact product/core/audit identity, owner isolation, cancellation, public-safe create-once evidence, and teardown without claiming native/renderer execution. |
| `server/tests/evaluation/test_coordinator_product_qualification_gate.py` | 532 | One gate suite protects product acceptance/candidate closure, strict authenticated wire parsing, owner isolation, exact bundle/citation binding, controlled cancellation, database/audit arithmetic, privacy-safe receipt shape, and fail-closed create-once publication. |
| `server/src/yap_server/agents/auditor.py` | 833 | One Auditor semantic owner validates bounded explicit requests, current permission-safe evidence, unique source items, canonical evidence-pair ordering, server-derived noncanonical review-required findings/citations, exact hashes, and report wire shape. Admission, model transport, retrieval, and persistence remain separate. |
| `server/src/yap_server/agents/auditor_result_audit.py` | 694 | One immutable content-free terminal ledger reauthorizes the complete current evidence pack and binds Auditor request, work, evidence, report/citation, provider, authorization, and runtime identities without storing focus, evidence, finding, citation, or model-output bytes. |
| `server/src/yap_server/agents/auditor_service.py` | 871 | One idle-only complex-route workflow owns a single broker lease, current-evidence read and revalidation, bounded pair selection, queue-inclusive deadlines, exact cancellation acknowledgement, containment, typed terminal results, and audit handoff without invoking another role service or mutating knowledge. |
| `server/src/yap_server/evaluation/auditor_qualification.py` | 1,535 | One deterministic qualification owner binds the frozen synthetic corpus and acceptance plan, runs three synchronized repeat waves plus controlled failures, independently derives exact server-owned reports and citations, and emits only bounded public counts and booleans. Private infrastructure remains in the gate. |
| `server/src/yap_server/evaluation/auditor_qualification_gate.py` | 1,832 | One exact-head private gate owns protected candidate admission, independent render/compile/bind, live idle-only active/pending blocking and resumption, complex c8/ninth-owner-queued probing, two PostgreSQL restart/read-backs, exact admission and audit cardinality, unchanged provider/broker identity, create-once owner-private publication, and teardown. |
| `server/tests/agents/test_auditor_service.py` | 525 | One lifecycle suite covers the single idle-only lease invariant, complete/unavailable outcomes, invalid selection, stale authority, provider/runtime failures, deadline and cancellation acknowledgement, exact terminal auditing, and worker containment. |
| `server/tests/evaluation/test_auditor_qualification.py` | 449 | One decision suite protects the three exact synchronized repeat waves, frozen report/citation oracle, terminal arithmetic, hidden/absent equivalence, controlled failures, actual service-call cardinality, and false-pass prevention. |
| `server/tests/evaluation/test_auditor_qualification_gate.py` | 744 | One gate suite protects complete candidate-source closure, full complex profile, live idle-only and c8/ninth-queued admission probes, exact 29-ticket lifecycle and database/audit cardinality, private/public receipt separation, restart read-back, and teardown. |
| `desktop/src-tauri/src/auditor_report.rs` | 398 | One native Auditor product aggregate owns a single authenticated connector lease, monotonic report-request state, cancellation, terminal retention, connector fencing, exact report/finding/citation validation, and quit containment without exposing bearer material or granting React semantic authority. |
| `desktop/src-tauri/src/server_connector/auditor.rs` | 570 | One strict native HTTP client owns Auditor create/status/cancel transport, exact report/finding/citation/span validation, response bounds, and typed error projection; token acquisition, evidence authority, and UI state remain separate owners. |
| `server/src/yap_server/agents/auditor_report_service.py` | 318 | One bounded asynchronous Auditor product-job owner generates public request IDs, retains active and terminal jobs, projects exact qualified-core reports, and contains cancellation/shutdown without creating a second evidence, finding, citation, or audit authority. |
| `server/src/yap_server/evaluation/auditor_product_qualification_gate.py` | 1,797 | One exact-head private product gate owns checked candidate admission, authenticated threaded HTTP composition, independent Auditor report expectations, complex-c8/ninth-owner-queued probing, two PostgreSQL restart/read-backs, exact product/core/audit identity, owner isolation, cancellation, public-safe create-once evidence, and teardown without claiming native/renderer execution. |
| `server/tests/evaluation/test_auditor_product_qualification_gate.py` | 660 | One gate suite protects product acceptance/candidate closure, strict authenticated wire parsing, owner isolation, exact report/finding/citation binding, controlled cancellation, database/audit arithmetic, privacy-safe receipt shape, and fail-closed create-once publication. |
| `desktop/src-tauri/src/server_connector/student.rs` | 503 | One strict native HTTP client owns Student create/status/cancel transport, exact request/status/question/citation/span validation, response bounds, and typed error projection; token acquisition, source authority, and UI state remain separate owners. |
| `desktop/src-tauri/src/student_question.rs` | 407 | One native Student product aggregate owns a single connector lease, monotonic request state, cancellation, terminal retention, connector fencing, and quit cleanup without exposing bearer material or granting React citation authority. |
| `server/src/yap_server/agents/student_question_service.py` | 376 | One bounded asynchronous product-job owner generates request IDs, retains active/terminal jobs, projects exact qualified-core results, and contains cancellation/shutdown without creating a second Student semantic, evidence, or audit authority. |
| `server/src/yap_server/evaluation/student_product_qualification_gate.py` | 2,204 | One exact-head private product gate owns checked candidate admission, authenticated HTTP composition, independent compiled Student evidence, rapid-c4/fifth-queued probing, two PostgreSQL restart/read-backs, exact product/internal/audit binding, owner isolation, cancellation, public-safe create-once evidence, and teardown without claiming native/renderer execution. |
| `server/tests/evaluation/test_student_product_qualification_gate.py` | 654 | One gate suite protects acceptance/candidate closure, terminal polling, HTTP auth/isolation, compiled evidence binding, rapid-route capacity, exact audit/read-back cardinality, teardown vocabulary, public receipt shape, and fail-closed evidence creation. |
| `server/src/yap_server/agents/student.py` | 430 | One Student source contract owns the versioned request, permission-safe conversation evidence read, exact evidence/request/work identities, and read audit. Model generation, broker lifecycle, and terminal persistence remain separate. |
| `server/src/yap_server/agents/student_model.py` | 513 | One bounded Student model contract exposes ordered evidence text, forces one candidate (`n=1`), accepts exactly one evidence index, source subject, and support quote, requires an exact subject-inside-quote-inside-evidence chain without topic copying, binds the selected canonical evidence and server-owned citation identity, derives the support span, enforces exact source boundaries, and renders the deterministic question. It owns no database, lease, or product publication state. |
| `server/src/yap_server/agents/student_service.py` | 680 | One Student workflow lifecycle owns queue admission, queue-inclusive deadline, cancellation acknowledgement, exact rapid-route lease, validated result publication, and redacted terminal audit. Evidence retrieval and model semantics remain independent owners. |
| `server/src/yap_server/evaluation/student_qualification.py` | 652 | One Student decision synchronizes distinct owners, independently revalidates exact compiled evidence selection and source grounding, recomputes term/latency checks, observes the unchanged warm provider and broker, and publishes no question text in public evidence. The aggregate gate owns database/runtime orchestration. |
| `server/src/yap_server/evaluation/student_qualification_gate.py` | 871 | One exact-head Student aggregate owns full-profile admission, a live rapid-route capacity-four/fifth-owner-queued probe, ordered multi-item compiled evidence, temporary reviewed knowledge, per-case evidence-read counts, real PostgreSQL restart/cross-owner/audit verification, unchanged warm provider/broker identities, exact probe/runtime/database containment, and create-once private publication. It never launches, swaps, or reduces the Qwen service. |
| `server/tests/agents/test_student.py` | 842 | One Student contract/lifecycle suite covers exact-one response shape and candidate count, prompt grounding, index bounds, request/evidence identity, hidden-source rejection, exact Unicode and numeric subject boundaries, server-owned citation binding, queueing, cancellation, containment, and terminal audit without duplicating PostgreSQL integration. |
| `server/tests/evaluation/test_student_qualification.py` | 394 | One Student decision test owner rejects always-first and always-last evidence selection across the frozen two-direction multi-item corpus, forged citation/source identity, disconnected support, wrong terms, lifecycle drift, and owner-wave defects without duplicating aggregate PostgreSQL orchestration. |
| `server/tests/evaluation/test_student_qualification_gate.py` | 343 | One Student aggregate-gate contract owner protects runtime/storage/broker inputs, rejects throttled rapid profiles, freezes the live four-owner/fifth-queued capacity evidence, and covers exact evidence-read counts, database restart, teardown, public-safe projection, and create-once private destinations. |
| `server/tests/agents/test_student_postgres.py` | 380 | One real-PostgreSQL Student integration owner covers exact active-generation reads, cross-owner invisibility, stale-generation rejection, cancellation, and audit isolation through the production evidence owner. |
| `desktop/src-tauri/src/curator_proposal.rs` | 456 | One native Curator product aggregate owns a single authenticated connector lease, monotonic proposal-request state, cancellation, terminal retention, connector fencing, and quit containment without exposing bearer material or granting React proposal authority. |
| `desktop/src-tauri/src/server_connector/curator.rs` | 790 | One strict native HTTP client owns Curator create/status/cancel transport, exact request/result/proposal/citation validation, response bounds, and typed error projection; credential acquisition and semantic authority remain separate owners. |
| `server/src/yap_server/agents/curator_proposal_service.py` | 370 | One bounded asynchronous product-job owner generates public request IDs, retains active and terminal jobs, projects exact qualified-core results, and contains cancellation/shutdown without creating a second Curator semantic, evidence, proposal, or audit authority. |
| `server/src/yap_server/evaluation/curator_product_qualification_gate.py` | 1,863 | One exact-head private product gate owns checked candidate admission, authenticated threaded HTTP composition, independent Curator evidence binding, complex-c8/ninth-owner-queued probing, two PostgreSQL restart/read-backs, exact product/internal/proposal/audit identity, owner isolation, cancellation, public-safe create-once evidence, and teardown without claiming native/renderer execution. |
| `server/tests/evaluation/test_curator_product_qualification_gate.py` | 327 | One gate suite protects acceptance and candidate closure, strict bearer/owner isolation, product-to-durable request binding, capacity and cancellation evidence, exact restart/read-back arithmetic, public receipt privacy, and fail-closed create-once publication. |
| `server/src/yap_server/agents/curator.py` | 724 | One Curator request/evidence contract owns the versioned `explicit-proposal` and `reviewed-student-answer` triggers, bounded nonoverlapping citations, exact Student-question lineage, permission-safe server re-read, generation/evidence/work identities, and read audit. Model review, broker lifecycle, proposal persistence, and terminal result persistence remain separate owners. |
| `server/src/yap_server/agents/curator_model.py` | 234 | One bounded Curator model contract revalidates server-owned evidence, verifies the exact rendered-input token count, forces one nonparallel tool call and one candidate (`n=1`), and accepts only `propose` or `reject`. It cannot author content, select citations, read hidden data, retry, or publish. |
| `server/src/yap_server/agents/curator_publisher.py` | 192 | One atomic publication owner re-reads the exact evidence inside the caller-owned PostgreSQL transaction, stores one noncanonical proposal, and writes knowledge-tool plus terminal-success audits together. Cancellation/deadline containment wraps the database operation; canonical activation remains outside it. |
| `server/src/yap_server/agents/curator_result_audit.py` | 379 | One durable terminal-result owner binds request/submission, evidence, provider, proposal, authorization, and runtime-audit identities; unique replay and the caller-owned transaction seam keep successful proposal publication atomic with its terminal audit. It does not mutate proposals or canonical knowledge. |
| `server/src/yap_server/agents/curator_runtime.py` | 160 | One team-only runtime composer binds explicit `warm_gemma` mode, absolute owner-controlled paths, the exact complex profile/candidate lock, broker transport, bounded vLLM client, private PostgreSQL factory, and distinct evidence/model/publisher/audit/service owners. It neither launches nor swaps the provider. |
| `server/src/yap_server/agents/curator_service.py` | 899 | One explicit-submission lifecycle owns durable replay, the complex-route broker lease, one evidence read and one model review, queue-inclusive deadline, cancellation acknowledgement, containment, typed terminal disposition, and dispatch to atomic noncanonical publication. Semantic validation, model transport, persistence, and active-knowledge authority remain separate. |
| `server/src/yap_server/evaluation/curator_qualification.py` | 740 | One Curator qualification decision loads the frozen acceptance/corpus, synchronizes eight distinct owners, independently validates exact evidence and one proposal-or-rejection result per case, observes unchanged warm provider/broker identities, and emits only bounded public-safe counts and booleans. The aggregate gate owns runtime/database mutation and private publication. |
| `server/src/yap_server/evaluation/curator_qualification_gate.py` | 1,422 | One exact-head Curator aggregate owns candidate/profile admission, the live complex-route capacity-eight/ninth-owner-queued probe, temporary reviewed knowledge, two real PostgreSQL restart boundaries, replay/conflict/cross-owner/atomic-audit checks, provider/broker observation, exact probe/runtime/database containment, and create-once private evidence publication. Exact head `7cd24deb...` qualified this workflow; the module itself and later changes do not extend that claim. |
| `server/tests/agents/test_curator.py` | 1,065 | One Curator semantic/lifecycle suite covers both explicit triggers, exact Student lineage and citations, one forced model decision, exact empty-or-null no-prose envelopes, publish-once behavior, rejection/invalid-output no-publish behavior, durable replay, queueing, deadlines, cancellation races, capacity failure, terminal audit, and containment without duplicating real-PostgreSQL orchestration. |
| `server/tests/agents/test_curator_postgres.py` | 423 | One real-PostgreSQL Curator owner covers exact evidence and atomic proposal/result-audit publication, restart replay, cross-owner isolation, transaction rollback on audit failure, and exact unresolved-capacity/idempotent-retry/discard release behavior. |
| `server/tests/agents/test_curator_runtime.py` | 103 | One runtime-wiring suite proves fail-closed mode/path/profile admission, organization-authentication enforcement, and exact already-warm Gemma complex-profile identity without starting or mutating a provider. |
| `server/tests/evaluation/test_curator_qualification.py` | 364 | One decision-level Curator suite freezes both triggers, prevents acceptance from reducing input/output/broker capacity, exercises the exact eight-owner wave without public content, rejects wrong decisions or evidence, and proves timeout cancellation/worker containment. |
| `server/tests/evaluation/test_curator_qualification_gate.py` | 434 | One aggregate-gate contract owner protects runtime/storage/capacity inputs, rejects throttled complex profiles, validates source-bound compiled evidence and empty-state preflight, and freezes two database restarts, exact teardown, public-safe receipt shape, and create-once private destinations. |
| `server/src/yap_server/knowledge/generation_ledger.py` | 835 | One Postgres transaction owner installs/stages/embeds/rehashes/activates/rolls back/prunes generations and the active pointer under one tenant lock. Splitting mutations would obscure atomicity. |
| `server/src/yap_server/knowledge/knowledge_proposals.py` | 921 | One Postgres proposal authority validates and publishes immutable noncanonical Curator proposals, serializes exact per-subject unresolved capacity, preserves idempotent retry/discard, and exposes a bounded owner-scoped Coordinator projection that reauthorizes current citations and successful Curator lineage under the same advisory-lock order. Canonical activation remains outside it. |
| `server/src/yap_server/knowledge/vllm_reasoning_client.py` | 282 | One bounded loopback transport owner enforces numeric authority, a total wall-clock deadline, cancellation acknowledgement, response-byte/JSON-depth limits, exact `/render` token counting, and one-candidate (`n=1`) generation. Model-specific semantics and broker admission remain outside it. |
| `server/src/yap_server/knowledge/knowledge_source_admission.py` | 377 | One durable admission writer binds authenticated review authority, immutable source identity, canonical generation identity, durable idempotency, and restart read-back. Curated role authorization and write are one operation; reviewed capture rendering and compilation remain separate owners. |
| `server/src/yap_server/knowledge/knowledge_tool_contract.py` | 506 | One product protocol owner defines strict request/citation types, bounds, schemas, response DTOs, and cancellation errors consumed by MCP, RAG, storage, and evaluation. Splitting schemas from validation caused the defect removed here. |
| `server/src/yap_server/knowledge/okf_compiler.py` | 387 | One deterministic compiler contract parses the Yap OKF profile, derives every projection identity, and revalidates canonical POSIX path/profile/resource/projection/generation identities plus raw-source digest shape before durable admission. Lane 1 exact source binding and Lane 2 curator authority remain outside it. |
| `server/src/yap_server/knowledge/postgres_knowledge_retrieval.py` | 541 | One query-family owner shares the same transaction-pinned authorized generation/result/citation projection across tree, lexical, vector, and hybrid reads. |
| `server/src/yap_server/evaluation/owned_postgres_knowledge_runtime.py` | 753 | One lifecycle state machine owns immutable image/container/network/volume/start/restart/readiness/containment/teardown identity; decomposition would split failure containment. |
| `server/orchestrator/src/agent_admission.rs` | 364 | One bounded scheduler owns queue admission, immutable-profile rapid/complex active capacities of four/eight, one active request per owner, owner round robin, priority selection, provider generations, deadlines, cancellation acknowledgement, and terminal retention. Protocol, dispatch, queue, priority, terminal, and DTO helpers are already separate; this is lease authority, not evidence of simultaneous model residency or sustained throughput. |
| `server/src/yap_server/evaluation/agent_admission_broker_observation.py` | 405 | One qualification observation owner builds and hashes the checked broker, validates its owner-private socket/process/binary/profile/state identity, and runs the shared active-capacity probe that holds the exact route limit, queues one additional owner, contains every lease, and proves provider/broker identity unchanged. It does not supervise providers or own scheduler state. |
| `server/orchestrator/tests/agent_admission_broker_contract.rs` | 256 | One private-broker integration owner proves the rapid profile admits four distinct owners before queuing the fifth, promotes queued work after release, acknowledges cancellation, cleans up its socket/process, and never replaces an existing socket owner. |
| `server/orchestrator/tests/agent_admission_contract.rs` | 288 | One scheduler contract owner freezes exact rapid-four/complex-eight active capacities, one-active-per-owner fairness, hot/background dispatch, queue/owner bounds, deadline/cancellation fencing, provider-generation disruption, and auditor quiescence. It is deterministic scheduler evidence, not GPU throughput evidence. |
| `server/orchestrator/tests/agent_admission_failure_contract.rs` | 262 | One failure-contract owner covers invalid provider identity, generation high-water behavior, non-disclosing tokens and duplicate submissions, per-owner active-plus-pending bounds, cancellation acknowledgement before capacity release, and deferred backward-generation disruption. |
| `server/orchestrator/tests/supervised_service.rs` | 453 | One hardware-independent supervised-service suite owns readiness, restart/backoff, launcher identity, forced process-group teardown, and full-profile construction with explicit maximum sequences. Admission scheduling and live model-capacity qualification remain outside it. |
| `server/src/yap_server/evaluation/governed_knowledge_gate.py` | 570 | One aggregate decision composes exact candidate admission, the fixed 173-test portable membership, Ruff/Postgres/restart children, teardown, and create-once publication. Child lifecycle and evidence validators remain separate modules; exact head `7f896b34...` owns the admitted aggregate outcome. |
| `server/src/yap_server/evaluation/agent_route_qualification_evidence.py` | 517 | One private-tree admission boundary verifies exact membership, hashes, permissions, semantic summaries, predecessor identity, protected drift, and route-specific service/build inputs without importing raw output into public evidence. The admission/gate owners and the new production-admission contract are protected. |
| `server/src/yap_server/evaluation/agent_service_lifecycle_observation.py` | 409 | One read-only observation owner validates exact service state, container launch policy, model readiness, process/listener absence, and the public-safe receipt projection without owning lifecycle mutation. |
| `server/src/yap_server/evaluation/agent_service_lifecycle_runtime.py` | 582 | One sequential lifecycle state machine stages the immutable launcher, owns the route network/supervisor/container observations, forces one restart, and proves every observed process and resource absent on success or failure. Splitting mutation from containment would weaken exact teardown. |
| `server/src/yap_server/evaluation/agent_model_qualification.py` | 810 | One fail-closed route decision recomputes both owned candidate results, route-specific runtime evidence, protected build inputs, runtime children, common/proposal latency groups, and atomic tree publication. Runtime execution remains separately owned. |
| `server/src/yap_server/evaluation/agent_vllm_runtime.py` | 643 | One qualification lifecycle state machine retains pending/observed immutable identities through route-specific image/platform/launch-policy validation, readiness, cgroup observation, containment, and exact teardown while consuming the shared launch contract. |
| `server/src/yap_server/pools/agent_vllm_service_profile.py` | 418 | One exact profile reader binds the service identity, candidate/runtime/model revisions, resource policy, candidate-lock digest, numeric loopback endpoint, and shared launch arguments before any production container mutation. |
| `server/src/yap_server/evaluation/agent_model_acceptance.py` | 586 | One frozen acceptance reader validates exact candidate, fixture, route-to-runtime mapping, build/provenance inputs, route-specific common/proposal thresholds and proposal cap, final-response attempts, and exact cited-proposal policy through the shared product tool contract. Splitting schema checks from this owner would recreate divergent admission. |
| `server/src/yap_server/evaluation/agent_model_fixture_runner.py` | 539 | Conversation sequencing, forced one-candidate (`n=1`) requests, route-specific proposal output bounds, tool/result rounds, and bounded final structural decoding remain one evaluation driver after the duplicate product-tool schema authority was removed. Completed tools sit outside the retry loop. |
| `server/src/yap_server/evaluation/agent_model_scoring.py` | 334 | One scorer recomputes route quality from frozen cases, exact tool/argument/citation/term behavior, and bounded per-case request evidence; it trusts no supplied aggregate. |
| `server/tests/evaluation/test_owned_postgres_knowledge_runtime.py` | 495 | One fake Docker lifecycle test owner covers start/restart/rebind/partial-observation/containment/teardown; aggregate-gate contracts remain in their separate functional module. |
| `server/tests/evaluation/test_agent_model_qualification.py` | 880 | One fail-closed decision test owner covers full admission, evidence-schema rejection, route-specific runtime/failure, protected-build-input tamper, common/proposal latency policy, and exceptional containment cases against the same qualification seam. |
| `server/tests/evaluation/test_agent_model_fixture_runner.py` | 843 | One conversation-driver test owner covers one-candidate requests, route and proposal output caps, tool/result sequencing, exact cited-proposal and semantic context withholding, warmups, contract parity, malformed tool-response continuation, and complex no-replay behavior. |
| `server/tests/evaluation/test_agent_model_scoring.py` | 354 | One scorer test owner independently rejects malformed or semantically different tool, argument, citation, terminology, request-count, and proposal evidence without trusting aggregates. |
| `server/tests/evaluation/test_agent_model_final_response_retry.py` | 269 | One narrow retry-contract test owner covers the observed proposal fixture, both final-response protocols, exhaustion, exact citation retention, semantic non-retry, request counting, latency, and no tool replay. It owns no product state. |
| `server/tests/evaluation/test_governed_knowledge_gate.py` | 359 | One aggregate-gate contract owner freezes exact child membership/counts, protected-route drift, dependency identities, receipt shape, local/offline boundary, and runner failure classification. Docker lifecycle behavior remains in its separate test owner. |
| `server/tests/evaluation/test_agent_vllm_runtime.py` | 717 | One immutable vLLM lifecycle test owner covers route-specific image/platform/build labels, strict tool guidance, launch policy, partial-start identity, name replacement, containment retry, cgroup/listener/PID teardown, and exact model artifacts. |
| `server/tests/knowledge/test_okf_compiler.py` | 544 | One compiler-contract test owner covers pinned conformance, permission/source projection, canonical hashes and POSIX paths, relationship authority, linked-directory rejection, and authenticated curator admission identity. |
| `server/tests/knowledge/test_postgres_generation_ledger.py` | 802 | One real-Postgres generation lifecycle test owner covers stage/embedding/activation/rollback/retention, exact admission, persisted tamper, proposal disposition, and reconnect semantics under the tenant lock. |
| `server/tests/knowledge/test_postgres_permission_safe_retrieval.py` | 485 | One real-Postgres permission/retrieval test owner covers hidden concepts/links, lexical/vector/hybrid output, revocation, and the two-connection generation-pin race. |
| `server/tests/knowledge/test_reviewed_meeting_postgres_route.py` | 768 | One end-to-end meeting-result-to-reviewed-source-to-cited-retrieval owner covers durable replay, cross-owner/path/content/policy attacks, read rehashing, proposal/audit, cancellation, and cleanup. |
| `server/tests/knowledge/test_knowledge_proposals.py` | 409 | One proposal-authority contract suite protects strict citations, unresolved-capacity serialization, replay/discard, owner-scoped Coordinator candidate filtering, exact Curator lineage and current citation rebinding, advisory-lock order, and hidden/foreign/stale suppression. |
| `server/tests/knowledge/test_vllm_reasoning_client.py` | 300 | One transport-contract suite covers numeric loopback admission, one-candidate structured requests, forced Gemma output, exact rendered token counts, bounded/deep JSON failure, cancellation acknowledgement, and total-deadline timeout behavior. |

## Thirty-minute comprehension assessment

**Result: pass within the allotted window.** Starting from the ownership map, a
senior-engineer navigation read-back located (1) the authoritative reviewed
meeting result and source-admission rows, (2) terminology and generation active
pointer writers, (3) the shared-lock permission/retrieval transaction, (4)
proposal disposition and audit, (5) explicit model-route selection and the
vLLM/Postgres lifecycle owners, (6) private/public evidence publication, and
(7) their portable versus required-real-Postgres tests without relying on
tribal naming. The test split and functional private-evidence name removed the
two ambiguous navigation points found during discovery. The frozen candidate
adds explicit profile-capacity and live-probe owners; simultaneous provider
residency, sustained throughput/SLOs, external networking, deployment, and
production promotion remain outside this public maintainability read-back.
