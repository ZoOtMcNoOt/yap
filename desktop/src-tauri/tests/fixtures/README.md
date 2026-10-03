# Native audio fixtures

The tone recordings are synthetic test data, not speech or model-accuracy evidence.

`tone-44k-stereo.flac` was created for Yap by Grant McNatt with FFmpeg 7.1.5. It contains one second of stereo PCM16 at 44.1 kHz: 440 Hz on the left and 12 kHz on the right. Tests verify duration, downmix, anti-aliasing and the FLAC integrity metadata. SHA-256: `6bf1c246ef250a3aa53f7481d953673c67eaef6537f34f8abb8ca4723ba36f6a`.

```bash
ffmpeg -f lavfi -i 'sine=frequency=440:sample_rate=44100:duration=1' \
  -f lavfi -i 'sine=frequency=12000:sample_rate=44100:duration=1' \
  -filter_complex '[0:a][1:a]amerge=inputs=2' -c:a flac -sample_fmt s16 \
  -map_metadata -1 -fflags +bitexact -flags:a +bitexact tone-44k-stereo.flac
```

`tone-44k-gapless.mp3` contains the same one-second stereo tones, encoded with a Xing/LAME duration/delay/padding header by Grant McNatt using FFmpeg 7.1.5. SHA-256: `10bd303b40bcc3b84c7dff971a5538ca933bc848ddbf6a30967cd4f819d36116`. Use the FLAC generation command above with `-c:a libmp3lame -b:a 128k -write_xing 1` in place of `-c:a flac -sample_fmt s16`, and this MP3 output name. Tests independently expect 44,100 source-content frames, verify cleanup after declared-duration truncation and strip metadata to exercise genuinely undeclared raw streams.

The existing `tone-44k-stereo.mp3` fixture and its measured tone/hash evidence remain described in [decoder tests](../../src/jobs/remote/decode/tests.rs). FFmpeg is a fixture-generation tool; it is not a shipped dependency or a runtime conversion service.

`silence-1hz.flac` was created for Yap by Grant McNatt with FFmpeg 7.1.5. It contains 64 mono zero-valued source frames at 1 Hz, with declared length and PCM checksum. It exercises valid extreme-rate duration, bounded resampling/cancellation, and mutated declared-duration rejection without a large fixture. SHA-256: `4052212b45474d127e3e5bdd4fea94e87a74393c212c1785403fa2bafd093116`.

```bash
ffmpeg -f lavfi -i 'aevalsrc=0:s=1:d=64' -c:a flac \
  -map_metadata -1 -fflags +bitexact -flags:a +bitexact silence-1hz.flac
```

`tone-44k-stereo.ogg` was created for Yap by Grant McNatt with FFmpeg 7.1.5. It contains the same one-second stereo 440 Hz/12 kHz tones encoded as Ogg Vorbis with final granule-position duration. SHA-256: `28bd80d98f45fff2ff132d0da458724a4cddd182dc061a4769f8cca5fba95f0c`. Use the FLAC generation command with `-c:a libvorbis -q:a 4` instead of `-c:a flac -sample_fmt s16`, and this Ogg output name. The single-page duration regression verifies encoder padding against the declared one-second content.

`tone-44k-pages.ogg` uses the same stereo source and command with `-page_duration 250000`. Its four audio pages exercise final granule-position trimming, damaged middle-page refusal and missing endings. SHA-256: `2315a4224a357f3c3bf7b7023b55200bcf8edf99d90ff17007ea5989afa88538`.

`tone-opus.ogg` is deliberately unsupported input, created by Grant McNatt with FFmpeg 7.1.5 using `-f lavfi -i 'sine=frequency=440:sample_rate=48000:duration=1' -c:a libopus -b:a 64k -map_metadata -1 -fflags +bitexact -flags:a +bitexact`. SHA-256: `7c169cd9db66242fb1821be28b5282b5934105abcd30b8f01fd39b98303c5d01`.

`tone-two-tracks.ogg` is deliberately ambiguous input: separate one-second mono tracks at 440 Hz and 880 Hz, created by Grant McNatt with FFmpeg 7.1.5. Use two `sine` inputs at 44.1 kHz with `-map 0:a -map 1:a -c:a libvorbis -q:a 4 -map_metadata -1 -fflags +bitexact -flags:a +bitexact`. SHA-256: `2548249114652993c2af388720e7dc42bec9160d62806ce504ee4451ec77fb96`. It and concatenated complete fixtures verify refusal of multiple/chained streams without silently omitting audio.

## AAC in M4A/MP4

Grant McNatt created these synthetic fixtures with FFmpeg 7.1.5. They verify container timing, actual decoding and refusal; they contain no speech. FFmpeg remains a fixture-generation tool, not a shipped dependency.

| Fixture | Content and expected source frames | SHA-256 |
| --- | --- | --- |
| `tone-44k-stereo.m4a` | AAC-LC, 44.1 kHz, stereo 440 Hz/12 kHz; 44,100 presentation frames after the declared 1,024-frame priming edit | `009baf20f4bf0be9d8846e959c8583aa25fb3442923bee4479cd4e9cac1240e5` |
| `tone-video.mp4` | The same AAC track plus a 16×16 black MPEG-4 video track; 44,100 audio frames | `58265dea7633beb1e13e5f6df71b14214b0967d29e29b1e748573f90c301f100` |
| `tone-tail-moov.m4a` | The same audio with metadata after media; 44,100 frames | `49bb5689cb77598256922732c98256479ebc87194df20fcae71e2934fafffac6` |
| `tone-997ms.m4a` | Mono 440 Hz AAC-LC; 43,968 available presentation frames; edit duration 997 ticks and track duration 998 ticks at 1,000 Hz | `141ed80ca97a434d04a594e0c31976e2196755aded6d331a228e0577e5e88acf` |
| `tone-no-edit.m4a` | The stereo source without an edit list; all 45,124 declared media frames retained, including priming | `98d071bd694b06edaec9378518d20798af093efb3b26ede2f26aa57f7e7f9ef0` |
| `tone-two-tracks.m4a` | Separate mono 440 Hz/880 Hz AAC tracks; refused as ambiguous | `5514dd9ae029861e61572a7863b623176c56a43feec2cae1caf2715241fc3390` |
| `tone-alac.m4a` | Mono 440 Hz ALAC; refused as an unsupported codec | `48fe21954bf519f351cc54d68b68367b5edb0ef95be382172eed7e56ce612d5e` |
| `tone-fragmented.mp4` | Mono 440 Hz AAC in a fragmented container; refused | `1b71b4ed5a068ad6ca64acc934a922fc4b50f7aeb984fda96b157365d6ec88c5` |

Generate the stereo source:

```bash
ffmpeg -f lavfi -i 'sine=frequency=440:sample_rate=44100:duration=1' \
  -f lavfi -i 'sine=frequency=12000:sample_rate=44100:duration=1' \
  -filter_complex '[0:a][1:a]amerge=inputs=2[a]' -map '[a]' \
  -c:a aac -b:a 192k -map_metadata -1 -fflags +bitexact -flags:a +bitexact \
  -movflags +faststart tone-44k-stereo.m4a
ffmpeg -f lavfi -i 'color=c=black:s=16x16:r=10:d=1' -i tone-44k-stereo.m4a \
  -map 0:v -map 1:a -c:v mpeg4 -c:a copy -map_metadata -1 \
  -fflags +bitexact -flags:v +bitexact -movflags +faststart tone-video.mp4
ffmpeg -i tone-44k-stereo.m4a -map 0:a -c:a copy -map_metadata -1 \
  -fflags +bitexact -flags:a +bitexact tone-tail-moov.m4a
ffmpeg -i tone-44k-stereo.m4a -map 0:a -c:a copy -map_metadata -1 \
  -fflags +bitexact -flags:a +bitexact -use_editlist 0 tone-no-edit.m4a
```

For the fractional fixture, use a mono 440 Hz input with `duration=0.997`, `-c:a aac -b:a 96k` and the same metadata, bitexact and faststart options. For two tracks, use separate 440 Hz and 880 Hz mono inputs at 44.1 kHz for one second, `-map 0:a -map 1:a -c:a aac -b:a 96k` with those options. For ALAC, use a one-second mono 440 Hz input and `-c:a alac`. For fragmentation, use that mono input with `-c:a aac -b:a 96k`, replacing faststart with `-movflags +frag_keyframe+empty_moov`.

Tests also mutate these actual containers' edit lists, packet durations and track duration, truncate media, and rename a non-MP4 source. Every refusal must preserve the original and an unrelated neighboring file while removing only its own temporary decoded output.
