use std::{
    io::{ErrorKind, Write},
    path::{Path, PathBuf},
    time::{SystemTime, UNIX_EPOCH},
};

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

    let (temp, mut file) = reserve_sibling_temp_file(path)?;
    let result = (|| {
        file.write_all(text.as_bytes())?;
        file.sync_all()?;
        drop(file);
        replace_same_directory(&temp, path)?;
        sync_parent_directory(path)
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
        match std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temp)
        {
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

#[cfg(windows)]
pub(crate) fn replace_same_directory(source: &Path, destination: &Path) -> std::io::Result<()> {
    use std::os::windows::ffi::OsStrExt;
    use windows::core::PCWSTR;
    use windows::Win32::Storage::FileSystem::{
        MoveFileExW, ReplaceFileW, MOVEFILE_REPLACE_EXISTING, MOVEFILE_WRITE_THROUGH,
        REPLACEFILE_WRITE_THROUGH,
    };

    let source_wide = source
        .as_os_str()
        .encode_wide()
        .chain(std::iter::once(0))
        .collect::<Vec<_>>();
    let destination_wide = destination
        .as_os_str()
        .encode_wide()
        .chain(std::iter::once(0))
        .collect::<Vec<_>>();
    let source = PCWSTR(source_wide.as_ptr());
    let destination = PCWSTR(destination_wide.as_ptr());

    let result = unsafe {
        if destination_path_exists(destination_wide.as_slice()) {
            ReplaceFileW(
                destination,
                source,
                PCWSTR::null(),
                REPLACEFILE_WRITE_THROUGH,
                None,
                None,
            )
        } else {
            MoveFileExW(
                source,
                destination,
                MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH,
            )
        }
    };
    if result.is_err() {
        Err(std::io::Error::last_os_error())
    } else {
        Ok(())
    }
}

#[cfg(windows)]
fn destination_path_exists(wide_path: &[u16]) -> bool {
    use windows::core::PCWSTR;
    use windows::Win32::Storage::FileSystem::{GetFileAttributesW, INVALID_FILE_ATTRIBUTES};
    unsafe { GetFileAttributesW(PCWSTR(wide_path.as_ptr())) != INVALID_FILE_ATTRIBUTES }
}

#[cfg(not(windows))]
pub(crate) fn replace_same_directory(source: &Path, destination: &Path) -> std::io::Result<()> {
    std::fs::rename(source, destination)
}

#[cfg(unix)]
pub(crate) fn sync_parent_directory(path: &Path) -> std::io::Result<()> {
    std::fs::File::open(path.parent().ok_or_else(|| {
        std::io::Error::new(ErrorKind::InvalidInput, "path has no parent directory")
    })?)?
    .sync_all()
}

#[cfg(not(unix))]
pub(crate) fn sync_parent_directory(_path: &Path) -> std::io::Result<()> {
    Ok(())
}
