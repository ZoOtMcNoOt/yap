//! Single-instance ownership: the lease, the instance marker, and the
//! activation handoff that lets a second launch raise the running window
//! instead of starting a rival process.
//!
//! Split out of `app.rs`, which was 1798 lines and mixed this with application
//! wiring and startup diagnostics. `app.rs` glob-imports it, so call sites and
//! tests read exactly as they did before the move.

use super::*;

pub(super) fn acquire_instance_lease_at(
    app_data_directory: &std::path::Path,
) -> std::io::Result<exclusive_file_lease::ExclusiveFileLease> {
    std::fs::create_dir_all(app_data_directory)?;
    let lease_path = app_data_directory.join(INSTANCE_LEASE_FILE);
    match exclusive_file_lease::try_acquire(&lease_path) {
        Ok(lease) => Ok(lease),
        Err(exclusive_file_lease::TryAcquireExclusiveFileLeaseError::Contended) => {
            Err(std::io::Error::new(
                std::io::ErrorKind::WouldBlock,
                format!(
                    "another Yap process owns the application-data directory: {}",
                    app_data_directory.display()
                ),
            ))
        }
        Err(exclusive_file_lease::TryAcquireExclusiveFileLeaseError::Io(error)) => {
            Err(std::io::Error::new(
                error.kind(),
                format!(
                    "could not acquire the Yap instance lease at {}: {error}",
                    lease_path.display()
                ),
            ))
        }
    }
}

pub(super) fn try_acquire_instance_activation_handoff_lease_at(
    app_data_directory: &std::path::Path,
) -> std::io::Result<Option<exclusive_file_lease::ExclusiveFileLease>> {
    std::fs::create_dir_all(app_data_directory)?;
    let lease_path = app_data_directory.join(INSTANCE_ACTIVATION_HANDOFF_LEASE_FILE);
    match exclusive_file_lease::try_acquire(&lease_path) {
        Ok(lease) => Ok(Some(lease)),
        Err(exclusive_file_lease::TryAcquireExclusiveFileLeaseError::Contended) => Ok(None),
        Err(exclusive_file_lease::TryAcquireExclusiveFileLeaseError::Io(error)) => {
            Err(std::io::Error::new(
                error.kind(),
                format!(
                    "could not acquire the Yap activation handoff lease at {}: {error}",
                    lease_path.display()
                ),
            ))
        }
    }
}

pub(super) fn acquire_instance_activation_handoff_lease_at(
    app_data_directory: &std::path::Path,
    max_polls: usize,
    poll_interval: std::time::Duration,
    mut pause: impl FnMut(std::time::Duration),
) -> std::io::Result<exclusive_file_lease::ExclusiveFileLease> {
    if max_polls == 0 {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            "activation handoff lease acquisition requires at least one poll",
        ));
    }
    for poll in 0..max_polls {
        if let Some(lease) = try_acquire_instance_activation_handoff_lease_at(app_data_directory)? {
            return Ok(lease);
        }
        if poll + 1 < max_polls {
            pause(poll_interval);
        }
    }
    Err(std::io::Error::new(
        std::io::ErrorKind::TimedOut,
        "the activation handoff lease remained contended past its deadline",
    ))
}

pub(super) enum InstanceMarkerPublicationError {
    NotPublished(std::io::Error),
    Durability(std::io::Error),
}

impl InstanceMarkerPublicationError {
    fn into_io_error(self) -> std::io::Error {
        match self {
            Self::NotPublished(error) | Self::Durability(error) => error,
        }
    }
}

pub(super) fn request_existing_instance_activation_at(
    path: &std::path::Path,
) -> std::io::Result<()> {
    request_existing_instance_activation_at_with_before_publish(path, |_| {})
}

// This is the atomic marker primitive. Runtime callers serialize it with the
// activation handoff lease; direct callers below are publication unit tests.
pub(super) fn request_existing_instance_activation_at_with_before_publish(
    path: &std::path::Path,
    before_publish: impl FnMut(&std::path::Path),
) -> std::io::Result<()> {
    publish_instance_marker_at_with_before_publish(
        path,
        INSTANCE_ACTIVATION_REQUEST,
        before_publish,
    )
}

pub(super) fn publish_instance_shutdown_at(path: &std::path::Path) -> std::io::Result<()> {
    match publish_instance_marker_at_with_before_publish(path, INSTANCE_SHUTDOWN, |_| {}) {
        Ok(()) => Ok(()),
        Err(original) => match discard_instance_shutdown_at(path) {
            Ok(()) => Err(original),
            Err(cleanup_error) => Err(std::io::Error::new(
                cleanup_error.kind(),
                format!("{original}; shutdown marker rollback also failed: {cleanup_error}"),
            )),
        },
    }
}

pub(super) fn publish_instance_marker_at_with_before_publish(
    path: &std::path::Path,
    contents: &[u8],
    mut before_publish: impl FnMut(&std::path::Path),
) -> std::io::Result<()> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    for _ in 0..=1 {
        match create_instance_marker_file(path, contents, &mut before_publish) {
            Ok(()) => return Ok(()),
            Err(InstanceMarkerPublicationError::Durability(error)) => return Err(error),
            Err(InstanceMarkerPublicationError::NotPublished(create_error)) => {
                match std::fs::symlink_metadata(path) {
                    Ok(_) => {}
                    Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                        return Err(create_error);
                    }
                    Err(error) => return Err(error),
                }
                match read_instance_marker(path, contents) {
                    Ok(Some(true)) => return Ok(()),
                    Ok(None) => continue,
                    Ok(Some(false)) | Err(_) => {
                        quarantine_invalid_instance_marker(path)?;
                    }
                }
            }
        }
    }
    create_instance_marker_file(path, contents, &mut before_publish)
        .map_err(InstanceMarkerPublicationError::into_io_error)
}

// Publish only after the complete marker is durable so readers cannot observe
// or quarantine an in-progress writer handle at the marker path.
pub(super) fn create_instance_marker_file(
    path: &std::path::Path,
    contents: &[u8],
    before_publish: &mut impl FnMut(&std::path::Path),
) -> Result<(), InstanceMarkerPublicationError> {
    let (temporary, mut file) = reserve_instance_marker_temp_file(path)
        .map_err(InstanceMarkerPublicationError::NotPublished)?;
    let prepared = (|| {
        file.write_all(contents)?;
        file.flush()?;
        file.sync_all()
    })();
    drop(file);
    if let Err(error) = prepared {
        return Err(InstanceMarkerPublicationError::NotPublished(
            instance_marker_temp_cleanup_error(&temporary, error),
        ));
    }
    before_publish(&temporary);
    if let Err(error) = crate::atomic_file::rename_same_directory_no_replace(&temporary, path) {
        return Err(InstanceMarkerPublicationError::NotPublished(
            instance_marker_temp_cleanup_error(&temporary, error),
        ));
    }
    crate::atomic_file::sync_parent_directory(path)
        .map_err(InstanceMarkerPublicationError::Durability)
}

pub(super) fn instance_marker_temp_cleanup_error(
    temporary: &std::path::Path,
    original: std::io::Error,
) -> std::io::Error {
    match std::fs::remove_file(temporary) {
        Ok(()) => original,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => original,
        Err(error) => error,
    }
}

pub(super) fn reserve_instance_marker_temp_file(
    path: &std::path::Path,
) -> std::io::Result<(std::path::PathBuf, std::fs::File)> {
    let file_name = path
        .file_name()
        .and_then(|name| name.to_str())
        .ok_or_else(|| {
            std::io::Error::new(
                std::io::ErrorKind::InvalidInput,
                "instance marker path has no file name",
            )
        })?;
    let nonce = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    for attempt in 0..INSTANCE_ACTIVATION_TEMP_ATTEMPTS {
        let temporary = path.with_file_name(format!(
            "{file_name}.pending-{}-{nonce}-{attempt}",
            std::process::id()
        ));
        let mut options = std::fs::OpenOptions::new();
        options.create_new(true).write(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        match options.open(&temporary) {
            Ok(file) => return Ok((temporary, file)),
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {}
            Err(error) => return Err(error),
        }
    }
    Err(std::io::Error::new(
        std::io::ErrorKind::AlreadyExists,
        "could not reserve an instance-marker temporary path",
    ))
}

pub(super) fn read_instance_marker(
    path: &std::path::Path,
    expected: &[u8],
) -> std::io::Result<Option<bool>> {
    match crate::bounded_file::read_bytes(path, expected.len()) {
        Ok(bytes) => Ok(Some(bytes == expected)),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(None),
        Err(error) => Err(error),
    }
}

pub(super) fn read_activation_request(path: &std::path::Path) -> std::io::Result<Option<bool>> {
    read_instance_marker(path, INSTANCE_ACTIVATION_REQUEST)
}

// Production consumption occurs only while holding the activation handoff
// lease, so marker removal and secondary decisions have one linearization order.
pub(super) fn take_existing_instance_activation_request_at(
    path: &std::path::Path,
) -> std::io::Result<bool> {
    match read_activation_request(path) {
        Ok(None) => Ok(false),
        Ok(Some(true)) => match std::fs::remove_file(path) {
            Ok(()) => Ok(true),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(false),
            Err(error) => Err(error),
        },
        Ok(Some(false)) => {
            quarantine_invalid_instance_marker(path)?;
            Err(std::io::Error::new(
                std::io::ErrorKind::InvalidData,
                "stale activation request was quarantined",
            ))
        }
        Err(error) => {
            quarantine_invalid_instance_marker(path)?;
            Err(std::io::Error::new(
                std::io::ErrorKind::InvalidData,
                format!("invalid activation request was quarantined: {error}"),
            ))
        }
    }
}

pub(super) fn discard_instance_marker_at(
    path: &std::path::Path,
    expected: &[u8],
) -> std::io::Result<()> {
    match read_instance_marker(path, expected) {
        Ok(None) => Ok(()),
        Ok(Some(true)) => match std::fs::remove_file(path) {
            Ok(()) => crate::atomic_file::sync_parent_directory(path),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
            Err(error) => Err(error),
        },
        Ok(Some(false)) | Err(_) => quarantine_invalid_instance_marker(path),
    }
}

pub(super) fn discard_existing_instance_activation_request_at(
    path: &std::path::Path,
) -> std::io::Result<()> {
    discard_instance_marker_at(path, INSTANCE_ACTIVATION_REQUEST)
}

pub(super) fn discard_instance_shutdown_at(path: &std::path::Path) -> std::io::Result<()> {
    discard_instance_marker_at(path, INSTANCE_SHUTDOWN)
}

pub(super) fn instance_shutdown_pending_at(path: &std::path::Path) -> std::io::Result<bool> {
    match read_instance_marker(path, INSTANCE_SHUTDOWN) {
        Ok(None) => Ok(false),
        Ok(Some(true)) => Ok(true),
        Ok(Some(false)) => {
            quarantine_invalid_instance_marker(path)?;
            Err(std::io::Error::new(
                std::io::ErrorKind::InvalidData,
                "stale instance shutdown marker was quarantined",
            ))
        }
        Err(error) => {
            quarantine_invalid_instance_marker(path)?;
            Err(std::io::Error::new(
                std::io::ErrorKind::InvalidData,
                format!("invalid instance shutdown marker was quarantined: {error}"),
            ))
        }
    }
}

pub(super) fn clear_owned_instance_activation_state_at(
    app_data_directory: &std::path::Path,
) -> std::io::Result<()> {
    discard_instance_shutdown_at(&app_data_directory.join(INSTANCE_SHUTDOWN_FILE))?;
    discard_existing_instance_activation_request_at(
        &app_data_directory.join(INSTANCE_ACTIVATION_REQUEST_FILE),
    )
}

pub(super) fn prepare_primary_instance_activation_state_at(
    app_data_directory: &std::path::Path,
    max_polls: usize,
    poll_interval: std::time::Duration,
    pause: impl FnMut(std::time::Duration),
) -> std::io::Result<()> {
    let _handoff_lease = acquire_instance_activation_handoff_lease_at(
        app_data_directory,
        max_polls,
        poll_interval,
        pause,
    )?;
    clear_owned_instance_activation_state_at(app_data_directory)
}

pub(super) fn publish_existing_instance_activation_request_at(
    app_data_directory: &std::path::Path,
    max_polls: usize,
    poll_interval: std::time::Duration,
    pause: impl FnMut(std::time::Duration),
) -> std::io::Result<()> {
    let _handoff_lease = acquire_instance_activation_handoff_lease_at(
        app_data_directory,
        max_polls,
        poll_interval,
        pause,
    )?;
    if !instance_shutdown_pending_at(&app_data_directory.join(INSTANCE_SHUTDOWN_FILE))? {
        request_existing_instance_activation_at(
            &app_data_directory.join(INSTANCE_ACTIVATION_REQUEST_FILE),
        )?;
    }
    Ok(())
}

pub(super) fn complete_existing_instance_activation_handoff_at<T>(
    app_data_directory: &std::path::Path,
    max_polls: usize,
    poll_interval: std::time::Duration,
    mut try_acquire_lease: impl FnMut() -> std::io::Result<Option<T>>,
    mut pause: impl FnMut(std::time::Duration),
) -> std::io::Result<InstanceActivationHandoff<T>> {
    if max_polls == 0 {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            "activation handoff requires at least one lease poll",
        ));
    }
    let request_path = app_data_directory.join(INSTANCE_ACTIVATION_REQUEST_FILE);
    let shutdown_path = app_data_directory.join(INSTANCE_SHUTDOWN_FILE);

    for poll in 0..max_polls {
        if let Some(_handoff_lease) =
            try_acquire_instance_activation_handoff_lease_at(app_data_directory)?
        {
            let shutdown_pending = instance_shutdown_pending_at(&shutdown_path)?;
            match try_acquire_lease()? {
                Some(lease) => {
                    clear_owned_instance_activation_state_at(app_data_directory)?;
                    return Ok(InstanceActivationHandoff::Acquired(lease));
                }
                None if shutdown_pending => {}
                None => match read_activation_request(&request_path)? {
                    None => return Ok(InstanceActivationHandoff::Acknowledged),
                    Some(true) => {}
                    Some(false) => {
                        return Err(std::io::Error::new(
                            std::io::ErrorKind::InvalidData,
                            "activation request marker became invalid during handoff",
                        ));
                    }
                },
            }
        }
        if poll + 1 < max_polls {
            pause(poll_interval);
        }
    }
    Err(std::io::Error::new(
        std::io::ErrorKind::TimedOut,
        "the existing Yap process did not acknowledge the activation request or release its lease before the handoff deadline",
    ))
}

pub(super) fn begin_instance_activation_shutdown_at(
    app_data_directory: &std::path::Path,
    max_polls: usize,
    poll_interval: std::time::Duration,
    pause: impl FnMut(std::time::Duration),
) -> std::io::Result<()> {
    let _handoff_lease = acquire_instance_activation_handoff_lease_at(
        app_data_directory,
        max_polls,
        poll_interval,
        pause,
    )?;
    publish_instance_shutdown_at(&app_data_directory.join(INSTANCE_SHUTDOWN_FILE))
}

pub(super) fn reopen_instance_activation_after_abandoned_shutdown_at(
    app_data_directory: &std::path::Path,
    max_polls: usize,
    poll_interval: std::time::Duration,
    pause: impl FnMut(std::time::Duration),
) -> std::io::Result<()> {
    let _handoff_lease = acquire_instance_activation_handoff_lease_at(
        app_data_directory,
        max_polls,
        poll_interval,
        pause,
    )?;
    let shutdown_path = app_data_directory.join(INSTANCE_SHUTDOWN_FILE);

    // A secondary that arrived during the abandoned shutdown may be waiting
    // without its own request marker. Publish one before reopening consumption
    // so marker absence cannot be mistaken for an acknowledgment.
    request_existing_instance_activation_at(
        &app_data_directory.join(INSTANCE_ACTIVATION_REQUEST_FILE),
    )?;
    discard_instance_shutdown_at(&shutdown_path)
}

pub(crate) fn begin_instance_activation_shutdown() -> std::io::Result<()> {
    begin_instance_activation_shutdown_at(
        &paths::app_data_dir(),
        INSTANCE_ACTIVATION_HANDOFF_POLLS,
        INSTANCE_ACTIVATION_HANDOFF_POLL_INTERVAL,
        std::thread::sleep,
    )
}

pub(crate) fn reopen_instance_activation_after_abandoned_shutdown() -> std::io::Result<()> {
    reopen_instance_activation_after_abandoned_shutdown_at(
        &paths::app_data_dir(),
        INSTANCE_ACTIVATION_HANDOFF_POLLS,
        INSTANCE_ACTIVATION_HANDOFF_POLL_INTERVAL,
        std::thread::sleep,
    )
}

pub(super) fn quarantine_invalid_instance_marker(path: &std::path::Path) -> std::io::Result<()> {
    let file_name = path
        .file_name()
        .and_then(|name| name.to_str())
        .ok_or_else(|| {
            std::io::Error::new(
                std::io::ErrorKind::InvalidInput,
                "instance marker path has no file name",
            )
        })?;
    let nonce = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    for attempt in 0..INSTANCE_ACTIVATION_QUARANTINE_ATTEMPTS {
        let quarantine = path.with_file_name(format!(
            "{file_name}.invalid-{}-{nonce}-{attempt}",
            std::process::id()
        ));
        match std::fs::rename(path, &quarantine) {
            Ok(()) => {
                remove_quarantined_activation_entry(&quarantine);
                return Ok(());
            }
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(()),
            Err(error) => return Err(error),
        }
    }
    Err(std::io::Error::new(
        std::io::ErrorKind::AlreadyExists,
        "could not reserve an instance-marker quarantine path",
    ))
}

pub(super) fn remove_quarantined_activation_entry(path: &std::path::Path) {
    let Ok(metadata) = std::fs::symlink_metadata(path) else {
        return;
    };
    if metadata.file_type().is_file() {
        let _ = std::fs::remove_file(path);
        return;
    }
    if metadata.file_type().is_dir() {
        let _ = std::fs::remove_dir(path);
        return;
    }
    if std::fs::remove_file(path).is_err() {
        let _ = std::fs::remove_dir(path);
    }
}

pub(super) fn report_activation_request_result(
    result: std::io::Result<bool>,
    error_logged: &AtomicBool,
    mut log: impl FnMut(&str),
) -> bool {
    match result {
        Ok(activated) => {
            error_logged.store(false, Ordering::Release);
            activated
        }
        Err(error) => {
            if error_logged
                .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
                .is_ok()
            {
                log(&format!(
                    "existing instance activation request could not be consumed: {error}"
                ));
            }
            false
        }
    }
}

pub(super) fn request_existing_instance_activation_or_acquire_lease(
) -> std::io::Result<InstanceActivationHandoff<exclusive_file_lease::ExclusiveFileLease>> {
    let app_data_directory = paths::app_data_dir();
    publish_existing_instance_activation_request_at(
        &app_data_directory,
        INSTANCE_ACTIVATION_HANDOFF_POLLS,
        INSTANCE_ACTIVATION_HANDOFF_POLL_INTERVAL,
        std::thread::sleep,
    )?;
    complete_existing_instance_activation_handoff_at(
        &app_data_directory,
        INSTANCE_ACTIVATION_HANDOFF_POLLS,
        INSTANCE_ACTIVATION_HANDOFF_POLL_INTERVAL,
        || match acquire_instance_lease_at(&app_data_directory) {
            Ok(lease) => Ok(Some(lease)),
            Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => Ok(None),
            Err(error) => Err(error),
        },
        std::thread::sleep,
    )
}

pub(super) fn consume_existing_instance_activation_request_at(
    app_data_directory: &std::path::Path,
    mut activate: impl FnMut(),
) -> std::io::Result<bool> {
    match try_acquire_instance_activation_handoff_lease_at(app_data_directory)? {
        None => Ok(false),
        Some(_handoff_lease) => {
            if instance_shutdown_pending_at(&app_data_directory.join(INSTANCE_SHUTDOWN_FILE))? {
                Ok(false)
            } else {
                let activated = take_existing_instance_activation_request_at(
                    &app_data_directory.join(INSTANCE_ACTIVATION_REQUEST_FILE),
                )?;
                if activated {
                    activate();
                }
                Ok(activated)
            }
        }
    }
}

pub(super) fn consume_existing_instance_activation_request(app: &tauri::AppHandle) {
    let result = consume_existing_instance_activation_request_at(&paths::app_data_dir(), || {
        live::actions::show_main_window(app);
    });
    report_activation_request_result(
        result,
        &ACTIVATION_REQUEST_ERROR_LOGGED,
        crate::diagnostics::log,
    );
}

pub(super) fn instance_lease_startup_message(error: &std::io::Error) -> String {
    if error.kind() == std::io::ErrorKind::WouldBlock {
        return format!(
            "Yap is already running. Use the existing Yap tray app, or close the other Yap process before trying again.\n\nReason: {error}"
        );
    }
    format!(
        "Yap did not start because it could not establish exclusive access to its application data. Yap stopped before migration and runtime startup. Resolve the access problem before trying again.\n\nReason: {error}"
    )
}

pub(super) fn stop_for_instance_lease_error(error: &std::io::Error) -> ! {
    let message = instance_lease_startup_message(error);

    #[cfg(windows)]
    show_startup_error_dialog(&message);
    #[cfg(not(windows))]
    eprintln!("{message}");

    std::process::exit(1)
}
