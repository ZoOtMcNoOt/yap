use std::{
    fs::File,
    io::{self, Read, Seek},
    path::{Path, PathBuf},
};

#[cfg(target_os = "macos")]
use std::os::unix::fs::PermissionsExt;

use super::Artifact;
use crate::stt::{
    error::SttError,
    model::{model_directory_state, verify_open_artifact, ModelDirectoryState},
};

pub(super) struct UnixModelLoadGuard {
    artifacts: Vec<Snapshot>,
    #[cfg(target_os = "macos")]
    _directory: tempfile::TempDir,
}

struct Snapshot {
    file: File,
    path: PathBuf,
    #[cfg(target_os = "macos")]
    expected: Artifact,
}

impl UnixModelLoadGuard {
    pub(super) fn open(root: &Path, artifacts: &[Artifact]) -> Result<Self, SttError> {
        if model_directory_state(root) != ModelDirectoryState::Usable {
            return Err(SttError::ModelCorrupt);
        }
        #[cfg(target_os = "macos")]
        let directory = tempfile::Builder::new()
            .prefix("yap-model-")
            .permissions(std::fs::Permissions::from_mode(0o700))
            .tempdir()
            .map_err(|_| SttError::ModelCorrupt)?;
        let mut snapshots = Vec::with_capacity(artifacts.len());
        for artifact in artifacts {
            let (source, _) =
                crate::bounded_file::open_regular_file(&root.join(artifact.file), artifact.bytes)
                    .map_err(|_| SttError::ModelCorrupt)?;
            let copy = |writer: &mut File| {
                let copied = io::copy(&mut source.take(artifact.bytes + 1), writer)?;
                if copied != artifact.bytes {
                    return Err(io::Error::new(
                        io::ErrorKind::InvalidData,
                        "unexpected model size",
                    ));
                }
                Ok(())
            };
            #[cfg(target_os = "linux")]
            let snapshot = snapshot_file(copy);
            #[cfg(target_os = "macos")]
            let snapshot = snapshot_file(&directory.path().join(snapshots.len().to_string()), copy);
            let snapshot = snapshot.map_err(|_| SttError::ModelCorrupt)?;
            verify_open_artifact(&snapshot, artifact.bytes, artifact.sha256, || false)?;
            (&snapshot).rewind().map_err(|_| SttError::ModelCorrupt)?;
            let path = native_model_path(&snapshot).map_err(|_| SttError::ModelCorrupt)?;
            snapshots.push(Snapshot {
                file: snapshot,
                path,
                #[cfg(target_os = "macos")]
                expected: *artifact,
            });
        }
        Ok(Self {
            artifacts: snapshots,
            #[cfg(target_os = "macos")]
            _directory: directory,
        })
    }

    pub(super) fn path(&self, index: usize) -> &Path {
        &self.artifacts[index].path
    }

    pub(super) fn revalidate_after_native_load(&self) -> Result<(), SttError> {
        use std::os::unix::fs::MetadataExt;
        for snapshot in &self.artifacts {
            let held = snapshot
                .file
                .metadata()
                .map_err(|_| SttError::ModelCorrupt)?;
            let visible = std::fs::metadata(&snapshot.path).map_err(|_| SttError::ModelCorrupt)?;
            if (held.dev(), held.ino()) != (visible.dev(), visible.ino()) {
                return Err(SttError::ModelCorrupt);
            }
            #[cfg(target_os = "macos")]
            verify_open_artifact(
                &snapshot.file,
                snapshot.expected.bytes,
                snapshot.expected.sha256,
                || false,
            )?;
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
fn snapshot_file(name: &Path, write: impl FnOnce(&mut File) -> io::Result<()>) -> io::Result<File> {
    use std::os::unix::fs::OpenOptionsExt;
    // Keep a link in the guard's private directory so Darwin can reopen the inode by ID.
    let mut writer = File::options()
        .write(true)
        .create_new(true)
        .mode(0o400)
        .custom_flags(libc::O_NOFOLLOW)
        .open(name)?;
    write(&mut writer)?;
    File::open(native_model_path(&writer)?)
}
