# Finish Yap without model hardware

**Status:** Completed supported UI milestone; target qualification continues in the project goal. **Owner:** Grant McNatt. **Started:** 2026-10-02.

## Goal

**Milestone: finish Yap's UI and every hardware-independent part of its supported workflows, so the next qualification can focus on real models, Windows behavior, and enterprise deployment.**

A new user can understand setup, find the next action, finish supported workflows, and recover from unavailable services without losing work. Developers can reproduce builds and exercise those workflows with deterministic fixtures, without model weights or a GPU. The code and documentation explain the same product with fewer obsolete paths, duplicated responsibilities, and scattered plans.

This records the completed supported UI milestone. The [project hill-climbing goal](../active/2026-10-02-yap-project-hill-climb.md) now owns the single execution queue, including remaining feature implementation and target qualification. Earlier plans are reference material. Model quality, capacity, and enterprise evidence remain release requirements, but do not block UI completion, refactoring, or portable tests.

The broader product direction remains in [Product](../../../PRODUCT.md), [Design](../../../DESIGN.md), the [Voice OS architecture](../../VOICE-OS-ARCHITECTURE.md), accepted ADRs, and specs. Archiving a plan does not cancel its proposed features or requirements. Consolidation must carry forward that intent with source links and an explicit disposition; shortening the execution queue is not a decision to reduce the product's ambition.

## How we measure progress

For each workspace—Home, Transcribe, Correct, Knowledge, Settings, Help—review:

1. A clear purpose and next action, with concise, accurate language.
2. Empty and loading states that explain what is happening.
3. A usable completion/review state under deterministic fixtures.
4. Offline, missing-model, unavailable-server, and denied-capability states with an appropriate next action; no silent data loss or route change.
5. Keyboard, focus, reduced-motion, and supported-window-size behavior.

Mark a workspace complete only with the relevant behavior/browser evidence. Track acceptance, not line counts, screenshots alone, or the number of receipts. Keep raw transcripts, credentials, authorization, job durability, and native ownership intact as the implementation gets smaller.

The UI target is **30 verified acceptance areas: six workspaces × five areas**. All 30 supported UI acceptance areas are verified within the documented browser/fixture scope; target qualification is separate. Existing test counts do not establish a completion score. Record each area's concrete gap and verification reference here as the audit proceeds. An area passes when all applicable states work; any hardware-dependent behavior must have an explicit limitation and a named handoff test, rather than receive credit from a simulation.

## Definition of done

- All 30 UI acceptance areas are verified, including onboarding and transitions between workspaces. No unfinished controls, misleading readiness claims, or unexplained dead ends remain in supported flows.
- Deterministic fixtures exercise transcription → history → correction and supported knowledge review, including failure, cancellation, retry, restart, and unavailable capabilities. Original transcripts and accepted revisions remain intact.
- A fresh supported development environment can install locked dependencies, build the frontend/native client/services, and run the documented hardware-independent checks using pnpm and Rust. Checks relevant to the final changes pass; skips and platform limits are explained.
- Obsolete code and documentation identified during this work are removed or reconciled. There is one active execution queue, concise setup guidance, and a current account of what works.
- Intended features and unresolved decisions from the prior roadmap and decision queue are reconciled into the current roadmap with source links, distinguishing implemented behavior, work for this milestone, later work, and hardware/IT dependencies. Retiring a requirement needs a recorded reason; moving its document to the archive is insufficient.
- Every remaining qualification task for the supported UI milestone names its target environment, required models or IT inputs, and observable pass condition. Remaining product software work is carried into the project goal, not deferred to hardware qualification.

## Execution loop

Audit a real user journey in the running UI, record the highest-impact gap here, complete the smallest end-to-end fix, and verify the changed behavior. Update acceptance evidence and current status, then select the next gap. Prioritize blocked tasks and recovery over visual polish; polish each completed flow before closing the milestone. Refactor where the flow exposes unnecessary complexity, rather than opening a separate rewrite.

The first increment is **first-run setup → Transcribe → readable transcript history**: honest readiness, a useful path when models are absent, fixture-driven job completion, and clear recovery. Continue through correction and knowledge, then close remaining Settings, Help, and cross-workspace acceptance gaps. Sequence planned future features in the roadmap while prioritizing completion of these journeys.

## Ordered work

### 1. Working development environment

- [x] Verify the cloud resource and network boundary.
- [x] Install Rust 1.96, Clippy, rustfmt, PowerShell, native Linux build libraries, and repository-pinned pnpm 11.7.0; synchronize locked Python dependencies.
- [x] Build the frontend, native Tauri app, and Rust server orchestrator.
- [x] Run browser tests using an explicitly selected system Chromium.
- [x] Provide reusable setup, shell environment, and isolated server-test commands.
- [x] Close portable/native test failures and record platform-specific limits in [current status](../../CURRENT-STATUS.md).

### 2. Complete the core user journey

- [x] Reconcile intended features and open decisions from the product/architecture documents, [prior roadmap](../../archive/implementation-evidence/roadmap-2026-08-14.md), and [prior decision queue](../archived/2026-07-17-voiceos-decision-evidence-queue.md) into the current roadmap, retaining source links and explicit dispositions. The current roadmap retains the feature inventory and all 27 open-question identifiers with dispositions; nothing is retired by archiving.
- [x] Establish the initial running-UI audit and record concrete gaps below. Continue auditing completion states in each increment.
- [x] Fix first-run setup: missing models must be actionable, setup must be skippable, and typed practice text must not claim verified dictation/privacy.
- [x] Finish Home and transcript history: useful empty/loading state, search, selection, readable transcripts, shipped copy/open/reveal, and recovery actions. Dedicated export stays explicit later work in the roadmap.
- [x] Finish Transcribe: supported-format guidance, language selection, explicit routing, queue progress, cancel/retry, restart recovery, and completed results.
- [x] Finish Correct: source selection, visible proposed edits, acceptance, immutable revision, cancellation, and raw-transcript access when unavailable.
- [x] Finish Knowledge: understandable search/answer entry points, citations, review-required outputs, capability-specific availability, and clear recovery.
- [x] Finish Settings and Help: setup/recovery actions, direct descriptions, accurate output/location information, and technical detail behind disclosure.
- [x] Verify all six workspaces against the five acceptance areas above.

### 3. Simplify around working behavior

- [x] Remove unused components, stale paths, duplicated state, and unnecessary configuration after confirming the executable owners and callers.
- [x] Refactor repeated workflow transport/presentation only where it reduces complexity without moving native credentials or authority into the renderer.
- [x] Establish one short root README, documentation index, roadmap, and active plan; preserve historical qualification narratives as reference evidence.
- [x] Reconcile stale product/design and contributor documentation with the actual interface.
- [x] Keep code modular by responsibility; preserve provenance and user data.

### 4. Close the hardware-free milestone

- [x] All advertised fixture workflows finish or reach an explicit unavailable outcome. Cancel/retry/restart and disconnected local controls are exercised.
- [x] Relevant desktop/browser/native/server checks pass, with every platform or real-model exclusion named. Review the final diff and current documentation.
- [x] Record the precise hardware/IT handoff inputs and remaining tests.

## Product completion checkpoint

The supported journeys are implemented and all 30 software/UI acceptance areas pass within the documented scope. Final verification: 388 frontend tests passed (2 Windows-only skips), 86 browser tests passed (1 Windows-only skip), TypeScript/Vite build passed, 4 native remote-ledger restart/idempotency tests passed, and documentation/format/whitespace checks passed. The [30-area acceptance matrix and qualification handoff](../../evidence/ui-completion/2026-10-02-acceptance.md) records behavior, test sources, fixture boundaries, and the exact remaining model/Windows/IT inputs. [Mobbin references](../../evidence/ui-completion/2026-10-02-design-references.md) cover inspected screens, flow preview steps, and website sections with canonical links.

### Changes and inspected journeys

| Journey | Completed software work and evidence |
| --- | --- |
| Welcome → setup → explore | Shared native language projection; explicit confirmation, skip/Escape, focus trap and check/save retries; no typed-text claim of verified dictation. `first-run.spec.ts`. |
| Home → transcript review | Catalog loading/error/retry, body search, bounded preview/read retries, readable text and copy/open/reveal; saved-source selection persists after review. `recording-journey.spec.ts`, history and workspace acceptance suites. |
| Recording → completion | Truthful queued/processing phases, explicit language/server route, cancel/re-add/failure/retry, startup projections; a Review notification preserves other pending work. Recording and Knowledge journey suites. |
| Review → Correct → accept | Selected older source retained, visible edit markup, original preserved, copy and explicit separate revision, save/job failure retry and source-change cancellation. `correction-journey.spec.ts`. |
| Knowledge search → answer/review | Four tabs retain drafts/pending tasks; six role journeys, shared exact source citations/disclosure, learning question → proposal reference, noncanonical review-required bundles/reports. Cancellation no longer resubmits the form. `knowledge-journey.spec.ts`. |
| History maintenance | Hide/recovery/native-delete failures retain rows; retries use native identities; saved and partial deletion require confirmation. Workspace acceptance, history action units and native baseline. |
| Settings and Help | Local/server readiness separated; server load/save/check retries retain inputs; model lifecycle fixture exercises failure/retry/cancel/ready independently of server denial. Help FAQs and Settings link; modal focus restoration, keyboard and window checks. Workspace acceptance and existing language/shortcut/island suites. |

Visual inspection includes the initial nine setup/unavailable/review states and seven completion/settings/help states at 1122×740; Help also inspected at 720×520. Browser layout checks cover 1122×740, 1440×900 and the narrow accessibility probe. Local captures live under `.tools/ui-audit/`; the evidence record links reproducible assertions.

### Simplification and preserved intent

One current execution queue replaces the scattered active plans. Earlier plans and detailed status/roadmap/product receipts are preserved in the archive. The roadmap retains all intended feature areas and OQ-01–OQ-27 with source-linked dispositions; nothing is retired by archiving. Dedicated export, more formats, personalization, and broader Voice OS work remain planned, without implying shipped controls.

Obsolete setup prompts, skip flags, duplicated onboarding/readiness state and stale explanatory comments are removed. Shared citations, request-cancellation controls, and modal focus handling replace repeated presentation responsibilities; source-specific authority and native transport stay with their existing owners. Product/Design/desktop guidance now matches navigation, supported decoding, readability, and color tokens. No third-party branding or attribution is removed.

### Verification and handoff

Final working-tree checks pass. The native restart tests are fresh; the full native/service suites are the preceding environment baseline. The environment's preceding native/service baseline remains recorded in [current status](../../CURRENT-STATUS.md); frontend-only changes do not renew inference or enterprise qualification. The [handoff table](../../evidence/ui-completion/2026-10-02-acceptance.md#qualification-handoff) names required inputs and observable pass conditions for every remaining qualification task. Merge and release remain subject to reviewed-head and target-environment gates.

## Attribution

Attribute project work to Grant McNatt. Do not add AI coauthor trailers or generated-by branding. Preserve third-party notices, licenses, and provenance.
