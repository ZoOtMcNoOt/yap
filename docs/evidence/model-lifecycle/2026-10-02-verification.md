# Model lifecycle verification

**Owner:** Grant McNatt. **Date:** 2026-10-02. **Scope:** Development working tree; native Linux IO with synthetic artifact bytes. No model weights or inference were used.

## Offline import: 4/4 software outcomes

Model import now keeps a bounded, no-follow regular file handle from source admission through copying. Previously it checked pathname metadata, prepared the destination and then reopened the pathname. A deterministic replacement regression reproduced reading the substituted source; the fixed path imports the validated original without changing either source file.

| Outcome | Evidence |
| --- | --- |
| Bind size/type checks to the opened source before staging | The shared bounded-file owner returns the regular handle and its metadata. Exact model size is checked before preparing destination directories. Unix no-follow/nonblocking flags reject links and FIFOs; Windows retains its existing reparse-point open and regular-file check. |
| Retain original authority through pathname replacement | A Unix regression replaces the pathname with different equal-length bytes after admission. The approved original is imported; the original and replacement bytes remain intact. |
| Preserve bounded hash-verified atomic replacement and cancellation | Existing synthetic IO checks preserve the installed artifact after bad hash/length or cancellation and remove staging. New cancellation after source admission creates no destination directory or staging. The streaming owner also checks exact/oversized limits and directory/link/FIFO refusal. |
| Verify native behavior and keep qualification limits explicit | Fourteen model primitive cases and six bounded-file cases pass. Full native suite: 1,281 unit + 27 integration passed, 11 existing hardware/model ignores. The FIFO watchdog regression was hardened afterward to release a blocking reader before failing; all six bounded-file cases were rerun. |

Sources: [import](../../../desktop/src-tauri/src/stt/model/import.rs), [bounded file owner/tests](../../../desktop/src-tauri/src/bounded_file.rs), [existing verified download](../../../desktop/src-tauri/src/stt/model/download.rs), [temporary/atomic publication owner](../../../desktop/src-tauri/src/stt/model/temp.rs), and [registered model commands](../../../desktop/src-tauri/src/commands/setup.rs).

```bash
source verification/cloud-env.sh
cargo test --manifest-path desktop/src-tauri/Cargo.toml --locked --lib stt::model
cargo test --manifest-path desktop/src-tauri/Cargo.toml --locked --lib bounded_file
.tools/native/usr/bin/tini -s -- cargo test --manifest-path desktop/src-tauri/Cargo.toml --locked
```

This increment reuses one file owner and adds no dependency, download or renderer write authority. Frontend/build/server checks remain the preceding dated baselines; no UI behavior was changed. Windows share/reparse behavior, real model loading and performance remain target qualification. A held handle prevents pathname substitution from redirecting reads; approved hash verification still rejects changed contents of that opened file. This is not a claim of protection against every same-user filesystem modification.

## Installed artifacts and readiness: 5/5 software outcomes

The regression reproduced **Ready** for a linked fallback artifact with an otherwise valid marker. Readiness now rejects linked/nonregular files before trusting a cache marker. Generic hashing, downloaded/imported staging and installed artifact verification share the bounded regular-file owner and one SHA-256 reader. The two older verification entry points were removed; approved byte count, digest and cancellation are explicit inputs.

| Outcome | Evidence |
| --- | --- |
| No false readiness for linked/nonregular installed artifacts | Native status/marker regression rejects a link to otherwise approved synthetic bytes and leaves its target intact. |
| Bounded no-follow hashing | Installed/staged verification checks metadata on the opened handle against approved size. The shared reader consumes at most the expected length plus one byte and rejects both early EOF and growth; generic file hashing refuses links. Shared FIFO refusal remains covered. |
| Markers require valid artifacts | Linked verification fails instead of renewing a marker. Existing good/cache, stale/tampered, wrong size/hash, missing and progress cases remain green. |
| Cancellation preserves artifacts and markers | The reader regression requests cancellation after an actual buffer read. Fallback verification observes cancellation between buffers and before writing a marker; a native regression retains its artifact and stale marker unchanged. |
| Regression and qualification boundary | Focused STT suite: 78 passed, three existing model/platform ignores. Full native suite: **1,286 unit + 27 integration passed**, 11 existing hardware/model ignores. Formatting, four documentation contracts and diff whitespace pass. |

Sources: [shared verification](../../../desktop/src-tauri/src/stt/model/integrity.rs), [fallback catalog](../../../desktop/src-tauri/src/stt/nemotron/catalog.rs), [fallback regressions](../../../desktop/src-tauri/src/stt/nemotron/tests/catalog.rs), [auxiliary VAD](../../../desktop/src-tauri/src/stt/silero_vad.rs), and [language-model lifecycle](../../../desktop/src-tauri/src/stt/ambernet_language_detector/lifecycle.rs). Real weights, inference, Windows load guards and physical client behavior remain unqualified by these synthetic Linux checks.
