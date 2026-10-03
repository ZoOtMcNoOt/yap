# Complete Yap: project hill-climbing goal

**Status:** Active. **Owner:** Grant McNatt. **Started:** 2026-10-02.

## Goal

**Build Yap into a complete, maintainable private transcription and governed-knowledge product by repeatedly finishing the highest-impact end-to-end outcome across the entire approved roadmap. Complete and verify every task possible without model hardware, then qualify the remaining behavior on its actual models, Windows clients, and enterprise environment.**

This is the single execution queue for the entire project. The [roadmap](../../roadmap/ROADMAP.md) retains the feature inventory and OQ-01–OQ-27; [Product](../../../PRODUCT.md), [Design](../../../DESIGN.md), the [Voice OS architecture](../../VOICE-OS-ARCHITECTURE.md), accepted ADRs, and contracts retain the requirements. Conditional proposals require their stated evidence before implementation. Nothing is retired by archiving a document or completing a milestone.

The [completed UI milestone](../completed/2026-10-02-hardware-free-product-completion.md) is a starting point. Its 30/30 acceptance areas describe supported UI journeys under fixtures, not completion of every feature or production qualification.

## Hill-climbing rule

1. Inspect the executable path and a real user or operator journey. Record a concrete gap, its authority boundary, and observable acceptance conditions before changing code.
2. Select the smallest complete increment that removes the highest-impact blocker. Order by data integrity and authority, blocked core workflows, missing capabilities, recovery, usability, then measured maintenance cost. Respect dependencies; avoid a project-wide rewrite.
3. Implement the interface, native/service ownership, persistence and recovery needed for that outcome. Use deterministic providers to exercise orchestration without pretending to qualify inference.
4. Verify behavior at the appropriate layers, inspect relevant UI states, and review the diff. Keep raw transcripts, source identities, accepted revisions, credentials, provenance and user data intact.
5. Record the before/after outcome and evidence in the [execution history](../../archive/implementation-evidence/2026-10-02-project-hill-climb-history.md). Keep remaining limitations and the next increment here. Update current status and the roadmap when capability claims change. Continue with the next available task.

Use pnpm 11.7.0, Rust and locked Python dependencies through the [cloud environment](../../runbooks/cloud-development.md). Reuse existing dependencies and owners. Simplify code and documentation as part of each working increment; do not measure progress by deletions or test counts. Use [Mobbin screens, flows and website sections](../../evidence/ui-completion/2026-10-02-design-references.md) for relevant interaction decisions, inspect the references, and retain canonical links.

## Progress and completion

Track each acceptance outcome as **not implemented**, **partial**, **software verified**, or **target qualified**, with its test/evidence link. A partial backend or fixture-only screen does not verify an end-to-end software outcome. Model accuracy, physical Windows behavior and enterprise operation cannot receive qualification credit from fixtures.

For each increment record:

- **Coverage:** newly verified acceptance outcomes / defined outcomes for that increment. Preserve the denominator; newly found requirements expand it rather than disappear.
- **Open work:** unresolved software gaps and separately named external dependencies. A blocked model test must not hide available software work.
- **Regression gate:** zero known failures introduced in applicable durability, authorization, recovery, accessibility and build checks. Prior results remain dated baselines until rerun.
- **Maintenance:** concrete duplication or obsolete paths removed while preserving behavior; no arbitrary line-count target.

There is no defensible project-wide completion percentage yet. The initial cross-project audit must define the remaining acceptance outcomes before reporting one. [Current status](../../CURRENT-STATUS.md) records the verified development baseline; the [UI acceptance record](../../evidence/ui-completion/2026-10-02-acceptance.md) records the existing 30-area subset.

**Software readiness** requires every approved hardware-independent outcome implemented and verified, no unexplained dead ends or available software blockers, reproducible builds/checks, accurate concise documentation, and executable qualification procedures for each external dependency. It is an intermediate checkpoint.

**Full project completion** additionally requires actual model/provider/locale/speaker evidence, Windows capture/delivery/identity/installation qualification, enterprise policy and deployment inputs, representative capacity and operations evidence, and the repository's reviewed-head release gates. Conditional directions must have an explicit evidence-based disposition. Do not stop the project goal merely because one workspace, milestone, or feature is complete. If every available software task is exhausted, record the exact missing inputs and wait for qualification without declaring the entire project complete.

## Execution queue

The rows below cover the full roadmap. Their order is the initial priority; revise it when an audit exposes a higher-impact blocker. Each row needs bounded acceptance outcomes as its implementation begins.

| Workstream | Baseline and next complete outcome | Qualification boundary |
| --- | --- | --- |
| Transcript review and dedicated export | Original and latest accepted-revision UTF-8 exports are software verified alongside reading/search/copy/open/reveal and offline accepted-correction recovery. Preserve the [original](../../evidence/transcript-export/2026-10-02-verification.md) and [accepted export](../../evidence/accepted-correction-export/2026-10-03/verification.md) contracts. Earlier revision selection is locally implemented with integration pending; timed/speaker exports remain open. | Native dialog/platform filesystem behavior needs target checks; export correctness is model independent. |
| Terminology and personalization | Personal and explicitly configured shared CRUD connect trusted scope/connection authority, the canonical ledger, frozen snapshots and Settings controls; [shared evidence](../../evidence/shared-terminology/2026-10-03-verification.md) covers nine outcomes. Continue directory administration and provider projections using [ADR 0028](../../adr/0028-model-independent-terminology-authority.md). | Directory/admin policy and provider-specific effectiveness need IT and models. |
| Imported recordings and more formats | WAV/MP3/FLAC/Ogg Vorbis/single-track AAC-LC M4A/MP4 normalization, durable jobs, cancellation/retry and native result access exist. Audit full source-to-result recovery; add remaining approved WebM and broader Ogg codecs incrementally with decoder/license, resource and malformed-input checks. | Actual ASR quality, speaker/alignment quality and advertised maximum duration require representative inference. |
| Local dictation, setup and model lifecycle | Supported setup/recovery UI is verified under fixtures. Audit capture/session/restart, explicit install/import, corruption, atomic replacement, rollback and offline behavior; close portable gaps and prepare target checks. | Physical microphones, hotkeys, cross-app delivery, tray hit testing and Windows model guards require Windows. |
| Languages and meeting evidence | Fixed locale and explicit Preview routes exist. Verify unknown/abstention, switching reconciliation, immutable finalized text, source-time alignment and anonymous speaker review. Implement authorized naming/enrollment/profile lifecycle without inferred contact identity. | Locale/switch/overlap/roster promotion, recording length, battery/thermal and sustained performance require actual targets. |
| Supervised services and batch ASR | Rust supervision and bounded admission exist. Finish missing supervised ASR integration; verify health/readiness, source/result ownership, fair scheduling, cancellation, crash/restart and model-unavailable failures with deterministic providers. | Full simultaneous model residency, mixed-owner throughput, latency/memory budgets and SLOs need representative nodes. |
| Server live dictation and secure edge | Authenticated private admission exists; end-to-end live ASR and external serving remain incomplete. Connect native client, authenticated transport and supervised provider; test stream ordering/gaps/backpressure, cancellation, teardown and same-origin WSS/TLS. | Real live quality/performance and enterprise TLS/networking require targets. HTTP/3 requires parity and measured benefit before adoption. |
| Scribe and governed knowledge | Supported eight-role UI journeys are fixture verified. Audit real service persistence and permission-safe integration, raw-preserving corrections, citations, proposal acceptance/publication, revocation and multi-principal isolation; close software gaps across every role. | Production corpus, real reasoning models, model-benefit evidence and organizational publication governance require actual inputs. |
| Organization identity | Native token authority and owner isolation exist. Verify explicit sign-in/out, capability denial, session expiry, revocation and offline local independence; prepare actual provider/cache/policy checks. Never add Yap credentials or caller-selected identity. | WAM/Entra, tenant registration, audience and conditional-access policy require Windows and IT. |
| UI, accessibility and documentation | Preserve the 30-area baseline; apply the same usability/recovery checks to every added feature. Keep one queue, readable product/setup guidance and source-linked decisions. Preserve historical goals/features and third-party attribution. | Physical focus/input/hit testing remains target-platform work. |
| Release and operations | Audit existing observability, redaction, dependency/provenance, SBOM, packaging, backup/deletion, disaster recovery, deployment and rollback paths. Implement missing software and run disposable rehearsals; perform focused correctness/security review. The [complete skip-free PostgreSQL gate](../../evidence/governed-postgres-ci/2026-10-03/verification.md) is software verified and required in hosted Linux CI. | Production retention, monitoring/SLO approval, target installer and deployment/drills need accountable environments. |
| Repository and storage boundaries | Preserve [ADR 0018](../../adr/0018-three-repo-topology.md) and [ADR 0022](../../adr/0022-google-okf-permission-safe-projections.md). Make deployment/access boundaries work before splitting repositories. Add Redis/object storage/Neo4j only for a measured gap. | Organization access and hosting decisions need their owners; diagrams alone do not justify dependencies. |

## Software-verified increments

The linked records retain each increment's acceptance conditions, before/after behavior, checks and limitations. Coverage applies to that increment only; the workstreams above remain open until all their outcomes are verified and qualified.

| Increment | Coverage | Outcome and evidence |
| --- | --- | --- |
| Original transcript export | 6/6 | Explicit new-file UTF-8 export, retained originals, recovery and focus; [evidence](../../evidence/transcript-export/2026-10-02-verification.md). Corrected/timed/speaker exports and Windows picker qualification remain separate. |
| Personal terminology | 9/9 | Authenticated CRUD, native/UI authority, conflict/replay/recovery and immutable snapshots; [evidence](../../evidence/personal-terminology/2026-10-02-verification.md). Broader administration/projections and provider effectiveness remain open. |
| Damaged imported audio | 4/4 | Fatal packet errors, temporary cleanup, source retention and exact-job isolation; [evidence](../../evidence/imported-audio-integrity/2026-10-02-verification.md#acceptance). Detection of every corrupt raw stream is not claimed. |
| FLAC import | 5/5 | Catalog/picker/UI, canonical duration/content/provenance, integrity/recovery and dependency notices; [evidence](../../evidence/flac-import/2026-10-02-verification.md). Remaining formats and actual inference/Windows playback stay open. |
| Model import source | 4/4 | Bounded regular handle, retained admitted source, hash/atomic publication and cancellation; [evidence](../../evidence/model-lifecycle/2026-10-02-verification.md#offline-import-44-software-outcomes). No weights or loading qualification. |
| Installed model readiness | 5/5 | Linked artifacts cannot become Ready; bounded verification and cancellation preserve markers/data; [evidence](../../evidence/model-lifecycle/2026-10-02-verification.md#installed-artifacts-and-readiness-55-software-outcomes). Actual loading remains unqualified. |
| MP3 source duration | 5/5 | Declared trim/ending reconciled, invalid bounds refused, raw-stream limitation corrected; [evidence](../../evidence/imported-audio-integrity/2026-10-02-verification.md#mp3-source-content-duration). No ASR/alignment qualification. |
| Decoded plaintext ownership | 5/5 | Exclusive private reservation, retained preparation handle, scoped cleanup and crash recovery; [evidence](../../evidence/imported-audio-integrity/2026-10-02-verification.md#decoded-plaintext-ownership). Windows sharing/deletion remains target work. |
| Bounded resampling | 5/5 | Early duration checks, bounded cancellable chunks and complete final interpolation interval; [evidence](../../evidence/imported-audio-integrity/2026-10-02-verification.md#bounded-resampling-and-final-content-interval). Expanded from four after discovering the final-interval gap; no whole-decoder memory qualification. |
| Compressed-source admission | 4/4 | Selected handle/fingerprint retained through both native preparation paths, mutation refusal and nonblocking regular admission; [evidence](../../evidence/imported-audio-integrity/2026-10-02-verification.md#compressed-source-admission-ownership). Same-account adversarial and Windows qualifications remain explicit. |
| Ogg Vorbis import | 5/5 | Exact licensed decoder upgrade, native/recording UI, declared duration/content/provenance and safe refusal/recovery; [evidence](../../evidence/ogg-import/2026-10-02-verification.md). Opus, multiple/chained streams and actual ASR/Windows playback remain outside verified support. |
| Shared terminology | 9/9 | Trusted scope policy, bounded CRUD/discovery, native connection revision binding, read-only controls and frozen snapshots; [evidence](../../evidence/shared-terminology/2026-10-03-verification.md). Automatic directory integration, additional projections and model/Windows effectiveness remain open. |
| Shared design and motion | 7/7 | Original vector/icon family, coherent tokens, responsive Knowledge tasks, contrast/preference controls and bounded motion; [screen review/evidence](../../evidence/design-refresh/2026-10-03/review.md). Full UI completion, latest native Wispr comparison and Windows compositor qualification remain open. |
| Knowledge connections | 6/7 | Model-free permission-filtered browsing, source-cited incoming/outgoing links, native lease/cancellation, accessible graph/list and recovery; [evidence](../../evidence/knowledge-connections/2026-10-03/verification.md). Curator connection proposals are separately verified below; human publication and rebuild recovery remain open. |
| Connection-owned Knowledge | 5/5 | Shared native authority revision, owner-bound submission/rendering, same-owner offline/task drafts and contained delayed cancellation; [acceptance/evidence](../../evidence/connection-owned-knowledge/2026-10-03-verification.md). |
| Curator connection proposals | 6/6 | Exact identified source pair, binary review, atomic noncanonical persistence, native owned-query binding and responsive recovery; [evidence/screens](../../evidence/curator-connections/2026-10-03/verification.md). Actual reasoning and human canonical publication/rebuilding remain open. |
| Accepted correction recovery | 6/6 | Trusted bounded source/chain reopening, preserved damaged history, source-bound offline reading/copying and responsive saved-versus-suggested review; [evidence/screens](../../evidence/accepted-correction-recovery/2026-10-03/verification.md). Earlier-revision selection is locally implemented with integration pending; explicit repair remains open. Accepted UTF-8 export is verified below. |
| Saved connection inspection | 6/6 | Owned persisted references, current-generation endpoint permissions, exact citations and contained native/UI reads; [acceptance/screens/checks](../../evidence/connection-proposal-inspection/2026-10-03/verification.md). Human publication and rebuilding remain open. |
| Accepted correction export | 6/6 | Displayed saved-revision preconditions, native source/history revalidation, exact UTF-8 new-file publication and shared original/accepted export ownership; [evidence/screens](../../evidence/accepted-correction-export/2026-10-03/verification.md). Earlier-revision selection is locally implemented with integration pending; timed/speaker export and Windows picker checks remain open. |
| AAC in M4A/MP4 | 6/6 | Real single-track AAC-LC container timing/content, retained source/durable preparation, bounded refusal/cancellation and responsive Recording/History; [evidence/screens](../../evidence/aac-import/2026-10-03/verification.md). Distribution patent clearance, inference and Windows playback remain open. |
| Owned connection discard | 6/6 | Explicit confirmation, retained provenance, atomic audit, capacity release and uncertain-delivery recovery; [acceptance/screens/integration](../../evidence/connection-proposal-discard/2026-10-03/verification.md). Human publication/rebuilding remain open. |
| Owned connection discovery | 6/6 | Dated owner-only list, strict native receipts, permission-checked selection and confirmed-only cleanup; [acceptance/screens/integration](../../evidence/saved-connection-proposals/2026-10-03/verification.md). Canonical publication/rebuilding remains open. |
| Complete PostgreSQL CI gate | 5/5 | All 23 modules/117 cases, isolated digest-pinned runtime, self-contained fixtures, shared receipt contract and required hosted execution; [evidence/integration](../../evidence/governed-postgres-ci/2026-10-03/verification.md). Model and production-runtime qualification remain separate. |

## Connections: remaining publication outcome

**Status:** 6/7 software outcomes verified; human canonical publication/rebuilding remain open. Broad read-path checks and the Linux application build pass. Permission-filtered topic browsing and bounded incoming/outgoing neighborhoods now run through a model-free authenticated service, strict native connection leases, and responsive graph/list controls. Twenty focused storage/API/configuration cases, seven native cases and ten browser cases pass. Generic agent/MCP responses now preserve source authority; 65 focused agent/storage/API regression cases pass. [Contract](../../specs/knowledge-connections.md) and [screens/evidence](../../evidence/knowledge-connections/2026-10-03/verification.md) record the limits. Preserve the existing compiler/projection/permission owners and eight agent workflows. Curator now implements the typed proposal journey recorded above. Complete human canonical publication and rebuilding before closing the remaining outcome.

- [x] Inventory earlier relationship/compiler/agent work and identify what is executable versus proposed; preserve provenance and approval/publication boundaries.
- [x] Provide a bounded current-generation neighborhood of an authorized concept, with typed edges, source citations and explicit authority; filter both endpoints before traversal and counts.
- [x] Expose only authenticated principal/connection-owned reads through the private service and native bridge; revoked, expired and changed generations cannot return stale relationships.
- [x] Offer a readable connections list and optional bounded graph, keyboard selection, focused source details and responsive layout; avoid a force simulation or animation without a concrete use.
- [x] Retain cancellation, retry, empty/unavailable states and local controls; explain why a relationship exists and provide a useful next action.
- [ ] Connection-building agents produce reviewed proposals with provenance; deterministic providers can verify persistence, rejection, publication and rebuilding without claiming model reasoning quality.
- [x] Verify stored relationships and multi-principal isolation with real Postgres, native/API/browser contract checks and model-free providers; qualify actual model/corpus/Windows separately.

The proposal-boundary increment verifies four outcomes through the existing
governed tool and journal: strict bounded endpoints/type/rationale; exact current
evidence at both endpoints; stable owner-scoped replay/discard without graph
mutation; and real storage/MCP checks. All 14 focused cases pass. Existing stored
proposals remain data. The verified Curator increment in the table connects this contract to its product workflow.
Next complete human review/publication and verify rebuilding. The remaining project
outcome stays open until its complete journey passes.

## Completed supporting work

The table above and linked evidence retain the acceptance conditions for
connection-owned views, Curator proposals and accepted-correction recovery/export.
Their completed checklists are consolidated here; the full feature inventory,
open questions and execution record remain. Earlier correction-history selection
is locally implemented with integration pending. Timed/speaker exports, explicit
damaged-history repair and target qualification remain open.

Canonical publication still requires a trusted `knowledge.curator` reviewer,
reviewed repository/source-admission provenance and complete relational/vector
projection before activation. Inspection or a proposal reference cannot supply
that approval. Human publication and rebuild recovery remain available software
work; they are not closed by the model qualification boundary.

## Completed increment: readable documentation and main consolidation

**Status:** Software verified and merged. User authorized a documentation sub-agent, consolidation
of existing branches/PRs onto `main`, and committing/pushing every verified
iteration. [Consolidation evidence](../../evidence/repository-consolidation/2026-10-03/verification.md)
retains the branch snapshot and dispositions. This does not close unresolved
issues or promote unqualified models/platforms.

- [x] Make the root README, documentation index and server README readable entry points; retain product goals/features, operational requirements and complete historical evidence.
- [x] Preserve every original branch tip before cleanup; close stale dependency PRs and retire historical branches without losing their commits.
- [x] Commit and push the verified development backlog and documentation as reviewable iterations; integrate through required exact-head checks, then remove the temporary integration branch.
- [x] Repair the current locked dependency audit's high advisories through supported upstream releases, retaining license/provenance checks and avoiding audit suppression.
- [x] Inspect the official Tauri/Tao update for issue #92; verify removal of the affected source path in software, keeping actual Windows RDP/session-lock reproduction/recovery as an explicit target check before issue closure.
- [x] Renew the relevant native/frontend/browser/build/contracts, review changes and record the actual `main` head and remaining qualification limits.

[PR #199](https://github.com/ZoOtMcNoOt/yap/pull/199) merged to
`dbdd8d1752f260ca37623b74f0f87d86241175cc`, with the identical tree tested at
`02da8f11`. [Run 532](https://github.com/ZoOtMcNoOt/yap/actions/runs/37118650222)
passed all six jobs. The completed integration branch was retired; `main` is
the shared integration branch. Issue #92 and the full project goal remain open.

## Completed increment: core server dependency integrity

**Status:** Software verified and merged. Auditing the exact Python lock exposed published
advisories in PyJWT, cryptography and httpx2. Repair the supported core before
continuing human publication/rebuild recovery. Model runtime overlays have a
separate dependency boundary and cannot inherit a clean core result.

- [x] Lock compatible published fixes, preserving hashes, strict identity policy and third-party licenses.
- [x] Add a repeatable core audit covering every locked registry version, including platform markers and optional/development groups; refuse findings, skipped packages and unavailable evidence without ignores.
- [x] Verify valid identity flows, malformed token rejection, MCP and the full portable server suite without models; record remaining runtime findings separately.
- [x] Review, commit/push and integrate through all green exact-head jobs, then retire the temporary branch and continue the software queue.

[Core server evidence](../../evidence/server-dependencies/2026-10-03/verification.md)
records the four patched versions, complete 40-version audit, 53 identity cases,
1,640 portable server passes (96 declared exclusions) and 177 governed contracts
with no skips. Historical model receipts keep their original dependency hashes;
changed dependencies require renewed qualification. NeMo overlay findings remain
open and cannot inherit the clean core result.

[PR #201](https://github.com/ZoOtMcNoOt/yap/pull/201) merged at `85d87c0f` with
the identical tree tested at `7622a5a6`; all six jobs in
[run 536](https://github.com/ZoOtMcNoOt/yap/actions/runs/37121648208) passed.
The iteration branch and superseded Dependabot PR #200 are retired; the latter's
exact tip remains under `archive/dependency-proposal-200-2026-10-03`.

## Awaiting integration: export a connection review package

**Status:** 5/6 local software outcomes; exact-head integration pending. Owners can
export an inspected candidate and its exact evidence into human Git review through
the existing native connection and new-file owners. [Verification and screens](../../evidence/connection-review-export/2026-10-03/verification.md)
retain the checks and limits. The
package remains a proposal; authenticated canonical review, complete embedding
projection, publication and rebuilding remain separate open outcomes.

- [x] Define a bounded, versioned review package containing the immutable proposal reference, generation, typed candidate and two exact source revision/hash/span citations. Keep proposed rationale distinct from quoted evidence; include no credentials or inferred approval.
- [x] Build it from current authenticated inspection through the existing server route. Native code validates the receipt and displayed proposal/generation under the current main-window connection lease; renderer content cannot become source authority.
- [x] Offer an explicit new-file destination. Revalidate after selection, preserve existing files and internal data, and refuse stale, revoked, changed-owner or discarded evidence before publication. Retain write ownership through completion; do not report cancellation while a write can continue.
- [x] Connect a readable, keyboard-accessible export action to Review proposals. Success, cancelled picker, unavailable/expired connection, retained uncertainty, failed destination and account changes keep local controls and source navigation usable; inspect narrow and wide layouts.
- [x] Verify actual native transport/file invariants and browser recovery with deterministic evidence, using existing dependencies and retained source provenance. Document how the package enters human Git review and its limits; it does not mutate the canonical graph.
- [ ] Review/push and integrate through every exact-head job, retain the reviewed head and retire the branch. Continue actual canonical publication/rebuilding and the full software queue.

GitHub rejected the implementation push; its connector reports disconnected.
Restore access before hosted checks/merging. Local development remains available;
`9cb8d310` retains the verified implementation and the evidence records the full
221-pass Linux browser regression (one declared Windows-only skip).

## Awaiting integration: verify a review package against its source bundle

**Status:** 4/5 local software outcomes; integration waits for GitHub access.
The read-only operator command checks exported citations using the existing
bounded artifact reader and OKF compiler. It verifies the complete selected
bundle/generation and both exact quotes. Source matching supplies no access
or approval; the human reviewer still assesses provenance and rationale.

- [x] Strictly read the bounded version-1 exported package, rejecting duplicate/extra fields, malformed identity, unsupported status and inconsistent endpoints/citations.
- [x] Compile an explicitly selected local OKF bundle with an explicit tenant/revision; require the exact generation and compare both file-byte hashes, parsed-body Unicode spans, metadata and quote text.
- [x] Return a content-free source-match receipt through a documented command. Preserve every file; open no credentials, server/SQL connections or embedding/model providers. Source matching cannot authorize review, admission or publication.
- [x] Verify actual files, Unicode/frontmatter hashing, changed generations/quotes/revisions, malformed packages, linked/escaped/missing sources, CLI success/refusal and no file mutation without model hardware.
- [ ] Record actual software results, commit the verified iteration and push/integrate when GitHub access returns. Canonical human review, complete projection and activation remain open.

[Source-check evidence](../../evidence/connection-review-source-check/2026-10-03/verification.md)
records 29 focused, all 185 governed portable and 1,648 isolated full-server
passes (114 declared exclusions), including actual files and CLI execution.
The checker is read-only; approval and activation remain open.

## Awaiting integration: preserve published vectors through rollback

**Status:** 4/5 local software outcomes; exact-head integration pending.
The embedding writer now freezes every previously published projection using
durable activation history and the existing tenant lock. Replacement no longer
permits a vector overwrite of a retained rollback target. Staged preparation
remains usable; no model or publication authority is added.

- [x] Reproduce an overwritten retained projection against actual PostgreSQL, then freeze previously published vectors using durable activation history alongside the active pointer.
- [x] Keep initial staged embedding preparation usable; refusals preserve vectors, model identity, active state and activation history. Rollback restores the original projection.
- [x] Verify a concurrent writer waits for tenant activation, then refuses after publication rather than overwriting the newly published generation.
- [x] Run the complete skip-free disposable PostgreSQL gate with the expanded population and applicable portable/lint/documentation regressions; distinguish synthetic vectors from qualified inference.
- [ ] Record the reviewed result and commit it locally; push/integrate through all six exact-head checks when GitHub access returns. Continue canonical review/rebuilding and the complete software queue.

[Rollback evidence](../../evidence/knowledge-rollback-integrity/2026-10-03/verification.md)
records both original-code failures, eight real ledger passes, all 119
skip-free disposable database cases and all 185 governed portable passes.

## Awaiting integration: read and export earlier accepted corrections

**Status:** 6/7 software outcomes checked locally; reviewed hosted integration pending.
Owners can now select, read, copy and export an earlier accepted revision offline.
The existing native history/read/export owners validate the complete chain and
return only the selected text plus a bounded revision count. Original transcripts,
latest acceptance and all saved revisions remain unchanged. New acceptance resets
selection to Latest; a repeated selection keeps its pending read alive.

- [x] Read an explicitly selected revision from the complete validated chain, bound to the current original source. Reject invalid/missing selection and damaged, linked or inconsistent history without repair or deletion.
- [x] Export that displayed revision through the shared new-file owner, rechecking source, selected text/hash and complete history before publication; preserve original files, all revisions and existing destinations.
- [x] Offer a compact keyboard-accessible revision selector when history has multiple revisions. Latest remains the initial choice; reading, copying and export work offline without running a model or accepting edits.
- [x] Keep source/selection changes and late reads isolated, retain explicit retry and original access on failure, and prevent revision changes while a native export is active.
- [x] Refresh the latest accepted history after every new acceptance, including identical corrected text under a new revision. Use publication identity rather than its text hash alone.
- [x] Verify native files and exact Unicode text, malformed receipt/selection refusal, browser recovery/focus and narrow/wide screens; run applicable units/build/contracts and the complete browser regression.
- [ ] Record the result and commit the verified iteration. Push/integrate through the required exact-head checks when GitHub access returns; timed/speaker export, history repair and target qualification remain open.

[Selection evidence and screens](../../evidence/accepted-correction-selection/2026-10-03/verification.md)
record 1,375 native units + 27 integrations, 404 frontend units and all 231
Linux browser passes (one declared Windows-only skip), plus the reproduced
same-text acceptance and repeated pending-selection failures and their fixes.

## Awaiting integration: truthful transcript export recovery

**Status:** 5/6 software outcomes checked locally; reviewed hosted integration pending.
Original and accepted exports now explain unconfirmed write/join completion and
ask the user to inspect the selected destination before retry. Original receipts
must prove saved/cancelled status; malformed or misbound receipts cannot claim
completion. Focus-owned error visibility keeps narrow feedback readable while
leaving another chosen control's focus and scroll position alone.

- [x] Keep definite precondition refusals and genuine picker cancellation precise; generic write/join errors explain unconfirmed completion and destination inspection before retry.
- [x] Validate original success/cancellation receipts; accepted misbound receipts explain uncertainty without claiming that no file was saved.
- [x] Retain source/revision text, copy and explicit retry beside an unconfirmed export. Never retry automatically or claim success/cancellation without its receipt.
- [x] Verify actual post-commit errors retain exact destination bytes and existing-file protection; preserve shared worker admission and original/history data.
- [x] Exercise malformed receipts and original/accepted export recovery, keyboard focus and responsive alerts; run applicable native/frontend/build/contracts and retain actual evidence.
- [ ] Commit the verified iteration and push/integrate through all six reviewed exact-head checks when GitHub access returns. Physical Windows and the entire remaining queue stay open.

[Recovery evidence and screens](../../evidence/transcript-export-recovery/2026-10-03/verification.md)
record the real Linux post-commit error, malformed receipt and hidden-alert
reproductions; 1,377 native units + 27 integrations, 404 frontend units, all 38
related browser cases, production build and release checks pass. Complete
canonical human publication/rebuilding and supervised ASR remain available
software work; timed/speaker export, history repair and target checks stay queued.

## Current local increment: retain the admitted export directory

**Status:** 5/6 outcomes verified locally; reviewed exact-head integration pending.
A real Linux regression reproduces an external export parent replaced by a link
to internal Yap data. Native directory ownership now retains the admitted folder
through creation, exclusive publication, sync and cleanup. Exact bytes,
source/history checks, existing-file protection and uncertainty guidance remain
intact. [Directory evidence](../../evidence/export-directory-ownership/2026-10-03/verification.md)
records actual checks; Windows and hosted integration remain pending.

- [x] Bind the canonical, external destination to native directory identity before the source recheck; refuse changed/linked/replaced directories without publishing into their substitutes.
- [x] Keep creation, exclusive publication, directory sync and staging cleanup on that admitted directory. Windows directory leases retain ancestor identities; Unix operations use the owned directory descriptor.
- [x] Preserve exact UTF-8 bytes, no-replace behavior, unrelated staging, source/history and explicit worker ownership. Unknown completion retains the existing inspection guidance.
- [x] Reproduce and verify selected-parent/ancestor substitution and publication-time replacement with actual files; changed paths never create or clean files in their replacements.
- [x] Run applicable native/transport/frontend/export/contracts and inspect changes; record Linux, hosted Windows and physical-target boundaries accurately.
- [ ] Commit and push the verified iteration; integrate only reviewed six-job green exact heads when GitHub access returns. Continue the entire software queue.

Final Linux checks pass: 1,383 native units + 27 integrations, all 36 related
browser export flows, 72 release contracts (67 passes/five Windows-only skips),
Linux lint and 14 documentation/license/provenance/population checks. Existing
renderer/full-browser receipts stay dated baselines. No hosted Windows, physical
picker/filesystem, model or enterprise behavior is qualified. Push and reviewed
integration remain pending access; the entire software queue continues.

## Execution record

The [dated execution history](../../archive/implementation-evidence/2026-10-02-project-hill-climb-history.md) retains every iteration, evidence link and next action recorded at the time. Those next actions are historical; the current increment above determines what to do now. Append new iteration receipts there and keep this queue current.

Attribute project work to Grant McNatt. Preserve third-party attribution/provenance; do not add AI branding or coauthor trailers.
