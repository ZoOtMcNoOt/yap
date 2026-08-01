use std::path::Path;

use crate::stt::error::SttError;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum ModelDirectoryState {
    Missing,
    Usable,
    Invalid,
}

pub(crate) fn model_directory_state(path: &Path) -> ModelDirectoryState {
    match std::fs::symlink_metadata(path) {
        Ok(metadata) if metadata.is_dir() && !metadata_is_link_or_reparse(&metadata) => {
            ModelDirectoryState::Usable
        }
        Ok(_) => ModelDirectoryState::Invalid,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => ModelDirectoryState::Missing,
        Err(_) => ModelDirectoryState::Invalid,
    }
}

pub(crate) fn create_model_directory(path: &Path) -> Result<(), SttError> {
    match model_directory_state(path) {
        ModelDirectoryState::Usable => return Ok(()),
        ModelDirectoryState::Invalid => return Err(SttError::ModelCorrupt),
        ModelDirectoryState::Missing => {}
    }
    if std::fs::create_dir_all(path).is_err() {
        return match model_directory_state(path) {
            ModelDirectoryState::Invalid => Err(SttError::ModelCorrupt),
            ModelDirectoryState::Missing | ModelDirectoryState::Usable => {
                Err(SttError::ModelMissing)
            }
        };
    }
    match model_directory_state(path) {
        ModelDirectoryState::Usable => Ok(()),
        ModelDirectoryState::Missing => Err(SttError::ModelMissing),
        ModelDirectoryState::Invalid => Err(SttError::ModelCorrupt),
    }
}

// Re-exported so this module keeps one import path while the
// implementation lives in exactly one place.
pub(crate) use crate::bounded_file::metadata_is_link_or_reparse;
