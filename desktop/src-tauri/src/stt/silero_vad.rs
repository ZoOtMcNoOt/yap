//! Explicitly installed, hash-pinned Silero VAD artifact and runtime.

mod detector;

use std::path::{Path, PathBuf};

use crate::stt::{
    error::SttError,
    model::{
        cleanup_stale_download_temps, download_verified_file, import_verified_file,
        metadata_is_link_or_reparse, model_directory_state, verify_sha256, DownloadOperation,
        DownloadProgress, DownloadRequest, ModelDirectoryState,
    },
    nemotron::{cleanup_stale_model_snapshots, Artifact},
};

pub(crate) use detector::{SileroVadDetector, SileroVadRuntimeError};
pub struct SileroVadInstallTag;
pub type SileroVadInstallState = crate::stt::model::ModelInstallState<SileroVadInstallTag>;

pub const MODEL_ID: &str = "k2-fsa/silero_vad.onnx";
pub const MODEL_REVISION: &str = "github-release-asset-271935959";
pub const ARTIFACT_SHA256: &str =
    "9e2449e1087496d8d4caba907f23e0bd3f78d91fa552479bb9c23ac09cbb1fd6";
pub const ARTIFACT_BYTES: u64 = 643_854;
pub const DOWNLOAD_URL: &str =
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx";

const MODEL_DIRECTORY: &str = "silero-vad/sha256-9e2449e1087496d8";
pub(crate) const BUNDLED_MODEL_DIR: &str = MODEL_DIRECTORY;
const MODEL_FILE: &str = "silero_vad.onnx";

pub(crate) const ARTIFACTS: &[Artifact] = &[Artifact {
    file: MODEL_FILE,
    sha256: ARTIFACT_SHA256,
    bytes: ARTIFACT_BYTES,
}];

#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SileroVadStatus {
    Missing,
    Ready,
    Corrupted,
}

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SileroVadView {
    pub id: String,
    pub revision: String,
    pub status: SileroVadStatus,
    pub installed_bytes: Option<u64>,
    pub expected_bytes: u64,
    pub model_path: String,
    pub install_active: bool,
}

pub fn root_dir() -> PathBuf {
    crate::stt::model::models_dir().join(MODEL_DIRECTORY)
}

pub fn model_path() -> PathBuf {
    root_dir().join(MODEL_FILE)
}

pub fn status() -> SileroVadView {
    status_at(&model_path())
}

pub fn install<P>(operation: &DownloadOperation, on_progress: P) -> Result<SileroVadView, SttError>
where
    P: FnMut(DownloadProgress),
{
    let request = download_request();
    download_verified_file(&request, operation, on_progress)?;
    resolve_model()?;
    Ok(status())
}

pub fn import_from_file(
    source: &Path,
    operation: &DownloadOperation,
) -> Result<SileroVadView, SttError> {
    let request = download_request();
    import_verified_file(source, &request, operation)?;
    resolve_model()?;
    Ok(status())
}

pub fn verify() -> Result<SileroVadView, SttError> {
    resolve_model()?;
    Ok(status())
}

pub fn remove() -> Result<SileroVadView, SttError> {
    let root = root_dir();
    let path = model_path();
    remove_at(&root, &path)
}

fn remove_at(root: &Path, path: &Path) -> Result<SileroVadView, SttError> {
    match model_directory_state(root) {
        ModelDirectoryState::Missing => return Ok(status_at(path)),
        ModelDirectoryState::Invalid => return Err(SttError::ModelCorrupt),
        ModelDirectoryState::Usable => {}
    }

    let cleanup = DownloadOperation::new(u64::MAX);
    cleanup_stale_download_temps(path, &cleanup)?;
    cleanup_stale_model_snapshots(root)?;
    remove_file_if_present(path)?;
    match std::fs::remove_dir(root) {
        Ok(()) => {}
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
        Err(error) if error.kind() == std::io::ErrorKind::DirectoryNotEmpty => {
            return Err(SttError::ModelCorrupt)
        }
        Err(_) => return Err(SttError::ModelMissing),
    }
    Ok(status_at(path))
}

pub(crate) fn resolve_model() -> Result<PathBuf, SttError> {
    resolve_model_at(&model_path())
}

pub(crate) fn resolve_model_at(path: &Path) -> Result<PathBuf, SttError> {
    match path.parent().map(model_directory_state) {
        Some(ModelDirectoryState::Usable) => {}
        Some(ModelDirectoryState::Missing) => return Err(SttError::ModelMissing),
        Some(ModelDirectoryState::Invalid) | None => return Err(SttError::ModelCorrupt),
    }
    let metadata = std::fs::symlink_metadata(path).map_err(|error| {
        if error.kind() == std::io::ErrorKind::NotFound {
            SttError::ModelMissing
        } else {
            SttError::ModelCorrupt
        }
    })?;
    if !metadata.is_file()
        || metadata_is_link_or_reparse(&metadata)
        || metadata.len() != ARTIFACT_BYTES
    {
        return Err(SttError::ModelCorrupt);
    }
    verify_sha256(path, ARTIFACT_SHA256)?;
    Ok(path.to_path_buf())
}

fn status_at(path: &Path) -> SileroVadView {
    let directory_state = path
        .parent()
        .map(model_directory_state)
        .unwrap_or(ModelDirectoryState::Invalid);
    let (status, installed_bytes) = match directory_state {
        ModelDirectoryState::Missing => (SileroVadStatus::Missing, None),
        ModelDirectoryState::Invalid => (SileroVadStatus::Corrupted, None),
        ModelDirectoryState::Usable => match std::fs::symlink_metadata(path) {
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                (SileroVadStatus::Missing, None)
            }
            Ok(metadata)
                if metadata.is_file()
                    && !metadata_is_link_or_reparse(&metadata)
                    && metadata.len() == ARTIFACT_BYTES
                    && verify_sha256(path, ARTIFACT_SHA256).is_ok() =>
            {
                (SileroVadStatus::Ready, Some(metadata.len()))
            }
            Ok(metadata) => (SileroVadStatus::Corrupted, Some(metadata.len())),
            Err(_) => (SileroVadStatus::Corrupted, None),
        },
    };
    SileroVadView {
        id: MODEL_ID.into(),
        revision: MODEL_REVISION.into(),
        status,
        installed_bytes,
        expected_bytes: ARTIFACT_BYTES,
        model_path: path.display().to_string(),
        install_active: false,
    }
}

fn download_request() -> DownloadRequest {
    DownloadRequest {
        url: DOWNLOAD_URL.into(),
        destination: model_path(),
        expected_bytes: ARTIFACT_BYTES,
        expected_sha256: ARTIFACT_SHA256.into(),
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
mod tests;
