# AAC recording import

**Owner:** Grant McNatt. **Date:** 2026-10-03. **Scope:** Cloud working tree; actual Linux-native codec fixtures and simulated browser jobs, without model weights.

## Outcome

Native selection previously refused M4A/MP4 although the renderer recognized the
extensions. The existing durable import path now admits complete ISO-MP4
containers with one mono/stereo AAC-LC track and supported presentation timing.
Symphonia 0.6.1 remains the decoder. Video in MP4 is ignored, never decoded;
multiple audio tracks are refused rather than selected silently.

## Acceptance

| Outcome | Evidence |
| --- | --- |
| Decoder and truthful scope | Exact 0.6.1 AAC and ISO-MP4 features; native extensions, shared recording guidance and Help agree. Raw ADTS, ALAC, HE-AAC, fragments and multiple audio tracks remain outside support. |
| Actual content and declared duration | Real stereo/video/tail-metadata fixtures retain 44,100 presentation frames, then produce 16,000 mono PCM16 samples. Tone and anti-aliasing checks inspect decoded audio. The 997 ms fixture preserves 43,968 frames; no-edit audio retains all 45,124 declared frames. |
| Source and durable preparation ownership | Case-insensitive imports retain native selection, catalog binding and unchanged originals. Both M4A and MP4 exercise persisted preparation, canonical manifest/source hash, admitted handles and exact prepared bytes through existing owners. |
| Bounded failure and cancellation | Timing metadata uses at most 16 MiB, 4,096 boxes and 64 tracks. Existing duration/output and chunked cancellation bounds apply. Real unsupported/truncated containers, malformed edits/timing and wrong-container content refuse without accepting partial audio or disturbing neighboring files. |
| Recording and recovery | Selection → queued result → review → History uses M4A and MP4 fixtures. Narrow keyboard selection, preparation, failure, retry and removal retain the selected source. Actual browser screenshots below are inspected. |
| Applicable verification and provenance | Native decoder/catalog/persisted preparation tests, browser workflows, frontend/native builds and exact shipped dependency/license/documentation checks are recorded below. Inference and target-platform qualification remain separate. |

## Timing and ownership

Symphonia's current MP4 reader does not apply edit lists. The native bounded
metadata reader inspects the same admitted file handle before demuxing; it never
reopens an arbitrary source path. It accepts one nonnegative unit-rate edit with
no gap, or no edit. Packet timestamps/durations must form the complete declared
media timeline; only the final packet may contain codec padding. Every selected
audio packet is decoded, including packets outside the presentation interval,
so damage cannot be hidden by trimming.

Presentation frames include each sample whose beginning lies inside the edit.
An initial floor calculation lost the fractional fixture's last sample. The
correct ceiling preserves it. FFmpeg legitimately rounds the track header to
998 ticks and edit list to 997 ticks; they may differ by at most 1 ms. Rounding
past available media is clamped only within one movie tick, capped at 1 ms.
Coarse clocks cannot authorize a large invented silence interval. No edit means
no guessed priming trim. Canonical time starts at the retained presentation
content; existing normalization evidence records its rate/channels/frame count.

The four-hour admission ceiling is a resource safeguard, not a qualified
recording-length claim. The metadata ceiling does not establish a whole-decoder
memory benchmark. Shared source fingerprint, temporary-output ownership,
resampling, spool/manifest, job routing and cancellation boundaries are retained.

## Provenance and release boundary

The only added locked crates are unmodified `symphonia-codec-aac` and
`symphonia-format-isomp4`, both 0.6.1 under MPL-2.0. Their exact source/license
origins join the existing [notices](../../../../THIRD_PARTY_NOTICES.md), shipped
inventory and notice bundle. The native timing helper is project code, not a
copied decoder. [Fixture provenance](../../../../desktop/src-tauri/tests/fixtures/README.md)
records all eight synthetic files, generation instructions and hashes. FFmpeg
is used only to create test data; it is not shipped or used at runtime.

AAC distribution patent clearance remains an explicit release handoff. Decoder
copyright licensing and local development tests do not settle that decision.
Actual ASR, alignment/speaker quality, Windows playback and representative long
recordings remain unqualified. No credentials, model weights or enterprise
services were required.

## Screens

[Desktop queue](01-aac-queue-desktop.png), [360 px preparation](02-aac-preparation-mobile.png)
and [360 px failure/retry](03-aac-retry-mobile.png) show the actual application
under the recording bridge. Browser completion/error text is fixture output,
not inference or native codec evidence. Native tests independently decode the
actual source containers.

## Verification

Full native: **1,363 unit + 27 integration passed**, 11 existing model/hardware
ignores. Frontend: **388 unit passed**, two existing Windows-only skips. Full
browser: **183 passed**, one existing Windows-only island skip. TypeScript/Vite
and Linux native debug builds pass; eight documentation/license/provenance
contracts pass. Final native formatting/Clippy renewal is recorded with the
integration checks; Linux-only unused-code warnings are not Windows evidence.

The initial narrow tests used an invalid preparation status, an ambiguous text
locator and the active-job cancellation label for a queued job. They were
corrected to the actual native status, selected-card description and Remove file
control. Screens also reproduced an unnecessarily fixed-height queue and clipped
filenames. The queue now fits its content up to the existing scroll ceiling;
status/actions move below filenames in narrow containers. Both new narrow cases
assert readable filenames and the single-row queue's height. Final full browser
checks and all three inspected captures include this layout.

```bash
source verification/cloud-env.sh
CARGO_BUILD_JOBS=1 .tools/native/usr/bin/tini -s -- cargo test --manifest-path desktop/src-tauri/Cargo.toml --locked
pnpm --dir desktop test
pnpm --dir desktop build
pnpm --dir desktop test:e2e
CARGO_BUILD_JOBS=1 pnpm --dir desktop tauri build --debug --no-bundle
node --test desktop/tests/scripts/release-contract/documentation-truth.contract.mjs desktop/tests/scripts/release-contract/dependency-license.contract.mjs desktop/tests/scripts/release-contract/provenance.contract.mjs
```
