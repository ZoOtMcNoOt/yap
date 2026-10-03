# Hardware-free UI acceptance

**Owner:** Grant McNatt. **Date:** 2026-10-02. **Scope:** current working tree, cloud Chromium and deterministic native-boundary fixtures. **Result:** 30/30 supported UI acceptance areas verified within this scope.

The [completion plan](../../plans/completed/2026-10-02-hardware-free-product-completion.md) measures six workspaces against five acceptance areas. This record concerns supported software flows. It does not score model accuracy, Windows capture, enterprise identity, or production readiness. Future formats, dedicated export, personalization, and other intended features remain in the [roadmap](../../roadmap/ROADMAP.md).

## Acceptance matrix

Each cell names the verified behavior; the suite references below provide reproducible evidence. Help has no asynchronous task or result publication: its applicable loading/recovery behavior is that guidance remains available when services are absent.

| Workspace | Purpose and next action | Empty/loading | Completion/review | Unavailable/failure recovery | Keyboard, focus, window and motion |
| --- | --- | --- | --- | --- | --- |
| Home | Recent recordings, direct Transcribe action, named review/actions buttons. | Catalog loading is distinct from empty; body search reports indexing. | Read/copy/open/reveal; review retains the chosen source for correction. | File/catalog/preview retries retain saved entries; failed hide, recovery or native delete retains the row. Delete requires confirmation. | Named native buttons; review traps focus and closes with Escape; layout checked at the window floor. |
| Transcribe | WAV/MP3 guidance, explicit per-job language, organization-server queue. | Empty queue and actual queued/processing phases have distinct text. | Native result projection appears in history; completion notification offers deliberate review. | Cancel/re-add/failure/retry; startup restores queued/failed/completed projections. Offline imports keep their route and local controls remain available. | Language picker keys, queue actions, review transitions, reduced motion and window checks. |
| Correct | Choose a transcript, review proposed changes, explicitly save a revision. | No-source and pending correction states are visible. | Original/proposed text, insertion/deletion markup, copy and separate revision acceptance. | Server/capability denial preserves original access; job/save failure can retry; changing sources cancels pending work. | Review-to-correction transition retains source, named controls and original/corrected reading panes fit supported windows. |
| Knowledge | Search, Ask, Proposals and Conflicts have distinct task tabs. | Drafts and pending tasks survive tab changes; empty evidence is explicit. | Exact numbered citations, readable names, revision/range disclosure; learning question → copyable proposal reference; bundles/reports require review. | Failure/cancel/retry preserves drafts, absent evidence reveals no hidden results, unavailable capabilities lead to Settings. Background recording completion preserves pending work. | Tabs support arrow keys; inactive panels are hidden; source disclosures and forms remain usable at supported sizes with reduced motion. |
| Settings | Local model/setup and organization connection/sign-in are separate. | Language/model lifecycle projections and server loading are explicit; failed loads do not expose an empty form for saving. | Language confirmation, native shortcut projection, saved connection notice and explicit test result. | Skippable/retryable setup; load/save/check failures preserve choice or URL; sign-in is never automatic and remote denial does not disable local model controls. | Labelled microphone/compute/language controls, focus-trapped modal with opener restoration, section/disclosure navigation, accessible Close at tested sizes. |
| Help | Concise recording, reading, storage and review guidance; Open Settings next action. | Available before setup and without models/services; optional answers remain collapsed. | Expanding a question reveals routing, storage, correction or proposal guidance. | Help → Settings and return/Close; instructions explain retained routes and immutable originals. | Native details work with Enter; scrolling body keeps footer Close visible; Settings/Help are mutually exclusive modals. |

## Final verification

| Check | Result |
| --- | --- |
| `pnpm test` | 388 passed; 2 Windows-only skips. |
| `pnpm build` | TypeScript and Vite passed. |
| `pnpm test:e2e` | 86 passed; 1 Windows-only skip. |
| Native `remote_state` tests | 4 passed: atomic attachment, create/chunk/commit idempotency, deferred retry and mutated-source retry all survive restart. |
| Documentation contracts | 4 passed, including every relative documentation link. |
| Native rustfmt and `git diff --check` | Passed. |

The unit exclusions are Windows WDIO main-window recovery and exact Windows-path saved-bundle ownership. The browser exclusion is the initial collapsed island state: Linux Chromium synthesizes hover on load; the test remains enabled for Windows. Other island motion/frame tests pass here. Full native, orchestrator, Python and provenance/license results are the preceding [environment baseline](../../CURRENT-STATUS.md), not repeated inference qualification.

## Reproducible evidence

Run from `desktop/` after sourcing [the cloud environment](../../runbooks/cloud-development.md):

```bash
pnpm test
pnpm build
pnpm test:e2e
```

Relevant browser suites:

- [First run](../../../desktop/tests/e2e/first-run.spec.ts): skip, Escape/focus, missing models/services, failed checks/confirmation, supported locale choice and separate local/server language authority.
- [Recording journey](../../../desktop/tests/e2e/recording-journey.spec.ts): cancel/re-add, failure/retry, deliberate completion review, copy/search, read failure/retry and startup projections.
- [Correction journey](../../../desktop/tests/e2e/correction-journey.spec.ts): older-source selection, diff/copy, explicit publication failure/retry, immutable original, source-change cancellation.
- [Knowledge journey](../../../desktop/tests/e2e/knowledge-journey.spec.ts): all six task roles, exact citations, tab/pending preservation, reviewed proposal reference, cancel without resubmission, background completion.
- [Workspace acceptance](../../../desktop/tests/e2e/workspace-acceptance.spec.ts): 1122×740, 1440×900 and a 720×520 accessibility probe; modal/tab keys, loading/failure/denial, connection retries, preview retries and history maintenance.
- [Pending admission](../../../desktop/tests/e2e/pending-admission.spec.ts): cancellation is disabled until a native request identity is available, then completes without resubmitting the form.
- Existing [history](../../../desktop/tests/e2e/app-history.spec.ts), [language](../../../desktop/tests/e2e/app-language-accessibility.spec.ts), [shortcuts](../../../desktop/tests/e2e/app-shortcuts.spec.ts), [Archivist](../../../desktop/tests/e2e/archivist-ingestion.spec.ts), [playback authorization](../../../desktop/tests/e2e/playback-authorization.spec.ts) and [island](../../../desktop/tests/e2e/live-overlay.spec.ts) suites remain enabled.

Fixtures prove renderer behavior at native commands/events. Startup fixtures replay a native projection; they do not prove filesystem or ledger durability. The four fresh [native remote-state tests](../../../desktop/src-tauri/src/jobs/ledger/tests/remote_state.rs) provide separate restart/idempotency evidence. Run `cargo test --manifest-path desktop/src-tauri/Cargo.toml --locked remote_state -- --test-threads=1` from the repository root after sourcing the cloud environment. Browser checks also do not qualify actual Windows rendering, microphones, hotkey enrollment, model downloads/inference, or enterprise sign-in.

Visual inspection covers the initial nine states plus correction review/acceptance, cited search/answer, expanded organization Settings, Help FAQ and narrow Help. Captures are local artifacts in `.tools/ui-audit/`; meaningful assertions live in the reproducible suites. [Mobbin references](2026-10-02-design-references.md) cite the inspected screens, flow preview steps and website sections; no third-party image/brand assets ship with Yap.

## Qualification handoff

These tasks require inputs absent from this cloud environment. Each must run against the reviewed build and record exact model/runtime/configuration identities. Historical receipts remain reference evidence.

| Qualification | Target and required inputs | Observable pass condition |
| --- | --- | --- |
| Local dictation and model lifecycle | Supported Windows x64 client, physical microphone, locked artifacts from [model-artifacts.lock.json](../../../desktop/model-artifacts.lock.json); permitted download/import sources. | Verified install/repair/cancel/remove and restart; explicit capture produces preserved source audio and accurate transcript; no unsolicited capture, download or route change. |
| Locale switching and meeting labels | Windows client plus representative multilingual/ambiguous/switching recordings, pinned Nemotron/Silero/language detector and promoted server catalogs. | Locale selection and retained primary-language fallback follow [ADR 0024](../../adr/0024-global-language-routing.md); review-required labels are explicit; promotion thresholds and quality exclusions are recorded. |
| Batch ASR, timing and speakers | Organization-owned model node, approved provider locks, representative WAV/MP3/meeting recordings, target GPU/driver/runtime and storage. | Native intake → durable job → verified transcript/timing/speaker result → history/playback works; accuracy/overlap/source-time tests meet the accepted qualification specs. No fixture result counts as inference evidence. |
| Source-bound correction and knowledge integration | Approved private node, actual correction model/provider, PostgreSQL/pgvector, reviewed permission-scoped corpus and organization principals. | Real native/client round trips produce source-bound outputs; raw transcript remains unchanged; accepted revision is separate; citations are exact and permission-safe; proposals/bundles/reports never auto-activate knowledge. |
| Capacity and service lifecycle | Representative organization node, full pinned provider profile, realistic concurrent owners/load and agreed SLOs. | Simultaneous residency, memory, fairness/backpressure, cancel/restart, tail latency and sustained-load results meet the [capacity evidence](../agent-admission-profile-capacity/VERIFICATION.md) requirements; partial-profile simulation is insufficient. |
| Native interaction | Supported Windows machine, physical keyboard, tray/island and microphone, approved target applications and accessibility settings. | Record/reset hotkeys, stop/cancel, push-to-talk, text injection, focus/hit regions, scaling and restart operate without unexpected capture or delivery. Use the documented desktop/target-client harnesses. |
| Enterprise identity and networking | IT-provided Entra tenant/client/scope, approved native provider/cache, test principals, certificates/proxy/VPN and server origin. | Explicit sign-in/out, renewal and denial follow the [identity handoff](../../runbooks/entra-identity-conformance-handoff.md); native credentials stay out of renderer/logs; permission isolation and TLS/origin policy pass; local controls survive failures. |
| Installer and data migration | Fresh disposable Windows VM/runner, exact reviewed NSIS build/hash and representative legacy/canonical data. | [Installer harness](../../../desktop/README.md) verifies install/launch/uninstall, provenance and preservation; interrupted/conflicting/cross-volume migration preserves recoverable data and fails closed. |

Merge and production promotion require their normal reviewed-head gates after these qualifications. This milestone supplies a buildable, testable UI and a concrete handoff; it does not authorize release.
