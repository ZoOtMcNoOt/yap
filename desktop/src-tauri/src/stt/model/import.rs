use std::{
    io::{Read, Write},
    path::Path,
};

use crate::stt::error::SttError;

use super::{
    io_error_to_stt,
    path_safety::create_model_directory,
    temp::{cleanup_stale_download_temps, OperationTemp},
    DownloadOperation, DownloadRequest,
};

const COPY_BUFFER_BYTES: usize = 64 * 1024;

/// Copies a user-selected model artifact through the same bounded, verified,
/// same-directory publication boundary used by network installation.
pub fn import_verified_file(
    source: &Path,
    request: &DownloadRequest,
    operation: &DownloadOperation,
) -> Result<(), SttError> {
    import_verified_file_after_admission(source, request, operation, || {})
}

fn import_verified_file_after_admission(
    source: &Path,
    request: &DownloadRequest,
    operation: &DownloadOperation,
    after_admission: impl FnOnce(),
) -> Result<(), SttError> {
    if operation.is_cancelled() {
        return Err(SttError::ModelInstallCancelled);
    }
    let (mut source, source_metadata) =
        crate::bounded_file::open_regular_file(source, request.expected_bytes).map_err(
            |error| {
                if error.kind() == std::io::ErrorKind::InvalidData {
                    SttError::ModelCorrupt
                } else {
                    io_error_to_stt(error)
                }
            },
        )?;
    if source_metadata.len() != request.expected_bytes {
        return Err(SttError::ModelCorrupt);
    }
    after_admission();
    if operation.is_cancelled() {
        return Err(SttError::ModelInstallCancelled);
    }
    let parent = request.destination.parent().ok_or(SttError::ModelMissing)?;
    create_model_directory(parent)?;
    cleanup_stale_download_temps(&request.destination, operation)?;

    let mut temp = OperationTemp::create(&request.destination, operation.clone())?;
    let mut copied = 0_u64;
    let mut buffer = [0_u8; COPY_BUFFER_BYTES];
    loop {
        if operation.is_cancelled() {
            return Err(SttError::ModelInstallCancelled);
        }
        let read = source.read(&mut buffer).map_err(io_error_to_stt)?;
        if read == 0 {
            break;
        }
        copied = copied
            .checked_add(read as u64)
            .ok_or(SttError::ModelCorrupt)?;
        if copied > request.expected_bytes {
            return Err(SttError::ModelCorrupt);
        }
        temp.file_mut()?
            .write_all(&buffer[..read])
            .map_err(io_error_to_stt)?;
    }
    if copied != request.expected_bytes {
        return Err(SttError::ModelCorrupt);
    }
    temp.sync()?;
    temp.verify(request.expected_bytes, &request.expected_sha256)?;
    if operation.is_cancelled() {
        return Err(SttError::ModelInstallCancelled);
    }
    temp.publish_to(&request.destination)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cancellation_after_source_admission_creates_no_destination_or_staging() {
        let root = std::env::temp_dir().join(format!(
            "yap-model-import-admission-cancel-{}-{:?}",
            std::process::id(),
            std::thread::current().id()
        ));
        std::fs::create_dir_all(&root).unwrap();
        let source = root.join("source.onnx");
        let approved = b"approved offline model bytes";
        std::fs::write(&source, approved).unwrap();
        let request = DownloadRequest {
            url: "unused://offline".into(),
            destination: root.join("models/model.onnx"),
            expected_bytes: approved.len() as u64,
            expected_sha256: crate::stt::model::sha256_file(&source).unwrap(),
        };
        let operation = DownloadOperation::new(1);
        let result = import_verified_file_after_admission(&source, &request, &operation, || {
            operation.cancel();
        });
        assert_eq!(result, Err(SttError::ModelInstallCancelled));
        assert_eq!(std::fs::read(&source).unwrap(), approved);
        assert!(!request.destination.parent().unwrap().exists());
        std::fs::remove_dir_all(root).unwrap();
    }

    #[cfg(unix)]
    #[test]
    fn source_replacement_after_admission_keeps_the_opened_original() {
        let root = std::env::temp_dir().join(format!(
            "yap-model-import-source-swap-{}-{:?}",
            std::process::id(),
            std::thread::current().id()
        ));
        std::fs::create_dir_all(&root).unwrap();
        let source = root.join("source.onnx");
        let admitted = root.join("admitted.onnx");
        let destination = root.join("models/model.onnx");
        let approved = b"approved offline model bytes";
        let replaced = b"replaced offline model bytes";
        assert_eq!(approved.len(), replaced.len());
        std::fs::write(&source, approved).unwrap();
        let request = DownloadRequest {
            url: "unused://offline".into(),
            destination: destination.clone(),
            expected_bytes: approved.len() as u64,
            expected_sha256: crate::stt::model::sha256_file(&source).unwrap(),
        };

        let result = import_verified_file_after_admission(
            &source,
            &request,
            &DownloadOperation::new(1),
            || {
                std::fs::rename(&source, &admitted).unwrap();
                std::fs::write(&source, replaced).unwrap();
            },
        );
        assert_eq!(
            result,
            Ok(()),
            "the validated open source stays authoritative"
        );
        assert_eq!(std::fs::read(&destination).unwrap(), approved);
        assert_eq!(std::fs::read(&admitted).unwrap(), approved);
        assert_eq!(std::fs::read(&source).unwrap(), replaced);
        std::fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn offline_import_is_hash_verified_and_atomic() {
        let root = std::env::temp_dir().join(format!(
            "yap-model-import-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir_all(&root).unwrap();
        let source = root.join("source.onnx");
        let destination = root.join("models/model.onnx");
        let approved = b"approved offline model bytes";
        std::fs::write(&source, approved).unwrap();
        let request = DownloadRequest {
            url: "unused://offline".into(),
            destination: destination.clone(),
            expected_bytes: approved.len() as u64,
            expected_sha256: crate::stt::model::sha256_file(&source).unwrap(),
        };

        import_verified_file(&source, &request, &DownloadOperation::new(1)).unwrap();
        assert_eq!(std::fs::read(&destination).unwrap(), approved);

        std::fs::write(&source, b"rejected offline model bytes").unwrap();
        assert!(import_verified_file(&source, &request, &DownloadOperation::new(2)).is_err());
        assert_eq!(std::fs::read(&destination).unwrap(), approved);
        assert_eq!(
            std::fs::read_dir(destination.parent().unwrap())
                .unwrap()
                .count(),
            1
        );
        std::fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn offline_import_classifies_a_non_directory_model_root_as_corrupt() {
        let root = std::env::temp_dir().join(format!(
            "yap-model-import-file-root-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap_or_default()
                .as_nanos()
        ));
        std::fs::create_dir_all(&root).unwrap();
        let source = root.join("source.onnx");
        let model_root = root.join("models");
        let destination = model_root.join("model.onnx");
        let approved = b"approved offline model bytes";
        std::fs::write(&source, approved).unwrap();
        std::fs::write(&model_root, b"not a model directory").unwrap();
        let request = DownloadRequest {
            url: "unused://offline".into(),
            destination,
            expected_bytes: approved.len() as u64,
            expected_sha256: crate::stt::model::sha256_file(&source).unwrap(),
        };

        assert_eq!(
            import_verified_file(&source, &request, &DownloadOperation::new(1)),
            Err(SttError::ModelCorrupt)
        );
        assert_eq!(std::fs::read(&source).unwrap(), approved);

        std::fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn cancelled_offline_import_preserves_the_installed_artifact_and_cleans_staging() {
        let root = std::env::temp_dir().join(format!(
            "yap-model-import-cancel-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap_or_default()
                .as_nanos()
        ));
        std::fs::create_dir_all(&root).unwrap();
        let source = root.join("source.onnx");
        let destination = root.join("models/model.onnx");
        let approved = b"approved offline model bytes";
        std::fs::write(&source, approved).unwrap();
        std::fs::create_dir_all(destination.parent().unwrap()).unwrap();
        std::fs::write(&destination, approved).unwrap();
        let request = DownloadRequest {
            url: "unused://offline".into(),
            destination: destination.clone(),
            expected_bytes: approved.len() as u64,
            expected_sha256: crate::stt::model::sha256_file(&source).unwrap(),
        };
        let operation = DownloadOperation::new(7);
        operation.cancel();

        assert_eq!(
            import_verified_file(&source, &request, &operation),
            Err(SttError::ModelInstallCancelled)
        );
        assert_eq!(std::fs::read(&destination).unwrap(), approved);
        assert_eq!(
            std::fs::read_dir(destination.parent().unwrap())
                .unwrap()
                .count(),
            1
        );

        std::fs::remove_dir_all(root).unwrap();
    }
}
