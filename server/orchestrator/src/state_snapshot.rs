use std::fs::{self, OpenOptions};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use crate::error::OrchestratorError;
use crate::lifecycle::ServiceSnapshot;

const MAXIMUM_SNAPSHOT_BYTES: u64 = 64 * 1024;

pub fn read_private_snapshot(path: &Path) -> Result<ServiceSnapshot, OrchestratorError> {
    if !path.is_absolute() {
        return Err(OrchestratorError::new(
            "service state source must be absolute",
        ));
    }
    let canonical = path
        .canonicalize()
        .map_err(|_| OrchestratorError::new("service state source is unavailable"))?;
    if canonical != path {
        return Err(OrchestratorError::new(
            "service state source path must be canonical",
        ));
    }
    let parent = path
        .parent()
        .ok_or_else(|| OrchestratorError::new("service state parent is invalid"))?;
    let parent_metadata = fs::symlink_metadata(parent)?;
    if !parent_metadata.file_type().is_dir() || parent_metadata.file_type().is_symlink() {
        return Err(OrchestratorError::new(
            "service state parent must be a real directory",
        ));
    }
    require_private_directory(parent, &parent_metadata)?;
    require_current_owner(&parent_metadata, "service state parent")?;

    let mut options = OpenOptions::new();
    options.read(true);
    set_no_follow_open_flags(&mut options);
    let file = options
        .open(path)
        .map_err(|_| OrchestratorError::new("service state source is unavailable"))?;
    let metadata = file.metadata()?;
    if !metadata.file_type().is_file()
        || metadata.len() == 0
        || metadata.len() > MAXIMUM_SNAPSHOT_BYTES
    {
        return Err(OrchestratorError::new(
            "service state source must be a bounded regular file",
        ));
    }
    require_owner_private_file(&metadata)?;
    require_current_owner(&metadata, "service state source")?;
    let mut bytes = Vec::with_capacity(metadata.len() as usize);
    file.take(MAXIMUM_SNAPSHOT_BYTES + 1)
        .read_to_end(&mut bytes)?;
    if bytes.len() as u64 != metadata.len() || !bytes.ends_with(b"\n") {
        return Err(OrchestratorError::new(
            "service state source bytes are invalid",
        ));
    }
    serde_json::from_slice(&bytes)
        .map_err(|_| OrchestratorError::new("service state source is invalid"))
}

pub fn write_private_snapshot(
    path: &Path,
    snapshot: &ServiceSnapshot,
) -> Result<(), OrchestratorError> {
    if !path.is_absolute() {
        return Err(OrchestratorError::new(
            "service state destination must be absolute",
        ));
    }
    let parent = path
        .parent()
        .ok_or_else(|| OrchestratorError::new("service state parent is invalid"))?;
    let parent_metadata = fs::symlink_metadata(parent)?;
    if !parent_metadata.file_type().is_dir() || parent_metadata.file_type().is_symlink() {
        return Err(OrchestratorError::new(
            "service state parent must be a real directory",
        ));
    }
    require_private_directory(parent, &parent_metadata)?;
    if let Ok(metadata) = fs::symlink_metadata(path) {
        if !metadata.file_type().is_file() || metadata.file_type().is_symlink() {
            return Err(OrchestratorError::new(
                "service state destination must be a regular file",
            ));
        }
    }

    let file_name = path
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or_else(|| OrchestratorError::new("service state filename is invalid"))?;
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| OrchestratorError::new("system clock is invalid"))?
        .as_nanos();
    let temporary = parent.join(format!(".{file_name}.{}.{nonce}.tmp", std::process::id()));
    let result = write_snapshot_file(&temporary, snapshot).and_then(|()| {
        fs::rename(&temporary, path)?;
        sync_parent(parent)?;
        Ok(())
    });
    if result.is_err() {
        let _ = fs::remove_file(&temporary);
    }
    result
}

fn write_snapshot_file(path: &Path, snapshot: &ServiceSnapshot) -> Result<(), OrchestratorError> {
    let mut options = OpenOptions::new();
    options.create_new(true).write(true);
    set_owner_private_create_mode(&mut options);
    let mut file = options.open(path)?;
    let mut bytes = serde_json::to_vec(snapshot)?;
    bytes.push(b'\n');
    file.write_all(&bytes)?;
    file.sync_all()?;
    set_owner_private_file_permissions(path)?;
    Ok(())
}

#[cfg(unix)]
fn set_owner_private_create_mode(options: &mut OpenOptions) {
    use std::os::unix::fs::OpenOptionsExt;
    options.mode(0o600);
}

#[cfg(unix)]
fn set_no_follow_open_flags(options: &mut OpenOptions) {
    use std::os::unix::fs::OpenOptionsExt;
    options.custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW);
}

#[cfg(not(unix))]
fn set_no_follow_open_flags(_options: &mut OpenOptions) {}

#[cfg(not(unix))]
fn set_owner_private_create_mode(_options: &mut OpenOptions) {}

#[cfg(unix)]
fn set_owner_private_file_permissions(path: &Path) -> Result<(), OrchestratorError> {
    use std::os::unix::fs::PermissionsExt;
    fs::set_permissions(path, fs::Permissions::from_mode(0o600))?;
    Ok(())
}

#[cfg(not(unix))]
fn set_owner_private_file_permissions(_path: &Path) -> Result<(), OrchestratorError> {
    Ok(())
}

#[cfg(unix)]
fn require_private_directory(
    _path: &Path,
    metadata: &fs::Metadata,
) -> Result<(), OrchestratorError> {
    use std::os::unix::fs::PermissionsExt;
    if metadata.permissions().mode() & 0o077 != 0 {
        return Err(OrchestratorError::new(
            "service state parent must be owner-private",
        ));
    }
    Ok(())
}

#[cfg(unix)]
fn require_owner_private_file(metadata: &fs::Metadata) -> Result<(), OrchestratorError> {
    use std::os::unix::fs::PermissionsExt;
    if metadata.permissions().mode() & 0o077 != 0 {
        return Err(OrchestratorError::new(
            "service state source must be owner-private",
        ));
    }
    Ok(())
}

#[cfg(not(unix))]
fn require_owner_private_file(_metadata: &fs::Metadata) -> Result<(), OrchestratorError> {
    Ok(())
}

#[cfg(unix)]
fn require_current_owner(
    metadata: &fs::Metadata,
    component: &str,
) -> Result<(), OrchestratorError> {
    use std::os::unix::fs::MetadataExt;
    if metadata.uid() != unsafe { libc::geteuid() } {
        return Err(OrchestratorError::new(format!(
            "{component} must be owned by the service account"
        )));
    }
    Ok(())
}

#[cfg(not(unix))]
fn require_current_owner(
    _metadata: &fs::Metadata,
    _component: &str,
) -> Result<(), OrchestratorError> {
    Ok(())
}

#[cfg(not(unix))]
fn require_private_directory(
    _path: &Path,
    _metadata: &fs::Metadata,
) -> Result<(), OrchestratorError> {
    Ok(())
}

#[cfg(unix)]
fn sync_parent(parent: &Path) -> Result<(), OrchestratorError> {
    fs::File::open(parent)?.sync_all()?;
    Ok(())
}

#[cfg(not(unix))]
fn sync_parent(_parent: &Path) -> Result<(), OrchestratorError> {
    Ok(())
}

pub(crate) fn validate_snapshot_path(path: PathBuf) -> Result<PathBuf, OrchestratorError> {
    if !path.is_absolute() {
        return Err(OrchestratorError::new(
            "service state destination must be absolute",
        ));
    }
    Ok(path)
}
