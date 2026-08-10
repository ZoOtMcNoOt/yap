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

The initial threshold screen found 461 tracked text surfaces at or above 250
lines: 15 desktop frontend, 168 desktop native, 34 desktop test-harness, 91
server production, 76 server test, 21 verification, two server contract/runtime,
two hosted-workflow, one infrastructure, eight root/configuration, and 43
documentation surfaces. Review disposition—not line count alone—decides whether
each is cohesive, generated/machine-maintained, historical, or needs repair.

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
| Desktop UI/native/local lifecycle | Complete across three lenses | Risk/threshold owners sampled; no Phase 9 desktop delta | No P0-P2; retain inherited local/offline boundary evidence |
| Durable client/server batch and preprocessing | Complete across three lenses | Job scheduling/result/cancel/restart owners | No P0-P2; retain `jobs/service.py` with aggregate-root cohesion justification |
| Identity/authorization/WSS | Complete across three lenses | Identity durable owner and adjacent trust seams | KAP-06 removes the obsolete development-schema migration; no tenant/subject/revocation defect found |
| Meeting evidence | Complete across three lenses | Result revision -> reviewed capture -> source admission -> compilation | KAP-02/KAP-03 remediations implemented; real Postgres gate and re-review remain |
| Knowledge/terminology/retrieval | Complete across three lenses | Generation, permissions, retrieval, terminology, proposal, SQL lifecycle | KAP-01 through KAP-05 remediations implemented; real Postgres gate and re-review remain |
| Agent runtime/evidence | Complete across three lenses | Tool/RAG/MCP, route selection, vLLM lifecycle, qualification, private admission | AR-01 through AR-05 and ARCH-03 remediations implemented; protected changes require one fresh private qualification; no fallback defect found |
| Packaging/CI/gates/provenance | Complete across three lenses | Locks, licenses, receipt boundaries, exact-head hosted workflow | No P0-P2; private/public evidence separation remains sound |
| Docs/ADRs/plans/runbooks/status | Complete across three lenses | Current/normative taxonomy and ownership navigation | Ownership/current docs reconciled and mixed test owner split; independent re-review remains |

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

| Surface | Lines after remediation | Concrete owner justification |
| --- | ---: | --- |
| `server/src/yap_server/jobs/service.py` | 1,401 | One `RLock` protects the server job aggregate: scheduling, cancellation, result publication, and recovery must not acquire a second state owner. Extract only pure policies if a future change establishes a real seam. |
| `server/src/yap_server/knowledge/generation_ledger.py` | 654 | One Postgres transaction owner installs/stages/embeds/activates/rolls back/prunes generations and the active pointer under one tenant lock. Splitting mutations would obscure atomicity. |
| `server/src/yap_server/knowledge/postgres_knowledge_retrieval.py` | 360 | One query-family owner shares the same authorized generation/result/citation projection across tree, lexical, vector, and hybrid reads. |
| `server/src/yap_server/evaluation/owned_postgres_knowledge_runtime.py` | 753 | One lifecycle state machine owns immutable image/container/network/volume/start/restart/readiness/containment/teardown identity; decomposition would split failure containment. |
| `server/src/yap_server/evaluation/governed_knowledge_gate.py` | 569 | One aggregate decision composes exact candidate admission, portable/Ruff/Postgres/restart children, teardown, and create-once publication. Child lifecycle and evidence validators remain separate modules. |
| `server/src/yap_server/evaluation/agent_route_qualification_evidence.py` | 476 | One private-tree admission boundary verifies exact membership, hashes, permissions, semantic summaries, predecessor identity, and protected drift without importing raw output into public evidence. |
| `server/src/yap_server/evaluation/agent_model_qualification.py` | 678 | One fail-closed route decision recomputes both owned candidate results, route-specific evidence, runtime children, and atomic tree publication. Runtime execution remains separately owned. |
| `server/src/yap_server/evaluation/agent_vllm_runtime.py` | 678 | One repaired lifecycle state machine retains pending/observed immutable identities through launch-policy validation, readiness, cgroup observation, containment, and exact teardown. |
| `server/src/yap_server/evaluation/agent_model_fixture_runner.py` | 415 | Conversation sequencing and tool/result rounds remain one evaluation driver after the duplicate product-tool schema authority was removed. |
| `server/tests/evaluation/test_owned_postgres_knowledge_runtime.py` | 497 | One fake Docker lifecycle test owner covers start/restart/rebind/partial-observation/containment/teardown; aggregate-gate contracts were split into their own 293-line module. |

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
