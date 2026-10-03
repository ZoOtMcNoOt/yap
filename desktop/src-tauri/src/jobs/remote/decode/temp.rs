use std::{
    fs::File,
    path::{Path, PathBuf},
};

/// Holds the reserved plaintext handle until canonical preparation finishes.
/// Reservation never replaces a path; cleanup never owns an occupied path.
pub(super) struct DecodedFile {
    // Unix cleanup needs the pathname; Windows cleanup belongs to the handle.
    // Tests retain it to assert that owned files disappear after handle close.
    #[cfg(any(unix, test))]
    pub(super) path: PathBuf,
    pub(super) file: File,
}

impl DecodedFile {
    pub(super) fn reserve(path: PathBuf) -> std::io::Result<Self> {
        let mut options = std::fs::OpenOptions::new();
        options.read(true).write(true).create_new(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600).custom_flags(libc::O_NOFOLLOW);
        }
        #[cfg(windows)]
        {
            use std::os::windows::fs::OpenOptionsExt;
            // DELETE_ON_CLOSE binds deletion to the created object, including
            // after a crash. Preparation clones this handle rather than opening
            // the pathname, and the last handle closes only after it is done.
            const FILE_FLAG_DELETE_ON_CLOSE: u32 = 0x0400_0000;
            const FILE_FLAG_OPEN_REPARSE_POINT: u32 = 0x0020_0000;
            const GENERIC_READ_WRITE_DELETE: u32 = 0xC001_0000;
            options
                .access_mode(GENERIC_READ_WRITE_DELETE)
                .custom_flags(FILE_FLAG_DELETE_ON_CLOSE | FILE_FLAG_OPEN_REPARSE_POINT);
        }
        #[cfg(not(any(unix, windows)))]
        return Err(std::io::Error::new(
            std::io::ErrorKind::Unsupported,
            "private decoded-file ownership is unsupported on this platform",
        ));
        let file = options.open(&path)?;
        Ok(Self {
            #[cfg(any(unix, test))]
            path,
            file,
        })
    }

    pub(super) fn create(root: &Path, job_id: &str) -> Result<Self, String> {
        super::super::artifact_io::validate_identifier(job_id, 128, "job ID")?;
        super::super::spool::prepare_spool_root(root)?;
        for _ in 0..32 {
            let nonce = super::super::artifact_io::next_staging_nonce();
            let path = root.join(format!(
                ".{job_id}-decoded-{}-{nonce}.wav",
                std::process::id()
            ));
            match Self::reserve(path) {
                Ok(file) => return Ok(file),
                Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {}
                Err(error) => return Err(format!("failed to reserve decoded audio: {error}")),
            }
        }
        Err("could not reserve a new decoded audio file".into())
    }
}

#[cfg(unix)]
impl Drop for DecodedFile {
    fn drop(&mut self) {
        // A renamed/replaced path no longer belongs to this attempt. Refuse
        // links and compare device/inode while the original handle stays open.
        if let Ok((current, _)) = crate::bounded_file::open_regular_file(&self.path, u64::MAX) {
            if crate::bounded_file::same_file_identity(&self.file, &current).unwrap_or(false) {
                let _ = std::fs::remove_file(&self.path);
            }
        }
    }
}
