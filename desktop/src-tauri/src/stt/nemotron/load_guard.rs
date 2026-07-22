use std::path::Path;

use super::Artifact;
use crate::stt::error::SttError;

#[cfg(windows)]
mod windows;

/// Keeps the exact verified files supplied to the native recognizer stable for its lifetime.
pub(crate) struct ModelLoadGuard {
    #[cfg(windows)]
    inner: windows::WindowsModelLoadGuard,
    #[cfg(not(windows))]
    _unsupported: (),
}

impl ModelLoadGuard {
    pub(crate) fn open(root: &Path, artifacts: &[Artifact]) -> Result<Self, SttError> {
        #[cfg(not(windows))]
        {
            let _ = (root, artifacts);
            Err(SttError::ModelCorrupt)
        }

        #[cfg(windows)]
        {
            windows::WindowsModelLoadGuard::open(root, artifacts).map(|inner| Self { inner })
        }
    }

    pub(crate) fn path(&self, index: usize) -> &Path {
        #[cfg(not(windows))]
        {
            unreachable!("native local model loading is unsupported off Windows")
        }

        #[cfg(windows)]
        self.inner.path(index)
    }

    pub(crate) fn revalidate_after_native_load(&self) -> Result<(), SttError> {
        #[cfg(not(windows))]
        {
            Err(SttError::ModelCorrupt)
        }

        #[cfg(windows)]
        self.inner.revalidate_after_native_load()
    }
}

#[cfg(windows)]
pub(crate) fn cleanup_stale_snapshots(root: &Path) -> Result<(), SttError> {
    windows::cleanup_stale_snapshots(root)
}

#[cfg(not(windows))]
pub(crate) fn cleanup_stale_snapshots(_root: &Path) -> Result<(), SttError> {
    Ok(())
}
