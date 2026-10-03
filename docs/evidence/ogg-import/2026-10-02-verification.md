# Ogg Vorbis recording import

**Owner:** Grant McNatt. **Date:** 2026-10-02. **Scope:** Cloud development working tree; Linux native decoding and simulated browser journeys, without model weights.

**Status:** Software verified. **Coverage:** 5/5 defined outcomes; actual model and Windows qualification remain open.

Ogg Vorbis now uses the existing native picker/catalog/source-fingerprint authority, private decoded-file owner, bounded normalization and canonical spool/manifest. The interface names Vorbis explicitly. Opus, multiple/chained tracks and recordings without a complete declared ending are refused; other formats remain planned.

| Outcome | Evidence |
| --- | --- |
| Exact decoder/license provenance | Symphonia is pinned to 0.6.1 with MP3/FLAC/Ogg/Vorbis features. All eight Symphonia crates include the same standalone MPL-2.0 license, bound to upstream revision `ee35874b571a35a9a6e15d3bc9a3aaf8f11fbeee`. Three dependency inventory/license contracts pass; obsolete 0.5.5 notice exceptions are removed. |
| Native intake and truthful UI scope | Case-insensitive OGG admission retains native selection, catalog binding, source/playback authority and queue identity. Picker extensions and guidance state Ogg Vorbis; renderer file detection does not acquire native authority. |
| Content/duration and immutable provenance | The single-page fixture reproduced 44,608 source frames instead of its declared 44,100 under 0.5.5. Version 0.6.1 corrects single-page padding and uses decoder-owned gapless trimming. Single/multi-page fixtures preserve one-second duration, stereo downmix, tone/anti-aliasing, original bytes and source evidence in the canonical manifest. |
| Safe refusal and cancellation | A CRC-damaged middle page, missing final page, shortened headers, unsupported Opus, chained streams and multiple audio tracks fail without accepted partial audio or leftover decoded plaintext. Cancellation retains the original and removes only its owned temporary copy. |
| Applicable checks and UI inspection | Full native, production frontend build, complete browser regression, dependency/license and documentation/format checks pass. Recording guidance and selected queue state were inspected at 1122×740 and 720×520, including scrolling to the narrow queue. |

## Verification

Full native: **1,317 unit + 27 integration passed**, 11 existing model/hardware ignores. Focused remote suite: **63 passed**, one existing model ignore. Full browser: **102 passed**, one existing Windows-only skip. TypeScript/Vite production build, three license contracts, four documentation contracts, rustfmt and diff whitespace pass. Frontend unit/server/orchestrator/application launch results remain the preceding dated baselines.

```bash
source verification/cloud-env.sh
CARGO_BUILD_JOBS=1 .tools/native/usr/bin/tini -s -- cargo test --manifest-path desktop/src-tauri/Cargo.toml --locked
pnpm --dir desktop build
pnpm --dir desktop test:e2e
node --test desktop/tests/scripts/release-contract/dependency-license.contract.mjs
node --test desktop/tests/scripts/release-contract/documentation-truth.contract.mjs
cargo fmt --manifest-path desktop/src-tauri/Cargo.toml --all --check
```

The first native rebuild exhausted the workspace's free disk while linking. Cleaning disposable Yap package artifacts and rebuilding sequentially resolved that environmental failure; it is not counted as a passing test. The [cloud runbook](../../runbooks/cloud-development.md) now records recovery.

Browser evidence includes both FLAC and Ogg selection → queued job → transcript review → History → restored source-bound review. The complete regression also retains cancellation/retry, keyboard navigation, offline/local independence, settings and every supported Knowledge role. Native checks use real synthetic containers; browser service outputs are fixtures. The visual captures are workspace artifacts under `.tools/ui-audit/25-ogg-queue.png`, `26-ogg-narrow.png` and `27-ogg-narrow-queue.png`. Existing [Mobbin screens, flows and sections](../ui-completion/2026-10-02-design-references.md) remain the interaction references; no third-party visuals were shipped.

## Implementation and limits

- [Decoder](../../../desktop/src-tauri/src/jobs/remote/decode.rs) uses explicit end-of-stream results and gapless decoder options. The obsolete two-pass MP3 probe is removed. Sequential MP3 probing still excludes bitrate estimates; seekable Ogg probing reads declared granule positions from the admitted handle and requires a complete ending.
- [Regressions](../../../desktop/src-tauri/src/jobs/remote/decode/tests.rs), [canonical manifest](../../../desktop/src-tauri/src/jobs/remote/tests.rs) and [native admission](../../../desktop/src-tauri/src/jobs/commands/tests/catalog_imports.rs) verify the same owners as existing formats.
- [Fixtures](../../../desktop/src-tauri/tests/fixtures/README.md) retain Grant's generation commands, content descriptions and hashes. FFmpeg is used only to create synthetic fixtures; it is not a runtime service or shipped dependency.
- [Notices](../../../THIRD_PARTY_NOTICES.md) and the exact shipped inventory preserve upstream attribution. No decoder code was copied or forked; Symphonia's published release fixes the reproduced single-page timing issue.

Physical Windows picker/playback, ASR accuracy, word/speaker alignment and advertised maximum duration remain unqualified. The four-hour limit is a safety ceiling. Ogg support means single-track, non-chained Vorbis with a complete declared ending, not every codec in an Ogg container. M4A/MP4/WebM and broader codecs remain goals; AAC needs its separate decision. Raw MP3's unknowable-ending limitation remains explicit in the [integrity evidence](../imported-audio-integrity/2026-10-02-verification.md).
