use std::{
    io::{self, ErrorKind},
    path::Path,
};

fn require_same_directory(source: &Path, destination: &Path) -> io::Result<()> {
    let source_parent = source.parent().ok_or_else(|| {
        io::Error::new(
            ErrorKind::InvalidInput,
            "source path has no parent directory",
        )
    })?;
    let destination_parent = destination.parent().ok_or_else(|| {
        io::Error::new(
            ErrorKind::InvalidInput,
            "destination path has no parent directory",
        )
    })?;
    if source_parent != destination_parent {
        return Err(io::Error::new(
            ErrorKind::InvalidInput,
            "atomic file publication requires one directory",
        ));
    }
    Ok(())
}

#[cfg(windows)]
pub(crate) fn replace_same_directory(source: &Path, destination: &Path) -> io::Result<()> {
    use std::os::windows::ffi::OsStrExt;
    use windows::core::PCWSTR;
    use windows::Win32::Storage::FileSystem::{
        MoveFileExW, ReplaceFileW, MOVEFILE_REPLACE_EXISTING, MOVEFILE_WRITE_THROUGH,
        REPLACEFILE_WRITE_THROUGH,
    };

    require_same_directory(source, destination)?;
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
    result.map_err(|_| io::Error::last_os_error())
}

#[cfg(windows)]
fn destination_path_exists(wide_path: &[u16]) -> bool {
    use windows::core::PCWSTR;
    use windows::Win32::Storage::FileSystem::{GetFileAttributesW, INVALID_FILE_ATTRIBUTES};

    unsafe { GetFileAttributesW(PCWSTR(wide_path.as_ptr())) != INVALID_FILE_ATTRIBUTES }
}

#[cfg(not(windows))]
pub(crate) fn replace_same_directory(source: &Path, destination: &Path) -> io::Result<()> {
    require_same_directory(source, destination)?;
    std::fs::rename(source, destination)
}

#[cfg(windows)]
pub(crate) fn rename_same_directory_no_replace(
    source: &Path,
    destination: &Path,
) -> io::Result<()> {
    use std::os::windows::ffi::OsStrExt;
    use windows::core::PCWSTR;
    use windows::Win32::Storage::FileSystem::{MoveFileExW, MOVEFILE_WRITE_THROUGH};

    require_same_directory(source, destination)?;
    let wide = |path: &Path| {
        path.as_os_str()
            .encode_wide()
            .chain(std::iter::once(0))
            .collect::<Vec<_>>()
    };
    let source = wide(source);
    let destination = wide(destination);
    unsafe {
        MoveFileExW(
            PCWSTR(source.as_ptr()),
            PCWSTR(destination.as_ptr()),
            MOVEFILE_WRITE_THROUGH,
        )
    }
    .map_err(|_| io::Error::last_os_error())
}

#[cfg(target_os = "linux")]
pub(crate) fn rename_same_directory_no_replace(
    source: &Path,
    destination: &Path,
) -> io::Result<()> {
    require_same_directory(source, destination)?;
    let source = path_c_string(source, "source")?;
    let destination = path_c_string(destination, "destination")?;
    let result = unsafe {
        libc::renameat2(
            libc::AT_FDCWD,
            source.as_ptr(),
            libc::AT_FDCWD,
            destination.as_ptr(),
            libc::RENAME_NOREPLACE,
        )
    };
    if result == 0 {
        Ok(())
    } else {
        Err(io::Error::last_os_error())
    }
}

#[cfg(target_os = "macos")]
pub(crate) fn rename_same_directory_no_replace(
    source: &Path,
    destination: &Path,
) -> io::Result<()> {
    require_same_directory(source, destination)?;
    let source = path_c_string(source, "source")?;
    let destination = path_c_string(destination, "destination")?;
    let result =
        unsafe { libc::renamex_np(source.as_ptr(), destination.as_ptr(), libc::RENAME_EXCL) };
    if result == 0 {
        Ok(())
    } else {
        Err(io::Error::last_os_error())
    }
}

#[cfg(unix)]
fn path_c_string(path: &Path, label: &str) -> io::Result<std::ffi::CString> {
    use std::os::unix::ffi::OsStrExt;

    std::ffi::CString::new(path.as_os_str().as_bytes()).map_err(|_| {
        io::Error::new(
            ErrorKind::InvalidInput,
            format!("{label} path contains a NUL byte"),
        )
    })
}

#[cfg(not(any(windows, target_os = "linux", target_os = "macos")))]
pub(crate) fn rename_same_directory_no_replace(
    _source: &Path,
    _destination: &Path,
) -> io::Result<()> {
    Err(io::Error::new(
        ErrorKind::Unsupported,
        "atomic no-replace file publication is unsupported on this platform",
    ))
}

#[cfg(unix)]
pub(crate) fn sync_parent_directory(path: &Path) -> io::Result<()> {
    std::fs::File::open(
        path.parent().ok_or_else(|| {
            io::Error::new(ErrorKind::InvalidInput, "path has no parent directory")
        })?,
    )?
    .sync_all()
}

#[cfg(not(unix))]
pub(crate) fn sync_parent_directory(_path: &Path) -> io::Result<()> {
    Ok(())
}
