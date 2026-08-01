use std::{fmt, fs::File, io, path::Path};

// This coordinates trusted processes that use a stable lease path. On Unix, advisory locks are
// inode-scoped; a same-user actor that can replace this path or an ancestor is outside the trust
// model and can bypass pathname-based coordination despite the final-component no-follow checks.
pub(crate) struct ExclusiveFileLease {
    file: File,
}

#[derive(Debug)]
pub(crate) enum TryAcquireExclusiveFileLeaseError {
    Contended,
    Io(io::Error),
}

impl fmt::Display for TryAcquireExclusiveFileLeaseError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Contended => formatter.write_str("exclusive file lease is already held"),
            Self::Io(error) => error.fmt(formatter),
        }
    }
}

impl std::error::Error for TryAcquireExclusiveFileLeaseError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            Self::Contended => None,
            Self::Io(error) => Some(error),
        }
    }
}

pub(crate) fn try_acquire(
    path: &Path,
) -> Result<ExclusiveFileLease, TryAcquireExclusiveFileLeaseError> {
    let file = open_lease_file(path).map_err(TryAcquireExclusiveFileLeaseError::Io)?;
    match file.try_lock() {
        Ok(()) => Ok(ExclusiveFileLease { file }),
        Err(std::fs::TryLockError::WouldBlock) => Err(TryAcquireExclusiveFileLeaseError::Contended),
        Err(std::fs::TryLockError::Error(error)) => {
            Err(TryAcquireExclusiveFileLeaseError::Io(error))
        }
    }
}

impl Drop for ExclusiveFileLease {
    fn drop(&mut self) {
        self.file.unlock().ok();
    }
}

fn lease_entry_must_be_regular(path: &Path) -> io::Error {
    io::Error::new(
        io::ErrorKind::InvalidData,
        format!(
            "exclusive lease entry must be a regular file: {}",
            path.display()
        ),
    )
}

#[cfg(windows)]
fn validate_existing_lease_entry(path: &Path) -> io::Result<()> {
    use std::os::windows::fs::MetadataExt;

    const FILE_ATTRIBUTE_DIRECTORY: u32 = 0x10;
    const FILE_ATTRIBUTE_REPARSE_POINT: u32 = 0x400;

    match std::fs::symlink_metadata(path) {
        Ok(metadata)
            if metadata.is_file()
                && metadata.file_attributes()
                    & (FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT)
                    == 0 =>
        {
            Ok(())
        }
        Ok(_) => Err(lease_entry_must_be_regular(path)),
        Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(()),
        Err(error) => Err(error),
    }
}

#[cfg(unix)]
fn validate_existing_lease_entry(path: &Path) -> io::Result<()> {
    match std::fs::symlink_metadata(path) {
        Ok(metadata) if metadata.is_file() => Ok(()),
        Ok(_) => Err(lease_entry_must_be_regular(path)),
        Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(()),
        Err(error) => Err(error),
    }
}

#[cfg(windows)]
fn open_lease_file(path: &Path) -> io::Result<File> {
    use std::os::windows::fs::{MetadataExt, OpenOptionsExt};

    const FILE_SHARE_READ: u32 = 0x0000_0001;
    const FILE_SHARE_WRITE: u32 = 0x0000_0002;
    const FILE_ATTRIBUTE_DIRECTORY: u32 = 0x10;
    const FILE_ATTRIBUTE_REPARSE_POINT: u32 = 0x400;
    const FILE_FLAG_OPEN_REPARSE_POINT: u32 = 0x0020_0000;

    validate_existing_lease_entry(path)?;
    let file = std::fs::OpenOptions::new()
        .create(true)
        .truncate(false)
        .read(true)
        .write(true)
        .share_mode(FILE_SHARE_READ | FILE_SHARE_WRITE)
        .custom_flags(FILE_FLAG_OPEN_REPARSE_POINT)
        .open(path)?;
    let metadata = file.metadata()?;
    if !metadata.is_file()
        || metadata.file_attributes() & (FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT)
            != 0
    {
        return Err(lease_entry_must_be_regular(path));
    }
    Ok(file)
}

#[cfg(unix)]
fn open_lease_file(path: &Path) -> io::Result<File> {
    use std::os::unix::fs::OpenOptionsExt;

    validate_existing_lease_entry(path)?;
    let file = match std::fs::OpenOptions::new()
        .create(true)
        .truncate(false)
        .read(true)
        .write(true)
        .mode(0o600)
        .custom_flags(libc::O_NOFOLLOW)
        .open(path)
    {
        Ok(file) => file,
        Err(error) if error.raw_os_error() == Some(libc::ELOOP) => {
            return Err(lease_entry_must_be_regular(path));
        }
        Err(error) => return Err(error),
    };
    if !file.metadata()?.is_file() {
        return Err(lease_entry_must_be_regular(path));
    }
    Ok(file)
}

#[cfg(not(any(windows, unix)))]
fn open_lease_file(_path: &Path) -> io::Result<File> {
    Err(io::Error::new(
        io::ErrorKind::Unsupported,
        "secure exclusive file leases are unsupported on this platform",
    ))
}

#[cfg(test)]
mod tests;
