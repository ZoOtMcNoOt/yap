# Current status

**Updated:** 2026-10-04. **Project owner:** Grant McNatt.

## Current goal

The [project hill-climbing goal](plans/active/2026-10-02-yap-project-hill-climb.md) is active across the entire [roadmap](roadmap/ROADMAP.md): finish and verify all available software work, then qualify actual model, Windows and enterprise behavior. Original/accepted-transcript export, personal/shared terminology, damaged-audio rejection, FLAC, Ogg Vorbis and single-track AAC-LC M4A/MP4 import are implemented and checked in the cloud; broader terminology and recording-format work remain open. Format expansion, supervised ASR/live integration and release/operations remain in the same queue. All 27 open questions and conditional directions retain their source-linked dispositions.

The completed UI milestone verified **30/30 supported UI acceptance areas**, with fixture/native boundaries in the [acceptance evidence](evidence/ui-completion/2026-10-02-acceptance.md). That subset does not establish project-wide completion or authorize production promotion.

## Development environment

The managed cloud workspace has four CPU cores and 16 GiB RAM. This session has
no GPU, company VPN or private-server credentials. Package networking and GitHub
fetch/push have been exercised; environment metadata alone does not establish
enterprise network policy or private-node readiness.

The fresh successor restored and exercised locked Python dependencies, Node
24.19/pnpm 11.7.0, Rust 1.96 with rustfmt/Clippy, PowerShell 7.6 and Docker. The
isolated Ubuntu server and digest-pinned PostgreSQL suites pass. Earlier receipts
below retain the GTK/WebKit/Chromium/native setup observed in the predecessor;
this fresh snapshot has not renewed that local desktop toolchain/build claim.
Hosted Windows software checks are separately recorded below. See
[cloud development](runbooks/cloud-development.md) for the reproducible setup.

## Earlier local verification baseline

These recorded local checks precede the current increment. Later merged receipts
and current export checks are linked below.

| Check | Recorded result |
| --- | --- |
| Desktop frontend unit tests | 393 passed, 2 declared Windows-only skips |
| TypeScript/Vite production build | Passed |
| Browser workflows with system Chromium | Pre-correction baseline: 189 passed, 1 Windows-only skip; 53 related journeys renewed on corrected code |
| Linux Tauri native debug build, no installer bundle | Passed; platform-specific unused-code warnings remain |
| Desktop Rust tests | 1,364 unit + 27 integration passed, 11 declared model/hardware ignores |
| Orchestrator release build and strict Clippy | Passed |
| Orchestrator tests under Tini | 54 tests passed, including all 8 supervised-service integration cases |
| Portable Python server suite in isolated Ubuntu | 1,640 passed, 104 platform/fixture/database skips (1,744 total) |
| Local Postgres/pgvector knowledge suite | 19 passed, no skips; Postgres 17.11 and pgvector 0.8.0 development runtime |
| Personal/shared terminology database, authenticated HTTP and policy/configuration | 28 passed, no skips; full focused correction/OpenAPI/startup checks total 53 passed |
| Proposal discard, inspection and related PostgreSQL/API regression | 52 passed, no skips; final ten discard/API cases renewed |
| Governed knowledge portable suite | 177 passed, no skips; includes changed-dependency qualification refusal |
| Python Ruff | Passed |
| Complete core Python dependency audit | 40 locked versions, no known findings or skips; strict gate added to CI |
| Setup script repeated in the same workspace | Passed |
| Native Linux headless launch with mapped WebKit helpers | Remained running for 12 seconds; startup smoke only |
| Documentation contracts | 4 passed on the final working tree |
| Model provenance checks | 3 passed in the environment baseline |
| Remote-ledger restart/idempotency | 4 passed on the final working tree |
| Native rustfmt and diff whitespace | Passed |
| Shipped dependency inventory/license checks | 3 passed |

[Hosted run 541](https://github.com/ZoOtMcNoOt/yap/actions/runs/37127757876)
passed all six jobs on `853261129f3c720d97ee2b5556fae00f8934da3e`: Windows native
1,368 units + 27 integrations (11 declared ignores), strict Clippy, native WDIO
and both connector runtimes; frontend 395 units, all 193 browser workflows and
71 release contracts; portable Windows server 1,601 passes with 143 declared
exclusions; the 40-version core audit; Linux identity and all 54 service-lifecycle
cases. [PR #202](https://github.com/ZoOtMcNoOt/yap/pull/202) merged to
`b32e7b7ad603b26c1606dcee8c2e3bd5efe6815a` with the identical tested tree; its
branch is retired. [Discard evidence](evidence/connection-proposal-discard/2026-10-03/verification.md)
retains the reproduced review defects, corrections, local real-database checks,
platform exclusions and screen review. The existing frontend policy retains one
low-severity finding. These results do not qualify inference or enterprise operation.

Earlier dependency/consolidation results remain in the [desktop evidence](evidence/dependency-refresh/2026-10-03/verification.md)
(PR #199, run 532) and [core server evidence](evidence/server-dependencies/2026-10-03/verification.md)
(PR #201, run 536). Historical receipts and their repairs remain preserved.

## Changes made to enable development

- Windows-only Rust dependencies are scoped to the Windows target, so the native client compiles on Linux.
- Playwright warmup and workers accept an explicitly selected browser. Cloud setup uses system Chromium and disables video encoding; failure traces/screenshots remain enabled.
- Provider supervision inventories child processes through standard procfs parent identities. It no longer requires the optional task/children kernel interface; identity changes and unreadable inventories fail closed. All 21 focused supervisor tests passed in the isolated runtime.
- Native tests account for Windows versus Linux directory resolution, no-follow errors, and lease revocation after Unix metadata changes. Production data/source protections remain unchanged.
- Deeply nested Curator responses remain rejected regardless of the host Python recursion limit. The language-preflight fixture now creates private working directories explicitly.
- Setup, shell environment, and isolated server checks are reusable repository commands. The root README, documentation index, roadmap, and active plan now share one execution order.

## Current increment

Reviewed embedding generation now connects explicit source preparation to
publication through `POST /v1/knowledge/embedding-preparations`. Deployment
selects one already-running numeric-loopback provider/model/revision; the
admitting curator supplies only a stored generation reference. Complete-source
validation precedes provider dispatch. Complete 768-dimensional vectors and the
success audit commit atomically, preserving source/proposals/active/history.
Replay validates without another provider call. Published, conflicting, partial,
foreign-owned and damaged projections refuse. Local checks pass: 161 required
real PostgreSQL cases/26 modules and 209 portable cases without skips; isolated
full server 1,672 passes/158 declared exclusions (1,830 total). The full source →
embedding → publication → permission-filtered vector/read → rollback journey
uses deterministic local HTTP vectors and real SQL. Actual model quality and
enterprise identity are unqualified. Six of seven bounded outcomes are locally
verified; reviewed exact-head hosted integration remains pending.
[Evidence](evidence/knowledge-embedding-generation/2026-10-04/verification.md)
retains limits and the original missing route. Desktop rebuild controls, larger
rebuilds and every roadmap workstream remain open.

Retained-generation rollback merged through [PR #206](https://github.com/ZoOtMcNoOt/yap/pull/206)
as `d2d3685bdb5d45e6387257113ebe4c27c197c42c`, with the identical tree tested at
`85ce2ada`. [Run 552](https://github.com/ZoOtMcNoOt/yap/actions/runs/37222318769)
passes all six required jobs; review reports no findings. All six bounded rollback
outcomes are software verified. The tested head is tagged, and the completed
branch is retired. [Integration evidence](evidence/knowledge-rollback-api/2026-10-04/integration.md)
retains model/enterprise/platform limits and the local real SQL receipt.

The recovered backlog and review corrections merged through [PR #205](https://github.com/ZoOtMcNoOt/yap/pull/205)
as `82ea8362ee53220218b78926b762ab707ebaf2a9`, with the identical tested tree
at `6c1c5e1f`. [Run 551](https://github.com/ZoOtMcNoOt/yap/actions/runs/37222033380)
passes all six jobs: Windows frontend 406 units/all 238 browser flows/72 release
contracts; native 1,380 units + 27 integrations/11 declared hardware ignores;
Windows server 1,625 passes/180 declared exclusions; Linux all 144 required
real PostgreSQL cases without skips, identity and lifecycle; native WDIO smoke.
[Integration evidence](evidence/connection-review-export/2026-10-04/integration.md)
retains reviewed corrections, exact-tree comparison and the preserved tag.
The completed feature branch is retired. These are hosted software checks,
not physical Windows/model/enterprise qualification.

GitHub fetch/push and the app connection are restored. This fresh app chat
recovered the pushed checkout, wrote a readiness receipt and then archived its
idle predecessor. Earlier disconnected-app/push/CLI stream observations remain
historical in the preserved handoff. The whole project goal stays active.

## Earlier increments integrated through PR #205

Embedding preparation now validates current stored source, admission and all four
counts under the tenant lock before vector/model writes. Prepared keys must
match validated chunks; invalid storage refuses without repairs. Eleven actual
ledger cases, all 144 required database and 201 governed portable cases pass;
full isolated server passes 1,664 with 141 declared exclusions.
[Evidence](evidence/knowledge-embedding-source-integrity/2026-10-04/verification.md)
retains the reproduced successful write over changed source and observed lock-wait
regression. This does not verify vector provenance or add an embedding provider;
actual generation and complete product rebuild integration remain open.


Curators can inspect and explicitly admit/stage a deployment-selected reviewed
source through authenticated HTTP. The bounded pinned manifest and compiled
identity prevent client source selection and source drift. Admission, staging and
audit commit together; replay preserves existing vectors and active/history.
All 142 required database and 201 governed portable cases pass without skips;
full isolated server discovery passes 1,664 with 139 declared exclusions.
[Evidence and operator guidance](evidence/knowledge-source-preparation/2026-10-04/verification.md)
retain configuration, recovery and the reproduced Linux source-read race.
Embedding preparation and complete product rebuild integration remain open.


Rebuild staging retries now refuse inconsistent descriptors and all four
stored generation counts. Valid staged retries work before embeddings; valid
active retries preserve vectors/history. Nine actual SQL ledger cases, all 130
required database and 192 governed portable cases pass; full isolated server
passes 1,655 with 127 declared exclusions. [Evidence](evidence/knowledge-staging-descriptor/2026-10-04/verification.md)
retains the failure and limits. Source preparation now has its own verified operator flow; complete product
rebuilding remains open.


[Reviewed publication](specs/knowledge-publication.md) now gives authenticated
curators explicit HTTP inspection and activation of their own admitted,
prepared repository generations. Expected-active comparison, complete
validation/replay and atomic success audit are verified locally: all 129 required
database and 192 governed portable cases pass without skips; the full isolated
server suite passes 1,655 cases with 126 declared exclusions. Hosted integration
is pending. Git review, embedding preparation,
canonical rebuilding and desktop product integration remain separate open work;
the overall publication outcome stays open. [Evidence](evidence/knowledge-publication/2026-10-04/verification.md)
records the scope and checks. End-to-end rebuilding remains in the active queue.

The [export-directory increment](plans/active/2026-10-02-yap-project-hill-climb.md#awaiting-integration-retain-the-admitted-export-directory)
retains the admitted folder for original, accepted-correction and connection-review
exports. Actual Linux files reproduced a parent replacement redirecting an export
into internal Yap data. Directory ownership fixes that redirection; 1,383 native
units and 27 integrations pass, with 11 declared model/hardware ignores. All 36
related browser export cases, Linux lint and release/documentation checks pass.
Five of six outcomes are locally verified; Windows and reviewed hosted integration
remain pending in the [directory evidence](evidence/export-directory-ownership/2026-10-03/verification.md).

The earlier [completion recovery](evidence/transcript-export-recovery/2026-10-03/verification.md)
increment retains its passing 1,377 + 27 native, 404 frontend, production-build
and 38 related-browser checks. Those dated checks remain separate from the new
directory increment; neither server publication nor directory ownership changes renderer code.

**Earlier accepted corrections** now support offline reading, copying and export.
The selector preserves original transcripts, latest acceptance and saved history;
late reads and repeated selection retain their owner. That increment's checks pass with
1,375 units and 27 integrations (11 declared model/hardware ignores); frontend
units pass 404 cases with two Windows-only skips, and the production build passes.
All 27 related browser cases and the complete 231-case Linux browser regression
pass, with one declared Windows-only island skip (232 total).
[Evidence and screens](evidence/accepted-correction-selection/2026-10-03/verification.md)
retain the checks and limits. All retained iterations are now pushed; reviewed
exact-head hosted integration remains pending.

[Connection review export](evidence/connection-review-export/2026-10-03/verification.md)
carries the exact proposal and citations into human Git review. Five local software outcomes pass;
the complete Linux browser suite passes with 221 cases and one declared Windows-only skip.
Canonical publication and generation rebuilding remain separate open outcomes.

[Local source checking](evidence/connection-review-source-check/2026-10-03/verification.md)
verifies exported evidence against an explicitly selected complete OKF bundle.
All 185 governed portable cases pass without skips. The receipt proves source
matching; authorized review and activation remain separate.

[Rollback integrity](evidence/knowledge-rollback-integrity/2026-10-03/verification.md)
now protects published vectors after replacement. Eight real ledger checks,
all 119 current database cases and all 185 governed portable cases pass locally
without skips. Reviewed exact-head integration remains pending.

The [complete PostgreSQL gate](evidence/governed-postgres-ci/2026-10-03/verification.md)
is merged and **5/5 software verified**. [PR #204](https://github.com/ZoOtMcNoOt/yap/pull/204)
and [run 547](https://github.com/ZoOtMcNoOt/yap/actions/runs/37137161514) pass all six jobs,
including every one of the 117 real database cases without skips. Main has the
identical tested tree, the reviewed head is retained and its branch retired.

Owned connection discovery is merged and **6/6 software verified**. [PR #203](https://github.com/ZoOtMcNoOt/yap/pull/203)
and [run 544](https://github.com/ZoOtMcNoOt/yap/actions/runs/37133293613) pass all six jobs:
Windows native 1,370 units + 27 integrations, frontend 398 units, all 205 browser
cases, native WDIO, server, identity and service lifecycle. Main has the identical
tested tree; the reviewed head is retained and its branch retired.
[Evidence](evidence/saved-connection-proposals/2026-10-03/verification.md) keeps
local, hosted and physical-target checks separate. Canonical publication/rebuilding
and the full project goal remain open. Issue #92 still needs actual Windows
RDP/session-lock responsiveness qualification.

## Recent verified work

The [core Python dependency increment](evidence/server-dependencies/2026-10-03/verification.md)
is verified and merged through PR #201. Only PyJWT, cryptography, httpx2 and
httpcore2 versions changed; all 40 core versions pass the strict audit. The
completed branch and superseded PR #200 are retired, with the latter's tip
preserved under `archive/dependency-proposal-200-2026-10-03`.

NeMo's pinned upstream constraints exclude the published Hydra/Lightning fixes;
those overlay findings remain open. A clean core audit does not qualify a model
runtime or its base image. Historical model receipts retain their original JSON
and hashes; current dependencies require renewed qualification. The linked core
evidence records the exact upstream constraints and inspected source hash.

[AAC M4A/MP4 import](evidence/aac-import/2026-10-03/verification.md) verifies six
software outcomes through existing native selection and preparation owners.
Actual encoded fixtures retain presentation duration, content and original files;
unsupported/damaged containers refuse with scoped cleanup. Recording/History and
360 px preparation/retry work without models. AAC distribution patent clearance,
actual inference and Windows playback remain separate release/target checks.

Documentation entry points are refreshed; the complete prior server narrative
remains in a linked archive. [Repository consolidation](evidence/repository-consolidation/2026-10-03/verification.md)
preserves all 27 original branch tips under one archive tag, closes nine stale
dependency PRs and removes 26 branches. Development work and documentation are
merged through [PR #199](https://github.com/ZoOtMcNoOt/yap/pull/199) after all six
exact-head jobs passed. Its temporary branch is retired; `main` remains the
shared integration branch.
The [dependency refresh](evidence/dependency-refresh/2026-10-03/verification.md)
removes the 11 high npm findings: one low finding remains, with no ignores. Rust
has zero vulnerability-class findings and two reviewed warnings. The working
lockfile uses official Tauri 2.12.1 / Tao 0.37.1, whose Windows source removes the
global mutex implicated in [issue #92](https://github.com/ZoOtMcNoOt/yap/issues/92).
That issue stays open until actual Windows RDP/session-lock checks pass.


[Saved connection inspection](evidence/connection-proposal-inspection/2026-10-03/verification.md)
connects persisted Curator references to Review proposals, with exact direction,
rationale and reauthorized source excerpts. Reading invokes no model and changes
no graph/proposal data. Unknown/hidden/foreign references share an unavailable
result; stale knowledge refuses inspection. Account changes hide private evidence;
owned offline drafts, cancellation and new-proposal handoffs retain their existing
owners. All six software outcomes are verified; the real Postgres/service
regression passes 102 cases. Human publication and rebuild recovery remain open.

[Accepted correction recovery](evidence/accepted-correction-recovery/2026-10-03/verification.md)
and [UTF-8 export](evidence/accepted-correction-export/2026-10-03/verification.md)
retain six verified outcomes each for trusted offline reopening, source/history
revalidation, exact new-file publication and preserved originals/history.
[Earlier-revision selection](specs/accepted-correction-history.md) is locally
implemented with hosted integration pending. Timed/speaker exports and explicit
damaged-history repair remain open.

The [shared design](evidence/design-refresh/2026-10-03/review.md) retains seven
verified outcomes and the island. [Connections](evidence/knowledge-connections/2026-10-03/verification.md)
remains six of seven overall outcomes; [Curator](evidence/curator-connections/2026-10-03/verification.md)
verifies its six proposal outcomes. Actual reasoning, authorized human canonical
publication and rebuilding remain open. Further formats, correction-history repair and supervised ASR/live work remain in the active queue.

[Connection-owned Knowledge views](evidence/connection-owned-knowledge/2026-10-03-verification.md)
verify five outcomes for native revision binding, private-state clearing and
same-owner/offline drafts. Earlier increments retain their [evidence](evidence/README.md):
original export, personal/shared terminology, imported-audio integrity,
MP3/FLAC/Ogg Vorbis support and model-source/readiness ownership. Automatic
directory integration and broader projections remain open. The [single project
queue](plans/active/2026-10-02-yap-project-hill-climb.md) retains every workstream;
the four-hour audio safety ceiling is not a qualified recording-duration claim.

## Remaining verification boundary

The cloud shell explicitly selects the repository-local pnpm store, so dependency-license checks use the same package index as installation. Linux-specific unused-code warnings remain; the desktop native build is not a strict-Clippy result.

Supported software journeys now cover setup, recording → history → correction, all Knowledge roles, history maintenance, and Settings/Help recovery. Work retains the selected source and pending drafts; completion never forces navigation; raw transcripts and native authorization remain intact. Shared citations, cancellation controls and modal focus handling reduce duplicated presentation. [Mobbin references](evidence/ui-completion/2026-10-02-design-references.md) include screens, flows and website sections.

Windows-only unit exclusions cover native WDIO main-window recovery and exact saved-bundle path ownership. The one browser exclusion covers collapsed-at-load island hover behavior in Windows Chromium. Model/native/enterprise limitations from the baseline remain unchanged. The [qualification handoff](evidence/ui-completion/2026-10-02-acceptance.md#qualification-handoff) names the inputs and pass conditions for local models, language switching, ASR/speakers, real correction/knowledge round trips, capacity, Windows interaction, identity/networking and installation.

Linux compilation does not support Windows-only model load guards, text injection, native shortcut enrollment, WAM, or installer behavior. Those need the Windows target. Real model quality/performance, GPU residency/capacity, sustained load, and enterprise connectivity need their actual environments. Simulated outputs do not qualify inference.

## Historical evidence

Earlier detailed qualification and merge receipts remain in the [2026-08-14 status snapshot](archive/implementation-evidence/current-status-2026-08-14.md), [roadmap snapshot](archive/implementation-evidence/roadmap-2026-08-14.md), and [evidence index](evidence/README.md). The [current architecture](architecture/CURRENT-ARCHITECTURE.md), accepted ADRs, contracts, security boundaries, and third-party provenance remain applicable.
