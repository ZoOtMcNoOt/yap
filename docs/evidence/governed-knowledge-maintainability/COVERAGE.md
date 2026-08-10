# Governed Knowledge Maintainability Coverage

**Merged implementation base:**
`ae81ff067c73a64528eecc14403765562726f2fe`

**Inventory anchor:** `3ce9909d7ba172a48139814336b2cd41ff89e1df`

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

The detailed pre-Phase-9 workflow map remains
[Executable Ownership and Trust Boundaries](../../architecture/boundaries/EXECUTABLE-OWNERSHIP.md).
This checkpoint must reconcile it with the owners below before closure.

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
| Desktop UI/native/local lifecycle | Pending | Pending | Pending reviewer evidence |
| Durable client/server batch and preprocessing | Pending | Pending | Pending reviewer evidence |
| Identity/authorization/WSS | Pending | Pending | Pending reviewer evidence |
| Meeting evidence | Pending | Pending | Pending reviewer evidence |
| Knowledge/terminology/retrieval | Pending | Pending | Pending reviewer evidence |
| Agent runtime/evidence | Pending | Pending | Pending reviewer evidence |
| Packaging/CI/gates/provenance | Pending | Pending | Pending reviewer evidence |
| Docs/ADRs/plans/runbooks/status | Pending | Pending | Pending reviewer evidence |

The final version records all dispositions, every retained >350-line cohesion
justification, actual LOC removed, and the thirty-minute comprehension result.
