use std::{
    fs::File,
    io::{Read, Seek, SeekFrom},
    path::Path,
};

use sha2::{Digest, Sha256};

use crate::stt::error::SttError;

use super::io_error_to_stt;

const HASH_BUFFER_BYTES: usize = 64 * 1024;

pub fn sha256_file(path: &Path) -> std::io::Result<String> {
    let (file, metadata) = crate::bounded_file::open_regular_file(path, u64::MAX)?;
    hash_reader(file, metadata.len(), || false)
}

/// Checks the approved size and hash of one regular artifact. Installation
/// and explicit verification share the same bounded, cancellable read path.
pub fn verify_artifact(
    path: &Path,
    expected_bytes: u64,
    expected_sha256: &str,
    is_cancelled: impl Fn() -> bool,
) -> Result<(), SttError> {
    if is_cancelled() {
        return Err(SttError::ModelInstallCancelled);
    }
    let (file, _) =
        crate::bounded_file::open_regular_file(path, expected_bytes).map_err(verification_error)?;
    verify_open_artifact(&file, expected_bytes, expected_sha256, is_cancelled)
}

/// Installation verifies the retained staging object, without reopening its
/// pathname or relaxing the Windows sharing boundary on admitted artifacts.
pub(super) fn verify_open_artifact(
    file: &File,
    expected_bytes: u64,
    expected_sha256: &str,
    is_cancelled: impl Fn() -> bool,
) -> Result<(), SttError> {
    if is_cancelled() {
        return Err(SttError::ModelInstallCancelled);
    }
    let metadata = file.metadata().map_err(verification_error)?;
    if !metadata.is_file() || metadata.len() != expected_bytes {
        return Err(SttError::ModelCorrupt);
    }
    let mut file = file.try_clone().map_err(verification_error)?;
    file.seek(SeekFrom::Start(0)).map_err(verification_error)?;
    let actual = hash_reader(file, expected_bytes, &is_cancelled).map_err(|error| {
        if error.kind() == std::io::ErrorKind::Interrupted && is_cancelled() {
            SttError::ModelInstallCancelled
        } else {
            verification_error(error)
        }
    })?;
    actual
        .eq_ignore_ascii_case(expected_sha256)
        .then_some(())
        .ok_or(SttError::ModelCorrupt)
}

fn verification_error(error: std::io::Error) -> SttError {
    if error.kind() == std::io::ErrorKind::InvalidData {
        SttError::ModelCorrupt
    } else {
        io_error_to_stt(error)
    }
}

fn hash_reader(
    reader: impl Read,
    expected_bytes: u64,
    is_cancelled: impl Fn() -> bool,
) -> std::io::Result<String> {
    use std::io::{Error, ErrorKind};
    let limit = expected_bytes.checked_add(1).ok_or_else(|| {
        Error::new(
            ErrorKind::InvalidData,
            "artifact size exceeds the read bound",
        )
    })?;
    let mut reader = reader.take(limit);
    let mut hasher = Sha256::new();
    let mut buffer = [0u8; HASH_BUFFER_BYTES];
    let mut hashed_bytes = 0_u64;
    loop {
        if is_cancelled() {
            return Err(Error::new(
                ErrorKind::Interrupted,
                "artifact verification cancelled",
            ));
        }
        let read = reader.read(&mut buffer)?;
        if read == 0 {
            break;
        }
        hashed_bytes += read as u64;
        if hashed_bytes > expected_bytes {
            return Err(Error::new(
                ErrorKind::InvalidData,
                "artifact changed while being verified",
            ));
        }
        hasher.update(&buffer[..read]);
    }
    if hashed_bytes != expected_bytes {
        return Err(Error::new(
            ErrorKind::InvalidData,
            "artifact changed while being verified",
        ));
    }
    Ok(hex_digest(hasher.finalize()))
}

fn hex_digest(bytes: impl AsRef<[u8]>) -> String {
    let bytes = bytes.as_ref();
    let mut hex = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        use std::fmt::Write as _;
        write!(hex, "{byte:02x}").expect("writing to a String cannot fail");
    }
    hex
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn verification_stops_when_the_stream_is_shorter_or_grows_past_its_bound() {
        let short = std::io::Cursor::new(b"abc");
        assert_eq!(
            hash_reader(short, 4, || false).unwrap_err().kind(),
            std::io::ErrorKind::InvalidData
        );
        // An unending source must be refused after the bounded extra byte.
        assert_eq!(
            hash_reader(std::io::repeat(1), 3, || false)
                .unwrap_err()
                .kind(),
            std::io::ErrorKind::InvalidData
        );
    }

    #[test]
    fn cancellation_after_reading_a_buffer_stops_verification() {
        struct CancellingReader {
            input: std::io::Cursor<Vec<u8>>,
            operation: super::super::DownloadOperation,
        }
        impl Read for CancellingReader {
            fn read(&mut self, buffer: &mut [u8]) -> std::io::Result<usize> {
                let read = self.input.read(buffer)?;
                if read > 0 {
                    self.operation.cancel();
                }
                Ok(read)
            }
        }
        let operation = super::super::DownloadOperation::new(1);
        let source = CancellingReader {
            input: std::io::Cursor::new(vec![1; HASH_BUFFER_BYTES * 2]),
            operation: operation.clone(),
        };
        let result = hash_reader(source, (HASH_BUFFER_BYTES * 2) as u64, || {
            operation.is_cancelled()
        });
        assert_eq!(result.unwrap_err().kind(), std::io::ErrorKind::Interrupted);
    }

    #[cfg(unix)]
    #[test]
    fn artifact_hashing_refuses_a_link_to_approved_bytes() {
        let dir = std::env::temp_dir().join(format!(
            "yap-artifact-hash-link-{}-{:?}",
            std::process::id(),
            std::thread::current().id()
        ));
        std::fs::create_dir_all(&dir).unwrap();
        let original = dir.join("original.onnx");
        let link = dir.join("model.onnx");
        std::fs::write(&original, b"abc").unwrap();
        std::os::unix::fs::symlink(&original, &link).unwrap();
        assert!(sha256_file(&link).is_err());
        assert!(verify_artifact(
            &link,
            3,
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
            || false
        )
        .is_err());
        assert_eq!(std::fs::read(&original).unwrap(), b"abc");
        std::fs::remove_dir_all(dir).unwrap();
    }
}
