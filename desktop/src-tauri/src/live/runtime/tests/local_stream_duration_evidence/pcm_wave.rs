use sha2::{Digest, Sha256};
use std::{
    fs::{File, OpenOptions},
    io::{Read, Seek, SeekFrom},
    path::Path,
};

use super::{manifest::DurationTrackAudio, SAMPLE_RATE_HZ};

pub(super) struct Pcm16WaveReader {
    file: File,
    remaining_data_bytes: u64,
    decoded_digest: Sha256,
    expected_decoded_sha256: String,
}

impl Pcm16WaveReader {
    pub(super) fn open(path: &Path, expected: &DurationTrackAudio) -> Self {
        let path_metadata = std::fs::symlink_metadata(path)
            .expect("duration track audio metadata must be readable");
        assert!(path_metadata.is_file());
        assert!(!crate::stt::model::metadata_is_link_or_reparse(
            &path_metadata
        ));
        assert_eq!(path_metadata.len(), expected.byte_length);
        let maximum_bytes = expected
            .duration_samples
            .checked_mul(u64::from(expected.sample_width_bytes))
            .and_then(|bytes| bytes.checked_add(1_048_576))
            .expect("duration track byte bound must not overflow");
        assert!(expected.byte_length <= maximum_bytes);

        let mut file = open_no_follow_read(path).expect("duration track audio must open safely");
        let opened = file
            .metadata()
            .expect("opened duration track metadata must be readable");
        assert!(opened.is_file());
        assert!(!crate::stt::model::metadata_is_link_or_reparse(&opened));
        assert_eq!(opened.len(), path_metadata.len());
        assert_eq!(sha256_reader(&mut file), expected.sha256);

        let (data_start, data_bytes) = parse_pcm16_wave(&mut file, opened.len());
        assert_eq!(data_bytes, expected.duration_samples * 2);
        file.seek(SeekFrom::Start(data_start))
            .expect("duration track data must be seekable");
        Self {
            file,
            remaining_data_bytes: data_bytes,
            decoded_digest: Sha256::new(),
            expected_decoded_sha256: expected.decoded_pcm_sha256.clone(),
        }
    }

    pub(super) fn read_samples(
        &mut self,
        maximum_samples: usize,
    ) -> std::io::Result<Option<Vec<f32>>> {
        if self.remaining_data_bytes == 0 {
            return Ok(None);
        }
        let requested_bytes = (maximum_samples as u64 * 2).min(self.remaining_data_bytes) as usize;
        let mut pcm = vec![0_u8; requested_bytes];
        self.file.read_exact(&mut pcm)?;
        self.remaining_data_bytes -= requested_bytes as u64;
        self.decoded_digest.update(&pcm);
        let samples = pcm
            .chunks_exact(2)
            .map(|bytes| i16::from_le_bytes([bytes[0], bytes[1]]) as f32 / 32_768.0)
            .collect();
        Ok(Some(samples))
    }

    pub(super) fn finish(self) {
        assert_eq!(self.remaining_data_bytes, 0);
        assert_eq!(
            hex_digest(self.decoded_digest.finalize()),
            self.expected_decoded_sha256
        );
    }
}

fn parse_pcm16_wave(file: &mut File, file_bytes: u64) -> (u64, u64) {
    file.seek(SeekFrom::Start(0)).unwrap();
    let mut riff = [0_u8; 12];
    file.read_exact(&mut riff).unwrap();
    assert_eq!(&riff[0..4], b"RIFF");
    assert_eq!(&riff[8..12], b"WAVE");
    assert_eq!(
        u64::from(u32::from_le_bytes(riff[4..8].try_into().unwrap())) + 8,
        file_bytes
    );

    let mut format_seen = false;
    let mut data = None;
    while file.stream_position().unwrap() < file_bytes {
        let mut chunk_header = [0_u8; 8];
        file.read_exact(&mut chunk_header).unwrap();
        let chunk_size = u64::from(u32::from_le_bytes(chunk_header[4..8].try_into().unwrap()));
        let chunk_start = file.stream_position().unwrap();
        let padded_end = chunk_start
            .checked_add(chunk_size)
            .and_then(|end| end.checked_add(chunk_size % 2))
            .expect("WAV chunk extent must not overflow");
        assert!(padded_end <= file_bytes);
        if &chunk_header[0..4] == b"fmt " {
            assert!(!format_seen && chunk_size >= 16);
            let mut format = [0_u8; 16];
            file.read_exact(&mut format).unwrap();
            assert_eq!(u16::from_le_bytes(format[0..2].try_into().unwrap()), 1);
            assert_eq!(u16::from_le_bytes(format[2..4].try_into().unwrap()), 1);
            assert_eq!(
                u32::from_le_bytes(format[4..8].try_into().unwrap()),
                SAMPLE_RATE_HZ
            );
            assert_eq!(
                u32::from_le_bytes(format[8..12].try_into().unwrap()),
                32_000
            );
            assert_eq!(u16::from_le_bytes(format[12..14].try_into().unwrap()), 2);
            assert_eq!(u16::from_le_bytes(format[14..16].try_into().unwrap()), 16);
            format_seen = true;
        } else if &chunk_header[0..4] == b"data" {
            assert!(data.is_none() && chunk_size > 0 && chunk_size % 2 == 0);
            data = Some((chunk_start, chunk_size));
        }
        file.seek(SeekFrom::Start(padded_end)).unwrap();
    }
    assert!(format_seen);
    data.expect("WAV must contain one PCM data chunk")
}

fn open_no_follow_read(path: &Path) -> std::io::Result<File> {
    open_no_follow_read_platform(path)
}

#[cfg(windows)]
fn open_no_follow_read_platform(path: &Path) -> std::io::Result<File> {
    use std::os::windows::fs::OpenOptionsExt;

    const FILE_FLAG_OPEN_REPARSE_POINT: u32 = 0x0020_0000;
    const FILE_SHARE_READ: u32 = 0x0000_0001;
    OpenOptions::new()
        .read(true)
        .share_mode(FILE_SHARE_READ)
        .custom_flags(FILE_FLAG_OPEN_REPARSE_POINT)
        .open(path)
}

#[cfg(unix)]
fn open_no_follow_read_platform(path: &Path) -> std::io::Result<File> {
    use std::os::unix::fs::OpenOptionsExt;

    OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW)
        .open(path)
}

#[cfg(not(any(unix, windows)))]
fn open_no_follow_read_platform(_path: &Path) -> std::io::Result<File> {
    Err(std::io::Error::new(
        std::io::ErrorKind::Unsupported,
        "no-follow reads are unsupported on this platform",
    ))
}

fn sha256_reader(file: &mut File) -> String {
    file.seek(SeekFrom::Start(0)).unwrap();
    let mut digest = Sha256::new();
    let mut buffer = [0_u8; 64 * 1_024];
    loop {
        let read = file.read(&mut buffer).unwrap();
        if read == 0 {
            break;
        }
        digest.update(&buffer[..read]);
    }
    hex_digest(digest.finalize())
}

fn hex_digest(bytes: impl AsRef<[u8]>) -> String {
    bytes
        .as_ref()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicU64, Ordering};

    static NEXT_CASE: AtomicU64 = AtomicU64::new(0);

    #[test]
    fn streaming_reader_preserves_exact_pcm_without_loading_the_whole_wave() {
        let id = NEXT_CASE.fetch_add(1, Ordering::Relaxed);
        let directory = std::env::temp_dir().join(format!(
            "yap-local-duration-wave-{}-{id}",
            std::process::id()
        ));
        std::fs::create_dir(&directory).unwrap();
        let path = directory.join("audio.wav");
        let pcm = [-32_768_i16, 0, 16_384]
            .into_iter()
            .flat_map(i16::to_le_bytes)
            .collect::<Vec<_>>();
        let mut wave = Vec::new();
        wave.extend_from_slice(b"RIFF");
        wave.extend_from_slice(&(36_u32 + pcm.len() as u32).to_le_bytes());
        wave.extend_from_slice(b"WAVEfmt ");
        wave.extend_from_slice(&16_u32.to_le_bytes());
        wave.extend_from_slice(&1_u16.to_le_bytes());
        wave.extend_from_slice(&1_u16.to_le_bytes());
        wave.extend_from_slice(&SAMPLE_RATE_HZ.to_le_bytes());
        wave.extend_from_slice(&32_000_u32.to_le_bytes());
        wave.extend_from_slice(&2_u16.to_le_bytes());
        wave.extend_from_slice(&16_u16.to_le_bytes());
        wave.extend_from_slice(b"data");
        wave.extend_from_slice(&(pcm.len() as u32).to_le_bytes());
        wave.extend_from_slice(&pcm);
        std::fs::write(&path, &wave).unwrap();
        let expected = DurationTrackAudio {
            sha256: hex_digest(Sha256::digest(&wave)),
            decoded_pcm_sha256: hex_digest(Sha256::digest(&pcm)),
            byte_length: wave.len() as u64,
            duration_samples: 3,
            sample_rate_hz: SAMPLE_RATE_HZ,
            channels: 1,
            sample_width_bytes: 2,
        };

        let mut reader = Pcm16WaveReader::open(&path, &expected);
        assert_eq!(reader.read_samples(2).unwrap().unwrap(), vec![-1.0, 0.0]);
        assert_eq!(reader.read_samples(2).unwrap().unwrap(), vec![0.5]);
        assert!(reader.read_samples(2).unwrap().is_none());
        reader.finish();

        std::fs::remove_file(path).unwrap();
        std::fs::remove_dir(directory).unwrap();
    }
}
