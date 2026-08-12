# Governed Knowledge Maintainability Coverage

**Merged implementation base:**
`ae81ff067c73a64528eecc14403765562726f2fe`

**Inventory and review anchor:** `e2fff1f5b087cc05a549588ea41aae71a6806024`

**Inventory date:** 2026-08-10

This checkpoint reviews the whole active first-party repository through merged
Phase 9. Earlier phase and checkpoint acceptance is evidence, not an exemption.
The Phase 9 delta receives deeper inspection, but it is not the coverage limit.

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
| Server production | 207 | All three reviewers by assigned lens |
| Server tests and fixtures | 199 | All three reviewers by assigned lens |
| Server contracts, runtime locks, and configuration | 71 | Runtime and assurance reviewers |
| Infrastructure | 12 | Runtime and assurance reviewers |
| Verification | 50 | Runtime/evidence and architecture reviewers |
| Hosted workflows and policy | 4 | Assurance reviewer |
| Documentation | 103 | Architecture/comprehensibility reviewer |
| Root product, dependency, provenance, and repository files | 21 | Assurance and architecture reviewers |
| **Total** | **1,470** | One consolidated controller |

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
| Server production | 207 | 58,575 |
| Server tests | 197 | 48,378 |
| Server contracts/runtime configuration | 27 | 6,397 |
| Verification tooling | 47 | 12,312 |
| Infrastructure | 2 | 1,131 |
| Hosted workflows | 4 | 1,372 |
| Documentation | 103 | 33,237 |
| Root/configuration/provenance text | 49 | 19,801 |

The reproducible threshold screen finds 494 tracked regular source, text, and
policy surfaces at or above 250 lines: 259 at or above 350 and 235 from 250
through 349. The exact extension set, five excluded generated/dependency
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

At the current Phase 10 Scribe candidate tree, the inventory contains 512
in-scope tracked source, text, policy, and provenance surfaces at or above 250
physical lines: 272 at or above 350 and 240 from 250 through 349. The completed
checkpoint reviews deep-traced the inherited surfaces
through the same workflow owners and found no additional mixed authority. The
mutually exclusive rows below classify every one of the 272
decomposition-triggering surfaces. The exact path/line/disposition read-back is
recorded in [THRESHOLD-DISPOSITION.md](THRESHOLD-DISPOSITION.md); generated
OpenAPI, the package lock, dependency-inventory JSON, media, model artifacts,
caches, and build output remain excluded rather than disguised as cohesion
decisions.

| Exact path group | >=350 files | Disposition and concrete cohesion reason |
| --- | ---: | --- |
| `.github/workflows/*` | 2 | Retain the CI and release dependency DAGs as the two hosted policy owners. Jobs are already named by functional gate; extracting YAML fragments would hide exact-head ordering without removing authority. |
| `desktop/src-tauri/migrations/*` | 1 | Retain the single current job-ledger schema as one atomic durable-state definition; obsolete migration branches are forbidden and were removed where found. |
| `desktop/src-tauri/src/**` | 83 | Retain along existing functional module boundaries: app activation, audio session/coordinator, commands, job drain/ledger/remote state, language/live runtime, connector/auth, model adapters, and the new trusted-source/correction-revision owner each own one state machine or transaction family. Inline tests remain beside their private Rust owners. Scribe adds no second capture/job/identity writer. |
| `desktop/src-tauri/tests/*` | 2 | Retain the two integration owners for audio foundation and model-download lifecycle; each crosses native components deliberately and owns no production state. |
| `desktop/src/*` | 4 | Retain the application composer, live-overlay views, shared sidebar primitive, and settings-control hook as separate UI owners; native projected state remains authoritative. |
| `desktop/tests/**` | 15 | Retain each functional E2E, WDIO, release-contract, inventory, or runner configuration owner, including the hand-written dependency-inventory script rather than its generated JSON products. These are scenario/gate compositions, not production authority; the mixed gate contracts already use named child boundaries. |
| Current/normative `docs/**` excluding completed/archived plans and research | 17 | Retain each ADR, current architecture/status, active decision queue, runbook, spec, and Voice OS document by taxonomy/decision owner. Stale current-state claims are repaired; these files are not executable modules. |
| `docs/plans/{archived,completed}/**` and `docs/research/**` | 11 | Retain as immutable historical delivery/evidence records. Rewriting or splitting them would damage provenance; current truth lives in current/normative documents. |
| `infra/**` | 5 | Retain each process-group, supervisor, loopback proxy, resident lifecycle, and setup owner because containment must remain end to end within its script/process boundary. |
| `server/README.md` | 1 | Retain the server runbook as the single operator navigation surface; executable gates and source modules remain authoritative. |
| `server/orchestrator/**` | 3 | Retain the supervisor as the provider-lifecycle owner, the admission scheduler as the bounded multi-user lease/fairness owner, and the hardware-independent integration suite as the end-to-end lifecycle contract. The two state machines consume typed snapshots but do not share mutation authority. Configuration, protocol, queue, terminal, and readiness concerns remain split across functional Rust modules. |
| `server/src/yap_server/auth/**` | 3 | Retain identity repository, token validation, and OIDC metadata as separate trust-boundary owners. The obsolete identity migration was deleted; no caller-chosen tenant/subject path remains. |
| `server/src/yap_server/evaluation/**` | 36 | Retain each named acceptance, corpus/review, scorer, runtime observation, lifecycle, qualification, and aggregate-decision owner. Scribe corpus/qualification/source-evidence/gate modules separate private input admission, measurement, and aggregate lifecycle rather than sharing runtime mutation. The existing agent qualification and supervised-service lifecycle owners remain separate for the same reason. |
| `server/src/yap_server/jobs/**` | 5 | Retain completion/store/runtime plus the single locked service aggregate. The 1,401-line service owns one `RLock`; pure policies may move only when they do not create a second job-state authority. |
| `server/src/yap_server/knowledge/**` | 6 | Retain generation ledger, source admission, tool contract, compiler, proposal, and Postgres retrieval by transaction/protocol boundary. Canonical hashes, owner/source admission, shared-lock queries, and proposal disposition are now explicit; individual high-change surfaces are itemized below. |
| `server/src/yap_server/lid/**` | 5 | Retain component lock, runtime/materialization, policy, and worker contract as the bounded acoustic-LID artifact/runtime decision family; selection and durable job state remain outside it. |
| `server/src/yap_server/live/**` | 2 | Retain protocol and WebSocket server as separate contract/admission owners; neither owns ASR jobs, identity, or external production transport. |
| `server/src/yap_server/meeting_transcription/**` | 3 | Retain container worker, immutable result-revision authority, and runtime provenance as distinct meeting execution/evidence owners; speaker naming remains outside scope. |
| `server/src/yap_server/pools/**` | 13 | Retain provider-neutral pool contracts, the exact agent-service profile reader, and provider-specific engine/client/service/scheduler boundaries. Each large file owns one runtime or request protocol; no universal fallback/router was reintroduced. |
| Other `server/src/yap_server/**` | 2 | Retain the Scribe structured-edit contract and bounded asynchronous service as separate semantic and lifecycle owners. Admission, model transport, terminology, HTTP, and publication remain outside them; splitting either state transition further would obscure validation or containment. |
| `server/tests/{auth,capabilities,contract}/**` | 6 | Retain by trust/contract owner; these suites intentionally enumerate adversarial token, metadata, catalog, public-contract, and OpenAPI cases. |
| `server/tests/evaluation/**` | 13 | Retain one suite per corpus/runtime/qualification/evidence owner. Aggregate-gate and owned-Postgres lifecycle tests stay split; Scribe qualification has one independent multi-owner acceptance owner. |
| `server/tests/infra/**` | 4 | Retain end-to-end process/proxy/lifecycle harnesses because their failure cases span subprocess boundaries while production owners stay in `infra/`. |
| `server/tests/jobs/**` | 8 | Retain suites by runtime, commit admission, contract, meeting result, processing, restart, recovery, and retention workflow. They share fixtures, not production state. |
| `server/tests/knowledge/**` | 4 | Retain the compiler and three real-Postgres integration owners. Each is itemized below and the database lane requires every test with zero skips. |
| `server/tests/{lid,live,model_pools,pools}/**` | 8 | Retain by component/runtime owner; these are bounded lifecycle, protocol, scheduler, and client integration suites inherited from reviewed earlier phases. |
| Other `server/tests/**` | 2 | Retain the Scribe semantic-validator and asynchronous-service suites beside their two production owners. They cover adversarial edit integrity and cancellation/containment separately and own no product state. |
| `verification/**` | 8 | Retain each functional aggregate runner, hosted-closure, private-evidence, product-checkpoint, meeting-evidence, OIDC-owner, and checkout verifier. They compose existing children and publish no product state. |

This grouped inventory is exhaustive for the threshold at this tree, while the
following individual decisions make the most coupled or changed owners directly
navigable.

| Surface | Lines after remediation | Concrete owner justification |
| --- | ---: | --- |
| `server/src/yap_server/jobs/service.py` | 1,401 | One `RLock` protects the server job aggregate: scheduling, cancellation, result publication, and recovery must not acquire a second state owner. Extract only pure policies if a future change establishes a real seam. |
| `desktop/src-tauri/src/server_connector/transcript_correction.rs` | 498 | One strict authenticated HTTP client owns the bounded correction wire request/status/error projection. Credential acquisition remains in the connector dispatcher and source/publication authority remains in native Scribe owners. |
| `desktop/src-tauri/src/transcript_correction/mod.rs` | 446 | One native request aggregate owns trusted-source admission, connector lease lifetime, monotonic server-state projection, cancellation, bounded terminal retention, and explicit publication dispatch. Source and revision mechanics are already separate modules. |
| `desktop/src-tauri/src/transcript_correction/revision.rs` | 828 | One hash-chained correction-revision owner validates source identity before/after publication, serializes user acceptance, and couples deletion to the existing live/remote source lifecycle. Splitting the write/read/delete invariants would create competing derivative authority. |
| `server/src/yap_server/agents/transcript_correction.py` | 944 | One Scribe semantic contract owns segment/request/edit/response schema, source hashes, bounded edit application, protected-fact preservation, terminology, and exact raw/corrected projection. Scheduling, model transport, persistence, and HTTP remain separate owners. |
| `server/src/yap_server/agents/transcript_correction_service.py` | 754 | One bounded asynchronous lifecycle owns submit/status/cancel, broker lease, worker containment, queue-inclusive deadline, 64 in-flight and 256 terminal limits, and typed terminal disposition. The semantic validator and model client remain separate. |
| `server/src/yap_server/evaluation/transcript_correction_qualification.py` | 713 | One qualification decision synchronizes distinct owners through one warm generation, records every case/wave, recomputes correction/safety/latency/disposition metrics, and fails closed on containment or lifecycle drift. Corpus/source admission and aggregate orchestration remain separate. |
| `server/src/yap_server/evaluation/transcript_correction_qualification_gate.py` | 621 | One exact-head aggregate composes source-evidence admission, public contracts, Rust/desktop/server children, warm-route qualification, teardown, and create-once public-safe publication. It does not own model/service mutation. |
| `server/src/yap_server/evaluation/transcript_correction_source_evidence.py` | 447 | One private source-evidence admission boundary binds exact public plan/release/model hashes, private file identity, membership, language, candidate route, and privacy-safe result shape without disclosing source paths or transcript content. |
| `server/tests/agents/test_transcript_correction_service.py` | 770 | One lifecycle suite covers multi-owner admission, overload, deadline, cancellation acknowledgement, model/terminology failures, no-op/uncertain/invalid distinctions, containment fencing, and bounded retention against the service owner. |
| `server/tests/evaluation/test_transcript_correction_qualification.py` | 822 | One acceptance suite covers eight-owner synchronized waves, duplicate-owner rejection, warm-generation identity, real-ASR source membership, correction/safety bounds, invalid fallback false-pass prevention, latency, and teardown. |
| `server/src/yap_server/knowledge/generation_ledger.py` | 809 | One Postgres transaction owner installs/stages/embeds/rehashes/activates/rolls back/prunes generations and the active pointer under one tenant lock. Splitting mutations would obscure atomicity. |
| `server/src/yap_server/knowledge/knowledge_proposals.py` | 358 | One Postgres proposal owner validates the shared strict citation contract, publishes immutable noncanonical proposals, owns authorized discard, and serializes proposal liveness against generation pruning. Splitting persistence from disposition would recreate duplicate retention authority. |
| `server/src/yap_server/knowledge/knowledge_source_admission.py` | 377 | One durable admission writer binds authenticated review authority, immutable source identity, canonical generation identity, durable idempotency, and restart read-back. Curated role authorization and write are one operation; reviewed capture rendering and compilation remain separate owners. |
| `server/src/yap_server/knowledge/knowledge_tool_contract.py` | 501 | One product protocol owner defines strict request/citation types, bounds, schemas, response DTOs, and cancellation errors consumed by MCP, RAG, storage, and evaluation. Splitting schemas from validation caused the defect removed here. |
| `server/src/yap_server/knowledge/okf_compiler.py` | 387 | One deterministic compiler contract parses the Yap OKF profile, derives every projection identity, and revalidates canonical POSIX path/profile/resource/projection/generation identities plus raw-source digest shape before durable admission. Lane 1 exact source binding and Lane 2 curator authority remain outside it. |
| `server/src/yap_server/knowledge/postgres_knowledge_retrieval.py` | 404 | One query-family owner shares the same transaction-pinned authorized generation/result/citation projection across tree, lexical, vector, and hybrid reads. |
| `server/src/yap_server/evaluation/owned_postgres_knowledge_runtime.py` | 753 | One lifecycle state machine owns immutable image/container/network/volume/start/restart/readiness/containment/teardown identity; decomposition would split failure containment. |
| `server/orchestrator/src/agent_admission.rs` | 350 | One bounded scheduler owns queue admission, per-route capacity, owner round robin, priority selection, provider generations, deadlines, cancellation acknowledgement, and terminal retention. Protocol, dispatch, queue, priority, terminal, and DTO helpers are already separate; splitting the state transition owner would create competing lease authority. |
| `server/src/yap_server/evaluation/governed_knowledge_gate.py` | 573 | One aggregate decision composes exact candidate admission, portable/Ruff/Postgres/restart children, teardown, and create-once publication. Child lifecycle and evidence validators remain separate modules. |
| `server/src/yap_server/evaluation/agent_route_qualification_evidence.py` | 517 | One private-tree admission boundary verifies exact membership, hashes, permissions, semantic summaries, predecessor identity, protected drift, and route-specific service/build inputs without importing raw output into public evidence. The admission/gate owners and the new production-admission contract are protected. |
| `server/src/yap_server/evaluation/agent_service_lifecycle_observation.py` | 382 | One read-only observation owner validates exact service state, container launch policy, model readiness, process/listener absence, and the public-safe receipt projection without owning lifecycle mutation. |
| `server/src/yap_server/evaluation/agent_service_lifecycle_runtime.py` | 582 | One sequential lifecycle state machine stages the immutable launcher, owns the route network/supervisor/container observations, forces one restart, and proves every observed process and resource absent on success or failure. Splitting mutation from containment would weaken exact teardown. |
| `server/src/yap_server/evaluation/agent_model_qualification.py` | 717 | One fail-closed route decision recomputes both owned candidate results, route-specific runtime evidence, protected build inputs, runtime children, common/proposal latency groups, and atomic tree publication. Runtime execution remains separately owned. |
| `server/src/yap_server/evaluation/agent_vllm_runtime.py` | 626 | One qualification lifecycle state machine retains pending/observed immutable identities through route-specific image/platform/launch-policy validation, readiness, cgroup observation, containment, and exact teardown while consuming the shared launch contract. |
| `server/src/yap_server/pools/agent_vllm_service_profile.py` | 372 | One exact profile reader binds the service identity, candidate/runtime/model revisions, resource policy, candidate-lock digest, numeric loopback endpoint, and shared launch arguments before any production container mutation. |
| `server/src/yap_server/evaluation/agent_model_acceptance.py` | 585 | One frozen acceptance reader validates exact candidate, fixture, route-to-runtime mapping, build/provenance inputs, route-specific common/proposal thresholds and proposal cap, final-response attempts, and exact cited-proposal policy through the shared product tool contract. Splitting schema checks from this owner would recreate divergent admission. |
| `server/src/yap_server/evaluation/agent_model_fixture_runner.py` | 483 | Conversation sequencing, route-specific proposal output bounds, tool/result rounds, and bounded final structural decoding remain one evaluation driver after the duplicate product-tool schema authority was removed. Completed tools sit outside the retry loop. |
| `server/src/yap_server/evaluation/agent_model_scoring.py` | 334 | One scorer recomputes route quality from frozen cases, exact tool/argument/citation/term behavior, and bounded per-case request evidence; it trusts no supplied aggregate. |
| `server/tests/evaluation/test_owned_postgres_knowledge_runtime.py` | 495 | One fake Docker lifecycle test owner covers start/restart/rebind/partial-observation/containment/teardown; aggregate-gate contracts remain in their separate functional module. |
| `server/tests/evaluation/test_agent_model_qualification.py` | 750 | One fail-closed decision test owner covers full admission, evidence-schema rejection, route-specific runtime/failure, protected-build-input tamper, common/proposal latency policy, and exceptional containment cases against the same qualification seam. |
| `server/tests/evaluation/test_agent_model_fixture_runner.py` | 754 | One conversation-driver test owner covers route and proposal output caps, tool/result sequencing, exact cited-proposal and semantic context withholding, warmups, contract parity, malformed tool-response continuation, and complex no-replay behavior. |
| `server/tests/evaluation/test_agent_model_scoring.py` | 354 | One scorer test owner independently rejects malformed or semantically different tool, argument, citation, terminology, request-count, and proposal evidence without trusting aggregates. |
| `server/tests/evaluation/test_agent_model_final_response_retry.py` | 269 | One narrow retry-contract test owner covers the observed proposal fixture, both final-response protocols, exhaustion, exact citation retention, semantic non-retry, request counting, latency, and no tool replay. It owns no product state. |
| `server/tests/evaluation/test_governed_knowledge_gate.py` | 359 | One aggregate-gate contract owner freezes exact child membership/counts, protected-route drift, dependency identities, receipt shape, local/offline boundary, and runner failure classification. Docker lifecycle behavior remains in its separate test owner. |
| `server/tests/evaluation/test_agent_vllm_runtime.py` | 647 | One immutable vLLM lifecycle test owner covers route-specific image/platform/build labels, strict tool guidance, launch policy, partial-start identity, name replacement, containment retry, cgroup/listener/PID teardown, and exact model artifacts. |
| `server/tests/knowledge/test_okf_compiler.py` | 544 | One compiler-contract test owner covers pinned conformance, permission/source projection, canonical hashes and POSIX paths, relationship authority, linked-directory rejection, and authenticated curator admission identity. |
| `server/tests/knowledge/test_postgres_generation_ledger.py` | 802 | One real-Postgres generation lifecycle test owner covers stage/embedding/activation/rollback/retention, exact admission, persisted tamper, proposal disposition, and reconnect semantics under the tenant lock. |
| `server/tests/knowledge/test_postgres_permission_safe_retrieval.py` | 484 | One real-Postgres permission/retrieval test owner covers hidden concepts/links, lexical/vector/hybrid output, revocation, and the two-connection generation-pin race. |
| `server/tests/knowledge/test_reviewed_meeting_postgres_route.py` | 768 | One end-to-end meeting-result-to-reviewed-source-to-cited-retrieval owner covers durable replay, cross-owner/path/content/policy attacks, read rehashing, proposal/audit, cancellation, and cleanup. |

## Thirty-minute comprehension assessment

**Result: pass within the allotted window.** Starting from the ownership map, a
senior-engineer navigation read-back located (1) the authoritative reviewed
meeting result and source-admission rows, (2) terminology and generation active
pointer writers, (3) the shared-lock permission/retrieval transaction, (4)
proposal disposition and audit, (5) explicit model-route selection and the
vLLM/Postgres lifecycle owners, (6) private/public evidence publication, and
(7) their portable versus required-real-Postgres tests without relying on
tribal naming. The test split and functional private-evidence name removed the
two ambiguous navigation points found during discovery. Production supervision,
capacity, external networking, and deployment are visibly outside these owners
and remain Phase 10/IT handoffs.
