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
mod tests;
