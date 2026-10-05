//! Decodes a compressed import into the canonical mono PCM16 16 kHz WAV that
//! the rest of the pipeline already admits.
//!
//! The hardened parser in `wav.rs` stays the admission boundary for untrusted
//! containers. This module never widens it: it produces a Yap-owned canonical
//! file, and that file is then inspected, frozen, hashed and chunked by the
//! unchanged path. What the source was is recorded as evidence rather than
//! being reported as an identity normalization.

use std::{
    io::{Seek, SeekFrom},
    path::Path,
};

use symphonia::core::{
    codecs::audio::{
        well_known::{CODEC_ID_AAC, CODEC_ID_FLAC},
        AudioCodecParameters, AudioDecoderOptions,
    },
    errors::Error as SymphoniaError,
    formats::{probe::Hint, FormatReader, Track},
    io::{MediaSource, MediaSourceStream, ReadOnlySource},
};

mod mpeg4_timing;
mod temp;
use crate::audio::preprocess::{downmix_to_mono, f32_to_i16, LinearResampler};
use temp::DecodedFile;

pub(super) const CANONICAL_SAMPLE_RATE_HZ: u32 = 16_000;
/// Four hours at the canonical rate, matching the WAV admission ceiling. A
/// small compressed file can describe far more audio than it occupies, so this
/// is enforced while decoding rather than after.
const MAX_SOURCE_DURATION_SECONDS: u64 = 4 * 60 * 60;
const MAX_OUTPUT_SAMPLES: u64 = MAX_SOURCE_DURATION_SECONDS * CANONICAL_SAMPLE_RATE_HZ as u64;
// At most one second of input and 4,096 frames per call. At the minimum
// legal rate (1 Hz), one retained interpolation frame adds at most another
// second: output stays below 32,768 f32 samples (128 KiB capacity).
const MAX_INPUT_CHUNK_FRAMES: usize = 4_096;
const MAX_RESAMPLED_CHUNK_SAMPLES: usize = 32_768;

/// Extensions this build can decode. `wav` is absent on purpose: canonical WAV
/// goes straight to the hardened parser and is never re-encoded.
pub(super) const DECODABLE_EXTENSIONS: &[&str] = &["mp3", "flac", "ogg", "m4a", "mp4"];

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

fn decode_to_canonical_wav(
    source_path: &Path,
    source: &std::fs::File,
    destination: &mut std::fs::File,
    ensure_active: &mut impl FnMut() -> Result<(), String>,
) -> Result<DecodedSource, String> {
    ensure_active()?;
    let mut file = source
        .try_clone()
        .map_err(|error| format!("failed to access imported audio: {error}"))?;
    file.seek(SeekFrom::Start(0))
        .map_err(|error| format!("failed to seek imported audio: {error}"))?;
    let is_mpeg4 = source_path
        .extension()
        .and_then(|value| value.to_str())
        .is_some_and(|value| {
            value.eq_ignore_ascii_case("m4a") || value.eq_ignore_ascii_case("mp4")
        });
    let timing = if is_mpeg4 {
        Some(mpeg4_timing::MovieTiming::read(&mut file, ensure_active)?)
    } else {
        None
    };
    // Preparation is sequential. Do not let the reader estimate a duration
    // from seekable-file bitrate and treat that estimate as a declared ending.
    // Container-provided counts and trim metadata remain available.
    let mut hint = Hint::new();
    if let Some(extension) = source_path.extension().and_then(|value| value.to_str()) {
        hint.with_extension(extension);
    }
    let mut format = probe_import(
        file.try_clone()
            .map_err(|error| format!("failed to inspect imported audio: {error}"))?,
        &hint,
        is_mpeg4,
    )?;
    if is_mpeg4 && format.format_info().short_name != "isomp4" {
        return Err("M4A/MP4 recording is not an ISO MP4 container".into());
    }
    let (initial_track, parameters) = audio_track(format.as_ref())?;
    let initial_declared_frames = initial_track.num_frames;
    if is_mpeg4 && parameters.codec != CODEC_ID_AAC {
        return Err("M4A/MP4 recordings require one AAC-LC audio track".into());
    }
    let is_ogg = format.format_info().short_name == "ogg";
    if is_ogg {
        // Ogg duration is declared by final granule positions, not a bitrate
        // estimate. Let its reader inspect the ending on the admitted handle.
        drop(format);
        file.seek(SeekFrom::Start(0))
            .map_err(|error| format!("failed to inspect imported audio: {error}"))?;
        ensure_active()?;
        format = probe_import(file, &hint, true)?;
    }
    let (track, parameters) = audio_track(format.as_ref())?;
    if track.num_frames == Some(0) {
        return Err("imported audio has inconsistent trim or declared duration metadata".into());
    }
    if is_mpeg4 && track.num_frames.is_none() {
        return Err("M4A/MP4 recording has no complete declared duration".into());
    }
    if is_ogg && track.num_frames.is_none() {
        return Err(
            "Ogg recording has no complete declared ending; select an intact recording".into(),
        );
    }
    if is_ogg && initial_declared_frames.is_some_and(|frames| Some(frames) != track.num_frames) {
        return Err("Ogg recording has conflicting declared duration metadata".into());
    }
    let track_id = track.id;
    let is_flac = parameters.codec == CODEC_ID_FLAC;
    let expected_source_frames = track.num_frames;
    let source_codec = format!("{:?}", parameters.codec);
    let source_sample_rate_hz = parameters
        .sample_rate
        .ok_or_else(|| "imported audio does not declare a sample rate".to_string())?;
    validate_source_duration(expected_source_frames.unwrap_or(0), source_sample_rate_hz)?;
    let content_range = timing
        .as_ref()
        .map(|timing| {
            timing.content(
                track_id,
                source_sample_rate_hz,
                expected_source_frames.unwrap(),
            )
        })
        .transpose()?;
    let expected_content_frames = content_range
        .map(|range| range.end - range.start)
        .or(expected_source_frames);
    let input_chunk_frames = (source_sample_rate_hz as usize).min(MAX_INPUT_CHUNK_FRAMES);
    let channel_count = parameters
        .channels
        .as_ref()
        .ok_or_else(|| "imported audio does not declare a channel layout".to_string())?
        .count();
    if channel_count == 0 || channel_count > 8 {
        return Err("imported audio declares an unsupported channel count".into());
    }
    let mut decoder = symphonia::default::get_codecs()
        .make_audio_decoder(
            parameters,
            &AudioDecoderOptions::default().gapless(true).verify(is_flac),
        )
        .map_err(|_| "imported audio uses an unsupported codec".to_string())?;

    let mut writer = hound::WavWriter::new(
        std::io::BufWriter::new(destination),
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
    let mut media_frame_count = 0_u64;
    let mut output_sample_count = 0_u64;
    loop {
        ensure_active()?;
        let packet = match format.next_packet() {
            Ok(Some(packet)) => packet,
            Ok(None) => break,
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
        if packet.track_id != track_id {
            continue;
        }
        let decoded = match decoder.decode(&packet) {
            Ok(decoded) => decoded,
            // Omitting a damaged packet would shorten the recording while
            // claiming that normalization preserved its source timeline.
            Err(SymphoniaError::DecodeError(_)) => {
                return Err(
                    "imported audio contains a damaged packet; select an intact recording".into(),
                );
            }
            Err(error) => return Err(format!("failed to decode imported audio: {error}")),
        };
        let spec = decoded.spec();
        // downmix and resampling both use the header's values, so a mid-stream
        // change would quietly mix the wrong channel count and resample at the
        // wrong ratio.
        if spec.channels().count() != channel_count || spec.rate() != source_sample_rate_hz {
            return Err("imported audio changes channel layout or sample rate mid-stream".into());
        }
        let mut interleaved = vec![0.0_f32; decoded.samples_interleaved()];
        decoded.copy_to_slice_interleaved(&mut interleaved);
        let interleaved = if let Some(range) = content_range {
            let frames = packet.dur.get();
            let end = media_frame_count
                .checked_add(frames)
                .ok_or_else(|| "M4A/MP4 packet duration is out of range".to_string())?;
            let decoded_frames = (interleaved.len() / channel_count) as u64;
            if u64::try_from(packet.pts.get()).ok() != Some(media_frame_count)
                || packet.dts != packet.pts
                || packet.trim_start.get() != 0
                || packet.trim_end.get() != 0
                || frames == 0
                || frames > decoded_frames
                || (frames != decoded_frames && Some(end) != expected_source_frames)
            {
                return Err("M4A/MP4 audio packets do not match their declared timeline".into());
            }
            let start = range.start.saturating_sub(media_frame_count).min(frames) as usize;
            let stop = range.end.saturating_sub(media_frame_count).min(frames) as usize;
            media_frame_count = end;
            validate_source_duration(media_frame_count, source_sample_rate_hz)?;
            &interleaved[start * channel_count..stop * channel_count]
        } else {
            &interleaved[..]
        };
        source_frame_count = source_frame_count
            .checked_add((interleaved.len() / channel_count) as u64)
            .ok_or_else(|| "imported audio frame count is out of range".to_string())?;
        validate_source_duration(source_frame_count, source_sample_rate_hz)?;
        let mono = downmix_to_mono(interleaved, channel_count);
        for chunk in mono.chunks(input_chunk_frames) {
            ensure_active()?;
            let resampled = resampler.push(chunk);
            write_resampled_audio(&mut writer, &resampled, &mut output_sample_count)?;
        }
    }
    if output_sample_count == 0 {
        return Err("imported audio decoded to no audio".into());
    }
    if expected_content_frames.is_some_and(|expected| expected != source_frame_count)
        || (is_mpeg4 && Some(media_frame_count) != expected_source_frames)
    {
        return Err("imported audio does not match its declared duration".into());
    }
    if decoder.finalize().verify_ok == Some(false) {
        return Err("imported audio failed its integrity check".into());
    }

    ensure_active()?;
    write_resampled_audio(&mut writer, &resampler.finish(), &mut output_sample_count)?;

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

fn validate_source_duration(frames: u64, sample_rate: u32) -> Result<(), String> {
    if sample_rate == 0 {
        return Err("imported audio declares an invalid sample rate".into());
    }
    if frames > u64::from(sample_rate) * MAX_SOURCE_DURATION_SECONDS {
        return Err("imported audio decodes to more than the four-hour ceiling".into());
    }
    Ok(())
}

fn write_resampled_audio(
    writer: &mut hound::WavWriter<impl std::io::Write + Seek>,
    samples: &[f32],
    output_count: &mut u64,
) -> Result<(), String> {
    if samples.len() > MAX_RESAMPLED_CHUNK_SAMPLES {
        return Err("imported audio exceeded its resampling work bound".into());
    }
    let next_count = output_count
        .checked_add(samples.len() as u64)
        .filter(|count| *count <= MAX_OUTPUT_SAMPLES)
        .ok_or_else(|| "imported audio decodes to more than the four-hour ceiling".to_string())?;
    for sample in samples {
        writer
            .write_sample(f32_to_i16(*sample))
            .map_err(|error| format!("failed to write decoded audio: {error}"))?;
    }
    *output_count = next_count;
    Ok(())
}

fn audio_track(format: &dyn FormatReader) -> Result<(&Track, &AudioCodecParameters), String> {
    let mut tracks = format.tracks().iter().filter_map(|track| {
        track
            .codec_params
            .as_ref()?
            .audio()
            .map(|parameters| (track, parameters))
    });
    let track = tracks
        .next()
        .ok_or_else(|| "imported audio has no decodable track".to_string())?;
    if tracks.next().is_some() {
        return Err(
            "imported audio contains multiple audio tracks; select a single-track recording".into(),
        );
    }
    Ok(track)
}

fn probe_import(
    file: std::fs::File,
    hint: &Hint,
    seekable: bool,
) -> Result<Box<dyn FormatReader>, String> {
    let source: Box<dyn MediaSource> = if seekable {
        Box::new(file)
    } else {
        Box::new(ReadOnlySource::new(file))
    };
    let stream = MediaSourceStream::new(source, Default::default());
    symphonia::default::get_probe()
        .probe(hint, stream, Default::default(), Default::default())
        .map_err(|_| "imported audio is not a supported container".to_string())
}

/// A decoded canonical WAV owned by this job, deleted once preparation has
/// frozen its own snapshot.
pub(in crate::jobs) struct DecodedImport {
    #[cfg(test)]
    pub(in crate::jobs) path: std::path::PathBuf,
    pub(in crate::jobs) evidence: DecodedSource,
    owned: DecodedFile,
}

impl DecodedImport {
    pub(in crate::jobs) fn open_source(&self) -> Result<std::fs::File, String> {
        let mut file = self
            .owned
            .file
            .try_clone()
            .map_err(|error| format!("failed to access decoded audio: {error}"))?;
        file.seek(SeekFrom::Start(0))
            .map_err(|error| format!("failed to seek decoded audio: {error}"))?;
        Ok(file)
    }
}

/// Decodes `source_path` when it is a compressed import, or returns `None` when
/// it is already canonical and belongs to the hardened parser unchanged.
pub(in crate::jobs) fn decode_import_if_compressed(
    source_path: &Path,
    source: &std::fs::File,
    expected: &crate::media_protocol::MediaSourceFingerprint,
    job_id: &str,
    spool_root: &Path,
    mut ensure_active: impl FnMut() -> Result<(), String>,
) -> Result<Option<DecodedImport>, String> {
    if !is_decodable_extension(source_path) {
        return Ok(None);
    }
    ensure_active()?;
    crate::media_protocol::verify_opened_media_source(source, expected)?;
    let mut owned = DecodedFile::create(spool_root, job_id)?;
    let evidence =
        decode_to_canonical_wav(source_path, source, &mut owned.file, &mut ensure_active)?;
    ensure_active()?;
    crate::media_protocol::verify_opened_media_source(source, expected)?;
    Ok(Some(DecodedImport {
        #[cfg(test)]
        path: owned.path.clone(),
        evidence,
        owned,
    }))
}

#[cfg(test)]
mod tests;
