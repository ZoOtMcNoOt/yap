//! Directory-owned publication for explicit new-file exports.

use std::{
    ffi::OsStr,
    fs::{File, OpenOptions},
    io::{self, ErrorKind, Write},
    path::{Path, PathBuf},
    time::{SystemTime, UNIX_EPOCH},
};

use crate::bounded_file::metadata_is_link_or_reparse;
#[cfg(unix)]
use std::ffi::CString;

pub(crate) struct NewFileDestination {
    path: PathBuf,
    directories: Vec<DirectoryLease>,
}

struct DirectoryLease {
    path: PathBuf,
    file: File,
    identity: FileIdentity,
}

impl NewFileDestination {
    pub(crate) fn open(path: &Path) -> io::Result<Self> {
        if !path.is_absolute() || path.file_name().and_then(OsStr::to_str).is_none() {
            return Err(io::Error::new(
                ErrorKind::InvalidInput,
                "invalid export filename",
            ));
        }
        let parent = path.parent().ok_or_else(changed_directory)?;
        let mut paths = parent.ancestors().collect::<Vec<_>>();
        paths.reverse();
        let mut directories: Vec<DirectoryLease> = Vec::with_capacity(paths.len());
        for path in paths {
            let file = open_directory(path, directories.last().map(|entry| &entry.file))?;
            let metadata = file.metadata()?;
            if !metadata.is_dir() || metadata_is_link_or_reparse(&metadata) {
                return Err(changed_directory());
            }
            let identity = file_identity(&file)?;
            directories.push(DirectoryLease {
                path: path.to_path_buf(),
                file,
                identity,
            });
        }
        let destination = Self {
            path: path.to_path_buf(),
            directories,
        };
        destination.revalidate()?;
        Ok(destination)
    }

    pub(crate) fn path(&self) -> &Path {
        &self.path
    }

    #[cfg(unix)]
    fn parent(&self) -> &File {
        &self
            .directories
            .last()
            .expect("absolute export has a parent")
            .file
    }

    fn revalidate(&self) -> io::Result<()> {
        let mut previous = None;
        for entry in &self.directories {
            let current = open_directory(&entry.path, previous)?;
            let metadata = current.metadata()?;
            if file_identity(&entry.file)? != entry.identity
                || file_identity(&current)? != entry.identity
                || !metadata.is_dir()
                || metadata_is_link_or_reparse(&metadata)
            {
                return Err(changed_directory());
            }
            // The owned handle and freshly opened component identify the same directory.
            previous = Some(&entry.file);
        }
        Ok(())
    }

    pub(super) fn publish(
        &self,
        text: &str,
        commit: impl FnOnce(&Self, &OsStr) -> io::Result<()>,
    ) -> io::Result<()> {
        self.revalidate()?;
        let (name, mut file) = self.reserve()?;
        let identity = file_identity(&file)?;
        let result = (|| {
            file.write_all(text.as_bytes())?;
            file.sync_all()?;
            self.revalidate()?;
            self.require_staging(&name, identity)?;
            drop(file);
            commit(self, &name)?;
            self.sync_parent()?;
            self.revalidate()
        })();
        if result.is_err() {
            match self.require_staging(&name, identity) {
                Ok(()) => self.remove_staging(&name)?,
                Err(error) if error.kind() == ErrorKind::NotFound => {}
                // A substituted staging entry is somebody else's file.
                Err(_) => {}
            }
        }
        result
    }

    fn reserve(&self) -> io::Result<(std::ffi::OsString, File)> {
        let filename = self.path.file_name().and_then(OsStr::to_str).unwrap();
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos();
        for attempt in 0..32 {
            let name = std::ffi::OsString::from(format!(
                "{filename}.{}.{nonce}.{attempt}.part",
                std::process::id()
            ));
            match self.create_staging(&name) {
                Ok(file) => return Ok((name, file)),
                Err(error) if error.kind() == ErrorKind::AlreadyExists => {}
                Err(error) => return Err(error),
            }
        }
        Err(io::Error::new(
            ErrorKind::AlreadyExists,
            "temporary export path unavailable",
        ))
    }

    fn require_staging(&self, name: &OsStr, identity: FileIdentity) -> io::Result<()> {
        let current = self.open_staging(name)?;
        let metadata = current.metadata()?;
        if !metadata.is_file()
            || metadata_is_link_or_reparse(&metadata)
            || file_identity(&current)? != identity
        {
            return Err(io::Error::new(
                ErrorKind::InvalidData,
                "export staging changed",
            ));
        }
        Ok(())
    }
}

fn changed_directory() -> io::Error {
    io::Error::new(ErrorKind::InvalidData, "export directory changed")
}

#[cfg(unix)]
fn component_name(name: &OsStr) -> io::Result<CString> {
    use std::os::unix::ffi::OsStrExt;
    CString::new(name.as_bytes())
        .map_err(|_| io::Error::new(ErrorKind::InvalidInput, "invalid filename"))
}

#[cfg(unix)]
fn open_at(parent: &File, name: &OsStr, flags: i32, mode: libc::mode_t) -> io::Result<File> {
    use std::os::fd::{AsRawFd, FromRawFd};
    let name = component_name(name)?;
    let descriptor = unsafe {
        libc::openat(
            parent.as_raw_fd(),
            name.as_ptr(),
            flags | libc::O_CLOEXEC | libc::O_NOFOLLOW,
            mode,
        )
    };
    if descriptor < 0 {
        return Err(io::Error::last_os_error());
    }
    // This descriptor was just created for this owner and has no other owner.
    Ok(unsafe { File::from_raw_fd(descriptor) })
}

#[cfg(unix)]
fn open_directory(path: &Path, parent: Option<&File>) -> io::Result<File> {
    use std::os::unix::fs::OpenOptionsExt;
    match parent {
        Some(parent) => open_at(
            parent,
            path.file_name().ok_or_else(changed_directory)?,
            libc::O_RDONLY | libc::O_DIRECTORY,
            0,
        ),
        None => OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_DIRECTORY | libc::O_NOFOLLOW | libc::O_CLOEXEC)
            .open(path),
    }
}

#[cfg(windows)]
fn open_directory(path: &Path, _parent: Option<&File>) -> io::Result<File> {
    use std::os::windows::fs::OpenOptionsExt;
    // Deny deletion/rename of every ancestor while allowing child-file writes.
    OpenOptions::new()
        .read(true)
        .share_mode(0x0000_0001 | 0x0000_0002)
        .custom_flags(0x0200_0000 | 0x0020_0000)
        .open(path)
}

#[cfg(not(any(unix, windows)))]
fn open_directory(_path: &Path, _parent: Option<&File>) -> io::Result<File> {
    Err(io::Error::new(
        ErrorKind::Unsupported,
        "directory-owned export is unsupported",
    ))
}

#[cfg(unix)]
#[derive(Clone, Copy, PartialEq, Eq)]
struct FileIdentity {
    device: u64,
    inode: u64,
}

#[cfg(unix)]
fn file_identity(file: &File) -> io::Result<FileIdentity> {
    use std::os::unix::fs::MetadataExt;
    let metadata = file.metadata()?;
    Ok(FileIdentity {
        device: metadata.dev(),
        inode: metadata.ino(),
    })
}

#[cfg(windows)]
#[derive(Clone, Copy, PartialEq, Eq)]
struct FileIdentity {
    volume: u32,
    index: u64,
}

#[cfg(windows)]
fn file_identity(file: &File) -> io::Result<FileIdentity> {
    use std::os::windows::io::AsRawHandle;
    use windows::Win32::{
        Foundation::HANDLE,
        Storage::FileSystem::{GetFileInformationByHandle, BY_HANDLE_FILE_INFORMATION},
    };
    let mut information = BY_HANDLE_FILE_INFORMATION::default();
    unsafe { GetFileInformationByHandle(HANDLE(file.as_raw_handle()), &mut information) }
        .map_err(|_| io::Error::last_os_error())?;
    Ok(FileIdentity {
        volume: information.dwVolumeSerialNumber,
        index: (u64::from(information.nFileIndexHigh) << 32) | u64::from(information.nFileIndexLow),
    })
}

#[cfg(not(any(unix, windows)))]
#[derive(Clone, Copy, PartialEq, Eq)]
struct FileIdentity;

#[cfg(not(any(unix, windows)))]
fn file_identity(_file: &File) -> io::Result<FileIdentity> {
    Err(io::Error::new(
        ErrorKind::Unsupported,
        "file identity is unsupported",
    ))
}

#[cfg(unix)]
impl NewFileDestination {
    fn create_staging(&self, name: &OsStr) -> io::Result<File> {
        open_at(
            self.parent(),
            name,
            libc::O_WRONLY | libc::O_CREAT | libc::O_EXCL,
            0o600,
        )
    }
    fn open_staging(&self, name: &OsStr) -> io::Result<File> {
        open_at(self.parent(), name, libc::O_RDONLY | libc::O_NONBLOCK, 0)
    }
    fn remove_staging(&self, name: &OsStr) -> io::Result<()> {
        use std::os::fd::AsRawFd;
        let name = component_name(name)?;
        if unsafe { libc::unlinkat(self.parent().as_raw_fd(), name.as_ptr(), 0) } != 0 {
            return Err(io::Error::last_os_error());
        }
        Ok(())
    }
    fn sync_parent(&self) -> io::Result<()> {
        self.parent().sync_all()
    }
    pub(super) fn commit_new(&self, staging: &OsStr) -> io::Result<()> {
        use std::os::fd::AsRawFd;
        let staging = component_name(staging)?;
        let destination = component_name(self.path.file_name().unwrap())?;
        let directory = self.parent().as_raw_fd();
        #[cfg(target_os = "linux")]
        let result = unsafe {
            libc::renameat2(
                directory,
                staging.as_ptr(),
                directory,
                destination.as_ptr(),
                libc::RENAME_NOREPLACE,
            )
        };
        #[cfg(target_os = "macos")]
        let result = unsafe {
            libc::renameatx_np(
                directory,
                staging.as_ptr(),
                directory,
                destination.as_ptr(),
                libc::RENAME_EXCL,
            )
        };
        #[cfg(not(any(target_os = "linux", target_os = "macos")))]
        return Err(io::Error::new(
            ErrorKind::Unsupported,
            "exclusive export is unsupported",
        ));
        #[cfg(any(target_os = "linux", target_os = "macos"))]
        if result != 0 {
            return Err(io::Error::last_os_error());
        }
        Ok(())
    }
}

#[cfg(not(unix))]
impl NewFileDestination {
    fn staging_path(&self, name: &OsStr) -> PathBuf {
        self.path.parent().unwrap().join(name)
    }
    fn create_staging(&self, name: &OsStr) -> io::Result<File> {
        OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(self.staging_path(name))
    }
    fn open_staging(&self, name: &OsStr) -> io::Result<File> {
        #[cfg(windows)]
        {
            use std::os::windows::fs::OpenOptionsExt;
            OpenOptions::new()
                .read(true)
                .custom_flags(0x0020_0000)
                .open(self.staging_path(name))
        }
        #[cfg(not(windows))]
        File::open(self.staging_path(name))
    }
    fn remove_staging(&self, name: &OsStr) -> io::Result<()> {
        std::fs::remove_file(self.staging_path(name))
    }
    fn sync_parent(&self) -> io::Result<()> {
        Ok(())
    }
    pub(super) fn commit_new(&self, staging: &OsStr) -> io::Result<()> {
        crate::atomic_file::rename_same_directory_no_replace(
            &self.staging_path(staging),
            &self.path,
        )
    }
}

#[cfg(all(test, unix))]
mod tests {
    use super::*;

    struct Fixture(PathBuf);

    impl Fixture {
        fn new() -> Self {
            let root = std::env::temp_dir().join(format!(
                "yap-directory-export-{}-{}",
                std::process::id(),
                SystemTime::now()
                    .duration_since(UNIX_EPOCH)
                    .unwrap()
                    .as_nanos()
            ));
            std::fs::create_dir_all(root.join("exports")).unwrap();
            std::fs::create_dir(root.join("substitute")).unwrap();
            Self(root)
        }

        fn replace_parent(&self) {
            std::fs::rename(self.0.join("exports"), self.0.join("retained")).unwrap();
            std::os::unix::fs::symlink(self.0.join("substitute"), self.0.join("exports")).unwrap();
        }
    }

    impl Drop for Fixture {
        fn drop(&mut self) {
            std::fs::remove_dir_all(&self.0).ok();
        }
    }

    #[test]
    fn publication_after_parent_replacement_stays_on_owned_directory_and_is_unconfirmed() {
        let fixture = Fixture::new();
        let destination = NewFileDestination::open(&fixture.0.join("exports/review.txt")).unwrap();
        let text = "Reviewed café — 日本語\nDose: 25 mg.";
        let result = destination.publish(text, |destination, staging| {
            fixture.replace_parent();
            std::fs::write(
                fixture.0.join("substitute").join(staging),
                "unrelated staging",
            )
            .unwrap();
            destination.commit_new(staging)
        });
        assert!(result.is_err(), "changed path must not confirm publication");
        assert_eq!(
            std::fs::read(fixture.0.join("retained/review.txt")).unwrap(),
            text.as_bytes()
        );
        assert!(!fixture.0.join("substitute/review.txt").exists());
        assert_eq!(
            std::fs::read_dir(fixture.0.join("retained"))
                .unwrap()
                .count(),
            1
        );
        let substitute = std::fs::read_dir(fixture.0.join("substitute"))
            .unwrap()
            .next()
            .unwrap()
            .unwrap();
        assert_eq!(
            std::fs::read_to_string(substitute.path()).unwrap(),
            "unrelated staging"
        );
    }

    #[test]
    fn failed_publication_cleans_only_owned_staging_after_parent_replacement() {
        let fixture = Fixture::new();
        let destination = NewFileDestination::open(&fixture.0.join("exports/review.json")).unwrap();
        let result = destination.publish("review bytes", |_, staging| {
            fixture.replace_parent();
            std::fs::write(
                fixture.0.join("substitute").join(staging),
                "unrelated staging",
            )
            .unwrap();
            Err(io::Error::other("publication refused"))
        });
        assert_eq!(result.unwrap_err().kind(), ErrorKind::Other);
        assert_eq!(
            std::fs::read_dir(fixture.0.join("retained"))
                .unwrap()
                .count(),
            0
        );
        assert!(!fixture.0.join("substitute/review.json").exists());
        let substitute = std::fs::read_dir(fixture.0.join("substitute"))
            .unwrap()
            .next()
            .unwrap()
            .unwrap();
        assert_eq!(
            std::fs::read_to_string(substitute.path()).unwrap(),
            "unrelated staging"
        );
    }

    #[test]
    fn cleanup_does_not_block_on_or_remove_a_substituted_fifo() {
        use std::os::unix::fs::FileTypeExt;
        let fixture = Fixture::new();
        let destination = NewFileDestination::open(&fixture.0.join("exports/review.txt")).unwrap();
        let result = destination.publish("original staging bytes", |_, staging| {
            let path = fixture.0.join("exports").join(staging);
            std::fs::rename(&path, fixture.0.join("retained-stage")).unwrap();
            let path = component_name(path.as_os_str()).unwrap();
            assert_eq!(unsafe { libc::mkfifo(path.as_ptr(), 0o600) }, 0);
            Err(io::Error::other("publication refused"))
        });
        assert_eq!(result.unwrap_err().kind(), ErrorKind::Other);
        let replacement = std::fs::read_dir(fixture.0.join("exports"))
            .unwrap()
            .next()
            .unwrap()
            .unwrap();
        assert!(replacement.file_type().unwrap().is_fifo());
        assert_eq!(
            std::fs::read_to_string(fixture.0.join("retained-stage")).unwrap(),
            "original staging bytes"
        );
    }

    #[test]
    fn failed_publication_preserves_a_substituted_staging_entry() {
        let fixture = Fixture::new();
        let destination = NewFileDestination::open(&fixture.0.join("exports/review.txt")).unwrap();
        let result = destination.publish("original staging bytes", |_, staging| {
            std::fs::rename(
                fixture.0.join("exports").join(staging),
                fixture.0.join("retained-stage"),
            )
            .unwrap();
            std::fs::write(
                fixture.0.join("exports").join(staging),
                "unrelated replacement",
            )
            .unwrap();
            Err(io::Error::other("publication refused"))
        });
        assert_eq!(result.unwrap_err().kind(), ErrorKind::Other);
        assert_eq!(
            std::fs::read_to_string(fixture.0.join("retained-stage")).unwrap(),
            "original staging bytes"
        );
        let replacement = std::fs::read_dir(fixture.0.join("exports"))
            .unwrap()
            .next()
            .unwrap()
            .unwrap();
        assert_eq!(
            std::fs::read_to_string(replacement.path()).unwrap(),
            "unrelated replacement"
        );
        assert!(!fixture.0.join("exports/review.txt").exists());
    }
}
