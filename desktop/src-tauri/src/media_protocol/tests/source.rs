use std::time::Duration;

use super::{request, TestDirectory};
use crate::media_protocol::{inspect_media_source, open_unchanged_media_source, MediaOwner};

#[test]
fn admitted_source_lease_is_not_retargeted_by_path_replacement() {
    let directory = TestDirectory::new("replacement");
    let path = directory.join("meeting.wav");
    let original = directory.join("original.wav");
    std::fs::write(&path, b"original bytes").unwrap();
    let owner = MediaOwner::with_capacity_for_test(4);
    let admission = owner.admit(&path, 32 * 1024 * 1024).unwrap();
    match std::fs::rename(&path, &original) {
        Ok(()) => std::fs::write(&path, b"replacement bytes").unwrap(),
        Err(error) if cfg!(windows) => {
            assert!(path.is_file(), "lease failure was unexpected: {error}");
        }
        Err(error) => panic!("unexpected replacement failure: {error}"),
    }

    let response = request(&admission.url, "GET", None);
    // Unix rename changes ctime, so the revision check revokes the lease.
    // Windows sharing keeps the original open source stable instead.
    if cfg!(unix) {
        assert_eq!(response.status, 410);
        assert!(response.body.is_empty());
    } else {
        assert_eq!(response.status, 200);
        assert_eq!(response.body, b"original bytes");
    }
    assert_eq!(
        owner.active_admission_count_for_test(),
        usize::from(!cfg!(unix))
    );
}

#[test]
fn removable_source_lease_does_not_block_owned_recording_deletion() {
    let directory = TestDirectory::new("removable-source");
    let path = directory.join("meeting.wav");
    std::fs::write(&path, b"original bytes").unwrap();
    let owner = MediaOwner::with_capacity_for_test(4);
    let admission = owner
        .admit_with_path_removal(&path, 32 * 1024 * 1024)
        .unwrap();

    crate::audio::recording::remove_regular_artifact(path.parent().unwrap(), "meeting.wav")
        .unwrap();
    assert!(!path.exists());

    let response = request(&admission.url, "GET", None);
    if cfg!(unix) {
        assert_eq!(response.status, 410);
        assert!(response.body.is_empty());
    } else {
        assert_eq!(response.status, 200);
        assert_eq!(response.body, b"original bytes");
    }
}

#[test]
fn preprocessing_opens_the_exact_validated_source_without_following_replacements() {
    let directory = TestDirectory::new("preprocessing-source");
    let path = directory.join("meeting.wav");
    let original = directory.join("original.wav");
    std::fs::write(&path, b"original bytes").unwrap();
    let fingerprint = inspect_media_source(&path).unwrap();

    let opened = open_unchanged_media_source(&path, &fingerprint).unwrap();
    assert_eq!(opened.metadata().unwrap().len(), 14);
    drop(opened);

    std::fs::rename(&path, &original).unwrap();
    std::fs::write(&path, b"replacement bytes").unwrap();
    assert!(open_unchanged_media_source(&path, &fingerprint).is_err());
}

#[test]
fn preprocessing_rejects_same_identity_same_length_rewrites() {
    let directory = TestDirectory::new("preprocessing-rewrite");
    let path = directory.join("meeting.wav");
    std::fs::write(&path, b"first bytes").unwrap();
    let fingerprint = inspect_media_source(&path).unwrap();

    std::thread::sleep(Duration::from_millis(10));
    std::fs::write(&path, b"other bytes").unwrap();

    assert!(open_unchanged_media_source(&path, &fingerprint).is_err());
}

#[cfg(unix)]
#[test]
fn native_source_admission_refuses_a_fifo_without_waiting_for_a_writer() {
    use std::os::unix::{
        ffi::OsStrExt,
        fs::{FileTypeExt, OpenOptionsExt},
    };
    let directory = TestDirectory::new("source-fifo");
    let path = directory.join("meeting.flac");
    let name = std::ffi::CString::new(path.as_os_str().as_bytes()).unwrap();
    assert_eq!(unsafe { libc::mkfifo(name.as_ptr(), 0o600) }, 0);
    let source = path.clone();
    let (send, receive) = std::sync::mpsc::channel();
    let reader = std::thread::spawn(move || {
        send.send(inspect_media_source(&source).is_err()).unwrap();
    });
    let result = receive.recv_timeout(Duration::from_secs(1));
    let writer = result.is_err().then(|| {
        std::fs::OpenOptions::new()
            .read(true)
            .write(true)
            .custom_flags(libc::O_NONBLOCK)
            .open(&path)
            .unwrap()
    });
    reader.join().unwrap();
    drop(writer);
    assert!(result.expect("native admission must not wait for a FIFO writer"));
    assert!(std::fs::symlink_metadata(path)
        .unwrap()
        .file_type()
        .is_fifo());
}
