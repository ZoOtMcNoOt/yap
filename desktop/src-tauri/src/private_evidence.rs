use serde::Serialize;
use std::{
    fs::{self, File, OpenOptions},
    io::{self, Write},
    path::{Path, PathBuf},
    sync::atomic::{AtomicU64, Ordering},
};

static NEXT_TEMPORARY_ID: AtomicU64 = AtomicU64::new(0);

pub(crate) fn publish_private_json(
    requested_destination: &Path,
    evidence: &impl Serialize,
) -> io::Result<()> {
    let destination = checked_external_destination(requested_destination)?;
    let bytes = serde_json::to_vec_pretty(evidence).map_err(io::Error::other)?;
    let (temporary, mut output) = create_private_temporary(&destination)?;

    let publish = || -> io::Result<()> {
        output.write_all(&bytes)?;
        output.write_all(b"\n")?;
        output.sync_all()?;
        drop(output);
        fs::hard_link(&temporary, &destination)?;
        let _ = fs::remove_file(&temporary);
        Ok(())
    };

    if let Err(error) = publish() {
        let _ = fs::remove_file(&temporary);
        return Err(error);
    }
    Ok(())
}

fn checked_external_destination(requested: &Path) -> io::Result<PathBuf> {
    if !requested.is_absolute() {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "private evidence destination must be absolute",
        ));
    }
    match fs::symlink_metadata(requested) {
        Ok(_) => {
            return Err(io::Error::new(
                io::ErrorKind::AlreadyExists,
                "private evidence destination already exists",
            ));
        }
        Err(error) if error.kind() == io::ErrorKind::NotFound => {}
        Err(error) => return Err(error),
    }

    let file_name = requested.file_name().ok_or_else(|| {
        io::Error::new(
            io::ErrorKind::InvalidInput,
            "private evidence destination must have a file name",
        )
    })?;
    let parent = requested
        .parent()
        .ok_or_else(|| {
            io::Error::new(
                io::ErrorKind::InvalidInput,
                "private evidence destination must have a parent",
            )
        })?
        .canonicalize()?;
    let repository_root = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .canonicalize()?;
    if parent.starts_with(repository_root) {
        return Err(io::Error::new(
            io::ErrorKind::PermissionDenied,
            "private evidence must remain outside the repository",
        ));
    }
    Ok(parent.join(file_name))
}

fn create_private_temporary(destination: &Path) -> io::Result<(PathBuf, File)> {
    let parent = destination
        .parent()
        .expect("checked destination has a parent");
    let file_name = destination
        .file_name()
        .and_then(|name| name.to_str())
        .ok_or_else(|| {
            io::Error::new(
                io::ErrorKind::InvalidInput,
                "private evidence file name must be UTF-8",
            )
        })?;

    for _ in 0..16 {
        let id = NEXT_TEMPORARY_ID.fetch_add(1, Ordering::Relaxed);
        let temporary = parent.join(format!(".{file_name}.{}.{}.tmp", std::process::id(), id));
        match open_private_file(&temporary) {
            Ok(file) => return Ok((temporary, file)),
            Err(error) if error.kind() == io::ErrorKind::AlreadyExists => continue,
            Err(error) => return Err(error),
        }
    }
    Err(io::Error::new(
        io::ErrorKind::AlreadyExists,
        "could not reserve a unique private evidence temporary file",
    ))
}

fn open_private_file(path: &Path) -> io::Result<File> {
    let mut options = OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let file = options.open(path)?;
    #[cfg(windows)]
    if let Err(error) = restrict_windows_file_acl(path) {
        drop(file);
        let _ = fs::remove_file(path);
        return Err(error);
    }
    Ok(file)
}

#[cfg(windows)]
fn restrict_windows_file_acl(path: &Path) -> io::Result<()> {
    use std::os::windows::ffi::OsStrExt;
    use windows::{
        core::{w, PCWSTR},
        Win32::{
            Foundation::{LocalFree, HLOCAL},
            Security::{
                Authorization::{
                    ConvertStringSecurityDescriptorToSecurityDescriptorW, SDDL_REVISION_1,
                },
                SetFileSecurityW, DACL_SECURITY_INFORMATION, PROTECTED_DACL_SECURITY_INFORMATION,
                PSECURITY_DESCRIPTOR,
            },
        },
    };

    let mut descriptor = PSECURITY_DESCRIPTOR::default();
    unsafe {
        ConvertStringSecurityDescriptorToSecurityDescriptorW(
            w!("D:P(A;;FA;;;OW)(A;;FA;;;SY)(A;;FA;;;BA)"),
            SDDL_REVISION_1,
            &mut descriptor,
            None,
        )
        .map_err(|error| io::Error::other(error.to_string()))?;
    }

    let wide_path: Vec<u16> = path.as_os_str().encode_wide().chain(Some(0)).collect();
    let applied = unsafe {
        SetFileSecurityW(
            PCWSTR(wide_path.as_ptr()),
            DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION,
            descriptor,
        )
        .as_bool()
    };
    unsafe {
        LocalFree(Some(HLOCAL(descriptor.0)));
    }
    if !applied {
        return Err(io::Error::last_os_error());
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde::Serialize;

    #[derive(Serialize)]
    #[serde(rename_all = "camelCase")]
    struct Evidence {
        schema_version: u8,
        passed: bool,
    }

    #[test]
    fn publisher_is_noclobber_and_writes_deterministic_json() {
        let directory = std::env::temp_dir().join(format!(
            "yap-private-evidence-{}-{}",
            std::process::id(),
            NEXT_TEMPORARY_ID.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&directory).unwrap();
        let destination = directory.join("evidence.json");
        let evidence = Evidence {
            schema_version: 1,
            passed: false,
        };

        publish_private_json(&destination, &evidence).unwrap();
        assert_eq!(
            fs::read_to_string(&destination).unwrap(),
            "{\n  \"schemaVersion\": 1,\n  \"passed\": false\n}\n"
        );
        #[cfg(windows)]
        assert_owner_restricted_windows_acl(&destination);
        let error = publish_private_json(
            &destination,
            &Evidence {
                schema_version: 2,
                passed: true,
            },
        )
        .unwrap_err();
        assert_eq!(error.kind(), io::ErrorKind::AlreadyExists);
        assert!(!directory.read_dir().unwrap().any(|entry| entry
            .unwrap()
            .file_name()
            .to_string_lossy()
            .ends_with(".tmp")));

        fs::remove_file(destination).unwrap();
        fs::remove_dir(directory).unwrap();
    }

    #[cfg(windows)]
    fn assert_owner_restricted_windows_acl(path: &Path) {
        use std::os::windows::ffi::OsStrExt;
        use windows::{
            core::{PCWSTR, PWSTR},
            Win32::{
                Foundation::{LocalFree, ERROR_SUCCESS, HLOCAL},
                Security::{
                    Authorization::{
                        ConvertSecurityDescriptorToStringSecurityDescriptorW,
                        GetNamedSecurityInfoW, SDDL_REVISION_1, SE_FILE_OBJECT,
                    },
                    DACL_SECURITY_INFORMATION, PSECURITY_DESCRIPTOR,
                },
            },
        };

        let wide_path: Vec<u16> = path.as_os_str().encode_wide().chain(Some(0)).collect();
        let mut descriptor = PSECURITY_DESCRIPTOR::default();
        let read_result = unsafe {
            GetNamedSecurityInfoW(
                PCWSTR(wide_path.as_ptr()),
                SE_FILE_OBJECT,
                DACL_SECURITY_INFORMATION,
                None,
                None,
                None,
                None,
                &mut descriptor,
            )
        };
        assert_eq!(read_result, ERROR_SUCCESS);

        let mut encoded = PWSTR::null();
        unsafe {
            ConvertSecurityDescriptorToStringSecurityDescriptorW(
                descriptor,
                SDDL_REVISION_1,
                DACL_SECURITY_INFORMATION,
                &mut encoded,
                None,
            )
            .unwrap();
        }
        let sddl = unsafe { encoded.to_string().unwrap() };
        unsafe {
            LocalFree(Some(HLOCAL(encoded.0.cast())));
            LocalFree(Some(HLOCAL(descriptor.0)));
        }

        assert!(sddl.starts_with("D:P"), "DACL must be protected: {sddl}");
        assert!(sddl.contains(";;;SY)"), "SYSTEM must retain access: {sddl}");
        assert!(
            sddl.contains(";;;BA)"),
            "Administrators must retain access: {sddl}"
        );
        assert!(
            sddl.contains(";;;OW)") || sddl.contains(";;;S-1-3-4)"),
            "the object owner must retain access: {sddl}"
        );
        for forbidden in [";;;AU)", ";;;BU)", ";;;WD)"] {
            assert!(
                !sddl.contains(forbidden),
                "broad principal remained in private evidence DACL: {sddl}"
            );
        }
    }
}
