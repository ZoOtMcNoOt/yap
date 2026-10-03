# Imported audio integrity

**Owner:** Grant McNatt. **Date:** 2026-10-02. **Scope:** Development working tree; Linux native decoder and durable job preparation, without models.

MP3 preparation previously continued after a decoder-reported damaged packet. A regression test reproduced accepted partial audio with valid packets before and after the damage. Preparation now rejects that recording, removes its temporary decoded plaintext and retains the selected original. The exact job receives `PREPROCESSING_FAILED` with a concise recovery message; unrelated jobs remain queued.

## Acceptance

**Coverage:** 4/4 defined software outcomes.

| Outcome | Evidence |
| --- | --- |
| Reject damaged packets rather than omit source audio | A synthetic tone fixture with damaged Layer III side information reproduced partial acceptance before the fix and is rejected afterward. |
| Remove temporary decoded plaintext | The decoder-wrapper regression and actual job-preparation regression leave no decoded files or remote spool artifacts. |
| Preserve the selected source | Both regressions compare the original bytes after failure. |
| Fail only the affected job before a manifest is attached | The preparation test uses registered native source authority and an in-memory durable ledger, checks no prepared job or preflight artifact, records failure on the exact job and preserves a neighboring queued job. The persisted message contains no source path or decoder internals. |

Sources: [decoder](../../../desktop/src-tauri/src/jobs/remote/decode.rs), [decoder regression](../../../desktop/src-tauri/src/jobs/remote/decode/tests.rs), [shared test fixture](../../../desktop/src-tauri/src/jobs/test_media.rs), [job preparation regression](../../../desktop/src-tauri/src/jobs/drain/tests/preparation.rs), and [durable failure owner](../../../desktop/src-tauri/src/jobs/drain/owner.rs).

## Verification

```bash
source verification/cloud-env.sh
.tools/native/usr/bin/tini -s -- cargo test --manifest-path desktop/src-tauri/Cargo.toml --locked
cargo fmt --manifest-path desktop/src-tauri/Cargo.toml --all --check
```

Full native suite: **1,271 unit + 27 integration passed**, with 11 existing model/hardware ignores. The new decoder and job regressions pass. The preceding frontend baseline remains 388 unit and 100 browser passes, two unit Windows skips and one browser Windows skip; this native-only change does not renew frontend or enterprise qualification.

A later duration audit found that the earlier shortened-stream fixture carried a Xing header. The current raw-stream test explicitly removes that metadata and verifies the absence of a declared duration; a separate regression covers the header-bearing case. A shortened raw MP3 may not establish an expected ending. This fix rejects decoder-reported damage; it does not claim detection of every corrupt or incomplete recording. Source-time and transcript quality still require representative model qualification. No dependency or supported format was added.

## MP3 source-content duration

**Coverage:** 5/5 software outcomes. Preparation now validates declared trim bounds, applies encoder delay/padding, and reconciles decoded content against container-declared frame counts. Sequential probing avoids mistaking a bitrate-based estimate for an authoritative ending. When trimming requires another probe, it uses the same open source handle.

| Outcome | Evidence |
| --- | --- |
| Preserve declared content duration | The synthetic one-second MP3 previously emitted 46,080 frames; it now yields its intended 44,100 source frames and approximately 16,000 canonical samples. The prepared manifest records that content timeline and unchanged source provenance. |
| Reject detectably missing audio | Removing complete trailing packets while retaining declared length now fails instead of accepting partial audio. Temporary plaintext is removed and original bytes remain unchanged. |
| Keep the raw-stream limitation accurate | The raw MP3 regression strips metadata and verifies `n_frames` is absent. Available complete packets remain decodable without inventing an expected ending; existing WAV/FLAC and cancellation checks pass. |
| Refuse invalid trim metadata without panicking | Zero declared frames with nonzero delay/padding reproduced an upstream subtraction panic. Bounds are checked before gapless probing; failure retains the source and leaves no decoded plaintext. |
| Verify the native path | Focused remote preparation/decoder suite: 38 passed, one existing model ignore. Full native: **1,290 unit + 27 integration passed**, 11 existing hardware/model ignores. |

The fixture is attributed and pinned in [its README](../../../desktop/src-tauri/tests/fixtures/README.md). No dependency, format or model weights were added. The canonical normalization revision remains unchanged because it describes normalization of already-decoded PCM; decoded-source evidence and content hashes record the changed input. These checks verify software duration and integrity, not ASR accuracy, word alignment, physical Windows behavior or detection of every damaged raw stream. Frontend, server and dependency results remain their preceding dated baselines.

## Decoded plaintext ownership

**Coverage:** 5/5 software outcomes. The regression reproduced an occupied temporary pathname being reused by the truncating WAV writer. Decoding now reserves a new attempt file with exclusive creation, writes through that handle, and passes a cloned handle into both preflight and canonical preparation. The obsolete decoded-path reopening helper was removed.

| Outcome | Evidence |
| --- | --- |
| Retain occupied paths and enforce the spool boundary | Existing files, directories and links refuse reservation without cleanup. A planted legacy temporary link cannot redirect output. Invalid job identifiers fail without creating files outside the spool. |
| Own private plaintext through preparation | Unix creation uses mode 0600. The WAV writer uses a buffered retained handle; preparation clones and rewinds it. A pathname replacement still reads the original WAV rather than the substituted file. |
| Scope cleanup to the attempt | Cancellation removes only the newly created attempt while another attempt and the original remain. Unix cleanup checks the still-open device/inode and refuses substituted files or links; normal completion removes its owned path. |
| Refuse nonregular input and recover crashed attempts | An actual FIFO-source regression returns without waiting for a writer and leaves no decoded plaintext. Shared regular-file admission is reused. The existing restart test now covers precise process/nonce names, prior process-only names, unrelated names and neighboring jobs. |
| Verify the native owners | Eight new regressions plus expanded crash recovery pass. Full native: **1,298 unit + 27 integration passed**, 11 existing hardware/model ignores. Formatting, four documentation contracts and diff whitespace pass. |

Sources: [decoded-file owner](../../../desktop/src-tauri/src/jobs/remote/decode/temp.rs), [decoder tests](../../../desktop/src-tauri/src/jobs/remote/decode/tests.rs), [preparation](../../../desktop/src-tauri/src/jobs/drain/preparation.rs), [shared regular-file owner](../../../desktop/src-tauri/src/bounded_file.rs), and [crash recovery](../../../desktop/src-tauri/src/jobs/remote/spool.rs).

Windows uses delete-on-close ownership on the created handle and inherited application-directory permissions; actual Windows filesystem/sharing/crash behavior still needs target qualification. Unix path cleanup is an identity check in the private spool, not an atomic defense against a hostile process with the same account racing between check and unlink. If that process renames the original elsewhere, its new name is retained rather than searched for and deleted. No frontend, server, dependency or model behavior changed; their preceding results remain dated baselines.

## Bounded resampling and final content interval

**Coverage:** 5/5 software outcomes. A real, small 1 Hz FLAC fixture reproduced cancellation being checked only after 2,015,232 plaintext bytes were written, and 64 seconds becoming 1,008,001 samples instead of approximately 1,024,000. The source contains only 64 frames; this reproduction required no large allocation or model.

| Outcome | Evidence |
| --- | --- |
| Validate rate and duration before expansion | Declared frame counts are checked before decoder creation; actual counts use checked addition and are checked before resampling. Boundary cases cover zero rate, maximal counts/rates and the four-hour threshold. A mutated FLAC declared as 50,000 seconds fails early with its source retained. |
| Bound each resampling allocation | Calls contain at most one second of input and 4,096 source frames. Including retained interpolation state, canonical output remains below 32,768 floats (128 KiB capacity). Tests check actual vector capacity at rates from 1 to 655,350 Hz, through the existing resampler. |
| Check cancellation between chunks | The real low-rate fixture cancels before excessive plaintext is written, removes its owned temporary copy and retains identical source bytes. The regression requires cancellation before 128 KiB, without depending on an exact callback count. |
| Preserve the final content interval | Explicit stream finalization holds the final source sample through its interpolation interval. The 64-second fixture now retains its intended duration within one canonical sample; source frame count remains 64. Partitioned and whole-stream resampling agree in content/duration, and repeated finalization emits nothing. |
| Preserve existing supported paths | Six new regressions and all existing tone, anti-aliasing, MP3/FLAC duration, manifest, cleanup and preparation checks pass. Focused remote suite: 52 passed, one existing model ignore. Full native: **1,304 unit + 27 integration passed**, 11 existing hardware/model ignores. Formatting, four documentation contracts and diff whitespace pass. |

Sources: [decoder and bounds](../../../desktop/src-tauri/src/jobs/remote/decode.rs), [regressions](../../../desktop/src-tauri/src/jobs/remote/decode/tests.rs), [shared resampler](../../../desktop/src-tauri/src/audio/preprocess.rs), and [attributed/pinned fixture](../../../desktop/src-tauri/tests/fixtures/README.md). Existing streaming `push` behavior is retained; imported-file decoding explicitly finishes its stream. Rate-zero FLAC is already refused by the existing container library; the native duration guard also prevents invalid-rate arithmetic. No decoder fork, dependency or model weights were added.

The allocation bound covers canonical resampling work, not a newly qualified peak-memory budget for every decoder/container. The four-hour limit remains a safety ceiling, not advertised maximum recording duration. Synthetic silence/tones verify software duration and recovery, not ASR accuracy, word alignment or physical Windows performance. Frontend/server/dependency results remain their preceding baselines.

## Compressed-source admission ownership

**Coverage:** 4/4 software outcomes. The regression reproduced a pathname substitution selecting 44.1 kHz audio after a 1 Hz source had been admitted. Both native preparation paths now pass the already-open file and its trusted fingerprint into decoding. The pathname supplies a format hint only; it is never reopened by the decoder.

| Outcome | Evidence |
| --- | --- |
| Keep the selected open object through both preparation paths | Preflight and canonical preparation pass the same validated source handle. A substituted pathname cannot select replacement audio; a nonexistent path hint still decodes the admitted object and rewinds its handle correctly. |
| Refuse detectably changed or mismatched sources | Existing file identity/length/revision fingerprint checks run before reservation and after decoding. A same-length container-padding rewrite cannot yield an accepted result; a mismatched handle/fingerprint fails before creating a spool. Native FIFO admission also returns without waiting for a writer and retains the FIFO. |
| Preserve evidence, cancellation and private cleanup | No new source registry, caller-selected identity or compatibility reopening path is added. Substitution/mutation failures leave no decoded plaintext and retain originals/replacement files. Existing manifest, duration, cancellation and durable failure tests pass. |
| Verify the actual native paths and limits | Five new regressions pass. Full native: **1,309 unit + 27 integration passed**, 11 existing hardware/model ignores. Formatting, four documentation contracts and diff whitespace pass. |

Sources: [decoder](../../../desktop/src-tauri/src/jobs/remote/decode.rs), [native preparation](../../../desktop/src-tauri/src/jobs/drain/preparation.rs), [existing media fingerprint owner](../../../desktop/src-tauri/src/media_protocol/source.rs), [decoder regressions](../../../desktop/src-tauri/src/jobs/remote/decode/tests.rs), and [native admission FIFO regression](../../../desktop/src-tauri/src/media_protocol/tests/source.rs).

On Unix, renaming the selected file changes its revision and may safely fail preparation; on Windows, the existing source handle's sharing policy prevents replacement/write attempts. Physical Windows behavior still needs qualification. Fingerprints detect ordinary identity/size/revision changes; they do not claim resistance to every hostile same-account filesystem manipulation. No dependency, UI behavior, server contract or model changed. Their preceding results remain baselines.
