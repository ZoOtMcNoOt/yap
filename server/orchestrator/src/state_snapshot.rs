use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use crate::error::OrchestratorError;
use crate::lifecycle::ServiceSnapshot;

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
