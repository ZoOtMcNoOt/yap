use std::{fs::Metadata, path::Path};

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

#[cfg(windows)]
pub(crate) fn metadata_is_link_or_reparse(metadata: &Metadata) -> bool {
    use std::os::windows::fs::MetadataExt;

    const FILE_ATTRIBUTE_REPARSE_POINT: u32 = 0x0000_0400;
    metadata.file_type().is_symlink()
        || metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0
}

#[cfg(not(windows))]
pub(crate) fn metadata_is_link_or_reparse(metadata: &Metadata) -> bool {
    metadata.file_type().is_symlink()
}
