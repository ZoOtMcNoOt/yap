use std::path::Path;

use super::Artifact;
use crate::stt::error::SttError;

#[cfg(windows)]
mod windows;
#[cfg(windows)]
use windows::WindowsModelLoadGuard as PlatformGuard;

#[cfg(any(target_os = "linux", target_os = "macos"))]
mod unix;
#[cfg(any(target_os = "linux", target_os = "macos"))]
use unix::UnixModelLoadGuard as PlatformGuard;

/// Keeps the exact verified files supplied to the native recognizer stable for its lifetime.
pub(crate) struct ModelLoadGuard {
    #[cfg(any(windows, target_os = "linux", target_os = "macos"))]
    inner: PlatformGuard,
    #[cfg(not(any(windows, target_os = "linux", target_os = "macos")))]
    _unsupported: (),
}

impl ModelLoadGuard {
    pub(crate) fn open(root: &Path, artifacts: &[Artifact]) -> Result<Self, SttError> {
        #[cfg(not(any(windows, target_os = "linux", target_os = "macos")))]
        {
            let _ = (root, artifacts);
            Err(SttError::ModelCorrupt)
        }

        #[cfg(any(windows, target_os = "linux", target_os = "macos"))]
        {
            PlatformGuard::open(root, artifacts).map(|inner| Self { inner })
        }
    }

    pub(crate) fn path(&self, index: usize) -> &Path {
        #[cfg(not(any(windows, target_os = "linux", target_os = "macos")))]
        {
            unreachable!("native local model loading is unsupported on this target")
        }

        #[cfg(any(windows, target_os = "linux", target_os = "macos"))]
        self.inner.path(index)
    }

    pub(crate) fn revalidate_after_native_load(&self) -> Result<(), SttError> {
        #[cfg(not(any(windows, target_os = "linux", target_os = "macos")))]
        {
            Err(SttError::ModelCorrupt)
        }

        #[cfg(any(windows, target_os = "linux", target_os = "macos"))]
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
