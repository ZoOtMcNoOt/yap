# Current status

**Updated:** 2026-10-03. **Project owner:** Grant McNatt.

## Current goal

The [project hill-climbing goal](plans/active/2026-10-02-yap-project-hill-climb.md) is active across the entire [roadmap](roadmap/ROADMAP.md): finish and verify all available software work, then qualify actual model, Windows and enterprise behavior. Original/accepted-transcript export, personal/shared terminology, damaged-audio rejection, FLAC, Ogg Vorbis and single-track AAC-LC M4A/MP4 import are implemented and checked in the cloud; broader terminology and recording-format work remain open. Format expansion, supervised ASR/live integration and release/operations remain in the same queue. All 27 open questions and conditional directions retain their source-linked dispositions.

The completed UI milestone verified **30/30 supported UI acceptance areas**, with fixture/native boundaries in the [acceptance evidence](evidence/ui-completion/2026-10-02-acceptance.md). That subset does not establish project-wide completion or authorize production promotion.

## Development environment

The managed cloud workspace provides four CPU cores, 16 GiB RAM, and an initially available 30 GiB disk budget. It has no GPU, VPN, private-server credentials, or outbound cloud identity. Enforced networking permits package downloads; private-node access is not configured.

Installed and exercised: Node 24.19, pnpm 11.7.0, Python 3.12.14 with locked uv dependencies, Rust 1.96 with Clippy/rustfmt, PowerShell 7.6, GTK/WebKit/audio/tray build libraries, CMake, Chromium, Docker, Xvfb, and Tini. Native dependencies are installed into a user-owned prefix. See [cloud development](runbooks/cloud-development.md) for setup and commands.

## Verification

| Check | Current result |
| --- | --- |
| Desktop frontend unit tests | 393 passed, 2 declared Windows-only skips |
| TypeScript/Vite production build | Passed |
| Browser workflows with system Chromium | 189 passed, 1 declared Windows-only skip; 52 related journeys renewed after handoff correction |
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

[Hosted run 536](https://github.com/ZoOtMcNoOt/yap/actions/runs/37121648208)
passed all six jobs on `7622a5a654193dfd23c54219177fa72e73c35323`: 1,367 Windows
native units + 27 integration cases (11 declared ignores), native WDIO and both
actual connector runtimes; 392 frontend units, all 184 browser workflows and 71
release contracts; 1,601 portable Windows server cases with 135 declared
exclusions; the complete 40-version core audit; Linux identity and all 54
orchestrator cases. [PR #201](https://github.com/ZoOtMcNoOt/yap/pull/201) merged
to `85d87c0fc7bebbeff877c97a8c6f1fc77ff0d7be` with the identical tested tree.
The [core server evidence](evidence/server-dependencies/2026-10-03/verification.md)
retains local checks, the earlier checkout failure and its verified repair.
Earlier [run 532](https://github.com/ZoOtMcNoOt/yap/actions/runs/37118650222)
closed the desktop dependency/consolidation work through PR #199; its
[evidence](evidence/dependency-refresh/2026-10-03/verification.md) preserves those
dated results and repairs.
Nine new inspection database/HTTP
cases join the prior 51 new-feature database exclusions, all verified against
real local Postgres. The isolated suite retains 36 preexisting skips. The
expanded regression passes 102 cases, including existing Curator journal checks.
The local orchestrator release build and headless startup smoke retain their
earlier environment receipts. Hosted run 536 establishes exact-head software
verification; neither local nor hosted checks establish model or enterprise
qualification.

## Changes made to enable development

- Windows-only Rust dependencies are scoped to the Windows target, so the native client compiles on Linux.
- Playwright warmup and workers accept an explicitly selected browser. Cloud setup uses system Chromium and disables video encoding; failure traces/screenshots remain enabled.
- Provider supervision inventories child processes through standard procfs parent identities. It no longer requires the optional task/children kernel interface; identity changes and unreadable inventories fail closed. All 21 focused supervisor tests passed in the isolated runtime.
- Native tests account for Windows versus Linux directory resolution, no-follow errors, and lease revocation after Unix metadata changes. Production data/source protections remain unchanged.
- Deeply nested Curator responses remain rejected regardless of the host Python recursion limit. The language-preflight fixture now creates private working directories explicitly.
- Setup, shell environment, and isolated server checks are reusable repository commands. The root README, documentation index, roadmap, and active plan now share one execution order.

## Current increment

The [execution queue](plans/active/2026-10-02-yap-project-hill-climb.md#current-increment-owner-controlled-proposal-discard)
now targets **owner-controlled proposal discard**. The local implementation adds
explicit confirmation, owner-only idempotent discard and uncertain-delivery retries
through the API, native client and review interface. It retains the journal,
sources and published graph while freeing pending proposal capacity. [Local evidence](evidence/connection-proposal-discard/2026-10-03/verification.md)
records checks, screens and the reproduced handoff correction; hosted integration
is pending. Canonical publication and rebuild
recovery remain open. The full goal stays active.

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
revalidation, exact new-file publication and preserved originals/history. Older
revision selection, timed/speaker exports and explicit damaged-history repair
remain open.

The [shared design](evidence/design-refresh/2026-10-03/review.md) retains seven
verified outcomes and the island. [Connections](evidence/knowledge-connections/2026-10-03/verification.md)
remains six of seven overall outcomes; [Curator](evidence/curator-connections/2026-10-03/verification.md)
verifies its six proposal outcomes. Actual reasoning, authorized human canonical
publication and rebuilding remain open. Further formats, older correction revisions and supervised ASR/live work remain in the active queue.

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
