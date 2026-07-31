//! Decodes a compressed import into the canonical mono PCM16 16 kHz WAV that
//! the rest of the pipeline already admits.
//!
//! The hardened parser in `wav.rs` stays the admission boundary for untrusted
//! containers. This module never widens it: it produces a Yap-owned canonical
//! file, and that file is then inspected, frozen, hashed and chunked by the
//! unchanged path. What the source was is recorded as evidence rather than
//! being reported as an identity normalization.

use std::path::Path;

use symphonia::core::{
    audio::SampleBuffer,
    codecs::{DecoderOptions, CODEC_TYPE_NULL},
    errors::Error as SymphoniaError,
    io::MediaSourceStream,
    probe::Hint,
};

use super::artifact_io::{metadata_is_link_or_reparse, open_no_follow_read};
use crate::audio::preprocess::{downmix_to_mono, f32_to_i16, LinearResampler};

pub(super) const CANONICAL_SAMPLE_RATE_HZ: u32 = 16_000;
/// Four hours at the canonical rate, matching the WAV admission ceiling. A
/// small compressed file can describe far more audio than it occupies, so this
/// is enforced while decoding rather than after.
const MAX_OUTPUT_SAMPLES: usize = 4 * 60 * 60 * CANONICAL_SAMPLE_RATE_HZ as usize;

/// Extensions this build can decode. `wav` is absent on purpose: canonical WAV
/// goes straight to the hardened parser and is never re-encoded.
pub(super) const DECODABLE_EXTENSIONS: &[&str] = &["mp3"];

pub(super) fn is_decodable_extension(path: &Path) -> bool {
    path.extension()
        .and_then(|value| value.to_str())
        .map(|value| value.to_ascii_lowercase())
        .is_some_and(|value| DECODABLE_EXTENSIONS.contains(&value.as_str()))
}

/// What the decode observed about the source, for the normalization record.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(in crate::jobs) struct DecodedSource {
    pub(in crate::jobs) source_codec: String,
    pub(in crate::jobs) source_sample_rate_hz: u32,
    pub(in crate::jobs) source_channels: u16,
    pub(in crate::jobs) source_frame_count: u64,
    pub(in crate::jobs) output_sample_count: u64,
}

pub(super) fn decode_to_canonical_wav(
    source_path: &Path,
    destination: &Path,
    ensure_active: &mut impl FnMut() -> Result<(), String>,
) -> Result<DecodedSource, String> {
    ensure_active()?;
    // The spool admits this file by refusing links and reparse points, so
    // re-opening it with a bare File::open would discard that refusal and let a
    // link planted at the admitted path redirect the decode. Use the same pair
    // of helpers the sibling chunk and spool paths already use: the open refuses
    // a link outright on Unix, while Windows opens the reparse point itself so
    // the metadata check is what rejects it there. Everything after this reads
    // from the handle rather than the path, so the admitted object is the one
    // that gets decoded.
    let file = open_no_follow_read(source_path)
        .map_err(|error| format!("failed to open imported audio: {error}"))?;
    let source_metadata = file
        .metadata()
        .map_err(|error| format!("failed to inspect imported audio: {error}"))?;
    if !source_metadata.is_file() || metadata_is_link_or_reparse(&source_metadata) {
        return Err("imported audio is not a regular file".into());
    }
    let stream = MediaSourceStream::new(Box::new(file), Default::default());
    let mut hint = Hint::new();
    if let Some(extension) = source_path.extension().and_then(|value| value.to_str()) {
        hint.with_extension(extension);
    }
    let probed = symphonia::default::get_probe()
        .format(&hint, stream, &Default::default(), &Default::default())
        .map_err(|_| "imported audio is not a supported container".to_string())?;
    let mut format = probed.format;
    let track = format
        .tracks()
        .iter()
        .find(|track| track.codec_params.codec != CODEC_TYPE_NULL)
        .ok_or_else(|| "imported audio has no decodable track".to_string())?;
    let track_id = track.id;
    let source_codec = format!("{:?}", track.codec_params.codec);
    let source_sample_rate_hz = track
        .codec_params
        .sample_rate
        .ok_or_else(|| "imported audio does not declare a sample rate".to_string())?;
    let channel_count = track
        .codec_params
        .channels
        .ok_or_else(|| "imported audio does not declare a channel layout".to_string())?
        .count();
    if channel_count == 0 || channel_count > 8 {
        return Err("imported audio declares an unsupported channel count".into());
    }
    let mut decoder = symphonia::default::get_codecs()
        .make(&track.codec_params, &DecoderOptions::default())
        .map_err(|_| "imported audio uses an unsupported codec".to_string())?;

    let mut writer = hound::WavWriter::create(
        destination,
        hound::WavSpec {
            channels: 1,
            sample_rate: CANONICAL_SAMPLE_RATE_HZ,
            bits_per_sample: 16,
            sample_format: hound::SampleFormat::Int,
        },
    )
    .map_err(|error| format!("failed to create decoded audio: {error}"))?;

    let mut resampler = LinearResampler::new(source_sample_rate_hz, CANONICAL_SAMPLE_RATE_HZ);
    let mut source_frame_count = 0_u64;
    let mut output_sample_count = 0_u64;
    loop {
        ensure_active()?;
        let packet = match format.next_packet() {
            Ok(packet) => packet,
            // Only an unexpected EOF is the end of the stream. Any other IO
            // failure would otherwise truncate the audio silently and hand back
            // a short transcript with no indication anything was lost.
            Err(SymphoniaError::IoError(error))
                if error.kind() == std::io::ErrorKind::UnexpectedEof =>
            {
                break
            }
            Err(SymphoniaError::IoError(error)) => {
                return Err(format!("failed to read imported audio: {error}"))
            }
            // The stream changed shape mid-file. Continuing would decode the
            // remainder against stale parameters, so refuse rather than emit
            // audio that silently stops matching its source.
            Err(SymphoniaError::ResetRequired) => {
                return Err("imported audio changes format mid-stream".into())
            }
            Err(error) => return Err(format!("failed to read imported audio: {error}")),
        };
        if packet.track_id() != track_id {
            continue;
        }
        let decoded = match decoder.decode(&packet) {
            Ok(decoded) => decoded,
            // A damaged packet is skipped; a structurally broken stream is not.
            Err(SymphoniaError::DecodeError(_)) => continue,
            Err(error) => return Err(format!("failed to decode imported audio: {error}")),
        };
        let spec = *decoded.spec();
        // downmix and resampling both use the header's values, so a mid-stream
        // change would quietly mix the wrong channel count and resample at the
        // wrong ratio.
        if spec.channels.count() != channel_count || spec.rate != source_sample_rate_hz {
            return Err("imported audio changes channel layout or sample rate mid-stream".into());
        }
        let mut buffer = SampleBuffer::<f32>::new(decoded.capacity() as u64, spec);
        buffer.copy_interleaved_ref(decoded);
        let interleaved = buffer.samples();
        source_frame_count += (interleaved.len() / channel_count) as u64;
        let mono = downmix_to_mono(interleaved, channel_count);
        let resampled = resampler.push(&mono);
        output_sample_count += resampled.len() as u64;
        if output_sample_count > MAX_OUTPUT_SAMPLES as u64 {
            return Err("imported audio decodes to more than the four-hour ceiling".into());
        }
        for sample in &resampled {
            writer
                .write_sample(f32_to_i16(*sample))
                .map_err(|error| format!("failed to write decoded audio: {error}"))?;
        }
    }
    if output_sample_count == 0 {
        return Err("imported audio decoded to no audio".into());
    }

    // finalize patches the RIFF and data lengths, which is the part that most
    // wants a library rather than a hand-rolled seek back over the header.
    writer
        .finalize()
        .map_err(|error| format!("failed to finalize decoded audio: {error}"))?;

    Ok(DecodedSource {
        source_codec,
        source_sample_rate_hz,
        source_channels: channel_count as u16,
        source_frame_count,
        output_sample_count,
    })
}

/// A decoded canonical WAV owned by this job, deleted once preparation has
/// frozen its own snapshot.
pub(in crate::jobs) struct DecodedImport {
    pub(in crate::jobs) path: std::path::PathBuf,
    pub(in crate::jobs) evidence: DecodedSource,
}

/// Removing on drop rather than at a call site: this file holds a plaintext
/// copy of the user's audio, and every fallible step between the decode and
/// the end of preparation -- cancellation, a rejected header, a failed write --
/// would otherwise leave it behind with nothing to reclaim it.
impl Drop for DecodedImport {
    fn drop(&mut self) {
        // Preparation has frozen its own snapshot by now, so losing this is
        // recoverable; the next run re-decodes.
        let _ = std::fs::remove_file(&self.path);
    }
}

/// Decodes `source_path` when it is a compressed import, or returns `None` when
/// it is already canonical and belongs to the hardened parser unchanged.
pub(in crate::jobs) fn decode_import_if_compressed(
    source_path: &Path,
    job_id: &str,
    spool_root: &Path,
    mut ensure_active: impl FnMut() -> Result<(), String>,
) -> Result<Option<DecodedImport>, String> {
    if !is_decodable_extension(source_path) {
        return Ok(None);
    }
    std::fs::create_dir_all(spool_root)
        .map_err(|error| format!("failed to prepare the decode directory: {error}"))?;
    let path = spool_root.join(format!(".{job_id}-decoded-{}.wav", std::process::id()));
    match decode_to_canonical_wav(source_path, &path, &mut ensure_active) {
        Ok(evidence) => Ok(Some(DecodedImport { path, evidence })),
        Err(error) => {
            let _ = std::fs::remove_file(&path);
            Err(error)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs::File;
    use std::io::Read;

    fn fixture(name: &str) -> std::path::PathBuf {
        Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("tests")
            .join("fixtures")
            .join(name)
    }

    fn scratch(label: &str) -> std::path::PathBuf {
        let directory = std::env::temp_dir().join(format!(
            "yap-decode-{label}-{}-{:?}",
            std::process::id(),
            std::thread::current().id()
        ));
        std::fs::create_dir_all(&directory).expect("scratch dir");
        directory
    }

    fn decode(name: &str) -> (DecodedSource, Vec<u8>) {
        let directory = scratch(name);
        let destination = directory.join("decoded.wav");
        let evidence =
            decode_to_canonical_wav(&fixture(name), &destination, &mut || Ok(())).expect("decode");
        let mut bytes = Vec::new();
        File::open(&destination)
            .expect("open decoded")
            .read_to_end(&mut bytes)
            .expect("read decoded");
        std::fs::remove_dir_all(&directory).ok();
        (evidence, bytes)
    }

    fn samples(bytes: &[u8]) -> Vec<f32> {
        bytes[44..]
            .chunks_exact(2)
            .map(|pair| i16::from_le_bytes([pair[0], pair[1]]) as f32 / i16::MAX as f32)
            .collect()
    }

    /// Magnitude of one frequency, so the assertions describe audio rather than
    /// byte arithmetic.
    fn magnitude(samples: &[f32], hz: f64) -> f64 {
        let step = std::f64::consts::TAU * hz / CANONICAL_SAMPLE_RATE_HZ as f64;
        let (mut real, mut imaginary) = (0.0_f64, 0.0_f64);
        for (index, value) in samples.iter().enumerate() {
            let angle = step * index as f64;
            real += *value as f64 * angle.cos();
            imaginary += *value as f64 * angle.sin();
        }
        (real * real + imaginary * imaginary).sqrt() / samples.len() as f64 * 2.0
    }

    #[test]
    fn decodes_a_compressed_import_to_the_canonical_header() {
        let (evidence, bytes) = decode("tone-44k-stereo.mp3");

        assert_eq!(&bytes[0..4], b"RIFF");
        assert_eq!(&bytes[8..12], b"WAVE");
        assert_eq!(u16::from_le_bytes(bytes[22..24].try_into().unwrap()), 1);
        assert_eq!(
            u32::from_le_bytes(bytes[24..28].try_into().unwrap()),
            CANONICAL_SAMPLE_RATE_HZ
        );
        assert_eq!(u16::from_le_bytes(bytes[34..36].try_into().unwrap()), 16);
        // The declared RIFF length must equal the physical file length, which
        // is what the hardened parser reconciles.
        assert_eq!(
            u64::from(u32::from_le_bytes(bytes[4..8].try_into().unwrap())) + 8,
            bytes.len() as u64
        );
        assert_eq!(evidence.source_sample_rate_hz, 44_100);
        assert_eq!(evidence.source_channels, 2);
    }

    #[test]
    fn decoded_output_holds_the_source_duration() {
        let (evidence, bytes) = decode("tone-44k-stereo.mp3");

        let expected = evidence.source_frame_count * u64::from(CANONICAL_SAMPLE_RATE_HZ)
            / u64::from(evidence.source_sample_rate_hz);
        // Resampling a ratio that does not divide evenly lands on a boundary
        // sample, so the count can differ by one from the truncated quotient.
        // One sample at 16 kHz is 62.5 microseconds; asserting exact equality
        // would pin the resampler's boundary handling rather than the duration.
        let drift = evidence.output_sample_count.abs_diff(expected);
        assert!(
            drift <= 1,
            "decoded {} samples against an expected {expected}",
            evidence.output_sample_count
        );
        assert_eq!(samples(&bytes).len() as u64, evidence.output_sample_count);
    }

    /// The aliasing check below is only meaningful while the fixture actually
    /// carries an out-of-band tone and no 4 kHz content of its own. Neither
    /// property is visible in the decoded output, so nothing else can notice if
    /// the fixture is regenerated without them: the check would keep passing
    /// while testing nothing. Pin the bytes so that has to be deliberate.
    ///
    /// Measured on the pinned file, decoded to mono f32 at its own 44.1 kHz over
    /// a one-second settled window:
    ///
    /// ```text
    ///   440 Hz: 0.029682     4 kHz: 0.000000    12 kHz: 0.029685
    /// ```
    ///
    /// Equivalent content can be regenerated with the command below. It yields
    /// the two properties the check needs — the tones at equal amplitude and no
    /// 4 kHz — but at a different absolute level, so it is a replacement rather
    /// than a reproduction. The check compares the fold against the speech tone
    /// rather than an absolute floor, so the level does not matter; the hash
    /// would still need repinning.
    ///
    /// ```text
    /// ffmpeg -f lavfi -i "sine=frequency=440:sample_rate=44100:duration=2" \
    ///        -f lavfi -i "sine=frequency=12000:sample_rate=44100:duration=2" \
    ///        -filter_complex "[0][1]amix=inputs=2,pan=stereo|c0=c0|c1=c0" \
    ///        -c:a libmp3lame tone-44k-stereo.mp3
    /// ```
    #[test]
    fn the_aliasing_fixture_still_holds_the_tones_the_check_depends_on() {
        let bytes = std::fs::read(fixture("tone-44k-stereo.mp3")).expect("read fixture");
        let digest = crate::jobs::remote::artifact_io::sha256_bytes(&bytes);
        assert_eq!(
            digest, "ca25e3b53ab25cd7d6fb0c53fb01aee6270e28e2dfe343299e987838c490e1c3",
            "the aliasing fixture changed; re-measure that it still carries 12 kHz and no \
             4 kHz before repinning, or decoding_band_limits_before_it_resamples proves nothing"
        );
    }

    /// The fixture carries 440 Hz and 12 kHz. At 16 kHz the 12 kHz tone would
    /// fold onto 4 kHz without band limiting, so this is the decode path's
    /// aliasing check. Its premise is pinned by the test above.
    #[test]
    fn decoding_band_limits_before_it_resamples() {
        let (_evidence, bytes) = decode("tone-44k-stereo.mp3");
        let decoded = samples(&bytes);
        let settled = &decoded[decoded.len() / 2..];

        let speech = magnitude(settled, 440.0);
        let folded = magnitude(settled, 4_000.0);
        assert!(speech > 0.01, "440 Hz was lost, magnitude {speech}");
        assert!(
            folded < speech / 100.0,
            "12 kHz folded onto 4 kHz at {folded} against {speech} of speech"
        );
    }

    #[test]
    fn only_decodable_extensions_are_claimed() {
        assert!(is_decodable_extension(Path::new("a.mp3")));
        assert!(is_decodable_extension(Path::new("a.MP3")));
        // Canonical WAV must reach the hardened parser, never this path.
        assert!(!is_decodable_extension(Path::new("a.wav")));
        assert!(!is_decodable_extension(Path::new("a.m4a")));
        assert!(!is_decodable_extension(Path::new("a")));
    }

    #[test]
    fn a_non_container_is_refused() {
        let directory = scratch("bogus");
        let bogus = directory.join("bogus.mp3");
        std::fs::write(&bogus, b"this is not audio").expect("write");
        let error = decode_to_canonical_wav(&bogus, &directory.join("out.wav"), &mut || Ok(()))
            .expect_err("must refuse");
        assert!(
            error.contains("supported container") || error.contains("no audio"),
            "{error}"
        );
    }

    #[cfg(unix)]
    fn create_file_symlink(source: &Path, destination: &Path) -> std::io::Result<()> {
        std::os::unix::fs::symlink(source, destination)
    }

    #[cfg(windows)]
    fn create_file_symlink(source: &Path, destination: &Path) -> std::io::Result<()> {
        std::os::windows::fs::symlink_file(source, destination)
    }

    /// Creating a symlink needs a privilege that Windows does not grant by
    /// default, so an unprivileged run skips rather than failing.
    fn test_symlink_is_unavailable(error: &std::io::Error) -> bool {
        cfg!(windows)
            && (error.kind() == std::io::ErrorKind::PermissionDenied
                || error.raw_os_error() == Some(1314))
    }

    /// The spool admits an import by refusing links and reparse points. Decoding
    /// re-opens by path, so it has to refuse them too, or a link planted at the
    /// admitted path would be decoded instead of the file that was admitted.
    #[test]
    fn a_linked_source_is_refused_rather_than_followed() {
        let directory = scratch("linked");
        let real = directory.join("real.mp3");
        std::fs::copy(fixture("tone-44k-stereo.mp3"), &real).expect("copy fixture");
        let link = directory.join("link.mp3");
        if let Err(error) = create_file_symlink(&real, &link) {
            if test_symlink_is_unavailable(&error) {
                std::fs::remove_dir_all(&directory).ok();
                return;
            }
            panic!("could not create test symlink: {error}");
        }

        // The link resolves to a file that decodes cleanly, so anything other
        // than an open failure means the refusal was skipped rather than the
        // source simply being undecodable.
        decode_to_canonical_wav(&real, &directory.join("direct.wav"), &mut || Ok(()))
            .expect("the link target itself decodes");
        let error = decode_to_canonical_wav(&link, &directory.join("linked.wav"), &mut || Ok(()))
            .expect_err("a linked source must be refused");
        // Unix refuses at the open; Windows opens the reparse point itself, so
        // the metadata check is what rejects it there. Either is the refusal,
        // and neither is the "not a supported container" a pass-through gives.
        assert!(
            error.contains("failed to open imported audio")
                || error.contains("imported audio is not a regular file"),
            "{error}"
        );
    }

    /// A stream that ends mid-frame must not be mistaken for a clean EOF, or a
    /// truncated download would publish a short transcript silently.
    #[test]
    fn a_truncated_stream_does_not_pass_as_complete() {
        let directory = scratch("truncated");
        let whole = std::fs::read(fixture("tone-44k-stereo.mp3")).expect("read fixture");
        let cut = directory.join("truncated.mp3");
        std::fs::write(&cut, &whole[..whole.len() / 2]).expect("write");

        let (evidence, bytes) = {
            let destination = directory.join("decoded.wav");
            let evidence = decode_to_canonical_wav(&cut, &destination, &mut || Ok(()))
                .expect("a truncated stream still decodes what it holds");
            let bytes = std::fs::metadata(&destination).expect("stat").len();
            (evidence, bytes)
        };
        // Half the bytes must yield materially less audio, not the full duration.
        let (full, _) = decode("tone-44k-stereo.mp3");
        assert!(
            evidence.output_sample_count < full.output_sample_count,
            "truncated input produced {} samples against {} for the whole file",
            evidence.output_sample_count,
            full.output_sample_count
        );
        assert!(
            bytes > 44,
            "a decoded file must carry audio past its header"
        );
        std::fs::remove_dir_all(&directory).ok();
    }

    #[test]
    fn cancellation_stops_the_decode() {
        let directory = scratch("cancel");
        let mut calls = 0;
        let error = decode_to_canonical_wav(
            &fixture("tone-44k-stereo.mp3"),
            &directory.join("out.wav"),
            &mut || {
                calls += 1;
                if calls > 2 {
                    Err("cancelled".to_string())
                } else {
                    Ok(())
                }
            },
        )
        .expect_err("must cancel");
        assert_eq!(error, "cancelled");
    }
}
