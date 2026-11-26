use std::{
    fs::File,
    io::{self, Read, Seek},
    path::{Path, PathBuf},
};

use super::Artifact;
use crate::stt::{
    error::SttError,
    model::{model_directory_state, verify_open_artifact, ModelDirectoryState},
};

pub(super) struct UnixModelLoadGuard {
    artifacts: Vec<(File, PathBuf)>,
}

impl UnixModelLoadGuard {
    pub(super) fn open(root: &Path, artifacts: &[Artifact]) -> Result<Self, SttError> {
        if model_directory_state(root) != ModelDirectoryState::Usable {
            return Err(SttError::ModelCorrupt);
        }
        let mut snapshots = Vec::with_capacity(artifacts.len());
        for artifact in artifacts {
            let (source, _) =
                crate::bounded_file::open_regular_file(&root.join(artifact.file), artifact.bytes)
                    .map_err(|_| SttError::ModelCorrupt)?;
            let snapshot = snapshot_file(|writer| {
                let copied = io::copy(&mut source.take(artifact.bytes + 1), writer)?;
                if copied != artifact.bytes {
                    return Err(io::Error::new(
                        io::ErrorKind::InvalidData,
                        "unexpected model size",
                    ));
                }
                Ok(())
            })
            .map_err(|_| SttError::ModelCorrupt)?;
            verify_open_artifact(&snapshot, artifact.bytes, artifact.sha256, || false)?;
            (&snapshot).rewind().map_err(|_| SttError::ModelCorrupt)?;
            let path = native_model_path(&snapshot).map_err(|_| SttError::ModelCorrupt)?;
            snapshots.push((snapshot, path));
        }
        Ok(Self {
            artifacts: snapshots,
        })
    }

    pub(super) fn path(&self, index: usize) -> &Path {
        &self.artifacts[index].1
    }

    pub(super) fn revalidate_after_native_load(&self) -> Result<(), SttError> {
        use std::os::unix::fs::MetadataExt;
        for (file, path) in &self.artifacts {
            let held = file.metadata().map_err(|_| SttError::ModelCorrupt)?;
            let visible = std::fs::metadata(path).map_err(|_| SttError::ModelCorrupt)?;
            if (held.dev(), held.ino()) != (visible.dev(), visible.ino()) {
                return Err(SttError::ModelCorrupt);
            }
        }
        Ok(())
    }
}

#[cfg(target_os = "linux")]
fn native_model_path(file: &File) -> io::Result<PathBuf> {
    use std::os::fd::AsRawFd;
    Ok(Path::new("/proc/self/fd").join(file.as_raw_fd().to_string()))
}

#[cfg(target_os = "macos")]
fn native_model_path(file: &File) -> io::Result<PathBuf> {
    use std::os::unix::fs::MetadataExt;
    // Darwin's /dev/fd duplicates a descriptor and shares its file offset.
    // The native model reader needs independently seekable opens of the same inode.
    let held = file.metadata()?;
    let path = Path::new("/.vol")
        .join(held.dev().to_string())
        .join(held.ino().to_string());
    let opened = File::open(&path)?.metadata()?;
    if (opened.dev(), opened.ino()) != (held.dev(), held.ino()) {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "model file identity changed",
        ));
    }
    Ok(path)
}

#[cfg(target_os = "linux")]
fn snapshot_file(write: impl FnOnce(&mut File) -> io::Result<()>) -> io::Result<File> {
    use std::os::fd::{AsRawFd, FromRawFd};
    // memfd_create returns a new owned descriptor. The kernel seals apply to every opener.
    let fd = unsafe {
        libc::memfd_create(
            c"yap-model".as_ptr(),
            libc::MFD_CLOEXEC | libc::MFD_ALLOW_SEALING,
        )
    };
    if fd < 0 {
        return Err(io::Error::last_os_error());
    }
    let mut file = unsafe { File::from_raw_fd(fd) };
    write(&mut file)?;
    let seals = libc::F_SEAL_WRITE | libc::F_SEAL_GROW | libc::F_SEAL_SHRINK | libc::F_SEAL_SEAL;
    if unsafe { libc::fcntl(fd, libc::F_ADD_SEALS, seals) } < 0 {
        return Err(io::Error::last_os_error());
    }
    File::open(native_model_path(&file)?)
}

#[cfg(target_os = "macos")]
fn snapshot_file(write: impl FnOnce(&mut File) -> io::Result<()>) -> io::Result<File> {
    use std::os::unix::fs::{MetadataExt, OpenOptionsExt, PermissionsExt};
    let temporary = tempfile::Builder::new()
        .permissions(std::fs::Permissions::from_mode(0o400))
        .tempfile()?;
    let (mut writer, name) = temporary.into_parts();
    let reader = File::options()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
        .open(&name)?;
    let created = writer.metadata()?;
    let opened = reader.metadata()?;
    if (opened.dev(), opened.ino()) != (created.dev(), created.ino()) {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "model snapshot changed",
        ));
    }
    // Remove the name before copying. Sherpa receives only the independent read descriptor.
    name.close()?;
    write(&mut writer)?;
    Ok(reader)
}
