use std::path::Path;

use crate::stt::{
    error::SttError,
    model::{
        cleanup_stale_download_temps, import_verified_file, metadata_is_link_or_reparse,
        model_directory_state, verify_sha256, DownloadOperation, DownloadRequest,
        ModelDirectoryState, ModelInstallState,
    },
    nemotron::{cleanup_stale_model_snapshots, Artifact},
};

use super::{root_dir, ARTIFACTS, MODEL_FILE, MODEL_ID, MODEL_REVISION};

pub struct AcousticLanguageDetectorInstallTag;
pub type AcousticLanguageDetectorInstallState =
    ModelInstallState<AcousticLanguageDetectorInstallTag>;

#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "snake_case")]
pub enum AcousticLanguageDetectorStatus {
    Missing,
    Ready,
    Corrupted,
}

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct AcousticLanguageDetectorView {
    pub id: String,
    pub revision: String,
    pub status: AcousticLanguageDetectorStatus,
    pub installed_bytes: Option<u64>,
    pub expected_bytes: u64,
    pub model_path: String,
    pub install_active: bool,
}

pub fn status() -> AcousticLanguageDetectorView {
    status_at(&root_dir(), ARTIFACTS)
}

/// Imports the exact converted artifact selected by the user. The application
/// intentionally has no network installer until redistribution and hosting of
/// the NVIDIA-derived bytes are explicitly approved.
pub fn import_from_file(
    source: &Path,
    operation: &DownloadOperation,
) -> Result<AcousticLanguageDetectorView, SttError> {
    let root = root_dir();
    let artifact = ARTIFACTS.first().ok_or(SttError::ModelCorrupt)?;
    let request = DownloadRequest {
        url: "unused://verified-local-ambernet-import".into(),
        destination: root.join(MODEL_FILE),
        expected_bytes: artifact.bytes,
        expected_sha256: artifact.sha256.into(),
    };
    import_verified_file(source, &request, operation)?;
    resolve_model_at(&root, ARTIFACTS)?;
    Ok(ready_view(&root, expected_bytes(ARTIFACTS)?))
}

pub fn verify() -> Result<AcousticLanguageDetectorView, SttError> {
    let root = root_dir();
    resolve_model_at(&root, ARTIFACTS)?;
    Ok(ready_view(&root, expected_bytes(ARTIFACTS)?))
}

pub fn remove() -> Result<AcousticLanguageDetectorView, SttError> {
    let root = root_dir();
    remove_at(&root, ARTIFACTS)?;
    Ok(missing_view(&root, ARTIFACTS))
}

fn status_at(root: &Path, artifacts: &[Artifact]) -> AcousticLanguageDetectorView {
    let expected_bytes = expected_bytes(artifacts).unwrap_or(u64::MAX);
    match model_directory_state(root) {
        ModelDirectoryState::Missing => return missing_view(root, artifacts),
        ModelDirectoryState::Invalid => {
            return AcousticLanguageDetectorView {
                id: MODEL_ID.into(),
                revision: MODEL_REVISION.into(),
                status: AcousticLanguageDetectorStatus::Corrupted,
                installed_bytes: None,
                expected_bytes,
                model_path: root.display().to_string(),
                install_active: false,
            };
        }
        ModelDirectoryState::Usable => {}
    }
    let mut present = 0_usize;
    let mut valid = 0_usize;
    let mut installed_bytes = 0_u64;
    for artifact in artifacts {
        let path = root.join(artifact.file);
        match std::fs::symlink_metadata(&path) {
            Ok(metadata) => {
                present += 1;
                installed_bytes = installed_bytes.saturating_add(metadata.len());
                if verify_artifact(&path, artifact).is_ok() {
                    valid += 1;
                }
            }
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
            Err(_) => present += 1,
        }
    }
    let status = if present == 0 {
        AcousticLanguageDetectorStatus::Missing
    } else if valid == artifacts.len() {
        AcousticLanguageDetectorStatus::Ready
    } else {
        AcousticLanguageDetectorStatus::Corrupted
    };
    AcousticLanguageDetectorView {
        id: MODEL_ID.into(),
        revision: MODEL_REVISION.into(),
        status,
        installed_bytes: (present > 0).then_some(installed_bytes),
        expected_bytes,
        model_path: root.display().to_string(),
        install_active: false,
    }
}

fn ready_view(root: &Path, expected_bytes: u64) -> AcousticLanguageDetectorView {
    AcousticLanguageDetectorView {
        id: MODEL_ID.into(),
        revision: MODEL_REVISION.into(),
        status: AcousticLanguageDetectorStatus::Ready,
        installed_bytes: Some(expected_bytes),
        expected_bytes,
        model_path: root.display().to_string(),
        install_active: false,
    }
}

fn missing_view(root: &Path, artifacts: &[Artifact]) -> AcousticLanguageDetectorView {
    AcousticLanguageDetectorView {
        id: MODEL_ID.into(),
        revision: MODEL_REVISION.into(),
        status: AcousticLanguageDetectorStatus::Missing,
        installed_bytes: None,
        expected_bytes: expected_bytes(artifacts).unwrap_or(u64::MAX),
        model_path: root.display().to_string(),
        install_active: false,
    }
}

fn resolve_model_at(root: &Path, artifacts: &[Artifact]) -> Result<(), SttError> {
    match model_directory_state(root) {
        ModelDirectoryState::Missing => return Err(SttError::ModelMissing),
        ModelDirectoryState::Invalid => return Err(SttError::ModelCorrupt),
        ModelDirectoryState::Usable => {}
    }
    for artifact in artifacts {
        verify_artifact(&root.join(artifact.file), artifact)?;
    }
    Ok(())
}

fn verify_artifact(path: &Path, artifact: &Artifact) -> Result<(), SttError> {
    let metadata = std::fs::symlink_metadata(path).map_err(|error| {
        if error.kind() == std::io::ErrorKind::NotFound {
            SttError::ModelMissing
        } else {
            SttError::ModelCorrupt
        }
    })?;
    if !metadata.is_file()
        || metadata_is_link_or_reparse(&metadata)
        || metadata.len() != artifact.bytes
    {
        return Err(SttError::ModelCorrupt);
    }
    verify_sha256(path, artifact.sha256)
}

fn expected_bytes(artifacts: &[Artifact]) -> Result<u64, SttError> {
    artifacts.iter().try_fold(0_u64, |total, artifact| {
        total
            .checked_add(artifact.bytes)
            .ok_or(SttError::ModelCorrupt)
    })
}

fn remove_at(root: &Path, artifacts: &[Artifact]) -> Result<(), SttError> {
    match model_directory_state(root) {
        ModelDirectoryState::Missing => return Ok(()),
        ModelDirectoryState::Invalid => return Err(SttError::ModelCorrupt),
        ModelDirectoryState::Usable => {}
    }
    let cleanup = DownloadOperation::new(u64::MAX);
    cleanup_stale_model_snapshots(root)?;
    for artifact in artifacts {
        let path = root.join(artifact.file);
        cleanup_stale_download_temps(&path, &cleanup)?;
        remove_file_if_present(&path)?;
    }
    match std::fs::remove_dir(root) {
        Ok(()) => Ok(()),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(error) if error.kind() == std::io::ErrorKind::DirectoryNotEmpty => {
            Err(SttError::ModelCorrupt)
        }
        Err(_) => Err(SttError::ModelMissing),
    }
}

fn remove_file_if_present(path: &Path) -> Result<(), SttError> {
    match std::fs::symlink_metadata(path) {
        Ok(metadata) if !metadata.is_file() || metadata_is_link_or_reparse(&metadata) => {
            Err(SttError::ModelCorrupt)
        }
        Ok(_) => std::fs::remove_file(path).map_err(|_| SttError::ModelMissing),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(_) => Err(SttError::ModelMissing),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const TEST_ARTIFACTS: &[Artifact] = &[Artifact {
        file: "model.onnx",
        sha256: "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
        bytes: 3,
    }];

    fn test_root(name: &str) -> std::path::PathBuf {
        std::env::temp_dir().join(format!(
            "yap-ambernet-lifecycle-{name}-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap_or_default()
                .as_nanos()
        ))
    }

    #[cfg(unix)]
    fn create_directory_link(source: &Path, destination: &Path) -> std::io::Result<()> {
        std::os::unix::fs::symlink(source, destination)
    }

    #[cfg(windows)]
    fn create_directory_link(source: &Path, destination: &Path) -> std::io::Result<()> {
        std::os::windows::fs::symlink_dir(source, destination)
    }

    fn link_creation_is_unavailable(error: &std::io::Error) -> bool {
        cfg!(windows)
            && (error.kind() == std::io::ErrorKind::PermissionDenied
                || error.raw_os_error() == Some(1314))
    }

    #[test]
    fn empty_and_partial_imports_are_distinguished() {
        let root = std::env::temp_dir().join(format!(
            "yap-ambernet-lid-status-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap_or_default()
                .as_nanos()
        ));
        std::fs::remove_dir_all(&root).ok();
        assert_eq!(
            status_at(&root, ARTIFACTS).status,
            AcousticLanguageDetectorStatus::Missing
        );
        std::fs::create_dir_all(&root).unwrap();
        std::fs::write(root.join(ARTIFACTS[0].file), b"partial").unwrap();
        assert_eq!(
            status_at(&root, ARTIFACTS).status,
            AcousticLanguageDetectorStatus::Corrupted
        );
        std::fs::remove_dir_all(root).ok();
    }

    #[test]
    fn expected_size_matches_the_frozen_artifact() {
        assert_eq!(expected_bytes(ARTIFACTS).unwrap(), 29_613_392);
    }

    #[test]
    fn non_directory_model_root_is_corrupted() {
        let parent = test_root("file-root");
        std::fs::create_dir_all(&parent).unwrap();
        let root = parent.join("installed-model");
        std::fs::write(&root, b"not a model directory").unwrap();

        assert_eq!(
            status_at(&root, TEST_ARTIFACTS).status,
            AcousticLanguageDetectorStatus::Corrupted
        );
        assert_eq!(
            resolve_model_at(&root, TEST_ARTIFACTS),
            Err(SttError::ModelCorrupt)
        );

        std::fs::remove_dir_all(parent).ok();
    }

    #[cfg(any(windows, unix))]
    #[test]
    fn linked_model_root_is_never_ready_or_verified() {
        let parent = test_root("linked-root");
        let target = parent.join("outside-model");
        let root = parent.join("installed-model");
        std::fs::create_dir_all(&target).unwrap();
        std::fs::write(target.join(TEST_ARTIFACTS[0].file), b"abc").unwrap();
        if let Err(error) = create_directory_link(&target, &root) {
            if link_creation_is_unavailable(&error) {
                std::fs::remove_dir_all(parent).ok();
                return;
            }
            panic!("could not create model-root link: {error}");
        }

        assert_eq!(
            status_at(&root, TEST_ARTIFACTS).status,
            AcousticLanguageDetectorStatus::Corrupted
        );
        assert_eq!(
            resolve_model_at(&root, TEST_ARTIFACTS),
            Err(SttError::ModelCorrupt)
        );
        assert_eq!(
            remove_at(&root, TEST_ARTIFACTS),
            Err(SttError::ModelCorrupt)
        );
        assert_eq!(
            std::fs::read(target.join(TEST_ARTIFACTS[0].file)).unwrap(),
            b"abc"
        );

        #[cfg(windows)]
        std::fs::remove_dir(&root).ok();
        #[cfg(unix)]
        std::fs::remove_file(&root).ok();
        std::fs::remove_dir_all(parent).ok();
    }
}
