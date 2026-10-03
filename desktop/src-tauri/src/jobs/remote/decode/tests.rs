use super::*;
use std::fs::File;
use std::io::Read;

fn decode_to_canonical_wav(
    source: &Path,
    destination: &Path,
    active: &mut impl FnMut() -> Result<(), String>,
) -> Result<DecodedSource, String> {
    let mut file = std::fs::OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(true)
        .open(destination)
        .map_err(|e| e.to_string())?;
    let (input, _) = crate::bounded_file::open_regular_file(source, u64::MAX)
        .map_err(|error| format!("failed to open imported audio: {error}"))?;
    super::decode_to_canonical_wav(source, &input, &mut file, active)
}

fn decode_import_if_compressed(
    source: &Path,
    job_id: &str,
    root: &Path,
    active: impl FnMut() -> Result<(), String>,
) -> Result<Option<DecodedImport>, String> {
    if !is_decodable_extension(source) {
        return Ok(None);
    }
    let fingerprint = crate::media_protocol::inspect_media_source(source)?;
    let file = crate::media_protocol::open_unchanged_media_source(source, &fingerprint)?;
    super::decode_import_if_compressed(source, &file, &fingerprint, job_id, root, active)
}

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

fn cancel_after_plaintext(
    source: &Path,
    root: &Path,
    job_id: &str,
) -> (Result<DecodedSource, String>, u64) {
    let fingerprint = crate::media_protocol::inspect_media_source(source).unwrap();
    let input = crate::media_protocol::open_unchanged_media_source(source, &fingerprint).unwrap();
    let mut owned = DecodedFile::create(root, job_id).unwrap();
    // Windows directory-entry lengths can remain stale while a writer is open.
    // Observe the retained object, including its DELETE_ON_CLOSE ownership.
    let observer = owned.file.try_clone().unwrap();
    let mut observed_size = 0;
    let result = super::decode_to_canonical_wav(source, &input, &mut owned.file, &mut || {
        observed_size = observed_size.max(observer.metadata().unwrap().len());
        if observed_size >= 8_192 {
            Err("cancelled".into())
        } else {
            Ok(())
        }
    });
    drop(observer);
    drop(owned);
    (result, observed_size)
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

#[test]
fn declared_mp3_content_duration_excludes_encoder_delay_and_padding() {
    let original = std::fs::read(fixture("tone-44k-gapless.mp3")).unwrap();
    assert_eq!(
        crate::jobs::remote::artifact_io::sha256_bytes(&original),
        "10bd303b40bcc3b84c7dff971a5538ca933bc848ddbf6a30967cd4f819d36116"
    );
    let (evidence, bytes) = decode("tone-44k-gapless.mp3");
    assert_eq!(
        evidence.source_frame_count, 44_100,
        "one second of source content"
    );
    assert!(evidence.output_sample_count.abs_diff(16_000) <= 1);
    assert_eq!(samples(&bytes).len() as u64, evidence.output_sample_count);
    assert_eq!(
        std::fs::read(fixture("tone-44k-gapless.mp3")).unwrap(),
        original
    );
}

#[test]
fn inconsistent_mp3_trim_metadata_is_refused_without_panicking_or_staging() {
    let directory = scratch("inconsistent-mp3-trim");
    let source = directory.join("inconsistent.mp3");
    let mut bytes = std::fs::read(fixture("tone-44k-gapless.mp3")).unwrap();
    let info = bytes
        .windows(4)
        .position(|value| value == b"Info" || value == b"Xing")
        .unwrap();
    // Declared MPEG-frame count follows the tag identifier and flag word.
    // Keep the real encoder delay/padding but declare zero total frames.
    bytes[info + 8..info + 12].fill(0);
    std::fs::write(&source, &bytes).unwrap();
    let error = match decode_import_if_compressed(&source, "bad-trim", &directory, || Ok(())) {
        Err(error) => error,
        Ok(_) => panic!("inconsistent declared trim bounds must be refused"),
    };
    assert!(
        error.contains("trim") || error.contains("declared duration"),
        "{error}"
    );
    assert_eq!(std::fs::read(&source).unwrap(), bytes);
    assert_eq!(std::fs::read_dir(&directory).unwrap().count(), 1);
    std::fs::remove_dir_all(directory).unwrap();
}

#[test]
fn shortened_mp3_with_declared_duration_refuses_partial_audio_and_cleans_staging() {
    let whole = std::fs::read(fixture("tone-44k-gapless.mp3")).unwrap();
    let directory = scratch("short-declared-mp3");
    let source = directory.join("short.mp3");
    // Preserve the duration-bearing header and end on a complete audio packet.
    let stream = MediaSourceStream::new(
        Box::new(File::open(fixture("tone-44k-gapless.mp3")).unwrap()),
        Default::default(),
    );
    let mut format = symphonia::default::get_probe()
        .probe(&Hint::new(), stream, Default::default(), Default::default())
        .unwrap();
    assert!(format
        .default_track(symphonia::core::formats::TrackType::Audio)
        .unwrap()
        .num_frames
        .is_some());
    let mut packet = format.next_packet().unwrap().unwrap();
    for _ in 0..8 {
        packet = format.next_packet().unwrap().unwrap();
    }
    let start = whole
        .windows(packet.data.len())
        .position(|bytes| bytes == packet.data.as_ref())
        .unwrap();
    let shortened = &whole[..start + packet.data.len()];
    std::fs::write(&source, shortened).unwrap();
    let error = match decode_import_if_compressed(&source, "short-declared", &directory, || Ok(()))
    {
        Err(error) => error,
        Ok(_) => panic!("declared duration must prevent acceptance of a shortened recording"),
    };
    assert!(error.contains("declared duration"), "{error}");
    assert_eq!(std::fs::read(&source).unwrap(), shortened);
    assert_eq!(std::fs::read_dir(&directory).unwrap().count(), 1);
    std::fs::remove_dir_all(directory).unwrap();
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
    assert!(is_decodable_extension(Path::new("a.flac")));
    assert!(is_decodable_extension(Path::new("a.FLAC")));
    assert!(is_decodable_extension(Path::new("a.ogg")));
    assert!(is_decodable_extension(Path::new("a.OGG")));
    // Canonical WAV must reach the hardened parser, never this path.
    assert!(!is_decodable_extension(Path::new("a.wav")));
    assert!(is_decodable_extension(Path::new("a.m4a")));
    assert!(is_decodable_extension(Path::new("a.MP4")));
    assert!(!is_decodable_extension(Path::new("a.aac")));
    assert!(!is_decodable_extension(Path::new("a")));
}

#[test]
fn flac_preserves_duration_and_content_through_canonical_normalization() {
    let original = std::fs::read(fixture("tone-44k-stereo.flac")).unwrap();
    assert_eq!(
        crate::jobs::remote::artifact_io::sha256_bytes(&original),
        "6bf1c246ef250a3aa53f7481d953673c67eaef6537f34f8abb8ca4723ba36f6a"
    );
    let (evidence, bytes) = decode("tone-44k-stereo.flac");
    let reader = hound::WavReader::new(std::io::Cursor::new(&bytes)).unwrap();
    assert_eq!(reader.spec().channels, 1);
    assert_eq!(reader.spec().sample_rate, CANONICAL_SAMPLE_RATE_HZ);
    assert_eq!(reader.spec().bits_per_sample, 16);
    assert_eq!(evidence.source_sample_rate_hz, 44_100);
    assert_eq!(evidence.source_channels, 2);
    assert_eq!(evidence.source_frame_count, 44_100);
    assert!(evidence.output_sample_count.abs_diff(16_000) <= 1);
    let decoded = samples(&bytes);
    let settled = &decoded[decoded.len() / 2..];
    let speech = magnitude(settled, 440.0);
    assert!(speech > 0.01, "440 Hz content was lost");
    assert!(magnitude(settled, 4_000.0) < speech / 100.0);
    assert_eq!(
        std::fs::read(fixture("tone-44k-stereo.flac")).unwrap(),
        original
    );
}

#[test]
fn malformed_shortened_and_checksum_mismatched_flac_leave_no_decoded_copy() {
    let whole = std::fs::read(fixture("tone-44k-stereo.flac")).unwrap();
    let mut bad_checksum = whole.clone();
    // STREAMINFO follows the four-byte signature and metadata header. Its
    // final sixteen bytes are the declared checksum of the original PCM.
    bad_checksum[26] ^= 0xff;
    for (label, bytes) in [
        ("bogus-flac", b"not a FLAC container".to_vec()),
        ("short-flac", whole[..whole.len() / 2].to_vec()),
        ("checksum-flac", bad_checksum),
    ] {
        let directory = scratch(label);
        let source = directory.join("recording.flac");
        std::fs::write(&source, &bytes).unwrap();
        let error = match decode_import_if_compressed(&source, label, &directory, || Ok(())) {
            Err(error) => error,
            Ok(_) => panic!("{label} must be refused"),
        };
        if label == "checksum-flac" {
            assert!(error.contains("integrity check"), "{error}");
        }
        assert_eq!(std::fs::read(&source).unwrap(), bytes);
        assert_eq!(std::fs::read_dir(&directory).unwrap().count(), 1, "{label}");
        std::fs::remove_dir_all(directory).unwrap();
    }
}

#[test]
fn cancelling_flac_decode_cleans_its_temporary_copy_and_preserves_source() {
    let directory = scratch("cancel-flac");
    let source = directory.join("recording.flac");
    let original = std::fs::read(fixture("tone-44k-stereo.flac")).unwrap();
    std::fs::write(&source, &original).unwrap();
    let mut checks = 0;
    let error = match decode_import_if_compressed(&source, "cancel-flac", &directory, || {
        checks += 1;
        if checks >= 3 {
            Err("cancelled".into())
        } else {
            Ok(())
        }
    }) {
        Err(error) => error,
        Ok(_) => panic!("cancelled decode must not publish a canonical copy"),
    };
    assert_eq!(error, "cancelled");
    assert_eq!(std::fs::read(&source).unwrap(), original);
    assert_eq!(std::fs::read_dir(&directory).unwrap().count(), 1);
    std::fs::remove_dir_all(directory).unwrap();
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

#[test]
fn a_damaged_packet_refuses_partial_audio_and_cleans_its_temporary_copy() {
    let directory = scratch("damaged-packet");
    let damaged = directory.join("damaged.mp3");
    let original = crate::jobs::test_media::write_damaged_mp3_fixture(&damaged);
    let error = match decode_import_if_compressed(&damaged, "damaged-job", &directory, || Ok(())) {
        Err(error) => error,
        Ok(_) => panic!("damaged packets must not produce an accepted partial recording"),
    };
    assert!(error.contains("damaged packet"), "{error}");
    assert_eq!(
        std::fs::read(&damaged).unwrap(),
        original,
        "source is preserved"
    );
    assert_eq!(
        std::fs::read_dir(&directory).unwrap().count(),
        1,
        "temporary decoded audio is removed"
    );
    std::fs::remove_dir_all(directory).unwrap();
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

/// A headerless shortened MP3 can lack an authoritative expected duration.
/// This fixture records what it actually decodes; it does not establish that
/// arbitrary truncation is detectable or that the recording is complete.
#[test]
fn a_shortened_stream_without_declared_duration_reports_only_decoded_audio() {
    let directory = scratch("truncated");
    // The original fixture carries a Xing header. Rebuild only its audio
    // packets so this test actually has no declared count, delay or padding.
    let stream = MediaSourceStream::new(
        Box::new(File::open(fixture("tone-44k-stereo.mp3")).unwrap()),
        Default::default(),
    );
    let mut format = symphonia::default::get_probe()
        .probe(&Hint::new(), stream, Default::default(), Default::default())
        .unwrap();
    let mut whole = Vec::new();
    let mut packet_ends = Vec::new();
    while let Ok(Some(packet)) = format.next_packet() {
        whole.extend_from_slice(&packet.data);
        packet_ends.push(whole.len());
    }
    let raw = directory.join("raw.mp3");
    std::fs::write(&raw, &whole).unwrap();
    let stream = MediaSourceStream::new(
        Box::new(ReadOnlySource::new(File::open(&raw).unwrap())),
        Default::default(),
    );
    let format = symphonia::default::get_probe()
        .probe(&Hint::new(), stream, Default::default(), Default::default())
        .unwrap();
    assert!(format
        .default_track(symphonia::core::formats::TrackType::Audio)
        .unwrap()
        .num_frames
        .is_none());
    let cut = directory.join("truncated.mp3");
    std::fs::write(&cut, &whole[..packet_ends[packet_ends.len() / 2]]).expect("write");

    let (evidence, bytes) = {
        let destination = directory.join("decoded.wav");
        let evidence = decode_to_canonical_wav(&cut, &destination, &mut || Ok(()))
            .expect("a truncated stream still decodes what it holds");
        let bytes = std::fs::metadata(&destination).expect("stat").len();
        (evidence, bytes)
    };
    // Half the bytes must yield materially less audio, not the full duration.
    let full = decode_to_canonical_wav(&raw, &directory.join("whole.wav"), &mut || Ok(())).unwrap();
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

#[test]
fn decoding_never_overwrites_or_removes_a_preexisting_temporary_path() {
    let directory = scratch("occupied-temp");
    let occupied = directory.join(format!(".occupied-decoded-{}.wav", std::process::id()));
    let retained = b"unrelated retained data";
    std::fs::write(&occupied, retained).unwrap();
    let decoded = decode_import_if_compressed(
        &fixture("tone-44k-gapless.mp3"),
        "occupied",
        &directory,
        || Ok(()),
    )
    .unwrap()
    .unwrap();
    let actual_path = decoded.path.clone();
    assert_ne!(actual_path, occupied);
    assert_eq!(std::fs::read(&occupied).unwrap(), retained);
    drop(decoded);
    assert!(!actual_path.exists());
    assert_eq!(std::fs::read(&occupied).unwrap(), retained);
    let bad_source = directory.join("bad.mp3");
    std::fs::write(&bad_source, b"bad recording").unwrap();
    assert!(decode_import_if_compressed(&bad_source, "occupied", &directory, || Ok(())).is_err());
    assert_eq!(std::fs::read(&occupied).unwrap(), retained);
    std::fs::remove_dir_all(directory).unwrap();
}

#[cfg(unix)]
#[test]
fn a_planted_temporary_link_cannot_redirect_decoded_audio() {
    let directory = scratch("linked-temp");
    let target = directory.join("retained.txt");
    std::fs::write(&target, b"retained data").unwrap();
    let link = directory.join(format!(".linked-decoded-{}.wav", std::process::id()));
    std::os::unix::fs::symlink(&target, &link).unwrap();
    let decoded = decode_import_if_compressed(
        &fixture("tone-44k-gapless.mp3"),
        "linked",
        &directory,
        || Ok(()),
    )
    .unwrap()
    .unwrap();
    assert_eq!(std::fs::read(&target).unwrap(), b"retained data");
    drop(decoded);
    assert!(std::fs::symlink_metadata(&link)
        .unwrap()
        .file_type()
        .is_symlink());
    std::fs::remove_dir_all(directory).unwrap();
}

#[test]
fn reservation_refuses_occupied_files_and_directories_without_cleanup() {
    let directory = scratch("reserve-collision");
    let occupied = directory.join("occupied.wav");
    std::fs::write(&occupied, b"retained").unwrap();
    assert!(DecodedFile::reserve(occupied.clone()).is_err());
    assert_eq!(std::fs::read(&occupied).unwrap(), b"retained");
    let child = directory.join("directory.wav");
    std::fs::create_dir(&child).unwrap();
    assert!(DecodedFile::reserve(child.clone()).is_err());
    assert!(child.is_dir());
    #[cfg(unix)]
    {
        let link = directory.join("link.wav");
        std::os::unix::fs::symlink(&occupied, &link).unwrap();
        assert!(DecodedFile::reserve(link.clone()).is_err());
        assert!(std::fs::symlink_metadata(link)
            .unwrap()
            .file_type()
            .is_symlink());
        assert_eq!(std::fs::read(occupied).unwrap(), b"retained");
    }
    std::fs::remove_dir_all(directory).unwrap();
}

#[cfg(unix)]
#[test]
fn retained_handle_survives_path_replacement_and_cleanup_retains_the_replacement() {
    let directory = scratch("retained-handle");
    let decoded = decode_import_if_compressed(
        &fixture("tone-44k-gapless.mp3"),
        "retained",
        &directory,
        || Ok(()),
    )
    .unwrap()
    .unwrap();
    let path = decoded.path.clone();
    let renamed = directory.join("moved.wav");
    std::fs::rename(&path, &renamed).unwrap();
    std::fs::write(&path, b"replacement data").unwrap();
    let mut source = decoded.open_source().unwrap();
    let mut header = [0_u8; 12];
    source.read_exact(&mut header).unwrap();
    assert_eq!(&header[..4], b"RIFF");
    assert_eq!(&header[8..], b"WAVE");
    drop(source);
    drop(decoded);
    assert_eq!(std::fs::read(path).unwrap(), b"replacement data");
    assert!(renamed.is_file());
    std::fs::remove_dir_all(directory).unwrap();
}

#[test]
fn cancelling_an_attempt_preserves_another_attempt_and_the_original() {
    let directory = scratch("cancel-owned");
    let original = std::fs::read(fixture("tone-44k-gapless.mp3")).unwrap();
    let decoded = decode_import_if_compressed(
        &fixture("tone-44k-gapless.mp3"),
        "same-job",
        &directory,
        || Ok(()),
    )
    .unwrap()
    .unwrap();
    let other_path = decoded.path.clone();
    let mut saw_new_file = false;
    let result = decode_import_if_compressed(
        &fixture("tone-44k-gapless.mp3"),
        "same-job",
        &directory,
        || {
            if std::fs::read_dir(&directory).unwrap().count() > 1 {
                saw_new_file = true;
                Err("cancelled".into())
            } else {
                Ok(())
            }
        },
    );
    assert!(result.is_err());
    assert!(saw_new_file);
    assert!(other_path.is_file());
    assert_eq!(std::fs::read_dir(&directory).unwrap().count(), 1);
    assert_eq!(
        std::fs::read(fixture("tone-44k-gapless.mp3")).unwrap(),
        original
    );
    drop(decoded);
    assert_eq!(std::fs::read_dir(&directory).unwrap().count(), 0);
    std::fs::remove_dir_all(directory).unwrap();
}

#[cfg(unix)]
#[test]
fn decoded_plaintext_is_private() {
    use std::os::unix::fs::PermissionsExt;
    let directory = scratch("private-mode");
    let decoded = decode_import_if_compressed(
        &fixture("tone-44k-gapless.mp3"),
        "private",
        &directory,
        || Ok(()),
    )
    .unwrap()
    .unwrap();
    assert_eq!(
        std::fs::metadata(&decoded.path)
            .unwrap()
            .permissions()
            .mode()
            & 0o777,
        0o600
    );
    drop(decoded);
    assert_eq!(std::fs::read_dir(&directory).unwrap().count(), 0);
    std::fs::remove_dir_all(directory).unwrap();
}

#[test]
fn invalid_job_identifiers_cannot_reserve_plaintext_outside_the_spool() {
    let directory = scratch("invalid-job");
    let result = decode_import_if_compressed(
        &fixture("tone-44k-gapless.mp3"),
        "../outside",
        &directory,
        || Ok(()),
    );
    assert!(result.is_err());
    assert_eq!(std::fs::read_dir(&directory).unwrap().count(), 0);
    std::fs::remove_dir_all(directory).unwrap();
}

#[cfg(unix)]
#[test]
fn fifo_source_is_refused_without_waiting_and_owned_plaintext_is_cleaned() {
    use std::os::unix::{
        ffi::OsStrExt,
        fs::{FileTypeExt, OpenOptionsExt},
    };
    let directory = scratch("fifo-source");
    let fifo = directory.join("source.mp3");
    let name = std::ffi::CString::new(fifo.as_os_str().as_bytes()).unwrap();
    assert_eq!(unsafe { libc::mkfifo(name.as_ptr(), 0o600) }, 0);
    let source = fifo.clone();
    let spool = directory.clone();
    let (send, receive) = std::sync::mpsc::channel();
    let reader = std::thread::spawn(move || {
        let failed = decode_import_if_compressed(&source, "fifo", &spool, || Ok(())).is_err();
        send.send(failed).unwrap();
    });
    let result = receive.recv_timeout(std::time::Duration::from_secs(1));
    let writer = result.is_err().then(|| {
        // Release a regressed blocking open so the test fails instead of hanging.
        std::fs::OpenOptions::new()
            .read(true)
            .write(true)
            .custom_flags(libc::O_NONBLOCK)
            .open(&fifo)
            .unwrap()
    });
    reader.join().unwrap();
    drop(writer);
    assert!(result.expect("source admission must not wait for a FIFO writer"));
    assert_eq!(std::fs::read_dir(&directory).unwrap().count(), 1);
    assert!(std::fs::symlink_metadata(&fifo)
        .unwrap()
        .file_type()
        .is_fifo());
    std::fs::remove_dir_all(directory).unwrap();
}

#[test]
fn low_rate_flac_retains_its_complete_source_duration() {
    let original = std::fs::read(fixture("silence-1hz.flac")).unwrap();
    assert_eq!(
        crate::jobs::remote::artifact_io::sha256_bytes(&original),
        "4052212b45474d127e3e5bdd4fea94e87a74393c212c1785403fa2bafd093116"
    );
    let (evidence, bytes) = decode("silence-1hz.flac");
    assert_eq!(evidence.source_sample_rate_hz, 1);
    assert_eq!(evidence.source_frame_count, 64);
    assert!(
        evidence.output_sample_count.abs_diff(64 * 16_000) <= 1,
        "64 seconds became {} samples",
        evidence.output_sample_count
    );
    assert!(samples(&bytes).iter().all(|sample| *sample == 0.0));
}

#[test]
fn cancellation_during_low_rate_expansion_is_checked_before_excessive_plaintext() {
    let directory = scratch("cancel-low-rate");
    let source = directory.join("source.flac");
    let original = std::fs::read(fixture("silence-1hz.flac")).unwrap();
    std::fs::write(&source, &original).unwrap();
    let (result, observed_size) = cancel_after_plaintext(&source, &directory, "low-rate");
    assert_eq!(result.unwrap_err(), "cancelled");
    assert!(observed_size >= 8_192);
    assert!(
        observed_size <= 128 * 1024,
        "cancellation was delayed until {observed_size} plaintext bytes were written"
    );
    assert_eq!(std::fs::read(&source).unwrap(), original);
    assert_eq!(std::fs::read_dir(&directory).unwrap().count(), 1);
    std::fs::remove_dir_all(directory).unwrap();
}

#[test]
fn excessive_declared_duration_fails_before_decoding_and_keeps_source() {
    let directory = scratch("excessive-declared-duration");
    let source = directory.join("source.flac");
    let mut original = std::fs::read(fixture("silence-1hz.flac")).unwrap();
    // STREAMINFO's packed rate/channels/depth/count word starts at byte 18.
    let packed = u64::from_be_bytes(original[18..26].try_into().unwrap());
    let packed = (packed & !((1_u64 << 36) - 1)) | 50_000;
    original[18..26].copy_from_slice(&packed.to_be_bytes());
    std::fs::write(&source, &original).unwrap();
    let error = match decode_import_if_compressed(&source, "too-long", &directory, || Ok(())) {
        Err(error) => error,
        Ok(_) => panic!("declared excessive duration must be refused"),
    };
    assert!(error.contains("four-hour"), "{error}");
    assert_eq!(std::fs::read(&source).unwrap(), original);
    assert_eq!(std::fs::read_dir(&directory).unwrap().count(), 1);
    std::fs::remove_dir_all(directory).unwrap();
}

#[test]
fn source_duration_bounds_do_not_overflow_or_admit_zero_rate() {
    assert!(validate_source_duration(1, 0).is_err());
    for rate in [1, 44_100, 655_350, u32::MAX] {
        let last = u64::from(rate) * 14_400;
        assert!(validate_source_duration(last, rate).is_ok());
        assert!(validate_source_duration(last + 1, rate).is_err());
        assert!(validate_source_duration(u64::MAX, rate).is_err());
    }
}

#[test]
fn chunked_resampling_bounds_allocation_and_retains_partition_independent_duration() {
    for rate in [1_u32, 2, 3, 8_000, 16_000, 44_100, 192_000, 655_350] {
        let frame_count = rate.min(10_000) as usize;
        let input: Vec<f32> = (0..frame_count)
            .map(|index| (index % 16) as f32 / 16.0)
            .collect();
        let mut whole = LinearResampler::new(rate, CANONICAL_SAMPLE_RATE_HZ);
        let mut expected = whole.push(&input);
        expected.extend(whole.finish());
        let mut chunked = LinearResampler::new(rate, CANONICAL_SAMPLE_RATE_HZ);
        let mut actual = Vec::new();
        for chunk in input.chunks((rate as usize).min(MAX_INPUT_CHUNK_FRAMES)) {
            let output = chunked.push(chunk);
            assert!(
                output.capacity() <= MAX_RESAMPLED_CHUNK_SAMPLES,
                "rate {rate}"
            );
            actual.extend(output);
        }
        let tail = chunked.finish();
        assert!(
            tail.capacity() <= MAX_RESAMPLED_CHUNK_SAMPLES,
            "rate {rate}"
        );
        actual.extend(tail);
        assert!(actual.len().abs_diff(expected.len()) <= 1, "rate {rate}");
        assert!(
            actual
                .iter()
                .zip(&expected)
                .all(|(a, b)| (a - b).abs() < 0.000_01),
            "rate {rate}"
        );
        let expected_count = (frame_count as u64 * 16_000).div_ceil(u64::from(rate));
        assert!(
            (actual.len() as u64).abs_diff(expected_count) <= 1,
            "rate {rate}"
        );
        assert!(chunked.finish().is_empty());
    }
}

#[test]
fn zero_rate_flac_is_refused_without_plaintext_or_source_changes() {
    let directory = scratch("zero-rate");
    let source = directory.join("source.flac");
    let mut original = std::fs::read(fixture("silence-1hz.flac")).unwrap();
    let packed = u64::from_be_bytes(original[18..26].try_into().unwrap()) & ((1_u64 << 44) - 1);
    original[18..26].copy_from_slice(&packed.to_be_bytes());
    std::fs::write(&source, &original).unwrap();
    assert!(decode_import_if_compressed(&source, "zero-rate", &directory, || Ok(())).is_err());
    assert_eq!(std::fs::read(&source).unwrap(), original);
    assert_eq!(std::fs::read_dir(&directory).unwrap().count(), 1);
    std::fs::remove_dir_all(directory).unwrap();
}

#[cfg(unix)]
#[test]
fn a_source_substitution_after_admission_never_selects_different_audio() {
    let directory = scratch("source-substitution");
    let source = directory.join("source.flac");
    let admitted = directory.join("admitted.flac");
    let original = std::fs::read(fixture("silence-1hz.flac")).unwrap();
    let replacement = std::fs::read(fixture("tone-44k-stereo.flac")).unwrap();
    std::fs::write(&source, &original).unwrap();
    let mut replaced = false;
    let result = decode_import_if_compressed(&source, "substitution", &directory, || {
        if !replaced && std::fs::read_dir(&directory).unwrap().count() > 1 {
            std::fs::rename(&source, &admitted).unwrap();
            std::fs::write(&source, &replacement).unwrap();
            replaced = true;
        }
        Ok(())
    });
    assert!(replaced);
    if let Ok(Some(decoded)) = result {
        assert_eq!(
            decoded.evidence.source_sample_rate_hz, 1,
            "a replacement pathname must not select different audio"
        );
    }
    assert_eq!(std::fs::read(&source).unwrap(), replacement);
    assert_eq!(std::fs::read(&admitted).unwrap(), original);
    assert_eq!(std::fs::read_dir(&directory).unwrap().count(), 2);
    std::fs::remove_dir_all(directory).unwrap();
}

#[cfg(unix)]
#[test]
fn a_same_length_metadata_change_during_decode_refuses_the_result() {
    let directory = scratch("source-mutation");
    let source = directory.join("source.flac");
    let original = std::fs::read(fixture("silence-1hz.flac")).unwrap();
    std::fs::write(&source, &original).unwrap();
    let mut changed = false;
    let result = decode_import_if_compressed(&source, "mutation", &directory, || {
        let visible_output = std::fs::read_dir(&directory)
            .unwrap()
            .flatten()
            .any(|entry| entry.path() != source && entry.metadata().unwrap().len() > 8_192);
        if !changed && visible_output {
            // Change a byte in container padding; PCM and source length remain
            // valid, so only source revision validation can reject the change.
            let mut modified = original.clone();
            modified[100] ^= 0x01;
            std::fs::write(&source, &modified).unwrap();
            changed = true;
        }
        Ok(())
    });
    assert!(changed);
    assert!(
        result.is_err(),
        "changed source must not yield an accepted result"
    );
    assert_eq!(
        std::fs::metadata(&source).unwrap().len(),
        original.len() as u64
    );
    assert_eq!(std::fs::read_dir(&directory).unwrap().count(), 1);
    std::fs::remove_dir_all(directory).unwrap();
}

#[test]
fn compressed_source_path_is_a_hint_and_never_reopened() {
    let directory = scratch("admitted-hint");
    let source = fixture("silence-1hz.flac");
    let fingerprint = crate::media_protocol::inspect_media_source(&source).unwrap();
    let mut file =
        crate::media_protocol::open_unchanged_media_source(&source, &fingerprint).unwrap();
    file.seek(SeekFrom::End(0)).unwrap();
    let absent_hint = directory.join("no-longer-present.flac");
    assert!(!absent_hint.exists());
    let decoded = super::decode_import_if_compressed(
        &absent_hint,
        &file,
        &fingerprint,
        "admitted-hint",
        &directory,
        || Ok(()),
    )
    .unwrap()
    .unwrap();
    assert_eq!(decoded.evidence.source_sample_rate_hz, 1);
    assert_eq!(decoded.evidence.source_frame_count, 64);
    assert!(decoded.evidence.output_sample_count.abs_diff(64 * 16_000) <= 1);
    drop(decoded);
    assert_eq!(std::fs::read_dir(&directory).unwrap().count(), 0);
    std::fs::remove_dir_all(directory).unwrap();
}

#[test]
fn a_mismatched_source_handle_and_fingerprint_fail_before_staging() {
    let directory = scratch("admitted-mismatch");
    let source = directory.join("source.flac");
    let other = directory.join("other.flac");
    let original = std::fs::read(fixture("silence-1hz.flac")).unwrap();
    std::fs::write(&source, &original).unwrap();
    std::fs::write(&other, &original).unwrap();
    let fingerprint = crate::media_protocol::inspect_media_source(&source).unwrap();
    let file = crate::bounded_file::open_regular_file(&other, u64::MAX)
        .unwrap()
        .0;
    let spool = directory.join("spool");
    assert!(super::decode_import_if_compressed(
        &source,
        &file,
        &fingerprint,
        "mismatch",
        &spool,
        || Ok(()),
    )
    .is_err());
    assert!(!spool.exists());
    assert_eq!(std::fs::read(source).unwrap(), original);
    assert_eq!(std::fs::read(other).unwrap(), original);
    drop(file);
    std::fs::remove_dir_all(directory).unwrap();
}

#[test]
fn vorbis_container_duration_and_content_are_not_inferred_from_bitrate() {
    let (evidence, bytes) = decode("tone-44k-stereo.ogg");
    assert_eq!(evidence.source_sample_rate_hz, 44_100);
    assert_eq!(evidence.source_channels, 2);
    assert_eq!(
        evidence.source_frame_count, 44_100,
        "one second of declared content"
    );
    assert!(evidence.output_sample_count.abs_diff(16_000) <= 1);
    let decoded = samples(&bytes);
    let settled = &decoded[decoded.len() / 2..];
    let speech = magnitude(settled, 440.0);
    assert!(speech > 0.01);
    assert!(magnitude(settled, 4_000.0) < speech / 100.0);
}

fn fixture_ogg_pages(bytes: &[u8]) -> Vec<std::ops::Range<usize>> {
    let mut pages = Vec::new();
    let mut start = 0;
    while start < bytes.len() {
        assert_eq!(&bytes[start..start + 4], b"OggS");
        let segments = bytes[start + 26] as usize;
        let header_end = start + 27 + segments;
        let payload_length: usize = bytes[start + 27..header_end]
            .iter()
            .map(|value| *value as usize)
            .sum();
        let end = header_end + payload_length;
        assert!(end <= bytes.len());
        pages.push(start..end);
        start = end;
    }
    pages
}

#[test]
fn multipage_vorbis_keeps_declared_content_duration_and_original_bytes() {
    let original = std::fs::read(fixture("tone-44k-pages.ogg")).unwrap();
    assert_eq!(
        crate::jobs::remote::artifact_io::sha256_bytes(&original),
        "2315a4224a357f3c3bf7b7023b55200bcf8edf99d90ff17007ea5989afa88538"
    );
    assert!(fixture_ogg_pages(&original).len() > 3);
    let (evidence, bytes) = decode("tone-44k-pages.ogg");
    assert_eq!(evidence.source_frame_count, 44_100);
    assert!(evidence.output_sample_count.abs_diff(16_000) <= 1);
    assert_eq!(samples(&bytes).len() as u64, evidence.output_sample_count);
    assert_eq!(
        std::fs::read(fixture("tone-44k-pages.ogg")).unwrap(),
        original
    );
}

#[test]
fn damaged_middle_page_and_missing_ending_cannot_become_partial_vorbis_results() {
    let whole = std::fs::read(fixture("tone-44k-pages.ogg")).unwrap();
    let pages = fixture_ogg_pages(&whole);
    let mut damaged = whole.clone();
    // Leave valid audio before/after a page whose CRC no longer matches.
    damaged[pages[3].end - 1] ^= 0x80;
    let no_ending = whole[..pages.last().unwrap().start].to_vec();
    for (label, bytes) in [
        ("damaged-page", damaged),
        ("missing-ending", no_ending),
        ("short-header", whole[..100].to_vec()),
    ] {
        let directory = scratch(label);
        let source = directory.join("recording.ogg");
        std::fs::write(&source, &bytes).unwrap();
        assert!(
            decode_import_if_compressed(&source, label, &directory, || Ok(())).is_err(),
            "{label}"
        );
        assert_eq!(std::fs::read(&source).unwrap(), bytes);
        assert_eq!(std::fs::read_dir(&directory).unwrap().count(), 1);
        std::fs::remove_dir_all(directory).unwrap();
    }
}

#[test]
fn ogg_opus_is_refused_without_claiming_vorbis_support_for_every_codec() {
    let directory = scratch("unsupported-opus");
    let source = directory.join("recording.ogg");
    let original = std::fs::read(fixture("tone-opus.ogg")).unwrap();
    std::fs::write(&source, &original).unwrap();
    let error = match decode_import_if_compressed(&source, "opus", &directory, || Ok(())) {
        Err(error) => error,
        Ok(_) => panic!("Opus is not an enabled decoder"),
    };
    assert!(
        error.contains("unsupported codec") || error.contains("no decodable track"),
        "{error}"
    );
    assert_eq!(std::fs::read(&source).unwrap(), original);
    assert_eq!(std::fs::read_dir(&directory).unwrap().count(), 1);
    std::fs::remove_dir_all(directory).unwrap();
}

#[test]
fn cancelling_vorbis_decode_keeps_source_and_removes_only_owned_plaintext() {
    let directory = scratch("cancel-vorbis");
    let source = directory.join("recording.ogg");
    let original = std::fs::read(fixture("tone-44k-pages.ogg")).unwrap();
    std::fs::write(&source, &original).unwrap();
    let (result, observed_size) = cancel_after_plaintext(&source, &directory, "cancel-vorbis");
    assert!(observed_size >= 8_192);
    assert_eq!(result.unwrap_err(), "cancelled");
    assert_eq!(std::fs::read(&source).unwrap(), original);
    assert_eq!(std::fs::read_dir(&directory).unwrap().count(), 1);
    std::fs::remove_dir_all(directory).unwrap();
}

#[test]
fn chained_or_multiple_vorbis_tracks_are_refused_without_silently_omitting_audio() {
    let single = std::fs::read(fixture("tone-44k-stereo.ogg")).unwrap();
    let mut chained = single.clone();
    chained.extend_from_slice(&single);
    let multi = std::fs::read(fixture("tone-two-tracks.ogg")).unwrap();
    for (label, bytes) in [("chained-ogg", chained), ("multi-ogg", multi)] {
        let directory = scratch(label);
        let source = directory.join("recording.ogg");
        std::fs::write(&source, &bytes).unwrap();
        assert!(
            decode_import_if_compressed(&source, label, &directory, || Ok(())).is_err(),
            "{label}"
        );
        assert_eq!(std::fs::read(&source).unwrap(), bytes);
        assert_eq!(std::fs::read_dir(&directory).unwrap().count(), 1);
        std::fs::remove_dir_all(directory).unwrap();
    }
}

#[test]
fn aac_m4a_and_mp4_preserve_declared_content_and_duration() {
    for name in ["tone-44k-stereo.m4a", "tone-video.mp4"] {
        let original = std::fs::read(fixture(name)).unwrap();
        let (evidence, bytes) = decode(name);
        assert_eq!(evidence.source_sample_rate_hz, 44_100);
        assert_eq!(evidence.source_channels, 2);
        assert_eq!(evidence.source_frame_count, 44_100);
        assert!(evidence.output_sample_count.abs_diff(16_000) <= 1);
        let reader = hound::WavReader::new(std::io::Cursor::new(&bytes)).unwrap();
        assert_eq!(reader.spec().channels, 1);
        assert_eq!(reader.spec().sample_rate, 16_000);
        assert_eq!(reader.spec().bits_per_sample, 16);
        let decoded = samples(&bytes);
        let settled = &decoded[decoded.len() / 2..];
        let speech = magnitude(settled, 440.0);
        assert!(speech > 0.01, "AAC tone was lost");
        assert!(magnitude(settled, 4_000.0) < speech / 50.0);
        assert_eq!(std::fs::read(fixture(name)).unwrap(), original);
    }
}

#[test]
fn aac_tail_metadata_and_movie_rounding_preserve_available_audio() {
    let (tail, _) = decode("tone-tail-moov.m4a");
    assert_eq!(tail.source_frame_count, 44_100);
    let (unedited, _) = decode("tone-no-edit.m4a");
    assert_eq!(unedited.source_frame_count, 45_124);
    assert!(
        unedited
            .output_sample_count
            .abs_diff((45_124u64 * 16_000).div_ceil(44_100))
            <= 1
    );
    let (rounded, bytes) = decode("tone-997ms.m4a");
    assert_eq!(rounded.source_frame_count, 43_968);
    let expected = (43_968u64 * 16_000).div_ceil(44_100);
    assert!(rounded.output_sample_count.abs_diff(expected) <= 1);
    assert!(magnitude(&samples(&bytes)[8_000..], 440.0) > 0.01);
}
#[test]
fn aac_unsupported_or_damaged_inputs_preserve_sources_and_other_files() {
    let valid = std::fs::read(fixture("tone-44k-stereo.m4a")).unwrap();
    let mut variants: Vec<(&str, Vec<u8>)> = vec![
        ("alac", std::fs::read(fixture("tone-alac.m4a")).unwrap()),
        (
            "multitrack",
            std::fs::read(fixture("tone-two-tracks.m4a")).unwrap(),
        ),
        (
            "fragmented",
            std::fs::read(fixture("tone-fragmented.mp4")).unwrap(),
        ),
        ("truncated", valid[..valid.len() - 1024].to_vec()),
        (
            "renamed-mp3",
            std::fs::read(fixture("tone-44k-stereo.mp3")).unwrap(),
        ),
    ];
    let edit = valid.windows(4).position(|value| value == b"elst").unwrap();
    for (label, offset, bytes) in [
        ("empty-edit", edit + 16, 0xffff_ffffu32.to_be_bytes()),
        ("multiple-edits", edit + 8, 2u32.to_be_bytes()),
        ("retimed-edit", edit + 20, 0x0002_0000u32.to_be_bytes()),
        ("huge-edit", edit + 12, u32::MAX.to_be_bytes()),
    ] {
        let mut changed = valid.clone();
        changed[offset..offset + 4].copy_from_slice(&bytes);
        variants.push((label, changed));
    }
    let tkhd = valid.windows(4).position(|value| value == b"tkhd").unwrap();
    let mut changed = valid.clone();
    changed[tkhd + 24..tkhd + 28].copy_from_slice(&1100u32.to_be_bytes());
    variants.push(("conflicting-track-duration", changed));
    let stts = valid.windows(4).position(|value| value == b"stts").unwrap();
    let mut changed = valid.clone();
    changed[stts + 16..stts + 20].copy_from_slice(&1025u32.to_be_bytes());
    variants.push(("wrong-packet-duration", changed));
    for (label, bytes) in variants {
        let root = scratch(&format!("aac-invalid-{label}"));
        let source = root.join("input.m4a");
        std::fs::write(&source, &bytes).unwrap();
        std::fs::write(root.join("unrelated.part"), b"retain").unwrap();
        let result = decode_import_if_compressed(&source, "aac-invalid", &root, || Ok(()));
        assert!(result.is_err(), "{label} unexpectedly decoded");
        assert_eq!(std::fs::read(&source).unwrap(), bytes);
        assert_eq!(
            std::fs::read(root.join("unrelated.part")).unwrap(),
            b"retain"
        );
        assert_eq!(
            std::fs::read_dir(&root).unwrap().count(),
            2,
            "{label} left decoded plaintext"
        );
        std::fs::remove_dir_all(root).unwrap();
    }
}
#[test]
fn aac_cancellation_retains_original_and_reclaims_only_its_temp_file() {
    let root = scratch("aac-cancel");
    let source = root.join("recording.m4a");
    let original = std::fs::read(fixture("tone-44k-stereo.m4a")).unwrap();
    std::fs::write(&source, &original).unwrap();
    std::fs::write(root.join("unrelated.part"), b"retain").unwrap();
    let mut checks = 0;
    let result = decode_import_if_compressed(&source, "aac-cancel", &root, || {
        checks += 1;
        if checks >= 12 {
            Err("cancelled during AAC decode".into())
        } else {
            Ok(())
        }
    });
    assert!(result.is_err());
    assert!(checks >= 12);
    assert_eq!(std::fs::read(&source).unwrap(), original);
    assert_eq!(std::fs::read_dir(&root).unwrap().count(), 2);
    std::fs::remove_dir_all(root).unwrap();
}
