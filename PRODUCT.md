# Product

## Users

Privacy-conscious people who need accurate text from audio or video files — journalists transcribing interviews, researchers working through field recordings, podcasters, students, and anyone who batch-processes media without sending it to a third-party cloud.

They usually arrive with files already on disk (MP3, M4A, WAV, MP4, and similar formats). Live capture is explicit and secondary, used for local/offline fallback or saved sessions, not always-listening dictation. Context is focused work: drop files, wait for trusted transcription, review and export text, and optionally review source-bound corrections before sharing. They care that the current route is clear: local fallback stays on this device; team/server mode uses org-owned GB-class hardware, not third-party cloud.

## Product Purpose

The integrated main baseline includes PRs #205–#208, including authenticated
desktop rebuilding. The inspected development successors implement larger
embedding generations (#209), timed speaker JSON export (#210) and Ogg FLAC
(#211); those three remain unmerged. The capability descriptions below distinguish
those pending additions
from the integrated baseline. [Current status](docs/CURRENT-STATUS.md) records
their remaining checks and qualification limits.

Yap is a desktop transcription app (Tauri + React in `desktop/`). The current desktop implementation records and transcribes explicit live sessions locally with Nemotron 3.5 ASR Streaming 0.6B INT8 through in-process `sherpa-onnx`. The integrated imported-recording path accepts canonical mono PCM16/16 kHz WAV and decodes MP3, FLAC, Ogg Vorbis and AAC-LC in M4A/MP4 into that canonical format before using the durable private-server contract. It publishes only natively verified results. Disconnected imports remain queued or blocked instead of receiving official-looking fallback output. Additional audio/video formats remain the target product experience; integrated decoding support is WAV, MP3, FLAC, Ogg Vorbis and M4A/MP4; pending PR #211 adds Ogg FLAC. M4A/MP4 supports one mono/stereo AAC-LC track. Ogg requires a single, non-chained track with a complete ending: Vorbis in main, with FLAC added by pending PR #211. M4A/MP4 requires a complete nonfragmented container with supported presentation timing; video is ignored. Opus, other MP4 codecs and complex edits remain unsupported. AAC distribution patent clearance remains a separate release decision.

The target product loop is files in, accurate transcripts out, with minimal friction between drop → durable queue → private server transcript → copy/export. The integrated connected path accepts canonical mono PCM16/16 kHz WAV, MP3, FLAC, Ogg Vorbis and supported M4A/MP4 files. Pending PR #211 adds Ogg FLAC; additional audio/video formats remain open. The supported offline loop is explicit live capture → local transcript → history/playback/copy or reveal. The interface should make the current file and its transcript the center of attention; model names, auth paths, and runner details stay in secondary status unless something needs attention.

Supported navigation:

- **Home** — hub with recent transcripts and a quick path back into work
- **Transcribe** — the workbench: drop zone, queue, progress, and live transcript preview
- **Correct** — manual source-bound transcript correction with original/corrected review and explicit revision publication
- **Knowledge** — cited search/answers and human review of proposals/conflicts
- **Settings and Help** — setup, recovery, and concise guidance

Transcript history lives on Home. Review offers copy, open, reveal and **Export text** for the original UTF-8 transcript. Export creates a new file outside Yap data and preserves existing files. If completion is unconfirmed, a file may already exist: check the destination before explicitly retrying. This guidance also applies to saved-correction exports. Timed/speaker JSON export is implemented in pending PR #210; subtitle conversion and alignment of saved free-text corrections remain separate planned outcomes.

Correct requests source-bound suggestions through Scribe on the connected organization server. **Save revision** accepts edits separately and preserves raw ASR. Reopening starts with the latest accepted revision; **Accepted revision** can select an earlier one for offline reading, copying and **Export saved correction**. Reading an older revision does not replace the latest acceptance. A new acceptance resets selection to latest. Export revalidates the selected revision and source/history after destination selection. Unsaved suggestions stay separate; damaged history reports an error without replacing files. [Selection guidance and local verification](docs/specs/accepted-correction-history.md) retain the remaining integration and target checks.

The integrated Knowledge workspace provides Search sources, Ask a question, Connections, Review proposals, Review conflicts and a reviewer-owned Rebuild task for explicit reviewed-source inspection, staging, embedding preparation, publication and retained restore; it cannot certify Git review or turn a proposal into canonical source. Connections explores permission-filtered, source-cited relationships; proposed connections require two exact source excerpts and remain separate from canonical knowledge. Review proposals reopens a saved connection by reference, with its direction, rationale and exact cited sources; opening it does not publish knowledge. Tasks retain drafts and pending work across tabs; citations show exact excerpts and source revision/range details. The supported roles are:

| Role | User-facing outcome |
| --- | --- |
| Scribe | Proposed corrections; explicitly accepted separate revision. |
| Archivist | Stage a completed server transcript for knowledge review. |
| Librarian | Retrieve permission-safe excerpts with citations. |
| Analyst | Answer using current cited evidence. |
| Student | Ask a learning question about an exact cited excerpt. |
| Curator | Create a source-bound proposal with a copyable review reference. |
| Coordinator | Assemble a noncanonical proposal bundle for human review. |
| Auditor | Report source-cited findings without changing knowledge or scheduling actions. |

Credentials, source admission, authorization, transport, and durable jobs remain native/server-owned. Staging, proposals, bundles, and reports do not activate knowledge. Failed remote work leaves local reading and setup available; background completion offers an explicit review action instead of changing workspaces.

Settings separates local dictation from the optional organization connection and sign-in. Help explains language choice, routing, storage, corrections, and human review. Setup can be skipped and retried before models or services are available.

Settings → Personalization manages personal and explicitly configured team/organization preferred spellings, variants, language and sensitivity through the authenticated server ledger. Scope discovery provides trusted labels and separate viewing/editing permissions; team membership and organization administrator roles remain operator-owned. Creation retries preserve identity; edit conflicts require comparing the latest version; deletion preserves history and existing snapshots. Offline failures retain drafts, while sign-out clears private loaded data. Native connection revisions prevent old drafts from being submitted under another server/account. Terminology management works without correction models; saving terms does not enable correction or promise provider-specific ASR effectiveness. ADR 0028’s four deterministic projection contracts are delivered. Automatic directory synchronization, broader administration, supported provider/workflow integration and provider effectiveness remain in the [project queue](docs/plans/active/2026-10-02-yap-project-hill-climb.md).

Qualification history is preserved in the [product snapshot](docs/archive/implementation-evidence/product-2026-08-14.md) and [evidence index](docs/evidence/README.md). Those receipts establish their recorded server boundaries; they do not establish a current native/renderer round trip, live enterprise identity exchange, or renewed model qualification. The [roadmap](docs/roadmap/ROADMAP.md) retains intended formats, export, personalization, speaker identity, and the full Voice OS direction.

## Brand Personality

Calm, direct, private, warm, fast to understand. Three words: **quiet**, **capable**, **local**.

Voice is operational and plain — short labels like "Drop recordings" or "Transcript ready," not product essays on every screen. Confidence comes from clarity and visible progress, not from hype or technical jargon. The app should feel like a polished consumer utility: sparse navigation, one obvious action at a time, document-like transcript surfaces.

Reference feel (specific traits, not category buckets):

- **Wispr Flow** — practical sparse nav and compact status, adapted for batch files rather than live mic input
- **Figma-style tools** — soft canvas, one generous work surface, secondary details tucked away until needed

Emotional goal: users trust the visible route — local fallback on this device, server work on org-owned hardware — and that the tool disappears into the task.

## Anti-references

- Always-listening mic UX or live-only dictation (Wispr-style realtime capture is not the whole product)
- SaaS dashboard density — this is a file-to-transcript tool, not an analytics hub
- Marketing landing page inside the app: giant hero copy, gradient blobs, decorative sections, nested card grids
- Developer-first chrome: leading with model IDs, Python paths, GPU jargon, or auth mechanism details on the main screen
- Generic beige AI utility aesthetic with no identity (anonymous cream canvas with no purposeful accent discipline)
- Modal-heavy flows where inline or progressive disclosure would suffice
- Cloud-upload patterns that hide where files are processed

## Design Principles

1. **Drop audio, get text.** Every screen should reinforce the core loop; secondary capabilities (correction, knowledge staging, history, setup) support it, they don't compete with it.
2. **The transcript is the reward.** When transcription completes, the text surface becomes the hero; copy, export and reveal actions stay adjacent to the content.
3. **Trusted route, stated simply.** Distinguish local dictation readiness from server availability. Imported recordings retain their organization-server route during outages; no status label may imply an automatic local switch.
4. **One primary action per state.** Empty → drop; queued → wait for the trusted route; running → progress + cancel; done → read, copy, or reveal. Avoid competing primary buttons.
5. **Technical setup is secondary.** Model, auth, runner, and output path belong in details/status areas until something needs attention.

## Accessibility & Inclusion

Target WCAG 2.1 AA for text contrast and interactive states. Body and label text must remain readable on warm canvas and surface backgrounds (no washed-out muted gray for operational copy).

- Respect `prefers-reduced-motion`: state feedback should crossfade or snap instead of choreographed entrance sequences.
- Keyboard paths for navigation rail, queue actions, transcript copy/export, and shipped shortcuts.
- Tooltips and accessible names on icon-only actions (remove, reveal, copy, settings).
- Native window minimum is 640×480, with a 960×700 default in `desktop/src-tauri/tauri.conf.json`. Responsive single-column browser layouts are checked down to 360px; that is layout evidence, not a smaller native-window setting. Keep controls clear at minimum size and transcript reading comfortable at 15px+ with generous line height.
- No information conveyed by color alone for queue status — pair color with label or icon.
