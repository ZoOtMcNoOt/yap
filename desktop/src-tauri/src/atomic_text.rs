use std::{
    io::{ErrorKind, Write},
    path::{Path, PathBuf},
    time::{SystemTime, UNIX_EPOCH},
};

use crate::atomic_file;

pub(crate) fn write(path: &Path, text: &str) -> std::io::Result<()> {
    let file_name = path
        .file_name()
        .and_then(|name| name.to_str())
        .ok_or_else(|| std::io::Error::new(ErrorKind::InvalidInput, "missing file name"))?;
    let legacy_temp = path.with_file_name(format!("{file_name}.part"));
    match std::fs::remove_file(&legacy_temp) {
        Ok(()) => {}
        Err(error) if error.kind() == ErrorKind::NotFound => {}
        Err(error) => return Err(error),
    }

    publish(path, text, atomic_file::replace_same_directory)
}

pub(crate) fn write_new(path: &Path, text: &str) -> std::io::Result<()> {
    publish(path, text, atomic_file::rename_same_directory_no_replace)
}

fn publish(
    path: &Path,
    text: &str,
    commit: fn(&Path, &Path) -> std::io::Result<()>,
) -> std::io::Result<()> {
    let (temp, mut file) = reserve_sibling_temp_file(path)?;
    let result = (|| {
        file.write_all(text.as_bytes())?;
        file.sync_all()?;
        drop(file);
        commit(&temp, path)?;
        atomic_file::sync_parent_directory(path)
    })();
    if result.is_err() {
        match std::fs::remove_file(&temp) {
            Ok(()) => {}
            Err(error) if error.kind() == ErrorKind::NotFound => {}
            Err(error) => return Err(error),
        }
    }
    result
}

fn reserve_sibling_temp_file(path: &Path) -> std::io::Result<(PathBuf, std::fs::File)> {
    let file_name = path
        .file_name()
        .and_then(|name| name.to_str())
        .ok_or_else(|| std::io::Error::new(ErrorKind::InvalidInput, "missing file name"))?;
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    let pid = std::process::id();
    for attempt in 0..32 {
        let temp = path.with_file_name(format!("{file_name}.{pid}.{nonce}.{attempt}.part"));
        let mut options = std::fs::OpenOptions::new();
        options.write(true).create_new(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        match options.open(&temp) {
            Ok(file) => return Ok((temp, file)),
            Err(error) if error.kind() == ErrorKind::AlreadyExists => {}
            Err(error) => return Err(error),
        }
    }
    Err(std::io::Error::new(
        ErrorKind::AlreadyExists,
        "could not reserve temporary text path",
    ))
}
